"""Adapter for ``harness.status``."""

from __future__ import annotations

import json


def execute(args: dict, context: dict) -> str:
    del args, context
    from obsidience.harness.knowledge.index import INDEX
    from obsidience.harness.knowledge.review import list_proposals
    from obsidience.harness.knowledge.source import list_source_files
    from obsidience.harness.knowledge.vault import iter_notes

    notes = iter_notes()
    tasks = [note for note in notes if note.kind == "task"]
    graph = INDEX.graph()
    recent_runs = INDEX.runs(20)
    source_status = list_source_files()
    task_states: dict[str, int] = {}
    for task in tasks:
        state = str(task.meta.get("status", "draft"))
        task_states[state] = task_states.get(state, 0) + 1
    return json.dumps({
        "status": "healthy" if not source_status["issues"] else "degraded",
        "notes": len(notes),
        "graph_nodes": len(graph.get("nodes", [])),
        "graph_links": len(graph.get("links", [])),
        "tasks": len(tasks),
        "tasks_by_status": task_states,
        "reviews_pending": len(list_proposals()),
        "source_files": len(source_status["files"]),
        "source_issues": len(source_status["issues"]),
        "recent_runs": len(recent_runs),
        "recent_failures": sum(
            1 for row in recent_runs if row.get("status") in {"failed", "blocked"}
        ),
    }, sort_keys=True)
