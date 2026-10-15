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
import copy
import json
import os
import re
import socket
import stat
import struct
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from nemo.agents.voice_agent.pipecat.services.nemo.streaming_asr import NemoStreamingASRService
from nemo.agents.voice_agent.pipecat.services.nemo.utils import CacheFeatureBufferer
from pipecat.transports.base_input import BaseInputTransport

from . import worker as speech

MAX_LINE = 65_536
MAX_STREAMS = 8
MAX_PCM = 16_384
PCM_FRAME = 640  # 20 ms, mono s16/16 kHz.
MAX_QUEUED_FRAMES = 50  # One second per member, including terminal silence.
MAX_COMMAND_CHARS = 2_000
_PRINCIPAL_FIELDS = ("guild_id", "channel_id", "member_id")
_ID = re.compile(r"[0-9]{1,20}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_-]{1,96}\Z")


def _principal(message: dict) -> tuple[str, str, str]:
    values = tuple(message.get(key) for key in _PRINCIPAL_FIELDS)
    if not all(isinstance(value, str) and _ID.fullmatch(value) for value in values):
        raise ValueError("invalid_principal")
    return values


def _token(value) -> str:
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise ValueError("invalid_identity")
    return value


def _decoder_context(source):
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
    }
    isolated = {"_audio_buffer", "_cache_last_channel", "_cache_last_time",
                "_cache_last_channel_len", "_previous_hypotheses", "_last_transcript_timestamp"}
    if type(source) is not NemoStreamingASRService or set(vars(source)) != shared | isolated:
        # An upstream decoder adding stream state needs review before sharing.
        raise RuntimeError("unsupported_discord_asr_backend")
    result = copy.copy(source)
    result._audio_buffer = CacheFeatureBufferer(
        sample_rate=speech.SAMPLE_RATE,
        buffer_size_in_secs=source.buffer_size_in_secs,
        chunk_size_in_secs=source.chunk_size_in_secs,
        preprocessor_cfg=source.asr_model.cfg.preprocessor,
        device=source.device,
    )
    result._reset_cache()
    result._previous_hypotheses = result._get_blank_hypothesis()
    result._last_transcript_timestamp = time.time()
    return result


class _MemberSTT(speech.UtteranceNeMoSTTService):
    def __init__(self, source, decoder):
        self._shared_decoder = decoder
        super().__init__(model=source._model_name, device=source._device,
                         sample_rate=speech.SAMPLE_RATE, params=source._params,
                         has_turn_taking=False, backend="legacy",
                         decoder_type=source._decoder_type, audio_passthrough=True,
                         enable_direct_mode=True)
        self._model_lock = source._model_lock
        self.last_reset = time.monotonic()

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, speech.VADUserStoppedSpeakingFrame):
            self.last_reset = time.monotonic()

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
        self._wake_pattern = re.compile(r"(?<!\w)squanch\s*bot(?!\w)", re.IGNORECASE)

    async def _open_wake(self, text, *, cue_name="ready"):
        if not self.stream.server.claim(self.stream):
            await self._reset_wake_scan(segment_start=False)
            return ""
        return await super()._open_wake(text, cue_name=cue_name)

    async def _handle_transcription(self, frame, direction):
        if self.stream.server.listening(self.stream):
            await super()._handle_transcription(frame, direction)


