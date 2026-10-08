"""One Executive conversation lane shared by text and speech input."""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from typing import Any, Literal

from .store import CONVERSATION
from .selection import EXECUTIVE_REF, admit_executive
from .evidence import historical_evidence
from ..execution import trace
from ..execution import activity as knowledge_activity
from ..knowledge.index import INDEX
from ..knowledge.vault import Note, resolver
from ..models import runtime as model_runtime
from ..models.context import PROMPT_SAFETY_TOKENS, cached_text_count, measure_text

EXECUTIVE_AGENT_REF = "Agents/Executive/Executive"
SPEECH_RESPONSE_CONTRACT = (
    "This is a voice conversation. Owner utterances reach you as speech-recognition text, "
    "not raw audio. Receiving an utterance establishes that its words were captured. "
    "For a check such as 'can you hear me?', acknowledge receiving the spoken request "
    "directly; no camera observation is needed. A camera image cannot establish hearing. "
    "Transcript receipt alone does not establish audio quality, speaker identity, or "
    "continuous microphone health. "
    "Answer the owner in one or two short spoken sentences unless detail is requested. "
    "If unclear, ask one brief question. Never narrate Task, Tool, transport, "
    "or harness status unless asked. Answer directly in text; use native Tools for operations."
)
MAX_EVENT_TEXT = 512
DEFAULT_CONTEXT_THRESHOLD = 80
MIN_CONTEXT_THRESHOLD = 60
MAX_CONTEXT_THRESHOLD = 90
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
        self._last_task_ref = EXECUTIVE_REF
        self._session_finalize_lock = asyncio.Lock()
        self._compacting = False
        self._thinking_overhead_tokens = DEFAULT_THINKING_OVERHEAD_TOKENS
        self.speech = None
        self._steering: TurnSteering | None = None
        self._prefill_task: asyncio.Task | None = None
        self._prefill_latest: tuple[int, str] | None = None
        self._prepared_native: tuple[str, int] | None = None
        self._warm_state = "waiting"
        self._context_refresh_task: asyncio.Task | None = None
        self._context_refresh_requested: tuple[int, str] | None = None

    def readiness(self) -> dict:
        return {"state": self._warm_state, "warm": self._warm_state == "ready"}

    def invalidate_readiness(self) -> None:
        self._warm_state = "busy"
        self._prefill_latest = None

    def prepare_idle(self) -> None:
        """Prepare the selected Executive conversation when model work releases."""
        if (self.speech is None or not self.speech.snapshot()["ready"]
                or self._lock.locked() or not self.continuation_resume_available()
                or model_runtime.RUNTIME.work_requested):
            return
        if self._warm_state == "ready" and self._prefill_latest == (0, ""):
            return
        self._prefill_latest = (0, "")
        if self._prefill_task is None or self._prefill_task.done():
            self._prefill_task = asyncio.create_task(self._prepare_speech(), name="obsidience-executive-standby")

    def _stable_prefix_current(self) -> bool:
        """Ready standby already warmed the exact prefix a partial would prepare.

        Native preparation stops before request text, Scene and Knowledge. Model
        work invalidates readiness; any native turn advances the revision.
        """
        if self._warm_state != "ready" or self._prepared_native is None:
            return False
        from ..execution.deepseek.sessions import view
        conversation_id, revision = self._prepared_native
        current = view(conversation_id)
        return (conversation_id == self._conversation.conversation_id
                and current is not None and current.get("revision") == revision)

    def prepare_speech_prefix(self, text: str, sequence: int) -> None:
        """Coalesce partials into one cancellable, non-persistent model warmup."""
        if (not text.strip() or len(text) > MAX_EVENT_TEXT
                or type(sequence) is not int or sequence <= 0
                or self._lock.locked()
                or self.speech is None or not self.speech.snapshot()["ready"]
                or (self._turn_task is not None and not self._turn_task.done())
                or self._stable_prefix_current()):
            return
        latest = (sequence, text)
        if latest == self._prefill_latest:
            return
        self._prefill_latest = latest
        if self._prefill_task is None or self._prefill_task.done():
            self._prefill_task = asyncio.create_task(self._prepare_speech(), name="obsidience-speech-prefill")

    async def _prepare_speech(self) -> None:
        from ..execution.deepseek.prefill import prepare

        try:
            while self._prefill_latest is not None:
                sequence, text = latest = self._prefill_latest
                if sequence and self._stable_prefix_current():
                    # A partial queued behind standby would repeat its exact prefix.
                    self._prefill_latest = (0, "")
                    break
                started = time.monotonic()
                conversation_id = self._conversation.conversation_id
                if sequence == 0:
                    self._warm_state = "warming"
                    self._prepared_native = None
                    if self.speech is not None:
                        await self.speech.publish_readiness()
                trace.latency("speech_prefill_started", speech_sequence=sequence)
                try:
                    result = await prepare(self._conversation, text, SPEECH_RESPONSE_CONTRACT,
                                           idle=sequence == 0)
                    if sequence == 0:
                        self._warm_state = "ready" if result["status"] == "prepared" else "unavailable"
                        if self._warm_state == "ready" and result.get("native_revision") is not None:
                            self._prepared_native = (conversation_id, result["native_revision"])
                    trace.latency("speech_prefill_completed", speech_sequence=sequence,
                                  duration_ms=(time.monotonic() - started) * 1000)
                    trace.emit("measurement", "Executive standby preparation" if sequence == 0 else "Speech prefix preparation", [
                        f"status: {result['status']}",
                        f"prompt_tokens: {result.get('prompt_tokens', 0)}",
                        f"cached_tokens: {result.get('cached_tokens', 0)}",
                    ])
                except asyncio.CancelledError:
                    if sequence == 0:
                        self._warm_state = "busy" if model_runtime.RUNTIME.work_requested else "waiting"
                    trace.latency("speech_prefill_cancelled", speech_sequence=sequence)
                    raise
                except Exception as exc:
                    if sequence == 0:
                        self._warm_state = "unavailable"
                    # Optional preparation never blocks final admission or exposes draft output.
                    trace.emit("measurement", "Speech prefix preparation skipped", [type(exc).__name__])
                if latest == self._prefill_latest:
                    break
        finally:
            self._prefill_task = None
            if self.speech is not None:
                await self.speech.publish_readiness()

    async def _cancel_speech_prefill(self) -> None:
        self._prefill_latest = None
        task = self._prefill_task
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

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
                            speech_sequence: int | None = None,
                            outcome: str = "") -> None:
        """Speech delivery cannot change an already settled Task outcome."""
        if self.speech is None or generation != self._generation:
            return
        try:
            await self.speech.speak({
                "type": "speak", "generation": generation, "text": text,
                "outcome": outcome,
                **({"turn_id": turn_id} if turn_id else {}),
                **({"run_id": run_id} if run_id else {}),
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
        await self._cancel_context_refresh()
        await self._cancel_speech_prefill()
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
            from ..execution.deepseek.bridge import BRIDGE
            await BRIDGE.control('close', session_id=outgoing)
            result = await self._conversation.new_conversation()
            await self.publish_context()
            self._warm_state = "waiting"
            asyncio.get_running_loop().call_soon(self.prepare_idle)
            return result

    async def submit(
        self, text: str, *, source: Literal["text", "realtime"] = "text", wait: bool = True,
        speech_timing: dict | None = None, memory_writeback: bool = True,
    ) -> dict[str, Any]:
        """Bind one exact user turn, independent of microphone state.

        memory_writeback=False keeps an owner-controlled diagnostic turn out of
        Hindsight; the turn is otherwise ordinary.
        """
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
                               received_ns=received_ns, speech_timing=speech_timing,
                               memory_writeback=memory_writeback),
                name=f"obsidience-conversation-turn-{user_turn['id']}",
            )
            self._turn_task = turn_task
            turn_task.add_done_callback(lambda _task: self.prepare_idle())
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
        memory_writeback: bool = True,
    ) -> dict[str, Any]:
        from ..execution.scheduler import foreground_admission

        # Transport metadata never becomes conversation text or Task authority.
        timing = trace.input_speech_timing(speech_timing) if source == "realtime" else None
        sequence = timing["speech_sequence"] if timing else None
        scope = trace.bind_turn(str(user_turn["id"]), speech_sequence=sequence, generation=generation)
        # The Executive is handling this accepted request before a Task exists.
        # Only its identity may light until the real compiler supplies the packet.
        knowledge_activity.emit("admission_started", [EXECUTIVE_AGENT_REF],
                                turn_id=str(user_turn["id"]))
        try:
            trace.latency("input_final", monotonic_ns=received_ns)
            for edge in timing["stages"] if timing else ():
                trace.latency(edge["stage"], monotonic_ns=edge["monotonic_ns"])
            async with foreground_admission("conversation"):
                return await self._run_admitted_turn(text, generation, user_turn, source=source,
                                                     speech_sequence=sequence,
                                                     memory_writeback=memory_writeback)
        finally:
            knowledge_activity.emit("admission_completed", [], turn_id=str(user_turn["id"]))
            trace.reset(scope)

    async def _run_admitted_turn(
        self, text: str, generation: int, user_turn: dict, *,
        source: Literal["text", "realtime"],
        speech_sequence: int | None = None, memory_writeback: bool = True,
    ) -> dict[str, Any]:
        from ..execution.executor import run_conversation

        self._conversation.publish({"type": "start", "source": source})
        inbox = self._steering
        self._publish_active_turn()
        activity_completion: dict = {}
        refresh_context = False
        try:
            admission_started = time.monotonic()
            task, params, event = admit_executive(text, "voice" if source == "realtime" else "text")
            trace.latency("admission", duration_ms=(time.monotonic() - admission_started) * 1000)
            self._last_task_ref = task.ref
            preparation_started = time.monotonic()
            context = await self.prepare_conversation_context(user_turn, context_task_ref=task.ref)
            prior_effects = historical_evidence(
                self._conversation, conversation_id=str(user_turn["conversation_id"]),
                before_sequence=int(user_turn["sequence"]),
            )
            trace.latency("preparation", duration_ms=(time.monotonic() - preparation_started) * 1000)
            trace.emit("event", f"{task.title} activated", [task.ref, event])
            params.update({
                "conversation_id": str(user_turn["conversation_id"]),
                "reply_to_turn_id": str(user_turn["id"]),
            })
            if source == "realtime":
                params["response_contract"] = SPEECH_RESPONSE_CONTRACT
            async def verified_command(name: str, run_id: str) -> None:
                if source == "realtime" and generation == self._generation and self.speech is not None:
                    # The command's receipt and fresh state are settled now;
                    # do not wait for the model to compose its closing text.
                    trace.latency("command_verified", run_id=run_id)
                    await self.speech.cue("complete")

            result = await run_conversation(
                task, runtime_params=params, emit_turn_event=False,
                interactive=True, conversation_context=context,
                conversation_evidence=prior_effects,
                routing_context=self._routing_context(user_turn),
                steering=inbox,
                activity_completion=activity_completion,
                verified_command=verified_command,
            )
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
                raise RuntimeError("the Executive produced no public reply")
            assistant_turn = await self._conversation.append(
                role="assistant", source=source, text=reply,
                run_id=str(result.get("run_id") or "") or None,
                conversation_id=str(user_turn["conversation_id"]),
                reply_to=str(user_turn["id"]),
            )
            trace.latency("answer_committed", run_id=str(result.get("run_id") or ""))
            if memory_writeback:
                from ..memory.hindsight import MEMORY
                MEMORY.completed("Agents/Executive/Executive", text, reply,
                                 source="conversation:" + str(user_turn["conversation_id"]), identifier=str(user_turn["id"]))
            if source == "realtime" and result.get("voice_confirmation") != "cue_only":
                await self._speak_public(reply, generation, turn_id=str(user_turn["id"]),
                                         run_id=str(result.get("run_id") or ""),
                                         speech_sequence=speech_sequence, outcome="completed")
            refresh_context = True
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
                {"status": "failed", "run_id": activity_completion.get("run_id")}, source=source, generation=generation,
            )
            return {"status": "failed", "summary": message}
        finally:
            if activity_completion:
                knowledge_activity.emit(**activity_completion)
            if inbox is not None:
                inbox.close()
            if self._steering is inbox:
                self._steering = None
                self._publish_active_turn()
            self._conversation.publish({"type": "end"})
            if self._turn_task is asyncio.current_task():
                self._turn_task = None
            if (refresh_context and generation == self._generation
                    and not asyncio.current_task().cancelling()):
                self.request_context_refresh()

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
            await self._speak_public(notice, generation, run_id=str(result.get("run_id") or ""),
                                     outcome="failed")

    def _context_model(self, task_ref: str | None = None) -> model_runtime.ModelSpec:
        from ..knowledge.links import article_ref
        from ..knowledge.vault import load_note, resolver

        reference = task_ref or self._last_task_ref
        # The selected execution owner supplies its canonical identity. Preserve
        # ordinary resolver fallback for aliases, case variants, and misses.
        task = (
            load_note(reference + ".md")
            if reference.startswith(("Tasks/", "Agents/"))
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
        from ..execution.deepseek.sessions import compaction_threshold
        return compaction_threshold()

    async def context_status(
        self,
        *,
        before_sequence: int | None = None,
        conversation_id: str | None = None,
        context_task_ref: str | None = None,
        pending_text: str = "",
    ) -> dict[str, Any]:
        """Measure the selected model's native conversation input."""
        from .context import project_conversation
        from ..execution.deepseek.sessions import measure_context

        exact_conversation_id = conversation_id or self._conversation.conversation_id
        projection = project_conversation(
            self._conversation,
            conversation_id=exact_conversation_id,
            before_sequence=before_sequence,
        )
        spec = self._context_model(context_task_ref)
        # Native compaction prices pressure against the adapter's context window.
        # The provider's exact request guard separately reserves output capacity.
        capacity = spec.context_tokens
        count = await measure_context(exact_conversation_id, spec,
                                      before_sequence=before_sequence, pending_text=pending_text)
        if count is not None:
            used, method, scope = count.tokens, count.method, "native_session"
        else:
            # A conversation without a native session still uses the legacy
            # migration projection. Measure its text rather than showing bytes.
            immediate, pending = await asyncio.gather(
                measure_text(str(projection["body"]), spec), measure_text(pending_text, spec),
            )
            used = self._thinking_overhead_tokens + immediate.tokens + pending.tokens
            method = "runtime" if immediate.method == pending.method == "runtime" else "utf8_upper_bound"
            scope = "conversation_with_estimated_overhead"
        return {
            "type": "context",
            "conversation_id": exact_conversation_id,
            "article_ref": projection["ref"],
            "used_tokens": used,
            "count_method": method,
            "measurement_scope": scope,
            "capacity_tokens": capacity,
            "percent": round(min(100.0, used * 100.0 / capacity), 1),
            "compact_at": self._context_threshold(),
            "compacting": self._compacting,
            "compaction_count": projection["compaction_count"],
            "compaction_backend": "deepseek",
            "latest_sequence": projection["latest_sequence"],
        }

    async def publish_context(self) -> dict[str, Any]:
        status = await self.context_status()
        self._conversation.publish(status)
        return status

    def request_context_refresh(self) -> None:
        """Refresh the display after delivery; never hold the conversation lane."""
        self._context_refresh_requested = (self._generation, self._conversation.conversation_id)
        if self._context_refresh_task is None or self._context_refresh_task.done():
            self._context_refresh_task = asyncio.create_task(
                self._refresh_context_display(), name="obsidience-context-display",
            )

    async def _refresh_context_display(self) -> None:
        try:
            while self._context_refresh_requested is not None:
                generation, conversation_id = self._context_refresh_requested
                self._context_refresh_requested = None
                status = await self.context_status(conversation_id=conversation_id)
                if (generation == self._generation
                        and conversation_id == self._conversation.conversation_id
                        and self._context_refresh_requested is None):
                    self._conversation.publish(status)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Display failure cannot turn an accepted answer into a failed turn.
            trace.emit("measurement", "Conversation context display refresh skipped", [type(exc).__name__])
        finally:
            self._context_refresh_task = None

    async def _cancel_context_refresh(self) -> None:
        self._context_refresh_requested = None
        task = self._context_refresh_task
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

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
        from ..execution.deepseek.sessions import set_compaction_threshold
        await set_compaction_threshold(value)
        return await self.publish_context()

    async def compact_conversation(self, *, force: bool, conversation_id: str | None = None,
                                   wait: bool = True) -> dict[str, Any]:
        """Manual control of the native backend; automatic pressure belongs to DeepSeek."""
        if not force:
            return {"status": "native_backend_owned"}
        async with self._lock:
            if not self.continuation_resume_available():
                raise RuntimeError("wait for the active Executive turn before compacting")
            await self._cancel_context_refresh()
            await self._cancel_speech_prefill()
            self.invalidate_readiness()
            task = asyncio.create_task(
                self._compact_conversation(conversation_id or self._conversation.conversation_id),
                name="obsidience-conversation-compact",
            )
            self._turn_task = task
            task.add_done_callback(lambda _task: self.prepare_idle())
        if not wait:
            return {"status": "started", "backend": "deepseek"}
        try:
            return await task
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if task.cancelled() and current is not None and current.cancelling() == 0:
                return {"status": "interrupted", "backend": "deepseek"}
            raise

    async def _compact_conversation(self, conversation_id: str) -> dict[str, Any]:
        from ..execution.deepseek.sessions import compact
        generation = self._generation
        self._compacting = True
        self._conversation.publish({"type": "start", "source": "compact"})
        try:
            await self.publish_context()
            return await compact(conversation_id, self._context_model())
        except Exception as exc:
            self._conversation.publish({"type": "error", "text": str(exc)[:512]})
            return {"status": "failed", "backend": "deepseek"}
        finally:
            self._compacting = False
            if self._turn_task is asyncio.current_task():
                self._turn_task = None
            self._conversation.publish({"type": "end"})
            if generation == self._generation and not asyncio.current_task().cancelling():
                self.request_context_refresh()

    async def prepare_conversation_context(self, user_turn: dict[str, Any], *, context_task_ref: str | None = None) -> str:
        from ..execution.deepseek.sessions import refresh
        from .context import project_conversation
        await refresh(str(user_turn['conversation_id']))
        return project_conversation(self._conversation, conversation_id=str(user_turn['conversation_id']),
                                    before_sequence=int(user_turn['sequence']))['body']

    def _routing_context(self, user_turn: dict) -> str:
        """Recent exact dialogue for capability selection; execution keeps full context."""
        preceding = self._ledger().conversation_turns(
            str(user_turn["conversation_id"]), before_sequence=int(user_turn["sequence"]), limit=6)
        return json.dumps([{
            "role": turn["role"], "text": turn["text"][:2000],
            "text_truncated": len(turn["text"]) > 2000,
        } for turn in preceding], ensure_ascii=False)

    async def resume_continuation(self, continuation: dict) -> dict[str, Any]:
        """Resume one claimed caller from its exact persisted user turn and result."""
        from ..execution.scheduler import foreground_admission

        async with foreground_admission("conversation.continuation"):
            return await self._resume_admitted_continuation(continuation)

    async def _resume_admitted_continuation(self, continuation: dict) -> dict[str, Any]:
        from ..execution.executor import run_conversation, _computer_request_evidence, run_task
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
        if task is None or (task.kind != "task" and not (task.kind == "agent" and task.ref == EXECUTIVE_REF)):
            raise RuntimeError("continuation caller is no longer accepted")
        try:
            bound_result = json.loads(str(continuation.get("result") or "{}"))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("continuation result is not valid JSON evidence") from exc
        if not isinstance(bound_result, dict):
            raise RuntimeError("continuation result must be an evidence object")
        objective = str(continuation.get("objective", "")).strip()
        if not objective or objective != user_turn.get("text"):
            raise RuntimeError("continuation lost its original objective")
        caller = ledger.run(caller_run_id)
        if caller is None or caller.get("task_ref") != task.ref or caller.get("objective") != objective:
            raise RuntimeError("continuation lost its original caller execution")
        try:
            caller_trace = json.loads(caller.get("trace") or "[]")
        except (TypeError, ValueError) as exc:
            raise RuntimeError("continuation caller evidence is invalid") from exc
        if not isinstance(caller_trace, list):
            raise RuntimeError("continuation caller evidence is invalid")
        bindings = [item for item in caller_trace if isinstance(item, dict) and "computer_request" in item]
        computer_request = {}
        if bindings:
            if len(bindings) != 1 or bindings[0].get("interactive_turn") != {
                    "conversation_id": user_turn["conversation_id"], "reply_to_turn_id": turn_id}:
                raise RuntimeError("continuation lost its exact explicit operation binding")
            recorded = bindings[0]["computer_request"]
            computer_request = _computer_request_evidence(recorded)
            if computer_request is None or computer_request != recorded:
                raise RuntimeError("continuation explicit operation binding is invalid")

        current = asyncio.current_task()
        async with self._lock:
            if self._turn_task is not None and not self._turn_task.done():
                raise RuntimeError("the Executive turn lane is busy")
            await self._cancel_context_refresh()
            self._turn_task = current
            self._last_task_ref = task.ref
            generation = self._generation
        reply_source = str(continuation.get("reply_source") or user_turn.get("source") or "text")
        if reply_source not in {"text", "realtime"}:
            reply_source = "text"
        refresh_context = False
        try:
            conversation_context = await self.prepare_conversation_context(
                user_turn,
                context_task_ref=task.ref,
            )
            prior_effects = historical_evidence(
                self._conversation, conversation_id=str(user_turn["conversation_id"]),
                before_sequence=int(user_turn["sequence"]),
            )
            execute = run_conversation if task.kind == "agent" else run_task
            result = await execute(
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
                routing_context=self._routing_context(user_turn),
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
            from ..memory.hindsight import MEMORY
            MEMORY.completed("Agents/Executive/Executive", objective, reply,
                             source="conversation:" + str(user_turn["conversation_id"]), identifier=turn_id)
            if reply_source == "realtime" and active_conversation:
                await self._speak_public(reply, generation)
            if active_conversation:
                refresh_context = True
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
            if (refresh_context and generation == self._generation
                    and not asyncio.current_task().cancelling()):
                self.request_context_refresh()

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
        """Settle retained pre-migration finalization markers without memory writes."""
        exact = str(conversation_id).strip()
        if not exact:
            raise ValueError("Session finalization requires a conversation identity")
        self._ledger().complete_observation_finalization(exact)
        return {"status": "finalized", "conversation_id": exact, "backend": "deepseek"}

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
