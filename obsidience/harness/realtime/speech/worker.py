"""Upstream Pipecat/NeMo voice pipeline for the Obsidience Realtime Task."""

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
    LocalAudioTransport,
    LocalAudioTransportParams,
)
from pocket_tts import TTSModel

SAMPLE_RATE = 16_000
TTS_SAMPLE_RATE = 24_000
TRANSCRIPT_IDLE_SECS = 1.2


class NeMoLocalAudioInputTransport(LocalAudioInputTransport):
    """Leave turn interruption to NeMo without replacing Pipecat capture."""

    async def _handle_user_interruption(
        self, vad_state: VADState, emulated: bool = False,
    ) -> None:
        self._user_speaking = vad_state == VADState.SPEAKING


class NeMoLocalAudioTransport(LocalAudioTransport):
    def input(self) -> FrameProcessor:
        if self._input is None:
            self._input = NeMoLocalAudioInputTransport(self._pyaudio, self._params)
        return self._input


def emit(kind: str, **payload: Any) -> None:
    print(json.dumps({"type": kind, **payload}, ensure_ascii=False), flush=True)


class ObsidienceNeMoTurnTakingService(NeMoTurnTakingService):
    """Close recognized and empty VAD turns without leaving speech latched."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._transcript_timeout: asyncio.Task[None] | None = None

    async def _handle_vad_user_started_speaking(
        self,
        frame: VADUserStartedSpeakingFrame,
        direction: FrameDirection,
    ) -> None:
        """Let NeMo confirm speech before interrupting assistant playback."""

        if not self._bot_speaking:
            await super()._handle_vad_user_started_speaking(frame, direction)
            return
        self._vad_user_speaking = True
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

    def __init__(self, *, root: Path, voice: str) -> None:
        super().__init__(sample_rate=TTS_SAMPLE_RATE)
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

    async def run_tts(self, text: str) -> AsyncGenerator[Frame, None]:
        clean = " ".join(text.split())[:4_000]
        if not clean:
            return

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
        yield TTSStartedFrame()
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                if isinstance(item, BaseException):
                    yield ErrorFrame(error=f"Pocket TTS failed: {item}")
                    break
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

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if direction is FrameDirection.DOWNSTREAM and isinstance(frame, TTSStartedFrame):
            await self.prepare_playback()
        elif (
            direction is FrameDirection.UPSTREAM
            and isinstance(frame, BotStoppedSpeakingFrame)
        ) or isinstance(frame, (EndFrame, CancelFrame)):
            await asyncio.to_thread(self._move_sync, self._raw_source)
        await self.push_frame(frame, direction)


class ObsidienceTaskBridge(FrameProcessor):
    """The only Obsidience seam: transcripts out and Task replies back in."""

    def __init__(self) -> None:
        super().__init__()
        self._last_level_at = 0.0

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        await super().process_frame(frame, direction)
        if isinstance(frame, InputAudioRawFrame):
            now = time.monotonic()
            if now - self._last_level_at >= 0.1:
                emit(
                    "input_level",
                    level=round(calculate_audio_volume(frame.audio, frame.sample_rate), 4),
                )
                self._last_level_at = now
        elif isinstance(frame, TranscriptionFrame):
            text = " ".join(frame.text.split())
            if text and not (text.startswith("(") and text.endswith(")")):
                emit("transcript_final", text=text)
        elif isinstance(frame, StartInterruptionFrame):
            emit("interruption")
        elif isinstance(frame, UserStartedSpeakingFrame):
            emit("speech_detected")
        elif isinstance(frame, UserStoppedSpeakingFrame):
            emit("speech_ended")
        await self.push_frame(frame, direction)


async def command_loop(task: PipelineTask, playback_input: PlaybackInputRoute) -> None:
    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            await task.queue_frame(EndFrame())
            return
        try:
            command = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = command.get("type")
        if kind == "speak":
            text = " ".join(str(command.get("text", "")).split())[:4_000]
            if text:
                await playback_input.prepare_playback()
                await task.queue_frame(TTSSpeakFrame(text))
        elif kind == "cancel":
            await task.queue_frame(StartInterruptionFrame())
        elif kind == "stop":
            await task.queue_frame(EndFrame())
            return


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
                    stop_secs=1.2,
                    min_volume=0.0,
                ),
            ),
            audio_in_sample_rate=SAMPLE_RATE,
            audio_out_sample_rate=TTS_SAMPLE_RATE,
            audio_out_10ms_chunks=4,
        ),
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
        use_vad=True,
        use_diar=False,
        max_buffer_size=2,
        bot_stop_delay=0.5,
        backchannel_phrases=None,
    )
    bridge = ObsidienceTaskBridge()
    tts = PocketTTSService(root=Path(args.pocket_root), voice=args.voice)
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
        await playback_input.prepare_playback()
        await task.queue_frame(TTSSpeakFrame(args.startup_confirmation))

    commands = asyncio.create_task(
        command_loop(task, playback_input), name="speech-commands",
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
