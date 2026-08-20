"""Vault access: parse notes (frontmatter + wikilinks), resolve links, write safely.

The vault is a plain Obsidian vault. Notes are identified by their vault-relative
path without extension ("Runbooks/create-a-runbook") and addressable by title or
basename via wikilinks ([[create-a-runbook]] / [[Runbooks/create-a-runbook|alias]]).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter

from .config import CONFIG

WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+)(?:#[^\]\|]*)?(?:\|[^\]]*)?\]\]")
SYSTEM_DIRS = ("_staging",)  # excluded from search/graph unless asked


@dataclass
class Note:
    path: str                     # vault-relative, with .md
    title: str
    meta: dict
    body: str
    mtime: float = 0.0
    links: list[str] = field(default_factory=list)   # raw wikilink targets

    @property
    def ref(self) -> str:
        return self.path[:-3] if self.path.endswith(".md") else self.path

    @property
    def kind(self) -> str:
        k = self.meta.get("kind")
        if k:
            return str(k)
        top = self.path.split("/", 1)[0].lower()
        return {"runbooks": "runbook", "tasks": "task", "skills": "skill",
                "tools": "tool", "receipts": "receipt", "agents": "agent"}.get(top, "note")

    def text(self) -> str:
        return f"# {self.title}\n\n{self.body}"


def _title_of(path: Path, meta: dict) -> str:
    return str(meta.get("title") or path.stem)


def _extract_links(meta: dict, body: str) -> list[str]:
    links = WIKILINK_RE.findall(body)
    for key in ("runbook", "subtasks", "skills", "assignee", "parent", "links"):
        val = meta.get(key)
        vals = val if isinstance(val, list) else [val] if val else []
        for v in vals:
            if isinstance(v, str):
                links.extend(WIKILINK_RE.findall(v) or ([v] if "/" in v or v else []))
    return [l.strip() for l in links if l and l.strip()]


def load_note(rel_path: str | Path) -> Note | None:
    p = CONFIG.vault_dir / rel_path
    if not p.exists() or p.suffix != ".md":
        return None
    post = frontmatter.load(p)
    meta = dict(post.metadata or {})
    body = post.content
    return Note(
        path=str(Path(rel_path)), title=_title_of(p, meta), meta=meta, body=body,
        mtime=p.stat().st_mtime, links=_extract_links(meta, body),
    )


def iter_notes(include_system: bool = False) -> list[Note]:
    notes = []
    for p in sorted(CONFIG.vault_dir.rglob("*.md")):
        rel = p.relative_to(CONFIG.vault_dir)
        if not include_system and rel.parts and rel.parts[0] in SYSTEM_DIRS:
            continue
        if any(part.startswith(".") for part in rel.parts):
            continue
        note = load_note(rel)
        if note:
            notes.append(note)
    return notes


class Resolver:
    """Resolve wikilink targets to notes (exact path > title > basename)."""

    def __init__(self, notes: list[Note]):
        self.by_ref = {n.ref.lower(): n for n in notes}
        self.by_title: dict[str, Note] = {}
        self.by_base: dict[str, Note] = {}
        for n in notes:
            self.by_title.setdefault(n.title.lower(), n)
            self.by_base.setdefault(Path(n.ref).name.lower(), n)

    def resolve(self, target: str) -> Note | None:
        t = target.strip().strip("[]").split("|")[0].split("#")[0].strip().lower()
        if t.endswith(".md"):
            t = t[:-3]
        return (self.by_ref.get(t) or self.by_title.get(t) or self.by_base.get(t)
                or self.by_base.get(t.rsplit("/", 1)[-1]))


def resolver() -> Resolver:
    return Resolver(iter_notes(include_system=True))


def write_note(rel_path: str, meta: dict, body: str) -> str:
    """Write a note (harness/system writes only — receipts, status fields, approved proposals)."""
    p = CONFIG.vault_dir / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    post = frontmatter.Post(body, **meta)
    p.write_text(frontmatter.dumps(post) + "\n")
    return str(p)


def update_status(note: Note, status: str, extra: dict | None = None) -> None:
    """System-attributed frontmatter update (task status projection)."""
    meta = dict(note.meta)
    meta["status"] = status
    meta["status_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    if extra:
        meta.update(extra)
    write_note(note.path, meta, note.body)


def slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return s[:80] or "note"
