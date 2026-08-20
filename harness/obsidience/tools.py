"""The tool registry. Tools are the executable capabilities; Tool notes in
`Tools/` document and bind them (`binding: builtin:<name>`). Authorization is
closed: a session gets exactly the tools its skills/runbook grant, plus
`task.complete`.
"""

from __future__ import annotations

import time

from . import retrieval
from .vault import CHILD_FIELD_BY_KIND, HIERARCHY_FIELDS, load_note, resolver, slugify, write_note

# Fallback one-liners; the authoritative documentation lives in Tools/ notes.
BUILTIN_DOCS = {
    "vault.list": 'Deterministically list notes in a folder. args: {"folder": "Tasks|Runbooks|Skills|Tools|Agent|Agents|Sources"}',
    "vault.validate": "Deterministically validate every load-bearing frontmatter edge (primitive children, task runbook, runbook skills, skill/runbook tools) across the vault. args: {} — returns a broken-edge report.",
    "vault.search": 'Hybrid search over the vault. args: {"query": str}',
    "vault.read": 'Read a full note. args: {"ref": "Folder/name or [[wikilink]]"}',
    "vault.propose": ('Stage a note change for owner review (never writes the vault directly). '
                      'args: {"action": "create|update", "target": "Folder/name.md", "title": str, '
                      '"body": str, "reason": str}'),
    "task.create": ('Propose a new task (staged for review). args: {"title": str, "runbook": '
                    '"[[Runbooks/...]]" (leaf) OR "subtasks": ["[[Tasks/...]]", ...], "body": str, "reason": str}'),
    "task.complete": 'End the session. args: {"status": "completed|failed|review", "summary": str}',
}

ALWAYS_ALLOWED = ("task.complete",)


def _link_leaf(value: str) -> str:
    return value.strip().strip("[]").split("|", 1)[0].split("#", 1)[0].rsplit("/", 1)[-1]


def tool_doc(name: str) -> str:
    """Prefer the Tool note's body (the authored contract); fall back to builtin."""
    note = load_note(f"Tools/{name}.md")
    if note and note.body.strip():
        return note.body.strip()[:600]
    return BUILTIN_DOCS.get(name, "(undocumented)")


def tool_docs(allowed: list[str]) -> str:
    lines = [f"### {name}\n{tool_doc(name)}" for name in allowed]
    return "## Authorized tools\n\n" + "\n\n".join(lines)


def _stage(meta: dict, body: str) -> str:
    ts = time.strftime("%Y%m%d-%H%M%S")
    fname = f"_staging/{ts}-{slugify(meta.get('title') or meta.get('target') or 'proposal')}.md"
    meta.setdefault("proposed_at", time.strftime("%Y-%m-%dT%H:%M:%S"))
    write_note(fname, meta, body)
    return fname


