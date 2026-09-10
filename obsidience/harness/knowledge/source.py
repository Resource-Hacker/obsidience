"""One bounded Source view over the real Obsidience project tree.

Source is the physical substrate beside the Article graph, never a second
knowledge authority.  Every displayed path is project-relative and opens the
exact file at that path: wiki Markdown, application code, fixed System
descriptors, or immutable raw sources.  The graph and indexes are derived from
those files; Source never copies them into a competing store.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import mimetypes
import os
import re
import tempfile
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

import yaml

from ..config import CONFIG

MAX_SOURCE_CHARS = 500_000
MAX_DISTILL_INSTRUCTIONS_CHARS = 500
MAX_SOURCE_FILES = 2_000
MAX_SOURCE_PREVIEW_BYTES = 1_000_000
MAX_SOURCE_TREE_SCOPES = 16
PROJECT_SOURCE_ROOTS = (
    Path("docs"),
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
    Path("obsidience/shell/session/greetd.toml"),
    Path("obsidience/shell/session/install-session"),
    Path("obsidience/shell/session/obsidience-shell-login"),
    Path("obsidience/shell/session/obsidience.desktop"),
    Path("obsidience/ui/electron.vite.config.ts"),
    Path("obsidience/ui/package.json"),
    Path("obsidience/ui/pnpm-lock.yaml"),
    Path("obsidience/ui/tsconfig.json"),
    Path("obsidience/ui/tsconfig.node.json"),
    Path("obsidience/ui/tsconfig.web.json"),
)
SYSTEM_SOURCE_ROOT = Path("obsidience/state/system")
PROJECT_SOURCE_SUFFIXES = frozenset({
    ".conf", ".css", ".desktop", ".html", ".js", ".jsx", ".json", ".md",
    ".py", ".pyi", ".qml", ".service", ".sh", ".svg", ".target", ".toml", ".ts",
    ".tsx", ".txt", ".yaml", ".yml",
})
RAW_SOURCE_TYPES = frozenset({
    "user", "tool", "document", "import", "recovery", "research",
})
RAW_MEDIA_TYPES = frozenset({
    "text/plain", "text/markdown", "application/json", "application/xml",
    "application/rss+xml", "application/atom+xml", "text/xml", "text/html", "text/csv",
})
SOURCE_LANE_EVENTS = {
    "raw": "source.added",
    "inbox": "source.inbox",
}
SYSTEM_EVIDENCE_CATEGORIES = frozenset({
    "identity", "compute", "storage", "devices", "network", "applications", "runtime",
})


def _system_evidence_category(category: str) -> bool:
    return isinstance(category, str) and (category in SYSTEM_EVIDENCE_CATEGORIES or
        len(category) <= 200 and bool(re.fullmatch(r"schema\.[a-z0-9-]+(?:\.[a-z0-9-]+){0,8}", category)))


def _system_evidence_ref(reference: str) -> bool:
    return isinstance(reference, str) and reference.startswith("system://") and _system_evidence_category(reference[9:])


SOURCE_EVENT_TASKS = {
    "source.added": "Tasks/research/learn",
    "source.inbox": "Tasks/ingest",
}
DISTILL_TASK = "Tasks/research/distill"
OBSERVATION_ARCHIVE_SOURCE_CLASS = "observation_archive"
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
_OBSERVATION_ARCHIVE_REF = re.compile(
    r"\Aobsidience://observations/temporary/"
    r"(?P<conversation>conversation-[0-9a-f]{32})/"
    r"(?P<promotion>[0-9a-f]{20})\Z"
)
_EXECUTIVE_TEMPORARY_PREFIX = (
    "Agents/Executive/Observations/Temporary Observations/"
)


class SourceError(ValueError):
    """A source failed the bounded evidence contract."""


def normalize_distill_instructions(value: object) -> str:
    """Bound owner Feed preferences without interpreting provider content."""
    if not isinstance(value, str):
        raise SourceError("distill_instructions must be text")
    normalized = value.replace("\r\n", "\n")
    if (len(normalized) > MAX_DISTILL_INSTRUCTIONS_CHARS
            or any((ord(char) < 32 and char not in "\n\t") or 127 <= ord(char) <= 159
                   for char in normalized)):
        raise SourceError("distill_instructions must contain at most 500 characters without control characters")
    return normalized.strip()


def feed_binding_matches(admitted: object, current: dict) -> bool:
    """Old empty snapshots remain valid; no configured value rewrites a Task."""
    if not isinstance(admitted, dict):
        return False
    return {**admitted, "distill_instructions": admitted.get("distill_instructions", "")} == current


def research_source_binding(params: dict) -> dict | None:
    """Keep a Source event's admitted identity distinct from external metadata."""
    if params.get("event") != "source.added":
        return None
    try:
        source_id = str(uuid.UUID(str(params.get("source_id", ""))))
    except ValueError as exc:
        raise SourceError("source.added requires its exact activating Source UUID") from exc
    citation = "source://" + source_id
    digest = params.get("source_sha256")
    if (params.get("source_citation") != citation
            or params.get("activation_key") != "source.added:" + source_id
            or not isinstance(digest, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)):
        raise SourceError("source.added identity, event key, citation and content hash must agree")
    return {"citation": citation, "content_sha256": digest}


