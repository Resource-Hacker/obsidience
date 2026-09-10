"""Feed destinations are existing Knowledge containers, with one Article policy."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import PurePosixPath

import yaml

from ..config import CONFIG
from ..knowledge.auto_curate import enabled, policy_for
from ..knowledge.vault import _NOTE_WRITE_LOCK, _atomic_write, is_folder_article, load_note, write_note


def destination(ref: str, notes: dict | None = None) -> dict:
    if not isinstance(ref, str) or not ref or ref.endswith(".md") or "\\" in ref:
        raise ValueError("Select an existing Knowledge node")
    path = PurePosixPath(ref)
    if (path.is_absolute() or str(path) != ref
            or any(part.startswith((".", "_", "@")) for part in path.parts)):
        raise ValueError("Select an exact accepted Knowledge node")
    note = notes.get(ref) if notes is not None else load_note(ref + ".md")
    if (not note or note.kind != "knowledge" or note.runtime_observation
            or not is_folder_article(note) or note.meta.get("article_status") == "deprecated"):
        raise ValueError("The destination must be an accepted Knowledge container node")
    return {"ref": note.ref, "title": note.title, "auto_curate": enabled(note.ref, notes),
            "auto_curate_supported": True, "available": True}


def destinations() -> list[dict]:
    rows = []
    for path in sorted(CONFIG.vault_dir.rglob("*.md")):
        if path.name != path.parent.name + ".md":
            continue
        ref = path.relative_to(CONFIG.vault_dir).with_suffix("").as_posix()
        try:
            rows.append(destination(ref))
        except (OSError, ValueError, yaml.YAMLError):
            continue
    return rows


@contextmanager
def bind_destination(ref: str):
    """Default an unset publication policy on owner Save, preserving explicit choices."""
    with _NOTE_WRITE_LOCK:
        node = destination(ref)
        note = load_note(ref + ".md")
        changed = policy_for(ref) is None
        before = (CONFIG.vault_dir / note.path).read_text() if changed else None
        try:
            if changed:
                write_note(note.path, {**note.meta, "auto_curate": True}, note.body)
                node["auto_curate"] = True
            yield node, changed
        except BaseException:
            if changed:
                _atomic_write(CONFIG.vault_dir / note.path, before)
            raise
