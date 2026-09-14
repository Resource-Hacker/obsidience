"""Obsidience supervisor for the fixed Pipecat/NeMo speech runtime."""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import os
import signal
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Literal

from ..conversation import runtime as conversation_runtime
from ..execution import activity, trace
from ..models import runtime as model_runtime
from . import media as media_runtime

RealtimePhase = Literal["off", "starting", "command", "proactive", "stopping", "error"]

PROJECT_ROOT = Path("/home/wissenschafter/Projects/obsidience")
REALTIME_PYTHON = Path("/var/lib/ai/venvs/obsidience-speech/bin/python")
RUNTIME_ROOT = Path(f"/run/user/{os.getuid()}/obsidience-realtime")
POCKET_ROOT = Path("/var/lib/ai/models/obsidience-realtime/pocket-tts")
NEMOTRON_MODEL = Path(
    "/var/lib/ai/models/obsidience-nemotron-speech-streaming-en-0.6b/"
    "nemotron-speech-streaming-en-0.6b.nemo"
)
MAX_EVENT_TEXT = 512
MAX_EVENTS = 80
MAX_WORKER_EVENT_BYTES = 16_384
RUNTIME_LEASE_OWNER = "obsidience-realtime"
REALTIME_CONFIRMATION = "Realtime active."


_input_speech_timing = trace.input_speech_timing


