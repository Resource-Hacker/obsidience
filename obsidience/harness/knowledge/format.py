"""The Obsidience Article profile, layered on the OKF document contract.

``okf`` owns framing, serialization and conformance of the portable document.
This module adds what makes a document an Article: the six types, the
``obsidience`` namespace, the flat application view, and Task-ledger
separation. Parsing does not admit an Article, verify a claim, or authorize
execution. ``verified`` and the other foreign assertions remain ordinary
document data. The profile is checked separately, before the caller accepts
an Article.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import okf


ARTICLE_TYPES = frozenset({"knowledge", "task", "runbook", "skill", "tool", "agent"})
TASK_RUNTIME_FIELDS = frozenset({
    "status", "params", "event_queue", "status_updated", "triggered_at", "activation_id",
    "last_run", "summary", "blocked_reason", "generated_runbook",
})
# Only known application fields move between the flat runtime view and the
# namespace. Unknown fields retain their original root/namespace placement.
OBSIDIENCE_FIELDS = frozenset({
    "knowledge", "exclude_knowledge", "required_context", "relations", "context_role",
    "operation_tools", "runtime_sections", "requires",
    "acceptance", "action", "agent", "approved_at", "archive_reason", "archived_at", "articles", "assignee",
    "authored_fields", "optimization_auto_apply", "auto_curate", "auto_done", "base_sha256", "binding",
    "conversation_id", "curation_task", "enabled", "event_context", "exclude_subtasks", "expires_at",
    "for_agent", "generated_by", "immediate", "invalidated_at",
    "invalidated_reason", "label", "latest_sequence", "link_evidence", "links",
    "model", "name", "node", "observation_scope", "observed_at", "owner_maintained",
    "parent", "promotion_key", "promotion_pending", "proposal", "proposal_body_sha256",
    "proposed_at", "provenance", "purpose", "reader_ref", "reason", "reasoning_effort",
    "rejected_at", "rejected_reason", "related_refs", "research_task", "retrieval",
    "review_class", "review_due", "role", "run_id", "runbook", "runbooks",
    "schedule", "skills", "source", "source_archive", "source_archive_sha256",
    "source_archived_at", "source_article_sha256", "source_conversation_id",
    "source_trees", "source_turn_id", "subrunbooks", "subskills", "subtasks",
    "subtools", "superseded_by", "target", "task", "tasks", "taxonomy_path",
    "temporary", "through_sequence", "tool", "tools", "transient", "triggers", "trust",
}) | TASK_RUNTIME_FIELDS


def _namespace(meta: dict[str, Any]) -> dict[str, Any]:
    value = meta.pop("obsidience", {})
    if not isinstance(value, Mapping):
        raise ValueError("obsidience must be a mapping")
    return dict(value)


def decode_metadata(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Project canonical metadata to the existing flat, application-only view.

    ``kind`` and ``article_status`` are internal aliases for ``type`` and the
    common OKF ``status``. A legacy document with only ``kind`` keeps its old
    local ``status`` semantics for the caller's explicit migration policy.
    No ``summary``/``description`` or verification/trust inference is made.
    """
    meta = deepcopy(dict(raw))
    namespace = _namespace(meta)
    if "type" in meta:
        article_type = meta.pop("type")
        if "kind" in meta and meta["kind"] != article_type:
            raise ValueError("Conflicting type and kind")
        meta["kind"] = article_type
        if "status" in meta:
            status = meta.pop("status")
            if "article_status" in meta and meta["article_status"] != status:
                raise ValueError("Conflicting status and article_status")
            meta["article_status"] = status
    for key in list(namespace):
        if key not in OBSIDIENCE_FIELDS:
            continue
        value = namespace.pop(key)
        if key in meta and meta[key] != value:
            raise ValueError(f"Conflicting root and obsidience.{key}")
        meta[key] = value
    if namespace:
        meta["obsidience"] = namespace
    return meta


