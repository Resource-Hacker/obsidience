"""Vault access: parse notes (frontmatter + wikilinks), resolve links, write safely.

The vault is a plain Obsidian vault. Notes are identified by their vault-relative
path without extension ("Runbooks/create-a-runbook") and addressable by title or
basename via wikilinks ([[create-a-runbook]] / [[Runbooks/create-a-runbook|alias]]).
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

from ..config import CONFIG
from . import format as article_format
from .links import body_links, canonical_body

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
        return str(self.meta.get("kind") or "knowledge")

    @property
    def children(self) -> list[str]:
        """Ordered same-kind children for any of the four Library primitives."""
        value = self.meta.get(CHILD_FIELD_BY_KIND.get(self.kind, ""))
        values = value if isinstance(value, list) else [value] if value else []
        return [str(item) for item in values]

    def text(self) -> str:
        return f"# {self.title}\n\n{self.body}"

    @property
    def runtime_observation(self) -> bool:
        """Conversation projections are lifecycle-owned, not wiki-edit targets."""
        return self.meta.get("immediate") is True or self.meta.get("temporary") is True


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


def folder_article_path(folder: str | Path) -> str:
    """An authored folder condensation is an ordinary, same-named Article."""
    path = Path(folder)
    return str(path / (path.name + ".md"))


def is_folder_article(note: Note) -> bool:
    return note.path == folder_article_path(Path(note.path).parent)


def _extract_links(meta: dict, body: str, path: str = "") -> list[str]:
    links = body_links(body, path)
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


@lru_cache(maxsize=512)
def _parsed_note(text: str, path: str) -> tuple[dict, str, tuple[str, ...]]:
    """Cache parsing only, keyed by current bytes and link-resolution path.

    Callers always reread the file and copy mutable output. Task state, access,
    lifecycle and timestamps are projected fresh, never cached here.
    """
    meta, body = article_format.loads(text)
    return meta, body, tuple(_extract_links(meta, body, path))


def load_note(rel_path: str | Path) -> Note | None:
    with _NOTE_WRITE_LOCK:
        p = CONFIG.vault_dir / rel_path
        if not p.exists() or p.suffix != ".md":
            return None
        if p.name.lower() in {"index.md", "log.md"}:
            return None  # OKF listings/history are never Articles.
        text = p.read_text(encoding="utf-8")
        # Bound retained input as well as entry count; oversized Articles still
        # parse normally, without evicting the ordinary working set.
        parse = _parsed_note if len(text) <= 128 * 1024 else _parsed_note.__wrapped__
        authored, body, links = parse(text, str(rel_path))
        meta = deepcopy(authored)
        if meta.get("kind") == "task" and not str(rel_path).startswith(("_", ".")):
            from .index import INDEX
            meta = INDEX.project_task_runtime(str(Path(rel_path).with_suffix("")), meta)
        return Note(
            path=str(Path(rel_path)), title=_title_of(p, meta), meta=meta, body=body,
            mtime=p.stat().st_mtime, links=list(links),
        )


def iter_notes(include_system: bool = False) -> list[Note]:
    with _NOTE_WRITE_LOCK:
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
    """Resolve explicit paths exactly; pathless links allow title or basename."""

    def __init__(self, notes: list[Note]):
        self.by_ref = {n.ref.lower(): n for n in notes}
        self.by_title: dict[str, Note] = {}
        self.by_base: dict[str, Note] = {}
        for n in notes:
            self.by_title.setdefault(n.title.lower(), n)
            self.by_base.setdefault(Path(n.ref).name.lower(), n)

    def resolve(self, target: str) -> Note | None:
        from .links import article_ref
        t = target.strip().strip("[]").split("|")[0].split("#")[0].strip().lower()
        if t.startswith("/"):
            t = article_ref(t) or t.lstrip("/")
        if t.endswith(".md"):
            t = t[:-3]
        if "/" in t:
            return self.by_ref.get(t)
        return self.by_ref.get(t) or self.by_title.get(t) or self.by_base.get(t)


def resolver(*, include_system: bool = True) -> Resolver:
    """Build a fresh snapshot, optionally excluding archived and staged Articles."""
    return Resolver(iter_notes(include_system=include_system))


def expand_primitive(
    root: Note, res: Resolver, kind: str, *, paths: dict[str, list[str]] | None = None,
) -> tuple[list[Note], str | None]:
    """Resolve ancestors and the selected descendant tree, never sibling trees.

    Optional paths record a deterministic shortest hierarchy witness for graph
    presentation. The returned execution context and error behavior are unchanged.
    """
    ordered: list[Note] = []
    seen: set[str] = set()
    parents: dict[str, list[Note]] = {}
    for candidate in res.by_ref.values():
        if candidate.kind != kind:
            continue
        for raw in candidate.children:
            child = res.resolve(raw)
            if child and child.kind == kind:
                parents.setdefault(child.ref, []).append(candidate)

    def record_path(note: Note, stack: tuple[str, ...]) -> None:
        if paths is not None:
            path = [*stack, note.ref]
            previous = paths.get(note.ref)
            if previous is None or (len(path), path) < (len(previous), previous):
                paths[note.ref] = path

    def add_ancestors(note: Note, stack: tuple[str, ...]) -> str | None:
        if note.ref in stack:
            return f"cyclic {kind} hierarchy: {' -> '.join((*stack, note.ref))}"
        record_path(note, stack)
        for parent in parents.get(note.ref, []):
            error = add_ancestors(parent, (*stack, note.ref))
            if error:
                return error
        if note.ref not in seen:
            seen.add(note.ref)
            ordered.append(note)
        return None

    def add_descendants(note: Note, stack: tuple[str, ...]) -> str | None:
        if note.ref in stack:
            return f"cyclic {kind} hierarchy: {' -> '.join((*stack, note.ref))}"
        record_path(note, stack)
        if note.ref not in seen:
            seen.add(note.ref)
            ordered.append(note)
        for raw in note.children:
            child = res.resolve(raw)
            if not child or child.kind != kind:
                return f"{kind} child not found or wrong kind: {raw}"
            error = add_descendants(child, (*stack, note.ref))
            if error:
                return error
        return None

    error = add_ancestors(root, ())
    if not error:
        error = add_descendants(root, ())
    return ordered, error


def write_note(rel_path: str, meta: dict, body: str) -> str:
    """Write one native OKF Article; operational Task fields stay in SQLite."""
    with _NOTE_WRITE_LOCK:
        p = CONFIG.vault_dir / rel_path
        meta = dict(meta)
        if "kind" not in meta and "type" not in meta:
            meta["kind"] = "knowledge"
        if p.name.lower() in {"index.md", "log.md"}:
            raise ValueError("index.md and log.md are reserved OKF listings, not Articles")
        # Runtime proposal envelopes are not accepted Task definitions.
        if meta.get("kind", meta.get("type")) == "task" and not rel_path.startswith(("_", ".")):
            from .index import INDEX
            runtime = {key: value for key, value in meta.items() if key in article_format.TASK_RUNTIME_FIELDS}
            if runtime:
                INDEX.mutate_task_runtime(str(Path(rel_path).with_suffix("")), lambda state: state.update(runtime))
        _write_article(p, meta, canonical_body(body, rel_path))
        return str(p)


def _write_article(path: Path, meta: dict, body: str) -> None:
    content = article_format.dumps(meta, body)
    if not path.exists() or path.read_text(encoding="utf-8") != content:
        _atomic_write(path, content)


def mutate_note_metadata(
    note: Note, mutate: Callable[[dict], None], *,
    source_event: tuple[str, str] | None = None,
) -> dict:
    """Atomically merge one system mutation into the note's latest metadata.

    Task execution and UI events can update the same ordinary graph Task at
    nearly the same time. Re-reading under the shared write lock preserves
    fields added after the scheduler took its original Note snapshot.
    """
    with _NOTE_WRITE_LOCK:
        current = load_note(note.path) or note
        if current.kind == "task" and not current.path.startswith(("_", ".")):
            from .index import INDEX

            def apply(state: dict) -> None:
                meta = {key: value for key, value in current.meta.items()
                        if key not in article_format.TASK_RUNTIME_FIELDS}
                meta.update(state)
                mutate(meta)
                _write_article(CONFIG.vault_dir / current.path, meta, current.body)
                state.clear()
                state.update({key: value for key, value in meta.items()
                              if key in article_format.TASK_RUNTIME_FIELDS})
                updated.update(meta)

            updated: dict = {}
            state = INDEX.mutate_task_runtime(current.ref, apply, source_event=source_event)
            # An already receipted Source admission skips the mutation callback.
            return updated or {
                **{key: value for key, value in current.meta.items()
                   if key not in article_format.TASK_RUNTIME_FIELDS},
                **state,
            }
        if source_event is not None:
            raise ValueError("Source events require an ordinary Task runtime")
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


def move_vault_item(source: str, destination_parent: str, new_name: str | None = None,
                    *, _system_migration: tuple[str, str] | None = None) -> dict:
    """Move or rename one owner-managed article/folder and repair exact refs.

    Raw source bytes remain outside this owner-managed tree. All article
    transformations are prepared before the filesystem move and rolled back
    together if a write fails.
    """
    from .system import assert_system_move_allowed, assert_system_article_writable

    source_rel = _vault_relative(source)
    if _system_migration is None:
        assert_system_move_allowed(str(source_rel))
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
    migration_destination = None
    if _system_migration is not None:
        # Private schema migration: pin one exact existing Article and its
        # destination. API/Tool callers never receive this override. Ordinary
        # path, history, runtime and rollback checks below remain in force.
        expected_hash, destination = _system_migration
        migration_destination = _vault_relative(destination)
        if (not is_article or new_name is not None or source_path.suffix != ".md"
                or hashlib.sha256(source_path.read_bytes()).hexdigest() != expected_hash
                or migration_destination.parent != parent_rel
                or migration_destination.suffix != ".md"):
            raise ValueError("System migration Article or destination changed")
    if is_article and source_path.suffix.lower() != ".md":
        raise ValueError("only Markdown articles can be moved")
    if is_article and source_path.name.casefold() in {"index.md", "log.md"}:
        raise ValueError("index.md and log.md are reserved OKF listings, not Articles")
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
        destination_name = migration_destination.name if migration_destination is not None else source_rel.name
    if destination_name.startswith(".") or (
        is_article and destination_name.casefold() in {"index.md", "log.md"}
    ):
        raise ValueError("reserved or hidden destination name")
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
        str(source_rel.with_suffix("")) if is_article else str(source_rel):
        str(destination_rel.with_suffix("")) if is_article else str(destination_rel),
    }
    hub_source = source_path / (source_rel.name + ".md")
    hub_renamed = not is_article and source_rel.name != destination_name and hub_source.is_file()
    if hub_renamed and destination_name.casefold() in {"index", "log"}:
        raise ValueError("index.md and log.md are reserved OKF listings, not Articles")
    if hub_renamed and any(
        item.name.casefold() == (destination_name + ".md").casefold()
        and item != hub_source for item in source_path.iterdir()
    ):
        raise ValueError("destination folder hub already exists")
    moved_file_paths: dict[Path, Path] = {}
    for old_path in source_files:
        old_rel = old_path.relative_to(CONFIG.vault_dir)
        relative = Path(old_path.name) if is_article else old_path.relative_to(source_path)
        if hub_renamed and old_path == hub_source:
            relative = Path(destination_name + ".md")
        new_rel = destination_rel if is_article else destination_rel / relative
        if _system_migration is None:
            assert_system_article_writable(str(new_rel))
        mapping[str(old_rel.with_suffix(""))] = str(new_rel.with_suffix(""))
        moved_file_paths[old_path] = CONFIG.vault_dir / new_rel

    for old_path in source_files:
        note = load_note(old_path.relative_to(CONFIG.vault_dir))
        if note and note.runtime_observation:
            raise ValueError("runtime Observations are maintained by Compact and Promote and cannot be moved")
        if note and note.kind == "task" and str(note.meta.get("status", "draft")) == "running":
            raise ValueError("a running task cannot be moved")

    originals: dict[Path, bytes] = {}
    writes: dict[Path, str] = {}
    for path in sorted(CONFIG.vault_dir.rglob("*.md")):
        rel = path.relative_to(CONFIG.vault_dir)
        # Review envelopes and archived editions are historical evidence, not
        # accepted references to rebase during an owner move. Rewriting them
        # would invalidate their pins and can misinterpret legacy envelopes
        # without an Article type as current Knowledge.
        if rel.parts and rel.parts[0] in (*IMMUTABLE_DIRS, *SYSTEM_DIRS, *HIDDEN_DIRS):
            continue
        reserved = path.name.casefold() in {"index.md", "log.md"}
        parse = article_format.parse if reserved else article_format.loads
        original_meta, original_body = parse(path.read_text(encoding="utf-8"))
        meta = _rewrite_refs(original_meta, mapping)
        body = canonical_body(original_body, str(rel), mapping)
        target = moved_file_paths.get(path, path)
        if title is not None and path == source_path:
            meta["title"] = title
        elif hub_renamed and path == hub_source:
            meta["title"] = destination_name
        if meta != original_meta or body != original_body:
            originals[path] = path.read_bytes()
            serialize = article_format.serialize if reserved else article_format.dumps
            writes[target] = serialize(meta, body)

    moved = False
    renamed_hub = False
    runtime_moves: dict[str, str] = {}
    try:
        from .index import INDEX
        runtime_moves = INDEX.remap_task_runtime(mapping)
        source_path.rename(destination_path)
        moved = True
        if hub_renamed:
            (destination_path / hub_source.name).rename(destination_path / (destination_name + ".md"))
            renamed_hub = True
        for path, content in writes.items():
            _atomic_write(path, content)
    except Exception:
        if runtime_moves:
            INDEX.remap_task_runtime({new: old for old, new in runtime_moves.items()})
        if renamed_hub:
            (destination_path / (destination_name + ".md")).rename(destination_path / hub_source.name)
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
    """System-attributed runtime update; reusable Article bytes stay unchanged."""
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