class RealtimeSessionManager:
    def __init__(self, conversation=None, *, requested_state_path: Path | None = None) -> None:
        self._requested_state_path = requested_state_path
        self._lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None
        self._monitor: asyncio.Task[None] | None = None
        self._transport_ready = False
        self._phase: RealtimePhase = "off"
        self._requested_proactive = False
        self._started_ns: int | None = None
        self._last_error: str | None = None
        self._vision_source: str | None = None
        self._audio_source = media_runtime.DEFAULT_MICROPHONE
        self._audio_sink = media_runtime.DEFAULT_SPEAKER
        self._input_level = 0.0
        self._capture_active = False
        self._user_speaking = False
        self._speech_sequence = 0
        self._live_transcript: dict[str, Any] | None = None
        self._aec_active = False
        self._tts_voice = media_runtime.DEFAULT_TTS_VOICE
        self._events: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)
        self._recent_log: deque[str] = deque(maxlen=8)
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._operation = 0
        self._hardware_leased = False
        self._playback_timing_binding: tuple | None = None
        self._playback_timing_stages: set[str] = set()
        self._playback_id: str | None = None
        self._playback_run_id = ""
        self.conversation = conversation or conversation_runtime.RUNTIME

    def scheduler_paused(self) -> bool:
        # Connection setup/teardown is a short transition. Idle listening does
        # not block nonconflicting work; actual GPU reservations remain owned
        # by the existing model runtime and foreground demand preempts safely.
        return self._phase in {"starting", "stopping"}

    def snapshot(self) -> dict[str, Any]:
        process = self._process
        return {
            "schema_version": 1,
            "phase": self._phase,
            "enabled": self._phase not in {"off", "error"},
            "ready": self._phase in {"command", "proactive"},
            "transport_ready": self._transport_ready,
            "proactive": self._phase == "proactive",
            "requested_proactive": self._requested_proactive,
            "pid": None if process is None or process.returncode is not None else process.pid,
            "started_monotonic_ns": self._started_ns,
            "last_error": self._last_error,
            "vision_source": self._vision_source,
            "audio_source": self._audio_source,
            "audio_sink": self._audio_sink,
            "input_level": self._input_level,
            "playback": activity.playback(),
            "capture_active": self._capture_active,
            "user_speaking": self._user_speaking,
            "live_transcript": self._live_transcript,
            "acoustic_echo_cancellation": self._aec_active,
            "speech": {
                "transport": "Pipecat LocalAudioTransport 0.0.98",
                "turn_taking": "NVIDIA NeMo Voice Agent",
                "asr": "Nemotron Speech Streaming EN 0.6B",
                "asr_device": "RTX 4080 SUPER",
                "asr_chunk_ms": 160,
                "tts": "Pocket TTS 3.0.2",
                "tts_device": "CPU",
                "voice": self._tts_voice,
            },
            "scheduler_paused": self.scheduler_paused(),
            "recent_log": list(self._recent_log),
        }

    async def _publish(self, kind: str, **payload: Any) -> None:
        if kind == "state" and self._phase not in {"command", "proactive"}:
            self._clear_playback()
        event = {
            "type": kind,
            "monotonic_ns": time.monotonic_ns(),
            "state": self.snapshot(),
            **payload,
        }
        self._events.append(event)
        for queue in tuple(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=16)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def _trace_speech_boundary(self, event_type: str) -> None:
        """Correlate speech edges without copying words or acoustic data."""
        transcript = self._live_transcript
        boundary = event_type.removeprefix("speech_")
        metadata = {
            "event": f"speech.{boundary}",
            "conversation_id": str(self.conversation._conversation.conversation_id)[:96],
            "generation": int(getattr(self.conversation, "_generation", 0)),
            "speech_sequence": self._speech_sequence,
            "user_speaking": self._user_speaking,
            # This describes the latest observed transcript, not an acoustic
            # confidence or proof that a VAD onset was intentional speech.
            "latest_transcript_state": (
                "final" if transcript and transcript.get("final") is True
                else "partial" if transcript else "none"
            ),
        }
        trace.emit(
            "speech", f"Speech {boundary.replace('_', ' ')}",
            [json.dumps(metadata, sort_keys=True)],
        )

    def _command(self) -> tuple[str, ...]:
        return (
            str(REALTIME_PYTHON),
            "-m",
            "obsidience.harness.realtime.speech.worker",
            "--asr-model",
            str(NEMOTRON_MODEL),
            "--pocket-root",
            str(POCKET_ROOT),
            "--voice",
            self._tts_voice,
            "--startup-confirmation",
            REALTIME_CONFIRMATION,
        )

    async def _send_worker(self, payload: dict[str, Any]) -> None:
        process = self._process
        if process is None or process.returncode is not None or process.stdin is None:
            return
        if payload.get("type") in {"speak", "cancel", "stop"}:
            if payload["type"] == "speak":
                self._playback_id = uuid.uuid4().hex
                self._playback_run_id = str(payload.get("run_id") or "")[:128]
                payload = {**payload, "playback_id": self._playback_id}
                activity.emit_playback("pending", run_id=self._playback_run_id,
                                       playback_id=self._playback_id)
            else:
                self._clear_playback()
            self._playback_timing_binding = (
                tuple(payload.get(key) for key in ("generation", "speech_sequence", "turn_id", "run_id"))
                if payload.get("type") == "speak" else None
            )
            self._playback_timing_stages.clear()
        try:
            process.stdin.write((json.dumps(payload) + "\n").encode())
            await process.stdin.drain()
        except Exception:
            self._clear_playback()
            raise

    def _clear_playback(self) -> None:
        self._playback_id = None
        self._playback_run_id = ""
        if activity.playback()["status"] != "idle":
            activity.emit_playback("idle")

    def _record_output_audio(self, event: dict[str, Any]) -> None:
        playback_id = event.get("playback_id")
        if (type(event.get("generation")) is not int
                or event["generation"] != self.conversation._generation
                or not isinstance(playback_id, str)
                or not (playback_id == self._playback_id
                        or (playback_id == "startup" and self._playback_id is None))
                or event.get("status") not in {"speaking", "idle"}
                or type(event.get("level")) not in {int, float}
                or not math.isfinite(event["level"])):
            return
        activity.emit_playback(
            event["status"], level=max(0.0, min(1.0, event["level"]))
            if event["status"] == "speaking" else 0.0,
            run_id=self._playback_run_id, playback_id=playback_id,
        )

    def _record_playback_timing(self, event: dict[str, Any]) -> None:
        stage = event.get("stage")
        if (not isinstance(stage, str)
                or stage not in {"speech_received", "aec_ready", "first_pcm", "first_output_write"}
                or stage in self._playback_timing_stages
                or self._playback_timing_binding is None
                or tuple(event.get(key) for key in ("generation", "speech_sequence", "turn_id", "run_id"))
                != self._playback_timing_binding
                or type(event.get("generation")) is not int
                or type(event.get("speech_sequence")) is not int
                or event["generation"] != self.conversation._generation):
            return
        instant = event.get("monotonic_ns")
        duration = event.get("duration_ms")
        if (type(instant) is not int or not 0 < instant <= time.monotonic_ns()
                or (duration is not None and (type(duration) not in {int, float}
                    or not 0 <= duration <= 86_400_000))):
            return
        self._playback_timing_stages.add(stage)
        trace.latency(stage, monotonic_ns=instant, duration_ms=duration, **{
            key: event[key] for key in ("generation", "speech_sequence", "turn_id", "run_id")
        })

    async def start(self) -> dict[str, Any]:
        from ..execution.scheduler import foreground_admission

        async with foreground_admission("realtime.start"):
            return await self._start_admitted()

    async def restore(self) -> dict[str, Any]:
        """Restore same-login speech intent before autonomous admission opens."""
        path = self._requested_state_path
        if path is None:
            return self.snapshot()
        try:
            requested = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            return self.snapshot()
        if requested != {"enabled": True} or requested.get("enabled") is not True:
            return self.snapshot()
        try:
            return await self.start()
        except (OSError, RuntimeError, ValueError) as exc:
            self._phase = "error"
            self._last_error = f"{type(exc).__name__}: {exc}"[:MAX_EVENT_TEXT]
            await self._publish("state", reason="restore_failed")
            return self.snapshot()

    async def _start_admitted(self) -> dict[str, Any]:
        async with self._lock:
            if self._process is not None:
                return self.snapshot()
            if not REALTIME_PYTHON.is_file() or not REALTIME_PYTHON.resolve().is_file():
                raise RuntimeError("the pinned Obsidience Realtime Python is unavailable")
            if not NEMOTRON_MODEL.is_file():
                raise RuntimeError("the pinned Nemotron streaming ASR model is unavailable")
            self._operation += 1
            operation = self._operation
            self._phase = "starting"
            self._transport_ready = False
            self._requested_proactive = False
            self._started_ns = time.monotonic_ns()
            self._last_error = None
            self._input_level = 0.0
            self._capture_active = False
            self._user_speaking = False
            self._speech_sequence = 0
            self._live_transcript = None
            self._aec_active = False
            self._recent_log.clear()
            try:
                media = await asyncio.to_thread(media_runtime.settings)
                self._audio_source = media["microphone"]
                self._audio_sink = media["speaker"]
                self._tts_voice = media["tts_voice"]
                transport_source = await asyncio.to_thread(
                    media_runtime.prepare_microphone, self._audio_source,
                )
                aec_source, aec_sink = await asyncio.to_thread(
                    media_runtime.start_realtime_aec,
                    self._audio_source,
                    self._audio_sink,
                )
                self._aec_active = True
                await model_runtime.reserve_devices(
                    RUNTIME_LEASE_OWNER, (model_runtime.RTX_4080_DEVICE,),
                )
                self._hardware_leased = True
                RUNTIME_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
                interface_rows = await asyncio.to_thread(media_runtime.interface_catalog)
                for row in interface_rows:
                    if row["id"] == "camera":
                        continue
                    option = next(
                        (item for item in row["options"] if item["id"] == media[row["id"]]),
                        None,
                    )
                    if option is None or not option["available"]:
                        raise RuntimeError(f"selected {row['id']} is not currently available")
                self._vision_source = None
                self._process = await asyncio.create_subprocess_exec(
                    *self._command(),
                    cwd=str(PROJECT_ROOT),
                    env={
                        **os.environ,
                        "PYTHONPATH": ":".join((
                            str(PROJECT_ROOT),
                            "/var/lib/ai/src/obsidience-nemo-speech",
                        )),
                        "CUDA_DEVICE_ORDER": "PCI_BUS_ID",
                        "CUDA_VISIBLE_DEVICES": model_runtime.GPU_UUIDS[
                            model_runtime.RTX_4080_DEVICE
                        ],
                        "HF_HUB_OFFLINE": "1",
                        "HF_HUB_DISABLE_TELEMETRY": "1",
                        "TRANSFORMERS_OFFLINE": "1",
                        "PYTHONUNBUFFERED": "1",
                        "PULSE_SOURCE": transport_source,
                        "PULSE_SINK": aec_sink,
                        "OBSIDIENCE_RAW_SOURCE": transport_source,
                        "OBSIDIENCE_AEC_SOURCE": aec_source,
                    },
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    start_new_session=True,
                )
                self.conversation.speech = self
                if self._requested_state_path is not None:
                    media_runtime._atomic_json(self._requested_state_path, {"enabled": True})
                # Reconnecting speech preserves the one selected conversation.
                # Only the explicit Conversation control creates a new identity.
            except BaseException as exc:
                process, self._process = self._process, None
                if process is not None and process.returncode is None:
                    with contextlib.suppress(ProcessLookupError):
                        os.killpg(process.pid, signal.SIGKILL)
                    await process.wait()
                if self.conversation.speech is self:
                    self.conversation.speech = None
                if self._aec_active:
                    await asyncio.to_thread(media_runtime.stop_realtime_aec)
                    self._aec_active = False
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(
                        media_runtime.set_realtime_camera_active, self._audio_source, False,
                    )
                self._phase = "error"
                self._last_error = f"{type(exc).__name__}: {exc}"[:MAX_EVENT_TEXT]
                if self._hardware_leased:
                    await model_runtime.release_devices(RUNTIME_LEASE_OWNER)
                    self._hardware_leased = False
                raise
            self._monitor = asyncio.create_task(
                self._monitor_process(self._process, operation),
                name="obsidience-realtime-monitor",
            )
            await self._publish("state", reason="start_requested")
            return self.snapshot()

    async def set_proactive(self, enabled: bool) -> dict[str, Any]:
        if not isinstance(enabled, bool):
            raise TypeError("proactive must be bool")
        async with self._lock:
            process = self._process
            if process is None or process.returncode is not None:
                raise RuntimeError("real-time mode is not running")
            if self._phase not in {"command", "proactive"}:
                raise RuntimeError("real-time mode is not ready")
            self._requested_proactive = enabled
            self._phase = "proactive" if enabled else "command"
            await self._publish("state", reason="mode_applied")
            return self.snapshot()

    async def stop(self, *, preserve_requested: bool = False) -> dict[str, Any]:
        finalize_observations = False
        intent_error = None

        def stopped_snapshot():
            if intent_error is not None:
                raise RuntimeError("Realtime stopped, but its restart intent could not be cleared") from intent_error
            return self.snapshot()

        async with self._lock:
            if not preserve_requested and self._requested_state_path is not None:
                try:
                    self._requested_state_path.unlink(missing_ok=True)
                except OSError as exc:
                    intent_error = exc
            conversation_id = self.conversation._conversation.conversation_id
            process = self._process
            operation = self._operation
            if process is None or process.returncode is not None:
                if self.conversation.speech is self:
                    await self.conversation.cancel()
                finalize_observations = bool(
                    self._phase not in {"off", "error"}
                    or self.conversation._ledger().deferred_observation_finalizations()
                )
                await asyncio.to_thread(media_runtime.stop_realtime_aec)
                self._aec_active = False
                await asyncio.to_thread(
                    media_runtime.set_realtime_camera_active, self._audio_source, False,
                )
                self._phase = "off"
                self._transport_ready = False
                self._input_level = 0.0
                self._capture_active = False
                self._user_speaking = False
                self._live_transcript = None
                self._requested_proactive = False
                self._process = None
                release_hardware = self._hardware_leased
                self._hardware_leased = False
                if release_hardware:
                    await model_runtime.release_devices(RUNTIME_LEASE_OWNER)
                if self.conversation.speech is self:
                    self.conversation.speech = None
                result = self.snapshot()
            else:
                result = None
            if result is None and self._phase != "stopping":
                self._phase = "stopping"
                self._requested_proactive = False
                await self.conversation.cancel()
                await self._send_worker({"type": "stop"})
                await self._publish("state", reason="stop_requested")
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGINT)
        if result is not None:
            if finalize_observations:
                await self.conversation.finalize_pending(
                    "",
                    session_boundary="realtime.stopped",
                )
            return stopped_snapshot()
        try:
            await asyncio.wait_for(process.wait(), timeout=60)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(process.wait(), timeout=15)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
        async with self._lock:
            if self._process is not process or self._operation != operation:
                return stopped_snapshot()
            if self._aec_active:
                await asyncio.to_thread(media_runtime.stop_realtime_aec)
                self._aec_active = False
            if self._hardware_leased:
                await model_runtime.release_devices(RUNTIME_LEASE_OWNER)
                self._hardware_leased = False
            await asyncio.to_thread(
                media_runtime.set_realtime_camera_active, self._audio_source, False,
            )
            if self.conversation.speech is self:
                self.conversation.speech = None
            self._process = None
            self._phase = "off"
            self._transport_ready = False
            self._input_level = 0.0
            self._capture_active = False
            self._user_speaking = False
            self._live_transcript = None
            self._started_ns = None
            self._vision_source = None
            await self._publish("state", reason="stopped")
        await self.conversation.finalize_pending(
            "",
            session_boundary="realtime.stopped",
        )
        return stopped_snapshot()

    async def _monitor_process(
        self,
        process: asyncio.subprocess.Process,
        operation: int,
    ) -> None:
        assert process.stdout is not None
        pending_partial: tuple[int, str] | None = None
        prepared_sequence = 0
        try:
            while True:
                raw = await process.stdout.readline()
                if not raw:
                    break
                if operation != self._operation or self._process is not process:
                    return
                # Keep draining a stopping worker, but admit no late state or
                # work. Stop owns cleanup until it releases this exact process.
                if self._phase in {"stopping", "off", "error"}:
                    continue
                if len(raw) > MAX_WORKER_EVENT_BYTES:
                    continue
                # Parse the complete bounded record before trimming display text.
                # Trimming JSON would drop valid final transcripts with timings.
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    worker_event = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    worker_event = None
                event_type = (
                    str(worker_event.get("type", ""))
                    if isinstance(worker_event, dict)
                    else ""
                )
                if event_type == "speech_timing":
                    self._record_playback_timing(worker_event)
                    continue
                if event_type == "output_audio":
                    self._record_output_audio(worker_event)
                    continue
                if event_type == "input_capture":
                    active = worker_event.get("active")
                    if isinstance(active, bool) and active != self._capture_active:
                        # This provisional VAD hint is presentation only. NeMo's
                        # recognized speech owns interruption and final admission.
                        self._capture_active = active
                        if (active and self._live_transcript
                                and self._live_transcript.get("final") is True):
                            self._live_transcript = None
                        await self._publish("runtime", reason="capture_active")
                    continue
                if event_type == "input_level":
                    level = worker_event.get("level")
                    if isinstance(level, (int, float)) and not isinstance(level, bool):
                        numeric_level = float(level)
                        if math.isfinite(numeric_level):
                            self._input_level = max(0.0, min(1.0, numeric_level))
                            await self._publish("runtime", reason="input_level")
                    continue
                sequence = worker_event.get("speech_sequence") if isinstance(worker_event, dict) else None
                exact_sequence = type(sequence) is int and 0 < sequence < 2**31
                if exact_sequence and event_type in {"speech_detected", "speech_ended", "interruption"}:
                    self._speech_sequence = sequence
                if event_type == "speech_detected":
                    if not exact_sequence and not self._user_speaking:
                        self._speech_sequence += 1
                    self._user_speaking = True
                    if self._live_transcript and self._live_transcript.get("final") is True:
                        self._live_transcript = None
                elif event_type == "speech_ended":
                    self._user_speaking = False
                elif event_type in {"transcript_partial", "transcript_final"}:
                    transcript_text = " ".join(
                        str(worker_event.get("text", "")).split()
                    )[:MAX_EVENT_TEXT]
                    if transcript_text:
                        self._live_transcript = {
                            "text": transcript_text,
                            "final": event_type == "transcript_final",
                        }
                if event_type in {"speech_detected", "speech_ended"}:
                    self._trace_speech_boundary(event_type)
                display_line = line
                if event_type == "transport_ready":
                    display_line = "[pipecat-local-audio-ready]"
                elif event_type == "runtime_ready":
                    display_line = "[obsidience-realtime-ready]"
                elif event_type == "speech_detected":
                    display_line = "[listening: speech detected]"
                elif event_type == "speech_ended":
                    display_line = "[listening: speech ended]"
                elif event_type == "transcript_partial":
                    display_line = f"[partial] {transcript_text}"
                elif event_type == "transcript_final":
                    display_line = f"[heard] {transcript_text}"
                elif event_type == "interruption":
                    display_line = "[playback interrupted]"
                elif event_type == "speech_started":
                    display_line = "[playback started]"
                elif event_type == "speech_stopped":
                    display_line = "[playback stopped]"
                elif event_type == "fatal":
                    display_line = f"[worker fatal: {worker_event.get('error')}]"
                elif event_type == "summary":
                    display_line = "[realtime session summary]"
                self._recent_log.append(display_line[:MAX_EVENT_TEXT])
                if event_type == "transport_ready":
                    self._transport_ready = True
                    await self._publish("state", reason="transport_ready")
                elif event_type == "runtime_ready":
                    if self._phase != "starting":
                        continue
                    self._phase = "command"
                    await self._publish("state", reason="runtime_ready")
                elif event_type == "transcript_final":
                    pending_partial = None
                    prepared_sequence = 0
                    async with self._lock:
                        if (operation != self._operation or self._process is not process
                                or self._phase not in {"command", "proactive"}):
                            continue
                        timing = _input_speech_timing(worker_event.get("speech_timing"))
                        if timing is not None:
                            self._speech_sequence = timing["speech_sequence"]
                        self._trace_speech_boundary(event_type)
                        await self.conversation.submit(
                            transcript_text, source="realtime", wait=False,
                            **({"speech_timing": timing} if timing is not None else {}),
                        )
                    await self._publish("runtime", line=display_line)
                elif event_type == "transcript_partial":
                    if exact_sequence:
                        pending_partial = (sequence, transcript_text)
                        if (sequence == prepared_sequence and self._user_speaking
                                and self._phase in {"command", "proactive"}):
                            self.conversation.prepare_speech_prefix(transcript_text, sequence)
                    await self._publish("runtime", line=display_line)
                elif event_type == "interruption":
                    async with self._lock:
                        if (operation != self._operation or self._process is not process
                                or self._phase not in {"command", "proactive"}):
                            continue
                        self._trace_speech_boundary(event_type)
                        await self.conversation.cancel(
                            reason="speech.interruption", stop_playback=False,
                        )
                        # Pipecat queues the interruption frames independently
                        # of partial text. Admit the exact pending prefix only
                        # after its own interruption has drained previous work.
                        prepared_sequence = self._speech_sequence
                        if pending_partial and pending_partial[0] == prepared_sequence:
                            self.conversation.prepare_speech_prefix(pending_partial[1], prepared_sequence)
                    await self._publish("runtime", line=display_line)
                elif event_type == "fatal":
                    self._clear_playback()
                    self._last_error = display_line[:MAX_EVENT_TEXT]
                    await self._publish("runtime", line=display_line)
                elif event_type in {
                    "transport_ready", "speech_detected", "speech_ended",
                    "speech_started", "speech_stopped", "playback_started",
                    "playback_stopped",
                }:
                    await self._publish("runtime", line=display_line)
            returncode = await process.wait()
            async with self._lock:
                if operation != self._operation or self._process is not process:
                    return
                if self._phase == "stopping":
                    return
                conversation_id = self.conversation._conversation.conversation_id
                self._phase = "stopping"
                await self.conversation.cancel()
                if self._aec_active:
                    await asyncio.to_thread(media_runtime.stop_realtime_aec)
                    self._aec_active = False
                if self._hardware_leased:
                    await model_runtime.release_devices(RUNTIME_LEASE_OWNER)
                    self._hardware_leased = False
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(
                        media_runtime.set_realtime_camera_active, self._audio_source, False,
                    )
                if self.conversation.speech is self:
                    self.conversation.speech = None
                self._process = None
                self._started_ns = None
                self._requested_proactive = False
                self._transport_ready = False
                self._input_level = 0.0
                self._capture_active = False
                self._user_speaking = False
                self._live_transcript = None
                self._vision_source = None
                if returncode in {0, -signal.SIGINT}:
                    self._phase = "off"
                else:
                    self._phase = "error"
                    self._transport_ready = False
                    self._last_error = self._last_error or f"live runtime exited {returncode}"
                await self._publish("state", reason="process_exited", returncode=returncode)
            await self.conversation.finalize_pending(
                "",
                session_boundary="realtime.runtime_exited",
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            async with self._lock:
                if operation == self._operation and self._process is process:
                    if self._phase == "stopping":
                        return
                    self._phase = "error"
                    self._last_error = f"{type(exc).__name__}: {exc}"[:MAX_EVENT_TEXT]
                    await self._publish("state", reason="monitor_failed")
                    # A failed monitor cannot release a live worker's GPU or
                    # another operation's lease. Stop retains exact ownership.

    async def shutdown(self) -> None:
        await self.stop(preserve_requested=True)
        monitor = self._monitor
        if monitor is not None and monitor is not asyncio.current_task():
            with contextlib.suppress(asyncio.CancelledError):
                await monitor
        self._monitor = None


RUNTIME = RealtimeSessionManager(requested_state_path=RUNTIME_ROOT / "requested.json")
