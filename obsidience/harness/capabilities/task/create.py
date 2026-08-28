"""Adapter for ``task.create``."""

from __future__ import annotations

import hashlib
import json
import re


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
    realtime_context = (
        context.get("realtime") is True
        and str(context.get("task", "")) == "Tasks/executive/realtime"
    )
    if "task.create" not in task_triggers(target.meta) and not realtime_context:
        return (
            f"Task activation rejected: [[{target.ref}]] does not accept "
            "task.create activations."
        )
    raw_params = args.get("params") or {}
    if not isinstance(raw_params, dict) or len(raw_params) > 8:
        return "Task activation rejected: params must be an object with at most 8 fields."
    if not str(context.get("task", "")) or not str(context.get("run_id", "")):
        return "Task activation rejected: active Task execution context is incomplete."
    raw_params = {
        key: value
        for key, value in raw_params.items()
        if key not in {"created_by_task_ref", "created_by_run_id", "realtime_delegate"}
    }
    candidate_key = str(raw_params.get("candidate_key", "")).strip().lower()
    if candidate_key and not re.fullmatch(r"[a-f0-9]{12,64}", candidate_key):
        return "Task activation rejected: candidate_key is invalid."

    activation_key = candidate_key or hashlib.sha256(
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
    if realtime_context:
        params["realtime_delegate"] = True
    queued = enqueue_event(target, params)
    return json.dumps({
        "state": queued["state"],
        "task": target.ref,
        "target_status": queued.get("status", "pending"),
        "reason": queued.get("reason", ""),
        "created_by": str(context["task"]),
        "hierarchy": "unchanged",
        "queue_position": queued["position"],
    }, sort_keys=True)
