"""Knowledge graph, Reader Articles and the accepted Vault tree."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ....execution import activity as knowledge_activity
from ....knowledge import projection, retrieval, system as system_knowledge
from ....knowledge.index import INDEX
from ....knowledge.vault import iter_notes, load_note, resolver, write_note

router = APIRouter()


def _base_article(ref: str):
    try:
        return projection.base_article(ref)
    except projection.NotFound as cause:
        raise HTTPException(404, str(cause)) from cause


@router.get("/api/graph")
def graph():
    return projection.graph()


@router.get("/api/articles/{ref:path}")
def get_article(ref: str, graph_id: str = "", activity: bool = False):
    try:
        doc = projection.agent_article(ref, graph_id)
    except projection.NotFound as cause:
        raise HTTPException(404, str(cause)) from cause
    if activity:
        knowledge_activity.emit_operation("read", "returned", [str(doc["ref"])],
            label="Reading memory" if ref.startswith("@memory/") else "Reading · " + str(doc["title"]),
            graph_id="memory:" + ref.split("/", 2)[1] if ref.startswith("@memory/") else graph_id or "*")
    return doc


@router.put("/api/articles/{ref:path}/auto-curate")
def set_article_auto_curate(ref: str, payload: dict):
    """Owner permission, inherited by children; Task triggers stay independent."""
    enabled = payload.get("enabled")
    if not isinstance(enabled, bool):
        raise HTTPException(400, "enabled must be boolean")
    doc = projection.apply_reader_override(_base_article(ref))
    if not projection.auto_curate_supported(ref, doc):
        raise HTTPException(400, "Auto-curate applies to Knowledge branches, not capability definitions or checkouts")
    projection.set_auto_curate_tag(ref, doc, enabled)
    INDEX.sync()
    knowledge_activity.emit_operation("edit", "completed", [str(doc["ref"])],
        label="Auto-curate enabled" if enabled else "Auto-curate disabled", refresh=True)
    return {"article": ref, "enabled": enabled, "task": None}


@router.patch("/api/articles/{ref:path}")
def update_article(ref: str, payload: dict):
    try:
        return _update_article(ref, payload)
    except HTTPException:
        knowledge_activity.emit_operation("edit", "rejected", [ref], label="Edit rejected")
        raise


def _update_article(ref: str, payload: dict):
    """Direct owner edit for authored Articles and editable navigation nodes."""
    title = str(payload.get("title", "")).strip()
    body = str(payload.get("body", ""))
    if not title:
        raise HTTPException(400, "title required")
    if len(title) > 160:
        raise HTTPException(400, "title is too long")
    if len(body) > 200_000:
        raise HTTPException(400, "article body is too large")

    base = _base_article(ref)
    target_ref = str(base["ref"])
    if target_ref.startswith("@memory/"):
        raise HTTPException(409, "Hindsight owns this observation; durable changes are Alexandria recommendations")
    try:
        system_knowledge.assert_system_article_writable(target_ref)
    except ValueError as cause:
        raise HTTPException(409, str(cause)) from cause
    note = None if target_ref.startswith("@") else load_note(target_ref + ".md")
    if note:
        if note.runtime_observation:
            raise HTTPException(409, "runtime Observations are lifecycle-owned")
        if note.kind == "task" and str(note.meta.get("status", "draft")) == "running":
            raise HTTPException(409, "cannot edit a running task")
        meta = dict(note.meta)
        meta["title"] = title
        if note.kind == "agent":
            meta["name"] = title
        write_note(note.path, meta, body)
        saved_ref = note.ref
    else:
        if not target_ref.startswith("@"):
            raise HTTPException(404, f"article not found: {ref}")
        write_note(
            projection.reader_override_path(target_ref),
            {
                "title": title,
                "kind": str(base.get("kind", "note")),
                "reader_ref": target_ref,
                "owner_maintained": True,
            },
            body,
        )
        saved_ref = target_ref
    INDEX.sync()
    knowledge_activity.emit_operation("edit", "completed", [saved_ref],
        label="Saved · " + title, refresh=True)
    return {"article": saved_ref, "updated": True}


@router.get("/api/files")
def files():
    """Accepted vault tree for the Reader's Obsidian-style explorer."""
    return [
        {"ref": note.ref, "path": note.path, "title": note.title, "kind": note.kind}
        for note in iter_notes()
    ]


@router.get("/api/notes/{ref:path}")
def get_note(ref: str):
    note = load_note(ref + ".md") or resolver().resolve(ref)
    if not note:
        raise HTTPException(404, f"note not found: {ref}")
    return projection.note_doc(note)


@router.get("/api/search")
def search(q: str):
    return retrieval.search(q)
