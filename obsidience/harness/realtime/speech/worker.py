"""Upstream Pipecat/NeMo speech connection to Obsidience's conversation lane."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import re
import sys
import threading
import time
import types
from collections.abc import AsyncGenerator
from dataclasses import dataclass
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
    SystemFrame,
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
from .cues import CueAudioFrame, CueMarker, ReplyFinished, load_assets, CHUNK_BYTES

SAMPLE_RATE = 16_000
TTS_SAMPLE_RATE = 24_000
TRANSCRIPT_IDLE_SECS = 0.7
WAKE_COMMAND_WAIT_SECS = 8
# The wake word is an address, not any mention: it must start the speech
# segment or follow a pause in recognized words, optionally after hey/ok/okay.
WAKE_PAUSE_SECS = 0.4
# A name ending the recognized text may still become "computer's"; the next
# ASR delta normally arrives within one or two 80-160 ms steps.
WAKE_CONFIRM_SECS = 0.35
WAKE_STRIP = " ,.!?:;—-'’\t\n"
_WAKE_LEAD = re.compile(r"[\W_]*(?:(?:hey|ok|okay)\b[\W_]*)?", re.IGNORECASE)
# Speech PCM needs level correction independently of the selected device volume.
# A fixed gain preserves pauses and syllable dynamics across streaming chunks.
TTS_GAIN = 10.0 ** (9.0 / 20.0)
TTS_PEAK_KNEE = 0.85
TTS_PEAK_CEILING = 0.95


def _speech_pcm(samples: np.ndarray) -> bytes:
    boosted = samples * TTS_GAIN
    magnitude = np.abs(boosted)
    # A continuous soft knee protects unusually loud peaks without chunk-level
    # normalization, lookahead, or an envelope that pumps between chunks.
    headroom = TTS_PEAK_CEILING - TTS_PEAK_KNEE
    protected = np.sign(boosted) * (
        TTS_PEAK_KNEE + headroom * np.tanh((magnitude - TTS_PEAK_KNEE) / headroom)
    )
    boosted = np.where(magnitude > TTS_PEAK_KNEE, protected, boosted)
    return np.rint(boosted * 32767.0).astype("<i2").tobytes()


def classify_wake(text: str, address: int | None, scanned: int, pattern: re.Pattern,
                  *, final: bool = False) -> tuple[str, int, int, list[str]]:
    """Classify unaddressed wake-word mentions in one speech segment's text.

    ``address`` is where an address may begin (segment start or after a pause);
    only hey/ok/okay may precede the name there. Possessives and contractions
    ("computer's") are never addresses. A name ending the text stays pending
    until more text arrives, unless ``final``. Returns (decision, end, scanned,
    rejected): accept/pending/none, the end of the name, the index up to which
    mentions were classified, and the reasons for newly rejected mentions.
    """
    rejected: list[str] = []
    for match in pattern.finditer(text, scanned):
        after = text[match.end():]
        if not final and after in ("", "'", "’"):
            return "pending", match.end(), scanned, rejected
        if after[:1] in ("'", "’") and after[1:2].isalnum():
            rejected.append("possessive")
        elif (address is not None and match.start() >= address
              and _WAKE_LEAD.fullmatch(text, address, match.start())):
            return "accept", match.end(), match.end(), rejected
        else:
            rejected.append("mid_sentence")
        scanned = match.end()
    return "none", len(text), scanned, rejected


@dataclass
class ListeningModeFrame(SystemFrame):
    mode: str
    revision: int


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

    def __init__(self, *args: Any, input_channel: str = "mono", **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._input_channel = input_channel
        self._last_level_at = 0.0
        self._capture_active = False

    async def push_frame(self, frame: Frame, direction=FrameDirection.DOWNSTREAM) -> None:
        if direction is FrameDirection.DOWNSTREAM and isinstance(frame, VADUserStartedSpeakingFrame):
            frame.metadata["obsidience_onset_ns"] = time.monotonic_ns()
        await super().push_frame(frame, direction)

    async def push_audio_frame(self, frame: InputAudioRawFrame) -> None:
        if self._input_channel == "left":
            # This UMA-8's left channel contains the cancelled DSP signal;
            # folding its two USB channels to mono reintroduces speaker echo.
            # Select samples inside the existing frame, before metering/VAD/ASR.
            if frame.num_channels != 2 or len(frame.audio) % 4:
                raise ValueError("UMA-8 capture must provide interleaved stereo PCM")
            frame = InputAudioRawFrame(
                audio=np.frombuffer(frame.audio, dtype="<i2")[::2].tobytes(),
                sample_rate=frame.sample_rate, num_channels=1,
            )
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
    def __init__(self, *args, playback=None, input_channel="mono", **kwargs):
        super().__init__(*args, **kwargs)
        self._playback = playback
        self._input_channel = input_channel

    def input(self) -> FrameProcessor:
        if self._input is None:
            self._input = NeMoLocalAudioInputTransport(
                self._pyaudio, self._params, input_channel=self._input_channel,
            )
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
        self._binding = None
        self._cue_binding = None
        self._cue_failed = False
        self._cue_wrote = False
        self._reply_failed = False

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        if (direction is FrameDirection.DOWNSTREAM
                and isinstance(frame, StartInterruptionFrame)
                and not frame.metadata.get("obsidience_playback_cancel")
                and self._playback._ready_cue_binding is not None):
            # Natural speech still cancels reasoning/TTS upstream and keeps
            # capture live, but must not flush an opening chirp already playing.
            return
        await super().process_frame(frame, direction)
        # The open input window is local speech state. Queue its acknowledgement
        # as soon as native interruption clears old output, without a Harness
        # round trip or waiting for conversation/model cancellation cleanup.
        turn = self._playback._turn_taking
        if (direction is FrameDirection.DOWNSTREAM
                and isinstance(frame, StartInterruptionFrame)
                and not frame.metadata.get("obsidience_playback_cancel")
                and frame.metadata.get("obsidience_wake_ready")
                and turn is not None and turn.mode == "wake"
                and frame.metadata.get("obsidience_mode_revision") == turn.mode_revision
                and (turn._timing is None or (
                    turn._timing.sequence > 0
                    and frame.metadata.get("obsidience_speech_sequence") == turn._timing.sequence))
                and turn._wake_cue_eligible):
            await self._playback.queue_cue("ready", self._playback.generation)

    async def push_frame(self, frame: Frame, direction=FrameDirection.DOWNSTREAM) -> None:
        if direction is FrameDirection.DOWNSTREAM and isinstance(frame, CueMarker):
            if not frame.end:
                self._cue_binding = frame
                self._cue_failed = False
                self._cue_wrote = False
                if frame.cue_name == "ready" and self._playback.cue_current(frame):
                    self._playback._ready_cue_binding = (frame.generation, frame.epoch)
                if (frame.cue_name == "ready"
                        and self._playback._pending_ready_cue_binding == (frame.generation, frame.epoch)):
                    self._playback._pending_ready_cue_binding = None
            elif self._cue_binding is not None and self._playback.cue_current(frame) and not self._cue_failed and self._cue_wrote:
                emit("cue_finished", name=frame.cue_name, generation=frame.generation, epoch=frame.epoch)
            if frame.end:
                if (frame.cue_name == "ready"
                        and self._playback._ready_cue_binding == (frame.generation, frame.epoch)):
                    self._playback._ready_cue_binding = None
                self._cue_binding = None
        elif direction is FrameDirection.DOWNSTREAM and isinstance(frame, ReplyFinished):
            binding = frame.binding
            if (binding.get("generation"), binding.get("epoch")) == (self._playback.generation, self._playback.epoch):
                self._playback._reply_active = False
                self._playback.cancel_cues()
            if (not self._reply_failed
                    and (binding.get("generation"), binding.get("epoch")) == (self._playback.generation, self._playback.epoch)):
                name = "error" if not frame.successful or binding.get("outcome") == "failed" else "complete" if binding.get("outcome") == "completed" else None
                if name:
                    await self._playback.queue_cue(name, binding["generation"])
        # Upstream queues this marker with PCM and forwards it only when its
        # output task reaches it. Binding at process_frame would race old audio.
        if direction is FrameDirection.DOWNSTREAM and isinstance(frame, TTSStartedFrame):
            self._timing = frame.metadata.get("obsidience_timing")
            self._binding = frame.metadata.get("obsidience_output")
            self._first_write = False
            self._reply_failed = False
        elif direction is FrameDirection.DOWNSTREAM and isinstance(frame, (TTSStoppedFrame, BotStoppedSpeakingFrame)):
            self._output_level("idle", 0.0)
        await super().push_frame(frame, direction)

    def _output_level(self, status: str, level: float) -> None:
        binding = self._binding
        if (binding is not None and self._playback is not None
                and (binding["generation"], binding["epoch"])
                == (self._playback.generation, self._playback.epoch)):
            emit("output_audio", playback_id=binding["playback_id"],
                 generation=binding["generation"], status=status, level=round(level, 4))

    async def write_audio_frame(self, frame) -> bool:
        is_cue = isinstance(frame, CueAudioFrame)
        if is_cue and (self._cue_binding is None or not self._playback.cue_current(self._cue_binding)):
            return False
        timing = self._timing
        binding = self._binding
        def current_reply() -> bool:
            return (binding is not None and self._playback is not None
                    and (binding["generation"], binding["epoch"])
                    == (self._playback.generation, self._playback.epoch))
        if isinstance(frame, TTSAudioRawFrame) and not current_reply():
            # An opening chirp may outlive natural interruption. Any old TTS
            # already queued behind it must still be discarded.
            return False
        try:
            written = await super().write_audio_frame(frame)
        except Exception:
            if is_cue:
                self._cue_failed = True
            else:
                self._reply_failed = True
            if not is_cue and current_reply():
                self._playback.cancel_cues()
            if not is_cue:
                self._output_level("idle", 0.0)
            raise
        if not written:
            if is_cue:
                self._cue_failed = True
            else:
                self._reply_failed = True
                if current_reply():
                    self._playback.cancel_cues()
        if is_cue:
            if written and not self._cue_wrote:
                marker = self._cue_binding
                self._cue_wrote = True
                emit("cue_started", name=marker.cue_name, generation=marker.generation, epoch=marker.epoch)
            return written
        if written and not self._first_write and self._playback is not None:
            self._first_write = True
            self._playback.record_timing("first_output_write", timing, since="first_pcm_ns")
        if written and isinstance(frame, TTSAudioRawFrame):
            # The existing transport writes 40 ms PCM chunks at playback pace.
            # RMS follows the spoken syllables without another capture stream,
            # FFT, audio copy to the UI, or waiting for more synthesis.
            samples = np.frombuffer(frame.audio, dtype="<i2").astype(np.float32)
            rms = float(np.sqrt(np.mean(samples * samples))) / 32768.0 if samples.size else 0.0
            self._output_level("speaking", min(1.0, 3.0 * rms ** 0.65))
        return written


def emit(kind: str, **payload: Any) -> None:
    print(json.dumps({"type": kind, **payload}, ensure_ascii=False), flush=True)


class UtteranceNeMoSTTService(NemoSTTService):
    """Start voiced utterances with fresh ASR context and their onset audio."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._preroll = bytearray()
        self._recognized_since_stop = False

    async def _handle_transcription(self, transcript, is_final, language=None):
        if transcript.strip():
            self._recognized_since_stop = True
        await super()._handle_transcription(transcript, is_final, language)

    async def process_audio_frame(self, frame, direction) -> None:
        if not self._is_vad_active:
            # 320 ms of mono s16/16 kHz, including the first 100 ms before
            # Silero confirms onset. Never retain an unbounded idle recording.
            self._preroll.extend(frame.audio)
            del self._preroll[:-10_240]
        # Preserve recognition when quiet speech falls below VAD confidence.
        await super().process_audio_frame(frame, direction)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        if isinstance(frame, VADUserStartedSpeakingFrame):
            preroll = bytes(self._preroll)
            self._preroll.clear()
            # Long silence suppresses short words in this streaming model.
            # Reset at actual onset, but never replay text already recognized
            # before VAD: that existing unvoiced path owns the utterance.
            reset = not self._is_vad_active and not self._recognized_since_stop
            if reset:
                async with self._model_lock:
                    self._model.reset_state()
                self.audio_buffer.clear()
            await super().process_frame(frame, direction)
            if reset:
                # Keep NeMo's existing 4 x 20 ms batching and encoder shift.
                for offset in range(0, len(preroll), 640):
                    await super().process_audio_frame(
                        InputAudioRawFrame(preroll[offset:offset + 640], SAMPLE_RATE, 1),
                        direction,
                    )
            return
        await super().process_frame(frame, direction)
        if isinstance(frame, VADUserStoppedSpeakingFrame):
            # NeMo resets its caches on this same edge. Partial batches belong
            # to that finished utterance, never to the next one.
            self.audio_buffer.clear()
            self._recognized_since_stop = False
        if isinstance(frame, (VADUserStoppedSpeakingFrame, ListeningModeFrame,
                              EndFrame, CancelFrame)):
            self._preroll.clear()


