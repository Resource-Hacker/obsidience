"""The review system: staged proposals -> approve/reject, git as the audit trail.

A proposal is a note in _staging/ whose frontmatter carries:
  proposal: true, action: create|update, target: <vault-relative .md path>,
  agent, task, reason.
Approve applies it to the target (create fails if the target exists; update
overwrites) and commits. Reject moves it to _staging/_rejected/.
Owner edits made directly in Obsidian never pass through here — the owner is
a trusted writer by design.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import frontmatter

from .config import CONFIG
from .vault import load_note, write_note


def git_commit(message: str, rel_paths: list[str]) -> None:
    if not CONFIG.git_commit:
        return
    try:
        root = CONFIG.vault_dir.parent
        subprocess.run(["git", "-C", str(root), "add", "--"] +
                       [str(Path("vault") / p) for p in rel_paths],
                       check=False, capture_output=True, timeout=15)
        subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", message,
                        "--author", "Obsidience Harness <harness@obsidience.local>"],
                       check=False, capture_output=True, timeout=15)
    except Exception:  # noqa: BLE001 — audit trail must never break the run
        pass


def list_proposals() -> list[dict]:
    out = []
    for p in sorted(CONFIG.staging_dir.glob("*.md")):
        post = frontmatter.load(p)
        meta = dict(post.metadata or {})
        out.append({
            "file": p.name, "title": meta.get("title") or p.stem,
            "action": meta.get("action", "create"), "target": meta.get("target", ""),
            "agent": meta.get("agent", "?"), "task": meta.get("task", ""),
            "reason": meta.get("reason", ""), "proposed_at": meta.get("proposed_at", ""),
            "body_preview": post.content[:400],
        })
    return out


def _load_proposal(name: str) -> tuple[Path, dict, str]:
    p = CONFIG.staging_dir / name
    if not p.exists() or p.parent != CONFIG.staging_dir:
        raise FileNotFoundError(name)
    post = frontmatter.load(p)
    return p, dict(post.metadata or {}), post.content


def approve(name: str) -> dict:
    path, meta, body = _load_proposal(name)
    target = str(meta.get("target", "")).strip()
    if not target or target.startswith(("_", "/")) or ".." in target:
        raise ValueError(f"invalid target: {target}")
    action = meta.get("action", "create")
    existing = load_note(target)
    if action == "create" and existing:
        raise ValueError(f"target already exists: {target} (use action: update)")
    note_meta = {k: v for k, v in meta.items()
                 if k not in ("proposal", "action", "target", "reason", "proposed_at",
                              "agent", "task")}
    note_meta.setdefault("title", meta.get("title"))
    note_meta["approved_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    note_meta["provenance"] = f"proposed by {meta.get('agent', '?')} (task {meta.get('task', '-')})"
    write_note(target, note_meta, body)
    path.unlink()
    git_commit(f"[review] approve: {target} (from {meta.get('agent', '?')})", [target])
    from .indexer import INDEX
    INDEX.sync()
    return {"approved": target}


def reject(name: str, reason: str = "") -> dict:
    path, meta, body = _load_proposal(name)
    meta["rejected_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    meta["rejected_reason"] = reason[:400]
    dest = f"_staging/_rejected/{path.name}"
    write_note(dest, meta, body)
    path.unlink()
    return {"rejected": path.name, "moved_to": dest}
