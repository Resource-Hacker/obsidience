"""One bounded Source view over the real Obsidience project tree.

Source is the physical substrate beside the Article graph, never a second
knowledge authority.  Every displayed path is project-relative and opens the
exact file at that path: wiki Markdown, application code, fixed System
descriptors, or immutable raw sources.  The graph and indexes are derived from
those files; Source never copies them into a competing store.
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import tempfile
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

from ..config import CONFIG

MAX_SOURCE_CHARS = 500_000
MAX_SOURCE_FILES = 2_000
MAX_SOURCE_PREVIEW_BYTES = 1_000_000
MAX_SOURCE_TREE_SCOPES = 16
PROJECT_SOURCE_ROOTS = (
    Path("obsidience/harness"),
    Path("obsidience/shell"),
    Path("obsidience/ui/src"),
    Path("obsidience/scripts"),
    Path("obsidience/tests"),
)
PROJECT_SOURCE_FILES = (
    Path(".gitignore"),
    Path("AGENTS.md"),
    Path("DESIGN.md"),
    Path("README.md"),
    Path("artifacts.lock.json"),
    Path("obsidience.toml"),
    Path("obsidience/obsidience.toml"),
    Path("obsidience/shell/session/env-obsidiencekwin"),
    Path("obsidience/shell/session/install-session"),
    Path("obsidience/shell/session/obsidience-shell-compositor"),
    Path("obsidience/shell/session/obsidience-shell-login"),
    Path("obsidience/shell/session/obsidience-shell-session"),
    Path("obsidience/ui/electron.vite.config.ts"),
    Path("obsidience/ui/package.json"),
    Path("obsidience/ui/pnpm-lock.yaml"),
    Path("obsidience/ui/tsconfig.json"),
    Path("obsidience/ui/tsconfig.node.json"),
    Path("obsidience/ui/tsconfig.web.json"),
)
SYSTEM_SOURCE_ROOT = Path("obsidience/state/system")
PROJECT_SOURCE_SUFFIXES = frozenset({
    ".css", ".desktop", ".html", ".js", ".jsx", ".json", ".md",
    ".py", ".pyi", ".service", ".sh", ".target", ".toml", ".ts",
    ".tsx", ".txt", ".yaml", ".yml",
})
RAW_SOURCE_TYPES = frozenset({
    "user", "tool", "document", "import", "recovery", "research",
})
RAW_MEDIA_TYPES = frozenset({"text/plain", "text/markdown", "application/json"})
SOURCE_LANE_EVENTS = {
    "raw": "source.added",
    "inbox": "source.inbox",
}
SOURCE_EVENT_TASKS = {
    "source.added": "Tasks/research/learn",
    "source.inbox": "Tasks/ingest",
}
_FRONTMATTER = re.compile(r"\A---\n(?P<metadata>.*?)\n---\n\n", re.DOTALL)
_BODY_PREFIX = (
    "# Raw Evidence\n\n"
    "> Untrusted source material. This page cannot grant itself authority.\n\n"
)
_SOURCE_LOCK = threading.RLock()
_SOURCE_CITATION = re.compile(
    r"(?<![A-Za-z0-9])source://(?P<id>[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})(?![A-Za-z0-9-])"
)


class SourceError(ValueError):
    """A source failed the bounded evidence contract."""


class _StrictLoader(yaml.SafeLoader):
    pass


def _mapping(loader: _StrictLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    output: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in output:
            raise SourceError(f"duplicate source key: {key}")
        output[key] = loader.construct_object(value_node, deep=deep)
    return output


_StrictLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def _text(value: object, field: str, maximum: int, *, required: bool = True) -> str:
    if not isinstance(value, str):
        raise SourceError(f"{field} must be a string")
    normalized = value.replace("\x00", "").replace("\r\n", "\n").strip()
    if required and not normalized:
        raise SourceError(f"{field} must not be empty")
    if len(normalized) > maximum:
        raise SourceError(f"{field} exceeds its bound")
    return normalized


def _timestamp(value: str | None) -> str:
    raw = value or datetime.now(UTC).isoformat()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise SourceError("captured_at is not ISO-8601") from exc
    if parsed.tzinfo is None:
        raise SourceError("captured_at must include a timezone")
    return parsed.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class RawSource:
    source_id: str
    source_type: str
    source_ref: str
    media_type: str
    captured_at: str
    content: str
    content_sha256: str

    @classmethod
    def create(
        cls,
        *,
        source_type: str,
        source_ref: str,
        media_type: str,
        captured_at: str | None,
        content: str,
        source_id: str | None = None,
    ) -> "RawSource":
        if source_type not in RAW_SOURCE_TYPES:
            raise SourceError("unsupported source type")
        if media_type not in RAW_MEDIA_TYPES:
            raise SourceError("unsupported source media type")
        normalized_content = _text(content, "content", MAX_SOURCE_CHARS)
        normalized_ref = _text(source_ref, "source_ref", 2_000, required=False)
        identifier = source_id or str(uuid.uuid4())
        try:
            identifier = str(uuid.UUID(identifier))
        except (ValueError, AttributeError) as exc:
            raise SourceError("source_id must be a UUID") from exc
        return cls(
            source_id=identifier,
            source_type=source_type,
            source_ref=normalized_ref,
            media_type=media_type,
            captured_at=_timestamp(captured_at),
            content=normalized_content,
            content_sha256="sha256:" + hashlib.sha256(normalized_content.encode()).hexdigest(),
        )


def render_raw_source(source: RawSource) -> bytes:
    metadata = {
        "source_id": source.source_id,
        "source_type": source.source_type,
        "source_ref": source.source_ref,
        "media_type": source.media_type,
        "captured_at": source.captured_at,
        "content_sha256": source.content_sha256,
        "immutable": True,
    }
    frontmatter = yaml.safe_dump(
        metadata,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=4096,
    ).rstrip()
    return f"---\n{frontmatter}\n---\n\n{_BODY_PREFIX}{source.content}\n".encode()


def parse_raw_source(material: bytes) -> RawSource:
    if not material or len(material) > MAX_SOURCE_CHARS + 16 * 1024:
        raise SourceError("raw source exceeds its material bound")
    try:
        text = material.decode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise SourceError("raw source is not strict UTF-8") from exc
    match = _FRONTMATTER.match(text)
    if match is None:
        raise SourceError("raw source is missing frontmatter")
    try:
        metadata = yaml.load(match.group("metadata"), Loader=_StrictLoader)
    except yaml.YAMLError as exc:
        raise SourceError("raw source frontmatter is invalid") from exc
    expected = {
        "source_id", "source_type", "source_ref", "media_type",
        "captured_at", "content_sha256", "immutable",
    }
    if not isinstance(metadata, dict) or set(metadata) != expected:
        raise SourceError("raw source keys differ from the contract")
    body = text[match.end():]
    if not body.startswith(_BODY_PREFIX) or not body.endswith("\n"):
        raise SourceError("raw source body wrapper changed")
    source = RawSource.create(
        source_id=metadata["source_id"],
        source_type=metadata["source_type"],
        source_ref=metadata["source_ref"],
        media_type=metadata["media_type"],
        captured_at=metadata["captured_at"],
        content=body[len(_BODY_PREFIX):-1],
    )
    if metadata["immutable"] is not True or metadata["content_sha256"] != source.content_sha256:
        raise SourceError("raw source attestation changed")
    return source


def _material_sha256(material: bytes) -> str:
    return "sha256:" + hashlib.sha256(material).hexdigest()


def _relative_path(source: RawSource, lane: str) -> str:
    prefix = "research" if lane == "inbox" else "evidence"
    return f"{lane}/{source.captured_at[:10]}/{prefix}--{source.source_id}.md"


def _safe_path(relative: str) -> Path:
    rel = Path(relative)
    if (
        rel.is_absolute()
        or not rel.parts
        or rel.parts[0] not in SOURCE_LANE_EVENTS
        or ".." in rel.parts
    ):
        raise SourceError("source path is outside raw/ and inbox/")
    return CONFIG.source_dir / rel


def _atomic_write(relative: str, material: bytes) -> None:
    target = _safe_path(relative)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".source-", dir=target.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(material)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _row_doc(row: dict, *, include_content: bool = False, status: str = "verified") -> dict:
    material = bytes(row["material"])
    source = parse_raw_source(material)
    title = source.source_ref or f"Source {source.source_id[:8]}"
    doc = {
        "id": source.source_id,
        "citation": f"source://{source.source_id}",
        "path": row["path"],
        "title": title,
        "source_type": source.source_type,
        "source_ref": source.source_ref,
        "media_type": source.media_type,
        "captured_at": source.captured_at,
        "content_sha256": source.content_sha256,
        "material_sha256": row["material_sha256"],
        "immutable": True,
        "status": status,
    }
    if include_content:
        doc["content"] = source.content
    return doc


def _restore(row: dict) -> str:
    material = bytes(row["material"])
    if _material_sha256(material) != row["material_sha256"]:
        raise SourceError("private source ledger material failed attestation")
    target = _safe_path(row["path"])
    if target.exists() and target.read_bytes() == material:
        return "verified"
    _atomic_write(row["path"], material)
    return "restored"


def _source_event(row: dict) -> dict:
    """Dispatch one durable Source transition through its sole graph Task."""
    from .index import INDEX
    from ..execution.scheduler import enqueue_named_event

    lane = Path(str(row["path"])).parts[0]
    event = SOURCE_LANE_EVENTS.get(lane)
    event_key = str(row.get("event_key") or "")
    if not event or not event_key.startswith(event + ":"):
        raise SourceError("source event identity does not match its physical lane")

    source = parse_raw_source(bytes(row["material"]))
    params = {
        "activation_key": event_key,
        "queue_after_review": True,
        "source_id": source.source_id,
        "source_citation": f"source://{source.source_id}",
        "source_path": f"obsidience/evidence/{row['path']}",
        "source_type": source.source_type,
        "source_ref": source.source_ref,
        "source_media_type": source.media_type,
        "source_captured_at": source.captured_at,
        "source_sha256": source.content_sha256,
    }
    if lane == "inbox":
        params["source_citations"] = [
            item["citation"]
            for item in validate_source_citations(source.content, required=True)
        ]
    expected = SOURCE_EVENT_TASKS[event]
    try:
        occurrences = enqueue_named_event(event, params, expected_task=expected)
    except ValueError as exc:
        raise SourceError(str(exc)) from exc
    INDEX.mark_source_event_dispatched(source.source_id, datetime.now(UTC).timestamp())
    return {"name": event, "params": params, "occurrences": occurrences}


def _capture_source(
    *, lane: str, source_type: str, source_ref: str, media_type: str,
    captured_at: str | None, content: str, activation_key: str | None = None,
) -> dict:
    if lane not in SOURCE_LANE_EVENTS:
        raise SourceError("unsupported source lane")
    from .index import INDEX

    source = RawSource.create(
        source_type=source_type,
        source_ref=source_ref,
        media_type=media_type,
        captured_at=captured_at,
        content=content,
    )
    existing = INDEX.source_by_fingerprint(
        lane, source.source_type, source.source_ref,
        source.media_type, source.content_sha256,
    )
    if existing:
        status = _restore(existing)
        result = {**_row_doc(existing, include_content=True, status=status), "created": False}
        if existing.get("event_key") and existing.get("event_dispatched_at") is None:
            result["source_event"] = _source_event(existing)
        else:
            result["source_event"] = None
        return result
    material = render_raw_source(source)
    material_sha256 = _material_sha256(material)
    relative = _relative_path(source, lane)
    event = SOURCE_LANE_EVENTS[lane]
    durable_event_key = activation_key or f"{event}:{source.source_id}"
    if not durable_event_key.startswith(event + ":"):
        raise SourceError("source activation key does not match its physical lane")
    # Commit the immutable bytes and pending event to the ledger first. If the
    # process stops before the physical write or event dispatch, the ordinary
    # pending-event replay restores the exact file and resumes once.
    INDEX.record_source(
        id=source.source_id,
        path=relative,
        source_type=source.source_type,
        source_ref=source.source_ref,
        media_type=source.media_type,
        captured_at=source.captured_at,
        content_sha256=source.content_sha256,
        material_sha256=material_sha256,
        material=material,
        created_at=datetime.now(UTC).timestamp(),
        event_key=durable_event_key,
        event_dispatched_at=None,
    )
    row = INDEX.source(source.source_id)
    if not row:
        raise SourceError("source ledger failed to retain the new source")
    status = _restore(row)
    return {
        **_row_doc(row, include_content=True, status=status),
        "created": True,
        "source_event": _source_event(row),
    }


def ingest_source(
    *, source_type: str, source_ref: str, media_type: str,
    captured_at: str | None, content: str, activation_key: str | None = None,
) -> dict:
    """Preserve raw evidence and emit its ordinary ``source.added`` trigger."""
    with _SOURCE_LOCK:
        return _capture_source(
            lane="raw",
            source_type=source_type,
            source_ref=source_ref,
            media_type=media_type,
            captured_at=captured_at,
            content=content,
            activation_key=activation_key,
        )


def handoff_source(*, title: str, content: str, captured_at: str | None = None) -> dict:
    """Drop Darwin's cited synthesis into the physical Source Inbox."""
    citations = validate_source_citations(content, required=True)
    with _SOURCE_LOCK:
        result = _capture_source(
            lane="inbox",
            source_type="research",
            source_ref=_text(title, "title", 300),
            media_type="text/markdown",
            captured_at=captured_at,
            content=content,
        )
    return {**result, "source_citations": [item["citation"] for item in citations]}


