"""Opt-in Discord PCM transport inside the existing speech model owner.

Discord's adapter supplies per-member PCM, never mixed channel audio. Each
member has independent Pipecat VAD/turn/decoder state; all encoder/decoder
inference shares the desktop STT lock and loaded model. Only addressed final
text crosses this owner-only socket. No microphone, model or conversation owner
is created here.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import contextlib
import json
import math
import os
import re
import socket
import stat
import struct
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

import torch

from pipecat.transports.base_input import BaseInputTransport

from . import worker as speech

MAX_LINE = 65_536
MAX_STREAMS = 8
MAX_PCM = 16_384
PCM_FRAME = 640  # 20 ms, mono s16/16 kHz.
MAX_QUEUED_FRAMES = 50  # One second per member, including terminal silence.
MAX_COMMAND_CHARS = 2_000
TERMINAL_SILENCE_SECS = 4.0  # Covers Smart Turn's three-second pending bound.
PLAYBACK_LEAD_SECS = 0.4  # Fill the transport's unchanged 400 ms Opus prebuffer promptly.
_PRINCIPAL_FIELDS = ("guild_id", "channel_id", "member_id")
_ID = re.compile(r"[0-9]{1,20}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{1,96}\Z")
WAKE_WORD = "Bard"
_TIMING_FIELDS = ("asr_timing_count", "asr_native_last_ms", "asr_native_max_ms",
                  "asr_wait_last_ms", "asr_wait_max_ms", "decoder_lock_wait_ms", "decoder_context_ms")


def _timing_ms(seconds):
    return round(min(max(0.0, seconds), 1_000_000) * 1000)


def _input_timing(value, wake_ns):
    """Project existing addressed-turn clocks only; no transcript or analyzer data."""
    allowed = {"speech_onset", "first_partial", "last_voiced", "end_of_turn", "speech_final"}
    if (not isinstance(value, dict) or set(value) != {"speech_sequence", "stages"}
            or type(value["speech_sequence"]) is not int or not 0 < value["speech_sequence"] <= 1_000_000_000
            or not isinstance(value["stages"], list) or not 1 <= len(value["stages"]) <= 5):
        return None
    now = time.monotonic_ns()
    stages, seen = [], set()
    for row in value["stages"]:
        if (not isinstance(row, dict) or set(row) != {"stage", "monotonic_ns"}
                or not isinstance(row["stage"], str) or row["stage"] not in allowed or row["stage"] in seen
                or type(row["monotonic_ns"]) is not int
                or not max(1, now - 120_000_000_000) <= row["monotonic_ns"] <= now):
            return None
        seen.add(row["stage"])
        stages.append({"stage": row["stage"], "monotonic_ms": row["monotonic_ns"] / 1_000_000})
    if "speech_final" not in seen:
        return None
    result = {"speech_sequence": value["speech_sequence"], "stages": stages}
    if type(wake_ns) is int and max(1, now - 120_000_000_000) <= wake_ns <= now:
        result["wake_monotonic_ms"] = wake_ns / 1_000_000
    return result


def _principal(message: dict) -> tuple[str, str, str]:
    values = tuple(message.get(key) for key in _PRINCIPAL_FIELDS)
    if not all(isinstance(value, str) and _ID.fullmatch(value) for value in values):
        raise ValueError("invalid_principal")
    return values


def _token(value) -> str:
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise ValueError("invalid_identity")
    return value


def _decoder_context(source, decoding):
    """Fork only the pinned legacy decoder's explicit stream state.

    The upstream ``stream_id`` argument is unused. Its transcribe/reset methods
    mutate exactly the feature buffer, three encoder caches, RNNT hypotheses and
    transcript clock below. We share weights/tokenizer/configuration, never any
    of these mutable objects. Caller holds the desktop STT inference lock.
    """
    shared = {
        "model", "eou_string", "eob_string", "device", "att_context_size", "decoder_type",
        "chunk_size", "shift_size", "left_chunks", "asr_model", "tokenizer", "use_amp",
        "pad_and_drop_preencoded", "blank_id", "chunk_size_in_secs", "model_chunk_size",
        "pre_encode_cache_size", "pre_encode_cache_size_in_secs", "tokens_per_frame", "buffer_size_in_secs",
        "phrase_decoding",
    }
    isolated = {"_audio_buffer", "_cache_last_channel", "_cache_last_time",
                "_cache_last_channel_len", "_previous_hypotheses", "_last_transcript_timestamp"}
    if type(source) is not speech.StreamingASR or set(vars(source)) != shared | isolated:
        # An upstream decoder adding stream state needs review before sharing.
        raise RuntimeError("unsupported_discord_asr_backend")
    result = object.__new__(speech.StreamingASR)
    result.__dict__.update(vars(source))
    result.phrase_decoding = decoding
    result._audio_buffer = source.new_feature_buffer()
    result._reset_cache()
    result._previous_hypotheses = result._get_blank_hypothesis()
    result._last_transcript_timestamp = time.time()
    return result


def _warm_name_decoder(source):
    """Warm shared encoder/decoder graphs before ingress; discard stream state."""
    # Discord boosts only its own wake name, never the desktop phrase list.
    decoding = speech.phrase_decoding(source, [WAKE_WORD, WAKE_WORD.lower()])
    # desktop_asr() attached and captured the shared encoder's graphs.
    encoder = source.asr_model.encoder
    encoder_graphs = encoder._stream_step_cuda_graphs or encoder.set_streaming_cuda_graphs()
    context = _decoder_context(source, decoding)
    with torch.inference_mode():
        encoded = torch.zeros(
            (1, source.asr_model.joint.encoder_hidden, source.tokens_per_frame),
            device=source.device, dtype=next(source.asr_model.joint.parameters()).dtype,
        )
        encoded_len = torch.tensor([source.tokens_per_frame], device=source.device)
        previous = context._get_blank_hypothesis()
        # Exercise first-chunk and continuation decoding directly: synthetic
        # silence must not let an EOU reset skip the continuation warmup.
        for _ in range(2):
            previous = context._get_best_hypothesis(encoded, encoded_len, previous)
        # Warm actual feature extraction and cache-aware encoder steps too.
        # Native capture follows three eager steps; include a later replay.
        pcm = bytes(round(speech.SAMPLE_RATE * source.chunk_size_in_secs) * 2)
        for _ in range(encoder_graphs.warmup_steps + 2):
            context.transcribe(pcm)
        context.transcribe_final(pcm * speech.final_batches(context))
        torch.cuda.synchronize(source.device)
    return decoding


class _MemberSTT(speech.UtteranceNeMoSTTService):
    def __init__(self, stream, source, decoder):
        self.stream = stream
        self._shared_decoder = decoder
        super().__init__(model=source._model_name, device=source._device,
                         sample_rate=speech.SAMPLE_RATE, params=source._params,
                         has_turn_taking=False, backend="legacy",
                         decoder_type=source._decoder_type, audio_passthrough=True,
                         # Member decoders are fresh/bounded by packet lifetime.
                         # Preserve words decoded before a late VAD onset.
                         reset_on_vad_onset=False, enable_direct_mode=True)
        self._model_lock = source._model_lock
        self.utterance_pcm_bytes = 0
        self.audio_frames = 0
        self.transcription_frames = 0
        self.vad_starts = 0
        self.vad_stops = 0
        self._terminal_frames = 0
        self.skipped_terminal_frames = 0
        self.asr_timing_count = 0
        self.asr_native_last_ms = self.asr_native_max_ms = 0
        self.asr_wait_last_ms = self.asr_wait_max_ms = 0

    async def _transcribe(self, audio):
        started = time.perf_counter()
        # Keep the upstream lock and cancellation/native-work drain unchanged.
        result = await super()._transcribe(audio)
        elapsed = time.perf_counter() - started
        native = result.processing_time
        if isinstance(native, (int, float)) and math.isfinite(native) and native >= 0:
            self.asr_timing_count = min(self.asr_timing_count + 1, 1_000_000_000)
            self.asr_native_last_ms = _timing_ms(native)
            self.asr_native_max_ms = max(self.asr_native_max_ms, self.asr_native_last_ms)
            # Includes lock, thread dispatch and event-loop scheduling, not only
            # lock contention. Native ASR supplies its own processing duration.
            self.asr_wait_last_ms = _timing_ms(elapsed - native)
            self.asr_wait_max_ms = max(self.asr_wait_max_ms, self.asr_wait_last_ms)
        return result

    async def process_audio_frame(self, frame, direction):
        if not self.stream.server.listening(self.stream):
            return
        terminal = frame.metadata.get("discord_terminal_silence", False)
        if terminal:
            self._terminal_frames += 1
            # Input VAD/Smart Turn still sees the whole endpoint window. ASR
            # needs only its existing tail, ending on a complete decoder batch.
            # Do not keep competing with real speakers to transcribe zeros.
            if self._terminal_frames > round(speech.ASR_TAIL_SECS / 0.02) and not self.audio_buffer:
                self.skipped_terminal_frames = min(self.skipped_terminal_frames + 1, 1_000_000_000)
                return
        else:
            self._terminal_frames = 0
        self.audio_frames = min(self.audio_frames + 1, 1_000_000_000)
        if not terminal:
            self.utterance_pcm_bytes += len(frame.audio)
        await super().process_audio_frame(frame, direction)

    async def _handle_transcription(self, transcript, is_final, language=None):
        if transcript.strip():
            self.transcription_frames = min(self.transcription_frames + 1, 1_000_000_000)
        await super()._handle_transcription(transcript, is_final, language)
        if is_final:
            self.utterance_pcm_bytes = 0

    async def process_frame(self, frame, direction):
        if direction is speech.FrameDirection.DOWNSTREAM:
            if isinstance(frame, speech.VADUserStartedSpeakingFrame):
                self.vad_starts = min(self.vad_starts + 1, 1_000_000_000)
            elif isinstance(frame, speech.VADUserStoppedSpeakingFrame):
                self.vad_stops = min(self.vad_stops + 1, 1_000_000_000)
                if not self.stream.server.listening(self.stream):
                    frame.metadata["obsidience_asr_tail_frames"] = 0
        await super().process_frame(frame, direction)
        if isinstance(frame, speech.VADUserStoppedSpeakingFrame):
            self.utterance_pcm_bytes = 0

    def _load_model(self):
        # Do not call NeMo's constructor or reload/change a shared model.
        self._model = self._shared_decoder


class _MemberInput(speech.NeMoLocalAudioInputTransport):
    """Use existing input endpoint policy with supplied, bounded PCM only."""
    def __init__(self, params):
        # Deliberately bypass LocalAudioInputTransport: no PortAudio stream.
        BaseInputTransport.__init__(self, params, enable_direct_mode=True)
        self._last_voiced_ns = None
        self._held_stop = None
        self._capture_active = False

    async def start(self, frame):
        await BaseInputTransport.start(self, frame)
        await self.set_transport_ready(frame)

    def _create_audio_task(self):
        if self._audio_task is None:
            self._audio_in_queue = asyncio.Queue(maxsize=MAX_QUEUED_FRAMES)
            self._audio_task = self.create_task(self._audio_task_handler())

    async def cleanup(self):
        await BaseInputTransport.cleanup(self)

    async def push_audio_frame(self, frame):
        # No desktop metering events and no unbounded upstream audio queue.
        if not self._paused:
            self._audio_in_queue.put_nowait(frame)

    async def _handle_user_interruption(self, vad_state, emulated=False):
        self._user_speaking = vad_state == speech.VADState.SPEAKING
        if vad_state == speech.VADState.QUIET and not emulated and self._held_stop is not None:
            await self.push_frame(self._held_stop)


class _MemberTurn(speech.ObsidienceNeMoTurnTakingService):
    def __init__(self, stream, **kwargs):
        self.stream = stream
        super().__init__(event_sink=stream.event, **kwargs)

    async def _open_wake(self, text, *, cue_name="ready"):
        if not self.stream.server.claim(self.stream):
            await self._reset_wake_scan(segment_start=False)
            return ""
        return await super()._open_wake(text, cue_name=cue_name)

    def turn_short_reply(self):
        # Only a whole addressed command can shorten a judged, quiet pause.
        # Final ASR tail decoding and the sole final-text admission still run.
        if not self._wake_open:
            return False
        if super().turn_short_reply():
            return True
        text = " ".join(self._user_speaking_buffer.casefold().split()).rstrip(".!?")
        if len(text) > 100 or re.fullmatch(r"[a-z ]+", text) is None:
            return False
        return re.fullmatch(
            r"(?:please )?(?:(?:pause|resume|unpause|stop(?: playing)?)(?: (?:it|that|(?:the )?(?:music|audio|playback|song)))?"
            r"|(?:keep|continue) playing(?: (?:the )?music)?)(?: please)?", text) is not None

    async def _handle_transcription(self, frame, direction):
        if self.stream.probe_kind is not None:
            # A fresh explicit synthetic fixture or authorized real-speech
            # calibration enters this finite lane, never an Agent turn.
            if self.stream.server.current(self.stream) and time.monotonic() < self.stream.probe_deadline:
                self.stream.probe_text = (self.stream.probe_text + frame.text)[:512]
            return
        if self.stream.server.listening(self.stream):
            await super()._handle_transcription(frame, direction)


class _FinalText(speech.FrameProcessor):
    def __init__(self, stream):
        super().__init__(enable_direct_mode=True)
        self.stream = stream

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, speech.TranscriptionFrame):
            self.stream.final(frame.text, frame.metadata.get("obsidience_speech_timing"))
        elif isinstance(frame, speech.ErrorFrame):
            self.stream.fail("asr_failed")
        else:
            await self.push_frame(frame, direction)


@dataclass
class _Owner:
    principal: tuple[str, str, str]
    request_id: str
    phase: str = "listening"
    question: bool = False
    deadline: float = 0.0


class _Member:
    def __init__(self, server, principal, decoder, *, synthetic_probe=False, calibration_probe=False):
        self.server, self.principal = server, principal
        self.generation = server.generation
        self.last_input = time.monotonic()
        self.last_silence = self.last_input
        self.synthetic_probe = synthetic_probe
        self.probe_kind = ("synthetic_probe" if synthetic_probe else
                           "calibration_probe" if calibration_probe else None)
        self.probe_deadline = self.last_input + 30 if self.probe_kind is not None else 0
        self.probe_text = ""
        self.probe_pcm_bytes = 0
        self.remainder = bytearray()
        self.closed = False
        self.ready = asyncio.Event()
        self.received_pcm_frames = 0
        self.terminal_pcm_frames = 0
        self.queue_high_water = 0
        self.decoder_lock_wait_ms = self.decoder_context_ms = 0
        self.wake_rejected = {"possessive": 0, "mid_sentence": 0}
        self.wake_monotonic_ns = None
        self.stt = _MemberSTT(self, server.stt, decoder)
        turn_analyzer = speech.smart_turn_analyzer(
            lambda: self.turn.turn_pending(), lambda: self.turn.turn_short_reply(),
            model_path=speech.SMART_TURN_MODEL,
        )
        self.input = _MemberInput(speech.LocalAudioTransportParams(
            audio_in_enabled=True, audio_in_sample_rate=speech.SAMPLE_RATE,
            vad_analyzer=speech.SileroVADAnalyzer(
                sample_rate=speech.SAMPLE_RATE,
                params=speech.VADParams(confidence=0.2, start_secs=0.10,
                                       stop_secs=(speech.SMART_TURN_VAD_STOP_SECS
                                                  if turn_analyzer else speech.TRANSCRIPT_IDLE_SECS),
                                       min_volume=0.0)),
            turn_analyzer=turn_analyzer,
        ))
        self.turn = _MemberTurn(self, timing=speech.SpeechInputTiming(), mode="wake",
                                wake_word=WAKE_WORD, smart_turn=turn_analyzer is not None,
                                semantic_turns=False, use_vad=True, use_diar=False,
                                max_buffer_size=2, bot_stop_delay=0.5)
        self.task = speech.PipelineTask(
            speech.Pipeline([self.input, self.stt, self.turn, _FinalText(self)]),
            params=speech.PipelineParams(allow_interruptions=True,
                                        audio_in_sample_rate=speech.SAMPLE_RATE,
                                        audio_out_sample_rate=speech.TTS_SAMPLE_RATE,
                                        enable_metrics=False, enable_usage_metrics=False,
                                        idle_timeout=None),
            idle_timeout_secs=None, cancel_on_idle_timeout=False,
            enable_tracing=False, enable_turn_tracking=False,
        )

        @self.task.event_handler("on_pipeline_started")
        async def started(task, frame):
            self.ready.set()

        @self.task.event_handler("on_pipeline_error")
        async def failed(task, frame):
            self.fail("asr_failed")

        self.runner = asyncio.create_task(
            speech.PipelineRunner(handle_sigint=False, handle_sigterm=False).run(self.task),
            name="discord-member-speech",
        )

    def event(self, kind, **payload):
        if not self.server.current(self):
            return
        owner = self.server.owner(self.principal)
        if kind == "wake_rejected":
            reason = payload.get("reason")
            if reason in self.wake_rejected:
                self.wake_rejected[reason] = min(self.wake_rejected[reason] + 1, 1_000_000_000)
        if kind == "wake_detected" and owner is not None and owner.principal == self.principal:
            self.wake_monotonic_ns = time.monotonic_ns()
            self.server.emit("wake", self.principal, request_id=owner.request_id,
                             cue_name=self.turn._wake_cue_name)
        elif kind == "wake_idle" and owner is not None and owner.phase == "listening":
            self.server.emit("cue", self.principal, request_id=owner.request_id, name="cancel")
            self.server.release(self.principal)
        # Ambient words and partial transcripts never leave the speech owner.

    def timing_diagnostics(self):
        return {key: getattr(self.stt, key) if key.startswith("asr_") else getattr(self, key)
                for key in _TIMING_FIELDS}

    def diagnostics(self):
        # Default diagnostics never includes transcript, PCM, analyzer output
        # or exception text. Probe inspection is a separate one-shot opt-in.
        audio_task = self.input._audio_task
        return {
            "available": True,
            "received_pcm_frames": self.received_pcm_frames,
            "terminal_pcm_frames": self.terminal_pcm_frames,
            "skipped_terminal_frames": self.stt.skipped_terminal_frames,
            "stt_audio_frames": self.stt.audio_frames,
            "stt_transcription_frames": self.stt.transcription_frames,
            "vad_starts": self.stt.vad_starts,
            "vad_stops": self.stt.vad_stops,
            "wake_rejected": dict(self.wake_rejected),
            "input_task_done": audio_task is not None and audio_task.done(),
            "input_task_failed": (audio_task is not None and audio_task.done()
                                  and not audio_task.cancelled() and audio_task.exception() is not None),
            "runner_done": self.runner.done(),
            "queue_depth": self.input._audio_in_queue.qsize() if audio_task is not None else 0,
            "queue_high_water": self.queue_high_water,
            **self.timing_diagnostics(),
        }

    def final(self, text, timing=None):
        owner = self.server.owner(self.principal)
        text = " ".join(text.split())
        if (not self.server.current(self) or owner is None or owner.principal != self.principal
                or owner.phase != "listening" or not text):
            return
        if len(text) > MAX_COMMAND_CHARS:
            self.fail("utterance_limit")
            return
        owner.phase, owner.deadline = "waiting", time.monotonic() + 120
        clocks = _input_timing(timing, self.wake_monotonic_ns)
        self.server.emit("transcript", self.principal, request_id=owner.request_id, text=text,
                         **({"input_timing": clocks} if clocks is not None else {}))

    def fail(self, code):
        if self.server.current(self):
            if self.principal not in self.server.failures and len(self.server.failures) >= 64:
                self.server.failures.pop(next(iter(self.server.failures)))
            prior = self.server.failures.get(self.principal, {})
            self.server.failures[self.principal] = {
                "last_error": code,
                "error_count": min(prior.get("error_count", 0) + 1, 1_000_000_000),
                "failed_queue_depth": self.input._audio_in_queue.qsize(),
                **{"failed_" + key: value for key, value in self.timing_diagnostics().items()},
            }
            owner = self.server.owner(self.principal)
            self.server.emit("error", self.principal, code=code,
                             **({"request_id": owner.request_id} if owner else {}))
            self.closed = True
            self.server.block(self.principal)
            self.server.schedule_drop(self.principal)

    async def audio(self, pcm, *, terminal=False):
        if self.closed or not self.server.listening(self):
            return
        if not terminal:
            if self.probe_kind is not None:
                self.probe_pcm_bytes += len(pcm)
                if self.probe_pcm_bytes > 320_000 or time.monotonic() >= self.probe_deadline:
                    self.probe_text = ""
                    self.fail(self.probe_kind + "_limit")
                    return
            self.last_input = self.last_silence = time.monotonic()
            if self.stt.utterance_pcm_bytes > 35 * speech.SAMPLE_RATE * 2:
                # RNNT hypotheses grow across a continuous utterance. Bound
                # decoded audio, not quiet wall time between Discord packets.
                owner = self.server.owner(self.principal)
                if owner is None or owner.principal != self.principal:
                    # Ambient conversation can outlive one decoder window.
                    # Retire its state without the failure/silence latch; the
                    # next packet creates a fresh stream with shared weights.
                    await self.server._drop(self.principal)
                else:
                    self.fail("utterance_limit")
                return
        self.remainder.extend(pcm)
        while len(self.remainder) >= PCM_FRAME:
            piece = bytes(self.remainder[:PCM_FRAME])
            del self.remainder[:PCM_FRAME]
            try:
                frame = speech.InputAudioRawFrame(piece, speech.SAMPLE_RATE, 1)
                frame.metadata["discord_terminal_silence"] = terminal
                await self.input.push_audio_frame(frame)
                self.queue_high_water = max(self.queue_high_water, self.input._audio_in_queue.qsize())
                if terminal:
                    self.terminal_pcm_frames = min(self.terminal_pcm_frames + 1, 1_000_000_000)
                else:
                    self.received_pcm_frames = min(self.received_pcm_frames + 1, 1_000_000_000)
            except asyncio.QueueFull:
                self.fail("audio_backpressure")
                self.remainder.clear()
                return

    async def close(self):
        self.closed = True
        self.probe_text = ""
        self.remainder.clear()
        await self.task.cancel(reason="Discord member disconnected")
        await asyncio.gather(self.runner, return_exceptions=True)
        # These upstream analyzers own one CPU executor each, outside Pipecat's
        # frame task manager. Join them when relinquishing the member stream.
        for analyzer in (self.input.vad_analyzer, self.input.turn_analyzer):
            executor = getattr(analyzer, "_executor", None)
            if executor is not None:
                await asyncio.to_thread(executor.shutdown, wait=True, cancel_futures=True)


class DiscordSpeechServer:
    def __init__(self, path: Path, stt, tts):
        self.path, self.stt, self.tts = path, stt, tts
        self.generation = ""
        self.members: dict[tuple[str, str, str], _Member] = {}
        self.owners: dict[tuple[str, str], _Owner] = {}
        self.server = None
        self.writer = None
        self.connection = None
        self.outgoing = None
        self.sender = None
        self.maintenance = None
        self.speaking = None
        self.speaking_owner = None
        self.dropping: dict[tuple, asyncio.Task] = {}
        self.blocked: dict[tuple, float] = {}
        self.failures: dict[tuple, dict] = {}
        self._inode = None
        self._closed = False
        self._ownership_active = False
        self._name_decoding = None
        self.encoder_cuda_graphs = 0

    async def start(self):
        if not self.path.is_absolute() or self.path.parent.stat().st_uid != os.getuid():
            raise ValueError("Discord speech socket requires an owner runtime directory")
        if stat.S_IMODE(self.path.parent.stat().st_mode) & 0o077:
            raise ValueError("Discord speech socket directory must be owner-only")
        if self.path.is_symlink():
            raise RuntimeError("Discord speech socket is a symlink")
        if self.path.exists():
            info = self.path.lstat()
            if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                raise RuntimeError("Discord speech socket path is occupied")
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                probe.settimeout(0.2)
                result = probe.connect_ex(str(self.path))
            finally:
                probe.close()
            import errno
            if result != errno.ECONNREFUSED:
                raise RuntimeError("Discord speech socket already has an owner")
            self.path.unlink()
        async with self.stt._model_lock:
            warmup = asyncio.create_task(asyncio.to_thread(_warm_name_decoder, self.stt._model))
            try:
                self._name_decoding = await asyncio.shield(warmup)
            except asyncio.CancelledError:
                # Match STT's native-work drain: cancellation cannot release
                # the shared weights while warmup still owns CUDA work.
                while not warmup.done():
                    try:
                        await asyncio.shield(warmup)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                if not warmup.cancelled():
                    warmup.exception()
                raise
        helper = self.stt._model.asr_model.encoder._stream_step_cuda_graphs
        self.encoder_cuda_graphs = len(helper._graphs) if helper is not None else 0
        self.server = await asyncio.start_unix_server(self._accept, path=str(self.path), limit=MAX_LINE)
        self.path.chmod(0o600)
        self._inode = self.path.lstat().st_ino
        self.maintenance = asyncio.create_task(self._maintain(), name="discord-speech-lifecycle")

    def owner(self, principal):
        return self.owners.get(principal[:2])

    def current(self, member):
        return (not member.closed and member.generation == self.generation
                and self.members.get(member.principal) is member)

    def listening(self, member):
        owner = self.owner(member.principal)
        # Keep unaddressed members in their own wake scanner during an open
        # command/follow-up window. Final text still requires its exact owner;
        # only an accepted explicit wake may transfer channel ownership.
        return self.current(member) and (owner is None or owner.phase == "listening")

    def claim(self, member):
        if not self.listening(member):
            return False
        owner = self.owner(member.principal)
        if owner is None or owner.principal != member.principal:
            self.owners[member.principal[:2]] = _Owner(
                member.principal, uuid.uuid4().hex, deadline=time.monotonic() + 35)
            # Another participant's earlier unaddressed recognition cannot
            # survive this invoker's exclusive command/reply window.
            for principal in tuple(self.members):
                if principal[:2] == member.principal[:2] and principal != member.principal:
                    self.schedule_drop(principal)
        self._publish_ownership()
        return True

    def _publish_ownership(self):
        """Only occupancy crosses the worker event pipe; no member or text data."""
        active = bool(self.owners)
        if active != self._ownership_active:
            self._ownership_active = active
            speech.emit("discord_ownership", active=active)

    def block(self, principal):
        if len(self.blocked) >= 64:
            self.blocked.pop(min(self.blocked, key=self.blocked.get))
        self.blocked[principal] = time.monotonic()

    def release(self, principal):
        owner = self.owner(principal)
        if owner is not None and owner.principal == principal:
            self.owners.pop(principal[:2], None)
            self._publish_ownership()

    def emit(self, kind, principal, **payload):
        if self.outgoing is None:
            return
        message = {"type": kind, "generation": self.generation,
                   **dict(zip(_PRINCIPAL_FIELDS, principal)), **payload}
        try:
            self.outgoing.put_nowait(message)
        except asyncio.QueueFull:
            # A blocked consumer cannot keep receiving or act on delayed speech.
            if self.writer is not None:
                self.writer.close()

    async def send(self, kind, principal, **payload):
        if self.outgoing is None:
            raise ConnectionError("Discord transport disconnected")
        message = {"type": kind, "generation": self.generation,
                   **dict(zip(_PRINCIPAL_FIELDS, principal)), **payload}
        await asyncio.wait_for(self.outgoing.put(message), timeout=2)

    async def _write(self, writer, outgoing):
        while True:
            message = await outgoing.get()
            data = json.dumps(message, separators=(",", ":"), allow_nan=False).encode() + b"\n"
            if len(data) > MAX_LINE:
                raise ValueError("Discord speech output exceeds frame bound")
            writer.write(data)
            await asyncio.wait_for(writer.drain(), timeout=2)

    async def _accept(self, reader, writer):
        connection = asyncio.current_task()
        peer = writer.get_extra_info("socket").getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        if struct.unpack("3i", peer)[1] != os.getuid() or self.connection is not None or self._closed:
            writer.close()
            await writer.wait_closed()
            return
        self.connection, self.writer = connection, writer
        self.outgoing = asyncio.Queue(maxsize=32)
        self.sender = asyncio.create_task(self._write(writer, self.outgoing), name="discord-speech-send")
        self.sender.add_done_callback(lambda task: writer.close() if not task.cancelled() else None)
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                if len(line) > MAX_LINE:
                    raise ValueError("Discord speech input exceeds frame bound")
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError("Discord speech input must be an object")
                await self._message(message)
                if message.get("type") == "audio":
                    # Buffered socket reads can otherwise monopolize the loop
                    # and fill a member queue before its audio task can run.
                    await asyncio.sleep(0)
        except (ValueError, RuntimeError, OSError, TimeoutError, binascii.Error):
            pass  # No raw input, text or exception payload enters diagnostics.
        finally:
            await self._reset()
            self.generation = ""
            self.sender.cancel()
            with contextlib.suppress(asyncio.CancelledError, ValueError, OSError, TimeoutError):
                await self.sender
            self.sender = self.outgoing = None
            self.writer = self.connection = None
            writer.close()
            with contextlib.suppress(OSError):
                await writer.wait_closed()

    async def _message(self, message):
        kind = message.get("type")
        generation = _token(message.get("generation"))
        if kind == "reset":
            if generation != self.generation or not any(key in message for key in _PRINCIPAL_FIELDS):
                await self._reset()
                self.generation = generation
            else:
                await self._drop(_principal(message))
            return
        if generation != self.generation:
            raise ValueError("Discord speech generation is stale")
        principal = _principal(message)
        if kind == "diagnostics":
            member = self.members.get(principal)
            result = member.diagnostics() if member is not None else {"available": False}
            result.update(self.failures.get(principal, {}))
            result["blocked"] = (principal in self.blocked
                                 and time.monotonic() - self.blocked[principal] < speech.TRANSCRIPT_IDLE_SECS)
            calibration_probe = message.get("calibration_probe", False)
            if type(calibration_probe) is not bool or (calibration_probe and message.get("synthetic_probe") is True):
                raise ValueError("Invalid calibration probe flag")
            if calibration_probe:
                result["request_id"] = _token(message.get("request_id"))
            inspect_kind = ("calibration_probe" if calibration_probe else
                            "synthetic_probe" if message.get("synthetic_probe") is True else None)
            matching_probe = (inspect_kind is not None and member is not None
                              and member.probe_kind == inspect_kind)
            if inspect_kind is not None:
                if matching_probe and time.monotonic() < member.probe_deadline:
                    result[inspect_kind + "_text"] = member.probe_text
                    member.probe_text = ""
                else:
                    result["code"] = inspect_kind + "_unavailable"
            self.emit("diagnostics", principal, **result)
            if matching_probe:
                await self._drop(principal)
        elif kind == "audio":
            if (message.get("sample_rate", 16000) != 16000
                    or message.get("channels", 1) != 1 or message.get("format", "s16le") != "s16le"):
                raise ValueError("Discord input requires mono s16le/16000")
            encoded = message.get("pcm")
            if not isinstance(encoded, str) or len(encoded) > (MAX_PCM * 4 // 3 + 4):
                raise ValueError("Discord PCM exceeds frame bound")
            pcm = base64.b64decode(encoded, validate=True)
            if not pcm or len(pcm) > MAX_PCM or len(pcm) % 2:
                raise ValueError("Invalid Discord PCM")
            blocked_at = self.blocked.get(principal)
            if (blocked_at is not None
                    and time.monotonic() - blocked_at < speech.TRANSCRIPT_IDLE_SECS):
                # Cooldown is anchored to the failure, not refreshed forever
                # by an always-open microphone's discarded packets.
                return
            owner = self.owner(principal)
            if owner is not None and owner.phase != "listening":
                return
            if principal in self.dropping:
                return
            member = self.members.get(principal)
            synthetic_probe = message.get("synthetic_probe", False)
            if type(synthetic_probe) is not bool:
                raise ValueError("Invalid synthetic probe flag")
            calibration_probe = message.get("calibration_probe", False)
            if type(calibration_probe) is not bool or (synthetic_probe and calibration_probe):
                raise ValueError("Invalid calibration probe flag")
            probe_kind = ("synthetic_probe" if synthetic_probe else
                          "calibration_probe" if calibration_probe else None)
            if member is not None and member.probe_kind != probe_kind:
                self.emit("error", principal, code=(probe_kind or member.probe_kind) + "_requires_fresh_stream")
                return
            if member is None:
                if len(self.members) >= MAX_STREAMS:
                    self.emit("error", principal, code="stream_capacity")
                    return
                decoder_wait_started = time.perf_counter()
                async with self.stt._model_lock:
                    decoder_started = time.perf_counter()
                    decoder = _decoder_context(self.stt._model, self._name_decoding)
                    decoder_finished = time.perf_counter()
                member = _Member(self, principal, decoder, synthetic_probe=synthetic_probe,
                                 calibration_probe=calibration_probe)
                member.decoder_lock_wait_ms = _timing_ms(decoder_started - decoder_wait_started)
                member.decoder_context_ms = _timing_ms(decoder_finished - decoder_started)
                if blocked_at is not None:
                    # Recovery can begin mid-sentence. Require an explicit
                    # greeting or a later speech boundary before a bare name.
                    member.turn._wake_address = None
                    self.blocked.pop(principal, None)
                self.members[principal] = member
                await asyncio.wait_for(member.ready.wait(), timeout=5)
            await member.audio(pcm)
        elif kind == "speak":
            request_id = _token(message.get("request_id"))
            text = message.get("text")
            if not isinstance(text, str) or not text.strip() or len(text) > 4_000:
                raise ValueError("Invalid Discord reply")
            owner = self.owner(principal)
            if owner is None and message.get("source") == "owner":
                owner = _Owner(principal, request_id, phase="waiting", deadline=time.monotonic() + 120)
                self.owners[principal[:2]] = owner
                self._publish_ownership()
            if (owner is None or owner.principal != principal or owner.request_id != request_id
                    or owner.phase != "waiting" or self.speaking is not None):
                self.emit("error", principal, request_id=request_id, code="reply_not_current")
                return
            owner.phase = "speaking"
            owner.question = speech._QUESTION_END.search(text.strip()) is not None
            self.speaking_owner = owner
            self.speaking = asyncio.create_task(self._speak(owner, text), name="discord-speech-reply")
        elif kind == "played":
            owner = self.owner(principal)
            if (owner is None or owner.principal != principal or owner.phase != "draining"
                    or owner.request_id != _token(message.get("request_id"))):
                return
            member = self.members.get(principal)
            if owner.question and member is not None and self.current(member):
                # Transfer reply ownership to its native follow-up without
                # publishing an idle edge between release and claim.
                self.owners.pop(principal[:2], None)
                try:
                    await member.turn._open_wake("", cue_name="follow_up")
                finally:
                    self._publish_ownership()
            else:
                self.emit("cue", principal, request_id=owner.request_id, name="complete")
                self.release(principal)
        elif kind == "cancel":
            owner = self.owner(principal)
            request_id = message.get("request_id")
            if request_id is not None and (
                    owner is None or owner.principal != principal or owner.request_id != request_id):
                return
            await self._drop(principal)
        else:
            raise ValueError("Unknown Discord speech message")

    async def _speak(self, owner, text):
        principal, generation = owner.principal, self.generation
        try:
            first_write = None
            samples = 0
            async with contextlib.aclosing(self.tts.external_pcm(text)) as pcm_stream:
                async for pcm in pcm_stream:
                    for offset in range(0, len(pcm), 9_600):
                        if self.generation != generation or self.owner(principal) is not owner:
                            return
                        chunk = pcm[offset:offset + 9_600]
                        if first_write is None:
                            first_write = time.monotonic()
                        await self.send("speech_audio", principal, request_id=owner.request_id,
                                        pcm=base64.b64encode(chunk).decode(), sample_rate=24_000,
                                        channels=1, format="s16le")
                        # Fill the initial playback reserve as PCM becomes available,
                        # then pace with that same bounded lead. Waiting in real
                        # time to fill it adds latency without improving jitter tolerance.
                        samples += len(chunk) // 2
                        await asyncio.sleep(max(0, first_write + samples / 24_000 - PLAYBACK_LEAD_SECS - time.monotonic()))
            if self.generation == generation and self.owner(principal) is owner:
                owner.phase, owner.deadline = "draining", time.monotonic() + 30
                await self.send("speech_end", principal, request_id=owner.request_id)
        except Exception:
            # External libraries may include reply text in exceptions.
            self.emit("error", principal, request_id=owner.request_id, code="speech_delivery_failed")
            self.release(principal)
        finally:
            if self.speaking is asyncio.current_task():
                self.speaking = self.speaking_owner = None

    def schedule_drop(self, principal):
        if principal not in self.dropping:
            task = asyncio.create_task(self._drop(principal), name="discord-speech-drop")
            self.dropping[principal] = task
            def settled(task):
                self.dropping.pop(principal, None)
                if not task.cancelled():
                    task.exception()
            task.add_done_callback(settled)

    async def _drop(self, principal):
        owner = self.owner(principal)
        if owner is not None and owner.principal == principal:
            if self.speaking is not None and self.speaking_owner is owner:
                task, self.speaking = self.speaking, None
                self.speaking_owner = None
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            self.release(principal)
        member = self.members.pop(principal, None)
        if member is not None:
            await member.close()

    async def _reset(self):
        if self.speaking is not None:
            task, self.speaking = self.speaking, None
            self.speaking_owner = None
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self.owners.clear()
        self._publish_ownership()
        self.blocked.clear()
        self.failures.clear()
        members, self.members = self.members, {}
        for member in members.values():
            await member.close()
        pending = [task for task in self.dropping.values() if task is not asyncio.current_task()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _maintain(self):
        while True:
            await asyncio.sleep(0.04)
            now = time.monotonic()
            for principal, member in tuple(self.members.items()):
                if member.probe_kind is not None and now >= member.probe_deadline:
                    member.probe_text = ""
                    member.fail(member.probe_kind + "_expired")
                    continue
                # Pipecat's audio task may terminate outside its frame error
                # path. A live socket must not silently retain a dead stream.
                audio_task = member.input._audio_task
                if (self.current(member) and member.ready.is_set()
                        and ((audio_task is not None and audio_task.done()) or member.runner.done())):
                    member.fail("audio_pipeline_stopped")
                    continue
                owner = self.owner(principal)
                if owner is not None and owner.principal == principal and now >= owner.deadline:
                    member.fail("utterance_timeout" if owner.phase == "listening" else "reply_timeout")
                    continue
                # Discord sends no packets between utterances. Supply only the
                # bounded terminal silence needed by the existing turn policy.
                gap = now - member.last_input
                if (self.current(member) and (owner is None or owner.principal != principal)
                        and member.probe_kind is None
                        and member.ready.is_set() and not member.turn._wake_pending
                        and (member.turn._wake_confirm is None or member.turn._wake_confirm.done())
                        and gap > TERMINAL_SILENCE_SECS
                        and not member.input._audio_in_queue._unfinished_tasks):
                    # A packet gap is the stream boundary even if quiet speech
                    # never produced a VAD stop. Drain through the final ASR/
                    # wake handlers before retiring decoder state; loaded model
                    # weights remain shared. Never discard an addressed turn.
                    # _drop removes the unowned member before its first await;
                    # a returning packet can create the next stream immediately.
                    await self._drop(principal)
                    continue
                if (self.listening(member) and 0.04 <= gap <= TERMINAL_SILENCE_SECS
                        and now - member.last_silence >= 0.04 and member.ready.is_set()):
                    member.last_silence = now
                    await member.audio(b"\0" * (PCM_FRAME * 2), terminal=True)
            for owner in tuple(self.owners.values()):
                if owner.principal not in self.members and now >= owner.deadline:
                    self.emit("error", owner.principal, request_id=owner.request_id, code="reply_timeout")
                    await self._drop(owner.principal)

    async def close(self):
        self._closed = True
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
        if self.writer is not None:
            self.writer.close()
        if self.connection is not None and self.connection is not asyncio.current_task():
            await self.connection
        if self.maintenance is not None:
            self.maintenance.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.maintenance
        await self._reset()
        if self._inode is not None:
            with contextlib.suppress(FileNotFoundError):
                if self.path.lstat().st_ino == self._inode:
                    self.path.unlink()
