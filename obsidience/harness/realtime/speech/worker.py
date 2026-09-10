"""Upstream Pipecat/NeMo speech connection to Obsidience's conversation lane."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import subprocess
import sys
import threading
import time
import types
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import nemo
import numpy as np
import pyaudio
import torch

# NeMo's service package imports optional LLM providers from __init__.py. Load
# only its speech modules: Obsidience's Task-selected model is the sole LLM.
_NEMO_SERVICE_PACKAGE = "nemo.agents.voice_agent.pipecat.services.nemo"
_nemo_voice_services = types.ModuleType(_NEMO_SERVICE_PACKAGE)
_nemo_voice_services.__path__ = [
    str(Path(nemo.__file__).resolve().parent / "agents/voice_agent/pipecat/services/nemo")
]
sys.modules[_NEMO_SERVICE_PACKAGE] = _nemo_voice_services

from nemo.agents.voice_agent.pipecat.services.nemo.stt import (
    NemoSTTService,
    NeMoSTTInputParams,
)
from nemo.agents.voice_agent.pipecat.services.nemo.turn_taking import (
    NeMoTurnTakingService,
)
from pipecat.audio.utils import calculate_audio_volume
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADParams, VADState
from pipecat.frames.frames import (
    BotStoppedSpeakingFrame,
    CancelFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    InputAudioRawFrame,
    InterimTranscriptionFrame,
    StartInterruptionFrame,
    TranscriptionFrame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
    UserStartedSpeakingFrame,
    UserStoppedSpeakingFrame,
    VADUserStartedSpeakingFrame,
    VADUserStoppedSpeakingFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.tts_service import TTSService
from pipecat.transports.local.audio import (
    LocalAudioInputTransport,
    LocalAudioOutputTransport,
    LocalAudioTransport,
    LocalAudioTransportParams,
)
from pocket_tts import TTSModel

SAMPLE_RATE = 16_000
TTS_SAMPLE_RATE = 24_000
TRANSCRIPT_IDLE_SECS = 0.7


class SpeechInputTiming:
    """Bounded boundary timestamps; NeMo remains the sole turn owner."""

    def __init__(self) -> None:
        self.sequence = 0
        self._active = False
        self._stages: list[dict[str, Any]] = []

    def onset(self, monotonic_ns: int | None = None) -> None:
        if not self._active:
            self._active = True
            self.sequence += 1
            if monotonic_ns is not None:
                self._stages.append({"stage": "speech_onset", "monotonic_ns": monotonic_ns})

    def partial(self) -> None:
        if not self._active:
            self.onset()
        if not any(row["stage"] == "first_partial" for row in self._stages):
            self._stages.append({"stage": "first_partial", "monotonic_ns": time.monotonic_ns()})

    def finish(self) -> dict[str, Any]:
        if not self._active:
            self.onset()
        stages = self._stages + [{"stage": "speech_final", "monotonic_ns": time.monotonic_ns()}]
        self._stages = []
        self._active = False
        return {"speech_sequence": self.sequence, "stages": stages}

    def discard(self) -> None:
        self._stages = []
        self._active = False


class NeMoLocalAudioInputTransport(LocalAudioInputTransport):
    """Leave turn interruption to NeMo without replacing Pipecat capture."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._last_level_at = 0.0
        self._capture_active = False

    async def push_frame(self, frame: Frame, direction=FrameDirection.DOWNSTREAM) -> None:
        if direction is FrameDirection.DOWNSTREAM and isinstance(frame, VADUserStartedSpeakingFrame):
            frame.metadata["obsidience_onset_ns"] = time.monotonic_ns()
        await super().push_frame(frame, direction)

    async def push_audio_frame(self, frame: InputAudioRawFrame) -> None:
        # Observe the existing captured frame before ASR queues or inference.
        # No PCM is retained or sent to the Harness/UI.
        if self._params.audio_in_enabled and not self._paused:
            now = time.monotonic()
            if now - self._last_level_at >= 0.1:
                emit(
                    "input_level",
                    level=round(calculate_audio_volume(frame.audio, frame.sample_rate), 4),
                )
                self._last_level_at = now
        await super().push_audio_frame(frame)

    async def _handle_user_interruption(
        self, vad_state: VADState, emulated: bool = False,
    ) -> None:
        self._user_speaking = vad_state == VADState.SPEAKING
        if not emulated and self._capture_active != self._user_speaking:
            self._capture_active = self._user_speaking
            emit("input_capture", active=self._capture_active)


