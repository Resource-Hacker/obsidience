"""One accepted Article scope for Agent retrieval, Tools and graph views.

Checkout shares canonical Article identities, never copies or executable rights.
Only the owner API changes checkout. Model arguments cannot select an Agent.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import PurePosixPath

from .links import metadata_ref
from .vault import Note, Resolver, folder_article_path

MAX_CHECKOUTS = 128


def _accepted(note: Note) -> bool:
    return not any(part.startswith(("_", ".")) for part in note.path.split("/"))


def _within(note: Note, root: Note) -> bool:
    folder = PurePosixPath(root.path).parent
    is_index = PurePosixPath(root.path).stem.casefold() == folder.name.casefold()
    return note.ref == root.ref or (is_index and note.path.startswith(str(folder) + "/"))


def private_observation(note: Note, agent_ref: str) -> bool:
    if not note.ref.startswith("Agents/") or note.ref.startswith(agent_ref.rsplit("/", 1)[0] + "/"):
        return False
    return (any("observations" in part.casefold() for part in note.ref.split("/")[2:])
            or note.runtime_observation or note.meta.get("transient") is True)


def _roots(agent: Note, res: Resolver, field: str) -> list[Note]:
    values = agent.meta.get(field, [])
    if not isinstance(values, list) or len(values) > MAX_CHECKOUTS:
        raise ValueError(f"Agent {field} must contain at most {MAX_CHECKOUTS} exact Article references")
    found = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError("Knowledge checkout requires exact Article references")
        key = metadata_ref(value)
        note = res.by_ref.get(key.casefold())
        if (not note or note.kind != "knowledge" or not _accepted(note)
                or private_observation(note, agent.ref)):
            raise ValueError("Knowledge checkout contains an unavailable or private Article")
        if note.ref not in {item.ref for item in found}:
            found.append(note)
    return found


def knowledge_refs(agent: Note, res: Resolver) -> set[str]:
    """Evaluate current owner checkout, inherited scope and own Observations."""
    if not agent or agent.kind != "agent" or not _accepted(agent):
        raise ValueError("An accepted Agent identity is required")
    own = agent.ref.rsplit("/", 1)[0] + "/"
    roots = _roots(agent, res, "knowledge")
    exclusions = _roots(agent, res, "exclude_knowledge")
    visible = set()
    for note in res.by_ref.values():
        if note.kind != "knowledge" or not _accepted(note):
            continue
        if note.ref.startswith(own):
            visible.add(note.ref)
        elif (not private_observation(note, agent.ref)
                and any(_within(note, item) for item in roots)
                and not any(_within(note, item) for item in exclusions)):
            visible.add(note.ref)
    return visible


def knowledge_ancestry(res: Resolver) -> dict[str, list[str]]:
    """Derive structural ancestors from native folders and Agent graph scope.

    Folder ancestors are nearest-first, even across unauthored intermediate
    folders. Agent roots also contain their checked-out Knowledge, matching
    graph membership. This supplies no semantic link or executable authority.
    """
    notes = [note for note in res.by_ref.values() if note.kind in {"knowledge", "agent"} and _accepted(note)]
    ancestors: dict[str, list[str]] = {}
    for note in notes:
        parents = []
        for folder in PurePosixPath(note.path).parents:
            if str(folder) == ".":
                break
            parent = res.resolve(folder_article_path(folder))
            if (parent is not None and parent.ref != note.ref
                    and parent.kind in {"knowledge", "agent"} and _accepted(parent)):
                parents.append(parent.ref)
        ancestors[note.ref] = parents
    for agent in notes:
        if agent.kind != "agent":
            continue
        try:
            members = knowledge_refs(agent, res)
        except ValueError:
            # An invalid checkout has no membership, just as in navigation.
            continue
        for ref in members & ancestors.keys():
            if agent.ref != ref and agent.ref not in ancestors[ref]:
                ancestors[ref].append(agent.ref)
    return ancestors


def readable_refs(agent: Note, res: Resolver) -> set[str]:
    """Knowledge membership plus the exact Task-derived capability spine."""
    from .dependencies import agent_dependencies
    refs = knowledge_refs(agent, res) | {agent.ref}
    dependency = agent_dependencies(agent, res)
    for field in ("tasks", "runbooks", "skills", "tools"):
        refs.update(dependency[field])
    return refs


def execution_scope(context: dict, res: Resolver) -> tuple[Note, set[str]]:
    """Caller identity is a private executor binding, never a Tool argument."""
    key = context.get("_agent_ref")
    agent = res.by_ref.get(key.casefold()) if isinstance(key, str) else None
    if not agent or agent.kind != "agent":
        raise PermissionError("Agent scope is unavailable; no global Knowledge access was granted")
    try:
        return agent, readable_refs(agent, res)
    except ValueError as exc:
        raise PermissionError("Agent Knowledge checkout is invalid; access is closed") from exc


def revision(agent: Note) -> str:
    return hashlib.sha256(json.dumps({"ref": agent.ref, "meta": agent.meta, "body": agent.body},
        sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def checkout_state(note: Note, agent: Note, res: Resolver) -> dict:
    own = note.ref.startswith(agent.ref.rsplit("/", 1)[0] + "/")
    private = private_observation(note, agent.ref)
    roots = _roots(agent, res, "knowledge")
    excluded = _roots(agent, res, "exclude_knowledge")
    direct = any(item.ref == note.ref for item in roots)
    inherited_from = [item.ref for item in roots if item.ref != note.ref and _within(note, item)]
    exclusion = any(_within(note, item) for item in excluded)
    partial = any(item.ref != note.ref and _within(item, note) for item in [*roots, *excluded])
    return {"partial": partial, "ref": note.ref, "kind": note.kind, "agent_ref": agent.ref,
            "checked": own or (not private and not exclusion and (direct or bool(inherited_from))),
            "direct": direct, "inherited": bool(inherited_from), "inherited_from": inherited_from,
            "excluded": exclusion, "owned": own, "private": private,
            "editable": note.kind == "knowledge" and not own and not private,
            "revision": revision(agent)}


def assert_proposal_scope(target: str, context: dict, res: Resolver) -> None:
    """Knowledge checkout grants access, not another Agent's Observation writer."""
    agent, allowed = execution_scope(context, res)
    key = metadata_ref(target)
    if not key or any(part.startswith(("_", ".")) for part in key.split("/")):
        raise PermissionError("Proposal target is outside the accepted Agent scope")
    existing = res.by_ref.get(key.casefold())
    candidate = existing or Note(key + ".md", "", {"kind": "knowledge"}, "")
    if private_observation(candidate, agent.ref):
        raise PermissionError("Each Agent owns its own Observations")
    if existing and existing.ref not in allowed:
        raise PermissionError("Proposal target is not checked out to this Agent")
    definitions = key.split("/", 1)[0] in {"Tasks", "Runbooks", "Skills", "Tools"}
    if not existing and not definitions:
        own = agent.ref.rsplit("/", 1)[0] + "/"
        if not key.startswith(own) and not any(_within(candidate, item) for item in _roots(agent, res, "knowledge")):
            raise PermissionError("New Knowledge must be inside an owned or checked-out branch")