def run_tool(name: str, args: dict, context: dict) -> str:
    """Execute a registry tool; return the observation fed back to the model."""
    args = args or {}
    if name == "vault.list":
        from .vault import iter_notes
        folder = str(args.get("folder", "")).strip().strip("/")
        if folder not in ("Tasks", "Runbooks", "Skills", "Tools", "Agent", "Agents", "Sources"):
            return "Invalid folder. One of: Tasks, Runbooks, Skills, Tools, Agent, Sources."
        rows = [n for n in iter_notes() if n.ref.startswith(folder + "/")]
        if not rows:
            return f"{folder}/ is empty."
        return "\n".join(f"- [[{n.ref}]] — {n.title}" for n in rows[:60])

    if name == "vault.validate":
        from .vault import iter_notes
        res = resolver()
        notes = iter_notes()
        broken, checked = [], 0
        for n in notes:
            if n.ref.startswith("Receipts/"):
                continue
            for field in ("runbook", *HIERARCHY_FIELDS, "skills"):
                val = n.meta.get(field)
                for ref in (val if isinstance(val, list) else [val] if val else []):
                    checked += 1
                    target = res.resolve(str(ref))
                    if not target:
                        broken.append(f"- [[{n.ref}]] {field}: {ref} (unresolved)")
                    elif field == CHILD_FIELD_BY_KIND.get(n.kind) and target.kind != n.kind:
                        broken.append(
                            f"- [[{n.ref}]] {field}: {ref} (expected {n.kind}, got {target.kind})")
            for t in (n.meta.get("tools") or []) if n.kind in ("skill", "runbook") else []:
                checked += 1
                target = res.resolve(str(t))
                if target and target.kind != "tool":
                    broken.append(f"- [[{n.ref}]] tools: {t} (expected tool, got {target.kind})")
                elif not target and _link_leaf(str(t)) not in REGISTRY:
                    broken.append(f"- [[{n.ref}]] tools: {t} (no registry binding)")
        for tool in (note for note in notes if note.kind == "tool" and not note.children):
            checked += 1
            binding = str(tool.meta.get("binding", "")).removeprefix("builtin:")
            if binding not in REGISTRY:
                broken.append(f"- [[{tool.ref}]] binding: {binding or '(missing)'} (no registry binding)")
        reported_cycles: set[frozenset[str]] = set()
        for kind in CHILD_FIELD_BY_KIND:
            visited: set[str] = set()
            active: list[str] = []

            def visit(note):
                if note.ref in active:
                    cycle = active[active.index(note.ref):] + [note.ref]
                    key = frozenset(cycle)
                    if key not in reported_cycles:
                        reported_cycles.add(key)
                        broken.append(f"- {kind} hierarchy cycle: {' -> '.join(cycle)}")
                    return
                if note.ref in visited:
                    return
                active.append(note.ref)
                for raw in note.children:
                    child = res.resolve(raw)
                    if child and child.kind == kind:
                        visit(child)
                active.pop()
                visited.add(note.ref)

            for root in (note for note in notes if note.kind == kind):
                visit(root)
        if not broken:
            return f"All {checked} load-bearing edges resolve. No broken references."
        return f"{checked} edges checked, {len(broken)} broken:\n" + "\n".join(broken[:30])

    if name == "vault.search":
        hits = retrieval.search(str(args.get("query", ""))[:300])
        if not hits:
            return "No results."
        return "\n".join(f"- [[{h['ref']}]] ({h['kind']}) — {h['snippet'][:160]}" for h in hits[:10])

    if name == "vault.read":
        ref = str(args.get("ref", "")).strip()
        note = resolver().resolve(ref) or load_note(ref if ref.endswith(".md") else ref + ".md")
        if not note:
            return f"Note not found: {ref}"
        return note.text()[:8000]

    if name == "vault.propose":
        target = str(args.get("target", "")).strip()
        if not target or target.startswith("_") or ".." in target:
            return "Invalid target path."
        if not target.endswith(".md"):
            target += ".md"
        staged = _stage({
            "proposal": True, "action": args.get("action", "create"), "target": target,
            "title": args.get("title") or target, "agent": context.get("agent", "interpreter"),
            "task": context.get("task", ""), "reason": str(args.get("reason", ""))[:400],
        }, str(args.get("body", "")))
        return f"Proposal staged for owner review at {staged}."

    if name == "task.create":
        title = str(args.get("title", "")).strip() or "untitled-task"
        meta = {
            "proposal": True, "action": "create",
            "target": f"Tasks/{slugify(title)}.md", "title": title,
            "kind": "task", "status": "draft",
            "agent": context.get("agent", "interpreter"), "task": context.get("task", ""),
            "reason": str(args.get("reason", ""))[:400],
        }
        if args.get("subtasks"):
            meta["subtasks"] = [str(s) for s in args["subtasks"]][:9]
        if args.get("runbook"):
            meta["runbook"] = str(args["runbook"])
        staged = _stage(meta, str(args.get("body", "")))
        return f"Task proposal staged for review at {staged}."

    return f"Unknown tool: {name}"


REGISTRY = tuple(BUILTIN_DOCS)
