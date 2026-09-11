"""Adapter for ``task.create``."""

from __future__ import annotations

import hashlib
import json
import re

RESEARCH_TARGETS = frozenset({
    "Tasks/research/question",
    "Tasks/research/learn",
})
_MAINTENANCE_TARGETS = {
    "Merge": "Tasks/merge",
    "Link": "Tasks/link",
    "Improve": "Tasks/improve",
    "Archive": "Tasks/archive",
    "Audit": "Tasks/audit",
}
MAX_PARAMS_JSON_CHARS = 8_000


def _maintenance_params(
    target_ref: str,
    raw_params: dict,
    context: dict,
    res,
) -> dict | None:
    """Return one same-run controller candidate, or reject forged bindings."""
    candidate_fields = {
        "candidate_key", "candidate_revision", "candidate_refs",
        "candidate_kind", "candidate_signals",
    }
    if not (candidate_fields & raw_params.keys()):
        return None
    snapshot = context.get("_maintenance_snapshot")
    candidates = snapshot.get("candidates") if isinstance(snapshot, dict) else None
    if not isinstance(candidates, list):
        raise ValueError("maintenance activation requires a same-run vault.maintenance result")
    candidate_key = str(raw_params.get("candidate_key", "")).strip().lower()
    matches = [
        row for row in candidates
        if isinstance(row, dict) and str(row.get("candidate_key", "")) == candidate_key
    ]
    if len(matches) != 1:
        raise ValueError("candidate_key does not identify one controller maintenance result")
    row = matches[0]
    expected_target = _MAINTENANCE_TARGETS.get(str(row.get("recommended_task", "")))
    if expected_target != target_ref:
        raise ValueError("maintenance candidate does not authorize the requested Task")
    refs = row.get("refs")
    if not isinstance(refs, list) or not refs:
        raise ValueError("maintenance candidate has no exact Article refs")
    notes = [res.resolve(str(ref)) for ref in refs]
    if any(
        note is None
        or note.kind not in {"agent", "knowledge"}
        or note.runtime_observation
        for note in notes
    ):
        raise ValueError("maintenance candidate Articles are no longer accepted")
    from obsidience.harness.capabilities.vault.maintenance import candidate_revision

    current_revision = candidate_revision(notes)
    if current_revision != str(row.get("candidate_revision", "")):
        raise ValueError("maintenance candidate changed after inspection; rerun Curate")
    forwarded = {
        "candidate_key": candidate_key,
        "candidate_revision": str(raw_params.get("candidate_revision", "")),
        "candidate_refs": raw_params.get("candidate_refs"),
        "candidate_kind": str(raw_params.get("candidate_kind", "")),
        "candidate_signals": raw_params.get("candidate_signals"),
    }
    expected = {
        "candidate_key": candidate_key,
        "candidate_revision": current_revision,
        "candidate_refs": refs,
        "candidate_kind": str(row.get("kind", "")),
        "candidate_signals": row.get("signals", {}),
    }
    if forwarded != expected:
        raise ValueError("maintenance candidate fields do not match the controller result")
    return expected


