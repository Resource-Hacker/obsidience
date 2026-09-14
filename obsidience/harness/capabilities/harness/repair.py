"""Requeue one exact, inspected and fully covered occurrence without replay."""

from __future__ import annotations

import json


def execute(args: dict, context: dict) -> str:
    from obsidience.harness.execution import repair, scheduler
    from obsidience.harness.knowledge.vault import _NOTE_WRITE_LOCK, load_note

    def result(status: str, reason: str, **evidence) -> str:
        return json.dumps({"status": status, "reason": reason, **evidence}, sort_keys=True)

    if (not isinstance(args, dict) or set(args) != {"task", "run_id"}
            or any(not isinstance(args[key], str) or not args[key] or len(args[key]) > maximum
                   for key, maximum in (("task", 1024), ("run_id", 128)))):
        return result("blocked", "Exactly one Task and previous run_id are required.")
    task_ref, run_id = args["task"], args["run_id"]
    if (not isinstance(context.get("task"), str) or not context["task"]
            or not isinstance(context.get("run_id"), str) or not context["run_id"]):
        return result("blocked", "Recovery requires an active Task execution with the harness.repair Tool.", **args)
    snapshot = context.get("_harness_snapshot")
    plan = snapshot.get("repair_plan") if isinstance(snapshot, dict) else None
    if not isinstance(plan, list) or len(plan) > repair.PLAN_LIMIT:
        return result("blocked", "A same-run harness.status repair plan is required.", **args)
    matches = [row for row in plan if isinstance(row, dict)
               and row.get("task") == task_ref and row.get("run_id") == run_id]
    if len(matches) != 1:
        return result("blocked", "The exact occurrence is absent or ambiguous in the inspected plan.", **args)
    row = matches[0]
    if row.get("operation") != "retry":
        return result("blocked", str(row.get("reason") or "This occurrence has no permitted repair."), **args)
    # Any attempted recovery consumes the inspection, including a rejected
    # race. Completion must observe current state again after this boundary.
    context.pop("_harness_snapshot", None)
    if repair.repair_attempt_count(context) >= repair.PASS_ATTEMPT_LIMIT:
        return result("blocked", "This pass reached its recovery-attempt limit. Read harness.status again "
                      "and report the remaining work for a later Check pass.", **args)
    # Keep snapshot validation and the existing mutation under the same owner
    # lock. The scheduler rechecks exact params/FIFO and strict coverage inside
    # its SQLite transaction before committing the once-per-occurrence receipt.
    with _NOTE_WRITE_LOCK:
        note = load_note(task_ref + ".md")
        if (note is None or note.kind != "task" or note.ref != task_ref
                or note.ref == repair.REPAIR_TASK or note.path.startswith(("_", "."))
                or note.meta.get("article_status") == "deprecated"):
            return result("blocked", "An exact active accepted Task is required.", **args)
        try:
            if repair.occurrence_key(note) != row.get("occurrence_key"):
                raise ValueError("The occurrence changed after the health inspection.")
            previous = repair.retry_receipt(note)
            if previous is not None:
                return result("already_processed", repair.ALREADY_RETRIED, **args,
                              repair_receipt_id=previous["id"], current_status=note.meta.get("status"))
            applied = scheduler.retry_failed_occurrence(note, run_id, require_receipts=True)
        except repair.AlreadyProcessed as exc:
            return result("already_processed", str(exc), **args, repair_receipt_id=exc.receipt_id)
        except (ValueError, RuntimeError, TypeError, KeyError, RecursionError) as exc:
            return result("blocked", str(exc), **args)
    return result("requeued", "One retry is pending normal admission; the target has not completed.",
                  **args, occurrence_key=row["occurrence_key"],
                  repair_receipt_id=applied["repair_receipt_id"], queue_depth=applied["queue_depth"])
