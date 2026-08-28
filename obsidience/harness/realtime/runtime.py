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

from ..conversation.store import CONVERSATION
from ..execution import activity as knowledge_activity
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
RUNTIME_LEASE_OWNER = "obsidience-realtime"
REALTIME_TASK_REF = "Tasks/executive/realtime"
COMPACT_TASK_REF = "Tasks/observations/immediate/compact"
REALTIME_AGENT_REF = "Agents/Executive/Executive"
REALTIME_RUNBOOK_REF = "Runbooks/realtime"
REALTIME_CONFIRMATION = "Realtime active."
REALTIME_RESPONSE_CONTRACT = (
    "Answer the owner in one or two short spoken sentences unless detail is requested. "
    "If unclear, ask one brief question. Never narrate Realtime, Task, Tool, transport, "
    "or harness status unless asked."
)
DEFAULT_CONTEXT_THRESHOLD = 80
MIN_CONTEXT_THRESHOLD = 50
MAX_CONTEXT_THRESHOLD = 90
DEFAULT_THINKING_OVERHEAD_TOKENS = 1_500
PROMPT_SAFETY_TOKENS = 256


class RealtimeSessionManager:
    def __init__(self) -> None:
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
        self._user_speaking = False
        self._live_transcript: dict[str, Any] | None = None
        self._aec_active = False
        self._tts_voice = media_runtime.DEFAULT_TTS_VOICE
        self._events: deque[dict[str, Any]] = deque(maxlen=MAX_EVENTS)
        self._recent_log: deque[str] = deque(maxlen=8)
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self._operation = 0
        self._hardware_leased = False
        self._selected_model: model_runtime.ModelSpec | None = None
        self._selected_devices: tuple[str, ...] = ()
        self._task_run_id: str | None = None
        self._task_started: float | None = None
        self._task_objective: str | None = None
        self._task_runbook_ref: str | None = None
        self._task_runbook_sha256: str | None = None
        self._task_status: str = "draft"
        self._task_activity: dict[str, Any] | None = None
        self._realtime_refs: list[str] = [
            REALTIME_AGENT_REF,
            REALTIME_TASK_REF,
            REALTIME_RUNBOOK_REF,
        ]
        self._turn_task: asyncio.Task[dict[str, Any]] | None = None
        self._generation = 0
        self._conversation = CONVERSATION
        self._compact_lock = asyncio.Lock()
        self._session_finalize_lock = asyncio.Lock()
        self._deferred_observation_sessions: list[str] = []
        self._finalized_observation_sessions: set[str] = set()
        self._compacting = False
        self._thinking_overhead_tokens = DEFAULT_THINKING_OVERHEAD_TOKENS

    def scheduler_paused(self) -> bool:
        return self._task_run_id is not None and self._phase not in {"off", "error"}

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
            "model": (
                None
                if self._selected_model is None
                else {
                    "id": self._selected_model.id,
                    "label": self._selected_model.label,
                    "devices": list(self._selected_devices),
                }
            ),
            "task_ref": REALTIME_TASK_REF,
            "task_run_id": self._task_run_id,
            "task_status": self._task_status,
            "scheduler_paused": self.scheduler_paused(),
            "recent_log": list(self._recent_log),
        }

    def _context_model(self, task_ref: str | None = None) -> model_runtime.ModelSpec:
        if task_ref is None and self._selected_model is not None:
            return self._selected_model
        from ..knowledge.vault import resolver

        task = resolver().resolve(task_ref or REALTIME_TASK_REF)
        if task is None:
            return model_runtime.configured_spec(model_runtime.EXECUTIVE_MODEL)
        assignee = str(task.meta.get("assignee", "")).strip("[]")
        return model_runtime.resolve_model(
            task.meta.get("model"), assignee or REALTIME_AGENT_REF,
        )

    def _context_threshold(self) -> int:
        from ..knowledge.vault import resolver

        task = resolver().resolve(COMPACT_TASK_REF)
        try:
            value = int(task.meta.get("context_threshold", DEFAULT_CONTEXT_THRESHOLD))
        except (AttributeError, TypeError, ValueError):
            value = DEFAULT_CONTEXT_THRESHOLD
        return min(MAX_CONTEXT_THRESHOLD, max(MIN_CONTEXT_THRESHOLD, value))

    def context_status(
        self,
        *,
        before_sequence: int | None = None,
        conversation_id: str | None = None,
        context_task_ref: str | None = None,
        pending_text: str = "",
    ) -> dict[str, Any]:
        """Project the Immediate Observations Article and report its model occupancy."""
        from ..conversation.observations import project_immediate_observations

        exact_conversation_id = conversation_id or self._conversation.conversation_id
        projection = project_immediate_observations(
            self._conversation,
            conversation_id=exact_conversation_id,
            before_sequence=before_sequence,
            materialize=(exact_conversation_id == self._conversation.conversation_id),
        )
        spec = self._context_model(context_task_ref)
        capacity = max(
            1,
            spec.context_tokens - spec.max_output_tokens - PROMPT_SAFETY_TOKENS,
        )
        immediate_tokens = (len(str(projection["body"])) + 3) // 4
        pending_tokens = (len(pending_text.strip()) + 3) // 4
        used = self._thinking_overhead_tokens + immediate_tokens + pending_tokens
        return {
            "type": "context",
            "conversation_id": exact_conversation_id,
            "article_ref": projection["ref"],
            "used_tokens": used,
            "capacity_tokens": capacity,
            "percent": round(min(100.0, used * 100.0 / capacity), 1),
            "compact_at": self._context_threshold(),
            "compacting": self._compacting,
            "compacted_through": projection["compacted_through"],
            "latest_sequence": projection["latest_sequence"],
        }

    def publish_context(self) -> dict[str, Any]:
        status = self.context_status()
        self._conversation.publish(status)
        return status

    def record_prompt_usage(self, result: dict[str, Any], *, request_text: str = "") -> None:
        prompt = int(result.get("prompt_tokens_estimate") or 0)
        immediate = int(result.get("conversation_tokens_estimate") or 0)
        request = (len(request_text.strip()) + 3) // 4
        if prompt > immediate + request:
            self._thinking_overhead_tokens = prompt - immediate - request

    async def set_context_threshold(self, percent: object) -> dict[str, Any]:
        try:
            value = int(percent)
        except (TypeError, ValueError) as exc:
            raise ValueError("context threshold must be an integer percent") from exc
        if not MIN_CONTEXT_THRESHOLD <= value <= MAX_CONTEXT_THRESHOLD:
            raise ValueError(
                f"context threshold must be {MIN_CONTEXT_THRESHOLD}-{MAX_CONTEXT_THRESHOLD}"
            )
        from ..knowledge.index import INDEX
        from ..knowledge.vault import mutate_note_metadata, resolver

        task = resolver().resolve(COMPACT_TASK_REF)
        if task is None or task.kind != "task":
            raise RuntimeError("the Compact Immediate Observations Task is missing")
        mutate_note_metadata(task, lambda meta: meta.__setitem__("context_threshold", value))
        await asyncio.to_thread(INDEX.sync)
        return self.publish_context()

    async def compact_conversation(
        self,
        *,
        force: bool,
        before_sequence: int | None = None,
        conversation_id: str | None = None,
        context_task_ref: str | None = None,
        pending_text: str = "",
    ) -> dict[str, Any]:
        """Issue the one graph Task that compacts Immediate into Temporary."""
        exact_conversation_id = conversation_id or self._conversation.conversation_id
        current = asyncio.current_task()
        if force and self._turn_task and self._turn_task is not current and not self._turn_task.done():
            raise RuntimeError("wait for the active Executive turn before compacting")
        async with self._compact_lock:
            status = self.context_status(
                before_sequence=before_sequence,
                conversation_id=exact_conversation_id,
                context_task_ref=context_task_ref,
                pending_text=pending_text,
            )
            if (
                not force
                and int(status["used_tokens"]) * 100
                < int(status["compact_at"]) * int(status["capacity_tokens"])
            ):
                return {"status": "not_needed", "context": status}
            if int(status["latest_sequence"]) <= int(status["compacted_through"]):
                return {"status": "nothing_to_compact", "context": status}

            from ..conversation.observations import (
                EXECUTIVE_TEMPORARY_PATH,
                commit_context_compaction,
                discard_pending_context_compaction,
                project_immediate_observations,
            )
            from ..execution.executor import run_task
            from ..knowledge.index import INDEX
            from ..knowledge.vault import resolver

            task = resolver().resolve(COMPACT_TASK_REF)
            if task is None or task.kind != "task":
                raise RuntimeError("the Compact Immediate Observations Task is missing")
            projection = project_immediate_observations(
                self._conversation,
                conversation_id=exact_conversation_id,
                before_sequence=before_sequence,
                materialize=(exact_conversation_id == self._conversation.conversation_id),
            )
            through_sequence = int(projection["latest_sequence"])
            turn_id = (
                f"compact-{exact_conversation_id.removeprefix('conversation-')[:16]}"
                f"-{through_sequence}"
            )
            self._compacting = True
            if exact_conversation_id == self._conversation.conversation_id:
                self._conversation.publish(status | {"compacting": True})
            try:
                result = await run_task(
                    task,
                    runtime_params={
                        "event": "observations.immediate.manual" if force
                        else "observations.immediate.threshold",
                        "source": "executive:context",
                        "turn_id": turn_id,
                        "target_path": str(EXECUTIVE_TEMPORARY_PATH),
                        "curation_mode": "compaction",
                        "conversation_id": exact_conversation_id,
                        "through_sequence": str(through_sequence),
                    },
                    emit_turn_event=False,
                    keep_task_open=True,
                    conversation_context=str(projection["body"]),
                )
                if result.get("status") != "completed":
                    removed = discard_pending_context_compaction(
                        conversation_id=exact_conversation_id,
                        through_sequence=through_sequence,
                        turn_id=turn_id,
                    )
                    if removed:
                        await asyncio.to_thread(INDEX.sync)
                    return result
                compacted = commit_context_compaction(
                    conversation_id=exact_conversation_id,
                    through_sequence=through_sequence,
                    turn_id=turn_id,
                )
                project_immediate_observations(
                    self._conversation,
                    conversation_id=exact_conversation_id,
                    before_sequence=before_sequence,
                    materialize=(exact_conversation_id == self._conversation.conversation_id),
                )
                await asyncio.to_thread(INDEX.sync)
                return {**result, "temporary_ref": compacted.ref}
            except BaseException:
                removed = discard_pending_context_compaction(
                    conversation_id=exact_conversation_id,
                    through_sequence=through_sequence,
                    turn_id=turn_id,
                )
                if removed:
                    await asyncio.to_thread(INDEX.sync)
                raise
            finally:
                self._compacting = False
                self.publish_context()

    async def prepare_immediate_observations(
        self,
        user_turn: dict[str, Any],
        *,
        context_task_ref: str | None = None,
    ) -> str:
        exact_conversation_id = str(user_turn["conversation_id"])
        await self.compact_conversation(
            force=False,
            before_sequence=int(user_turn["sequence"]),
            conversation_id=exact_conversation_id,
            context_task_ref=context_task_ref,
            pending_text=str(user_turn.get("text") or ""),
        )
        from ..conversation.observations import project_immediate_observations

        return str(project_immediate_observations(
            self._conversation,
            conversation_id=exact_conversation_id,
            before_sequence=int(user_turn["sequence"]),
            materialize=(exact_conversation_id == self._conversation.conversation_id),
        )["body"])

    def _begin_task(self) -> None:
        """Open the one runtime Task and resolve its one selected model."""

        from ..execution.executor import build_activation_binding, resolve_spine
        from ..execution.ledger import runbook_tree_hash
        from ..knowledge.vault import resolver, update_status

        task = resolver().resolve(REALTIME_TASK_REF)
        if task is None or task.kind != "task":
            raise RuntimeError("the Realtime Task Article is missing")
        spine = resolve_spine(task, resolver())
        if "error" in spine or "subtasks" in spine:
            raise RuntimeError(str(spine.get("error") or "Realtime must be one leaf Task"))
        assignee_ref = str(task.meta.get("assignee", "")).strip("[]")
        self._selected_model = model_runtime.resolve_model(
            task.meta.get("model"),
            assignee_ref or REALTIME_AGENT_REF,
        )
        self._task_run_id = f"realtime-{uuid.uuid4().hex[:12]}"
        self._task_started = time.time()
        self._task_objective = build_activation_binding(
            task,
            spine["runbooks"],
            {"event": "realtime.start"},
        ).objective
        self._task_runbook_ref = spine["runbook"].ref
        self._task_runbook_sha256 = runbook_tree_hash(spine["runbooks"])
        self._task_status = "running"
        update_status(task, "running", {"last_run": self._task_run_id})

    def _finish_task(self, status: str, summary: str) -> None:
        """Close the runtime Task exactly once from its owner-controlled lifecycle."""

        if self._task_run_id is None or self._task_started is None:
            return
        from ..knowledge.index import INDEX
        from ..knowledge.vault import resolver, update_status

        task = resolver().resolve(REALTIME_TASK_REF)
        run_id = self._task_run_id
        started = self._task_started
        if task is not None:
            update_status(task, status, {"summary": summary, "last_run": run_id})
        INDEX.record_run(
            id=run_id,
            task_ref=REALTIME_TASK_REF,
            objective=self._task_objective or (task.title if task is not None else "Realtime"),
            agent="JARVIS",
            started=started,
            finished=time.time(),
            status=status,
            summary=summary,
            trace="[]",
            runbook_ref=self._task_runbook_ref or "",
            runbook_sha256=self._task_runbook_sha256 or "",
            reasoning_effort="none",
            model=(
                self._selected_model.id
                if self._selected_model is not None
                else model_runtime.EXECUTIVE_MODEL
            ),
        )
        INDEX.sync()
        self._task_status = status
        self._task_run_id = None
        self._task_started = None
        self._task_objective = None
        self._task_runbook_ref = None
        self._task_runbook_sha256 = None
        self._selected_model = None
        self._selected_devices = ()
        self._complete_task_activity()

    async def _activate_task_activity(self) -> None:
        """Compile and display the long-running Realtime Task like any other Task."""

        from ..execution.executor import build_activation_binding, compile_activation, resolve_spine
        from ..knowledge.vault import resolver

        res = resolver()
        task = res.resolve(REALTIME_TASK_REF)
        if task is None or task.kind != "task":
            raise RuntimeError("the Realtime Task Article is missing")
        spine = resolve_spine(task, res)
        if "error" in spine or "subtasks" in spine:
            raise RuntimeError(str(spine.get("error") or "Realtime must be one leaf Task"))
        self._task_objective = build_activation_binding(
            task,
            spine["runbooks"],
            {"event": "realtime.start"},
        ).objective
        query = self._task_objective
        graph_id = "main"
        knowledge_activity.emit(
            "query_started", [task.ref], query=query, graph_id=graph_id,
        )
        try:
            activation = await compile_activation(
                task,
                spine=spine,
                params={"event": "realtime.start"},
            )
        except BaseException:
            knowledge_activity.emit(
                "query_completed", [task.ref], query=query, graph_id=graph_id,
            )
            raise
        self._task_objective = str(activation["objective"])
        query = self._task_objective
        self._task_activity = {
            "refs": list(activation["refs"]),
            "query": query,
            "graph_id": graph_id,
            "retrieval_ms": float(activation["retrieval_ms"]),
        }
        self._realtime_refs = list(activation["refs"])

    def _complete_task_activity(self) -> None:
        """End startup illumination; idle Realtime is not unresolved graph work."""

        activity = self._task_activity
        if activity is None:
            return
        knowledge_activity.emit(
            "query_completed",
            activity["refs"],
            query=activity["query"],
            graph_id=activity["graph_id"],
            retrieval_ms=activity["retrieval_ms"],
        )
        self._task_activity = None

    async def _publish(self, kind: str, **payload: Any) -> None:
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
        process.stdin.write((json.dumps(payload) + "\n").encode())
        await process.stdin.drain()

    async def _cancel_turn(self, *, stop_playback: bool = True) -> None:
        self._generation += 1
        task, self._turn_task = self._turn_task, None
        if task and task is not asyncio.current_task():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if stop_playback:
            await self._send_worker({"type": "cancel", "generation": self._generation})

    async def _run_voice_turn(
        self,
        text: str,
        generation: int,
        user_turn: dict[str, Any] | None = None,
        *,
        source: Literal["text", "realtime"] = "realtime",
        speak: bool = True,
    ) -> dict[str, Any]:
        from ..execution.executor import run_task
        from ..knowledge.vault import resolver

        task = resolver().resolve(REALTIME_TASK_REF)
        if task is None or task.kind != "task":
            raise RuntimeError("the Realtime Task Article is missing")
        try:
            conversation_context = (
                await self.prepare_immediate_observations(
                    user_turn,
                    context_task_ref=task.ref,
                )
                if user_turn is not None
                else ""
            )
            result = await run_task(
                task,
                runtime_params={
                    "event": "realtime.utterance" if source == "realtime" else "chat.request",
                    "request": text,
                    "source": "voice" if source == "realtime" else "text",
                    "response_contract": REALTIME_RESPONSE_CONTRACT,
                },
                emit_turn_event=False,
                keep_task_open=True,
                realtime_projection=True,
                conversation_context=conversation_context,
            )
            self.record_prompt_usage(result, request_text=text)
            if generation != self._generation or self._phase not in {"command", "proactive"}:
                return {"status": "interrupted"}
            reply = str(result.get("reply", "")).strip()
            if result.get("status") != "completed":
                detail = str(result.get("summary", "")).strip()
                self._last_error = f"Realtime turn failed: {detail or 'no public reply'}"[:MAX_EVENT_TEXT]
                await self._publish("runtime", line=self._last_error)
                return result
            if reply:
                self._last_error = None
                if speak:
                    await self._send_worker({
                        "type": "speak",
                        "generation": generation,
                        "text": reply,
                    })
                if generation != self._generation or self._phase not in {"command", "proactive"}:
                    return {"status": "interrupted"}
                assistant_turn = None
                if user_turn is not None:
                    assistant_turn = await self._conversation.append(
                        role="assistant",
                        source=source,
                        text=reply,
                        run_id=str(result.get("run_id") or "") or None,
                        conversation_id=str(user_turn["conversation_id"]),
                        reply_to=str(user_turn["id"]),
                    )
                    self.publish_context()
                await self._publish(
                    "reply",
                    text=reply,
                    transcript=text,
                    run_id=result.get("run_id"),
                    turn_id=None if assistant_turn is None else assistant_turn["id"],
                )
            return result
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            message = f"Realtime turn failed: {type(exc).__name__}: {exc}"[:MAX_EVENT_TEXT]
            self._last_error = message
            await self._publish("runtime", line=message)
            return {"status": "failed", "summary": message}
        finally:
            if self._turn_task is asyncio.current_task():
                self._turn_task = None

    async def _start_turn(
        self,
        text: str,
        *,
        source: Literal["text", "realtime"],
        speak: bool,
        wait: bool,
    ) -> dict[str, Any]:
        clean = " ".join(text.split())[:4_000]
        if not clean:
            return {"status": "ignored"}
        async with self._lock:
            if self._phase not in {"command", "proactive"}:
                raise RuntimeError("real-time mode is not ready")
            await self._cancel_turn(stop_playback=source == "text")
            user_turn = await self._conversation.append(
                role="user",
                source=source,
                text=clean,
            )
            generation = self._generation
            turn_task = asyncio.create_task(
                self._run_voice_turn(
                    clean,
                    generation,
                    user_turn,
                    source=source,
                    speak=speak,
                ),
                name=f"obsidience-realtime-turn-{generation}",
            )
            self._turn_task = turn_task
        if not wait:
            return user_turn
        try:
            return await turn_task
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if turn_task.cancelled() and current is not None and current.cancelling() == 0:
                return {"status": "interrupted"}
            raise

    async def _accept_transcript(self, text: str) -> None:
        await self._start_turn(
            text,
            source="realtime",
            speak=True,
            wait=False,
        )

    async def submit_text(self, text: str) -> dict[str, Any]:
        """Run typed input through the active Realtime Task without speaking its reply."""

        return await self._start_turn(
            text,
            source="text",
            speak=False,
            wait=True,
        )

    def defer_observation_session(self, conversation_id: str) -> None:
        """Remember one rotated Realtime session without delaying startup."""

        exact = str(conversation_id).strip()
        if (
            exact
            and exact not in self._finalized_observation_sessions
            and exact not in self._deferred_observation_sessions
        ):
            self._deferred_observation_sessions.append(exact)

    async def finalize_observation_session(
        self,
        conversation_id: str,
        *,
        session_boundary: str,
    ) -> dict[str, Any]:
        """Compact one closed session and issue its ordinary promotion event once."""

        exact = str(conversation_id).strip()
        if not exact:
            raise ValueError("observation finalization requires a conversation identity")
        async with self._session_finalize_lock:
            if exact in self._finalized_observation_sessions:
                return {"status": "already_finalized", "conversation_id": exact}
            compacted = await self.compact_conversation(
                force=True,
                conversation_id=exact,
            )
            if compacted.get("status") not in {
                "completed", "nothing_to_compact", "not_needed",
            }:
                raise RuntimeError(
                    "final Immediate Observations compaction did not complete: "
                    f"{compacted.get('status', 'unknown')}"
                )
            from ..conversation.observations import queue_temporary_promotion

            promotion = queue_temporary_promotion(
                exact,
                session_boundary=session_boundary,
            )
            if promotion.get("state") == "not_configured":
                raise RuntimeError("the Alexandria promotion Task is not configured")
            self._finalized_observation_sessions.add(exact)
            return {
                "status": "finalized",
                "conversation_id": exact,
                "compaction": compacted,
                "promotion": promotion,
            }

    async def _finalize_realtime_observations(
        self,
        conversation_id: str,
        *,
        session_boundary: str,
    ) -> list[dict[str, Any]]:
        session_ids = list(self._deferred_observation_sessions)
        if conversation_id and conversation_id not in session_ids:
            session_ids.append(conversation_id)
        results = []
        for session_id in session_ids:
            try:
                result = await self.finalize_observation_session(
                    session_id,
                    session_boundary=session_boundary,
                )
            except Exception as exc:  # noqa: BLE001 - retain the exact session for retry
                self.defer_observation_session(session_id)
                self._last_error = (
                    f"Observation promotion deferred: {type(exc).__name__}: {exc}"
                )[:MAX_EVENT_TEXT]
                results.append({
                    "status": "deferred",
                    "conversation_id": session_id,
                    "error": self._last_error,
                })
            else:
                self._deferred_observation_sessions = [
                    item for item in self._deferred_observation_sessions
                    if item != session_id
                ]
                results.append(result)
        return results

    async def start(self) -> dict[str, Any]:
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
            self._user_speaking = False
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
                self._begin_task()
                await self._activate_task_activity()
                assert self._selected_model is not None
                await model_runtime.reserve_devices(
                    RUNTIME_LEASE_OWNER, (model_runtime.RTX_4080_DEVICE,),
                )
                hardware = model_runtime.RUNTIME.settings()["hardware"]
                self._selected_devices = tuple(
                    device
                    for device in model_runtime.GPU_DEVICES
                    if hardware.get(device) == self._selected_model.id
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
                outgoing_conversation = self._conversation.conversation_id
                await self._conversation.new_conversation()
                self.defer_observation_session(outgoing_conversation)
                self.publish_context()
            except BaseException as exc:
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
                self._finish_task("failed", f"Realtime failed to start: {exc}")
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

    async def stop(self) -> dict[str, Any]:
        conversation_id = self._conversation.conversation_id
        finalize_observations = False
        async with self._lock:
            process = self._process
            if process is None or process.returncode is not None:
                finalize_observations = bool(
                    self._task_run_id or self._deferred_observation_sessions
                )
                await asyncio.to_thread(media_runtime.stop_realtime_aec)
                self._aec_active = False
                await asyncio.to_thread(
                    media_runtime.set_realtime_camera_active, self._audio_source, False,
                )
                self._phase = "off"
                self._transport_ready = False
                self._input_level = 0.0
                self._user_speaking = False
                self._live_transcript = None
                self._requested_proactive = False
                self._process = None
                release_hardware = self._hardware_leased
                self._hardware_leased = False
                if release_hardware:
                    await model_runtime.release_devices(RUNTIME_LEASE_OWNER)
                self._finish_task("completed", "Realtime was disabled by the owner.")
                result = self.snapshot()
            else:
                result = None
            if result is None:
                self._phase = "stopping"
                self._requested_proactive = False
                await self._cancel_turn()
                await self._send_worker({"type": "stop"})
                await self._publish("state", reason="stop_requested")
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGINT)
        if result is not None:
            if finalize_observations:
                await self._finalize_realtime_observations(
                    conversation_id,
                    session_boundary="realtime.stopped",
                )
            return self.snapshot()
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
            if self._process is process:
                self._process = None
                self._phase = "off"
                self._transport_ready = False
                self._input_level = 0.0
                self._user_speaking = False
                self._live_transcript = None
                self._started_ns = None
                self._vision_source = None
                await self._publish("state", reason="stopped")
            release_hardware = self._hardware_leased
            self._hardware_leased = False
            if self._aec_active:
                await asyncio.to_thread(media_runtime.stop_realtime_aec)
                self._aec_active = False
        if release_hardware:
            await model_runtime.release_devices(RUNTIME_LEASE_OWNER)
        await asyncio.to_thread(
            media_runtime.set_realtime_camera_active, self._audio_source, False,
        )
        self._finish_task("completed", "Realtime was disabled by the owner.")
        await self._finalize_realtime_observations(
            conversation_id,
            session_boundary="realtime.stopped",
        )
        return self.snapshot()

    async def _monitor_process(
        self,
        process: asyncio.subprocess.Process,
        operation: int,
    ) -> None:
        assert process.stdout is not None
        try:
            while True:
                raw = await process.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").strip()[:MAX_EVENT_TEXT]
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
                if event_type == "input_level":
                    level = worker_event.get("level")
                    if isinstance(level, (int, float)) and not isinstance(level, bool):
                        numeric_level = float(level)
                        if math.isfinite(numeric_level):
                            self._input_level = max(0.0, min(1.0, numeric_level))
                            await self._publish("runtime", reason="input_level")
                    continue
                if event_type == "speech_detected":
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
                    self._phase = "command"
                    self._complete_task_activity()
                    await self._publish("state", reason="runtime_ready")
                elif event_type == "transcript_final":
                    await self._accept_transcript(transcript_text)
                    await self._publish("runtime", line=display_line)
                elif event_type == "interruption":
                    async with self._lock:
                        await self._cancel_turn(stop_playback=False)
                    await self._publish("runtime", line=display_line)
                elif event_type == "fatal":
                    self._last_error = display_line[:MAX_EVENT_TEXT]
                    await self._publish("runtime", line=display_line)
                elif event_type in {
                    "transport_ready", "transcript_partial", "speech_detected", "speech_ended",
                    "speech_started", "speech_stopped", "playback_started",
                    "playback_stopped",
                }:
                    await self._publish("runtime", line=display_line)
            returncode = await process.wait()
            conversation_id = self._conversation.conversation_id
            async with self._lock:
                if operation != self._operation or self._process is not process:
                    return
                stopping = self._phase == "stopping"
                if not stopping:
                    await self._cancel_turn()
                self._process = None
                self._started_ns = None
                self._requested_proactive = False
                self._transport_ready = False
                self._input_level = 0.0
                self._user_speaking = False
                self._live_transcript = None
                self._vision_source = None
                if stopping or returncode in {0, -signal.SIGINT}:
                    self._phase = "off"
                else:
                    self._phase = "error"
                    self._transport_ready = False
                    self._last_error = self._last_error or f"live runtime exited {returncode}"
                self._finish_task(
                    "completed" if stopping or returncode in {0, -signal.SIGINT} else "failed",
                    "Realtime was disabled by the owner."
                    if stopping or returncode in {0, -signal.SIGINT}
                    else f"Realtime runtime exited {returncode}.",
                )
                await self._publish("state", reason="process_exited", returncode=returncode)
                if self._aec_active:
                    await asyncio.to_thread(media_runtime.stop_realtime_aec)
                    self._aec_active = False
            if self._hardware_leased:
                self._hardware_leased = False
                await model_runtime.release_devices(RUNTIME_LEASE_OWNER)
            if not stopping:
                with contextlib.suppress(Exception):
                    await asyncio.to_thread(
                        media_runtime.set_realtime_camera_active, self._audio_source, False,
                    )
                await self._finalize_realtime_observations(
                    conversation_id,
                    session_boundary="realtime.runtime_exited",
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            async with self._lock:
                if operation == self._operation and self._process is process:
                    self._phase = "error"
                    self._last_error = f"{type(exc).__name__}: {exc}"[:MAX_EVENT_TEXT]
                    await self._publish("state", reason="monitor_failed")
            if self._hardware_leased:
                self._hardware_leased = False
                with contextlib.suppress(Exception):
                    await model_runtime.release_devices(RUNTIME_LEASE_OWNER)

    async def shutdown(self) -> None:
        await self.stop()
        monitor = self._monitor
        if monitor is not None and monitor is not asyncio.current_task():
            with contextlib.suppress(asyncio.CancelledError):
                await monitor
        self._monitor = None


RUNTIME = RealtimeSessionManager()
