"""Capability safety core shared by every model loop.

One call's receipt lifecycle and the evidence rules no agent framework owns:
durable dispatch receipts, uncertain-effect handling (in-flight interruption
never replays; failed or uncertain effects leave only completion), the
completion authority, single-use observation witnesses, the model-lease
handoff around model-resource Tools, prerequisite and target checks,
knowledge-graph activity, AutoSaddler decision capture and continuation
handoff binding. It keeps no messages, step budget or model-loop state;
each loop renders the outcome for its own model protocol.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import threading
import time
from dataclasses import dataclass, field

from . import activity as knowledge_activity
from . import trace as action_trace
from ..knowledge.index import INDEX
from ..capabilities.registry import MODEL_RESOURCE_TOOLS, READ_ONLY_CAPABILITIES

PRIVATE_IMAGE_FIELD = "_private_image_png"
PRIVATE_OBSERVATION_FIELD = "_private_observation_lease"
OBSERVATION_CONTEXT_FIELD = "_computer_observation_lease"
INTERRUPTED = "Interrupted while the Tool was in flight; outcome is unknown. Do not replay."


def foreground_checkpoint(interruption_event: asyncio.Event | None, ctx: dict) -> None:
    if interruption_event is not None and interruption_event.is_set():
        ctx["interruption_reason"] = "foreground_admission"
        raise asyncio.CancelledError("foreground_admission")


def publish_working_progress(ctx: dict, status: str) -> None:
    if not ctx.get("_working_context_ref") or not ctx.get("_agent_ref"):
        return
    try:
        from ..conversation.context import project_activation_context
        project_activation_context(ctx["_agent_ref"], str(ctx["task"]), ctx["_activation_id"],
                                   ctx.get("params") or {}, ctx.get("trace") or [], status,
                                   objective=str(ctx.get("objective", "")), context_refs=ctx.get("_context_refs", []))
    except Exception as exc:
        action_trace.emit("error", "Working context projection unavailable", [type(exc).__name__])


def observation_text(observation: str, nudge: str = "") -> str:
    """The model-facing rendering of one Tool observation."""
    return f"Observation:\n{observation}{nudge}"


@dataclass
class CallOutcome:
    """What one call established, for the calling loop to render.

    kind: ``prerequisite`` (rejected before dispatch), ``completion_rejected``,
    ``completed`` (accepted task.complete), ``waiting`` (task.create continuation)
    or ``returned`` (every other result, including rejections and Tool errors).
    """

    kind: str
    observation: str = ""
    image_png: bytes | None = None


@dataclass
class CapabilityExecution:
    """One activation's capability state for a loop that owns its own messages.

    ``CapabilityDispatch`` carries the same fields for the specialist loop.
    ``allowed`` is the run's current dispatch policy: failed or uncertain
    effects narrow it to ``task.complete``. ``step`` numbers calls for receipts.
    """

    task: object
    model: object
    ctx: dict
    agent_name: str
    trace: list[dict]
    emit: object
    allowed: list[str]
    interruption_event: asyncio.Event | None = None
    steering: object = None
    active_lease: object = None
    step: int = 0
    visual_context_seen: bool = False
    decision_messages: list = field(default_factory=list)
    messages: list = field(default_factory=list)
    prompt_format: str = "native_wire"
    response_observation_lease: object = None
    response_completion_observation: object = None
    pending_observation_lease: object = None
    pending_response_observation: object = None
    latest_action_evidence: object = None
    status: str = "failed"
    summary: str = "No accepted completion"
    done: bool = False


async def run_capability(ex, name: str, args: dict, *, execute, execute_async, scope_checkpoint,
                         blocked: tuple[str, dict] | None = None, started=None) -> CallOutcome:
    """Run one call through the receipt and evidence boundary.

    ``ex`` is a ``CapabilityExecution`` or ``CapabilityDispatch``. The loop
    passes the capability executors and scope checkpoint it is bound to, and an
    optional ``blocked`` observation (with extra trace fields) for a call its own
    policy refuses before dispatch. ``started`` runs once the call is announced.
    """
    from ..capabilities.task.complete import computer_completion_evidence, computer_request_target_error
    scope_checkpoint(ex.ctx, name)
    reflex_proposal = ex.ctx.pop("_reflex_proposal", None)
    if name != "task.complete":
        ex.ctx.pop("_reflex_command_verified", None)
        ex.ctx.pop("_reflex_command_result", None)
    from .optimization_incidents import snapshot, record as record_decision
    decision_sample = snapshot(ex, name, args)
    public_args = {key: value for key, value in args.items() if key != "point"}
    call_fields = {"step": ex.step + 1}
    if ex.ctx.get("run_id"):
        call_fields["call_id"] = f"{ex.ctx['run_id']}:{ex.step + 1}"
    call_started = time.perf_counter()
    receipt_started = False
    receipt_finished = False
    activity_refs: list[str] = []
    tool_ref = ex.ctx.get("_tool_receipt_articles", {}).get(name, ("", ""))[0]
    operation_id = "tool:" + str(call_fields.get("call_id", ""))

    def tool_activity(status: str) -> None:
        if not tool_ref or not ex.ctx.get("run_id"):
            return
        knowledge_activity.emit_operation(
            {"vault.read": "read", "vault.search": "search", "vault.list": "list"}.get(name, "tool"),
            "failed" if status == "error" else status, [tool_ref, *activity_refs],
            operation_id=operation_id, label=name, graph_id=ex.ctx.get("_graph_id", "main"),
            run_id=str(ex.ctx["run_id"]),
        )
    call_sig = f"{name}:sha256:" + hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()

    def begin_receipt() -> None:
        nonlocal receipt_started
        if not ex.ctx.get("_receipt_covered"):
            return
        tool_ref, tool_hash = ex.ctx["_tool_receipt_articles"].get(name, ("", ""))
        if not INDEX.begin_tool_call(
            run_id=ex.ctx["run_id"], call_id=call_fields["call_id"], step=ex.step + 1,
            tool=name, signature=call_sig, started=time.time(),
            read_only=name in READ_ONLY_CAPABILITIES and bool(tool_ref and tool_hash),
            tool_ref=tool_ref, tool_sha256=tool_hash,
        ):
            raise RuntimeError("Tool call already has a dispatch receipt; do not replay")
        receipt_started = True
        tool_activity("running")

    def finish_receipt(call_status: str, result: object) -> None:
        nonlocal receipt_finished
        if not receipt_started or receipt_finished:
            return
        encoded = json.dumps(result, sort_keys=True, default=str).encode()
        INDEX.finish_tool_call(
            run_id=ex.ctx["run_id"], call_id=call_fields["call_id"], status=call_status,
            finished=time.time(), duration_ms=(time.perf_counter() - call_started) * 1000,
            result_sha256=hashlib.sha256(encoded).hexdigest(), result_chars=len(encoded),
        )
        receipt_finished = True
        try:
            record_decision(decision_sample, ex.ctx['run_id'], ex.step + 1, result, call_status)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            ex.emit('error', 'AutoSaddler decision capture unavailable', [str(exc)[:300]])
    ex.emit("tool", f"{ex.agent_name} → {name}", [json.dumps(public_args, default=str)], {
        **call_fields, "payload": {"kind": "tool", "name": name, "phase": "start", "arguments": public_args},
    })
    if started is not None:
        started()

    def emit_tool_result(line: str, result: object, call_status: str = "returned", channel: str = "result") -> None:
        operation_status = call_status
        if call_status == "returned":
            # An inspection's subject status is not failure of the Tool.
            if isinstance(result, dict) and name not in {"task.inspect", "harness.status"}:
                outcome = result.get("observation", result) if name == "computer.observe" else result
                if isinstance(outcome, dict):
                    reported = outcome.get("status", outcome.get("state"))
                    if isinstance(reported, str) and reported in {"failed", "error", "unavailable", "blocked", "degraded"}:
                        operation_status = "failed"
                    elif reported == "rejected":
                        operation_status = "rejected"
            elif name == "vault.propose" and isinstance(result, str) and result.startswith("Proposal rejected:"):
                operation_status = "rejected"
        tool_activity(operation_status)
        ex.emit(channel, line, str(result).splitlines()[:12], {
            **call_fields, "payload": {"kind": "tool", "name": name, "phase": "result",
                "status": call_status,
                "duration_ms": round((time.perf_counter() - call_started) * 1_000, 3),
                "result": result},
        })
    from ..capabilities.source.read import precondition_error as source_precondition_error

    if source_error := source_precondition_error(name, args, ex.ctx):
        observation = "Tool prerequisite rejected: " + source_error
        ex.trace.append({"tool": name, "args": public_args, "obs": observation,
                         "sig": call_sig, "not_dispatched": True})
        emit_tool_result(f"{name} prerequisite rejected", observation, "rejected")
        ex.response_observation_lease = ex.response_completion_observation = None
        return CallOutcome("prerequisite", observation)
    if name != "computer.act":
        ex.response_observation_lease = None
    if name == "task.complete":
        if ex.steering is not None:
            ex.steering.close()
        # Only completion receives this single-response image witness.
        # Keep it out of shared context during provider or Tool work,
        # and consume it even when this completion is rejected.
        completion_context = {**ex.ctx, "task_note": ex.task}
        if ex.response_completion_observation is not None:
            completion_context["_computer_response_observation"] = ex.response_completion_observation
        ex.response_completion_observation = None
        try:
            begin_receipt()
            decision = await asyncio.to_thread(
                execute, name, args, completion_context,
            )
            finish_receipt("returned", decision)
        except asyncio.CancelledError:
            finish_receipt("interrupted", "Completion interrupted; outcome unknown")
            emit_tool_result("task.complete interrupted", "Completion interrupted; no accepted result was received.", "interrupted")
            raise
        except Exception as exc:
            finish_receipt("error", f"Tool error: {exc}")
            emit_tool_result("task.complete error", f"Tool error: {exc}", "error")
            raise
        finally:
            completion_context.pop("_computer_response_observation", None)
        if not isinstance(decision, dict) or not decision.get("accepted"):
            if ex.steering is not None:
                ex.steering.activate(ex.ctx["run_id"])
            error = (
                str(decision.get("error", "invalid completion result"))
                if isinstance(decision, dict)
                else "invalid completion result"
            )
            observation = f"Completion rejected: {error}."
            ex.trace.append({
                "tool": "task.complete",
                "args": public_args,
                "obs": observation,
                "completion_rejected": True,
            })
            emit_tool_result("task.complete rejected", observation, "rejected")
            return CallOutcome("completion_rejected", observation)
        ex.status = str(decision["status"])
        ex.summary = str(decision["summary"])
        completion_args = {
            "status": ex.status,
            "summary": ex.summary,
            "outcome": str(decision.get("outcome", "")),
            "evidence": list(decision.get("evidence") or []),
        }
        if isinstance(decision.get("verification"), dict):
            completion_args["verification"] = dict(decision["verification"])
        ex.ctx["completion"] = completion_args
        ex.trace.append({
            "tool": "task.complete",
            "args": completion_args,
            "accepted": True,
        })
        emit_tool_result(f"{ex.agent_name} completion accepted for {ex.task.title}: {ex.status}", completion_args, channel="status")
        ex.done = True
        return CallOutcome("completed")
    ex.response_completion_observation = None
    private_image_png: bytes | None = None
    private_observation_lease = None
    result_object: dict | None = None
    call_status = "rejected"
    if blocked is not None:
        observation = blocked[0]
    elif name in {"application.launch", "session.unlock"} and any(
            row.get("tool") == name and row.get("args") == public_args
            and row.get("not_dispatched") is not True for row in ex.trace):
        observation = "This operation was already dispatched in this run; use its receipt and never repeat it."
    elif name not in ex.allowed:
        observation = f"Tool '{name}' is not authorized for this task."
    elif target_error := computer_request_target_error(name, args, ex.ctx):
        result_object = {
            "status": "rejected",
            "delivery": "not_dispatched",
            "failure": {"code": "controller_target_mismatch", "message": target_error},
            # Nothing was dispatched; the message names the corrected target.
            "correction_allowed": True,
        }
        observation = json.dumps(result_object, sort_keys=True)
    elif ((name in {"camera.observe", "computer.observe", "computer.act"}
           or name == "tv.control" and args.get("action") not in {
               "on", "off", "find", "volume", "volume_up", "volume_down", "mute", "unmute", "pause", "resume",
               "notice"})
          and "vision" not in ex.model.capabilities):
        observation = json.dumps({
            "observation": {
                "status": "unavailable",
                "failure": {
                    "code": "model_has_no_vision",
                    "message": "The Task-selected model cannot receive visual evidence.",
                    "retryable": False,
                },
                "action_authorized": False,
            }
        }, sort_keys=True)
    else:
        call_status = "returned"
        if name in MODEL_RESOURCE_TOOLS and ex.active_lease is not None:
            lease = ex.active_lease
            ex.active_lease = None
            await lease.__aexit__(None, None, None)
        try:
            # asyncio cancellation does not stop a to_thread worker.
            # The current action reads this event before dispatch and
            # closes its owning Shell socket if STOP arrives in flight.
            capability_cancel = threading.Event()
            ex.ctx["_capability_cancel_event"] = capability_cancel
            if name == "computer.act" and ex.response_observation_lease is not None:
                ex.ctx[OBSERVATION_CONTEXT_FIELD] = ex.response_observation_lease
            begin_receipt()
            result = await execute_async(name, args, ex.ctx)
            if isinstance(result, dict):
                result = dict(result)
                private_observation_lease = result.pop(PRIVATE_OBSERVATION_FIELD, None)
                private_value = result.pop(PRIVATE_IMAGE_FIELD, None)
                if private_value is not None:
                    if isinstance(private_value, bytes):
                        private_image_png = private_value
                    else:
                        result = {
                            "observation": {
                                "status": "unavailable",
                                "failure": {
                                    "code": "invalid_visual_evidence",
                                    "message": "The private visual evidence was invalid.",
                                    "retryable": False,
                                },
                                "action_authorized": False,
                            }
                        }
                private_value = None
            finish_receipt("returned", result)
            if isinstance(result, dict):
                result_object = result
            elif isinstance(result, str):
                try:
                    parsed_result = json.loads(result)
                except (TypeError, ValueError):
                    parsed_result = None
                if isinstance(parsed_result, dict):
                    result_object = parsed_result
            if name == "vault.maintenance" and result_object is not None:
                ex.ctx["_maintenance_snapshot"] = result_object
            if name == "source.handoff":
                source_id = str(ex.ctx.get("handoff_source_id", ""))
                if not source_id and isinstance(result, str):
                    match = re.search(
                        r"source://([0-9a-fA-F-]{36})(?![0-9a-fA-F-])",
                        result,
                    )
                    source_id = match.group(1).lower() if match else ""
                caller_run_id = str(
                    (ex.ctx.get("params") or {}).get("created_by_run_id", "")
                    if isinstance(ex.ctx.get("params"), dict)
                    else ""
                )
                if source_id:
                    ex.ctx["handoff_source_id"] = source_id
                    if caller_run_id:
                        INDEX.bind_continuation_handoff(caller_run_id, source_id)
            observation = (
                result
                if isinstance(result, str)
                else json.dumps(result, sort_keys=True, default=str)
            )
        except asyncio.CancelledError:
            capability_cancel.set()
            finish_receipt("interrupted", "Tool interrupted; outcome unknown; do not replay")
            ex.trace.append({
                "tool": name, "args": public_args, "sig": call_sig,
                "obs": INTERRUPTED, "interrupted": True, "must_not_replay": True,
            })
            emit_tool_result(f"{name} interrupted", INTERRUPTED, "interrupted")
            raise
        except Exception as exc:  # noqa: BLE001
            # Failed receipt persistence must end the activation. It
            # cannot be converted into a model-retryable Tool error.
            if ex.ctx.get("_receipt_covered") and (not receipt_started or not receipt_finished):
                if receipt_started:
                    finish_receipt("error", f"Tool error: {exc}")
                raise
            observation = f"Tool error: {exc}"
            call_status = "error"
        finally:
            ex.ctx.pop(OBSERVATION_CONTEXT_FIELD, None)
    ex.response_observation_lease = None
    entry = {"tool": name, "args": public_args, "obs": observation[:600], "sig": call_sig}
    if blocked is not None:
        entry.update(blocked[1])
    if name == "vault.propose":
        required = ex.ctx.pop("_proposal_read_prerequisite", None)
        if call_status == "returned" and required:
            entry["proposal_read_prerequisite"] = required
    completion_evidence = computer_completion_evidence(
        name, result_object, image_attached=bool(private_image_png),
    )
    if completion_evidence is not None:
        entry["completion_evidence"] = completion_evidence
    if (ex.ctx.get("_receipt_covered") and receipt_finished and call_status == "returned"
            and reflex_proposal == {"name": name, "args": args}):
        # Only the actual receipt-bound result can silence a command reply.
        # Informational reflexes and failed/uncertain effects remain spoken.
        verified = (
            isinstance(result_object, dict) and result_object.get("status") == "completed"
            and result_object.get("delivery") == "verified"
            if name in {"lights.set", "tv.control"} else
            name in {"media.pause", "application.launch", "session.unlock"}
            and (completion_evidence or {}).get("verified") is True
        )
        if verified:
            ex.ctx["_reflex_command_verified"] = True
            # The command reply reports this exact readback (e.g. TV volume).
            ex.ctx["_reflex_command_result"] = result_object
            callback = ex.ctx.get("_verified_command")
            if callback is not None and not asyncio.current_task().cancelling():
                foreground_checkpoint(ex.interruption_event, ex.ctx)
                await callback(name, ex.ctx["run_id"])
    if name == "computer.observe" and isinstance(result_object, dict):
        observed = result_object.get("observation") or {}
        failure = observed.get("failure") if isinstance(observed, dict) else None
        if (isinstance(failure, dict) and failure.get("code") == "target_ambiguous"
                and ex.task.kind != "agent"):
            # The owner must identify one window. Rewording this same
            # observation or inspecting an unrelated pane cannot do so.
            # Retain the real failure and finish with the clarification.
            # The native Executive may resolve the ambiguity in its next
            # step; read-only failure dispatched no input to preserve.
            ex.allowed = ["task.complete"]
    if name == "tv.control" and (not isinstance(result_object, dict)
                                 or (result_object.get("status") == "failed"
                                     and result_object.get("correction_allowed") is not True)):
        # The TV adapter has already exhausted its bounded transport/read
        # attempt. Preserve the failure and end this turn's effects.
        ex.ctx["_tv_control_failed"] = True
        ex.allowed = ["task.complete"]
    if name in {"application.launch", "media.pause"} and not (completion_evidence or {}).get("verified"):
        # The capability owns its bounded wait. Failure or uncertainty ends
        # effects; a verified launch may continue the owner's procedure.
        ex.allowed = ["task.complete"]
    if name in {"computer.act", "window.activate", "window.place", "session.unlock"}:
        if (result_object is not None and result_object.get("status") != "completed"
                and result_object.get("correction_allowed") is not True):
            # A terminal input failure cannot become another attempted
            # click or a different outcome. Preserve the actual error for
            # the final public response instead of inviting more Tools.
            ex.allowed = ["task.complete"]
    if name == "computer.act" or (name == "application.launch" and args.get("url")):
        # Execution-local state excludes imported or prior-run traces.
        # A later failed action invalidates the earlier action basis.
        ex.latest_action_evidence = (
            completion_evidence
            if isinstance(completion_evidence, dict)
            and completion_evidence.get("verified") is True
            else None
        )
    if (name in {"computer.act", "computer.observe"} and private_image_png
            and isinstance(completion_evidence, dict)
            and completion_evidence.get("verified") is True
            and ex.latest_action_evidence is not None
            and completion_evidence.get("target") == ex.latest_action_evidence.get("target")):
        ex.pending_response_observation = completion_evidence
    if (
        name == "computer.observe" and private_image_png
        and isinstance(completion_evidence, dict)
        and completion_evidence.get("verified") is True
        and completion_evidence.get("target", {}).get("kind") == "application"
        and isinstance(private_observation_lease, dict)
        and getattr(private_observation_lease.get("capture"), "image_png", None) == private_image_png
    ):
        ex.pending_observation_lease = private_observation_lease
    private_observation_lease = None
    ex.trace.append(entry)
    context_refs = ex.ctx.pop("_last_context_refs", []) if name in {"vault.read", "vault.search"} else []
    activity_refs = [*context_refs, *ex.ctx.pop("_last_activity_refs", [])]
    ex.ctx.setdefault("_context_refs", []).extend(ref for ref in context_refs if ref not in ex.ctx.get("_context_refs", []))
    publish_working_progress(ex.ctx, "running")
    emit_tool_result(f"{name} returned", result_object if result_object is not None else observation, call_status)
    if ex.ctx.pop("_capability_cancelled_after_commit", False) or asyncio.current_task().cancelling():
        raise asyncio.CancelledError("Tool outcome retained after cancellation")
    if (
        name == "task.create"
        and result_object is not None
        and result_object.get("waiting_for_result") is True
        and result_object.get("continuation_id")
    ):
        ex.status = "waiting"
        ex.summary = (
            "Waiting for the source-backed result of "
            f"[[{result_object.get('task', '')}]]."
        )
        ex.trace[-1]["continuation_id"] = str(result_object["continuation_id"])
        ex.trace[-1]["wait_boundary"] = True
        ex.done = True
        return CallOutcome("waiting", observation)
    foreground_checkpoint(ex.interruption_event, ex.ctx)
    return CallOutcome("returned", observation, private_image_png)
