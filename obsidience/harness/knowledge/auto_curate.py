"""Owner-authored Auto-curate permission, inherited through Article containment.

This is permission to publish, not a Task trigger or evidence of truth. The
nearest explicit boolean wins, including false. An Agent Brain scopes its own
knowledge folder, never the shared Library articles checked out from elsewhere.
"""

from pathlib import PurePosixPath

from .vault import Note, folder_article_path, load_note


def selection(note: Note | None) -> bool | None:
    if note is None:
        return None
    value = note.meta.get("auto_curate")
    if isinstance(value, bool):
        return value
    # Read old accepted selections without inventing a second policy store.
    if "auto-curate" in (note.meta.get("tags") or []):
        return True
    return None


def policy_for(target: str, notes: dict[str, Note] | None = None) -> Note | None:
    path = PurePosixPath(target.removesuffix(".md"))
    if path.is_absolute() or any(part.startswith((".", "_", "@")) for part in path.parts):
        return None

    def read(ref: str) -> Note | None:
        return notes.get(ref) if notes is not None else load_note(ref + ".md")

    candidates = [str(path)]
    # A target may be an existing Article or a not-yet-populated folder.
    for folder in (path, *path.parents):
        if str(folder) == ".":
            break
        candidates.append(folder_article_path(str(folder)).removesuffix(".md"))
        if len(folder.parts) == 2 and folder.parts[0] == "Agents":
            candidates.append(str(folder / folder.name))
    for ref in dict.fromkeys(candidates):
        note = read(ref)
        if selection(note) is not None:
            return note
    return None


def enabled(target: str, notes: dict[str, Note] | None = None) -> bool:
    return selection(policy_for(target, notes)) is True
