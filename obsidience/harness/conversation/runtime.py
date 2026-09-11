"""One Executive conversation lane shared by text and speech input."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from typing import Any, Literal

from .store import CONVERSATION
from .selection import select_task
from .evidence import historical_evidence
from ..execution import trace
from ..knowledge.index import INDEX
from ..knowledge.vault import Note, resolver
from ..models import runtime as model_runtime
from ..models.context import PROMPT_SAFETY_TOKENS, cached_text_count, measure_text

QUERY_TASK_REF = "Tasks/query"
EXECUTIVE_AGENT_REF = "Agents/Executive/Executive"
COMPACT_TASK_REF = "Tasks/observations/immediate/compact"
SPEECH_RESPONSE_CONTRACT = (
    "Answer the owner in one or two short spoken sentences unless detail is requested. "
    "If unclear, ask one brief question. Never narrate Task, Tool, transport, "
    "or harness status unless asked. Put the public answer in task.complete summary."
)
MAX_EVENT_TEXT = 512
DEFAULT_CONTEXT_THRESHOLD = 80
MIN_CONTEXT_THRESHOLD = 60
MAX_CONTEXT_THRESHOLD = 90
RECENT_EXACT_PAIR_COUNT = 2
DEFAULT_THINKING_OVERHEAD_TOKENS = 1_500


class TurnSteering:
    """Bounded, single-loop clarifications for one exact admitted activation."""

    def __init__(self, turn_id: str, changed) -> None:
        self.turn_id = turn_id
        self.run_id = ""
        self.accepting = False
        self.pending: list[dict] = []
        self.applied: list[str] = []
        self.changed = changed

    def activate(self, run_id: str) -> None:
        self.run_id, self.accepting = run_id, True
        self.changed()

    def close(self) -> None:
        self.accepting = False
        self.changed()

    def take(self) -> list[dict]:
        pending, self.pending = self.pending, []
        self.applied.extend(turn["id"] for turn in pending)
        return pending



class ConversationRuntime:
    def __init__(self, conversation=CONVERSATION) -> None:
        self._conversation = conversation
        self._lock = asyncio.Lock()
        self._turn_task: asyncio.Task | None = None
        self._generation = 0
        self._last_task_ref = QUERY_TASK_REF
        self._compact_lock = asyncio.Lock()
        self._session_finalize_lock = asyncio.Lock()
        self._compacting = False
        self._thinking_overhead_tokens = DEFAULT_THINKING_OVERHEAD_TOKENS
        self.speech = None
        self._steering: TurnSteering | None = None

    def active_turn(self) -> dict:
        inbox = self._steering
        return {"type": "active_turn", "conversation_id": self._conversation.conversation_id,
                "turn_id": inbox.turn_id if inbox else "",
                "accepting_clarification": bool(inbox and inbox.accepting)}

    def _publish_active_turn(self) -> None:
        self._conversation.publish(self.active_turn())

    async def steer(self, text: str, *, expected_turn_id: str) -> dict:
        """Explicit clarification; never replace the Objective or Tool authority."""
        clean = text.strip()
        if not clean or len(clean) > 2000:
            raise ValueError("A clarification must contain 1–2000 characters")
        async with self._lock:
            inbox = self._steering
            if (inbox is None or inbox.turn_id != expected_turn_id or not inbox.accepting
                    or self._turn_task is None or self._turn_task.done()):
                raise ValueError("That Task is no longer accepting clarifications; send a new request")
            if len(inbox.applied) + len(inbox.pending) >= 8:
                raise ValueError("This Task has reached its clarification limit")
            turn = await self._conversation.append(
                role="user", source="text", text=clean, run_id=inbox.run_id,
            )
            if not inbox.accepting or self._steering is not inbox or self._turn_task.done():
                raise ValueError("The Task ended while receiving this clarification; the message was saved but not applied")
            inbox.pending.append(turn)
            trace.emit("context", "Owner clarification queued for the current Task",
                       [clean], {"run_id": inbox.run_id})
            return {"status": "queued", "turn_id": turn["id"], "active_turn_id": inbox.turn_id}

    def _ledger(self):
        return getattr(self._conversation, "index", INDEX)

    async def _publish_speech(self, kind: str, **payload: Any) -> None:
        if self.speech is not None:
            await self.speech._publish(kind, **payload)

    async def _speak_public(self, text: str, generation: int, *,
                            turn_id: str = "", run_id: str = "",
                            speech_sequence: int | None = None) -> None:
        """Speech delivery cannot change an already settled Task outcome."""
        if (self.speech is None or generation != self._generation
                or not self.speech.snapshot()["ready"]):
            return
        try:
            await self.speech._send_worker({
                "type": "speak", "generation": generation, "text": text,
                **({"turn_id": turn_id, "run_id": run_id} if turn_id and run_id else {}),
                **({"speech_sequence": speech_sequence} if type(speech_sequence) is int else {}),
            })
        except Exception as exc:
            message = f"Speech playback failed: {type(exc).__name__}"
            self.speech._last_error = message
            trace.emit("error", message, [str(exc)[:MAX_EVENT_TEXT]])
            await self._publish_speech("runtime", line=message)
        else:
            self.speech._last_error = None

    async def cancel(self, *, stop_playback: bool = True, reason: str = "requested") -> None:
        self._generation += 1
        if self._steering is not None:
            self._steering.close()
            self._steering = None
            self._publish_active_turn()
        task, self._turn_task = self._turn_task, None
        cancel_task = task is not None and not task.done() and task is not asyncio.current_task()
        if cancel_task:
            trace.emit("interruption", "Executive turn cancellation requested", [
                f"reason: {reason[:80]}",
                f"conversation: {self._conversation.conversation_id}",
                f"generation: {self._generation - 1}",
                f"turn: {task.get_name()}",
                f"task: {self._last_task_ref}",
            ])
            task.cancel()
        if self.speech is not None:
            try:
                await self.speech._send_worker({
                    "type": "cancel", "generation": self._generation,
                    "stop_playback": stop_playback,
                })
            except Exception as exc:
                message = f"Speech cancellation delivery failed: {type(exc).__name__}"
                self.speech._last_error = message
                trace.emit("error", message, [str(exc)[:MAX_EVENT_TEXT]])
        if cancel_task:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    def continuation_resume_available(self) -> bool:
        return self._turn_task is None or self._turn_task.done()

    async def new_conversation(self, *, defer: bool = False) -> dict:
        async with self._lock:
            await self.cancel(reason="conversation.new")
            outgoing = self._conversation.conversation_id
            if defer:
                self.defer_observation_session(outgoing, "realtime.started")
            else:
                await self.finalize_observation_session(
                    outgoing, session_boundary="chat.new_conversation",
                )
            result = await self._conversation.new_conversation()
            self.publish_context()
            return result

    async def submit(
        self, text: str, *, source: Literal["text", "realtime"] = "text", wait: bool = True,
        speech_timing: dict | None = None,
    ) -> dict[str, Any]:
        """Bind one exact user turn, independent of microphone state."""
        received_ns = time.monotonic_ns()
        clean = text.strip() if source == "text" else " ".join(text.split())
        if not clean:
            return {"status": "ignored"}
        if source == "realtime" and (
            self.speech is None or not self.speech.snapshot()["ready"]
        ):
            raise RuntimeError("speech transport is not ready")
        async with self._lock:
            await self.cancel(stop_playback=source == "text", reason=f"{source}.final")
            user_turn = await self._conversation.append(role="user", source=source, text=clean)
            self._steering = TurnSteering(user_turn["id"], self._publish_active_turn)
            turn_task = asyncio.create_task(
                self._run_turn(clean, self._generation, user_turn, source=source,
                               received_ns=received_ns, speech_timing=speech_timing),
                name=f"obsidience-conversation-turn-{user_turn['id']}",
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

    async def _run_turn(
        self, text: str, generation: int, user_turn: dict, *,
        source: Literal["text", "realtime"],
        received_ns: int | None = None, speech_timing: dict | None = None,
    ) -> dict[str, Any]:
        from ..execution.scheduler import foreground_admission

        # Transport metadata never becomes conversation text or Task authority.
        timing = trace.input_speech_timing(speech_timing) if source == "realtime" else None
        sequence = timing["speech_sequence"] if timing else None
        scope = trace.bind_turn(str(user_turn["id"]), speech_sequence=sequence, generation=generation)
        try:
            trace.latency("input_final", monotonic_ns=received_ns)
            for edge in timing["stages"] if timing else ():
                trace.latency(edge["stage"], monotonic_ns=edge["monotonic_ns"])
            async with foreground_admission("conversation"):
                return await self._run_admitted_turn(text, generation, user_turn, source=source,
                                                     speech_sequence=sequence)
        finally:
            trace.reset(scope)

    async def _run_admitted_turn(
        self, text: str, generation: int, user_turn: dict, *,
        source: Literal["text", "realtime"],
        speech_sequence: int | None = None,
    ) -> dict[str, Any]:
        from ..execution.executor import run_task

        self._conversation.publish({"type": "start", "source": source})
        inbox = self._steering
        self._publish_active_turn()
        try:
            # Intent admission must see the same conversation as execution.
            # Selection creates no Task or Tool authority of its own.
            preparation_started = time.monotonic()
            context_model = self._context_model()
            context = await self.prepare_immediate_observations(user_turn)
            prior_effects = historical_evidence(
                self._conversation, conversation_id=str(user_turn["conversation_id"]),
                before_sequence=int(user_turn["sequence"]),
            )
            trace.latency("preparation", duration_ms=(time.monotonic() - preparation_started) * 1000)
            selection_started = time.monotonic()
            task, params, event = await select_task(
                text, "voice" if source == "realtime" else "text",
                conversation_context=context, historical_evidence=prior_effects,
            )
            trace.latency("selection", duration_ms=(time.monotonic() - selection_started) * 1000)
            if task is None or task.kind != "task":
                raise RuntimeError("the selected Executive Task Article is missing")
            self._last_task_ref = task.ref
            trace.emit("event", f"{task.title} activated", [task.ref, event])
            if self._context_model(task.ref) != context_model:
                context = await self.prepare_immediate_observations(user_turn, context_task_ref=task.ref)
            params.update({
                "conversation_id": str(user_turn["conversation_id"]),
                "reply_to_turn_id": str(user_turn["id"]),
            })
            if source == "realtime":
                params["response_contract"] = SPEECH_RESPONSE_CONTRACT
            result = await run_task(
                task, runtime_params=params, emit_turn_event=False,
                interactive=True, conversation_context=context,
                conversation_evidence=prior_effects,
                steering=inbox,
            )
            if result.get("routing_reclassification") is True and generation == self._generation:
                # Re-run the SAME bounded admission once. No Task or Tool is
                # added by the failed Query, and the Objective stays unchanged.
                corrected, correction, correction_event = await select_task(
                    text, "voice" if source == "realtime" else "text",
                    conversation_context=context, historical_evidence=prior_effects)
                if corrected is not None and corrected.ref == "Tasks/executive/operate":
                    correction.update(conversation_id=str(user_turn["conversation_id"]),
                        reply_to_turn_id=str(user_turn["id"]), routing_rechecked=True)
                    if source == "realtime":
                        correction["response_contract"] = SPEECH_RESPONSE_CONTRACT
                    trace.emit("event", "Admission corrected before effects", [task.ref, corrected.ref, correction_event])
                    task = corrected
                    result = await run_task(task, runtime_params=correction, emit_turn_event=False,
                        interactive=True, conversation_context=context, conversation_evidence=prior_effects, steering=inbox)
            self.record_prompt_usage(result, request_text=text)
            if generation != self._generation:
                return {"status": "interrupted"}
            if result.get("status") == "waiting":
                trace.emit("event", "Waiting for research", [task.ref])
                await self._publish_speech("waiting", transcript=text, run_id=result.get("run_id"))
                return result
            if result.get("status") != "completed":
                await self._report_task_outcome(result, source=source, generation=generation)
                return result
            reply = str(result.get("summary") or "").strip()
            if not reply:
                raise RuntimeError("the Executive Task produced no public reply")
            assistant_turn = await self._conversation.append(
                role="assistant", source=source, text=reply,
                run_id=str(result.get("run_id") or "") or None,
                conversation_id=str(user_turn["conversation_id"]),
                reply_to=str(user_turn["id"]),
            )
            trace.latency("answer_committed", run_id=str(result.get("run_id") or ""))
            self.publish_context()
            if source == "realtime":
                await self._speak_public(reply, generation, turn_id=str(user_turn["id"]),
                                         run_id=str(result.get("run_id") or ""),
                                         speech_sequence=speech_sequence)
            await self._publish_speech(
                "reply", text=reply, transcript=text, run_id=result.get("run_id"),
                turn_id=assistant_turn["id"],
            )
            return result
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            message = f"Executive turn failed: {type(exc).__name__}: {exc}"[:MAX_EVENT_TEXT]
            trace.emit("error", message)
            await self._report_task_outcome(
                {"status": "failed"}, source=source, generation=generation,
            )
            return {"status": "failed", "summary": message}
        finally:
            if inbox is not None:
                inbox.close()
            if self._steering is inbox:
                self._steering = None
                self._publish_active_turn()
            self._conversation.publish({"type": "end"})
            if self._turn_task is asyncio.current_task():
                self._turn_task = None

    async def _report_task_outcome(self, result: dict, *, source: str, generation: int) -> None:
        """Deliver a terminal notice without inventing a successful dialogue pair.

        Only an accepted task.complete can supply public_summary. Internal
        executor errors stay in the trace and get a fixed, credential-free notice.
        """
        if generation != self._generation:
            return
        status = str(result.get("status") or "failed")
        notice = str(result.get("public_summary") or "").strip()[:2000]
        if result.get("resource_blocked") is True:
            # A live turn cannot be replayed later with a different Objective or
            # saved model. Explain admission without leaking internal details or
            # promising the continuation reserved for durable Task occurrences.
            notice = (
                "The selected model's hardware is currently reserved. "
                "Please retry this request when it is available."
            )
        if not notice:
            notice = (
                "That request needs review before it can complete."
                if status == "review" else
                "I couldn't complete that request. The Action Trace has the error details."
            )
        self._conversation.publish({"type": "error", "text": notice,
                                    "status": status, "run_id": result.get("run_id")})
        await self._publish_speech("task_result", status=status, text=notice,
                                   run_id=result.get("run_id"))
        if source == "realtime":
            await self._speak_public(notice, generation)

    def _context_model(self, task_ref: str | None = None) -> model_runtime.ModelSpec:
        from ..knowledge.links import article_ref
        from ..knowledge.vault import load_note, resolver

        reference = task_ref or self._last_task_ref
        # The selected Task already supplies its canonical identity. Preserve
        # ordinary resolver fallback for aliases, case variants, and misses.
        task = (
            load_note(reference + ".md")
            if reference.startswith("Tasks/")
            and article_ref("/" + reference + ".md") == reference
            else None
        )
        if task is None:
            task = resolver().resolve(reference)
        if task is None:
            return model_runtime.configured_spec(model_runtime.EXECUTIVE_MODEL)
        assignee = str(task.meta.get("assignee", "")).strip("[]")
        return model_runtime.resolve_model(
            task.meta.get("model"), assignee or EXECUTIVE_AGENT_REF,
        )

    def _context_threshold(self) -> int:
        from ..knowledge.vault import load_note

        task = load_note(COMPACT_TASK_REF + ".md")
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
        immediate = cached_text_count(str(projection["body"]), spec)
        pending = cached_text_count(pending_text, spec)
        used = self._thinking_overhead_tokens + immediate.tokens + pending.tokens
        return {
            "type": "context",
            "conversation_id": exact_conversation_id,
            "article_ref": projection["ref"],
            "used_tokens": used,
            "count_method": "runtime" if immediate.method == pending.method == "runtime" else "utf8_upper_bound",
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
        model_id = str(result.get("model") or "")
        try:
            spec = model_runtime.configured_spec(model_id) if model_id else self._context_model()
        except KeyError:
            spec = self._context_model()
        request = cached_text_count(request_text, spec).tokens
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
        closed_session: bool = False,
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
            if (not force and status["count_method"] != "runtime"
                    and int(status["used_tokens"]) * 100
                    >= int(status["compact_at"]) * int(status["capacity_tokens"])):
                from .observations import project_immediate_observations

                projection = project_immediate_observations(
                    self._conversation, conversation_id=exact_conversation_id,
                    before_sequence=before_sequence, materialize=False,
                )
                spec = self._context_model(context_task_ref)
                immediate, pending = await asyncio.gather(
                    measure_text(str(projection["body"]), spec), measure_text(pending_text, spec),
                )
                used = self._thinking_overhead_tokens + immediate.tokens + pending.tokens
                status.update(used_tokens=used, percent=round(min(100.0, used * 100.0 / status["capacity_tokens"]), 1))
                if immediate.method != "runtime" or pending.method != "runtime":
                    # A byte upper bound alone cannot justify another model
                    # inference. The exact whole-request guard still applies.
                    return {"status": "measurement_unavailable", "context": status}
                status["count_method"] = "runtime"
            if (
                not force
                and int(status["used_tokens"]) * 100
                < int(status["compact_at"]) * int(status["capacity_tokens"])
            ):
                return {"status": "not_needed", "context": status}
            if int(status["latest_sequence"]) <= int(status["compacted_through"]):
                return {"status": "nothing_to_compact", "context": status}
            pairs = self._conversation.complete_pairs(
                conversation_id=exact_conversation_id,
                before_sequence=before_sequence,
                after_sequence=int(status["compacted_through"]),
            )
            keep_recent = 0 if closed_session else RECENT_EXACT_PAIR_COUNT
            if len(pairs) <= keep_recent:
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
            through_sequence = int(pairs[-keep_recent - 1][1]["sequence"])
            projection = project_immediate_observations(
                self._conversation,
                conversation_id=exact_conversation_id,
                before_sequence=through_sequence + 1,
                materialize=(exact_conversation_id == self._conversation.conversation_id),
            )
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
                        "event": (
                            "observations.immediate.boundary"
                            if closed_session
                            else "observations.immediate.manual" if force
                            else "observations.immediate.threshold"
                        ),
                        "source": "executive:context",
                        "turn_id": turn_id,
                        "target_path": str(EXECUTIVE_TEMPORARY_PATH),
                        "curation_mode": "compaction",
                        "conversation_id": exact_conversation_id,
                        "through_sequence": str(through_sequence),
                        "active_conversation_id": self._conversation.conversation_id,
                    },
                    emit_turn_event=False,
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

    async def resume_continuation(self, continuation: dict) -> dict[str, Any]:
        """Resume one claimed caller from its exact persisted user turn and result."""
        from ..execution.scheduler import foreground_admission

        async with foreground_admission("conversation.continuation"):
            return await self._resume_admitted_continuation(continuation)

    async def _resume_admitted_continuation(self, continuation: dict) -> dict[str, Any]:
        from ..capabilities.task.complete import validate_computer_outcome
        from ..execution.executor import run_task
        from ..knowledge.vault import resolver

        if continuation.get("status") != "claimed":
            raise ValueError("continuation must be claimed before resumption")
        turn_id = str(continuation.get("reply_to_turn_id", ""))
        ledger = self._ledger()
        user_turn = ledger.conversation_turn(turn_id) if turn_id else None
        if (
            user_turn is None or user_turn.get("role") != "user"
            or user_turn.get("state") != "final"
            or user_turn.get("conversation_id") != continuation.get("conversation_id")
        ):
            raise RuntimeError("continuation lost its exact persisted user turn")
        caller_run_id = str(continuation.get("caller_run_id", ""))
        stored_continuation = ledger.continuation_for_caller(caller_run_id)
        if stored_continuation is None or any(
            stored_continuation.get(key) != continuation.get(key)
            for key in (
                "id", "caller_task_ref", "caller_run_id", "objective", "conversation_id",
                "reply_to_turn_id", "reply_source", "result",
            )
        ):
            raise RuntimeError("continuation does not match its recorded caller binding")
        existing_reply = ledger.assistant_reply_for(turn_id)
        if existing_reply is not None:
            return {
                "status": "completed",
                "run_id": str(existing_reply.get("run_id", "")),
                "summary": str(existing_reply.get("text", "")),
            }
        if stored_continuation.get("status") != "claimed":
            raise RuntimeError("continuation is no longer claimed")
        task_ref = str(continuation.get("caller_task_ref", ""))
        task = resolver().resolve(task_ref)
        if task is None or task.kind != "task":
            raise RuntimeError("continuation caller Task is no longer accepted")
        try:
            bound_result = json.loads(str(continuation.get("result") or "{}"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("continuation result is not valid JSON evidence") from exc
        if not isinstance(bound_result, dict):
            raise RuntimeError("continuation result must be an evidence object")
        objective = str(continuation.get("objective", "")).strip()
        if not objective or objective != user_turn.get("text"):
            raise RuntimeError("continuation lost its original objective")
        computer_request = {}
        if task.ref == "Tasks/executive/operate":
            caller = ledger.run(caller_run_id)
            if (
                caller is None or caller.get("task_ref") != task.ref
                or caller.get("objective") != objective
            ):
                raise RuntimeError("computer continuation lost its original caller execution")
            try:
                caller_trace = json.loads(caller.get("trace") or "[]")
            except (TypeError, ValueError) as exc:
                raise RuntimeError("computer continuation caller evidence is invalid") from exc
            if not isinstance(caller_trace, list):
                raise RuntimeError("computer continuation caller evidence is invalid")
            bindings = [
                entry for entry in caller_trace
                if isinstance(entry, dict) and "computer_request" in entry
            ]
            if len(bindings) != 1 or bindings[0].get("interactive_turn") != {
                "conversation_id": user_turn["conversation_id"], "reply_to_turn_id": turn_id,
            }:
                raise RuntimeError("computer continuation has no exact original outcome binding")
            recorded_request = bindings[0]["computer_request"]
            if not isinstance(recorded_request, dict):
                raise RuntimeError("computer continuation outcome binding is invalid")
            outcome = recorded_request.get("computer_outcome")
            scope = recorded_request.get("computer_scope")
            if outcome in (None, "", "answer") or validate_computer_outcome(outcome, scope):
                raise RuntimeError("computer continuation outcome binding is invalid")
            application = recorded_request.get("application")
            if application is not None and (
                not isinstance(application, str) or not application or len(application) > 256
                or any(ord(char) < 32 or ord(char) == 127 for char in application)
            ):
                raise RuntimeError("computer continuation application binding is invalid")
            if outcome in {"launch", "action"} and application is None:
                raise RuntimeError("computer continuation lost its original application")
            operation = recorded_request.get("operation")
            if operation is not None and operation != ("launch" if outcome == "launch" else "computer_use"):
                raise RuntimeError("computer continuation operation binding is invalid")
            computer_request = {
                key: recorded_request[key]
                for key in ("computer_outcome", "computer_scope", "application", "operation")
                if key in recorded_request
            }

        current = asyncio.current_task()
        async with self._lock:
            if self._turn_task is not None and not self._turn_task.done():
                raise RuntimeError("the Executive turn lane is busy")
            self._turn_task = current
            self._last_task_ref = task.ref
            generation = self._generation
        reply_source = str(continuation.get("reply_source") or user_turn.get("source") or "text")
        if reply_source not in {"text", "realtime"}:
            reply_source = "text"
        try:
            conversation_context = await self.prepare_immediate_observations(
                user_turn,
                context_task_ref=task.ref,
            )
            prior_effects = historical_evidence(
                self._conversation, conversation_id=str(user_turn["conversation_id"]),
                before_sequence=int(user_turn["sequence"]),
            )
            result = await run_task(
                task,
                runtime_params={
                    "event": "task.continue",
                    "request": objective,
                    "source": reply_source,
                    "conversation_id": str(user_turn["conversation_id"]),
                    "reply_to_turn_id": turn_id,
                    "continuation_id": str(continuation["id"]),
                    "continuation_result": bound_result,
                    **computer_request,
                    **(
                        {"response_contract": SPEECH_RESPONSE_CONTRACT}
                        if reply_source == "realtime"
                        else {}
                    ),
                },
                emit_turn_event=False,
                interactive=True,
                conversation_context=conversation_context,
                conversation_evidence=prior_effects,
            )
            if generation != self._generation:
                return {"status": "interrupted"}
            if result.get("status") != "completed":
                if str(user_turn["conversation_id"]) == self._conversation.conversation_id:
                    await self._report_task_outcome(result, source=reply_source, generation=generation)
                return result
            reply = str(result.get("summary") or "").strip()
            if not reply:
                raise RuntimeError("continued Task produced no public reply")
            if generation != self._generation:
                return {"status": "interrupted"}
            self.record_prompt_usage(result, request_text=objective)
            assistant_turn = await self._conversation.append(
                role="assistant",
                source=reply_source,
                text=reply,
                run_id=str(result.get("run_id") or "") or None,
                conversation_id=str(user_turn["conversation_id"]),
                reply_to=turn_id,
            )
            active_conversation = (
                str(user_turn["conversation_id"]) == self._conversation.conversation_id
            )
            if active_conversation:
                self.publish_context()
            if reply_source == "realtime" and active_conversation:
                await self._speak_public(reply, generation)
            await self._publish_speech(
                "reply",
                text=reply,
                transcript=objective,
                run_id=result.get("run_id"),
                turn_id=assistant_turn["id"],
                continuation_id=continuation["id"],
            )
            return result
        finally:
            if self._turn_task is current:
                self._turn_task = None

    def defer_observation_session(
        self,
        conversation_id: str,
        session_boundary: str = "realtime.deferred",
    ) -> None:
        """Persist one rotated conversation for restart-safe finalization."""

        exact = str(conversation_id).strip()
        if exact:
            self._ledger().defer_observation_finalization(exact, session_boundary)

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
            from ..conversation.observations import (
                project_immediate_observations,
                promoted_context_sequence,
                queue_temporary_promotion,
            )

            projection = project_immediate_observations(
                self._conversation,
                conversation_id=exact,
                materialize=(exact == self._conversation.conversation_id),
            )
            latest_sequence = int(projection["latest_sequence"])
            promoted_through = promoted_context_sequence(
                exact,
                active=(exact == self._conversation.conversation_id),
            )
            if latest_sequence <= promoted_through:
                self._ledger().complete_observation_finalization(exact)
                return {
                    "status": "already_finalized",
                    "conversation_id": exact,
                    "through_sequence": promoted_through,
                }
            compacted = await self.compact_conversation(
                force=True,
                conversation_id=exact,
                closed_session=True,
            )
            if compacted.get("status") not in {
                "completed", "nothing_to_compact", "not_needed",
            }:
                raise RuntimeError(
                    "final Immediate Observations compaction did not complete: "
                    f"{compacted.get('status', 'unknown')}"
                )
            promotion = queue_temporary_promotion(
                exact,
                session_boundary=session_boundary,
            )
            if promotion.get("state") == "not_configured":
                raise RuntimeError("the Alexandria promotion Task is not configured")
            self._ledger().complete_observation_finalization(exact)
            return {
                "status": "finalized",
                "conversation_id": exact,
                "through_sequence": latest_sequence,
                "compaction": compacted,
                "promotion": promotion,
            }

    async def finalize_pending(
        self,
        conversation_id: str,
        *,
        session_boundary: str,
    ) -> list[dict[str, Any]]:
        ledger = self._ledger()
        pending = {
            row["conversation_id"]: row
            for row in ledger.deferred_observation_finalizations()
        }
        if conversation_id and conversation_id not in pending:
            self.defer_observation_session(conversation_id, session_boundary)
            pending = {
                row["conversation_id"]: row
                for row in ledger.deferred_observation_finalizations()
            }
        results = []
        for session_id, row in pending.items():
            boundary = str(row.get("session_boundary") or session_boundary)
            try:
                result = await self.finalize_observation_session(
                    session_id,
                    session_boundary=boundary,
                )
            except Exception as exc:  # noqa: BLE001 - retain the exact session for retry
                error = (
                    f"Observation promotion deferred: {type(exc).__name__}: {exc}"
                )[:MAX_EVENT_TEXT]
                ledger.defer_observation_finalization(
                    session_id,
                    boundary,
                    error=error,
                )
                results.append({
                    "status": "deferred",
                    "conversation_id": session_id,
                    "error": error,
                })
            else:
                results.append(result)
        return results


RUNTIME = ConversationRuntime()