def execute(args: dict, context: dict) -> str:
    from obsidience.harness.execution.scheduler import enqueue_event
    from obsidience.harness.knowledge.tasks import task_triggers
    from obsidience.harness.knowledge.vault import resolver

    args = args or {}
    context = context or {}
    target_ref = str(args.get("task", "")).strip()
    target = resolver().resolve(target_ref)
    if not target or target.kind != "task":
        return f"Task activation rejected: accepted Task not found: {target_ref or '(empty)'}."
    if "task.create" not in task_triggers(target.meta):
        return (
            f"Task activation rejected: [[{target.ref}]] does not accept "
            "task.create activations."
        )
    wait_for_result = args.get("wait_for_result", False)
    await_publication = args.get("await_publication", False)
    if not isinstance(await_publication, bool) or await_publication and not wait_for_result:
        return "Task activation rejected: await_publication requires wait_for_result."
    if not isinstance(wait_for_result, bool):
        return "Task activation rejected: wait_for_result must be true or false."
    if wait_for_result and target.ref not in RESEARCH_TARGETS:
        return "Task activation rejected: only Question or Learn can be awaited."
    raw_params = args.get("params") or {}
    if not isinstance(raw_params, dict) or len(raw_params) > 8:
        return "Task activation rejected: params must be an object with at most 8 fields."
    if len(json.dumps(raw_params, sort_keys=True, default=str)) > MAX_PARAMS_JSON_CHARS:
        return "Task activation rejected: params exceed their bounded size."
    if not str(context.get("task", "")) or not str(context.get("run_id", "")):
        return "Task activation rejected: active Task execution context is incomplete."
    continuation_binding = None
    if wait_for_result:
        from obsidience.harness.knowledge.index import INDEX

        caller_params = (
            context.get("params") if isinstance(context.get("params"), dict) else {}
        )
        conversation_id = str(caller_params.get("conversation_id", "")).strip()
        reply_to_turn_id = str(caller_params.get("reply_to_turn_id", "")).strip()
        user_turn = INDEX.conversation_turn(reply_to_turn_id) if reply_to_turn_id else None
        if not (
            context.get("interactive") is True
            and user_turn
            and user_turn.get("role") == "user"
            and user_turn.get("state") == "final"
            and user_turn.get("conversation_id") == conversation_id
            and user_turn.get("source") in {"text", "realtime"}
        ):
            return (
                "Task activation rejected: wait_for_result requires one exact "
                "persisted user turn binding."
            )
        continuation_binding = {
            "conversation_id": conversation_id,
            "reply_to_turn_id": reply_to_turn_id,
            "reply_source": str(user_turn["source"]),
        }
    raw_params = {
        key: value
        for key, value in raw_params.items()
        if key not in {
            "created_by_task_ref", "created_by_run_id", "realtime_delegate",
            "interactive", "interactive_turn", "task_activation", "created_tasks",
        }
    }
    candidate_key = str(raw_params.get("candidate_key", "")).strip().lower()
    if candidate_key and not re.fullmatch(r"[a-f0-9]{12,64}", candidate_key):
        return "Task activation rejected: candidate_key is invalid."
    try:
        maintenance = _maintenance_params(target.ref, raw_params, context, resolver())
    except ValueError as exc:
        return f"Task activation rejected: {exc}."
    if maintenance is not None:
        raw_params = {
            key: value for key, value in raw_params.items()
            if not key.startswith("candidate_")
        }
        raw_params.update(maintenance)

    activation_key = (hashlib.sha256(json.dumps(
        [target.ref, candidate_key, maintenance["candidate_revision"]], sort_keys=True,
    ).encode()).hexdigest()[:20] if maintenance is not None else candidate_key) or hashlib.sha256(
        json.dumps(
            [context["run_id"], target.ref, raw_params],
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()[:20]
    params = {
        **raw_params,
        "event": "task.create",
        "target_task": target.ref,
        "created_by_task_ref": str(context["task"]),
        "created_by_run_id": str(context["run_id"]),
        "activation_key": activation_key,
    }
    queued = enqueue_event(target, params)
    if queued["state"] in {"started", "queued", "processed"}:
        context.setdefault("_created_tasks", []).append({
            "target_task_ref": target.ref,
            "activation_key": activation_key,
        })
    from obsidience.harness.execution.assignments import ensure_task_runbook
    readiness = ensure_task_runbook(target, resolver())
    continuation = None
    if wait_for_result and queued["state"] in {"started", "queued", "processed"}:
        from obsidience.harness.knowledge.index import INDEX

        assert continuation_binding is not None
        continuation = INDEX.create_continuation(
            caller_task_ref=str(context["task"]),
            caller_run_id=str(context["run_id"]),
            target_task_ref=target.ref,
            target_activation_key=activation_key,
            objective=str(context.get("objective", "")),
            **continuation_binding,
            await_publication=await_publication,
        )
    return json.dumps({
        "state": queued["state"],
        "task": target.ref,
        "target_status": queued.get("status", "pending"),
        "activation_id": queued.get("activation_id", ""),
        "reason": queued.get("reason", ""),
        "created_by": str(context["task"]),
        "hierarchy": "unchanged",
        "queue_position": queued["position"],
        "procedure": readiness,
        "waiting_for_result": continuation is not None,
        "await_publication": await_publication,
        "continuation_id": "" if continuation is None else continuation["id"],
    }, sort_keys=True)