def dispatch_pending_source_events() -> dict:
    """Replay attested Source transitions left pending by a process failure."""
    from .index import INDEX

    dispatched: list[str] = []
    issues: list[dict] = []
    with _SOURCE_LOCK:
        for row in INDEX.pending_source_events():
            try:
                _restore(row)
                event = _source_event(row)
                dispatched.append(str(event["params"]["source_citation"]))
            except SourceError as exc:
                issues.append({"source": str(row.get("id", "")), "error": str(exc)})
    return {"dispatched": dispatched, "issues": issues}


def list_sources() -> dict:
    from .index import INDEX

    rows = INDEX.sources()
    sources = []
    registered: set[str] = set()
    for row in rows:
        registered.add(row["path"])
        status = _restore(row)
        sources.append(_row_doc(row, status=status))
    unregistered = []
    for lane in SOURCE_LANE_EVENTS:
        lane_root = CONFIG.source_dir / lane
        if lane_root.exists():
            for path in sorted(lane_root.rglob("*.md")):
                relative = str(path.relative_to(CONFIG.source_dir))
                if relative not in registered:
                    unregistered.append(relative)
    return {
        "sources": sources,
        "issues": [
            {"path": path, "status": "unregistered", "detail": "Not indexed or trusted."}
            for path in unregistered
        ],
    }


