"""Adapter for the executor-owned ``task.complete`` terminal decision."""

from __future__ import annotations


def _generated_runbook_completion_error(status: str, context: dict) -> str | None:
    if context.get("event") != "task.checkout":
        return None
    params = context.get("params")
    if not isinstance(params, dict):
        return "Runbook generation is missing checkout event parameters"
    expected = str(params.get("output_runbook", "")).strip()
    staged = context.get("staged_proposals")
    matched = any(
        isinstance(item, dict)
        and item.get("target") == expected
        and item.get("action") in {"create", "update"}
        for item in (staged if isinstance(staged, list) else [])
    )
    if matched and status != "review":
        return 'a staged Runbook must finish with status "review"'
    if not matched and status != "failed":
        return (
            f"no validated proposal for {expected or '(missing output path)'} was staged "
            'during this execution; call vault.propose, then finish with status "review"'
        )
    return None


def _completion_error(task, status: str, context: dict) -> str | None:
    error = _generated_runbook_completion_error(status, context)
    if error:
        return error
    staged = context.get("staged_proposals")
    if staged and status != "review":
        return 'an execution with staged proposals must finish with status "review"'
    if status != "review":
        return None
    staged_targets = {
        str(item.get("target", ""))
        for item in (staged or [])
        if isinstance(item, dict) and item.get("target")
    }
    from obsidience.harness.knowledge.review import list_proposals

    incomplete = [
        row
        for row in list_proposals()
        if (
            str(row.get("task", "")) == task.ref
            or str(row.get("target", "")) in staged_targets
        )
        and str(row.get("blocked_reason", "")).startswith(
            "Merge is incomplete; no redirect proposal exists for:"
        )
    ]
    if incomplete:
        detail = " | ".join(str(row["blocked_reason"]) for row in incomplete)
        return (
            "review cannot complete while an archive lacks redirect proposals. "
            + detail
            + ". Read every exact missing Article, stage its complete redirect update, "
            "then call task.complete again."
        )
    if staged:
        return None
    if task.meta.get("acceptance"):
        return None
    return (
        "review requires a proposal staged by this exact execution or an explicit "
        "acceptance gate authored on the Task; a deferred downstream activation "
        "completes the calling Task honestly"
    )


def execute(args: dict, context: dict) -> dict:
    from obsidience.harness.knowledge.vault import resolver

    args = args or {}
    context = context or {}
    if context.get("realtime") is True:
        return {
            "accepted": False,
            "status": "",
            "summary": "",
            "error": (
                "task.complete is owned by the Realtime button. Return a reply object "
                "for this conversational turn instead."
            ),
        }
    requested_status = str(args.get("status", "completed"))
    if requested_status not in ("completed", "failed", "review"):
        requested_status = "completed"
    task = context.get("task_note")
    if task is None:
        task = resolver().resolve(str(context.get("task", "")))
    if not task or task.kind != "task":
        return {
            "accepted": False,
            "status": requested_status,
            "summary": "",
            "error": "active Task execution context is incomplete",
        }
    error = _completion_error(task, requested_status, context)
    if error:
        return {
            "accepted": False,
            "status": requested_status,
            "summary": "",
            "error": error,
        }
    return {
        "accepted": True,
        "status": requested_status,
        "summary": str(args.get("summary", ""))[:2000],
        "error": "",
    }
