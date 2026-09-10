"""Inspect pending owner-review evidence without deciding it."""

from __future__ import annotations

import json


def execute(args: dict, context: dict) -> str:
    del context
    from obsidience.harness.knowledge.review import list_proposals
    from obsidience.harness.knowledge.vault import Resolver, iter_notes

    task_ref = str(args.get("task", ""))
    if task_ref:
        task = Resolver(iter_notes()).resolve(task_ref)
        if not task or task.kind != "task":
            return json.dumps({"error": "An exact accepted Task is required"})
        task_ref = task.ref
    proposal = str(args.get("proposal", ""))
    rows = [row for row in list_proposals()
            if (not task_ref or row.get("task") == task_ref)
            and (not proposal or row.get("file") == proposal)]
    fields = ("file", "target", "task", "run_id", "action", "review_class", "reason",
              "proposed_at", "blocked_reason", "evidence_warning", "approvable", "link_changes")
    result = []
    for row in rows[:8]:
        item = {key: row.get(key) for key in fields}
        item["reason"] = str(item.get("reason") or "")[:1200]
        item["body_preview"] = str(row.get("body_preview", ""))[:2400] if proposal else ""
        item["body_truncated"] = bool(proposal and len(str(row.get("body_preview", ""))) > 2400)
        item["link_evidence"] = row.get("link_evidence", [])[:8]
        result.append(item)
    return json.dumps({"pending": result, "count": len(rows), "truncated": len(rows) > 8,
                       "rule": "Pending proposals are unaccepted. No pending proposal does not prove approval."}, default=str)