def get_source(value: str) -> dict:
    from .index import INDEX

    source_id = value.strip().removeprefix("source://").rsplit("/", 1)[-1]
    try:
        source_id = str(uuid.UUID(source_id))
    except ValueError as exc:
        raise SourceError("source reference must contain a UUID") from exc
    row = INDEX.source(source_id)
    if not row:
        raise SourceError(f"source not found: {source_id}")
    status = _restore(row)
    return _row_doc(row, include_content=True, status=status)


def validate_source_citations(text: str, *, required: bool = False) -> list[dict]:
    """Resolve every canonical Source citation in a finding before approval."""
    if not isinstance(text, str):
        raise SourceError("source finding must be text")
    matches = list(_SOURCE_CITATION.finditer(text))
    if text.count("source://") != len(matches):
        raise SourceError("source citations must use the exact source://<uuid> form")
    if required and not matches:
        raise SourceError("Source Inbox handoffs require at least one source:// citation")
    verified = []
    seen: set[str] = set()
    for match in matches:
        citation = f"source://{match.group('id').lower()}"
        if citation in seen:
            continue
        seen.add(citation)
        verified.append(get_source(citation))
    return verified


# ---------- Reader Source filesystem ----------

def _article_source_values(value: object) -> list[str]:
    values = value if isinstance(value, list) else [value] if value else []
    return [str(item).strip() for item in values if str(item).strip()]


