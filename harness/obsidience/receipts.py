"""Immutable run receipts, written as vault notes (Obsidian-visible)."""

from __future__ import annotations

import time

from .vault import Note, slugify, write_note
from .review import git_commit


def write_receipt(task: Note, charter: Note, run_id: str, status: str, summary: str,
                  trace: list[dict], started: float, finished: float) -> str:
    ts = time.strftime("%Y-%m-%d-%H%M%S", time.localtime(started))
    rel = f"Receipts/{slugify(task.title)}/{ts}-{run_id}.md"
    tool_log = "\n".join(
        f"- `{t.get('tool')}` {str(t.get('args'))[:120]} → {str(t.get('obs', ''))[:160]}"
        for t in trace if "tool" in t
    ) or "- (no tool calls)"
    body = (
        f"Run of [[{task.ref}]] by [[{charter.ref}]].\n\n"
        f"## Summary\n{summary or '(none)'}\n\n"
        f"## Tool log\n{tool_log}\n"
    )
    meta = {
        "kind": "receipt", "run_id": run_id, "task": f"[[{task.ref}]]",
        "agent": charter.title, "status": status,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(started)),
        "duration_s": round(finished - started, 1),
    }
    write_note(rel, meta, body)
    git_commit(f"[receipt] {task.title}: {status} ({run_id})", [rel])
    return rel
