"""Agent checkouts: Source-tree scopes, Knowledge scope and Task assignments.

One lock serializes every checkout mutation of an Agent identity Article.
"""

from __future__ import annotations

from dataclasses import replace
import threading

from fastapi import APIRouter, HTTPException

from ....execution import activity as knowledge_activity
from ....execution.assignments import ensure_task_runbook
from ....knowledge import source
from ....knowledge.dependencies import agent_dependencies, dependency_resolver
from ....knowledge.index import INDEX
from ....knowledge.projection import CHECKOUT_AGENTS, CHECKOUT_FIELDS
from ....knowledge.vault import Note, mutate_note_metadata, resolver, write_note

router = APIRouter()
SOURCE_SCOPE_FIELD = "source_trees"
_CHECKOUT_LOCK = threading.RLock()


def _link_values(value) -> list[str]:
    if not value:
        return []
    return [str(item) for item in (value if isinstance(value, list) else [value])]


@router.get("/api/source-checkouts")
def source_checkouts():
    """Return independent Source-tree Knowledge scopes for all principals."""
    res = resolver()
    assignments = []
    for agent, identity_ref in CHECKOUT_AGENTS.items():
        identity = res.resolve(identity_ref)
        if not identity:
            continue
        for raw in _link_values(identity.meta.get(SOURCE_SCOPE_FIELD)):
            try:
                tree = source.normalize_source_tree(raw)
            except source.SourceError:
                continue
            assignments.append({"agent": agent, "tree": tree})
    return {"assignments": assignments}


@router.put("/api/source-checkouts/{tree:path}")
def set_source_checkout(tree: str, payload: dict):
    """Assign one Source subtree as bounded Knowledge context for one Agent."""
    agent = str(payload.get("agent") or "").strip().lower()
    if agent not in CHECKOUT_AGENTS:
        raise HTTPException(400, f"unknown checkout agent: {agent or '(empty)'}")
    checked_out = payload.get("checked_out")
    if not isinstance(checked_out, bool):
        raise HTTPException(400, "checked_out must be boolean")
    try:
        normalized = source.normalize_source_tree(tree)
        if not source.source_tree_exists(normalized, folder_only=True):
            raise source.SourceError("source checkout must name an existing Source folder")
    except source.SourceError as cause:
        raise HTTPException(404, str(cause)) from cause

    with _CHECKOUT_LOCK:
        identity = resolver().resolve(CHECKOUT_AGENTS[agent])
        if not identity:
            raise HTTPException(500, f"checkout identity missing: {CHECKOUT_AGENTS[agent]}")

        changed = False

        def mutate(meta: dict) -> None:
            nonlocal changed
            current = []
            for raw in _link_values(meta.get(SOURCE_SCOPE_FIELD)):
                try:
                    candidate = source.normalize_source_tree(raw)
                except source.SourceError:
                    continue
                if candidate not in current:
                    current.append(candidate)
            present = normalized in current
            changed = present != checked_out
            if checked_out and not present:
                if len(current) >= source.MAX_SOURCE_TREE_SCOPES:
                    raise source.SourceError("Agent Source checkout limit reached")
                current.append(normalized)
            elif not checked_out and present:
                current.remove(normalized)
            if current:
                meta[SOURCE_SCOPE_FIELD] = sorted(current)
            else:
                meta.pop(SOURCE_SCOPE_FIELD, None)

        try:
            mutate_note_metadata(identity, mutate)
        except source.SourceError as cause:
            raise HTTPException(409, str(cause)) from cause
        INDEX.sync()
        if changed:
            knowledge_activity.emit("graph_changed", [identity.ref])
    return {
        "agent": agent,
        "tree": normalized,
        "checked_out": checked_out,
        "checkout_changed": changed,
        "article_refs": source.article_refs_for_trees([normalized]),
    }


def _assignment_row(agent: str, identity: Note, task: Note, res) -> dict:
    selected = _link_values(identity.meta.get("tasks"))
    remaining = [raw for raw in selected
                 if not ((target := res.resolve(raw)) and target.ref == task.ref)]
    direct = len(remaining) != len(selected)
    without_direct = replace(identity, meta={**identity.meta, "tasks": remaining})
    inherited = task.ref in agent_dependencies(without_direct, res)["tasks"]
    return {"agent": agent, "ref": task.ref, "kind": "task",
            "direct": direct, "inherited": inherited}


@router.get("/api/library/assignments")
def library_assignments():
    """Task assignments and their read-only shared Library dependencies."""
    res = dependency_resolver(resolver())
    from ....knowledge.scope import checkout_state, revision
    assignments, dependencies, knowledge, revisions = [], [], [], {}
    for agent, identity_ref in CHECKOUT_AGENTS.items():
        identity = res.resolve(identity_ref)
        if not identity:
            continue
        revisions[agent] = revision(identity)
        try:
            knowledge.extend({**checkout_state(note, identity, res), "agent": agent}
                             for note in res.by_ref.values() if note.kind == "knowledge")
        except ValueError as exc:
            knowledge.append({"agent": agent, "error": str(exc)})
        effective = agent_dependencies(identity, res)
        for kind, field in CHECKOUT_FIELDS.items():
            for ref in effective[field]:
                dependencies.append({"agent": agent, "ref": ref, "kind": kind})
                if kind == "task" and (task := res.resolve(ref)) and task.kind == "task":
                    row = _assignment_row(agent, identity, task, res)
                    if not row["direct"] and not row["inherited"]:
                        row["inherited"] = True  # Parent/descendant Task scope.
                    assignments.append(row)
    return {"assignments": assignments, "dependencies": dependencies,
            "knowledge": knowledge, "revisions": revisions}


