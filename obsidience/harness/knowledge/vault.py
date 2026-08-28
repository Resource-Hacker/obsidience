"""Vault access: parse notes (frontmatter + wikilinks), resolve links, write safely.

The vault is a plain Obsidian vault. Notes are identified by their vault-relative
path without extension ("Runbooks/create-a-runbook") and addressable by title or
basename via wikilinks ([[create-a-runbook]] / [[Runbooks/create-a-runbook|alias]]).
"""

from __future__ import annotations

import os
import re
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import frontmatter

from ..config import CONFIG

WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+)(?:#[^\]\|]*)?(?:\|[^\]]*)?\]\]")
WIKILINK_TOKEN_RE = re.compile(r"\[\[([^\]\|#]+)(#[^\]\|]*)?(\|[^\]]*)?\]\]")
SYSTEM_DIRS = ("_staging", "_archived")  # excluded from search/graph unless asked
SOURCE_DIRS = ("raw",)       # evidence, never graph knowledge even for system reads
IMMUTABLE_DIRS = SOURCE_DIRS
HIDDEN_DIRS = (".reader",)
PROTECTED_ROOTS = {
    "Agents", "Tools", "Skills", "Tasks", "Runbooks", "raw",
    "_staging", "_archived",
}
CHILD_FIELD_BY_KIND = {
    "task": "subtasks",
    "runbook": "subrunbooks",
    "skill": "subskills",
    "tool": "subtools",
}
HIERARCHY_FIELDS = tuple(CHILD_FIELD_BY_KIND.values())
_NOTE_WRITE_LOCK = threading.RLock()


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
        k = str(self.meta.get("kind") or "").strip().lower()
        if k in {"knowledge", "task", "runbook", "skill", "tool", "agent"}:
            return k
        top = self.path.split("/", 1)[0].lower()
        return {"runbooks": "runbook", "tasks": "task", "skills": "skill",
                "tools": "tool", "agents": "agent"}.get(top, "knowledge")

    @property
    def children(self) -> list[str]:
        """Ordered same-kind children for any of the four Library primitives."""
        value = self.meta.get(CHILD_FIELD_BY_KIND.get(self.kind, ""))
        values = value if isinstance(value, list) else [value] if value else []
        return [str(item) for item in values]

    def text(self) -> str:
        return f"# {self.title}\n\n{self.body}"


def normalize_article_body(body: str, title: str) -> str:
    """Remove only a redundant leading H1 that exactly repeats Article title.

    ``vault.read`` presents an Article-shaped ``# Title`` heading to the model,
    while the canonical title lives in frontmatter. Local models may copy that
    presentation heading into a complete update body; keeping it would render
    the title twice after approval.
    """
    match = re.match(r"^\s*#\s+([^\r\n]+)\r?\n(?:\r?\n)?", body)
    if not match:
        return body
    heading = " ".join(match.group(1).split()).casefold()
    canonical = " ".join(str(title).split()).casefold()
    return body[match.end():] if heading == canonical else body


def _title_of(path: Path, meta: dict) -> str:
    return str(meta.get("title") or path.stem)


def _extract_links(meta: dict, body: str) -> list[str]:
    links = WIKILINK_RE.findall(body)
    for key in (
        "runbook", *HIERARCHY_FIELDS, "skills", "tool", "assignee", "parent",
        "task", "links", "related_refs",
    ):
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
        if rel.parts and rel.parts[0] in SOURCE_DIRS:
            continue
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
    """Write a graph note (status, approved proposal, or transient observation)."""
    with _NOTE_WRITE_LOCK:
        p = CONFIG.vault_dir / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        post = frontmatter.Post(body, **meta)
        p.write_text(frontmatter.dumps(post) + "\n")
        return str(p)


def mutate_note_metadata(note: Note, mutate: Callable[[dict], None]) -> dict:
    """Atomically merge one system mutation into the note's latest metadata.

    Task execution and UI events can update the same ordinary graph Task at
    nearly the same time. Re-reading under the shared write lock preserves
    fields added after the scheduler took its original Note snapshot.
    """
    with _NOTE_WRITE_LOCK:
        current = load_note(note.path) or note
        meta = dict(current.meta)
        mutate(meta)
        write_note(current.path, meta, current.body)
        return meta


def _vault_relative(value: str, *, allow_root: bool = False) -> Path:
    """Validate an owner-supplied vault-relative path without resolving symlinks."""
    raw = value.strip().replace("\\", "/").strip("/")
    if not raw:
        if allow_root:
            return Path()
        raise ValueError("path required")
    path = Path(raw)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("invalid vault path")
    if any(part.startswith(".") for part in path.parts):
        raise ValueError("hidden vault paths cannot be moved")
    return path


def _replace_refs(value: str, mapping: dict[str, str]) -> str:
    """Rewrite exact note refs while retaining link aliases and headings."""
    folded = {old.casefold(): new for old, new in mapping.items()}

    def link(match: re.Match[str]) -> str:
        target = match.group(1).strip()
        markdown_suffix = target.lower().endswith(".md")
        lookup = target[:-3] if markdown_suffix else target
        replacement = folded.get(lookup.casefold())
        if not replacement:
            return match.group(0)
        if markdown_suffix:
            replacement += ".md"
        return f"[[{replacement}{match.group(2) or ''}{match.group(3) or ''}]]"

    rewritten = WIKILINK_TOKEN_RE.sub(link, value)
    stripped = rewritten.strip()
    base, marker, heading = stripped.partition("#")
    markdown_suffix = base.lower().endswith(".md")
    lookup = base[:-3] if markdown_suffix else base
    replacement = folded.get(lookup.casefold())
    if replacement:
        if markdown_suffix:
            replacement += ".md"
        replacement += f"#{heading}" if marker else ""
        leading = len(rewritten) - len(rewritten.lstrip())
        trailing = len(rewritten) - len(rewritten.rstrip())
        return f"{rewritten[:leading]}{replacement}{rewritten[len(rewritten) - trailing:] if trailing else ''}"
    return rewritten


def _rewrite_refs(value, mapping: dict[str, str]):
    if isinstance(value, str):
        return _replace_refs(value, mapping)
    if isinstance(value, list):
        return [_rewrite_refs(item, mapping) for item in value]
    if isinstance(value, tuple):
        return tuple(_rewrite_refs(item, mapping) for item in value)
    if isinstance(value, dict):
        return {key: _rewrite_refs(item, mapping) for key, item in value.items()}
    return value


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def move_vault_item(source: str, destination_parent: str, new_name: str | None = None) -> dict:
    """Move or rename one owner-managed article/folder and repair exact refs.

    Raw source bytes remain outside this owner-managed tree. All article
    transformations are prepared before the filesystem move and rolled back
    together if a write fails.
    """
    source_rel = _vault_relative(source)
    parent_rel = _vault_relative(destination_parent, allow_root=True)
    source_path = CONFIG.vault_dir / source_rel
    parent_path = CONFIG.vault_dir / parent_rel
    if not source_path.exists():
        raise ValueError(f"source not found: {source_rel}")
    if source_rel.parts[0] in (*IMMUTABLE_DIRS, *SYSTEM_DIRS, *HIDDEN_DIRS):
        raise ValueError("system and raw source items cannot be moved")
    if len(source_rel.parts) == 1 and source_rel.name in PROTECTED_ROOTS:
        raise ValueError("core vault roots cannot be moved or renamed")
    if not parent_path.is_dir():
        raise ValueError(f"destination folder not found: {parent_rel}")
    if parent_rel.parts and parent_rel.parts[0] in (*IMMUTABLE_DIRS, *SYSTEM_DIRS, *HIDDEN_DIRS):
        raise ValueError("items cannot be moved into a system or raw source folder")

    is_article = source_path.is_file()
    if is_article and source_path.suffix.lower() != ".md":
        raise ValueError("only Markdown articles can be moved")
    requested_name = str(new_name or "").strip()
    title = None
    if requested_name:
        if len(requested_name) > 160 or requested_name in {".", ".."} or "/" in requested_name or "\\" in requested_name:
            raise ValueError("invalid name")
        if is_article:
            destination_name = f"{slugify(requested_name)}.md"
            title = requested_name
        else:
            destination_name = requested_name
    else:
        destination_name = source_rel.name
    destination_rel = parent_rel / destination_name
    destination_path = CONFIG.vault_dir / destination_rel
    if destination_rel == source_rel:
        raise ValueError("item is already in that location")
    if not is_article and destination_rel.parts[:len(source_rel.parts)] == source_rel.parts:
        raise ValueError("a folder cannot be moved into itself")
    sibling_collision = next(
        (item for item in parent_path.iterdir()
         if item.name.casefold() == destination_name.casefold() and item != source_path),
        None,
    )
    if destination_path.exists() or sibling_collision:
        raise ValueError(f"destination already exists: {destination_rel}")

    source_files = [source_path] if is_article else sorted(source_path.rglob("*.md"))
    mapping: dict[str, str] = {
        str(source_rel.with_suffix("")): str(destination_rel.with_suffix("")),
    }
    moved_file_paths: dict[Path, Path] = {}
    for old_path in source_files:
        old_rel = old_path.relative_to(CONFIG.vault_dir)
        relative = Path(old_path.name) if is_article else old_path.relative_to(source_path)
        new_rel = destination_rel if is_article else destination_rel / relative
        mapping[str(old_rel.with_suffix(""))] = str(new_rel.with_suffix(""))
        moved_file_paths[old_path] = CONFIG.vault_dir / new_rel

    for old_path in source_files:
        note = load_note(old_path.relative_to(CONFIG.vault_dir))
        if note and note.kind == "task" and str(note.meta.get("status", "draft")) == "running":
            raise ValueError("a running task cannot be moved")

    originals: dict[Path, bytes] = {}
    writes: dict[Path, str] = {}
    for path in sorted(CONFIG.vault_dir.rglob("*.md")):
        rel = path.relative_to(CONFIG.vault_dir)
        if rel.parts and rel.parts[0] in (*IMMUTABLE_DIRS, *HIDDEN_DIRS):
            continue
        post = frontmatter.loads(path.read_text(encoding="utf-8"))
        meta = _rewrite_refs(dict(post.metadata or {}), mapping)
        body = _replace_refs(post.content, mapping)
        target = moved_file_paths.get(path, path)
        if title is not None and path == source_path:
            meta["title"] = title
        if meta != dict(post.metadata or {}) or body != post.content:
            originals[path] = path.read_bytes()
            writes[target] = frontmatter.dumps(frontmatter.Post(body, **meta)) + "\n"

    moved = False
    try:
        source_path.rename(destination_path)
        moved = True
        for path, content in writes.items():
            _atomic_write(path, content)
    except Exception:
        if moved and destination_path.exists() and not source_path.exists():
            destination_path.rename(source_path)
        for path, content in originals.items():
            _atomic_write(path, content.decode("utf-8"))
        raise

    return {
        "source": str(source_rel),
        "destination": str(destination_rel),
        "refs": mapping,
        "article": is_article,
    }


def update_status(note: Note, status: str, extra: dict | None = None) -> None:
    """System-attributed frontmatter update (task status projection)."""
    def mutate(meta: dict) -> None:
        meta["status"] = status
        meta["status_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        if extra:
            meta.update(extra)
        if status in {"blocked", "failed"}:
            if not meta.get("blocked_reason") and meta.get("summary"):
                meta["blocked_reason"] = meta["summary"]
        else:
            meta.pop("blocked_reason", None)

    mutate_note_metadata(note, mutate)


def slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return s[:80] or "note"