def feed_source_binding(source_id: str, *, index=None, restore: bool = True) -> dict | None:
    """Attest a Feed origin; read-only projections never restore Source files."""
    from .index import INDEX

    ledger = INDEX if index is None else index
    row = ledger.source(source_id)
    if not row:
        raise SourceError("Feed Source is missing")
    origin_id = str(row.get("origin_source_id") or source_id)
    receipt = ledger.feed_source_binding(origin_id)
    if receipt is None:
        if row.get("origin_source_id"):
            raise SourceError("Inbox Feed origin receipt is missing")
        return None
    if not receipt.get("destination_ref"):
        raise SourceError("Feed Source has no selected graph destination")
    instructions = receipt.get("distill_instructions", "")
    if normalize_distill_instructions(instructions) != instructions:
        raise SourceError("Feed Source instruction receipt is not normalized")
    original_row = row if origin_id == source_id else ledger.source(origin_id)
    if original_row is None:
        raise SourceError("Original Feed Source is missing")
    original = None
    evidence_rows = [(original_row, origin_id)]
    if origin_id != source_id:
        evidence_rows.append((row, source_id))
    for evidence_row, expected_id in evidence_rows:
        if _material_sha256(bytes(evidence_row["material"])) != evidence_row["material_sha256"]:
            raise SourceError("Feed Source ledger material failed attestation")
        doc = _row_doc(evidence_row, include_content=True)
        if doc["id"] != expected_id or doc["content_sha256"] != evidence_row["content_sha256"]:
            raise SourceError("Feed Source ledger identity failed attestation")
        if expected_id == origin_id:
            original = doc
    if restore:
        _restore(original_row)
    if (original["content_sha256"] != receipt["source_sha256"]
            or original["source_ref"] != f"feed://{receipt['feed_id']}/{receipt['item_key']}"):
        raise SourceError("Feed Source controller identity does not match its bytes")
    try:
        item = json.loads(original["content"])
        if (item.get("record_type") != "parsed_rss_item"
                or hashlib.sha256(item["native_id"].encode()).hexdigest() != receipt["item_key"]):
            raise ValueError("invalid item identity")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise SourceError("Feed Source item is malformed") from exc
    return {**receipt, "distill_instructions": instructions,
            "reporting_url": str(item.get("reporting_url") or ""),
            "published": item.get("published")}


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
        if media_type in {"application/xml", "application/rss+xml", "application/atom+xml", "text/xml"}:
            # Feedparser consumes original XML. Preserve whitespace/newlines
            # exactly so Source's UTF-8 content hash also attests the feed bytes.
            if (not isinstance(content, str) or not content.strip() or "\x00" in content
                    or len(content.encode("utf-8")) > MAX_SOURCE_CHARS):
                raise SourceError("XML content must be nonempty UTF-8 within the Source bound")
            normalized_content = content
        else:
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
    if lane == "system":
        return f"system/{source.source_ref.removeprefix('system://')}/{source.captured_at[:10]}/evidence--{source.source_id}.md"
    prefix = "research" if lane == "inbox" else "evidence"
    return f"{lane}/{source.captured_at[:10]}/{prefix}--{source.source_id}.md"


