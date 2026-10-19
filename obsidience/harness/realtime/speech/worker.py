"""Upstream Pipecat/NeMo speech connection to Obsidience's conversation lane."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import copy
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

from nemo.agents.voice_agent.pipecat.services.nemo.streaming_asr import ASRResult, NemoStreamingASRService
from nemo.agents.voice_agent.pipecat.services.nemo.stt import (
    NemoSTTService,
    NeMoSTTInputParams,
)
from nemo.agents.voice_agent.pipecat.services.nemo.utils import CacheFeatureBufferer
from nemo.agents.voice_agent.pipecat.services.nemo.turn_taking import (
    NeMoTurnTakingService,
)
from nemo.collections.asr.parts.context_biasing.boosting_graph_batched import BoostingTreeModelConfig
from nemo.collections.asr.parts.submodules.rnnt_decoding import RNNTBPEDecoding
from nemo.collections.asr.parts.utils.rnnt_utils import Hypothesis
from omegaconf import OmegaConf, open_dict
from pipecat.audio.turn.base_turn_analyzer import EndOfTurnState
from pipecat.audio.turn.smart_turn.base_smart_turn import SmartTurnParams
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
    StartFrame,
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
from pipecat.utils.time import time_now_iso8601
from pipecat.transports.local.audio import (
    LocalAudioInputTransport,
    LocalAudioOutputTransport,
    LocalAudioTransport,
    LocalAudioTransportParams,
)
from pocket_tts import TTSModel
from .cues import CueAudioFrame, CueMarker, ReplyFinished, load_assets, CHUNK_BYTES, OPENING_CUES

SAMPLE_RATE = 16_000
TTS_SAMPLE_RATE = 24_000
TRANSCRIPT_IDLE_SECS = 0.7
# Smart Turn (CPU ONNX) judges each Silero pause from the audio. NeMo resets
# its ASR context on the VAD stop edge, so it receives that edge only once the
# turn ends; shorter pauses stay inside one utterance. v3.2 (artifacts.lock)
# replaced Pipecat's bundled v3.1 after replay; "bundled" selects v3.1 again.
SMART_TURN_MODEL = "/var/lib/ai/models/obsidience-realtime/smart-turn/smart-turn-v3.2-cpu.onnx"
SMART_TURN_VAD_STOP_SECS = 0.2
# Silence that ends a turn the model judged incomplete, and the longer bound
# while the recognized text cannot end a turn yet (no words yet, a dangling
# end such as "what's" or "the", or only the wake-word address).
SMART_TURN_FALLBACK_SECS = 1.8
SMART_TURN_PENDING_SECS = 3.0
# NeMo emits a final word up to about 1 s of audio after Silero's last voiced
# frame. An earlier end of turn decodes the rest of that tail from silence in
# one encoder call before NeMo resets, instead of waiting for it. Replay of 256
# owner utterances (2026-10-19, asr-v2, one 80 ms step per batch): 0.7 s still
# cut the last word of 5 and 0.32 s (Pipecat's reference padding) of 30; the
# latest word came 10 steps (0.8 s) into the tail. In one call the length is
# nearly free (0.9 s: 17 ms, 1.2 s: 16 ms; stepwise 0.7 s took ~105 ms).
ASR_TAIL_SECS = 1.2
# Early final (realtime_asr_early_final, default off until the Harness consumes
# it): at Silero's 200 ms stop edge, before Smart Turn's verdict, a copy of the
# ASR stream decodes the same tail and the worker emits
# {"type": "speech_early_final", "text", "speech_sequence", "candidate_revision",
#  "mode_revision", "flush_ms"} with the addressed words a final would carry
# now. The real stream, its final and turn-taking are unchanged; later partials
# or the final supersede it (adopt only identical words, as with partials).
# Desktop ASR skips its GPU steps in sustained silence (2026-10-18: 12.5 steps/s
# kept the shared RTX 4000 ~11% busy and cost tensor-split Gemma ~13%, also while
# it answered). A voiced onset after silence already resets NeMo and replays the
# 320 ms pre-roll, so skipped silence cannot change what that utterance decodes;
# the stop edge decodes its own ASR tail. Recognition continues for the unvoiced
# transcript pause after a VAD stop or recognized word, so speech that never
# reaches Silero's onset still finishes an utterance already being recognized.
# realtime_asr_silence_gate = false restores continuous ASR.
ASR_SILENCE_HOLD_SECS = TRANSCRIPT_IDLE_SECS
# Encoder precision. bfloat16 weights, caches and features (NVIDIA's streaming
# pipeline default for this model) cut the encoder step 10.2 -> 6.3 ms and the
# whole step 14.5 -> 10.0 ms on the idle chipset RTX 4000, with the same replay
# WER (2026-10-19, asr-v2 replay). The RNNT decoder and joint stay float32.
# realtime_asr_dtype = "float32" restores full-precision weights.
ASR_DTYPES = {"bfloat16": torch.bfloat16, "float32": torch.float32}
# Desktop phrase boosting (NeMo GPU-PB in the label-looping CUDA-graph greedy
# decoder): the wake word plus the owner's artist, channel and application
# names, one phrase per line ('#' comments), owner-reviewed, built by
# gpu-tuning-20261018/asr-v2/build_phrases.py. Replay (2026-10-19): names cut
# synthetic desk-command WER 8.5 -> 7.3 % at no step cost; song titles of
# everyday words were inserted into ordinary speech. A missing file boosts the
# wake word alone; realtime_asr_phrases names another file, false restores
# NeMo's legacy greedy decoder.
ASR_PHRASES = Path(__file__).resolve().parents[3] / "state/realtime-asr-phrases.txt"
ASR_PHRASES_MAX = 2_000
ASR_BOOST_ALPHA = 1.0
# A trailing filled pause signals that the speaker is still formulating the
# request. Reuse the existing pending-text grace, including after ASR tail
# decoding, instead of accepting Smart Turn's early COMPLETE or delaying every turn.
_HESITATION_END = re.compile(r"(?:^|\s)(?:u+h+|u+m+|erm+)$")
_DANGLING_END = re.compile(
    r"(?:^|\s)(?:what's|whats|what is|you said|the|a|an|and|or|but|to|of|for|with|my|your)$",
)
# Complete short replies the model can score incomplete ("Yes." 0.14): when the
# recognized text is exactly one of these, the turn ends at the model's verdict.
SHORT_REPLIES = frozenset({
    "yes", "no", "yeah", "yep", "nope", "okay", "ok", "sure", "stop", "thanks",
    "thank you", "never mind", "nevermind", "cancel", "correct", "right",
})
WAKE_COMMAND_WAIT_SECS = 8
SEMANTIC_TEXT_MAX_CHARS = 2_000
# A bare wake name starts a segment or follows a recognized-word pause,
# optionally after hey/ok/okay. Explicit "hey <name>" also addresses mid-segment.
WAKE_PAUSE_SECS = 0.4
# A name ending the recognized text may still become "computer's"; the next
# ASR delta normally arrives within one or two 80-160 ms steps.
WAKE_CONFIRM_SECS = 0.35
# A CPU keyword spotter (wakeword.py) hears the name ~0.2 s after it ends, well
# before ASR text. At a segment start it chirps and interrupts at once; ASR text
# still opens the command window, or the segment's end drops the spot quietly.
# realtime_wake_spotter = false keeps ASR-only wake detection.
WAKE_SPOTTER_MODEL = "/var/lib/ai/models/obsidience-realtime/wake-word/computer.json"
# Latest spot after the segment's VAD onset: "hey computer", spoken slowly.
WAKE_SPOT_ONSET_SECS = 1.6
WAKE_STRIP = " ,.!?:;—-'’\t\n"
_WAKE_LEAD = re.compile(r"[\W_]*(?:(?:hey|hay|ok|okay)\b[\W_]*)?", re.IGNORECASE)
# Streaming ASR can spell the spoken greeting "hey" as its homophone "hay".
_WAKE_EXPLICIT_LEAD = re.compile(r"(?<!\w)(?:hey|hay)\b[\W_]*$", re.IGNORECASE)
# Short acknowledgements that must not interrupt a playing Realtime reply.
BACKCHANNEL_PHRASES = ("okay", "uh-huh", "mm-hmm", "yeah", "right")
# Speech PCM needs level correction independently of the selected device volume.
# A fixed gain preserves pauses and syllable dynamics across streaming chunks.
TTS_GAIN = 10.0 ** (9.0 / 20.0)
TTS_PEAK_KNEE = 0.85
TTS_PEAK_CEILING = 0.95
# Silence before the next sentence of one streamed reply (owner, 2026-10-08:
# gapless sentences ran together). Whole 40 ms output chunks.
SENTENCE_PAUSE_SECS = 0.2
# Only cleanup stops the input stream, so a capture that delivers no frames has
# stalled: the UMA-8 has hung with its PCM still RUNNING and no kernel error
# (2026-10-06, 2026-10-09). It is reported, never silently waited out.
CAPTURE_STALL_SECS = 5.0
_SENTENCE_PAUSE_PCM = b"\0" * (round(SENTENCE_PAUSE_SECS * TTS_SAMPLE_RATE * 2 / CHUNK_BYTES) * CHUNK_BYTES)
_SENTENCE_END = re.compile(r"[.!?…][\"'”’)\]*_]*$")
# A spoken reply that asks the owner something: "?" before any closing marks.
_QUESTION_END = re.compile(r"\?[\"'”’»)\]}]*$")


def _speech_pcm(samples: np.ndarray, *, gain: float = TTS_GAIN) -> bytes:
    boosted = samples * gain
    magnitude = np.abs(boosted)
    # A continuous soft knee protects unusually loud peaks without chunk-level
    # normalization, lookahead, or an envelope that pumps between chunks.
    headroom = TTS_PEAK_CEILING - TTS_PEAK_KNEE
    protected = np.sign(boosted) * (
        TTS_PEAK_KNEE + headroom * np.tanh((magnitude - TTS_PEAK_KNEE) / headroom)
    )
    boosted = np.where(magnitude > TTS_PEAK_KNEE, protected, boosted)
    return np.rint(boosted * 32767.0).astype("<i2").tobytes()


def _turn_words(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", text.lower().replace("’", "'")))


def turn_text_pending(text: str) -> bool:
    """True for missing words, a dangling phrase or a trailing filled pause."""
    words = _turn_words(text)
    return (not words or _DANGLING_END.search(words) is not None
            or _HESITATION_END.search(words) is not None)


def turn_text_short_reply(text: str) -> bool:
    """True when recognized text is exactly one complete short reply."""
    return _turn_words(text) in SHORT_REPLIES


def smart_turn_analyzer(pending, short_reply, model_path: str | None = None):
    """Load Smart Turn on CPU, or None to keep the fixed pause endpoint.

    A missing or unloadable model is reported once and keeps the fixed pause.

    ``model_path`` None selects Pipecat's bundled v3.1 ONNX.

    ``pending()`` reports whether the recognized command text cannot end a turn;
    ``short_reply()`` whether it is exactly one complete short reply.
    """
    try:
        from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3

        class SmartTurnGate(LocalSmartTurnAnalyzerV3):
            """Bound the model's verdict by silence and by the recognized text."""

            def __init__(self) -> None:
                super().__init__(smart_turn_model_path=model_path, params=SmartTurnParams(
                    # Upstream ends any turn after this much silence past the VAD stop.
                    stop_secs=SMART_TURN_PENDING_SECS - SMART_TURN_VAD_STOP_SECS,
                    # Silero confirms onset 100 ms late; keep the first syllable.
                    pre_speech_ms=300,
                ))
                self._vetoed = False
                # The model has judged this pause (its early end point).
                self._judged = False

            def append_audio(self, buffer: bytes, is_speech: bool) -> EndOfTurnState:
                state = super().append_audio(buffer, is_speech)
                if is_speech:
                    self._vetoed = self._judged = False
                elif state is EndOfTurnState.INCOMPLETE and self._speech_triggered:
                    silence = self._silence_ms / 1000 + SMART_TURN_VAD_STOP_SECS
                    # A complete verdict held for late ASR words ends once they
                    # arrive, a judged pause once its late text is a complete
                    # short reply; an incomplete one ends at the silence fallback.
                    if ((self._vetoed or silence >= SMART_TURN_FALLBACK_SECS
                         or (self._judged and short_reply()))
                            and not pending()):
                        self._clear(EndOfTurnState.COMPLETE)
                        state = EndOfTurnState.COMPLETE
                # Upstream keeps every frame while a turn stays incomplete; the
                # model reads only the last eight seconds.
                horizon = time.time() - self._params.pre_speech_ms / 1000 - self._params.max_duration_secs
                while self._speech_triggered and self._audio_buffer and self._audio_buffer[0][0] < horizon:
                    self._audio_buffer.pop(0)
                return state

            def _process_speech_segment(self, audio_buffer):
                state, result = super()._process_speech_segment(audio_buffer)
                self._judged = True
                if state is EndOfTurnState.COMPLETE and pending():
                    self._vetoed = True
                    state = EndOfTurnState.INCOMPLETE
                elif state is EndOfTurnState.INCOMPLETE and short_reply() and not pending():
                    state = EndOfTurnState.COMPLETE
                return state, result

            def _clear(self, turn_state: EndOfTurnState) -> None:
                super()._clear(turn_state)
                self._vetoed = self._judged = False

        return SmartTurnGate()
    except Exception as exc:
        emit("turn_detector_unavailable", fallback_pause_secs=TRANSCRIPT_IDLE_SECS,
             error=type(exc).__name__)
        return None


