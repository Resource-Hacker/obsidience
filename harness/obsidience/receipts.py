"""Immutable run receipts (evidence), written as vault notes (Obsidian-visible)."""

from __future__ import annotations

import time

from .vault import Note, slugify, write_note
from .review import git_commit


def write_receipt(task: Note, agent: str, run_id: str, status: str, summary: str,
                  trace: list[dict], started: float, finished: float) -> str:
    ts = time.strftime("%Y-%m-%d-%H%M%S", time.localtime(started))
    rel = f"Receipts/{slugify(task.title)}/{ts}-{run_id}.md"
    tool_log = "\n".join(
        f"- `{t.get('tool')}` {str(t.get('args'))[:120]} → {str(t.get('obs', ''))[:160]}"
        for t in trace if "tool" in t
    ) or "- (no tool calls)"
    body = (
        f"Run of [[{task.ref}]] by the {agent}.\n\n"
        f"## Summary\n{summary or '(none)'}\n\n"
        f"## Tool log\n{tool_log}\n"
    )
    meta = {
        "kind": "receipt", "run_id": run_id, "task": f"[[{task.ref}]]",
        "agent": agent, "status": status,
        "started": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(started)),
        "duration_s": round(finished - started, 1),
    }
    write_note(rel, meta, body)
    _append_log("run", f"{task.title} ({status})", started)
    git_commit(f"[receipt] {task.title}: {status} ({run_id})", [rel])
    return rel


def _append_log(op: str, title: str, when: float) -> None:
    """Append-only chronology, karpathy llm-wiki convention:
    `## [YYYY-MM-DD] <op> | <title>` — greppable with `grep "^## \[" log.md`."""
    from .config import CONFIG
    line = f"## [{time.strftime('%Y-%m-%d %H:%M', time.localtime(when))}] {op} | {title}\n"
    with open(CONFIG.vault_dir / "log.md", "a") as f:
        f.write(line)