def _set_knowledge_assignment(agent: str, identity: Note, note: Note, checked: bool, res) -> dict:
    """Owner mutation of exact Knowledge scope, never a capability grant."""
    from ....knowledge.scope import MAX_CHECKOUTS, checkout_state, revision, _within, _roots
    try:
        before = checkout_state(note, identity, res)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    if not before["editable"]:
        raise HTTPException(400, "Own Articles remain owned; another Agent's Observations cannot be checked out")
    # Toggling a branch is one subtree operation, not a hidden collection of
    # descendant grants that survive unchecking their parent.
    selected = [item for item in _roots(identity, res, "knowledge") if not _within(item, note)]
    excluded = [item for item in _roots(identity, res, "exclude_knowledge") if not _within(item, note)]
    if checked:
        # The most specific entry decides (knowledge.scope._admitted): an exact
        # checkout opens one Article inside an excluded parent branch.
        if not any(_within(note, item) for item in selected) or any(_within(note, item) for item in excluded):
            selected.append(note)
    elif any(_within(note, item) for item in selected):
        excluded.append(note)
    if max(len(selected), len(excluded)) > MAX_CHECKOUTS:
        raise HTTPException(400, "Knowledge checkout limit reached")
    meta = {**identity.meta, "knowledge": [f"[[{item.ref}]]" for item in selected],
            "exclude_knowledge": [f"[[{item.ref}]]" for item in excluded]}
    changed = meta != identity.meta
    if changed:
        write_note(identity.path, meta, identity.body)
        INDEX.sync()
        knowledge_activity.emit("graph_changed", [identity.ref, note.ref])
    updated = replace(identity, meta=meta)
    return {**checkout_state(note, updated, res), "agent": agent, "assigned": checked,
            "assignment_changed": changed, "revision": revision(updated)}


@router.put("/api/library/assignments/{ref:path}")
def set_library_assignment(ref: str, payload: dict):
    """Assign one accepted Task; its dependencies are never separate grants."""
    agent = str(payload.get("agent") or "").strip().lower()
    if agent not in CHECKOUT_AGENTS:
        raise HTTPException(400, f"unknown agent: {agent or '(empty)'}")
    assigned = payload.get("assigned")
    if not isinstance(assigned, bool):
        raise HTTPException(400, "assigned must be boolean")
    from ....knowledge.vault import NOTE_WRITE_LOCK
    with _CHECKOUT_LOCK, NOTE_WRITE_LOCK:
        res = dependency_resolver(resolver())
        identity = res.resolve(CHECKOUT_AGENTS[agent])
        if not identity:
            raise HTTPException(500, "Agent Article missing")
        from ....knowledge.scope import revision
        expected = payload.get("expected_revision")
        if expected is not None and expected != revision(identity):
            raise HTTPException(409, "Agent checkout changed; refresh before assigning")
        task = res.resolve(ref)
        if task and task.kind == "knowledge":
            if expected is None:
                raise HTTPException(409, "Knowledge checkout requires expected_revision")
            return _set_knowledge_assignment(agent, identity, task, assigned, res)
        if not task or task.kind != "task":
            raise HTTPException(400, "Only an accepted Task Article can be assigned")
        identity = res.resolve(CHECKOUT_AGENTS[agent])
        if not identity:
            raise HTTPException(500, f"Agent Article missing: {CHECKOUT_AGENTS[agent]}")
        before = _assignment_row(agent, identity, task, res)
        retained = [raw for raw in _link_values(identity.meta.get("tasks"))
                    if not ((target := res.resolve(raw)) and target.ref == task.ref)]
        if assigned:
            retained.append(f"[[{task.ref}]]")
        meta = dict(identity.meta)
        if retained:
            meta["tasks"] = retained
        else:
            meta.pop("tasks", None)
        changed = before["direct"] != assigned
        if changed:
            write_note(identity.path, meta, identity.body)
        activation = ensure_task_runbook(task, res, agent_ref=identity.ref) if assigned else {}
        if changed:
            INDEX.sync()
            knowledge_activity.emit("graph_changed", [identity.ref, task.ref])
        row = _assignment_row(agent, replace(identity, meta=meta), task, res)
        return {
            **row, "assigned": assigned or row["inherited"],
            "assignment_changed": changed,
            "activated_task": activation.get("generator_task"),
            "activation_state": activation.get("status"),
            "activation_error": activation.get("error"),
        }