def classify_wake(text: str, address: int | None, scanned: int, pattern: re.Pattern,
                  *, final: bool = False) -> tuple[str, int, int, list[str]]:
    """Classify unaddressed wake-word mentions in one speech segment's text.

    ``address`` is where an address may begin (segment start or after a pause);
    only hey/ok/okay may precede the name there. An explicit "hey <name>"
    address may also interrupt ongoing speech. Possessives and contractions
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
        elif (_WAKE_EXPLICIT_LEAD.search(text, 0, match.start()) is not None
              or (address is not None and match.start() >= address
                  and _WAKE_LEAD.fullmatch(text, address, match.start()))):
            return "accept", match.end(), match.end(), rejected
        else:
            rejected.append("mid_sentence")
        scanned = match.end()
    return "none", len(text), scanned, rejected


@dataclass
class ListeningModeFrame(SystemFrame):
    mode: str
    revision: int


@dataclass
class SpeechAdmissionFrame(SystemFrame):
    action: str
    speech_sequence: int
    candidate_revision: int
    mode_revision: int


@dataclass
class SpeechResetFrame(SystemFrame):
    pass


@dataclass
class SpeechPauseFrame(SystemFrame):
    """Silero's stop edge, held while the turn analyzer decides."""
    last_voiced_ns: int | None


@dataclass
class SpeechEarlyFinalFrame(SystemFrame):
    """Words a flushed copy of the ASR stream added at a pause."""
    text: str
    flush_ms: float


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

    def endpoint(self, last_voiced_ns: int | None = None, endpoint_ns: int | None = None) -> None:
        """Record the last VAD speech frame and the end-of-turn decision."""
        if not self._active:
            return
        self._stages = [row for row in self._stages
                        if row["stage"] not in {"last_voiced", "end_of_turn"}]
        onset = next((row["monotonic_ns"] for row in self._stages
                      if row["stage"] == "speech_onset"), 0)
        if type(last_voiced_ns) is int and last_voiced_ns >= onset:
            self._stages.append({"stage": "last_voiced", "monotonic_ns": last_voiced_ns})
        self._stages.append({"stage": "end_of_turn", "monotonic_ns": endpoint_ns
                             if type(endpoint_ns) is int else time.monotonic_ns()})

    def finish(self) -> dict[str, Any]:
        if not self._active:
            self.onset()
        # The first partial can follow the last voiced frame of a short command.
        stages = sorted(self._stages, key=lambda row: row["monotonic_ns"])
        stages.append({"stage": "speech_final", "monotonic_ns": time.monotonic_ns()})
        self._stages = []
        self._active = False
        return {"speech_sequence": self.sequence, "stages": stages}

    def discard(self) -> None:
        self._stages = []
        self._active = False