def encode_metadata(flat: Mapping[str, Any]) -> dict[str, Any]:
    """Write canonical metadata, excluding execution state from Task Articles.

    The caller must supply a kind/type; path-based legacy inference belongs to
    migration. Obsidience's local lifecycle status is not silently relabeled as
    an OKF lifecycle assertion. Only ``article_status`` supplies root ``status``.
    """
    meta = deepcopy(dict(flat))
    namespace = _namespace(meta)
    kind = meta.pop("kind", meta.get("type"))
    existing_type = meta.pop("type", kind)
    if kind != existing_type:
        raise ValueError("Conflicting type and kind")
    if not isinstance(kind, str) or not kind.strip():
        raise ValueError("Article kind/type must be a nonempty string")
    canonical: dict[str, Any] = {"type": kind}
    if "article_status" in meta:
        canonical["status"] = meta.pop("article_status")
    for key, value in meta.items():
        if kind == "task" and key in TASK_RUNTIME_FIELDS:
            continue
        if key in OBSIDIENCE_FIELDS:
            # The flat value is the application's current mutable projection.
            namespace[key] = value
        else:
            canonical[key] = value
    if kind == "task":
        for key in TASK_RUNTIME_FIELDS:
            namespace.pop(key, None)
    # Internal aliases must never survive as a second persisted type/status.
    for key in ("kind", "type", "article_status"):
        if key in namespace:
            raise ValueError(f"obsidience.{key} is reserved")
    if namespace:
        canonical["obsidience"] = namespace
    return canonical


def loads(text: str) -> tuple[dict[str, Any], str]:
    raw, body = okf.parse(text)
    return decode_metadata(raw), body


def dumps(meta: Mapping[str, Any], body: str) -> str:
    return okf.serialize(encode_metadata(meta), body)


def lifecycle_metadata(meta: Mapping[str, Any], now: datetime | None = None) -> dict[str, str]:
    """Project document freshness, never Task execution status or verification."""
    status = meta.get("article_status", "stable")
    if status not in okf.LIFECYCLE_STATUSES:
        return {"freshness": "unknown"}
    result = {"status": status, "freshness": "deprecated" if status == "deprecated" else "current"}
    if "stale_after" in meta:
        value = meta["stale_after"]
        if not okf.is_timestamp(value):
            result["freshness"] = "deprecated" if status == "deprecated" else "unknown"
        else:
            stale = okf.timestamp(value)
            result["stale_after"] = stale.isoformat()
            if status != "deprecated" and stale <= (now or datetime.now(timezone.utc)):
                result["freshness"] = "stale"
    return result


