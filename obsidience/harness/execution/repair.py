"""Receipt-bound, once-per-occurrence recovery through the existing scheduler."""

from __future__ import annotations

import hashlib
import json
import time

from ..knowledge.index import INDEX
from ..knowledge.vault import Note
from .ledger import current_task_issue

REPAIR_TASK = "Tasks/repair"
PLAN_LIMIT = 12
PASS_ATTEMPT_LIMIT = 8
ALREADY_RETRIED = "This occurrence already received its one automatic retry; further disposition is required."


class AlreadyProcessed(ValueError):
    def __init__(self, receipt_id: str):
        super().__init__(ALREADY_RETRIED)
        self.receipt_id = receipt_id


def repair_attempt_count(context: dict) -> int:
    """Count this executor's actual Repair calls, not model-authored evidence."""
    trace = context.get("trace")
    if not isinstance(trace, list):
        return 0
    return sum(isinstance(entry, dict) and entry.get("tool") == "harness.repair"
               and entry.get("not_dispatched") is not True for entry in trace)


def occurrence_key(note: Note) -> str:
    """A later run ID does not create a new original event commitment."""
    params = note.meta.get("params")
    # Event identity survives a changed/normalized parameter spelling. The
    # receipt separately pins every original parameter, so such drift blocks
    # recovery instead of granting a second retry for the same commitment.
    identity = ([params["event"], params["activation_key"]]
                if isinstance(params, dict) and all(isinstance(params.get(key), str) and params[key]
                   for key in ("event", "activation_key")) else params)
    encoded = json.dumps([note.ref, identity], sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def retry_receipt(note: Note) -> dict | None:
    key = occurrence_key(note)
    receipt = INDEX.run("repair-" + key)
    if receipt is None:
        return None
    try:
        raw = receipt.get("trace")
        if not isinstance(raw, str) or len(raw) > 4096:
            raise ValueError
        evidence = json.loads(raw)[0]["controller_disposition"]
        if (not isinstance(evidence, dict)
                or receipt.get("task_ref") != note.ref or receipt.get("agent") != "scheduler"
                or receipt.get("status") != "requeued" or evidence.get("kind") != "automatic_retry"
                or evidence.get("occurrence_key") != key
                or evidence.get("params_sha256") != INDEX.tool_params_sha256(note.meta.get("params"))
                or evidence.get("effect_applied") is not True
                or not isinstance(evidence.get("previous_run_id"), str) or not evidence["previous_run_id"]):
            raise ValueError
    except (ValueError, TypeError, IndexError, KeyError):
        raise ValueError("Existing automatic repair receipt cannot be attested.") from None
    return {"id": receipt["id"], "previous_run_id": evidence["previous_run_id"]}


def _blocked_reason(note: Note) -> str:
    from . import scheduler

    if note.ref == REPAIR_TASK:
        return "Repair cannot retry itself."
    if retry_receipt(note) is not None:
        return ALREADY_RETRIED
    # The owner Retry API retains its historical compatibility path. Autonomous
    # Repair cannot infer missing dispatch coverage from that legacy trace.
    reason = scheduler._receipt_retry_blocked_reason(note, str(note.meta.get("last_run") or ""))
    return reason or scheduler.retry_blocked_reason(note)


def repair_plan(notes: list[Note]) -> list[dict]:
    """Bounded guidance for current issues, never authority to replay an effect."""
    eligible, blocked = [], []
    for note in sorted(notes, key=lambda item: item.ref):
        issue = current_task_issue(note)
        if note.ref == REPAIR_TASK or issue is None:
            continue
        try:
            key = occurrence_key(note)
            reason = (_blocked_reason(note) if issue["kind"] == "unresolved_occurrence"
                      else "Repair does not change Task configuration: " + issue["reason"])
        except (ValueError, TypeError, RecursionError):
            key, reason = "", "The occurrence or existing recovery evidence cannot be attested."
        target = blocked if reason else eligible
        if len(target) < PLAN_LIMIT:
            target.append({"task": note.ref, "run_id": str(note.meta.get("last_run") or ""),
                           "occurrence_key": key, "operation": "blocked" if reason else "retry",
                           "reason": reason or "Exact durable receipts permit one retry through normal Task admission."})
        # Blocked rows cannot conceal later eligible work. Both temporary lists
        # and the final display stay bounded; ties retain exact Task order.
        if len(eligible) == PLAN_LIMIT:
            break
    return eligible + blocked[:PLAN_LIMIT - len(eligible)]


def check_retry_transaction(note: Note, *, already_pending: bool) -> None:
    """Recheck at the existing Task-runtime transaction's mutation boundary."""
    if not INDEX.db.in_transaction:
        raise ValueError("Automatic retry requires the Task owner transaction.")
    receipt = retry_receipt(note)
    if receipt is not None:
        raise AlreadyProcessed(receipt["id"])
    if already_pending:
        raise ValueError("The Task occurrence is already pending; no automatic retry was applied.")
    reason = _blocked_reason(note)
    if reason:
        raise ValueError(reason)


def record_retry_transaction(note: Note, previous_run_id: str) -> str:
    """The controller receipt and pending state commit or roll back together."""
    key = occurrence_key(note)
    receipt_id = "repair-" + key
    now = time.time()
    INDEX.record_run(overwrite=False, commit=False, id=receipt_id, task_ref=note.ref,
                     agent="scheduler", started=now, finished=now, status="requeued",
                     objective="Requeue one receipt-attested Task occurrence",
                     summary="One automatic retry queued; the target outcome remains unverified.",
                     trace=json.dumps([{"controller_disposition": {
                         "kind": "automatic_retry", "occurrence_key": key,
                         "params_sha256": INDEX.tool_params_sha256(note.meta.get("params")),
                         "activation_key": note.meta["params"]["activation_key"],
                         "previous_run_id": previous_run_id, "effect_applied": True,
                         "effect": "task_requeued", "tools_replayed": False,
                     }}], sort_keys=True))
    return receipt_id
