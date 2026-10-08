"""Adapter for ``harness.status``."""

from __future__ import annotations

import json


def execute(args: dict, context: dict) -> str:
    del args
    from obsidience.harness.execution.ledger import current_task_issue, run_history_findings
    from obsidience.harness.execution.repair import repair_plan
    from obsidience.harness.execution.scheduler import source_health_issues
    from obsidience.harness.knowledge.index import INDEX
    from obsidience.harness.knowledge.review import list_reviews
    from obsidience.harness.knowledge.source import list_source_files
    from obsidience.harness.knowledge.vault import iter_notes

    notes = iter_notes()
    tasks = [note for note in notes if note.kind == "task"]
    graph = INDEX.graph()
    recent_runs = INDEX.runs(20)
    source_status = list_source_files()
    source_findings = {json.dumps(item, sort_keys=True): item
                       for item in [*source_status["issues"], *source_health_issues()]}
    task_states: dict[str, int] = {}
    task_issues = []
    from obsidience.harness.memory.hindsight import MEMORY
    memory = MEMORY.status()
    for task in tasks:
        state = str(task.meta.get("status", "draft"))
        task_states[state] = task_states.get(state, 0) + 1
        issue = current_task_issue(task)
        if issue:
            task_issues.append({"task": task.ref, "status": state, **issue})
    report = {
        "status": "degraded" if source_findings or task_issues or memory["status"] == "degraded" else "healthy",
        "memory": memory,
        "task_issues": task_issues[:12],
        "task_issue_count": len(task_issues),
        "notes": len(notes),
        "graph_nodes": len(graph.get("nodes", [])),
        "graph_links": len(graph.get("links", [])),
        "tasks": len(tasks),
        "tasks_by_status": task_states,
        "reviews_pending": len(list_reviews()),
        "source_files": len(source_status["files"]),
        "source_issues": len(source_findings),
        "source_coverage": source_status.get("coverage", {}),
        "recent_runs": len(recent_runs),
        "recent_failures": sum(
            1 for row in recent_runs if row.get("status") in {"failed", "blocked"}
        ),
        "history": run_history_findings(INDEX),
        "repair_plan": [*MEMORY.repair_plan(), *repair_plan(tasks)],
    }
    # Runtime evidence from this actual read, never model-authored arguments.
    context["_harness_snapshot"] = report
    return json.dumps(report, sort_keys=True)