class NeMoLocalAudioInputTransport(LocalAudioInputTransport):
    """Leave turn interruption to NeMo without replacing Pipecat capture."""

    def __init__(self, *args: Any, input_channel: str = "mono", playback=None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._input_channel = input_channel
        self._playback = playback
        self._last_level_at = 0.0
        self._last_frame_at = 0.0
        self._stall_watch: asyncio.Task | None = None
        self._capture_active = False
        self._last_voiced_ns: int | None = None
        # With a turn analyzer, Silero's stop edge waits here for its verdict.
        self._held_stop: VADUserStoppedSpeakingFrame | None = None

    async def start(self, frame: StartFrame) -> None:
        await super().start(frame)
        self._last_frame_at = time.monotonic()
        if self._stall_watch is None:
            self._stall_watch = self.create_task(self._watch_capture(), name="capture-stall-watch")

    async def cleanup(self) -> None:
        if self._stall_watch is not None:
            await self.cancel_task(self._stall_watch)
            self._stall_watch = None
        await super().cleanup()

    def _audio_in_callback(self, in_data, frame_count, time_info, status):
        # Stamped on PortAudio's thread: a busy event loop is not a stalled device.
        self._last_frame_at = time.monotonic()
        return super()._audio_in_callback(in_data, frame_count, time_info, status)

    async def _watch_capture(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            silent = time.monotonic() - self._last_frame_at
            if silent >= CAPTURE_STALL_SECS:
                emit("input_stalled", seconds=round(silent, 1))
                return

    async def _vad_analyze(self, audio_frame: InputAudioRawFrame) -> VADState:
        state = await super()._vad_analyze(audio_frame)
        if state == VADState.SPEAKING:
            self._last_voiced_ns = time.monotonic_ns()
        return state

    async def push_frame(self, frame: Frame, direction=FrameDirection.DOWNSTREAM) -> None:
        if (direction is FrameDirection.DOWNSTREAM and self._playback is not None
                and isinstance(frame, (VADUserStartedSpeakingFrame, VADUserStoppedSpeakingFrame))
                and frame is not self._held_stop):
            # Raw Silero edges, before the turn analyzer holds a stop: barge-in ducking.
            self._playback.owner_voice(isinstance(frame, VADUserStartedSpeakingFrame))
        if direction is FrameDirection.DOWNSTREAM and isinstance(frame, VADUserStartedSpeakingFrame):
            if self._held_stop is not None:
                # Speech resumed inside the turn: NeMo never saw the pause.
                self._held_stop = None
                return
            frame.metadata["obsidience_onset_ns"] = time.monotonic_ns()
        elif direction is FrameDirection.DOWNSTREAM and isinstance(frame, VADUserStoppedSpeakingFrame):
            if self._params.turn_analyzer is not None and frame is not self._held_stop:
                frame.metadata["obsidience_last_voiced_ns"] = self._last_voiced_ns
                self._held_stop = frame
                # ASR may flush an early final while the verdict is pending.
                await super().push_frame(SpeechPauseFrame(self._last_voiced_ns), direction)
                return
            self._held_stop = None
            endpoint_ns = frame.metadata["obsidience_endpoint_ns"] = time.monotonic_ns()
            last_voiced_ns = frame.metadata.setdefault("obsidience_last_voiced_ns", self._last_voiced_ns)
            if self._params.turn_analyzer is not None and type(last_voiced_ns) is int:
                elapsed = (endpoint_ns - last_voiced_ns) / 1e9
                frame.metadata["obsidience_asr_tail_frames"] = max(0, round((ASR_TAIL_SECS - elapsed) / 0.02))
        await super().push_frame(frame, direction)

    async def _handle_prediction_result(self, result) -> None:
        # Metrics are disabled; never send per-pause metrics frames through ASR.
        return

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
        if vad_state == VADState.QUIET and not emulated and self._held_stop is not None:
            # The turn analyzer (or its silence bound, or lost input) ended the turn.
            await self.push_frame(self._held_stop)


class NeMoLocalAudioTransport(LocalAudioTransport):
    def __init__(self, *args, playback=None, input_channel="mono", **kwargs):
        super().__init__(*args, **kwargs)
        self._playback = playback
        self._input_channel = input_channel

    def input(self) -> FrameProcessor:
        if self._input is None:
            self._input = NeMoLocalAudioInputTransport(
                self._pyaudio, self._params, input_channel=self._input_channel, playback=self._playback,
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
            await self._playback.queue_cue(turn._wake_cue_name, self._playback.generation)

    async def push_frame(self, frame: Frame, direction=FrameDirection.DOWNSTREAM) -> None:
        if direction is FrameDirection.DOWNSTREAM and isinstance(frame, CueMarker):
            if not frame.end:
                self._cue_binding = frame
                self._cue_failed = False
                self._cue_wrote = False
                if frame.cue_name in OPENING_CUES and self._playback.cue_current(frame):
                    self._playback._ready_cue_binding = (frame.generation, frame.epoch)
                if (frame.cue_name in OPENING_CUES
                        and self._playback._pending_ready_cue_binding == (frame.generation, frame.epoch)):
                    self._playback._pending_ready_cue_binding = None
            elif self._cue_binding is not None and self._playback.cue_current(frame) and not self._cue_failed and self._cue_wrote:
                emit("cue_finished", name=frame.cue_name, generation=frame.generation, epoch=frame.epoch)
            if frame.end:
                if (frame.cue_name in OPENING_CUES
                        and self._playback._ready_cue_binding == (frame.generation, frame.epoch)):
                    self._playback._ready_cue_binding = None
                self._cue_binding = None
        elif direction is FrameDirection.DOWNSTREAM and isinstance(frame, ReplyFinished):
            name = self._playback.reply_finished(frame.binding, frame.successful)
            if name and not self._reply_failed:
                await self._playback.close_reply(name, frame.binding["generation"])
        # Upstream queues this marker with PCM and forwards it only when its
        # output task reaches it. Binding at process_frame would race old audio.
        if direction is FrameDirection.DOWNSTREAM and isinstance(frame, TTSStartedFrame):
            binding = frame.metadata.get("obsidience_output")
            if not _same_reply(binding, self._binding):
                # An appended chunk keeps its reply's write-failure state.
                self._reply_failed = False
            self._timing = frame.metadata.get("obsidience_timing")
            self._binding = binding
            self._first_write = False
        elif direction is FrameDirection.DOWNSTREAM and isinstance(frame, (TTSStoppedFrame, BotStoppedSpeakingFrame)):
            # A chunk already appended behind this one continues without an idle gap.
            if not (isinstance(frame, TTSStoppedFrame) and self._playback.reply_continues(self._binding)):
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
        if isinstance(frame, TTSAudioRawFrame) and self._playback is not None:
            # Owner barge-in: duck at once, hold after sustained speech, resume on quiet.
            await self._playback.barge_in_audio(frame, lambda: self._output_level("idle", 0.0))
            if not current_reply():
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
        if (written and not self._first_write and self._playback is not None
                and not isinstance(frame, SentencePauseFrame)):
            self._first_write = True
            self._playback.record_timing("first_output_write", timing, since="first_pcm_ns")
            self._playback.chunk_audible(binding)
        if written and isinstance(frame, TTSAudioRawFrame):
            # The existing transport writes 40 ms PCM chunks at playback pace.
            # RMS follows the spoken syllables without another capture stream,
            # FFT, audio copy to the UI, or waiting for more synthesis.
            samples = np.frombuffer(frame.audio, dtype="<i2").astype(np.float32)
            rms = float(np.sqrt(np.mean(samples * samples))) / 32768.0 if samples.size else 0.0
            self._output_level("speaking", min(1.0, 3.0 * rms ** 0.65))
        return written


def _same_reply(a, b) -> bool:
    return (isinstance(a, dict) and isinstance(b, dict)
            and all(a.get(key) == b.get(key) for key in ("generation", "epoch", "playback_id")))


def emit(kind: str, **payload: Any) -> None:
    print(json.dumps({"type": kind, **payload}, ensure_ascii=False), flush=True)


def load_boost_phrases(path, wake_word: str) -> list[str]:
    """The wake word plus a bounded, de-duplicated phrase file."""
    phrases = [wake_word, wake_word.lower()]
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines() if path else []
    except FileNotFoundError:
        lines = []
    for line in lines:
        line = " ".join(line.split())
        if line and not line.startswith("#") and len(line) <= 80:
            phrases.append(line)
    return list(dict.fromkeys(phrases))[:ASR_PHRASES_MAX]


def phrase_decoding(source, phrases: list[str], *, alpha: float = ASR_BOOST_ALPHA):
    """Greedy label-looping RNNT decoding (CUDA-graph decoder) with GPU-PB.

    Without phrases it is the same greedy search as NeMo's legacy decoder,
    batched on the GPU without per-symbol host synchronization. Per-frame
    alignment logits cost 3 ms per step here (0.5 ms without); StreamingASR
    reads token ids instead.
    """
    model = source.asr_model
    config = copy.deepcopy(model.decoding.cfg)
    with open_dict(config):
        config.preserve_alignments = False
        config.strategy = "greedy_batch"
        config.greedy.loop_labels = True
        config.greedy.use_cuda_graph_decoder = True
        config.greedy.enable_per_stream_biasing = False
        if phrases:
            config.greedy.boosting_tree = OmegaConf.structured(BoostingTreeModelConfig(
                key_phrases_list=list(phrases), use_triton=str(source.device).startswith("cuda"),
            ))
            config.greedy.boosting_tree_alpha = alpha
    return RNNTBPEDecoding(config, model.decoder, model.joint, source.tokenizer)


class StreamingASR(NemoStreamingASRService):
    """NeMo's legacy cache-aware stream whose encoder may run in bfloat16.

    Encoder weights, caches and stored log-mel features share the encoder's
    dtype; the RNNT decoder and joint keep float32, so encoder output is cast
    at that boundary. ``phrase_decoding`` (shared, stateless between calls)
    replaces the legacy per-symbol greedy loop. Stream state is unchanged
    otherwise (see discord.py).
    """

    phrase_decoding = None

    def _reset_cache(self) -> None:
        dtype = next(self.asr_model.encoder.parameters()).dtype
        (self._cache_last_channel, self._cache_last_time,
         self._cache_last_channel_len) = self.asr_model.encoder.get_initial_cache_state(1, dtype=dtype)

    def new_feature_buffer(self) -> CacheFeatureBufferer:
        buffer = CacheFeatureBufferer(
            sample_rate=SAMPLE_RATE, buffer_size_in_secs=self.buffer_size_in_secs,
            chunk_size_in_secs=self.chunk_size_in_secs,
            preprocessor_cfg=self.asr_model.cfg.preprocessor, device=self.device,
        )
        # Features are computed in float32 and stored at encoder precision.
        buffer.feature_buffer = buffer.feature_buffer.to(next(self.asr_model.encoder.parameters()).dtype)
        return buffer

    def _get_best_hypothesis(self, encoded, encoded_len, partial_hypotheses=None):
        encoded = encoded.to(next(self.asr_model.joint.parameters()).dtype)
        if self.phrase_decoding is None:
            return super()._get_best_hypothesis(encoded, encoded_len, partial_hypotheses)
        # Batched NeMo merges continuation text, whereas the streaming adapter
        # consumes per-chunk alignments. Keep only recurrent predictor/boosting
        # state between chunks so neither words nor alignment history repeat.
        previous = [Hypothesis(score=0.0, y_sequence=[], timestamp=[], dec_state=hyp.dec_state)
                    for hyp in partial_hypotheses] if partial_hypotheses else None
        hypotheses = self.phrase_decoding.rnnt_decoder_predictions_tensor(
            encoded, encoded_len, return_hypotheses=True, partial_hypotheses=previous,
        )
        for hyp in hypotheses:
            # This chunk's token ids where transcribe() reads alignments.
            hyp.alignments = [[(None, int(token))] for token in hyp.y_sequence]
        return hypotheses

    def _get_tokens_and_probs_from_alignments(self, alignments):
        if self.phrase_decoding is None:
            return super()._get_tokens_and_probs_from_alignments(alignments)
        # Probabilities only scored EOU/EOB tokens, which this model never emits.
        tokens = [token for frame in alignments for _, token in frame if token != self.blank_id]
        return tokens, [1.0] * len(tokens)

    def transcribe_final(self, audio: bytes) -> ASRResult:
        """Decode an utterance's remaining audio in one encoder call.

        NeMo's final-chunk path (keep_all_outputs): the pre-encode cache and the
        pending lookahead frame from the feature buffer, then the remainder's
        features. Its text continues the hypothesis; the caller then resets.
        """
        started = time.time()
        buffer = self._audio_buffer
        samples = torch.from_numpy(np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0)
        look_back = buffer.n_chunk_look_back
        frames = len(samples) // look_back
        # As CacheFeatureBufferer.update, for a longer chunk: drop the incomplete last frame.
        features = buffer.preprocess(torch.cat([buffer.sample_buffer.sample_buffer[-look_back:], samples]))
        features = features[:, :frames + 1][:, -frames:]
        keep = self.pre_encode_cache_size + buffer.feature_chunk_len
        signal = torch.cat([buffer.feature_buffer[:, -keep:], features.to(buffer.feature_buffer.dtype)], dim=1)
        with torch.no_grad():
            encoded, encoded_len, *_ = self.asr_model.encoder.cache_aware_stream_step(
                processed_signal=signal.unsqueeze(0),
                processed_signal_length=torch.tensor([signal.shape[1]], device=signal.device),
                cache_last_channel=self._cache_last_channel, cache_last_time=self._cache_last_time,
                cache_last_channel_len=self._cache_last_channel_len,
                keep_all_outputs=True, drop_extra_pre_encoded=self.drop_extra_pre_encoded,
            )
        best = self._get_best_hypothesis(encoded, encoded_len, partial_hypotheses=self._previous_hypotheses)
        tokens, _ = self._get_tokens_and_probs_from_alignments(best[0].alignments)
        return ASRResult(text=self.get_text_from_tokens(tokens), is_final=False,
                         processing_time=time.time() - started)


def fork_stream(source: StreamingASR) -> StreamingASR:
    """Copy one stream's mutable decoding state; weights and decoders stay shared."""
    result = copy.copy(source)
    buffer = result._audio_buffer = copy.copy(source._audio_buffer)
    buffer.sample_buffer = copy.copy(source._audio_buffer.sample_buffer)
    buffer.sample_buffer.sample_buffer = source._audio_buffer.sample_buffer.sample_buffer.clone()
    buffer.feature_buffer = source._audio_buffer.feature_buffer.clone()
    result._cache_last_channel = source._cache_last_channel.clone()
    result._cache_last_time = source._cache_last_time.clone()
    result._cache_last_channel_len = source._cache_last_channel_len.clone()
    # NeMo's legacy greedy decoder appends to a partial hypothesis's token list.
    result._previous_hypotheses = [
        Hypothesis(score=hyp.score, y_sequence=list(hyp.y_sequence), timestamp=list(hyp.timestamp),
                   dec_state=hyp.dec_state, last_token=hyp.last_token)
        for hyp in source._previous_hypotheses]
    return result


def final_batches(service: StreamingASR) -> int:
    """Batches in the longest end-of-turn remainder: pending frames plus the tail."""
    return int(ASR_TAIL_SECS / service.chunk_size_in_secs) + 2


def desktop_asr(model: str, *, device: str, dtype: str = "bfloat16",
                phrases: list[str] | None = None, boost_alpha: float = ASR_BOOST_ALPHA) -> StreamingASR:
    """Load, cast, place and warm the one shared ASR model before any capture.

    Restoring straight onto the GPU briefly held a second copy of the weights
    (4.7 GiB reserved on the RTX 4000 shared with Gemma), so restore on the
    CPU, cast the encoder, then move once. Encoder CUDA graphs are captured
    here; they were formerly only a side effect of the Discord adapter.
    """
    service = StreamingASR(model, [70, 1], device="cpu", decoder_type="rnnt", frame_len_in_secs=0.08)
    service.asr_model.encoder.to(ASR_DTYPES[dtype])
    if device != "cpu":
        service.asr_model.to(device)
        service.device = device
    service._audio_buffer = service.new_feature_buffer()
    service.phrase_decoding = (phrase_decoding(service, phrases, alpha=boost_alpha)
                               if phrases is not None else None)
    service.reset_state()  # Caches at the placed device and dtype.
    if device.startswith("cuda"):
        # Ada tensor cores for the float32 parts before graph capture.
        torch.backends.cuda.matmul.fp32_precision = "tf32"
        graphs = service.asr_model.encoder.set_streaming_cuda_graphs()
        silence = bytes(round(SAMPLE_RATE * service.chunk_size_in_secs) * 2)
        with torch.inference_mode():
            # Native capture follows three eager steps; include a later replay.
            # Silence also captures the decoder graphs, first chunk then continuation.
            for _ in range(graphs.warmup_steps + 2):
                service.transcribe(silence)
            # The longest end-of-turn remainder sizes the decoder's graphs once.
            service.transcribe_final(silence * final_batches(service))
        torch.cuda.synchronize(device)
    service.reset_state()
    return service


class UtteranceNeMoSTTService(NemoSTTService):
    """Start voiced utterances with fresh ASR context and their onset audio."""

    def __init__(self, *, reset_on_vad_onset: bool = True, silence_gate: bool = False,
                 asr_dtype: str = "bfloat16", boost_phrases: list[str] | None = None,
                 early_final: bool = False, **kwargs: Any) -> None:
        # Read by _load_model during NeMo's constructor.
        self._asr_dtype, self._boost_phrases = asr_dtype, boost_phrases
        super().__init__(**kwargs)
        self._reset_on_vad_onset = reset_on_vad_onset
        self._early_final = early_final
        # The gate relies on the onset reset and pre-roll replay below.
        self._silence_gate = silence_gate and reset_on_vad_onset
        self._asr_hold_until = 0.0
        self._asr_gated = False
        self._preroll = bytearray()
        self._recognized_since_stop = False

    async def _run_model(self, call, *args):
        # NemoSTTService._transcribe's lock and native-work drain, for other stream calls.
        async with self._model_lock:
            inference = asyncio.create_task(asyncio.to_thread(call, *args))
            try:
                return await asyncio.shield(inference)
            except asyncio.CancelledError:
                while not inference.done():
                    try:
                        await asyncio.shield(inference)
                    except asyncio.CancelledError:
                        continue
                    except Exception:
                        break
                if not inference.cancelled():
                    inference.exception()  # Retrieve an error without replacing cancellation.
                raise

    async def _push_transcript(self, text: str) -> None:
        # As NemoSTTService.run_stt pushes a step's text.
        if text:
            language = self._params.language
            await self.push_frame(InterimTranscriptionFrame(
                text, "", time_now_iso8601(), language, result={"text": text}))
            await self._handle_transcription(transcript=text, is_final=False, language=language)

    def _load_model(self) -> None:
        self._model = desktop_asr(self._model_name, device=self._device, dtype=self._asr_dtype,
                                  phrases=self._boost_phrases)

    async def _handle_transcription(self, transcript, is_final, language=None):
        if transcript.strip():
            self._recognized_since_stop = True
            self._asr_hold_until = time.monotonic() + ASR_SILENCE_HOLD_SECS
        await super()._handle_transcription(transcript, is_final, language)

    async def process_audio_frame(self, frame, direction) -> None:
        if self._reset_on_vad_onset and not self._is_vad_active:
            # 320 ms of mono s16/16 kHz, including the first 100 ms before
            # Silero confirms onset. Never retain an unbounded idle recording.
            self._preroll.extend(frame.audio)
            del self._preroll[:-10_240]
            if self._silence_gate and time.monotonic() >= self._asr_hold_until:
                # Sustained silence: the pre-roll alone feeds the next onset.
                self._asr_gated = True
                return
        # Preserve recognition when quiet speech falls below VAD confidence.
        self._asr_gated = False
        await super().process_audio_frame(frame, direction)

    async def _flush_early(self, last_voiced_ns: int, direction: FrameDirection) -> None:
        # The end-of-turn tail on a copy: the live stream keeps its audio and state.
        elapsed = (time.monotonic_ns() - last_voiced_ns) / 1e9
        tail = max(0, round((ASR_TAIL_SECS - elapsed) / 0.02))
        tail += -(len(self.audio_buffer) + tail) % self._params.buffer_size
        remainder = b"".join(self.audio_buffer) + b"\0" * (640 * tail)
        started = time.perf_counter()
        result = await self._run_model(lambda: fork_stream(self._model).transcribe_final(remainder))
        await self.push_frame(SpeechEarlyFinalFrame(
            result.text, round((time.perf_counter() - started) * 1000, 1)), direction)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        if isinstance(frame, SpeechPauseFrame):
            if self._early_final and self._is_vad_active and type(frame.last_voiced_ns) is int:
                await self._flush_early(frame.last_voiced_ns, direction)
            return
        if isinstance(frame, VADUserStartedSpeakingFrame):
            preroll = bytes(self._preroll)
            self._preroll.clear()
            # Long silence suppresses short words in this streaming model.
            # Reset at actual onset, but never replay text already recognized
            # before VAD: that existing unvoiced path owns the utterance. Gated
            # silence broke the decoder's audio continuity and outlasted the
            # pre-roll, so it always starts fresh.
            reset = (self._reset_on_vad_onset and not self._is_vad_active
                     and (not self._recognized_since_stop or self._asr_gated))
            if reset:
                async with self._model_lock:
                    self._model.reset_state()
                self.audio_buffer.clear()
                self._recognized_since_stop = False
            await super().process_frame(frame, direction)
            if reset:
                # Keep NeMo's existing 4 x 20 ms batching and encoder shift.
                for offset in range(0, len(preroll), 640):
                    await super().process_audio_frame(
                        InputAudioRawFrame(preroll[offset:offset + 640], SAMPLE_RATE, 1),
                        direction,
                    )
            return
        if isinstance(frame, VADUserStoppedSpeakingFrame):
            tail = frame.metadata.get("obsidience_asr_tail_frames", 0)
            if tail > 0:
                # Complete whole 80 ms batches so every silent frame is decoded,
                # then decode pending frames and silence in one encoder call.
                tail += -(len(self.audio_buffer) + tail) % self._params.buffer_size
                remainder = b"".join(self.audio_buffer) + b"\0" * (640 * tail)
                self.audio_buffer.clear()
                result = await self._run_model(self._model.transcribe_final, remainder)
                await self._push_transcript(result.text)
        await super().process_frame(frame, direction)
        if isinstance(frame, VADUserStoppedSpeakingFrame):
            # NeMo resets its caches on this same edge. Partial batches belong
            # to that finished utterance, never to the next one.
            self.audio_buffer.clear()
            self._recognized_since_stop = False
            self._asr_hold_until = time.monotonic() + ASR_SILENCE_HOLD_SECS
        if isinstance(frame, (VADUserStoppedSpeakingFrame, ListeningModeFrame,
                              EndFrame, CancelFrame)):
            self._preroll.clear()


class ObsidienceNeMoTurnTakingService(NeMoTurnTakingService):
    """Close recognized and empty VAD turns without leaving speech latched."""

    def __init__(self, *, timing: SpeechInputTiming | None = None,
                 playback: PlaybackCommands | None = None,
                 mode: str = "realtime", mode_revision: int = 0,
                 wake_word: str = "Computer", smart_turn: bool = False,
                 semantic_turns: bool = False, event_sink=None,
                 wake_spotter=None, **kwargs: Any) -> None:
        # STT audio and VAD share its system-frame FIFO, but transcription
        # frames use a separate downstream queue. Consume text inline so a
        # VAD stop cannot overtake recognized words before finalization.
        super().__init__(enable_direct_mode=True, **kwargs)
        self._timing = timing
        self._emit = event_sink or emit
        self._playback = playback
        self._smart_turn = smart_turn
        self._semantic_turns = semantic_turns
        self._semantic_text = ""
        self._semantic_timing: dict | None = None
        self._candidate_revision = 0
        self._candidate_sequence = 0
        self._candidate_ready = False
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
        self._wake_cue_name = "ready"
        self._wake_spotter = wake_spotter
        self._wake_spotted = False
        self._segment_onset_at = 0.0
        self._completed_pushed = False

    def _invalidate_candidate(self) -> None:
        """New capture invalidates a verdict without losing addressed text."""
        if not self._semantic_turns:
            return
        self._candidate_revision += 1
        if self._candidate_ready:
            self._candidate_ready = False
            self._emit("speech_candidate_invalidated", speech_sequence=self._candidate_sequence,
                 candidate_revision=self._candidate_revision, mode_revision=self.mode_revision)

    def _clear_semantic(self) -> None:
        self._candidate_revision += 1
        self._candidate_ready = False
        self._semantic_text = ""
        self._semantic_timing = None
        self._candidate_sequence = 0

    async def _admit_speech(self, frame: SpeechAdmissionFrame) -> None:
        # Check and clear before any await: an old model result cannot clear a
        # newer capture or the next addressed utterance.
        accepted = (self._semantic_turns and self._candidate_ready
                    and frame.mode_revision == self.mode_revision
                    and frame.speech_sequence == self._candidate_sequence
                    and frame.candidate_revision == self._candidate_revision
                    and not self._vad_user_speaking
                    and not self._user_speaking_buffer.strip())
        if accepted:
            self._clear_semantic()
            if self._timing is not None:
                self._timing.discard()
            await self._close_wake()
        self._emit("speech_admission", action=frame.action, accepted=accepted,
             speech_sequence=frame.speech_sequence,
             candidate_revision=frame.candidate_revision,
             mode_revision=frame.mode_revision)

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
            # Ongoing speech needs a later pause or an explicit greeting.
            self._wake_address = None

    def _classify_wake(self, *, final: bool = False) -> str | None:
        """Return command text after an accepted address, else None."""
        decision, end, self._wake_scanned, rejected = classify_wake(
            self._wake_prefix, self._wake_address, self._wake_scanned,
            self._wake_pattern, final=final,
        )
        for reason in rejected:
            # Counts only: rejected speech never leaves the worker.
            self._emit("wake_rejected", reason=reason, mode_revision=self.mode_revision)
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

    async def _open_wake(self, text: str, *, cue_name: str = "ready") -> str:
        spotted, self._wake_spotted = self._wake_spotted, False
        text = text.lstrip(WAKE_STRIP)
        self._wake_cue_name = cue_name
        self._wake_open = True
        await self._reset_wake_scan(segment_start=False)
        if self._timing is not None:
            self._timing.onset()
        self._emit("wake_detected", mode_revision=self.mode_revision,
             speech_sequence=self._timing.sequence if self._timing else 0)
        self._wake_timeout = self.create_task(self._expire_wake(), name="wake-command-window")
        # NeMo's bot flag includes the output queue's idle delay plus its
        # own stop grace. A completed reply's closing cue extends that tail.
        # Snapshot the actual reply owner before interruption invalidates
        # it, so immediate follow-ups chirp and true speech barge-in stays quiet.
        if not spotted:  # A spot already chose the cue and interrupted.
            self._wake_cue_eligible = self._wake_cue_choice()
        if not self._have_sent_user_started_speaking:
            await self._handle_user_interruption(UserStartedSpeakingFrame())
            self._have_sent_user_started_speaking = True
        return text

    def _wake_cue_choice(self) -> bool:
        reply_active = (self._playback._reply_active if self._playback is not None
                        else self._bot_speaking)
        # Owner choice (2026-10-19): the wake word always chirps, also when the
        # command follows in one breath; true speech barge-in during a reply stays quiet.
        return not reply_active

    async def _spot_wake(self) -> None:
        """The keyword spotter heard the name: chirp and interrupt now.

        Only at a segment start (the ASR rule's address position, before other
        recognized words). It opens no command window: ASR text still accepts
        the address, and a segment that ends without one drops the spot.
        """
        if (self.mode != "wake" or self._wake_open or self._wake_spotted
                or self._mode_waiting_for_stop or not self._vad_user_speaking
                or time.monotonic() - self._segment_onset_at > WAKE_SPOT_ONSET_SECS
                or self._wake_address != 0
                or not _WAKE_LEAD.fullmatch(self._wake_pattern.sub("", self._wake_prefix))):
            return
        self._wake_spotted = True
        self._wake_cue_name = "ready"
        self._wake_cue_eligible = self._wake_cue_choice()
        self._emit("wake_spotted", mode_revision=self.mode_revision,
                   score=round(self._wake_spotter.score, 3))
        if not self._have_sent_user_started_speaking:
            await self._handle_user_interruption(UserStartedSpeakingFrame())
            self._have_sent_user_started_speaking = True

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
            address = len(self._wake_prefix)
            if self._wake_prefix[-1:].isalnum() and text[:1].isalnum():
                # NeMo emits subword deltas. Preserve an eligible address
                # when a recognition gap splits its name ("Bar" + "d play").
                word = re.search(r"\w+$", self._wake_prefix)
                if (word is not None and self._wake_address is not None
                        and _WAKE_LEAD.fullmatch(self._wake_prefix,
                                                self._wake_address, word.start())):
                    address = self._wake_address
            self._wake_address = address
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

    def turn_pending(self) -> bool:
        """True while the current speech cannot end a turn: no words, a dangling
        end, or only the wake-word address (Realtime keeps it in the text)."""
        text = self._user_speaking_buffer
        if self._semantic_turns:
            text = self._semantic_text + " " + text
        address = self._wake_pattern.sub("", text)
        # A bare "okay" or "hey" is not an address without the wake word.
        return turn_text_pending(text) or (address != text and _WAKE_LEAD.fullmatch(address) is not None)

    def turn_short_reply(self) -> bool:
        """True when the command text, without the wake-word address, is
        exactly one complete short reply ("yes", "never mind")."""
        text = self._user_speaking_buffer
        if self._semantic_turns:
            text = self._semantic_text + " " + text
        return turn_text_short_reply(self._wake_pattern.sub(" ", text))

    def _reply_playing(self) -> bool:
        return self._bot_speaking or bool(self._playback is not None and self._playback._reply_active)

    def is_backchannel(self, text: str) -> bool:
        # Realtime only, and only over a reply: an addressed wake command and
        # an answer to a finished reply stay ordinary speech.
        return self.mode == "realtime" and self._reply_playing() and super().is_backchannel(text)

    def _backchannel_prefix(self, text: str) -> bool:
        cleaned = self.clean_text(text)
        return bool(cleaned) and any(phrase.startswith(cleaned) for phrase in self.backchannel_phrases_nopc)

    async def _close_wake(self) -> None:
        timeout, self._wake_timeout = self._wake_timeout, None
        if timeout is not None and timeout is not asyncio.current_task():
            await self.cancel_task(timeout)
        await self._reset_wake_scan(segment_start=not self._vad_user_speaking)
        self._wake_open = False
        self._wake_spotted = False
        self._wake_cue_eligible = False

    async def _expire_wake(self) -> None:
        try:
            await asyncio.sleep(WAKE_COMMAND_WAIT_SECS)
            if not self._user_speaking_buffer.strip():
                await self._close_wake()
                if self._have_sent_user_started_speaking and not self._vad_user_speaking:
                    await self._handle_user_interruption(UserStoppedSpeakingFrame())
                    self._have_sent_user_started_speaking = False
                self._emit("wake_idle", mode_revision=self.mode_revision)
        finally:
            if self._wake_timeout is asyncio.current_task():
                self._wake_timeout = None

    def follow_up(self, reply: tuple[int, int]) -> bool:
        """A spoken question has finished playing: open the command window as
        the name said alone would (owner, 2026-10-14). False in Realtime mode
        or with a window already open; the closing cue then plays as before."""
        if self.mode != "wake" or self._wake_open or self._mode_waiting_for_stop:
            return False
        self.create_task(self._open_follow_up(reply), name="wake-follow-up")
        return True

    async def _open_follow_up(self, reply: tuple[int, int]) -> None:
        # Its own task, like _confirm_wake: the output's audio task reported
        # the end and must never be the one an interruption cancels mid-open.
        # A newer reply, cancellation, mode change or stop has moved the epoch.
        playback = self._playback
        if (self.mode != "wake" or self._wake_open or self._mode_waiting_for_stop
                or playback is None or (playback.generation, playback.epoch) != reply):
            return
        await self._open_wake("", cue_name="follow_up")
        if self._have_sent_user_started_speaking and not self._vad_user_speaking:
            # Nobody spoke: end the opening edge as the name's own VAD stop
            # does, so the answer is the next utterance with its own timing.
            await self._handle_user_interruption(UserStoppedSpeakingFrame())
            self._have_sent_user_started_speaking = False
            if self._timing is not None:
                self._timing.discard()

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
            timeout, self._wake_timeout = self._wake_timeout, None
            if timeout is not None:
                await self.cancel_task(timeout)
        if frame.text.strip():
            self._invalidate_candidate()
            await super()._handle_transcription(frame, direction)

    async def _handle_completed_text(self, completed_text, direction, is_final=True):
        if not any(character.isalnum() for character in completed_text):
            return
        self._completed_pushed = True
        await super()._handle_completed_text(completed_text, direction, is_final)
        if is_final and self.mode == "wake" and not self._semantic_turns:
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
        if (self._semantic_turns and direction is FrameDirection.DOWNSTREAM
                and isinstance(frame, TranscriptionFrame) and frame.text.strip()
                and not (frame.text.startswith("(") and frame.text.endswith(")"))):
            text = " ".join((self._semantic_text + " " + frame.text).split())
            if len(text) > SEMANTIC_TEXT_MAX_CHARS:
                self._clear_semantic()
                await self._close_wake()
                self._emit("speech_candidate_failed", code="text_limit", mode_revision=self.mode_revision)
                return
            self._semantic_text = text
            timing = frame.metadata.get("obsidience_speech_timing")
            if timing is not None:
                # Keep the latest segment that actually supplied words.
                # A noise-only refresh must not replace its endpoint evidence.
                self._semantic_timing = timing
            self._candidate_revision += 1
            self._candidate_sequence = self._timing.sequence if self._timing else 0
            self._candidate_ready = True
            # The address chirped once; later segments remain in its window
            # without presenting another opening cue.
            self._wake_cue_eligible = False
            frame.text = self._semantic_text
            frame.metadata["obsidience_candidate_revision"] = self._candidate_revision
            frame.metadata["obsidience_speech_sequence"] = self._candidate_sequence
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
        self._segment_onset_at = time.monotonic()
        self._invalidate_candidate()
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
            if self._smart_turn and self.turn_pending():
                # The same bound as a VAD pause that ends on a dangling word.
                await asyncio.sleep(SMART_TURN_PENDING_SECS - TRANSCRIPT_IDLE_SECS)
            if self._user_speaking_buffer.strip() and not self._vad_user_speaking:
                # A gap in recognized words is not silence while VAD still
                # hears speech. Keep the fallback for late, unvoiced ASR only.
                # The endpoint has won. Disarm it before the first await so a
                # real VAD edge cannot cancel NeMo halfway through finalizing.
                self._transcript_timeout = None
                await self.push_frame(
                    VADUserStoppedSpeakingFrame(), direction=FrameDirection.UPSTREAM,
                )
                stop = VADUserStoppedSpeakingFrame()
                stop.metadata["obsidience_endpoint_ns"] = time.monotonic_ns()
                await self.queue_frame(stop, direction)
        except asyncio.CancelledError:
            return
        finally:
            if self._transcript_timeout is asyncio.current_task():
                self._transcript_timeout = None

    def _early_final(self, frame: SpeechEarlyFinalFrame) -> None:
        """Offer the words a final would carry now; no turn state changes."""
        if self._mode_waiting_for_stop:
            return
        if self.mode == "wake" and not self._wake_open:
            # As the VAD stop does: silence after a trailing name addresses it.
            heard = self._wake_prefix + frame.text
            decision, end, _, _ = classify_wake(heard, self._wake_address, self._wake_scanned,
                                                self._wake_pattern, final=True)
            if decision != "accept":
                return
            command = heard[end:]
        else:
            command = self._user_speaking_buffer + frame.text
            if (self.mode == "realtime" and not self._have_sent_user_started_speaking
                    and self._reply_playing() and self._backchannel_prefix(" ".join(command.split()))):
                return  # As partials: an acknowledgement over a reply is not a turn.
        command = command.lstrip(WAKE_STRIP)
        if not any(character.isalnum() for character in command):
            return
        text = (self._semantic_text + " " + command) if self._semantic_turns else command
        self._emit("speech_early_final", text=" ".join(text.split())[:SEMANTIC_TEXT_MAX_CHARS],
                   speech_sequence=self._timing.sequence if self._timing else 0,
                   candidate_revision=self._candidate_revision, mode_revision=self.mode_revision,
                   flush_ms=frame.flush_ms)

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        if (isinstance(frame, InputAudioRawFrame) and self._wake_spotter is not None
                and self.mode == "wake" and self._wake_spotter.process(frame.audio)):
            await self._spot_wake()
        if isinstance(frame, SpeechAdmissionFrame):
            await self._admit_speech(frame)
            return
        if isinstance(frame, SpeechEarlyFinalFrame):
            self._early_final(frame)
            return
        if isinstance(frame, SpeechResetFrame):
            if not self._semantic_turns:
                return
            self._clear_semantic()
            await self._cancel_transcript_timeout()
            waiting = self._vad_user_speaking
            self.reset()
            self._mode_waiting_for_stop = waiting
            if self._timing is not None:
                self._timing.discard()
            await self._close_wake()
            return
        if isinstance(frame, ListeningModeFrame):
            self._clear_semantic()
            waiting = self._vad_user_speaking
            await self._cancel_transcript_timeout()
            await self._close_wake()
            self.reset()
            self._mode_waiting_for_stop = waiting
            self.mode, self.mode_revision = frame.mode, frame.revision
            if self._timing is not None:
                self._timing.discard()
            self._emit("mode_applied", mode=self.mode, mode_revision=self.mode_revision)
            return
        if isinstance(frame, (EndFrame, CancelFrame)):
            self._clear_semantic()
            await self._close_wake()
        refresh_candidate = (self._semantic_turns and self._semantic_text
                             and isinstance(frame, VADUserStoppedSpeakingFrame)
                             and not self._user_speaking_buffer.strip()
                             and not self._mode_waiting_for_stop)
        if refresh_candidate and self._timing is not None:
            # A noise-only VAD edge invalidated the old verdict. Re-offer the
            # held words with its new identity only after capture stops, while
            # keeping the actual spoken text's timestamps.
            self._timing.discard()
        if (isinstance(frame, VADUserStoppedSpeakingFrame) and self._smart_turn
                and frame.metadata.get("obsidience_asr_tail_frames", 0) > 0
                and any(c.isalnum() for c in self._user_speaking_buffer) and self.turn_pending()):
            # The decoded ASR tail ended mid-phrase ("turn the"). NeMo has reset,
            # but the turn stays open: later words join this text, or the
            # transcript fallback ends it at the same pending bound.
            self._vad_user_speaking = False
            await self._cancel_transcript_timeout()
            await self.push_frame(frame, direction)
            self._transcript_timeout = self.create_task(
                self._close_unvoiced_transcript(direction), name="nemo-transcript-endpoint",
            )
            return
        if isinstance(frame, VADUserStoppedSpeakingFrame):
            if self.mode == "wake" and not self._wake_open and self._wake_pending:
                # Silence after a trailing name confirms it as an address.
                command = self._classify_wake(final=True)
                if command is not None:
                    await self._open_wake(command)
            if self._wake_spotted and not self._wake_open:
                # ASR never accepted the spotted name; the empty stop below
                # ends the provisional speech edge.
                self._wake_spotted = False
                self._wake_cue_eligible = False
                self._emit("wake_spot_dropped", mode_revision=self.mode_revision)
            await self._reset_wake_scan(segment_start=True)
            self._mode_waiting_for_stop = False
            if self._timing is not None and self._user_speaking_buffer.strip():
                self._timing.endpoint(frame.metadata.get("obsidience_last_voiced_ns"),
                                      frame.metadata.get("obsidience_endpoint_ns"))
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
        had_words = any(character.isalnum() for character in self._user_speaking_buffer)
        had_sent = self._have_sent_user_started_speaking
        self._completed_pushed = False

        await super().process_frame(frame, direction)

        if refresh_candidate and self._semantic_text and not self._vad_user_speaking:
            self._candidate_revision += 1
            self._candidate_sequence = self._timing.sequence if self._timing else 0
            self._candidate_ready = True
            self._emit("speech_candidate", text=self._semantic_text,
                 speech_sequence=self._candidate_sequence,
                 candidate_revision=self._candidate_revision, mode_revision=self.mode_revision,
                 refreshed=True,
                 **({"speech_timing": {**self._semantic_timing,
                       "speech_sequence": self._candidate_sequence}}
                    if self._semantic_timing else {}))

        if empty_vad_stop and self._have_sent_user_started_speaking:
            await self._handle_user_interruption(UserStoppedSpeakingFrame())
            self._have_sent_user_started_speaking = False
        if had_words and not self._user_speaking_buffer.strip() and not self._completed_pushed:
            # NeMo dropped a backchannel over the reply. It clears its started
            # flag without a stop edge, which would latch user speech.
            if self._timing is not None:
                self._timing.discard()
            if had_sent and not self._have_sent_user_started_speaking:
                await self._handle_user_interruption(UserStoppedSpeakingFrame())

        if not isinstance(frame, (InterimTranscriptionFrame, TranscriptionFrame)):
            return
        transcript = " ".join(self._user_speaking_buffer.split())
        if not transcript or not any(character.isalnum() for character in transcript):
            return
        if (not self._have_sent_user_started_speaking and self._reply_playing()
                and self.mode == "realtime" and self._backchannel_prefix(transcript)):
            # A short acknowledgement must not interrupt the reply. NeMo drops
            # it at the VAD stop; any further word makes it ordinary speech.
            return
        if self._timing is not None:
            self._timing.partial()
        if not self._have_sent_user_started_speaking:
            await self._handle_user_interruption(UserStartedSpeakingFrame())
            self._have_sent_user_started_speaking = True
        partial = (" ".join((self._semantic_text + " " + transcript).split())
                   if self._semantic_turns else transcript)
        self._emit("transcript_partial", text=partial,
             mode_revision=self.mode_revision,
             **({"speech_sequence": self._timing.sequence} if self._timing else {}))
        await self._cancel_transcript_timeout()
        self._transcript_timeout = self.create_task(
            self._close_unvoiced_transcript(direction),
            name="nemo-transcript-endpoint",
        )


class SentencePauseFrame(TTSAudioRawFrame):
    """Silence between two sentences of one reply; discarded like its reply's audio."""


class PocketTTSService(TTSService):
    """Pocket TTS as a normal Pipecat streaming TTS service."""

    def __init__(self, *, root: Path, voice: str, playback=None) -> None:
        super().__init__(sample_rate=TTS_SAMPLE_RATE)
        self._playback = playback
        self._timing = None
        self._output_binding = None
        # The previous chunk's reply identity and whether it ended a sentence.
        self._previous_chunk: tuple | None = None
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

    async def external_pcm(self, text: str) -> AsyncGenerator[bytes, None]:
        """Serialize an external reply on the existing Pocket model.

        This consumer owns only its PCM iterator, never desktop playback state.
        The bounded queue and cooperative cancellation retain Pocket's required
        producer cleanup before releasing its existing synthesis lock.
        """
        clean = " ".join(text.split())[:4_000]
        if not clean:
            return
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=8)
        cancelled = threading.Event()

        def put(item) -> bool:
            future = asyncio.run_coroutine_threadsafe(queue.put(item), loop)
            while not cancelled.is_set():
                try:
                    future.result(timeout=0.1)
                    return True
                except TimeoutError:
                    continue
            future.cancel()
            return False

        def synthesize() -> None:
            try:
                while not self._synthesis_lock.acquire(timeout=0.1):
                    if cancelled.is_set():
                        return
                try:
                    if cancelled.is_set():
                        return
                    # Pocket's own stop event ends the latent producer at its next frame;
                    # the generator still joins its decoder before the lock is released.
                    for chunk in self._model.generate_audio_stream(self._voice_state, clean, stop=cancelled):
                        if not cancelled.is_set():
                            samples = chunk.detach().float().cpu().numpy().reshape(-1)
                            # Discord has its own playback volume. Preserve Pocket's
                            # dynamics instead of applying the desk speaker's +9 dB.
                            put(_speech_pcm(samples, gain=1.0))
                finally:
                    self._synthesis_lock.release()
            except BaseException:
                if not cancelled.is_set():
                    put(RuntimeError("Pocket TTS speech delivery failed"))
            finally:
                if not cancelled.is_set():
                    put(None)

        worker = threading.Thread(target=synthesize, name="pocket-discord", daemon=False)
        worker.start()
        try:
            while True:
                item = await queue.get()
                if item is None:
                    return
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            cancelled.set()
            # Never detach a generator that still owns Pocket's native work.
            join = asyncio.create_task(asyncio.to_thread(worker.join))
            while not join.done():
                try:
                    await asyncio.shield(join)
                except asyncio.CancelledError:
                    continue

    async def process_frame(self, frame: Frame, direction: FrameDirection) -> None:
        if isinstance(frame, TTSSpeakFrame):
            if self._playback is not None and not self._playback.accepts(frame):
                return  # A superseded chunk queued behind synthesis is never voiced.
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
        # Chunks are synthesized in order, so the previous run is the previous
        # chunk; a reply's first chunk never waits.
        reply = (tuple(output_binding.get(key) for key in ("generation", "epoch", "playback_id"))
                 if output_binding is not None else None)
        pause = reply is not None and self._previous_chunk == (reply, True)
        self._previous_chunk = (reply, _SENTENCE_END.search(clean) is not None)
        first_pcm = True
        successful = True
        pcm_bytes = 0

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[bytes | BaseException | None] = asyncio.Queue()
        cancelled = threading.Event()

        def synthesize() -> None:
            try:
                # Pocket's generator is not thread-safe and only joins its
                # native workers when consumed to completion. Its stop event ends
                # the latent producer at the next frame (and skips later text
                # chunks); drain the generator's ordinary decoder join here.
                with self._synthesis_lock:
                    if cancelled.is_set():
                        return
                    for chunk in self._model.generate_audio_stream(self._voice_state, clean, stop=cancelled):
                        if cancelled.is_set():
                            continue
                        samples = chunk.detach().float().cpu().numpy().reshape(-1)
                        loop.call_soon_threadsafe(queue.put_nowait, _speech_pcm(samples))
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
            if pause:
                # Queued behind the previous sentence's audio while this one
                # synthesizes; interruption discards it with the reply.
                yield SentencePauseFrame(_SENTENCE_PAUSE_PCM, TTS_SAMPLE_RATE, 1)
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


# Barge-in (owner decision 2026-10-19), Realtime mode: a Silero onset over a
# reply ducks it at once, sustained speech holds it, recognized words commit the
# existing interruption, and quiet without them resumes it where it was held.
# LiveKit Agents pauses after 0.5 s and resumes false alarms; Voice-Light ducks -15 dB.
BARGE_IN_DUCK_GAIN = 10.0 ** (-15.0 / 20.0)
BARGE_IN_PAUSE_SECS = 0.5  # Owner speech this long holds the reply.
# Quiet this long without committed words resumes it. The first partial comes
# 0.7-0.95 s after onset, so up to ~0.5 s after a short burst's quiet edge.
BARGE_IN_RESUME_SECS = 1.5
BARGE_IN_MAX_HOLD_SECS = 4.0  # Word-less noise never holds a reply longer.
BARGE_IN_POLL_SECS = 0.02


class PlaybackCommands:
    """One pending Task reply, invalidated before preparation or synthesis.

    A reply opened with ``open`` accepts ``speak_append`` chunks under the same
    generation and epoch: they queue behind it for the one serialized Pocket
    producer, so playback continues without a gap or an interruption. Its
    outcome cue follows only the final chunk (see ``close_reply``).
    Owner speech over a reply ducks or holds its audio (``owner_voice``).
    """

    def __init__(self) -> None:
        self.generation = -1
        self.epoch = 0
        # FIFO of (generation, epoch, text, timing, playback_id, outcome, open).
        self._queued: list[tuple[int, int, str, dict | None, str, str | None, bool]] = []
        # The open reply accepting appends, its unfinished chunks, a final
        # outcome waiting for the last chunk, and any unsuccessful chunk.
        self._reply: tuple[int, int, str] | None = None
        self._chunks = 0
        self._closing: str | None = None
        self._chunk_failed = False
        self._last_text = ""  # The open or latest reply's last spoken chunk.
        self._preparing: asyncio.Task | None = None
        self._controller_ready = asyncio.Event()
        self._startup_pending = True
        self._cue_assets = load_assets(Path(__file__).resolve().parents[3] / "state/realtime-cues")
        self._ready_cue_binding: tuple[int, int] | None = None
        self._pending_ready_cue_binding: tuple[int, int] | None = None
        self._output = None
        self._turn_taking = None
        self._reply_active = False
        # The latest reply's playback id and how many of its chunks had begun
        # audible output; owner barge-in reports them before invalidation.
        self._playing: str | None = None
        self._audible = 0
        # Barge-in: enabled by run(); the owner-speech episode over a reply and
        # the gain last written, so every change ramps within one chunk.
        self.barge_in = False
        self._barge: dict | None = None
        self._duck = 1.0

    def owner_voice(self, speaking: bool) -> None:
        """One raw Silero edge from capture: start, extend or end a barge-in."""
        now = time.monotonic()
        barge = self._barge
        if barge is not None and barge["quiet"] is not None and now - barge["quiet"] >= BARGE_IN_RESUME_SECS:
            self.end_barge_in("released", barge["quiet"])
            barge = None
        if not speaking:
            if barge is not None and barge["quiet"] is None:
                barge["quiet"] = now
            return
        if barge is not None:
            barge["quiet"] = None  # Speech resumed within the window: the same barge-in.
            return
        turn = self._turn_taking
        if self.barge_in and turn is not None and turn.mode == "realtime" and turn._reply_playing():
            self._barge = {"onset": now, "quiet": None, "paused": False, "ducked": False}

    def end_barge_in(self, outcome: str, at: float | None = None) -> None:
        """Close the barge-in: ``committed`` by words, ``released`` without them."""
        barge, self._barge = self._barge, None
        if barge is not None and barge["ducked"]:
            # Counts and durations only, to tune false alarms (residual echo, coughs).
            emit("barge_in", outcome=outcome, generation=self.generation, paused=barge["paused"],
                 speech_ms=round(max(0.0, (time.monotonic() if at is None else at) - barge["onset"]) * 1000))

    def _barge_in_level(self, now: float) -> tuple[float, bool]:
        """The reply gain and whether its audio is held, at ``now``."""
        barge = self._barge
        if barge is None:
            return 1.0, False
        quiet = barge["quiet"]
        if quiet is not None and now - quiet >= BARGE_IN_RESUME_SECS:
            self.end_barge_in("released", quiet)
            return 1.0, False
        spoken = (now if quiet is None else quiet) - barge["onset"]
        return BARGE_IN_DUCK_GAIN, (BARGE_IN_PAUSE_SECS <= spoken
                                    and now - barge["onset"] < BARGE_IN_MAX_HOLD_SECS)

    async def barge_in_audio(self, frame: TTSAudioRawFrame, on_hold) -> None:
        """Hold one reply chunk while the owner keeps speaking, then scale it.

        Holding stops writing, so the reply resumes at this exact sample; an
        interruption cancels the output task and with it this wait.
        """
        gain, hold = self._barge_in_level(time.monotonic())
        while hold:
            if not self._barge["paused"]:
                self._barge["paused"] = True
                on_hold()
            await asyncio.sleep(BARGE_IN_POLL_SECS)
            gain, hold = self._barge_in_level(time.monotonic())
        if gain < 1.0:
            self._barge["ducked"] = True
        start, self._duck = self._duck, gain
        if start == gain == 1.0 or not frame.audio:
            return
        samples = np.frombuffer(frame.audio, dtype="<i2").astype(np.float32)
        ramp = np.linspace(start, gain, samples.size, dtype=np.float32) if start != gain else gain
        frame.audio = np.clip(samples * ramp, -32768, 32767).astype("<i2").tobytes()

    def cancel_cues(self) -> None:
        self._ready_cue_binding = None
        self._pending_ready_cue_binding = None

    def cue_current(self, marker) -> bool:
        turn = self._turn_taking
        if marker.cue_name in OPENING_CUES and self._ready_cue_binding == (marker.generation, marker.epoch):
            return True
        # Harness's natural-speech cancellation may arrive before the queued
        # marker. It must not delay this local acknowledgement. Command text
        # still suppresses an unstarted cue; explicit cancellation clears both
        # pending and started bindings.
        pending_ready = (marker.cue_name in OPENING_CUES
                         and self._pending_ready_cue_binding == (marker.generation, marker.epoch))
        return (((marker.generation, marker.epoch) == (self.generation, self.epoch) or pending_ready)
                and (marker.cue_name in OPENING_CUES or not (turn and turn._user_speaking_buffer.strip()))
                and (marker.cue_name not in OPENING_CUES or (not self._reply_active and turn and turn._wake_open and turn._wake_cue_eligible)))

    async def queue_cue(self, name: str, generation: int) -> None:
        pcm = self._cue_assets.get(name) if isinstance(name, str) else None
        if not pcm or type(generation) is not int or generation != self.generation or self._output is None:
            return
        marker = CueMarker(name, generation, self.epoch)
        if not self.cue_current(marker):
            return
        if name in OPENING_CUES:
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
        self._queued = []
        self._reply, self._chunks, self._closing = None, 0, None
        self._playing, self._audible = None, 0
        self._barge, self._duck = None, 1.0  # The audio it governed is discarded.
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
        playback_id = command.get("playback_id", "startup")
        opened = command.get("open") is True and isinstance(playback_id, str)
        self._reply = (generation, self.epoch, playback_id) if opened else None
        self._playing = playback_id if isinstance(playback_id, str) else None
        self._audible = 0
        self._chunks, self._closing, self._chunk_failed = 1, None, False
        self._last_text = text
        self._queued = [(generation, self.epoch, text, timing, playback_id,
                         None if opened else command.get("outcome"), opened)]
        self._start_preparing(task)

    async def speak_append(self, task: PipelineTask, command: dict) -> None:
        """Queue one more chunk of the open reply, or report why it is ignored."""
        generation, playback_id = command.get("generation"), command.get("playback_id")
        text = " ".join(str(command.get("text", "")).split())[:4_000]
        opened = command.get("open") is True
        if self._reply is None or self._reply != (generation, self.epoch, playback_id):
            emit("speak_append_ignored",
                 generation=generation if type(generation) is int else None,
                 playback_id=(playback_id if isinstance(playback_id, str) and 0 < len(playback_id) <= 96
                              and all(c.isascii() and (c.isalnum() or c in "-_:.") for c in playback_id)
                              else None),
                 reason="closed" if self._reply is None else "superseded")
            return
        if not opened:
            self._reply = None  # The final chunk closes the reply.
        outcome = None if opened else command.get("outcome")
        if text:
            self._reply_active = True
            self._chunks += 1
            self._last_text = text
            # Only the first words after a spoken acknowledgement carry timing.
            timing = self._timing_context(command)
            self.record_timing("speech_received", timing)
            self._queued.append((generation, self.epoch, text, timing, playback_id, outcome, opened))
            self._start_preparing(task)
        elif not opened:
            # Nothing left to say: the outcome cue follows the last chunk.
            if self._chunks:
                self._closing = outcome
            else:
                await self.close_reply(self._closing_cue(outcome), generation)

    def _start_preparing(self, task: PipelineTask) -> None:
        if self._preparing is None or self._preparing.done():
            self._preparing = asyncio.create_task(
                self._prepare(task), name="speech-playback-prepare",
            )

    def _closing_cue(self, outcome) -> str | None:
        return ("error" if self._chunk_failed or outcome == "failed"
                else "complete" if outcome == "completed" else None)

    async def close_reply(self, name: str | None, generation: int) -> None:
        """Close the current reply, all of whose audio has been written.

        A completed reply that ends in a question opens the wake-mode command
        window instead of its closing cue; a distinct follow-up chirp follows.
        """
        turn = self._turn_taking
        if (name == "complete" and turn is not None and generation == self.generation
                and _QUESTION_END.search(self._last_text)
                and turn.follow_up((self.generation, self.epoch))):
            return
        if name:
            await self.queue_cue(name, generation)

    def chunk_audible(self, binding) -> None:
        """Count one chunk of the current reply whose first PCM was written."""
        if (isinstance(binding, dict)
                and (binding.get("generation"), binding.get("epoch")) == (self.generation, self.epoch)):
            self._audible += 1

    def interrupted_reply(self) -> dict:
        """The unfinished reply that owner speech is cutting off, if any.

        ``heard_chunks`` counts its chunks (``speak`` then each ``speak_append``)
        whose audio had started; the rest was never played.
        """
        if self._playing is None or (self._reply is None and not self._chunks):
            return {}
        return {"playback_id": self._playing, "heard_chunks": self._audible}

    def reply_continues(self, binding) -> bool:
        """True while another chunk of this reply is queued behind it."""
        return (isinstance(binding, dict) and self._chunks > 1
                and (binding.get("generation"), binding.get("epoch")) == (self.generation, self.epoch))

    def reply_finished(self, binding: dict, successful: bool) -> str | None:
        """Account one played chunk of the current reply; return its closing cue."""
        if (binding.get("generation"), binding.get("epoch")) != (self.generation, self.epoch):
            return None
        self._chunk_failed |= not successful
        self._chunks = max(0, self._chunks - 1)
        if self._chunks:
            return None
        self._reply_active = False
        self.cancel_cues()
        if binding.get("open"):
            if self._closing is None:
                return None  # More text may still be appended.
            outcome, self._closing = self._closing, None
        else:
            outcome = binding.get("outcome")
        return self._closing_cue(outcome)

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
            while self._queued:
                generation, epoch, text, timing, playback_id, outcome, opened = self._queued.pop(0)
                # Capture already uses the resident AEC feed, including while
                # waiting for a wake word or hearing other speaker playback.
                if (generation, epoch) != (self.generation, self.epoch):
                    continue
                self.record_timing("aec_ready", timing, since="received_ns")
                frame = TTSSpeakFrame(text)
                frame.metadata["obsidience_playback"] = (generation, epoch)
                frame.metadata["obsidience_timing"] = timing
                frame.metadata["obsidience_output"] = {
                    "generation": generation, "epoch": epoch, "playback_id": playback_id,
                    "outcome": outcome, "open": opened,
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
        interrupted = {}
        if isinstance(frame, StartInterruptionFrame) and not frame.metadata.get("obsidience_playback_cancel"):
            # What owner speech cut off; invalidation forgets the reply.
            interrupted = self.playback.interrupted_reply()
            self.playback.end_barge_in("committed")
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
                candidate = frame.metadata.get("obsidience_candidate_revision")
                emit("speech_candidate" if type(candidate) is int else "transcript_final",
                     text=text, **correlation,
                     **({"candidate_revision": candidate} if type(candidate) is int else {}),
                     **({"speech_timing": timing} if timing else {}))
        elif isinstance(frame, StartInterruptionFrame):
            if not frame.metadata.get("obsidience_playback_cancel"):
                emit("interruption", **correlation, **interrupted)
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
            elif kind == "speak_append":
                await playback.speak_append(task, command)
            elif kind == "cancel":
                if not playback.invalidate(
                    command.get("generation"), preserve_ready=command.get("stop_playback", True) is False,
                ):
                    continue
                if command.get("stop_playback", True) is True:
                    await task.queue_frame(SpeechResetFrame())
                    frame = StartInterruptionFrame()
                    frame.metadata["obsidience_playback_cancel"] = True
                    await task.queue_frame(frame)
            elif kind == "speech_admission":
                if (command.get("action") in {"accept", "discard"}
                        and all(type(command.get(key)) is int and command[key] >= 0
                                for key in ("speech_sequence", "candidate_revision", "mode_revision"))):
                    await task.queue_frame(SpeechAdmissionFrame(
                        action=command["action"], speech_sequence=command["speech_sequence"],
                        candidate_revision=command["candidate_revision"], mode_revision=command["mode_revision"],
                    ))
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


def create_stt(args: argparse.Namespace):
    from obsidience.harness.config import CONFIG

    dtype = CONFIG.extras.get("realtime_asr_dtype", "bfloat16")
    if dtype not in ASR_DTYPES:
        raise ValueError("realtime_asr_dtype must be one of: " + ", ".join(ASR_DTYPES))
    phrases = CONFIG.extras.get("realtime_asr_phrases", str(ASR_PHRASES))
    return UtteranceNeMoSTTService(
        silence_gate=CONFIG.extras.get("realtime_asr_silence_gate", True) is not False,
        asr_dtype=dtype,
        boost_phrases=None if phrases is False else load_boost_phrases(phrases, args.wake_word),
        early_final=CONFIG.extras.get("realtime_asr_early_final", False) is True,
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


async def run_discord_only(args: argparse.Namespace) -> None:
    """Own shared models and Discord while desktop capture/playback is muted."""
    if not args.discord_socket:
        raise ValueError("Desktop-disabled speech requires the configured Discord socket")
    # No PyAudio probe, local transport, desktop pipeline, cue or microphone.
    stt = create_stt(args)
    tts = PocketTTSService(root=Path(args.pocket_root), voice=args.voice)
    sys.modules.setdefault(f"{__package__}.worker", sys.modules[__name__])
    from .discord import DiscordSpeechServer
    server = DiscordSpeechServer(Path(args.discord_socket), stt, tts)
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    import signal
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stopping.set)
    reader = asyncio.StreamReader(limit=65_536)
    protocol = asyncio.StreamReaderProtocol(reader)
    pipe = None

    async def commands():
        while True:
            line = await reader.readline()
            if not line:
                stopping.set()
                return
            message = json.loads(line)
            if isinstance(message, dict) and message.get("type") == "stop":
                stopping.set()
                return
            # Desktop speak/cue/mode/control messages cannot enable an input
            # or output route on this worker. Mode transitions replace it.

    command_task = None
    try:
        await server.start()
        pipe, _ = await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)
        command_task = asyncio.create_task(commands(), name="discord-shared-control")
        command_task.add_done_callback(lambda _task: stopping.set())
        emit("discord_ready", desktop_disabled=True, encoder_cuda_graphs=server.encoder_cuda_graphs)
        await stopping.wait()
    finally:
        if command_task is not None:
            command_task.cancel()
            await asyncio.gather(command_task, return_exceptions=True)
        if pipe is not None:
            pipe.close()
        await server.close()
        for signum in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(signum)


async def run(args: argparse.Namespace) -> None:
    if args.desktop_disabled:
        await run_discord_only(args)
        return
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
    from obsidience.harness.config import CONFIG

    playback.barge_in = CONFIG.extras.get("realtime_barge_in_ducking", True) is not False
    short_replies = CONFIG.extras.get("realtime_short_replies", True) is not False
    # Read at each Silero pause, after the pipeline (and turn_taking) exists.
    model = str(CONFIG.extras.get("realtime_smart_turn_model", SMART_TURN_MODEL))
    turn_analyzer = (smart_turn_analyzer(lambda: turn_taking.turn_pending(),
                                         lambda: short_replies and turn_taking.turn_short_reply(),
                                         model_path=None if model == "bundled" else model)
                     if CONFIG.extras.get("realtime_smart_turn", True) is not False else None)
    wake_spotter = None
    if CONFIG.extras.get("realtime_wake_spotter", True) is not False:
        try:
            from .wakeword import WakeWordSpotter
            wake_spotter = WakeWordSpotter(WAKE_SPOTTER_MODEL)
            if wake_spotter.wake_word.strip().lower() != args.wake_word.strip().lower():
                raise ValueError("the spotter model was trained for another wake word")
        except Exception as exc:
            # A missing package or model keeps ASR-only wake detection.
            wake_spotter = None
            emit("wake_spotter_unavailable", error=type(exc).__name__)
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
                    stop_secs=(SMART_TURN_VAD_STOP_SECS if turn_analyzer is not None
                               else TRANSCRIPT_IDLE_SECS),
                    min_volume=0.0,
                ),
            ),
            turn_analyzer=turn_analyzer,
            audio_in_sample_rate=SAMPLE_RATE,
            audio_out_sample_rate=TTS_SAMPLE_RATE,
            audio_out_10ms_chunks=4,
        ), playback=playback, input_channel=args.input_channel,
    )
    stt = create_stt(args)
    turn_taking = ObsidienceNeMoTurnTakingService(
        timing=input_timing,
        playback=playback,
        mode=args.mode,
        mode_revision=args.mode_revision,
        wake_word=args.wake_word,
        smart_turn=turn_analyzer is not None,
        semantic_turns=CONFIG.extras.get("realtime_semantic_turns", False) is True,
        wake_spotter=wake_spotter,
        use_vad=True,
        use_diar=False,
        max_buffer_size=2,
        bot_stop_delay=0.5,
        # Wake mode ignores them: is_backchannel() is Realtime-only.
        backchannel_phrases=list(BACKCHANNEL_PHRASES),
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
            semantic_turns=turn_taking._semantic_turns,
            asr="nvidia/nemotron-speech-streaming-en-0.6b",
            asr_chunk_ms=160,
            wake_spotter=wake_spotter is not None,
            tts="pocket-tts-3.3.0+9aa7a7f-cpu",
            voice=args.voice,
            cues=sorted(playback._cue_assets),
        )
        await playback.startup(task, args.startup_confirmation)

    discord = None
    if args.discord_socket:
        # The worker is normally launched with -m. Let the optional adapter
        # reuse these exact service classes rather than import a second copy.
        sys.modules.setdefault(f"{__package__}.worker", sys.modules[__name__])
        from .discord import DiscordSpeechServer
        discord = DiscordSpeechServer(Path(args.discord_socket), stt, tts)
        await discord.start()
        emit("discord_ready", desktop_disabled=False, encoder_cuda_graphs=discord.encoder_cuda_graphs)

    commands = asyncio.create_task(
        command_loop(task, playback), name="speech-commands",
    )
    try:
        await PipelineRunner(handle_sigint=True, handle_sigterm=True).run(task)
    finally:
        if discord is not None:
            await discord.close()
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
    result.add_argument("--discord-socket", default="", help="Optional owner-only Discord PCM socket")
    result.add_argument("--desktop-disabled", action="store_true", help="Share speech models without desktop audio")
    return result


def main() -> None:
    from loguru import logger

    # NeMo/Pipecat DEBUG lines carry recognized words. Stderr is the Harness's
    # crash diagnostic tail, so keep only warnings and errors there.
    logger.remove()
    logger.add(sys.stderr, level="WARNING")
    try:
        asyncio.run(run(parser().parse_args()))
    except KeyboardInterrupt:
        pass
    except BaseException as exc:
        emit("fatal", error=f"{type(exc).__name__}: {exc}"[:1000])
        raise


if __name__ == "__main__":
    main()