class ObsidienceNeMoTurnTakingService(NeMoTurnTakingService):
    """Close recognized and empty VAD turns without leaving speech latched."""

    def __init__(self, *, timing: SpeechInputTiming | None = None,
                 playback: PlaybackCommands | None = None,
                 mode: str = "realtime", mode_revision: int = 0,
                 wake_word: str = "Computer", **kwargs: Any) -> None:
        # STT audio and VAD share its system-frame FIFO, but transcription
        # frames use a separate downstream queue. Consume text inline so a
        # VAD stop cannot overtake recognized words before finalization.
        super().__init__(enable_direct_mode=True, **kwargs)
        self._timing = timing
        self._playback = playback
        self._transcript_timeout: asyncio.Task[None] | None = None
        self.mode = mode
        self.mode_revision = mode_revision
        self._wake_pattern = re.compile(
            rf"(?<!\w){re.escape(wake_word.strip() or 'Computer')}(?!\w)", re.IGNORECASE,
        )
        self._wake_prefix = ""
        self._wake_address: int | None = 0
        self._wake_scanned = 0
        self._wake_pending = False
        self._wake_heard_at: float | None = None
        self._wake_confirm: asyncio.Task[None] | None = None
        self._wake_open = False
        self._wake_timeout: asyncio.Task[None] | None = None
        self._mode_waiting_for_stop = False
        self._wake_cue_eligible = False

    async def _reset_wake_scan(self, *, segment_start: bool) -> None:
        confirm, self._wake_confirm = self._wake_confirm, None
        if confirm is not None and confirm is not asyncio.current_task():
            await self.cancel_task(confirm)
        self._wake_prefix = ""
        self._wake_scanned = 0
        self._wake_pending = False
        if segment_start or self._wake_heard_at is None:
            self._wake_address, self._wake_heard_at = 0, None
        else:
            # Ongoing speech: only a later pause can start an address.
            self._wake_address = None

    def _classify_wake(self, *, final: bool = False) -> str | None:
        """Return command text after an accepted address, else None."""
        decision, end, self._wake_scanned, rejected = classify_wake(
            self._wake_prefix, self._wake_address, self._wake_scanned,
            self._wake_pattern, final=final,
        )
        for reason in rejected:
            # Counts only: rejected speech never leaves the worker.
            emit("wake_rejected", reason=reason, mode_revision=self.mode_revision)
        self._wake_pending = decision == "pending"
        return self._wake_prefix[end:] if decision == "accept" else None

    async def _confirm_wake(self) -> None:
        try:
            await asyncio.sleep(WAKE_CONFIRM_SECS)
            self._wake_confirm = None
            if (self.mode == "wake" and not self._wake_open and self._wake_pending
                    and not self._mode_waiting_for_stop):
                text = self._classify_wake(final=True)
                if text is not None:
                    await self._open_wake(text)
        finally:
            if self._wake_confirm is asyncio.current_task():
                self._wake_confirm = None

    async def _open_wake(self, text: str) -> str:
        text = text.lstrip(WAKE_STRIP)
        self._wake_open = True
        await self._reset_wake_scan(segment_start=False)
        if self._timing is not None:
            self._timing.onset()
        emit("wake_detected", mode_revision=self.mode_revision,
             speech_sequence=self._timing.sequence if self._timing else 0)
        self._wake_timeout = self.create_task(self._expire_wake(), name="wake-command-window")
        # NeMo's bot flag includes the output queue's idle delay plus its
        # own stop grace. A completed reply's closing cue extends that tail.
        # Snapshot the actual reply owner before interruption invalidates
        # it, so immediate follow-ups chirp and true speech barge-in stays quiet.
        reply_active = (self._playback._reply_active if self._playback is not None
                        else self._bot_speaking)
        self._wake_cue_eligible = not any(c.isalnum() for c in text) and not reply_active
        if not self._have_sent_user_started_speaking:
            await self._handle_user_interruption(UserStartedSpeakingFrame())
            self._have_sent_user_started_speaking = True
        return text

    async def _wake_delta(self, text: str) -> str | None:
        """Track one unaddressed ASR delta; return command text once addressed."""
        now = time.monotonic()
        words = any(c.isalnum() for c in text)
        if self._wake_pending:
            confirm, self._wake_confirm = self._wake_confirm, None
            if confirm is not None:
                await self.cancel_task(confirm)
        if (words and self._wake_heard_at is not None
                and now - self._wake_heard_at >= WAKE_PAUSE_SECS):
            # A pause confirms a trailing name and opens a possible address.
            if self._wake_pending:
                command = self._classify_wake(final=True)
                if command is not None:
                    return command + text
            self._wake_address = len(self._wake_prefix)
        if words:
            self._wake_heard_at = now
        self._wake_prefix += text
        if len(self._wake_prefix) > 512:
            dropped = len(self._wake_prefix) - 512
            self._wake_prefix = self._wake_prefix[dropped:]
            self._wake_scanned = max(0, self._wake_scanned - dropped)
            if self._wake_address is not None:
                self._wake_address = (self._wake_address - dropped
                                      if self._wake_address >= dropped else None)
        command = self._classify_wake()
        if self._wake_pending:
            self._wake_confirm = self.create_task(self._confirm_wake(), name="wake-confirm")
        return command

    async def _close_wake(self) -> None:
        timeout, self._wake_timeout = self._wake_timeout, None
        if timeout is not None and timeout is not asyncio.current_task():
            await self.cancel_task(timeout)
        await self._reset_wake_scan(segment_start=not self._vad_user_speaking)
        self._wake_open = False
        self._wake_cue_eligible = False

    async def _expire_wake(self) -> None:
        try:
            await asyncio.sleep(WAKE_COMMAND_WAIT_SECS)
            if not self._user_speaking_buffer.strip():
                await self._close_wake()
                if self._have_sent_user_started_speaking and not self._vad_user_speaking:
                    await self._handle_user_interruption(UserStoppedSpeakingFrame())
                    self._have_sent_user_started_speaking = False
                emit("wake_idle", mode_revision=self.mode_revision)
        finally:
            if self._wake_timeout is asyncio.current_task():
                self._wake_timeout = None

    async def _handle_transcription(self, frame, direction) -> None:
        # STT stays resident. Unaddressed words never enter NeMo's command
        # buffer, interruption frames, UI events or the conversation owner.
        if self._mode_waiting_for_stop:
            return
        if self.mode == "wake" and not self._wake_open:
            command = await self._wake_delta(frame.text)
            if command is None:
                return
            frame.text = await self._open_wake(command)
        if self._wake_open and not self._user_speaking_buffer.strip():
            # NeMo may return punctuation after the name in a later delta.
            frame.text = frame.text.lstrip(WAKE_STRIP)
        if self._wake_open and any(character.isalnum() for character in frame.text):
            self._wake_cue_eligible = False
            timeout, self._wake_timeout = self._wake_timeout, None
            if timeout is not None:
                await self.cancel_task(timeout)
        if frame.text.strip():
            await super()._handle_transcription(frame, direction)

    async def _handle_completed_text(self, completed_text, direction, is_final=True):
        if not any(character.isalnum() for character in completed_text):
            return
        await super()._handle_completed_text(completed_text, direction, is_final)
        if is_final and self.mode == "wake":
            await self._close_wake()

    async def push_frame(self, frame: Frame, direction=FrameDirection.DOWNSTREAM) -> None:
        if isinstance(frame, (UserStartedSpeakingFrame, UserStoppedSpeakingFrame,
                              StartInterruptionFrame, TranscriptionFrame)):
            frame.metadata["obsidience_mode_revision"] = self.mode_revision
        if (self._timing is not None and self._timing.sequence > 0
                and isinstance(frame, (UserStartedSpeakingFrame, UserStoppedSpeakingFrame, StartInterruptionFrame))):
            frame.metadata["obsidience_speech_sequence"] = self._timing.sequence
        if (self._timing is not None and direction is FrameDirection.DOWNSTREAM
                and isinstance(frame, TranscriptionFrame) and frame.text.strip()
                and not (frame.text.startswith("(") and frame.text.endswith(")"))):
            frame.metadata["obsidience_speech_timing"] = self._timing.finish()
        if isinstance(frame, StartInterruptionFrame):
            frame.metadata["obsidience_wake_ready"] = self._wake_cue_eligible
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
            if self._user_speaking_buffer.strip() and not self._vad_user_speaking:
                # A gap in recognized words is not silence while VAD still
                # hears speech. Keep the fallback for late, unvoiced ASR only.
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
        if isinstance(frame, ListeningModeFrame):
            waiting = self._vad_user_speaking
            await self._cancel_transcript_timeout()
            await self._close_wake()
            self.reset()
            self._mode_waiting_for_stop = waiting
            self.mode, self.mode_revision = frame.mode, frame.revision
            if self._timing is not None:
                self._timing.discard()
            emit("mode_applied", mode=self.mode, mode_revision=self.mode_revision)
            return
        if isinstance(frame, (EndFrame, CancelFrame)):
            await self._close_wake()
        if isinstance(frame, VADUserStoppedSpeakingFrame):
            if self.mode == "wake" and not self._wake_open and self._wake_pending:
                # Silence after a trailing name confirms it as an address.
                command = self._classify_wake(final=True)
                if command is not None:
                    await self._open_wake(command)
            await self._reset_wake_scan(segment_start=True)
            self._mode_waiting_for_stop = False
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
        if not self._have_sent_user_started_speaking:
            await self._handle_user_interruption(UserStartedSpeakingFrame())
            self._have_sent_user_started_speaking = True
        emit("transcript_partial", text=transcript,
             mode_revision=self.mode_revision,
             **({"speech_sequence": self._timing.sequence} if self._timing else {}))
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
        self._output_binding = None
        config = root / "english.yaml"
        voice_path = root / "voices" / f"{voice}.safetensors"
        if not config.is_file() or not voice_path.is_file():
            raise FileNotFoundError("Pocket TTS config or selected voice is missing")
        # Small streaming batches start sooner without a 16-thread CPU pool.
        # Four threads also preserve the GPU ASR's measured batch latency.
        torch.set_num_threads(max(1, min(4, (os.cpu_count() or 8) // 2)))
        self._model = TTSModel.load_model(
            config=config,
            temp=0.3,
            sampler_decode_steps=5 if voice == "starfleet" else 1,
        )
        self._model.to("cpu")
        self._voice_state = self._model.get_state_for_audio_prompt(str(voice_path))
        self._synthesis_lock = threading.Lock()

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        if isinstance(frame, TTSSpeakFrame):
            self._timing = frame.metadata.get("obsidience_timing")
            self._output_binding = frame.metadata.get("obsidience_output")
        await super().process_frame(frame, direction)

    async def run_tts(self, text: str) -> AsyncGenerator[Frame, None]:
        clean = " ".join(text.split())[:4_000]
        if not clean:
            return

        timing = self._timing
        output_binding = dict(self._output_binding) if isinstance(self._output_binding, dict) else None
        if timing is not None:
            timing["tts_started_ns"] = time.monotonic_ns()
        first_pcm = True
        successful = True
        pcm_bytes = 0

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[bytes | BaseException | None] = asyncio.Queue()
        cancelled = threading.Event()

        def synthesize() -> None:
            try:
                # Pocket's generator is not thread-safe and only joins its
                # native workers when consumed to completion. Cancel its latent
                # producer cooperatively, then drain its ordinary cleanup path.
                with self._synthesis_lock:
                    if cancelled.is_set():
                        return
                    owner_thread = threading.get_ident()

                    def cancel_generation(_module, _inputs) -> None:
                        # Pocket catches producer errors, stops the decoder and
                        # joins it. Stop at a Python boundary in that producer,
                        # never during the caller's initial prompt preparation.
                        if cancelled.is_set() and threading.get_ident() != owner_thread:
                            raise InterruptedError("Speech synthesis cancelled")

                    hook = self._model.flow_lm.conditioner.register_forward_pre_hook(cancel_generation)
                    try:
                        for chunk in self._model.generate_audio_stream(self._voice_state, clean):
                            if cancelled.is_set():
                                continue
                            samples = chunk.detach().float().cpu().numpy().reshape(-1)
                            loop.call_soon_threadsafe(queue.put_nowait, _speech_pcm(samples))
                    finally:
                        hook.remove()
            except BaseException as exc:
                if not cancelled.is_set():
                    loop.call_soon_threadsafe(queue.put_nowait, exc)
            finally:
                if not cancelled.is_set():
                    loop.call_soon_threadsafe(queue.put_nowait, None)

        worker = threading.Thread(target=synthesize, name="pocket-tts", daemon=False)
        worker.start()
        started = TTSStartedFrame()
        started.metadata["obsidience_timing"] = timing
        started.metadata["obsidience_output"] = output_binding
        try:
            yield started
            while True:
                item = await queue.get()
                if item is None:
                    break
                if isinstance(item, BaseException):
                    # Exception text can contain owner text or private paths.
                    # Preserve only this synthesis's exact playback identity.
                    successful = False
                    error = ErrorFrame(error="Pocket TTS speech delivery failed")
                    error.metadata["obsidience_playback_error"] = output_binding
                    yield error
                    break
                if first_pcm and self._playback is not None:
                    first_pcm = False
                    self._playback.record_timing("first_pcm", timing, since="tts_started_ns")
                pcm_bytes += len(item)
                yield TTSAudioRawFrame(item, TTS_SAMPLE_RATE, 1)
        finally:
            cancelled.set()
            await asyncio.to_thread(worker.join, 2)
        if pcm_bytes % CHUNK_BYTES:
            yield TTSAudioRawFrame(b"\0" * (-pcm_bytes % CHUNK_BYTES), TTS_SAMPLE_RATE, 1)
        yield TTSStoppedFrame()
        if output_binding is not None:
            yield ReplyFinished(output_binding, successful and pcm_bytes > 0)


class PlaybackCommands:
    """One pending Task reply, invalidated before preparation or synthesis."""

    def __init__(self) -> None:
        self.generation = -1
        self.epoch = 0
        self._queued: tuple[int, int, str, dict | None, str, str | None] | None = None
        self._preparing: asyncio.Task | None = None
        self._controller_ready = asyncio.Event()
        self._startup_pending = True
        self._cue_assets = load_assets(Path(__file__).resolve().parents[3] / "state/realtime-cues")
        self._ready_cue_binding: tuple[int, int] | None = None
        self._pending_ready_cue_binding: tuple[int, int] | None = None
        self._output = None
        self._turn_taking = None
        self._reply_active = False

    def cancel_cues(self) -> None:
        self._ready_cue_binding = None
        self._pending_ready_cue_binding = None

    def cue_current(self, marker) -> bool:
        turn = self._turn_taking
        if marker.cue_name == "ready" and self._ready_cue_binding == (marker.generation, marker.epoch):
            return True
        # Harness's natural-speech cancellation may arrive before the queued
        # marker. It must not delay this local acknowledgement. Command text
        # still suppresses an unstarted cue; explicit cancellation clears both
        # pending and started bindings.
        pending_ready = (marker.cue_name == "ready"
                         and self._pending_ready_cue_binding == (marker.generation, marker.epoch))
        return (((marker.generation, marker.epoch) == (self.generation, self.epoch) or pending_ready)
                and not (turn and turn._user_speaking_buffer.strip())
                and (marker.cue_name != "ready" or (not self._reply_active and turn and turn._wake_open and turn._wake_cue_eligible)))

    async def queue_cue(self, name: str, generation: int) -> None:
        pcm = self._cue_assets.get(name) if isinstance(name, str) else None
        if not pcm or type(generation) is not int or generation != self.generation or self._output is None:
            return
        marker = CueMarker(name, generation, self.epoch)
        if not self.cue_current(marker):
            return
        if name == "ready":
            self._pending_ready_cue_binding = (marker.generation, marker.epoch)
        # Admit ordinary frames to the existing output processor: TTS
        # synthesis gaps and zero-PCM failures must not hold cue delivery.
        for frame in (marker, CueAudioFrame(pcm, 24000, 1), CueMarker(name, generation, self.epoch, True)):
            await self._output.queue_frame(frame)

    async def cue(self, task: PipelineTask, command: dict) -> None:
        name, generation = command.get("name"), command.get("generation")
        await self.queue_cue(name, generation)

    def invalidate(self, generation: int | None = None, *, preserve_ready: bool = False) -> bool:
        if generation is not None and (
            type(generation) is not int or generation < self.generation
        ):
            return False
        if generation is None or self._controller_ready.is_set():
            self._startup_pending = False
        if not preserve_ready:
            self.cancel_cues()
        self._reply_active = False
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

    def speak(self, task: PipelineTask, command: dict) -> None:
        generation = command.get("generation")
        text = " ".join(str(command.get("text", "")).split())[:4_000]
        if type(generation) is not int or generation < self.generation or not text:
            return
        self._reply_active = True
        self._startup_pending = False
        self._controller_ready.set()
        self.generation = generation
        self.epoch += 1
        timing = self._timing_context(command)
        self.record_timing("speech_received", timing)
        self._queued = (generation, self.epoch, text, timing, command.get("playback_id", "startup"), command.get("outcome"))
        if self._preparing is None or self._preparing.done():
            self._preparing = asyncio.create_task(
                self._prepare(task), name="speech-playback-prepare",
            )

    async def startup(self, task: PipelineTask, text: str) -> None:
        # Speak once the pipeline starts. Reconnecting speech sends no initial
        # cancellation, so waiting for one deferred this announcement until a
        # later STOP or typed turn. A command received before start still sets
        # the generation; earlier user activity supersedes the announcement.
        if not text.strip():
            self._startup_pending = False
            return
        if self._startup_pending:
            self.speak(task, {"generation": self.generation, "text": text})

    async def _prepare(self, task: PipelineTask) -> None:
        try:
            while self._queued is not None:
                generation, epoch, text, timing, playback_id, outcome = self._queued
                self._queued = None
                # Capture already uses the resident AEC feed, including while
                # waiting for a wake word or hearing other speaker playback.
                if (generation, epoch) != (self.generation, self.epoch):
                    continue
                self.record_timing("aec_ready", timing, since="received_ns")
                frame = TTSSpeakFrame(text)
                frame.metadata["obsidience_playback"] = (generation, epoch)
                frame.metadata["obsidience_timing"] = timing
                frame.metadata["obsidience_output"] = {
                    "generation": generation, "epoch": epoch, "playback_id": playback_id, "outcome": outcome,
                }
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
            self.playback.invalidate(preserve_ready=True)
        await super().process_frame(frame, direction)
        sequence = frame.metadata.get("obsidience_speech_sequence")
        correlation = {"speech_sequence": sequence} if type(sequence) is int and sequence > 0 else {}
        revision = frame.metadata.get("obsidience_mode_revision")
        if type(revision) is int:
            correlation["mode_revision"] = revision
        if isinstance(frame, TranscriptionFrame):
            text = " ".join(frame.text.split())
            if text and not (text.startswith("(") and text.endswith(")")):
                timing = frame.metadata.get("obsidience_speech_timing")
                emit("transcript_final", text=text, **correlation,
                     **({"speech_timing": timing} if timing else {}))
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
    task: PipelineTask,
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
            if kind == "cue":
                await playback.cue(task, command)
            elif kind == "speak":
                playback.speak(task, command)
            elif kind == "cancel":
                if not playback.invalidate(
                    command.get("generation"), preserve_ready=command.get("stop_playback", True) is False,
                ):
                    continue
                if command.get("stop_playback", True) is True:
                    frame = StartInterruptionFrame()
                    frame.metadata["obsidience_playback_cancel"] = True
                    await task.queue_frame(frame)
            elif kind == "stop":
                await playback.close()
                await task.queue_frame(EndFrame())
                return
            elif kind == "mode" and command.get("mode") in {"wake", "realtime"}:
                revision = command.get("mode_revision")
                if type(revision) is int and revision >= 0:
                    playback.cancel_cues()
                    playback.epoch += 1
                    playback._turn_taking._wake_cue_eligible = False
                    await task.queue_frame(ListeningModeFrame(command["mode"], revision))
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
            audio_in_channels=2 if args.input_channel == "left" else 1,
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
        ), playback=playback, input_channel=args.input_channel,
    )
    stt = UtteranceNeMoSTTService(
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
        playback=playback,
        mode=args.mode,
        mode_revision=args.mode_revision,
        wake_word=args.wake_word,
        use_vad=True,
        use_diar=False,
        max_buffer_size=2,
        bot_stop_delay=0.5,
        backchannel_phrases=None,
    )
    playback._turn_taking = turn_taking
    bridge = ObsidienceTaskBridge(playback)
    tts = PocketTTSService(root=Path(args.pocket_root), voice=args.voice, playback=playback)
    playback._output = transport.output()
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            turn_taking,
            bridge,
            tts,
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

    @task.event_handler("on_pipeline_error")
    async def on_pipeline_error(task: PipelineTask, frame: ErrorFrame) -> None:
        binding = frame.metadata.get("obsidience_playback_error")
        if (not isinstance(binding, dict)
                or type(binding.get("generation")) is not int
                or type(binding.get("epoch")) is not int
                or (binding["generation"], binding["epoch"])
                != (playback.generation, playback.epoch)
                or not isinstance(binding.get("playback_id"), str)
                or not 0 < len(binding["playback_id"]) <= 96
                or any(not (c.isascii() and (c.isalnum() or c in "-_:."))
                       for c in binding["playback_id"])):
            return
        emit("playback_error", generation=binding["generation"], epoch=binding["epoch"],
             playback_id=binding["playback_id"], code="pocket_tts_failed")

    @task.event_handler("on_pipeline_started")
    async def on_pipeline_started(task: PipelineTask, frame: Frame) -> None:
        emit("transport_ready", transport="pipecat.local")
        emit(
            "runtime_ready",
            mode=args.mode,
            mode_revision=args.mode_revision,
            asr="nvidia/nemotron-speech-streaming-en-0.6b",
            asr_chunk_ms=160,
            tts="pocket-tts-3.0.2-cpu",
            voice=args.voice,
            cues=sorted(playback._cue_assets),
        )
        await playback.startup(task, args.startup_confirmation)

    commands = asyncio.create_task(
        command_loop(task, playback), name="speech-commands",
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
    result.add_argument("--input-channel", choices=("mono", "left"), default="mono")
    result.add_argument("--startup-confirmation", default="Realtime active.")
    result.add_argument("--wake-word", default="Computer")
    result.add_argument("--mode", choices=("wake", "realtime"), default="realtime")
    result.add_argument("--mode-revision", type=int, default=0)
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