class _FinalText(speech.FrameProcessor):
    def __init__(self, stream):
        super().__init__(enable_direct_mode=True)
        self.stream = stream

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, speech.TranscriptionFrame):
            self.stream.final(frame.text)
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
    def __init__(self, server, principal, decoder):
        self.server, self.principal = server, principal
        self.generation = server.generation
        self.last_input = time.monotonic()
        self.last_silence = self.last_input
        self.remainder = bytearray()
        self.closed = False
        self.ready = asyncio.Event()
        self.stt = _MemberSTT(server.stt, decoder)
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
                                wake_word="Squanchbot", smart_turn=turn_analyzer is not None,
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
        if kind == "wake_detected" and owner is not None and owner.principal == self.principal:
            self.server.emit("wake", self.principal, request_id=owner.request_id)
        elif kind == "wake_idle" and owner is not None and owner.phase == "listening":
            self.server.release(self.principal)
        # Ambient words and partial transcripts never leave the speech owner.

    def final(self, text):
        owner = self.server.owner(self.principal)
        text = " ".join(text.split())
        if (not self.server.current(self) or owner is None or owner.principal != self.principal
                or owner.phase != "listening" or not text):
            return
        if len(text) > MAX_COMMAND_CHARS:
            self.fail("utterance_limit")
            return
        owner.phase, owner.deadline = "waiting", time.monotonic() + 120
        self.server.emit("transcript", self.principal, request_id=owner.request_id, text=text)

    def fail(self, code):
        if self.server.current(self):
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
            self.last_input = self.last_silence = time.monotonic()
            if self.last_input - self.stt.last_reset > 35:
                # RNNT hypotheses grow across a continuous utterance. Bound
                # ambient speech too, and require a real gap before rearming.
                self.fail("utterance_limit")
                return
        self.remainder.extend(pcm)
        while len(self.remainder) >= PCM_FRAME:
            piece = bytes(self.remainder[:PCM_FRAME])
            del self.remainder[:PCM_FRAME]
            try:
                await self.input.push_audio_frame(speech.InputAudioRawFrame(piece, speech.SAMPLE_RATE, 1))
            except asyncio.QueueFull:
                self.fail("audio_backpressure")
                self.remainder.clear()
                return

    async def close(self):
        self.closed = True
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
        self._inode = None
        self._closed = False

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
        return self.current(member) and (owner is None or (
            owner.principal == member.principal and owner.phase == "listening"))

    def claim(self, member):
        if not self.listening(member):
            return False
        if self.owner(member.principal) is None:
            self.owners[member.principal[:2]] = _Owner(
                member.principal, uuid.uuid4().hex, deadline=time.monotonic() + 35)
            # Another participant's earlier unaddressed recognition cannot
            # survive this invoker's exclusive command/reply window.
            for principal in tuple(self.members):
                if principal[:2] == member.principal[:2] and principal != member.principal:
                    self.schedule_drop(principal)
        return True

    def block(self, principal):
        if len(self.blocked) >= 64:
            self.blocked.pop(min(self.blocked, key=self.blocked.get))
        self.blocked[principal] = time.monotonic()

    def release(self, principal):
        owner = self.owner(principal)
        if owner is not None and owner.principal == principal:
            self.owners.pop(principal[:2], None)

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
        if kind == "audio":
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
            if blocked_at is not None:
                if time.monotonic() - blocked_at < speech.TRANSCRIPT_IDLE_SECS:
                    self.blocked[principal] = time.monotonic()
                    return
                self.blocked.pop(principal, None)
            owner = self.owner(principal)
            if owner is not None and (owner.principal != principal or owner.phase != "listening"):
                return
            if principal in self.dropping:
                return
            member = self.members.get(principal)
            if member is None:
                if len(self.members) >= MAX_STREAMS:
                    self.emit("error", principal, code="stream_capacity")
                    return
                async with self.stt._model_lock:
                    decoder = _decoder_context(self.stt._model)
                member = _Member(self, principal, decoder)
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
            self.release(principal)
            member = self.members.get(principal)
            if owner.question and member is not None and self.current(member):
                await member.turn._open_wake("", cue_name="follow_up")
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
                        # Pace media, preserving socket and downstream PCM bounds.
                        samples += len(chunk) // 2
                        await asyncio.sleep(max(0, first_write + samples / 24_000 - time.monotonic()))
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
        self.blocked.clear()
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
                owner = self.owner(principal)
                if owner is not None and owner.principal == principal and now >= owner.deadline:
                    member.fail("utterance_timeout" if owner.phase == "listening" else "reply_timeout")
                    continue
                if owner is None and now - member.last_input > 60:
                    self.schedule_drop(principal)
                    continue
                # Discord sends no packets between utterances. Supply only the
                # bounded terminal silence needed by the existing turn policy.
                gap = now - member.last_input
                if (self.listening(member) and 0.04 <= gap <= 4.0
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