def _safe_path(relative: str) -> Path:
    rel = Path(relative)
    if (
        rel.is_absolute()
        or not rel.parts
        or rel.parts[0] not in {*SOURCE_LANE_EVENTS, "system"}
        or ".." in rel.parts
    ):
        raise SourceError("source path is outside its physical lane")
    if rel.parts[0] == "system":
        if (len(rel.parts) != 4 or not _system_evidence_category(rel.parts[1])
                or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", rel.parts[2])
                or not re.fullmatch(r"evidence--[0-9a-f-]{36}\.md", rel.parts[3])):
            raise SourceError("invalid System evidence path")
        target = CONFIG.source_dir / rel
        if any(path.is_symlink() for path in (target, *target.parents)):
            raise SourceError("System evidence path cannot follow symlinks")
        return target
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
        "source_path": _safe_path(row["path"]).relative_to(CONFIG.project_root).as_posix(),
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


def _attested_material(row: dict) -> bytes:
    material = bytes(row["material"])
    if _material_sha256(material) != row["material_sha256"]:
        raise SourceError("private source ledger material failed attestation")
    if str(row["path"]).startswith("system/"):
        captured = parse_raw_source(material)
        if (not _system_evidence_ref(captured.source_ref)
                or captured.source_type != "tool" or captured.media_type != "application/json"
                or row.get("event_key") is not None
                or row["path"] != _relative_path(captured, "system")
                or any(row[field] != getattr(captured, attribute) for field, attribute in (
                    ("id", "source_id"), ("source_ref", "source_ref"), ("source_type", "source_type"),
                    ("media_type", "media_type"), ("captured_at", "captured_at"), ("content_sha256", "content_sha256")))):
            raise SourceError("System evidence ledger identity failed attestation")
    return material


def _restore(row: dict) -> str:
    material = _attested_material(row)
    target = _safe_path(row["path"])
    if target.exists() and target.read_bytes() == material:
        return "verified"
    _atomic_write(row["path"], material)
    return "restored"


def _trusted_source_class(source: RawSource, lane: str) -> str | None:
    """Classify only a controller-bound internal observation archive."""
    if (
        lane != "raw"
        or source.source_type != "document"
        or source.media_type != "text/markdown"
    ):
        return None
    match = _OBSERVATION_ARCHIVE_REF.fullmatch(source.source_ref)
    if match is None:
        return None

    # The reserved URI is necessary but not sufficient.  Require the exact
    # committed Temporary Observation that the promotion controller marked
    # with this key; arbitrary Source text and caller-supplied labels cannot
    # manufacture the routing class.
    from .vault import iter_notes

    for note in iter_notes():
        meta = note.meta
        if (
            note.kind == "knowledge"
            and note.ref.startswith(_EXECUTIVE_TEMPORARY_PREFIX)
            and meta.get("observation_scope") == "temporary"
            and meta.get("temporary") is True
            and meta.get("compaction") is True
            and meta.get("compaction_committed") is True
            and str(meta.get("source_conversation_id", ""))
            == match.group("conversation")
            and str(meta.get("promotion_pending", ""))
            == match.group("promotion")
        ):
            return OBSERVATION_ARCHIVE_SOURCE_CLASS
    return None


def research_activation_key(context: dict) -> str | None:
    """Bind supporting captures to their existing research, not another Learn."""
    params = context.get("params") or {}
    if context.get("event") == "source.added":
        key = str(params.get("activation_key", ""))
        if key.startswith("source.added:"):
            return key
    task = str(context.get("task", ""))
    run_id = str(context.get("run_id", ""))
    if context.get("agent") == "Darwin" and task.startswith("Tasks/research/") and run_id:
        return f"source.added:research:{run_id}:{task}"
    return None


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
    source_class = _trusted_source_class(source, lane)
    if source_class is not None:
        params["source_class"] = source_class
    if lane == "inbox":
        params["source_citations"] = [
            item["citation"]
            for item in validate_source_citations(source.content, required=True)
        ]
        if event_key.startswith("source.inbox:research:"):
            parts = event_key.split(":", 4)
            if len(parts) != 5 or not _research_owner(parts[3], parts[2]):
                raise SourceError("Inbox research provenance does not match its execution")
            params.update(research_task=parts[3], research_run_id=parts[2])
    expected = SOURCE_EVENT_TASKS[event]
    feed_binding = feed_source_binding(source.source_id) if (
        row.get("origin_source_id") or source.source_ref.startswith("feed://")
    ) else None
    if feed_binding is not None:
        params["feed_binding"] = feed_binding
        if lane == "raw":
            expected = DISTILL_TASK
    handled_by = {}
    if event_key.startswith("source.added:research:"):
        parts = event_key.split(":", 3)
        if len(parts) != 4:
            raise SourceError("invalid research capture identity")
        handled_by = {"handled_by_run_id": parts[2], "handled_by_task_ref": parts[3]}
    try:
        occurrences = enqueue_named_event(
            event, params, expected_task=expected,
            source_event=(source.source_id, event_key), **handled_by,
        )
    except ValueError as exc:
        raise SourceError(str(exc)) from exc
    if not occurrences:
        # Research-owned captures and observation archives require no new Task.
        # Ordinary admissions stamp this receipt atomically with their FIFO.
        INDEX.mark_source_event_dispatched(source.source_id, datetime.now(UTC).timestamp())
    return {"name": event, "params": params, "occurrences": occurrences}


