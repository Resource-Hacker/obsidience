"""Read one accepted Task and bounded execution evidence; never retry it."""

from __future__ import annotations

import json


def _stored_truncated(value: object) -> bool:
    """Retain the ledger's clipping signals when making a smaller display copy."""
    if isinstance(value, str):
        return "[truncated sha256=" in value
    if isinstance(value, list):
        return any(_stored_truncated(item) for item in value)
    if isinstance(value, dict):
        return any(key in value for key in ("trace_truncated", "_truncated_fields", "_truncated_items")) or any(
            _stored_truncated(item) for item in value.values()
        )
    return False


def execute(args: dict, context: dict) -> str:
    del context
    from obsidience.harness.knowledge.index import INDEX
    from obsidience.harness.knowledge.vault import Resolver, iter_notes

    note = Resolver(iter_notes()).resolve(str(args.get("task", "")))
    if not note or note.kind != "task":
        return json.dumps({"error": "An exact accepted Task is required"})
    run_id = str(args.get("run_id", ""))
    columns = "id,started,finished,status,summary,model,runbook_ref,runbook_sha256,trace"
    query = f"SELECT {columns} FROM runs WHERE task_ref=?"
    params = [note.ref]
    if run_id:
        query += " AND id=?"
        params.append(run_id)
    with INDEX.lock:
        rows = INDEX.db.execute(query + " ORDER BY started DESC LIMIT 5", params).fetchall()
    runs = []
    for raw in rows:
        row = dict(zip(columns.split(","), raw))
        row["summary"] = str(row["summary"] or "")[:1600]
        try:
            trace = json.loads(row.pop("trace") or "[]")
            if not isinstance(trace, list):
                raise ValueError("Trace is not a list")
        except (ValueError, TypeError):
            row["evidence_error"] = "Stored trace is unavailable or invalid; do not infer success"
            trace = []
        steps = [step for step in trace if isinstance(step, dict) and step.get("tool")]
        row["tool_evidence"] = [{
            "tool": step["tool"],
            "arguments": json.dumps(step.get("args", {}), default=str)[:1200],
            "result": str(step.get("obs", ""))[:1600],
            "truncated": len(json.dumps(step.get("args", {}), default=str)) > 1200
            or len(str(step.get("obs", ""))) > 1600 or _stored_truncated(step),
        } for step in steps[:12]] if run_id else []
        row["tool_count"] = len(steps)
        row["tool_count_complete"] = bool(trace) and not any("trace_truncated" in step for step in trace if isinstance(step, dict))
        row["evidence_truncated"] = not trace or bool(steps and not run_id) or len(steps) > 12 or _stored_truncated(trace)
        if row.get("evidence_error"):
            row["tool_count_complete"] = False
            row["evidence_truncated"] = True
        receipts = INDEX.tool_run_receipts(row["id"])
        if receipts is not None and receipts["task_ref"] == note.ref:
            calls = receipts["calls"]
            row["tool_count"] = len(calls)
            row["tool_count_complete"] = True
            row["tool_receipts"] = [{key: call[key] for key in (
                "call_id", "step", "tool", "status", "read_only", "started", "finished",
                "duration_ms", "result_sha256", "result_chars",
            )} for call in calls[:12]] if run_id else []
            row["receipts_truncated"] = bool(calls and not run_id) or len(calls) > 12
            row["evidence_truncated"] |= row["receipts_truncated"] or len(steps) < len(calls)
        runs.append(row)
    return json.dumps({
        "task": note.ref, "status": note.meta.get("status", "draft"),
        "blocked_reason": str(note.meta.get("blocked_reason", ""))[:500],
        "queue_depth": len(note.meta.get("event_queue") or []),
        "schedule": note.meta.get("schedule"), "triggers": note.meta.get("triggers", []),
        "runs": runs, "requested_run_missing": bool(run_id and not runs),
        "rule": "Execution completion is not review approval; missing or truncated evidence is not proof.",
    }, default=str)