class NeMoLocalAudioTransport(LocalAudioTransport):
    def __init__(self, *args, playback=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._playback = playback

    def input(self) -> FrameProcessor:
        if self._input is None:
            self._input = NeMoLocalAudioInputTransport(self._pyaudio, self._params)
        return self._input

    def output(self) -> FrameProcessor:
        if self._output is None:
            self._output = SpeechTimingAudioOutput(self._pyaudio, self._params, self._playback)
        return self._output


class SpeechTimingAudioOutput(LocalAudioOutputTransport):
    """Observe the existing ordered output queue; never own a second audio path."""

    def __init__(self, py_audio, params, playback) -> None:
        super().__init__(py_audio, params)
        self._playback = playback
        self._timing = None
        self._first_write = False

    async def push_frame(self, frame: Frame, direction=FrameDirection.DOWNSTREAM) -> None:
        # Upstream queues this marker with PCM and forwards it only when its
        # output task reaches it. Binding at process_frame would race old audio.
        if direction is FrameDirection.DOWNSTREAM and isinstance(frame, TTSStartedFrame):
            self._timing = frame.metadata.get("obsidience_timing")
            self._first_write = False
        await super().push_frame(frame, direction)

    async def write_audio_frame(self, frame) -> bool:
        timing = self._timing
        written = await super().write_audio_frame(frame)
        if written and not self._first_write and self._playback is not None:
            self._first_write = True
            self._playback.record_timing("first_output_write", timing, since="first_pcm_ns")
        return written


def emit(kind: str, **payload: Any) -> None:
    print(json.dumps({"type": kind, **payload}, ensure_ascii=False), flush=True)


class ObsidienceNeMoTurnTakingService(NeMoTurnTakingService):
    """Close recognized and empty VAD turns without leaving speech latched."""

    def __init__(self, *, timing: SpeechInputTiming | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._timing = timing
        self._transcript_timeout: asyncio.Task[None] | None = None

    async def push_frame(self, frame: Frame, direction=FrameDirection.DOWNSTREAM) -> None:
        if (self._timing is not None and self._timing.sequence > 0
                and isinstance(frame, (UserStartedSpeakingFrame, UserStoppedSpeakingFrame, StartInterruptionFrame))):
            frame.metadata["obsidience_speech_sequence"] = self._timing.sequence
        if (self._timing is not None and direction is FrameDirection.DOWNSTREAM
                and isinstance(frame, TranscriptionFrame) and frame.text.strip()
                and not (frame.text.startswith("(") and frame.text.endswith(")"))):
            frame.metadata["obsidience_speech_timing"] = self._timing.finish()
        await super().push_frame(frame, direction)

    async def _handle_vad_user_started_speaking(
        self,
        frame: VADUserStartedSpeakingFrame,
        direction: FrameDirection,
    ) -> None:
        """Keep VAD provisional until recognized speech confirms interruption."""

        self._vad_user_speaking = True
        if self._timing is not None:
            self._timing.onset(frame.metadata.get("obsidience_onset_ns"))
        await self.push_frame(frame, direction)

    async def _cancel_transcript_timeout(self) -> None:
        timeout = self._transcript_timeout
        self._transcript_timeout = None
        if timeout is not None and timeout is not asyncio.current_task():
            await self.cancel_task(timeout)

    async def _close_unvoiced_transcript(self, direction: FrameDirection) -> None:
        try:
            await asyncio.sleep(TRANSCRIPT_IDLE_SECS)
            if self._user_speaking_buffer.strip():
                # The endpoint has won. Disarm it before the first await so a
                # real VAD edge cannot cancel NeMo halfway through finalizing.
                self._transcript_timeout = None
                await self.push_frame(
                    VADUserStoppedSpeakingFrame(), direction=FrameDirection.UPSTREAM,
                )
                await self.queue_frame(VADUserStoppedSpeakingFrame(), direction)
        except asyncio.CancelledError:
            return
        finally:
            if self._transcript_timeout is asyncio.current_task():
                self._transcript_timeout = None

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        if (self._timing is not None and (
                isinstance(frame, (EndFrame, CancelFrame)) or (
                    isinstance(frame, VADUserStoppedSpeakingFrame)
                    and not self._user_speaking_buffer.strip()))):
            self._timing.discard()
        empty_vad_stop = (
            isinstance(frame, VADUserStoppedSpeakingFrame)
            and self._have_sent_user_started_speaking
            and not self._user_speaking_buffer.strip()
        )
        if isinstance(
            frame,
            (VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame, EndFrame, CancelFrame),
        ):
            await self._cancel_transcript_timeout()

        await super().process_frame(frame, direction)

        if empty_vad_stop and self._have_sent_user_started_speaking:
            await self._handle_user_interruption(UserStoppedSpeakingFrame())
            self._have_sent_user_started_speaking = False

        if not isinstance(frame, (InterimTranscriptionFrame, TranscriptionFrame)):
            return
        transcript = " ".join(self._user_speaking_buffer.split())
        if not transcript or not any(character.isalnum() for character in transcript):
            return
        if self._timing is not None:
            self._timing.partial()
        emit("transcript_partial", text=transcript)
        if not self._have_sent_user_started_speaking:
            await self._handle_user_interruption(UserStartedSpeakingFrame())
            self._have_sent_user_started_speaking = True
        await self._cancel_transcript_timeout()
        self._transcript_timeout = self.create_task(
            self._close_unvoiced_transcript(direction),
            name="nemo-transcript-endpoint",
        )


class PocketTTSService(TTSService):
    """Pocket TTS as a normal Pipecat streaming TTS service."""

    def __init__(self, *, root: Path, voice: str, playback=None) -> None:
        super().__init__(sample_rate=TTS_SAMPLE_RATE)
        self._playback = playback
        self._timing = None
        config = root / "english.yaml"
        voice_path = root / "voices" / f"{voice}.safetensors"
        if not config.is_file() or not voice_path.is_file():
            raise FileNotFoundError("Pocket TTS config or selected voice is missing")
        torch.set_num_threads(max(1, min(16, (os.cpu_count() or 8) // 2)))
        self._model = TTSModel.load_model(
            config=config,
            temp=0.3,
            sampler_decode_steps=5 if voice == "starfleet" else 1,
        )
        self._model.to("cpu")
        self._voice_state = self._model.get_state_for_audio_prompt(str(voice_path))

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        if isinstance(frame, TTSSpeakFrame):
            self._timing = frame.metadata.get("obsidience_timing")
        await super().process_frame(frame, direction)

    async def run_tts(self, text: str) -> AsyncGenerator[Frame, None]:
        clean = " ".join(text.split())[:4_000]
        if not clean:
            return

        timing = self._timing
        if timing is not None:
            timing["tts_started_ns"] = time.monotonic_ns()
        first_pcm = True

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[bytes | BaseException | None] = asyncio.Queue()
        cancelled = threading.Event()

        def synthesize() -> None:
            try:
                for chunk in self._model.generate_audio_stream(self._voice_state, clean):
                    if cancelled.is_set():
                        break
                    samples = chunk.detach().float().cpu().numpy().reshape(-1)
                    pcm = np.rint(np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
                    loop.call_soon_threadsafe(queue.put_nowait, pcm.tobytes())
            except BaseException as exc:
                loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        worker = threading.Thread(target=synthesize, name="pocket-tts", daemon=True)
        worker.start()
        started = TTSStartedFrame()
        started.metadata["obsidience_timing"] = timing
        yield started
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                if isinstance(item, BaseException):
                    yield ErrorFrame(error=f"Pocket TTS failed: {item}")
                    break
                if first_pcm and self._playback is not None:
                    first_pcm = False
                    self._playback.record_timing("first_pcm", timing, since="tts_started_ns")
                yield TTSAudioRawFrame(item, TTS_SAMPLE_RATE, 1)
        finally:
            cancelled.set()
            await asyncio.to_thread(worker.join, 2)
        yield TTSStoppedFrame()


class PlaybackInputRoute(FrameProcessor):
    """Keep one Pipecat input on AEC only while assistant audio is playing."""

    def __init__(self, *, raw_source: str, aec_source: str) -> None:
        super().__init__()
        self._raw_source = raw_source
        self._aec_source = aec_source
        self._current_source = raw_source
        self._source_output: int | None = None

    def _move_sync(self, source: str) -> None:
        if source == self._current_source:
            return
        if self._source_output is None:
            completed = subprocess.run(
                ("/usr/bin/pactl", "-f", "json", "list", "source-outputs"),
                stdin=subprocess.DEVNULL,
                capture_output=True,
                check=False,
                timeout=2,
            )
            if completed.returncode:
                raise RuntimeError("Pipecat microphone stream could not be inspected")
            rows = json.loads(completed.stdout)
            matches = [
                row.get("index")
                for row in rows
                if isinstance(row, dict)
                and isinstance(row.get("properties"), dict)
                and row["properties"].get("application.process.id") == str(os.getpid())
                and isinstance(row.get("index"), int)
            ]
            if len(matches) != 1:
                raise RuntimeError("Pipecat microphone stream is not uniquely addressable")
            self._source_output = matches[0]
        completed = subprocess.run(
            (
                "/usr/bin/pactl",
                "move-source-output",
                str(self._source_output),
                source,
            ),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            check=False,
            timeout=2,
        )
        if completed.returncode:
            raise RuntimeError("Pipecat microphone stream could not change input route")
        self._current_source = source

    async def prepare_playback(self) -> None:
        """Settle capture on AEC before the first speaker sample is queued."""

        await asyncio.to_thread(self._move_sync, self._aec_source)

    async def restore_capture(self) -> None:
        await asyncio.to_thread(self._move_sync, self._raw_source)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if direction is FrameDirection.DOWNSTREAM and isinstance(frame, TTSStartedFrame):
            await self.prepare_playback()
        elif (
            direction is FrameDirection.UPSTREAM
            and isinstance(frame, BotStoppedSpeakingFrame)
        ) or isinstance(frame, (EndFrame, CancelFrame)):
            await self.restore_capture()
        await self.push_frame(frame, direction)


class PlaybackCommands:
    """One pending Task reply, invalidated before preparation or synthesis."""

    def __init__(self) -> None:
        self.generation = -1
        self.epoch = 0
        self._queued: tuple[int, int, str, dict | None] | None = None
        self._preparing: asyncio.Task | None = None
        self._controller_ready = asyncio.Event()
        self._startup_pending = True

    def invalidate(self, generation: int | None = None) -> bool:
        if generation is not None and (
            type(generation) is not int or generation < self.generation
        ):
            return False
        if generation is None or self._controller_ready.is_set():
            self._startup_pending = False
        self.generation = self.generation + 1 if generation is None else generation
        self.epoch += 1
        self._queued = None
        if generation is not None:
            self._controller_ready.set()
        return True

    def accepts(self, frame: TTSSpeakFrame) -> bool:
        binding = frame.metadata.get("obsidience_playback")
        return binding is None or binding == (self.generation, self.epoch)

    def record_timing(self, stage: str, timing: dict | None, *, since: str = "") -> None:
        if (not isinstance(timing, dict)
                or (timing.get("generation"), timing.get("epoch")) != (self.generation, self.epoch)):
            return
        now = time.monotonic_ns()
        payload = {key: timing[key] for key in ("generation", "speech_sequence", "turn_id", "run_id")}
        payload.update(stage=stage, monotonic_ns=now)
        if since and type(timing.get(since)) is int:
            payload["duration_ms"] = max(0, now - timing[since]) / 1_000_000
        if stage == "first_pcm":
            timing["first_pcm_ns"] = now
        emit("speech_timing", **payload)

    def _timing_context(self, command: dict) -> dict | None:
        # Startup speech and malformed/unbound diagnostics have no Task identity.
        if (type(command.get("speech_sequence")) is not int
                or not 0 < command["speech_sequence"] < 2**31
                or any(not isinstance(command.get(key), str) or not command[key]
                       or len(command[key]) > 96 or not command[key].isascii()
                       or any(not (c.isalnum() or c in "-_:.") for c in command[key])
                       for key in ("turn_id", "run_id"))):
            return None
        return {key: command[key] for key in ("generation", "speech_sequence", "turn_id", "run_id")} | {
            "epoch": self.epoch, "received_ns": time.monotonic_ns(),
        }

    def speak(self, task: PipelineTask, route: PlaybackInputRoute, command: dict) -> None:
        generation = command.get("generation")
        text = " ".join(str(command.get("text", "")).split())[:4_000]
        if type(generation) is not int or generation < self.generation or not text:
            return
        self._startup_pending = False
        self._controller_ready.set()
        self.generation = generation
        self.epoch += 1
        timing = self._timing_context(command)
        self.record_timing("speech_received", timing)
        self._queued = (generation, self.epoch, text, timing)
        if self._preparing is None or self._preparing.done():
            self._preparing = asyncio.create_task(
                self._prepare(task, route), name="speech-playback-prepare",
            )

    async def startup(self, task: PipelineTask, route: PlaybackInputRoute, text: str) -> None:
        # The initial new-conversation cancellation establishes the generation;
        # later user activity supersedes this optional startup announcement.
        await self._controller_ready.wait()
        if self._startup_pending:
            self.speak(task, route, {"generation": self.generation, "text": text})

    async def _prepare(self, task: PipelineTask, route: PlaybackInputRoute) -> None:
        try:
            while self._queued is not None:
                generation, epoch, text, timing = self._queued
                self._queued = None
                # Let the bounded PipeWire operation finish before restoring raw
                # capture; cancelling to_thread would leave its mutation running.
                await route.prepare_playback()
                if (generation, epoch) != (self.generation, self.epoch):
                    await route.restore_capture()
                    continue
                self.record_timing("aec_ready", timing, since="received_ns")
                frame = TTSSpeakFrame(text)
                frame.metadata["obsidience_playback"] = (generation, epoch)
                frame.metadata["obsidience_timing"] = timing
                await task.queue_frame(frame)
        except Exception as exc:
            self.invalidate()
            emit("fatal", error=f"Task playback preparation failed: {exc}")
            await task.queue_frame(EndFrame())

    async def close(self) -> None:
        self.invalidate()
        self._controller_ready.set()
        if self._preparing is not None:
            await self._preparing


class ObsidienceTaskBridge(FrameProcessor):
    """The only Obsidience seam: transcripts out and Task replies back in."""

    def __init__(self, playback: PlaybackCommands | None = None) -> None:
        super().__init__()
        self.playback = playback or PlaybackCommands()

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        if isinstance(frame, StartInterruptionFrame) and not frame.metadata.get("obsidience_playback_cancel"):
            self.playback.invalidate()
        await super().process_frame(frame, direction)
        sequence = frame.metadata.get("obsidience_speech_sequence")
        correlation = {"speech_sequence": sequence} if type(sequence) is int and sequence > 0 else {}
        if isinstance(frame, TranscriptionFrame):
            text = " ".join(frame.text.split())
            if text and not (text.startswith("(") and text.endswith(")")):
                timing = frame.metadata.get("obsidience_speech_timing")
                emit("transcript_final", text=text, **({"speech_timing": timing} if timing else {}))
        elif isinstance(frame, StartInterruptionFrame):
            if not frame.metadata.get("obsidience_playback_cancel"):
                emit("interruption", **correlation)
        elif isinstance(frame, TTSSpeakFrame) and not self.playback.accepts(frame):
            return
        elif isinstance(frame, UserStartedSpeakingFrame):
            emit("speech_detected", **correlation)
        elif isinstance(frame, UserStoppedSpeakingFrame):
            emit("speech_ended", **correlation)
        await self.push_frame(frame, direction)


async def command_loop(
    task: PipelineTask, playback_input: PlaybackInputRoute,
    playback: PlaybackCommands | None = None,
) -> None:
    playback = playback or PlaybackCommands()
    try:
        while True:
            line = await asyncio.to_thread(sys.stdin.readline)
            if not line:
                await playback.close()
                await task.queue_frame(EndFrame())
                return
            try:
                command = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(command, dict):
                continue
            kind = command.get("type")
            if kind == "speak":
                playback.speak(task, playback_input, command)
            elif kind == "cancel":
                if not playback.invalidate(command.get("generation")):
                    continue
                if command.get("stop_playback", True) is True:
                    frame = StartInterruptionFrame()
                    frame.metadata["obsidience_playback_cancel"] = True
                    await task.queue_frame(frame)
            elif kind == "stop":
                await playback.close()
                await task.queue_frame(EndFrame())
                return
    finally:
        await playback.close()


async def run(args: argparse.Namespace) -> None:
    probe = pyaudio.PyAudio()
    try:
        pulse_devices = [
            index
            for index in range(probe.get_device_count())
            if probe.get_device_info_by_index(index).get("name") == "pulse"
        ]
    finally:
        probe.terminate()
    if len(pulse_devices) != 1:
        raise RuntimeError("Pipecat could not resolve the local PulseAudio device")

    playback = PlaybackCommands()
    input_timing = SpeechInputTiming()
    transport = NeMoLocalAudioTransport(
        LocalAudioTransportParams(
            input_device_index=pulse_devices[0],
            output_device_index=pulse_devices[0],
            audio_in_enabled=True,
            audio_out_enabled=True,
            vad_analyzer=SileroVADAnalyzer(
                sample_rate=SAMPLE_RATE,
                params=VADParams(
                    confidence=0.2,
                    start_secs=0.10,
                    stop_secs=TRANSCRIPT_IDLE_SECS,
                    min_volume=0.0,
                ),
            ),
            audio_in_sample_rate=SAMPLE_RATE,
            audio_out_sample_rate=TTS_SAMPLE_RATE,
            audio_out_10ms_chunks=4,
        ), playback=playback,
    )
    stt = NemoSTTService(
        model=args.asr_model,
        device="cuda:0",
        sample_rate=SAMPLE_RATE,
        params=NeMoSTTInputParams(
            att_context_size=[70, 1],
            frame_len_in_secs=0.08,
            raw_audio_frame_len_in_secs=0.02,
            buffer_size=4,
        ),
        has_turn_taking=False,
        backend="legacy",
        decoder_type="rnnt",
        audio_passthrough=True,
    )
    turn_taking = ObsidienceNeMoTurnTakingService(
        timing=input_timing,
        use_vad=True,
        use_diar=False,
        max_buffer_size=2,
        bot_stop_delay=0.5,
        backchannel_phrases=None,
    )
    bridge = ObsidienceTaskBridge(playback)
    tts = PocketTTSService(root=Path(args.pocket_root), voice=args.voice, playback=playback)
    playback_input = PlaybackInputRoute(
        raw_source=os.environ["OBSIDIENCE_RAW_SOURCE"],
        aec_source=os.environ["OBSIDIENCE_AEC_SOURCE"],
    )
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            turn_taking,
            bridge,
            tts,
            playback_input,
            transport.output(),
        ]
    )
    task = PipelineTask(
        pipeline,
        params=PipelineParams(
            allow_interruptions=True,
            audio_in_sample_rate=SAMPLE_RATE,
            audio_out_sample_rate=TTS_SAMPLE_RATE,
            enable_metrics=False,
            enable_usage_metrics=False,
            idle_timeout=None,
        ),
        idle_timeout_secs=None,
        cancel_on_idle_timeout=False,
    )

    @task.event_handler("on_pipeline_started")
    async def on_pipeline_started(task: PipelineTask, frame: Frame) -> None:
        emit("transport_ready", transport="pipecat.local")
        emit(
            "runtime_ready",
            asr="nvidia/nemotron-speech-streaming-en-0.6b",
            asr_chunk_ms=160,
            tts="pocket-tts-3.0.2-cpu",
            voice=args.voice,
        )
        await playback.startup(task, playback_input, args.startup_confirmation)

    commands = asyncio.create_task(
        command_loop(task, playback_input, playback), name="speech-commands",
    )
    try:
        await PipelineRunner(handle_sigint=True, handle_sigterm=True).run(task)
    finally:
        commands.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await commands


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("--asr-model", required=True)
    result.add_argument("--pocket-root", required=True)
    result.add_argument("--voice", choices=("starfleet", "hal", "ultron"), required=True)
    result.add_argument("--startup-confirmation", default="Realtime active.")
    return result


def main() -> None:
    try:
        asyncio.run(run(parser().parse_args()))
    except KeyboardInterrupt:
        pass
    except BaseException as exc:
        emit("fatal", error=f"{type(exc).__name__}: {exc}"[:1000])
        raise


if __name__ == "__main__":
    main()
