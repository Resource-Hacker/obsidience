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
from ..conversation.selection import EXECUTIVE_REF
from ..knowledge.vault import resolver
from ..execution import activity, trace
from ..models import runtime as model_runtime
from . import media as media_runtime

RealtimePhase = Literal["off", "starting", "wake", "command", "proactive", "suspended", "stopping", "error"]
READY_PHASES = {"wake", "command", "proactive"}

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
STDERR_TAIL_LINES = 40
# One automatic recovery per crash window; a repeat within it stays in error.
CRASH_RESTART_DELAY_SECS = 2.0
CRASH_RESTART_WINDOW_SECS = 300.0
AUDIO_MONITOR_BACKOFF_SECS = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)
PULSE_SOCKET = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "pulse" / "native"


_input_speech_timing = trace.input_speech_timing


def _exit_description(returncode: int) -> str:
    if returncode < 0:
        with contextlib.suppress(ValueError):
            return f"signal {signal.Signals(-returncode).name}"
        return f"signal {-returncode}"
    return f"code {returncode}"


class RealtimeSessionManager:
    def __init__(self, conversation=None, *, requested_state_path: Path | None = None) -> None:
        self._requested_state_path = requested_state_path
        self._lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None
        self._monitor: asyncio.Task[None] | None = None
        self._stderr_drain: asyncio.Task[None] | None = None
        self._restart_task: asyncio.Task[None] | None = None
        self._crash_restart_at: float | None = None
        self._last_exit: dict[str, Any] | None = None
        self._audio_monitor: asyncio.Task[None] | None = None
        self._audio_reconnect_pending = False
        self._audio_reconnect_attempt: tuple | None = None
        self._transport_ready = False
        self._phase: RealtimePhase = "off"
        self._mode = "wake"
        self._desired_mode = "off"
        self._mode_revision = 0
        self._wake_open = False
        self._wake_word = "Computer"
        self._paused_for_work = False
        self._standby_event = asyncio.Event()
        self._standby_task: asyncio.Task | None = None
        self._unsubscribe_activity = None
        self._closed = False
        self._deferred_reply: dict | None = None
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
        self._speech_handoff_task: asyncio.Task | None = None
        self._live_transcript: dict[str, Any] | None = None
        self._aec_active = False
        self._tts_voice = media_runtime.DEFAULT_TTS_VOICE
        self._cue_names: list[str] = []
        self._wake_rejected = {"mid_sentence": 0, "possessive": 0}
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
        # Accepted wake/recognized speech is foreground demand. Passive room
        # VAD and idle listening do not pause background work. Keep the final
        # dispatch bridge until its existing conversation task owns admission.
        return (self._phase in {"starting", "stopping"} or self._wake_open
                or self._user_speaking or (self._speech_handoff_task is not None
                                          and not self._speech_handoff_task.done()))

    async def _prioritize_speech_capture(self) -> None:
        from ..execution.scheduler import foreground_admission

        # Signal through the existing scheduler; each executor joins its own
        # cancellation. Its admission count is transient; capture state above
        # prevents another autonomous run from starting before final dispatch.
        async with foreground_admission("speech.capture"):
            pass

    def _speech_handoff_done(self, task: asyncio.Task) -> None:
        if self._speech_handoff_task is task:
            self._speech_handoff_task = None
        from ..execution.scheduler import wake_scheduler
        wake_scheduler()

    def snapshot(self) -> dict[str, Any]:
        process = self._process
        aec_backend = (media_runtime.realtime_aec_backend()
                       if not self._audio_reconnect_pending else "none")
        return {
            "schema_version": 1,
            "phase": self._phase,
            "mode": self._desired_mode,
            "wake_word": self._wake_word,
            "command_open": self._wake_open or self._mode == "realtime",
            "executive": self.conversation.readiness(),
            "enabled": self._phase not in {"off", "error"},
            "ready": self._phase in READY_PHASES,
            "transport_ready": self._transport_ready,
            "proactive": self._phase == "proactive",
            "requested_proactive": self._requested_proactive,
            "pid": None if process is None or process.returncode is not None else process.pid,
            "started_monotonic_ns": self._started_ns,
            "last_error": self._last_error,
            "last_exit": self._last_exit,
            "vision_source": self._vision_source,
            "audio_source": self._audio_source,
            "audio_sink": self._audio_sink,
            "input_level": self._input_level,
            "playback": activity.playback(),
            "capture_active": self._capture_active,
            "user_speaking": self._user_speaking,
            "live_transcript": self._live_transcript,
            "acoustic_echo_cancellation": self._aec_active and aec_backend != "none",
            "echo_cancellation_backend": aec_backend,
            "speech": {
                "input_channel": "left" if self._audio_source == media_runtime.UMA8_SOURCE else "mono",
                "transport": "Pipecat LocalAudioTransport 0.0.98",
                "turn_taking": "NVIDIA NeMo Voice Agent",
                "asr": "Nemotron Speech Streaming EN 0.6B",
                "asr_device": "RTX 4080 SUPER",
                "asr_chunk_ms": 160,
                "tts": "Pocket TTS 3.0.2",
                "tts_device": "CPU",
                "voice": self._tts_voice,
                "cues": list(self._cue_names),
                "wake_rejected": dict(self._wake_rejected),
            },
            "scheduler_paused": self.scheduler_paused(),
            "recent_log": list(self._recent_log),
        }

    async def _publish(self, kind: str, **payload: Any) -> None:
        queued_reply = self._deferred_reply and self._phase in {"suspended", "starting"}
        if kind == "state" and self._phase not in READY_PHASES and not queued_reply:
            self._clear_playback()
        state = self.snapshot()
        if state["last_exit"] is not None:
            # Streamed state stays small; GET /api/realtime keeps the tail.
            state["last_exit"] = {key: value for key, value in state["last_exit"].items()
                                  if key != "stderr_tail"}
        event = {
            "type": kind,
            "monotonic_ns": time.monotonic_ns(),
            "state": state,
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

    async def publish_readiness(self) -> None:
        await self._publish("state", reason="executive_readiness")

    def _model_activity(self, busy: bool) -> None:
        if busy:
            self.conversation.invalidate_readiness()
        self._standby_event.set()

    async def _audio_devices_changed(self) -> None:
        async with self._lock:
            if (self._closed or self._desired_mode == "off"
                    or self._audio_source != media_runtime.UMA8_SOURCE):
                return
            if not self._aec_active and not self._audio_reconnect_pending:
                return
            intact, generation = await asyncio.to_thread(
                media_runtime.uma8_reference_state, self._audio_sink,
            )
            if intact and not self._audio_reconnect_pending:
                return
            lost = self._aec_active
            if lost:
                self._audio_reconnect_pending = True
                self._audio_reconnect_attempt = None
                self._phase = "error"
                self._transport_ready = False
                self._last_error = "Selected UMA-8 audio disconnected; waiting for its capture and hardware reference."
                await self._publish("state", reason="audio_disconnected")
        if lost:
            # Drain the same capture/reference owner; never replay interrupted
            # speech or silently retain a stream on a fallback microphone.
            await self.stop(preserve_requested=True, audio_lost=True)
        async with self._lock:
            if self._closed or self._desired_mode == "off" or not self._audio_reconnect_pending:
                return
            self._phase = "error"
            await self._publish("state", reason="waiting_for_audio")
            if generation is None or generation == self._audio_reconnect_attempt:
                return
            self._audio_reconnect_attempt = generation
            mode, operation = self._desired_mode, self._operation
            if mode == "wake" and model_runtime.RUNTIME.work_requested:
                self._paused_for_work = True
                self._audio_reconnect_pending = False
                self._phase = "suspended"
                self._standby_event.set()
                return
        try:
            await self._start_admitted(mode=mode, audio_reconnect_operation=operation)
        except (OSError, RuntimeError, ValueError) as exc:
            # One attempt per available endpoint generation. A permanent bad
            # graph stays explicit rather than repeatedly loading the worker.
            self._last_error = f"Audio reconnection failed: {exc}"[:MAX_EVENT_TEXT]
            await self._publish("state", reason="audio_reconnect_failed")

    def _ensure_audio_monitor(self) -> None:
        if self._audio_monitor is None or self._audio_monitor.done():
            self._audio_monitor = asyncio.create_task(
                self._watch_audio_devices(), name="obsidience-audio-hotplug",
            )

    async def _watch_audio_devices(self) -> None:
        """One device subscription while voice is wanted, recreated after Pulse restarts."""
        attempt = 0
        while not self._closed:
            started = time.monotonic()
            await self._subscribe_audio_devices(restored=attempt > 0)
            if time.monotonic() - started >= 60:
                attempt = 0
            # Bounded backoff, never a tight loop. While voice is off, start()
            # recreates this watcher instead.
            while not self._closed and self._desired_mode != "off":
                await asyncio.sleep(AUDIO_MONITOR_BACKOFF_SECS[
                    min(attempt, len(AUDIO_MONITOR_BACKOFF_SECS) - 1)])
                attempt += 1
                if PULSE_SOCKET.exists():
                    break
            if self._closed or self._desired_mode == "off":
                return

    async def _subscribe_audio_devices(self, *, restored: bool = False) -> None:
        subscription = None
        try:
            subscription = await asyncio.create_subprocess_exec(
                "/usr/bin/pactl", "subscribe", stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, env={**os.environ, "LC_ALL": "C"},
            )
            assert subscription.stdout is not None
            if restored and (self._last_error or "").startswith("Audio hotplug monitor failed"):
                self._last_error = None
                await self._publish("state", reason="audio_monitor_restored")
            await self._audio_devices_changed()
            while line := await subscription.stdout.readline():
                if self._closed:
                    return
                if (b" on source #" in line or b" on sink #" in line) and (
                    b"'new'" in line or b"'remove'" in line
                    or (self._audio_reconnect_pending and b"'change'" in line)
                ):
                    await self._audio_devices_changed()
            raise RuntimeError("the audio-device subscription closed")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if not self._closed:
                self._last_error = f"Audio hotplug monitor failed: {exc}"[:MAX_EVENT_TEXT]
                await self._publish("state", reason="audio_monitor_failed")
        finally:
            if subscription is not None and subscription.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    subscription.terminate()
                try:
                    await asyncio.wait_for(subscription.wait(), timeout=2)
                except TimeoutError:
                    with contextlib.suppress(ProcessLookupError):
                        subscription.kill()
                    await subscription.wait()

    async def _standby(self) -> None:
        while not self._closed:
            await self._standby_event.wait()
            self._standby_event.clear()
            if self._closed:
                return
            if not model_runtime.RUNTIME.work_requested:
                if self._paused_for_work and self._desired_mode == "wake":
                    try:
                        await self._start_admitted(mode="wake", only_if_requested=True)
                    except (OSError, RuntimeError, ValueError):
                        # A new owner may have claimed the GPU on this edge.
                        # Another work boundary can resume it; never retry-loop.
                        if model_runtime.RUNTIME.work_requested:
                            self._phase = "suspended"
                            self._last_error = None
                self.conversation.prepare_idle()
            await self.publish_readiness()

    async def _yield_for_model(self) -> None:
        if self._desired_mode == "wake":
            self._paused_for_work = True
            # A cancelled model request must still finish the speech handoff;
            # otherwise a stopped worker can retain an unreleasable GPU lease.
            draining = asyncio.create_task(
                self.stop(preserve_requested=True, for_work=True), name="obsidience-speech-yield",
            )
            cancelled = False
            while True:
                try:
                    await asyncio.shield(draining)
                    break
                except asyncio.CancelledError:
                    cancelled = True
                    if draining.done():
                        break
            if cancelled:
                raise asyncio.CancelledError

    async def speak(self, payload: dict) -> None:
        if self._paused_for_work and self._desired_mode == "wake" and self._phase not in READY_PHASES:
            # One accepted public reply may wait for the same speech owner to
            # regain hardware. Generation changes and Stop discard it.
            self._deferred_reply = self._prepare_playback(payload)
            return
        if self._phase in READY_PHASES:
            await self._send_worker(payload)

    async def cue(self, name: str) -> None:
        """Nonverbal feedback uses the same generation-bound speech transport."""
        if self._phase in READY_PHASES and name in self._cue_names:
            try:
                await self._send_worker({
                    "type": "cue", "name": name,
                    "generation": self.conversation._generation,
                })
            except (OSError, RuntimeError):
                trace.emit("error", f"Computer cue delivery failed: {name}")

    def _prepare_playback(self, payload: dict) -> dict:
        """Publish queued speech at acceptance, including a deferred worker handoff."""
        self._playback_id = uuid.uuid4().hex
        self._playback_run_id = str(payload.get("run_id") or "")[:128]
        activity.emit_playback("pending", run_id=self._playback_run_id,
                              playback_id=self._playback_id)
        return {**payload, "playback_id": self._playback_id}

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
            "--input-channel", "left" if media_runtime.realtime_aec_backend() == "uma8" else "mono",
            "--wake-word", self._wake_word,
            "--mode", self._mode,
            "--mode-revision", str(self._mode_revision),
            "--startup-confirmation",
            REALTIME_CONFIRMATION if self._mode == "realtime" else "",
        )

    async def _send_worker(self, payload: dict[str, Any]) -> None:
        if payload.get("type") in {"cancel", "stop"}:
            if payload.get("type") == "stop" or payload.get("stop_playback", True):
                self._wake_open = self._capture_active = self._user_speaking = False
            self._deferred_reply = None
            self._clear_playback()
        process = self._process
        if process is None or process.returncode is not None or process.stdin is None:
            return
        if payload.get("type") in {"speak", "cancel", "stop"}:
            if payload["type"] == "speak":
                if not payload.get("playback_id") or payload["playback_id"] != self._playback_id:
                    payload = self._prepare_playback(payload)
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

    async def start(self, *, mode: str = "realtime") -> dict[str, Any]:
        from ..execution.scheduler import foreground_admission

        if self._process is not None:
            return await self.set_listening_mode(mode)
        if self._unsubscribe_activity is not None:
            # restore() owns the device watcher; it ends while voice is off.
            self._ensure_audio_monitor()
        if mode == "wake":
            # Arming passive listening is not foreground work. If another
            # agent owns the model, its release event starts this same worker.
            if not model_runtime.RUNTIME.work_requested:
                try:
                    return await self._start_admitted(mode=mode)
                except RuntimeError:
                    if not model_runtime.RUNTIME.work_requested:
                        raise
            async with self._lock:
                self._mode = self._desired_mode = "wake"
                self._paused_for_work = True
                self._phase = "suspended"
                self._last_error = None
                if self._requested_state_path is not None:
                    media_runtime._atomic_json(self._requested_state_path, {"mode": "wake"})
                self._standby_event.set()
                await self._publish("state", reason="waiting_for_work")
                return self.snapshot()
        async with foreground_admission("realtime.start"):
            return await self._start_admitted(mode=mode)

    async def restore(self) -> dict[str, Any]:
        """Wake-by-name is the default; retain explicit same-login mute/mode."""
        path = self._requested_state_path
        if path is None:
            return self.snapshot()
        self._closed = False
        self._ensure_audio_monitor()
        if self._unsubscribe_activity is None:
            self._unsubscribe_activity = model_runtime.RUNTIME.subscribe_activity(self._model_activity)
            self._standby_task = asyncio.create_task(self._standby(), name="obsidience-voice-standby")
        try:
            requested = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            requested = {"mode": "wake"}
        if not isinstance(requested, dict):
            requested = {}
        # Legacy intent is exactly {"enabled": true}; 1 == True must not match.
        legacy = set(requested) == {"enabled"} and requested["enabled"] is True
        mode = "realtime" if legacy else requested.get("mode", "wake")
        if mode == "off":
            return self.snapshot()
        if mode not in {"wake", "realtime"}:
            mode = "wake"
        try:
            return await self.start(mode=mode)
        except (OSError, RuntimeError, ValueError) as exc:
            self._phase = "error"
            self._last_error = f"{type(exc).__name__}: {exc}"[:MAX_EVENT_TEXT]
            await self._publish("state", reason="restore_failed")
            return self.snapshot()

    async def _start_admitted(self, *, mode: str = "realtime",
                             only_if_requested: bool = False,
                             audio_reconnect_operation: int | None = None) -> dict[str, Any]:
        if mode not in {"wake", "realtime"}:
            raise ValueError("Voice mode must be wake or realtime")
        async with self._lock:
            if audio_reconnect_operation is not None and (
                self._closed or self._desired_mode != mode
                or not self._audio_reconnect_pending or self._operation != audio_reconnect_operation
            ):
                return self.snapshot()
            if only_if_requested and (self._closed or self._desired_mode != mode
                                      or not self._paused_for_work):
                return self.snapshot()
            if self._process is not None:
                return self.snapshot()
            # Bind the worker and its status to the accepted Executive identity.
            executive = resolver(include_system=False).resolve(EXECUTIVE_REF)
            self._wake_word = executive.title.strip() if executive is not None else "Computer"
            self._wake_word = self._wake_word or "Computer"
            if not REALTIME_PYTHON.is_file() or not REALTIME_PYTHON.resolve().is_file():
                raise RuntimeError("the pinned Obsidience Realtime Python is unavailable")
            if not NEMOTRON_MODEL.is_file():
                raise RuntimeError("the pinned Nemotron streaming ASR model is unavailable")
            self._operation += 1
            self._mode = self._desired_mode = mode
            self._wake_open = False
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
                await asyncio.to_thread(
                    media_runtime.prepare_microphone, self._audio_source,
                )
                aec_source, playback_sink = await asyncio.to_thread(
                    media_runtime.start_realtime_aec,
                    self._audio_source,
                    self._audio_sink,
                )
                self._aec_active = True
                await model_runtime.reserve_devices(
                    RUNTIME_LEASE_OWNER, (model_runtime.RTX_4080_DEVICE,),
                    yield_when_needed=self._yield_for_model if mode == "wake" else None,
                    memory_mib={model_runtime.RTX_4080_DEVICE: 6000},
                    shared_model_ids=(model_runtime.FLASH_NEXT_MODEL,),
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
                        "PULSE_SOURCE": aec_source,
                        "PULSE_SINK": playback_sink,
                        "PULSE_PROP": "node.dont-fallback=true node.linger=true",
                    },
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    # Its own pipe: stdout carries only bounded JSON events.
                    stderr=asyncio.subprocess.PIPE,
                    start_new_session=True,
                )
                model_runtime.RUNTIME.set_reservation_process(RUNTIME_LEASE_OWNER, self._process.pid)
                self.conversation.speech = self
                if self._requested_state_path is not None:
                    media_runtime._atomic_json(self._requested_state_path, {"mode": mode})
                # Reconnecting speech preserves the one selected conversation.
                # Only the explicit Conversation control creates a new identity.
                self._audio_reconnect_pending = False
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

    async def set_listening_mode(self, mode: str) -> dict[str, Any]:
        if mode == "off":
            return await self.stop()
        if mode not in {"wake", "realtime"}:
            raise ValueError("Voice mode must be wake, realtime or off")
        if self._process is not None and self._process.returncode is not None:
            await self.stop(preserve_requested=True)
        if self._process is None:
            return await self.start(mode=mode)
        async with self._lock:
            if mode == self._mode and self._phase in READY_PHASES:
                return self.snapshot()
            await self.conversation.cancel(reason="voice.mode_changed")
            self._mode = self._desired_mode = mode
            self._mode_revision += 1
            self._wake_open = False
            self._requested_proactive = False
            self._live_transcript = None
            self._capture_active = self._user_speaking = False
            self._input_level = 0.0
            self._phase = "starting"
            model_runtime.RUNTIME.set_reservation_yielder(
                RUNTIME_LEASE_OWNER, self._yield_for_model if mode == "wake" else None,
            )
            await self._send_worker({"type": "mode", "mode": mode, "mode_revision": self._mode_revision})
            if self._requested_state_path is not None:
                media_runtime._atomic_json(self._requested_state_path, {"mode": mode})
            await self._publish("state", reason="mode_requested")
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

    async def stop(self, *, preserve_requested: bool = False, for_work: bool = False,
                   audio_lost: bool = False) -> dict[str, Any]:
        finalize_observations = False
        intent_error = None

        def stopped_snapshot():
            if intent_error is not None:
                raise RuntimeError("Realtime stopped, but its restart intent could not be cleared") from intent_error
            return self.snapshot()

        async with self._lock:
            if not preserve_requested:
                self._desired_mode = "off"
                self._paused_for_work = False
                self._audio_reconnect_pending = False
                self._audio_reconnect_attempt = None
            self._wake_open = False
            if not preserve_requested and self._requested_state_path is not None:
                try:
                    media_runtime._atomic_json(self._requested_state_path, {"mode": "off"})
                except OSError as exc:
                    intent_error = exc
            conversation_id = self.conversation._conversation.conversation_id
            process = self._process
            operation = self._operation
            if process is None or process.returncode is not None:
                if self.conversation.speech is self and not for_work:
                    await self.conversation.cancel()
                finalize_observations = bool(
                    self._phase not in {"off", "error"}
                    or self.conversation._ledger().deferred_observation_finalizations()
                )
                await asyncio.to_thread(media_runtime.stop_realtime_aec)
                self._aec_active = False
                # An unplugged source cannot resolve; release must still finish.
                with contextlib.suppress(Exception):
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
                if self.conversation.speech is self and not for_work:
                    self.conversation.speech = None
                if for_work:
                    self._phase = "suspended"
                result = self.snapshot()
            else:
                result = None
            if result is None and self._phase != "stopping":
                self._phase = "stopping"
                self._requested_proactive = False
                if not for_work:
                    await self.conversation.cancel()
                await self._send_worker({"type": "stop"})
                await self._publish("state", reason="stop_requested")
                with contextlib.suppress(ProcessLookupError):
                    # PortAudio cleanup can block in stop_stream after its
                    # device vanishes. The stateless worker cannot drain that
                    # dead input; cancellation is already owned by the parent.
                    os.killpg(process.pid, signal.SIGTERM if audio_lost else signal.SIGINT)
        if result is not None:
            if finalize_observations and not for_work:
                await self.conversation.finalize_pending(
                    "",
                    session_boundary="realtime.stopped",
                )
            return stopped_snapshot()
        try:
            await asyncio.wait_for(process.wait(), timeout=5 if audio_lost else 60)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL if audio_lost else signal.SIGTERM)
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
            with contextlib.suppress(Exception):
                await asyncio.to_thread(
                    media_runtime.set_realtime_camera_active, self._audio_source, False,
                )
            if self.conversation.speech is self and not for_work:
                self.conversation.speech = None
            self._process = None
            self._phase = "suspended" if for_work else "off"
            self._transport_ready = False
            self._input_level = 0.0
            self._capture_active = False
            self._user_speaking = False
            self._live_transcript = None
            self._started_ns = None
            self._vision_source = None
            await self._publish("state", reason="stopped")
        if not for_work:
            await self.conversation.finalize_pending("", session_boundary="realtime.stopped")
        return stopped_snapshot()

    async def _monitor_process(
        self,
        process: asyncio.subprocess.Process,
        operation: int,
    ) -> None:
        assert process.stdout is not None
        pending_partial: tuple[int, str] | None = None
        prepared_sequence = 0
        stderr_tail: deque[str] = deque(maxlen=STDERR_TAIL_LINES)
        stderr = getattr(process, "stderr", None)
        if stderr is not None:
            # Drain until EOF so a chatty worker can never block on its pipe.
            self._stderr_drain = asyncio.create_task(
                self._drain_stderr(stderr, stderr_tail), name="obsidience-speech-stderr",
            )
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
                if self._mode == "wake" and not isinstance(worker_event, dict):
                    # Upstream diagnostic text may include raw ASR tokens.
                    # Ambient recognition is never a retained public log.
                    continue
                if event_type == "wake_detected":
                    if (self._mode != "wake" or self._phase not in READY_PHASES
                            or worker_event.get("mode_revision", 0) != self._mode_revision):
                        continue
                    self._wake_open = True
                    self._capture_active = True
                    self._live_transcript = None
                    await self._prioritize_speech_capture()
                    await self._publish("runtime", reason="wake_detected")
                    continue
                if event_type == "wake_rejected":
                    reason = worker_event.get("reason")
                    if (reason in self._wake_rejected
                            and worker_event.get("mode_revision", 0) == self._mode_revision):
                        # Counts only; the rejected words never leave the worker.
                        self._wake_rejected[reason] += 1
                        trace.emit("speech", "Wake word heard, not as an address", [json.dumps({
                            "event": "speech.wake_rejected", "reason": reason,
                            "count": self._wake_rejected[reason],
                        }, sort_keys=True)])
                    continue
                if event_type == "wake_idle":
                    if worker_event.get("mode_revision", 0) == self._mode_revision:
                        if self._wake_open:
                            await self.cue("cancel")
                        self._wake_open = False
                        self._capture_active = False
                        self._user_speaking = False
                        self._input_level = 0.0
                        self._standby_event.set()
                        await self._publish("runtime", reason="wake_idle")
                    continue
                if event_type in {"cue_started", "cue_finished"}:
                    name = worker_event.get("name")
                    generation = worker_event.get("generation")
                    if (name in self._cue_names and type(generation) is int
                            and (generation == self.conversation._generation
                                 or (name == "ready" and 0 <= generation < self.conversation._generation))):
                        # A started opening chirp can finish after natural speech
                        # advances the turn. These events attest actual writes only.
                        trace.emit("speech", f"Computer cue: {name} ({event_type[4:]})", [
                            json.dumps({"event": "speech." + event_type, "name": name,
                                        "generation": worker_event["generation"]}, sort_keys=True),
                        ])
                        await self._publish("runtime", reason=event_type, cue=name)
                    continue
                if event_type in {"speech_detected", "speech_ended", "interruption",
                                  "transcript_partial", "transcript_final"}:
                    if worker_event.get("mode_revision", 0) != self._mode_revision:
                        continue
                    if self._mode == "wake" and not self._wake_open and event_type != "speech_ended":
                        continue
                if event_type == "speech_timing":
                    self._record_playback_timing(worker_event)
                    continue
                if event_type == "output_audio":
                    self._record_output_audio(worker_event)
                    continue
                if event_type == "playback_error":
                    if (type(worker_event.get("generation")) is not int
                            or worker_event["generation"] != self.conversation._generation
                            or type(worker_event.get("epoch")) is not int
                            or worker_event["epoch"] < 0
                            or self._playback_id is None
                            or worker_event.get("playback_id") != self._playback_id
                            or worker_event.get("code") != "pocket_tts_failed"):
                        continue
                    message = "Pocket TTS speech delivery failed."
                    self._last_error = message
                    trace.emit("error", message, [json.dumps({
                        "event": "speech.delivery_failed",
                        "generation": worker_event["generation"],
                        "epoch": worker_event["epoch"],
                        "playback_id": self._playback_id,
                        "run_id": self._playback_run_id,
                        "code": "pocket_tts_failed",
                    }, sort_keys=True)], {"run_id": self._playback_run_id})
                    self._clear_playback()
                    await self._publish("runtime", reason="playback_error", line=message)
                    continue
                if event_type == "input_capture":
                    if self._mode == "wake" and not self._wake_open:
                        continue
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
                    if self._mode == "wake" and not self._wake_open:
                        continue
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
                    await self._prioritize_speech_capture()
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
                elif event_type in {"runtime_ready", "mode_applied"}:
                    if event_type == "runtime_ready":
                        # Cue assets belong to this worker, not its startup
                        # mode revision; a mode change before ready keeps them.
                        self._cue_names = [name for name in worker_event.get("cues", [])
                                           if name in {"ready", "accepted", "complete", "cancel", "error"}]
                    if self._phase != "starting":
                        continue
                    if worker_event.get("mode_revision", 0) != self._mode_revision:
                        continue
                    self._phase = "wake" if self._mode == "wake" else "command"
                    self._paused_for_work = False
                    reply, self._deferred_reply = self._deferred_reply, None
                    if reply and reply.get("generation") == self.conversation._generation:
                        await self._send_worker(reply)
                    self.conversation.prepare_idle()
                    await self._publish("state", reason="runtime_ready")
                elif event_type == "transcript_final":
                    pending_partial = None
                    prepared_sequence = 0
                    async with self._lock:
                        if (operation != self._operation or self._process is not process
                                or self._phase not in READY_PHASES):
                            continue
                        timing = _input_speech_timing(worker_event.get("speech_timing"))
                        if timing is not None:
                            self._speech_sequence = timing["speech_sequence"]
                        self._trace_speech_boundary(event_type)
                        await self.conversation.submit(
                            transcript_text, source="realtime", wait=False,
                            **({"speech_timing": timing} if timing is not None else {}),
                        )
                        # submit(wait=False) schedules final admission. Bridge
                        # that scheduling edge without releasing capture early.
                        self._speech_handoff_task = self.conversation._turn_task
                        if self._speech_handoff_task is not None:
                            self._speech_handoff_task.add_done_callback(self._speech_handoff_done)
                        await self.cue("accepted")
                        if self._mode == "wake":
                            self._wake_open = False
                            self._capture_active = False
                            self._input_level = 0.0
                    await self._publish("runtime", line=display_line)
                elif event_type == "transcript_partial":
                    if exact_sequence:
                        pending_partial = (sequence, transcript_text)
                        if (sequence == prepared_sequence and self._user_speaking
                                and self._phase in READY_PHASES):
                            self.conversation.prepare_speech_prefix(transcript_text, sequence)
                    await self._publish("runtime", line=display_line)
                elif event_type == "interruption":
                    async with self._lock:
                        if (operation != self._operation or self._process is not process
                                or self._phase not in READY_PHASES):
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
            drain = self._stderr_drain
            if stderr is not None and drain is not None and not drain.done():
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(asyncio.shield(drain), timeout=1)
            restart = False
            async with self._lock:
                if operation != self._operation or self._process is not process:
                    return
                if self._phase == "stopping":
                    return
                conversation_id = self.conversation._conversation.conversation_id
                self._phase = "stopping"
                self._wake_open = self._capture_active = self._user_speaking = False
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
                    exited = f"Speech worker exited with {_exit_description(returncode)}"
                    self._last_error = (self._last_error or (
                        exited + (f": {stderr_tail[-1]}" if stderr_tail else "")
                    ))[:MAX_EVENT_TEXT]
                    now = time.monotonic()
                    # One automatic recovery; a second exit within the window
                    # stays in error. Stops and audio loss never reach here.
                    restart = (not self._closed and self._desired_mode in {"wake", "realtime"}
                               and (self._crash_restart_at is None
                                    or now - self._crash_restart_at > CRASH_RESTART_WINDOW_SECS))
                    self._last_exit = {
                        "returncode": returncode,
                        "description": _exit_description(returncode),
                        "monotonic_ns": time.monotonic_ns(),
                        "stderr_tail": list(stderr_tail),
                        "automatic_restart": restart,
                    }
                    trace.emit("error", exited, [json.dumps({
                        "event": "speech.worker_exited", "returncode": returncode,
                        "automatic_restart": restart,
                    }, sort_keys=True)])
                await self._publish("state", reason="process_exited", returncode=returncode)
                if restart:
                    self._restart_task = asyncio.create_task(
                        self._restart_after_exit(operation), name="obsidience-speech-restart",
                    )
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
                    self._wake_open = self._capture_active = self._user_speaking = False
                    self._last_error = f"{type(exc).__name__}: {exc}"[:MAX_EVENT_TEXT]
                    await self._publish("state", reason="monitor_failed")
                    # A failed monitor cannot release a live worker's GPU or
                    # another operation's lease. Stop retains exact ownership.

    @staticmethod
    async def _drain_stderr(stream: asyncio.StreamReader, tail: deque[str]) -> None:
        while True:
            try:
                line = await stream.readline()
            except ValueError:
                tail.append("[stderr line exceeded the pipe buffer]")
                continue
            except Exception:
                return
            if not line:
                return
            text = line.decode("utf-8", errors="replace").rstrip()
            if text:
                tail.append(text[:300])

    async def _restart_after_exit(self, operation: int) -> None:
        try:
            await asyncio.sleep(CRASH_RESTART_DELAY_SECS)
            if (self._closed or self._process is not None or self._operation != operation
                    or self._phase != "error" or self._audio_reconnect_pending
                    or self._desired_mode not in {"wake", "realtime"}):
                return
            self._crash_restart_at = time.monotonic()
            trace.emit("speech", "Speech worker restarting after an unexpected exit")
            await self.start(mode=self._desired_mode)
        except Exception as exc:  # noqa: BLE001 - the failure stays visible, never retried
            self._phase = "error"
            self._last_error = f"Automatic speech restart failed: {type(exc).__name__}: {exc}"[:MAX_EVENT_TEXT]
            await self._publish("state", reason="restart_failed")
        finally:
            if self._restart_task is asyncio.current_task():
                self._restart_task = None

    async def shutdown(self) -> None:
        self._closed = True
        if self._restart_task is not None:
            self._restart_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._restart_task
            self._restart_task = None
        if self._audio_monitor is not None:
            self._audio_monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._audio_monitor
            self._audio_monitor = None
        if self._unsubscribe_activity is not None:
            self._unsubscribe_activity()
            self._unsubscribe_activity = None
        if self._standby_task is not None:
            self._standby_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._standby_task
            self._standby_task = None
        await self.stop(preserve_requested=True)
        monitor = self._monitor
        if monitor is not None and monitor is not asyncio.current_task():
            with contextlib.suppress(asyncio.CancelledError):
                await monitor
        self._monitor = None


RUNTIME = RealtimeSessionManager(requested_state_path=RUNTIME_ROOT / "requested.json")
