"""Adapter for ``vault.list``."""

from __future__ import annotations


def execute(args: dict, context: dict) -> str:
    from obsidience.harness.knowledge.vault import iter_notes, Resolver
    from obsidience.harness.knowledge.scope import execution_scope

    notes = iter_notes()
    try:
        _agent, allowed = execution_scope(context, Resolver(notes))
    except PermissionError as exc:
        return str(exc)

    folder = str((args or {}).get("folder", "")).strip().strip("/")
    parts = folder.split("/") if folder else []
    if (
        any(not part or part in {".", ".."} or part.startswith((".", "_")) for part in parts)
        or "\\" in folder
    ):
        return "Invalid folder. Use an accepted Knowledge or Library folder; private paths are excluded."
    offset = args.get("offset", 0)
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        return "Invalid offset: use a nonnegative row offset."
    rows = sorted((note for note in notes
                   if note.ref in allowed and (not folder or note.ref.startswith(folder + "/"))
                   and not any(part.startswith(("_", ".")) for part in note.ref.split("/"))),
                  key=lambda note: note.ref)
    if not rows:
        return f"{folder}/ is empty."
    end = min(offset + 60, len(rows))
    if offset > len(rows):
        return f"Invalid offset: folder has {len(rows)} Articles."
    continuation = f"Next offset: {end}" if end < len(rows) else "End of folder."
    return f"Rows {offset}-{end} of {len(rows)}. {continuation}\n" + "\n".join(
        f"- [[{note.ref}]] — {note.title}" for note in rows[offset:end])