def _capture_source(
    *, lane: str, source_type: str, source_ref: str, media_type: str,
    captured_at: str | None, content: str, activation_key: str | None = None,
    feed_receipt: dict | None = None, origin_source_id: str = "",
) -> dict:
    if lane not in {*SOURCE_LANE_EVENTS, "system"}:
        raise SourceError("unsupported source lane")
    if lane == "system" and (
        source_type != "tool" or media_type != "application/json"
        or not _system_evidence_ref(source_ref)
        or activation_key is not None or feed_receipt is not None or origin_source_id
    ):
        raise SourceError("System capture requires the fixed controller identity")
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
        if feed_receipt is not None:
            result["feed_item_created"] = INDEX.record_feed_item(
                feed_receipt["feed_id"], feed_receipt["item_key"], result, feed_receipt["destination_ref"],
                feed_receipt.get("distill_instructions", ""),
            )
        if existing.get("event_key") and existing.get("event_dispatched_at") is None:
            result["source_event"] = _source_event(existing)
        else:
            result["source_event"] = None
        return result
    material = render_raw_source(source)
    material_sha256 = _material_sha256(material)
    relative = _relative_path(source, lane)
    if lane == "system":
        _safe_path(relative)
    event = SOURCE_LANE_EVENTS.get(lane)
    durable_event_key = (activation_key or f"{event}:{source.source_id}") if event else None
    if event and not durable_event_key.startswith(event + ":"):
        raise SourceError("source activation key does not match its physical lane")
    # Commit the immutable bytes and pending event to the ledger first. If the
    # process stops before the physical write or event dispatch, the ordinary
    # Source reconciliation/read restores the exact file; event-bearing lanes
    # also resume their ordinary pending-event dispatch once.
    feed_item_created = INDEX.record_source(
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
        **({"feed_receipt": feed_receipt} if feed_receipt is not None else {}),
        **({"origin_source_id": origin_source_id} if origin_source_id else {}),
    )
    row = INDEX.source(source.source_id)
    if not row:
        raise SourceError("source ledger failed to retain the new source")
    status = _restore(row)
    return {
        **_row_doc(row, include_content=True, status=status),
        "created": True,
        **({"feed_item_created": bool(feed_item_created)} if feed_receipt is not None else {}),
        "source_event": _source_event(row) if event else None,
    }


