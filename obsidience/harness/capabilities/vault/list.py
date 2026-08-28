"""Adapter for ``vault.list``."""

from __future__ import annotations


def execute(args: dict, context: dict) -> str:
    del context
    from obsidience.harness.knowledge.vault import iter_notes

    folder = str((args or {}).get("folder", "")).strip().strip("/")
    parts = folder.split("/") if folder else []
    safe_roots = {"Tasks", "Runbooks", "Skills", "Tools", "Agents"}
    if (
        not parts
        or parts[0] not in safe_roots
        or any(not part or part in {".", ".."} or part.startswith(".") for part in parts)
    ):
        return (
            "Invalid folder. Use Tasks, Runbooks, Skills, Tools, or Agents, "
            "or a safe subfolder beneath one of them."
        )
    rows = [note for note in iter_notes() if note.ref.startswith(folder + "/")]
    if not rows:
        return f"{folder}/ is empty."
    return "\n".join(f"- [[{note.ref}]] — {note.title}" for note in rows[:60])
