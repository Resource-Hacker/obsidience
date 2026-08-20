"""Agent tools. Small, closed set; charters can restrict further via `tools:`."""

from __future__ import annotations

import time

from . import retrieval
from .config import CONFIG
from .vault import load_note, resolver, slugify, write_note

TOOL_DOCS = {
    "search_vault": 'Search the vault. args: {"query": str}',
    "read_note": 'Read a full note. args: {"ref": "Folder/name or [[wikilink]]"}',
    "propose_note": ('Propose a note for owner review (goes to _staging/, never writes the vault '
                     'directly). args: {"action": "create|update", "target": "Folder/name.md", '
                     '"title": str, "body": str, "reason": str}'),
    "create_task": ('Propose a new task (staged for review). args: {"title": str, "runbook": '
                    '"[[runbook-ref]]", "assignee": "[[charter-ref]]", "body": str, "reason": str}'),
    "finish": 'End the session. args: {"status": "done|failed|review", "summary": str}',
}


def tool_docs(allowed: list[str]) -> str:
    lines = [f"- **{name}** — {TOOL_DOCS[name]}" for name in allowed if name in TOOL_DOCS]
    return "## Tools available\n" + "\n".join(lines)


def _stage(meta: dict, body: str) -> str:
    ts = time.strftime("%Y%m%d-%H%M%S")
    fname = f"_staging/{ts}-{slugify(meta.get('title') or meta.get('target') or 'proposal')}.md"
    meta.setdefault("proposed_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
    write_note(fname, meta, body)
    return fname


def run_tool(name: str, args: dict, context: dict) -> str:
    """Execute a tool; return the observation string fed back to the model."""
    args = args or {}
    if name == "search_vault":
        hits = retrieval.search(str(args.get("query", ""))[:300])
        if not hits:
            return "No results."
        return "\n".join(f"- [[{h['ref']}]] ({h['kind']}) — {h['snippet'][:160]}" for h in hits[:10])

    if name == "read_note":
        ref = str(args.get("ref", "")).strip()
        note = resolver().resolve(ref) or load_note(ref if ref.endswith(".md") else ref + ".md")
        if not note:
            return f"Note not found: {ref}"
        return note.text()[:8000]

    if name == "propose_note":
        target = str(args.get("target", "")).strip()
        if not target or target.startswith("_") or ".." in target:
            return "Invalid target path."
        if not target.endswith(".md"):
            target += ".md"
        staged = _stage({
            "proposal": True, "action": args.get("action", "create"), "target": target,
            "title": args.get("title") or target, "agent": context.get("agent", "?"),
            "task": context.get("task", ""), "reason": str(args.get("reason", ""))[:400],
        }, str(args.get("body", "")))
        return f"Proposal staged for owner review at {staged}."

    if name == "create_task":
        title = str(args.get("title", "")).strip() or "untitled-task"
        staged = _stage({
            "proposal": True, "action": "create",
            "target": f"Tasks/{slugify(title)}.md", "title": title,
            "kind": "task", "status": "draft",
            "assignee": args.get("assignee", "[[Operator]]"),
            "runbook": args.get("runbook", ""),
            "agent": context.get("agent", "?"), "task": context.get("task", ""),
            "reason": str(args.get("reason", ""))[:400],
        }, str(args.get("body", "")))
        return f"Task proposal staged for review at {staged}."

    return f"Unknown tool: {name}"


DEFAULT_TOOLS = ["search_vault", "read_note", "propose_note", "create_task", "finish"]