def _safe_linked_source(value: str) -> Path:
    """Resolve only an explicit accepted-Article link inside this project."""
    relative = Path(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise SourceError("linked source must be a project-relative path")
    target = (CONFIG.project_root / relative).resolve()
    project_root = CONFIG.project_root.resolve()
    try:
        target.relative_to(project_root)
    except ValueError as exc:
        raise SourceError("linked source escapes the project") from exc
    if target.is_symlink() or not target.is_file():
        raise SourceError("linked source is missing or is not a regular file")
    return target


def _media_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _path_record(
    *,
    key: str,
    actual: Path,
    storage: str,
    articles: list[str] | None = None,
) -> dict:
    stat = actual.stat()
    return {
        "key": key,
        "path": key,
        "name": actual.name,
        "media_type": _media_type(actual),
        "size": stat.st_size,
        "modified_at": stat.st_mtime,
        "storage": storage,
        "read_only": True,
        "articles": list(articles or []),
    }


def _add_article(record: dict | None, ref: str) -> None:
    if record is not None and ref not in record["articles"]:
        record["articles"].append(ref)


def _source_manifest() -> tuple[list[dict], dict[str, Path], list[dict]]:
    """Build a bounded inventory whose keys are exact paths on disk."""
    from .vault import iter_notes

    notes = list(iter_notes())
    records: dict[str, dict] = {}
    key_by_actual: dict[Path, str] = {}
    path_by_key: dict[str, Path] = {}
    blob_by_source_id: dict[str, str] = {}
    issues: list[dict] = []
    project_root = CONFIG.project_root.resolve()
    CONFIG.source_dir.mkdir(parents=True, exist_ok=True)

    for path in sorted(CONFIG.source_dir.rglob("*")):
        if len(records) >= MAX_SOURCE_FILES:
            issues.append({
                "path": CONFIG.source_dir.name,
                "status": "bounded",
                "detail": "Raw Source file limit reached.",
            })
            break
        if path.is_symlink() or not path.is_file() or any(part.startswith(".") for part in path.relative_to(CONFIG.source_dir).parts):
            continue
        actual = path.resolve()
        try:
            relative = actual.relative_to(project_root).as_posix()
        except ValueError:
            continue
        key = relative
        stat = actual.stat()
        record = _path_record(key=key, actual=actual, storage="blob")
        records[key] = record
        key_by_actual[actual] = key
        path_by_key[key] = actual
        if actual.suffix.lower() == ".md" and stat.st_size <= MAX_SOURCE_PREVIEW_BYTES:
            try:
                blob_by_source_id[parse_raw_source(actual.read_bytes()).source_id] = key
            except SourceError:
                pass

    # The complete visible wiki directory is physical Source. Accepted Articles
    # carry a reverse association; staged and archived files remain ordinary
    # files with no accepted-Article authority.
    accepted_by_path = {Path(note.path).as_posix(): note.ref for note in notes}
    for path in sorted(CONFIG.vault_dir.rglob("*")):
        if len(records) >= MAX_SOURCE_FILES:
            issues.append({
                "path": CONFIG.vault_dir.name,
                "status": "bounded",
                "detail": "Knowledge file limit reached.",
            })
            break
        if path.is_symlink() or not path.is_file():
            continue
        relative_in_vault = path.relative_to(CONFIG.vault_dir)
        if any(part.startswith(".") for part in relative_in_vault.parts):
            continue
        actual = path.resolve()
        try:
            actual.relative_to(CONFIG.vault_dir.resolve())
        except ValueError:
            issues.append({
                "path": relative_in_vault.as_posix(),
                "status": "missing",
                "detail": "Knowledge file escapes the project wiki.",
            })
            continue
        try:
            key = actual.relative_to(project_root).as_posix()
        except ValueError:
            continue
        records[key] = _path_record(
            key=key,
            actual=actual,
            storage="knowledge",
            articles=[accepted_by_path[relative_in_vault.as_posix()]]
            if relative_in_vault.as_posix() in accepted_by_path
            else [],
        )
        key_by_actual[actual] = key
        path_by_key[key] = actual

    project_paths: set[Path] = set()
    for relative_root in PROJECT_SOURCE_ROOTS:
        source_root = project_root / relative_root
        if source_root.is_symlink() or not source_root.is_dir():
            continue
        for path in source_root.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(project_root)
            if any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
                continue
            if path.suffix.lower() in PROJECT_SOURCE_SUFFIXES:
                project_paths.add(path.resolve())
    for relative_file in PROJECT_SOURCE_FILES:
        path = project_root / relative_file
        if not path.is_symlink() and path.is_file():
            project_paths.add(path.resolve())

    for actual in sorted(project_paths):
        if len(records) >= MAX_SOURCE_FILES:
            issues.append({
                "path": "harness",
                "status": "bounded",
                "detail": "Project source file limit reached.",
            })
            break
        try:
            relative = actual.relative_to(project_root).as_posix()
        except ValueError:
            continue
        key = relative
        records[key] = _path_record(key=key, actual=actual, storage="code")
        key_by_actual[actual] = key
        path_by_key[key] = actual

    # System files are stable physical descriptors. Live utilization remains
    # on the Hardware API; it must never masquerade as file content.
    system_root = CONFIG.system_dir.resolve()
    if system_root.is_dir() and not system_root.is_symlink():
        for path in sorted(system_root.rglob("*")):
            if len(records) >= MAX_SOURCE_FILES:
                issues.append({
                    "path": SYSTEM_SOURCE_ROOT.as_posix(),
                    "status": "bounded",
                    "detail": "System descriptor file limit reached.",
                })
                break
            if path.is_symlink() or not path.is_file():
                continue
            relative = path.relative_to(project_root)
            if any(part.startswith(".") for part in relative.parts):
                continue
            actual = path.resolve()
            key = relative.as_posix()
            records[key] = _path_record(
                key=key,
                actual=actual,
                storage="system",
            )
            key_by_actual[actual] = key
            path_by_key[key] = actual

    # Article metadata and Source citations associate already-scanned physical
    # files with their knowledge Articles. They never manufacture virtual paths.
    for note in notes:
        values = [
            *_article_source_values(note.meta.get("source")),
            *_article_source_values(note.meta.get("sources")),
        ]
        for value in values:
            try:
                actual = _safe_linked_source(value)
            except SourceError as exc:
                issues.append({"path": value, "status": "missing", "detail": f"[[{note.ref}]]: {exc}"})
                continue
            key = key_by_actual.get(actual)
            record = records.get(key) if key else None
            if record is None:
                key = actual.relative_to(project_root).as_posix()
                record = _path_record(key=key, actual=actual, storage="code")
                records[key] = record
                key_by_actual[actual] = key
                path_by_key[key] = actual
            _add_article(record, note.ref)

        for match in _SOURCE_CITATION.finditer(note.body):
            _add_article(records.get(blob_by_source_id.get(match.group("id").lower(), "")), note.ref)

    rows = sorted(records.values(), key=lambda row: str(row["path"]).casefold())
    for row in rows:
        row["articles"].sort()
    return rows, path_by_key, issues


def list_source_files() -> dict:
    files, _actual_by_key, issues = _source_manifest()
    return {"files": files, "issues": issues}


def get_source_file(key: str) -> dict:
    files, path_by_key, _issues = _source_manifest()
    record = next((row for row in files if row["key"] == key), None)
    source_path = path_by_key.get(key)
    if record is None or source_path is None:
        raise SourceError("source file not found")
    complete = source_path.read_bytes()
    size = len(complete)
    material = complete[:MAX_SOURCE_PREVIEW_BYTES]
    media_type = str(record["media_type"])
    textual = media_type.startswith("text/") or media_type == "application/json" or Path(str(record["name"])).suffix.lower() in {
        ".py", ".pyi", ".md", ".json", ".toml", ".yaml", ".yml", ".csv", ".ts", ".tsx", ".js", ".jsx", ".css", ".html", ".sh",
    }
    content = material.decode("utf-8", errors="replace") if textual else None
    digest = "sha256:" + hashlib.sha256(complete).hexdigest() if size <= 32 * 1024 * 1024 else None
    return {
        **record,
        "size": size,
        "content": content,
        "truncated": size > MAX_SOURCE_PREVIEW_BYTES,
        "sha256": digest,
    }


def normalize_source_tree(value: str) -> str:
    """Return one safe project-relative Source scope for Agent metadata."""
    raw = value.strip().replace("\\", "/")
    if raw.startswith("/"):
        raise SourceError("source tree must be Source-relative")
    normalized = raw.strip("/")
    path = Path(normalized)
    if (
        not normalized
        or not path.parts
        or path.is_absolute()
        or ".." in path.parts
        or any(part.startswith(".") for part in path.parts)
    ):
        raise SourceError("source tree must be a visible project-relative scope")
    return path.as_posix()


def source_tree_exists(value: str, *, folder_only: bool = True) -> bool:
    """Check one exact manifest prefix; loose string-prefix matches are forbidden."""
    scope = normalize_source_tree(value)
    files = list_source_files()["files"]
    if folder_only:
        return any(str(row["key"]).startswith(scope + "/") for row in files)
    return any(
        row["key"] == scope or str(row["key"]).startswith(scope + "/")
        for row in files
    )


def article_refs_for_trees(values: object) -> list[str]:
    """Map checked-out Source scopes to related accepted Knowledge Articles.

    The scope only biases ordinary bounded retrieval.  Raw files never enter
    the Thinking Packet and never grant Tool or Task authority.
    """
    raw_values = values if isinstance(values, list) else [values] if values else []
    scopes: list[str] = []
    for raw in raw_values[:MAX_SOURCE_TREE_SCOPES]:
        try:
            scopes.append(normalize_source_tree(str(raw)))
        except SourceError:
            continue
    if not scopes:
        return []

    refs: set[str] = set()
    rows = list_source_files()["files"]
    for scope in scopes:
        for row in rows:
            key = str(row["key"])
            if key == scope or key.startswith(scope + "/"):
                refs.update(str(ref) for ref in row.get("articles", []))

    # The physical System inventory is the Source-side counterpart of the
    # Executive's ADMECH branch. A checkout biases matching accepted Knowledge
    # without copying raw descriptor bytes into the Thinking Packet.
    if any(scope == "obsidience/state/system" for scope in scopes):
        from .vault import iter_notes

        refs.update(
            note.ref for note in iter_notes()
            if note.ref.startswith("ADMECH Workstation/")
        )
    if any(
        scope == "obsidience/state/system/hardware"
        or scope.startswith("obsidience/state/system/hardware/")
        for scope in scopes
    ):
        from .vault import iter_notes

        refs.update(
            note.ref for note in iter_notes()
            if note.ref.startswith("ADMECH Workstation/Hardware/")
        )
    if any(
        scope == "obsidience/state/system/applications"
        or scope.startswith("obsidience/state/system/applications/")
        for scope in scopes
    ):
        from .vault import iter_notes

        refs.update(
            note.ref for note in iter_notes()
            if note.ref.startswith("ADMECH Workstation/Software/")
        )
    return sorted(refs)