def validate_profile(raw: Mapping[str, Any], path: str | Path | None = None) -> list[str]:
    """Return Article-admission errors, never inferred trust or execution rights.

    Unknown fields are valid. The six Article types and their optional common
    field shapes are the local profile; generic OKF documents remain parsable.
    Reserved navigation/history filenames are not Article concepts.
    """
    errors: list[str] = []
    if path is not None and okf.is_reserved(path):
        errors.append("index.md and log.md are reserved OKF documents, not Articles")
    kind = raw.get("type")
    if not isinstance(kind, str) or kind not in ARTICLE_TYPES:
        errors.append("type must be one of: " + ", ".join(sorted(ARTICLE_TYPES)))
    for key in ("kind", "article_status"):
        if key in raw:
            errors.append(f"{key} is an internal alias, not canonical OKF metadata")
    for key in ("title", "description", "resource"):
        if key in raw and not isinstance(raw[key], str):
            errors.append(f"{key} must be a string")
    if "tags" in raw and (not isinstance(raw["tags"], list)
                          or any(not isinstance(tag, str) for tag in raw["tags"])):
        errors.append("tags must be a list of strings")
    if "status" in raw and raw["status"] not in okf.LIFECYCLE_STATUSES:
        errors.append("status must be draft, stable, or deprecated")
    if "stale_after" in raw and not okf.is_timestamp(raw["stale_after"]):
        errors.append("stale_after must be an ISO 8601 timestamp with a timezone")

    def event(value: Any, label: str) -> None:
        if not isinstance(value, Mapping):
            errors.append(f"{label} must be a mapping")
            return
        if not isinstance(value.get("by"), str) or not value["by"].strip():
            errors.append(f"{label}.by must be a nonempty string")
        if "at" in value and not okf.is_timestamp(value["at"]):
            errors.append(f"{label}.at must be an ISO 8601 timestamp with a timezone")

    if "generated" in raw:
        event(raw["generated"], "generated")
    if "verified" in raw:
        verified = raw["verified"]
        if isinstance(verified, Mapping):
            verified = [verified]
        if not isinstance(verified, list):
            errors.append("verified must be a mapping or list of mappings")
        else:
            for i, value in enumerate(verified):
                event(value, f"verified[{i}]")
    if "usage_window" in raw and not isinstance(raw["usage_window"], Mapping):
        errors.append("usage_window must be a mapping")
    if "sources" in raw:
        sources = raw["sources"]
        if not isinstance(sources, list):
            errors.append("sources must be a list of mappings")
        else:
            for i, source in enumerate(sources):
                if not isinstance(source, Mapping):
                    errors.append(f"sources[{i}] must be a mapping")
                elif not isinstance(source.get("resource"), str) or not source["resource"].strip():
                    errors.append(f"sources[{i}].resource must be a nonempty string")
    namespace = raw.get("obsidience", {})
    if not isinstance(namespace, Mapping):
        errors.append("obsidience must be a mapping")
    else:
        for key in (okf.SPEC_FIELDS - {"status"}) | {"kind", "article_status"}:
            if key in namespace:
                errors.append(f"obsidience.{key} is reserved for canonical root metadata")
        if kind == "task":
            for key in sorted(TASK_RUNTIME_FIELDS & namespace.keys()):
                errors.append(f"obsidience.{key} is Task execution state, not Article metadata")
        if kind == "agent":
            for key in ("tools", "runbook", "runbooks"):
                if key in namespace:
                    errors.append(f"Agent {key} is derived; standing instructions belong to identity and capabilities to Skills")
            if "skills" in namespace and (not isinstance(namespace["skills"], list)
                    or len(namespace["skills"]) > 128
                    or any(not isinstance(ref, str) or not ref.startswith("[[Skills/")
                           or not ref.endswith("]]") for ref in namespace["skills"])):
                errors.append("Agent skills require bounded exact Skill references")
        if "requires" in namespace:
            requirements = namespace["requires"]
            if (kind != "skill" or not isinstance(requirements, list) or len(requirements) > 24
                    or any(not isinstance(ref, str) or not ref.startswith("[[Skills/")
                           or not ref.endswith("]]") for ref in requirements)):
                errors.append("Skill requires must contain bounded exact Skill prerequisites")
    if isinstance(namespace, Mapping):
        from .links import metadata_ref
        for key in ("knowledge", "exclude_knowledge", "required_context"):
            values = namespace.get(key, [])
            if (not isinstance(values, list) or len(values) > (16 if key == "required_context" else 128)
                    or any(not isinstance(value, str) or len(value) > 512
                           or not metadata_ref(value) or metadata_ref(value).startswith("@")
                           or any(part in {"", ".", ".."} for part in metadata_ref(value).split("/"))
                           for value in values)):
                errors.append(f"obsidience.{key} requires bounded exact Article references")
        if "context_role" in namespace and namespace["context_role"] not in {
            "constraint", "decision", "inventory", "reference", "working",
        }:
            errors.append("obsidience.context_role is not a recognized Knowledge role")
        for key in ("operation_tools", "runtime_sections"):
            values = namespace.get(key, {})
            if not isinstance(values, Mapping) or len(values) > 12:
                errors.append(f"obsidience.{key} requires a bounded operation mapping")
            elif key == "runtime_sections" and any(not isinstance(value, str) or not 1 <= len(value) <= 120 for value in values.values()):
                errors.append("runtime section names must be bounded text")
            elif key == "operation_tools" and any(not isinstance(value, list) or len(value) > 32
                    or any(not isinstance(ref, str) or not metadata_ref(ref).startswith("Tools/") for ref in value)
                    for value in values.values()):
                errors.append("operation tools require exact Tool reference lists")
    for key in sorted((OBSIDIENCE_FIELDS - okf.SPEC_FIELDS) & raw.keys()):
        errors.append(f"{key} belongs under obsidience, not at the root")
    return errors