def capture_system_evidence(category: str, facts: dict) -> dict:
    """Capture one controller-observed inventory version without model work.

    This is an internal Source owner operation. Ordinary ingestion retains its
    mandatory Source event and cannot select this physical lane.
    """
    if not _system_evidence_category(category) or not isinstance(facts, dict):
        raise SourceError("System evidence requires one fixed category and JSON facts")
    if category.startswith("schema."):
        from .system_schema import system_schema
        if category not in {"schema." + row["key"].replace("/", ".") for row in system_schema()}:
            raise SourceError("System evidence requires a current schema node")
    try:
        content = json.dumps({"schema": "obsidience.system-evidence.v1", "category": category, "facts": facts},
                             ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise SourceError("System evidence must contain finite JSON facts") from exc
    if len(content.encode("utf-8")) > MAX_SOURCE_CHARS:
        raise SourceError("System evidence exceeds the Source bound")
    with _SOURCE_LOCK:
        return _capture_source(lane="system", source_type="tool", source_ref=f"system://{category}",
                               media_type="application/json", captured_at=None, content=content)


def ingest_source(
    *, source_type: str, source_ref: str, media_type: str,
    captured_at: str | None, content: str, activation_key: str | None = None,
    feed_receipt: dict | None = None,
) -> dict:
    """Preserve raw evidence and emit its ordinary ``source.added`` trigger."""
    if feed_receipt is not None:
        if (not isinstance(feed_receipt, dict)
                or set(feed_receipt) not in ({"feed_id", "item_key", "destination_ref"},
                                            {"feed_id", "item_key", "destination_ref", "distill_instructions"})
                or not all(isinstance(feed_receipt[key], str) and feed_receipt[key]
                           for key in ("feed_id", "item_key", "destination_ref"))
                or re.fullmatch(r"[0-9a-f]{32}", feed_receipt["feed_id"]) is None
                or re.fullmatch(r"[0-9a-f]{64}", feed_receipt["item_key"]) is None
                or source_ref != f"feed://{feed_receipt['feed_id']}/{feed_receipt['item_key']}"
                or source_type != "document" or media_type != "application/json"
                or activation_key is not None):
            raise SourceError("Feed receipt requires exact controller item identity")
        feed_receipt = {**feed_receipt, "distill_instructions": normalize_distill_instructions(
            feed_receipt.get("distill_instructions", ""))}
    with _SOURCE_LOCK:
        return _capture_source(
            lane="raw",
            source_type=source_type,
            source_ref=source_ref,
            media_type=media_type,
            captured_at=captured_at,
            content=content,
            activation_key=activation_key,
            feed_receipt=feed_receipt,
        )


def _research_owner(task_ref: str, run_id: str) -> bool:
    from .index import INDEX
    from .vault import load_note

    task = load_note(task_ref + ".md")
    if (not task or task.kind != "task" or not task_ref.startswith("Tasks/research/")
            or str(task.meta.get("assignee", "")) != "[[Agents/Darwin/Darwin]]"):
        return False
    if task.meta.get("status") == "running" and task.meta.get("last_run") == run_id:
        return True
    execution = INDEX.run(run_id)
    return bool(execution and execution.get("task_ref") == task_ref)


def research_handoff_origin(params: dict) -> dict | None:
    """Attest an Inbox occurrence's research origin against immutable Source."""
    from .index import INDEX

    row = INDEX.source(str(params.get("source_id", "")))
    if not row or not str(row.get("path", "")).startswith("inbox/"):
        return None
    event_key = str(row.get("event_key", ""))
    if not event_key.startswith("source.inbox:research:") or params.get("activation_key") != event_key:
        return None
    material = bytes(row["material"])
    if _material_sha256(material) != row["material_sha256"]:
        return None
    try:
        source = parse_raw_source(material)
    except SourceError:
        return None
    if (source.source_id != params.get("source_id")
            or source.content_sha256 != params.get("source_sha256")):
        return None
    parts = event_key.split(":", 4)
    if len(parts) != 5:
        return None
    if not _research_owner(parts[3], parts[2]):
        # Historical evidence keeps its original executor after a definition
        # retires. This read-only attestation grants no new handoff authority.
        from .vault import load_note

        task_ref, run_id = parts[3], parts[2]
        execution = INDEX.run(run_id)
        archived = load_note("_archived/" + task_ref + ".md") if (
            task_ref.startswith("Tasks/research/") and ".." not in task_ref.split("/")
        ) else None
        if (not archived or archived.kind != "task"
                or archived.meta.get("article_status") != "deprecated"
                or archived.meta.get("archived_from") != task_ref
                or str(archived.meta.get("assignee", "")) != "[[Agents/Darwin/Darwin]]"
                or not execution or execution.get("task_ref") != task_ref
                or execution.get("agent") != "Darwin"):
            return None
    origin = {"research_task": parts[3], "research_run_id": parts[2]}
    return origin if all(params.get(key) == value for key, value in origin.items()) else None


def handoff_source(*, title: str, content: str, captured_at: str | None = None,
                   research_task: str = "", research_run_id: str = "",
                   feed_source_id: str = "") -> dict:
    """Drop Darwin's cited synthesis into the physical Source Inbox."""
    citations = validate_source_citations(content, required=True)
    if feed_source_id:
        binding = feed_source_binding(feed_source_id)
        if (research_task != DISTILL_TASK or binding is None
                or not any(item["id"] == feed_source_id for item in citations)):
            raise SourceError("Distill handoff requires its exact controller-bound Feed Source")
    activation_key = None
    if research_task or research_run_id:
        if not research_run_id or not _research_owner(research_task, research_run_id):
            raise SourceError("Inbox requires the exact Darwin research execution")
        # Include content identity: multiple findings from one execution remain
        # distinct Inbox items, while retries of the same finding are idempotent.
        identity = hashlib.sha256((feed_source_id or content).encode()).hexdigest()[:20]
        activation_key = f"source.inbox:research:{research_run_id}:{research_task}:{identity}"
    with _SOURCE_LOCK:
        if feed_source_id:
            from .index import INDEX

            previous = INDEX.source_by_event_key(activation_key)
            if previous:
                original = parse_raw_source(bytes(previous["material"]))
                if (original.source_ref != _text(title, "title", 300)
                        or original.content != _text(content, "content", MAX_SOURCE_CHARS)
                        or previous.get("origin_source_id") != feed_source_id):
                    raise SourceError("This Distill execution already handed off its item; a different handoff cannot be replayed")
        result = _capture_source(
            lane="inbox",
            source_type="research",
            source_ref=_text(title, "title", 300),
            media_type="text/markdown",
            captured_at=captured_at,
            content=content,
            activation_key=activation_key,
            origin_source_id=feed_source_id,
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
    for lane in (*SOURCE_LANE_EVENTS, "system"):
        lane_root = CONFIG.source_dir / lane
        if lane_root.exists():
            for path in sorted(lane_root.rglob("*.md")):
                relative = ("system/" + path.relative_to(lane_root).as_posix()) if lane == "system" else str(path.relative_to(CONFIG.source_dir))
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
    resources = [item.get("resource", "") if isinstance(item, dict) else item for item in values]
    return [item.strip() for item in resources if isinstance(item, str) and item.strip()]


def _safe_linked_source(value: str) -> Path:
    """Resolve only an explicit accepted-Article link inside this project."""
    try:
        uri = urlsplit(value)
    except ValueError as exc:
        raise SourceError("invalid linked source URL") from exc
    if uri.scheme == "file":
        if uri.netloc not in {"", "localhost"} or uri.query or uri.fragment:
            raise SourceError("linked file resource must be local")
        try:
            relative = Path(unquote(uri.path)).relative_to(CONFIG.project_root.resolve())
        except ValueError as exc:
            raise SourceError("linked source escapes the project") from exc
    else:
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
    if path.suffix.lower() == ".qml":
        return "text/x-qml"
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _system_file_metadata() -> dict:
    from .system_schema import system_source_metadata
    try:
        return system_source_metadata()
    except (OSError, ValueError) as exc:
        # A schema fault blocks publication, never inspection of the
        # physical files needed to correct it or the rest of Source.
        return {"": {"system_schema_error": str(exc)[:200]}}


def _path_record(
    *,
    key: str,
    actual: Path,
    storage: str,
    articles: list[str] | None = None,
    system_metadata: dict | None = None,
) -> dict:
    stat = actual.stat()
    record = {
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
    if storage == "system":
        schema = _system_file_metadata() if system_metadata is None else system_metadata
        record.update(schema.get(key, schema.get("", {})))
    return record


def _source_metadata() -> tuple[dict, dict, dict, list[dict]]:
    """Validate all accepted file references, independently of a listing page."""
    from .vault import iter_notes

    notes = list(iter_notes())
    accepted_by_path = {Path(note.path).as_posix(): note.ref for note in notes}
    linked: dict[Path, set[str]] = {}
    citations: dict[str, set[str]] = {}
    issues: list[dict] = []
    for note in notes:
        values = [
            *_article_source_values(note.meta.get("source")),
            *_article_source_values(note.meta.get("resource")),
            *_article_source_values(note.meta.get("sources")),
        ]
        for value in values:
            # Documentary URLs are provenance, not files or permission to fetch.
            try:
                uri = urlsplit(value)
            except ValueError:
                issues.append({"path": value, "status": "missing", "detail": "Invalid resource URL"})
                continue
            if uri.scheme and uri.scheme != "file":
                if uri.scheme == "source":
                    citations.setdefault(uri.netloc.lower(), set()).add(note.ref)
                continue
            try:
                actual = _safe_linked_source(value)
            except SourceError as exc:
                issues.append({"path": value, "status": "missing", "detail": f"[[{note.ref}]]: {exc}"})
                continue
            linked.setdefault(actual, set()).add(note.ref)

        for match in _SOURCE_CITATION.finditer(note.body):
            citations.setdefault(match.group("id").lower(), set()).add(note.ref)
    return accepted_by_path, linked, citations, issues


def _source_roots() -> list[tuple[Path, str]]:
    return [
        (CONFIG.source_dir, "blob"), (CONFIG.vault_dir, "knowledge"),
        (CONFIG.system_dir, "system"),
        *((CONFIG.project_root / root, "code") for root in PROJECT_SOURCE_ROOTS),
    ]


def _source_storage(actual: Path) -> str | None:
    """Classify ordinary exposed files; accepted explicit links are separate."""
    for root, storage in _source_roots():
        if not actual.is_relative_to(root):
            continue
        relative = actual.relative_to(root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if storage == "code" and (
            "__pycache__" in relative.parts
            or actual.suffix.lower() not in PROJECT_SOURCE_SUFFIXES
        ):
            continue
        return storage
    if actual.relative_to(CONFIG.project_root) in PROJECT_SOURCE_FILES:
        return "code"
    return None


def _source_candidates(linked: dict[Path, set[str]], scope: str | None = None):
    """Walk existing roots without constructing an unbounded file catalog."""
    project_root = CONFIG.project_root.resolve()
    for root, storage in _source_roots():
        if root.is_symlink() or not root.is_dir() or not root.is_relative_to(project_root):
            continue
        walk_root = root
        if scope:
            target = project_root / scope
            if target.is_relative_to(root):
                relative = target.relative_to(root)
                if any(part.startswith(".") or (storage == "code" and part == "__pycache__")
                       or (root / Path(*relative.parts[:index + 1])).is_symlink()
                       for index, part in enumerate(relative.parts)):
                    continue
                walk_root = target
            elif not root.is_relative_to(target):
                continue
        walk = ([(str(walk_root.parent), [], [walk_root.name])] if walk_root.is_file()
                else os.walk(walk_root, followlinks=False))
        for directory, folders, files in walk:
            folders[:] = [name for name in folders if not name.startswith(".")
                          and not (storage == "code" and name == "__pycache__")
                          and not (Path(directory) / name).is_symlink()]
            for name in files:
                actual = Path(directory) / name
                if name.startswith(".") or actual.is_symlink() or not actual.is_file():
                    continue
                if storage == "code" and actual.suffix.lower() not in PROJECT_SOURCE_SUFFIXES:
                    continue
                yield actual.relative_to(project_root).as_posix(), actual, storage
    for relative in PROJECT_SOURCE_FILES:
        actual = project_root / relative
        # These fixed entrypoints may lack an extension or be hidden. Avoid
        # repeating files already emitted by a normal project root.
        in_tree = any(actual.is_relative_to(project_root / root)
                      for root in PROJECT_SOURCE_ROOTS)
        if in_tree and actual.suffix.lower() in PROJECT_SOURCE_SUFFIXES:
            continue
        if actual.is_file() and not actual.is_symlink():
            yield relative.as_posix(), actual, "code"
    for actual in linked:
        if _source_storage(actual) is None:
            yield actual.relative_to(project_root).as_posix(), actual, "code"


def _attest_system_file(actual: Path, material: bytes) -> str:
    """Reader attestation never repairs or rewrites the immutable evidence."""
    from .index import INDEX

    try:
        captured = parse_raw_source(material)
        row = INDEX.source(captured.source_id)
        if (not row or not str(row["path"]).startswith("system/")
                or _safe_path(row["path"]) != actual
                or _attested_material(row) != material):
            raise SourceError("System evidence does not match its ledger")
    except SourceError as exc:
        raise SourceError("Immutable System evidence mismatch; controller refresh must restore its captured bytes") from exc
    return captured.source_id


def _source_record(key: str, actual: Path, storage: str, metadata: tuple, system_metadata: dict | None = None) -> dict:
    accepted, linked, citations, _issues = metadata
    refs = set(linked.get(actual, ()))
    if storage == "knowledge":
        ref = accepted.get(actual.relative_to(CONFIG.vault_dir).as_posix())
        if ref:
            refs.add(ref)
    record = _path_record(key=key, actual=actual, storage=storage, system_metadata=system_metadata)
    if storage == "blob" and actual.is_relative_to(CONFIG.source_dir / "system"):
        try:
            if record["size"] > MAX_SOURCE_PREVIEW_BYTES:
                raise SourceError("Immutable System evidence exceeds the Reader bound")
            source_id = _attest_system_file(actual, actual.read_bytes())
            record["source_id"] = source_id
            refs.update(citations.get(source_id, ()))
        except (SourceError, OSError):
            # Preserve navigation to a damaged physical file, without using
            # its unverified citation or accepting bytes as captured evidence.
            record["integrity"] = "mismatch"
            refs.clear()
    elif storage == "blob" and actual.suffix.lower() == ".md" and record["size"] <= MAX_SOURCE_PREVIEW_BYTES:
        try:
            source_id = parse_raw_source(actual.read_bytes()).source_id
            refs.update(citations.get(source_id, ()))
        except SourceError:
            pass
    record["articles"] = sorted(refs)
    return record


def list_source_files(*, scope: str | None = None, after: str | None = None,
                      limit: int = MAX_SOURCE_FILES) -> dict:
    """Return one bounded live page; listing coverage is not a Source fault."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_SOURCE_FILES:
        raise SourceError(f"source page limit must be between 1 and {MAX_SOURCE_FILES}")
    scope = normalize_source_tree(scope) if scope is not None else None
    if after is not None:
        path = Path(after)
        if not after or path.is_absolute() or ".." in path.parts or path.as_posix() != after:
            raise SourceError("source cursor must be an exact project-relative path")
        if scope and after != scope and not after.startswith(scope + "/"):
            raise SourceError("source cursor must belong to its scope")
    metadata = _source_metadata()
    candidates = (
        candidate for candidate in _source_candidates(metadata[1], scope)
        if (scope is None or candidate[0] == scope or candidate[0].startswith(scope + "/"))
        and (after is None or (candidate[0].casefold(), candidate[0]) > (after.casefold(), after))
    )
    page = heapq.nsmallest(limit + 1, candidates, key=lambda row: (row[0].casefold(), row[0]))
    complete = len(page) <= limit
    schema = _system_file_metadata() if any(row[2] == "system" for row in page[:limit]) else {}
    files = [_source_record(*row, metadata, schema) for row in page[:limit]]
    issues = [*metadata[3], *({"path": row["key"], "status": "integrity_mismatch",
        "detail": "Immutable System evidence could not be attested; Reader content is unavailable."}
        for row in files if row.get("integrity") == "mismatch")]
    return {"files": files, "issues": issues, "coverage": {
        "scope": scope, "limit": limit, "returned": len(files),
        "complete": complete, "next_cursor": None if complete else files[-1]["key"],
        "consistency": "live",
    }}


def get_source_file(key: str) -> dict:
    relative = Path(key)
    if not key or relative.is_absolute() or ".." in relative.parts or relative.as_posix() != key:
        raise SourceError("source file not found")
    source_path = CONFIG.project_root.resolve() / relative
    if (not source_path.is_file()
            or any((CONFIG.project_root / Path(*relative.parts[:length])).is_symlink()
                   for length in range(1, len(relative.parts) + 1))):
        raise SourceError("source file not found")
    metadata = _source_metadata()
    storage = _source_storage(source_path)
    if storage is None and source_path not in metadata[1]:
        raise SourceError("source file not found")
    record = _source_record(key, source_path, storage or "code", metadata)
    complete = source_path.read_bytes()
    if storage == "blob" and source_path.is_relative_to(CONFIG.source_dir / "system"):
        _attest_system_file(source_path, complete)
    size = len(complete)
    material = complete[:MAX_SOURCE_PREVIEW_BYTES]
    media_type = str(record["media_type"])
    textual = media_type.startswith("text/") or media_type == "application/json" or Path(str(record["name"])).suffix.lower() in {
        ".py", ".pyi", ".md", ".json", ".toml", ".yaml", ".yml", ".csv", ".ts", ".tsx", ".js", ".jsx", ".css", ".html", ".sh", ".svg",
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
    """Check one exact scoped page, independent of unrelated Source volume."""
    scope = normalize_source_tree(value)
    files = list_source_files(scope=scope, limit=1)["files"]
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
    for scope in scopes:
        after = None
        while True:
            page = list_source_files(scope=scope, after=after)
            for row in page["files"]:
                key = str(row["key"])
                if key == scope or key.startswith(scope + "/"):
                    refs.update(str(ref) for ref in row.get("articles", []))
            after = page.get("coverage", {}).get("next_cursor")
            if after is None:
                break

    # Exact schema ownership, including absorbed directory hubs. System scope
    # never grants unrelated authored workstation Observations.
    if any(scope == "obsidience/state/system" or scope.startswith("obsidience/state/system/") for scope in scopes):
        from .system import system_articles
        from .vault import iter_notes
        accepted = {note.ref for note in iter_notes()}
        for row in system_articles().values():
            if any(component["path"] == scope or component["path"].startswith(scope + "/")
                   or component["descriptor_path"] == scope
                   for component in (row, *row.get("components", [])) for scope in scopes):
                if row["ref"] in accepted:
                    refs.add(row["ref"])
    return sorted(refs)
