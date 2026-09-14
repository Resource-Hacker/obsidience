"""Observation lifecycles and completed-turn events for graph-native Obsidience.

The Executive conversation projects into ``Current conversation`` beneath the
``Immediate Observations`` index Article. Compact turns its prefix into a cumulative Temporary
Observation Article while SQLite retains the exact public turns. Other completed
work may still emit ``turn.complete`` for owner-enabled observation Tasks.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import CONFIG
from ..knowledge.links import metadata_ref
from ..knowledge.tasks import task_triggers
from ..knowledge.auto_curate import enabled as auto_curate_enabled
from ..knowledge.vault import Note, Resolver, load_note, resolver, slugify, write_note, _NOTE_WRITE_LOCK

TURN_COMPLETE_EVENT = "turn.complete"
TEMPORARY_MAX_ENTRIES = 10
TEMPORARY_MAX_ENTRY_CHARS = 2_000
TEMPORARY_MAX_TOTAL_CHARS = 20_000
TEMPORARY_TTL_SECONDS = 24 * 60 * 60
IMMEDIATE_OBSERVATIONS_PATH = Path(
    "Agents/Executive/Observations/Immediate Observations/current-conversation.md"
)
IMMEDIATE_OBSERVATIONS_REF = str(IMMEDIATE_OBSERVATIONS_PATH.with_suffix(""))
IMMEDIATE_COMPACT_TASK_REF = "Tasks/observations/immediate/compact"
TEMPORARY_PROMOTION_EVENT = "observations.temporary.ready"
TEMPORARY_PROMOTION_TASK_REF = "Tasks/observations/durable/promote"
EXECUTIVE_TEMPORARY_PATH = Path(
    "Agents/Executive/Observations/Temporary Observations"
)

_SECRET_PATTERNS = (
    re.compile(r"\b(?:sk|pk)-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}", re.IGNORECASE),
    re.compile(
        r"(?i)\b(api[_ -]?key|token|password|secret|credential)\b\s*[:=]\s*[^\s,;]+"
    ),
    re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s/:]+:[^\s/@]+@"),
)
_WRITE_LOCK = threading.Lock()
_AGENT_LOCKS: dict[str, asyncio.Lock] = {}
_BACKGROUND_TASKS: set[asyncio.Task] = set()
_QUEUED_TURNS: set[tuple[str, str]] = set()


def _enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "no", "off", "0"}
    return value is not False


def _redact(value: object, limit: int) -> str:
    text = str(value or "").strip()
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub("[REDACTED]", text)
    if len(text) > limit:
        text = text[: max(0, limit - 14)].rstrip() + "\n[truncated]"
    return text


_COMPACTION_SECTIONS = ("Goal", "Constraints and corrections", "Verified state", "Outstanding")
_COMPACTION_HEADING = re.compile(
    r"^(?:\#{1,6}[ \t]+)?(Goal|Constraints and corrections|Verified state|Outstanding)"
    r"(?:[ \t]*:[ \t]*|[ \t]*(?=\n|$))", re.MULTILINE,
)


def _valid_compaction_text(text: str) -> bool:
    """Enforce the Compact Runbook's complete section contract, not its truth."""
    if not text or len(text) > TEMPORARY_MAX_ENTRY_CHARS or _redact(text, TEMPORARY_MAX_ENTRY_CHARS) != text:
        return False
    headings = list(_COMPACTION_HEADING.finditer(text))
    if tuple(match.group(1) for match in headings) != _COMPACTION_SECTIONS:
        return False
    if text[:headings[0].start()].strip():
        return False
    return all(
        text[match.end():headings[index + 1].start() if index + 1 < len(headings) else len(text)].strip()
        for index, match in enumerate(headings)
    )


def _temporary_dir(value: object) -> Path:
    raw = str(value or "").strip().replace("\\", "/").strip("/")
    path = Path(raw)
    if (
        not raw
        or path.is_absolute()
        or any(part in {"", ".", ".."} or part.startswith(".") for part in path.parts)
        or path.name != "Temporary Observations"
        or "Observations" not in path.parts
    ):
        raise ValueError("temporary observation target is invalid")
    return path


def _temporary_notes(target_path: str | Path) -> list:
    directory = CONFIG.vault_dir / _temporary_dir(target_path)
    if not directory.exists():
        return []
    notes = []
    for path in directory.glob("*.md"):
        note = load_note(path.relative_to(CONFIG.vault_dir))
        if note and note.meta.get("temporary") is True:
            notes.append(note)
    return sorted(
        notes,
        key=lambda note: str(note.meta.get("observed_at", "")),
        reverse=True,
    )


def _prune_temporary(
    target_path: str | Path,
    *,
    active_conversation_id: str | None = None,
    remove_expired: bool = True,
) -> tuple[int, list]:
    target = _temporary_dir(target_path)
    if active_conversation_id is None and target == EXECUTIVE_TEMPORARY_PATH:
        immediate = load_note(IMMEDIATE_OBSERVATIONS_PATH)
        if immediate and immediate.meta.get("immediate") is True:
            active_conversation_id = str(
                immediate.meta.get("conversation_id") or ""
            ).strip() or None
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=TEMPORARY_TTL_SECONDS)
    notes = _temporary_notes(target)
    # A closed session's exact inputs cannot disappear while its ordinary
    # promotion Task waits for the executor. Pending inputs temporarily sit
    # outside the live-cache limits; the normal limits apply again as soon as
    # Source archival clears ``promotion_pending``.
    retained = [
        note for note in notes
        if str(note.meta.get("promotion_pending", ""))
        and not str(note.meta.get("source_archive", ""))
    ]
    pending_refs = {note.ref for note in retained}
    active_summary = max(
        (
            note for note in notes
            if active_conversation_id
            and note.meta.get("compaction") is True
            and note.meta.get("compaction_committed") is True
            and _valid_compaction_text(note.body.strip())
            and str(note.meta.get("source_conversation_id", ""))
            == active_conversation_id
        ),
        key=lambda note: int(note.meta.get("through_sequence") or 0),
        default=None,
    )
    if active_summary is not None and active_summary not in retained:
        retained.append(active_summary)
    protected_refs = {note.ref for note in retained}
    active_counts = active_summary is not None and active_summary.ref not in pending_refs
    normal_count = int(active_counts)
    total_chars = (
        len(re.sub(r"\s+", " ", active_summary.body).strip())
        if active_counts
        else 0
    )
    removed = 0
    for note in notes:
        if note.ref in protected_refs:
            continue
        try:
            observed = datetime.fromisoformat(str(note.meta.get("observed_at", "")))
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
        except ValueError:
            observed = datetime.fromtimestamp(note.mtime, timezone.utc)
        text = re.sub(r"\s+", " ", note.body).strip()
        keep = (
            observed >= cutoff
            and normal_count < TEMPORARY_MAX_ENTRIES
            and total_chars + len(text) <= TEMPORARY_MAX_TOTAL_CHARS
        )
        if keep:
            retained.append(note)
            normal_count += 1
            total_chars += len(text)
        elif remove_expired:
            (CONFIG.vault_dir / note.path).unlink()
            removed += 1
    return removed, retained


def append_temporary_observation(args: dict, runtime: dict) -> dict:
    """Append one idempotent bounded observation to the selected node."""
    mode = str(runtime.get("curation_mode", ""))
    if mode not in {"temporary", "compaction"}:
        raise ValueError("this auto-curation Task does not target Temporary Observations")
    target = _temporary_dir(runtime.get("target_path"))
    if not auto_curate_enabled(str(target)):
        raise ValueError("Auto-curate is disabled for this Temporary Observations branch")
    if mode == "compaction" and (
        str(runtime.get("origin_task_ref", "")) != IMMEDIATE_COMPACT_TASK_REF
        or target != EXECUTIVE_TEMPORARY_PATH
    ):
        raise ValueError("context compaction requires the exact Compact Task and target")
    turn_id = slugify(str(runtime.get("turn_id") or ""))[:96]
    if not turn_id:
        raise ValueError("temporary observation requires an exact completed-turn identity")
    text = str(args.get("text") or "")
    if mode == "compaction":
        text = "\n".join(
            line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        ).strip()
    else:
        text = re.sub(r"\s+", " ", text).strip()
    maximum = TEMPORARY_MAX_ENTRY_CHARS if mode == "compaction" else 200
    if not text or len(text) > maximum:
        raise ValueError(
            f"temporary observation text must be 1-{maximum} characters"
        )
    if _redact(text, maximum) != text:
        raise ValueError("temporary observation text failed the safety policy")
    if mode == "compaction" and not _valid_compaction_text(text):
        raise ValueError(
            "context compaction requires four nonempty sections in order: "
            "Goal, Constraints and corrections, Verified state, Outstanding; "
            "the complete cumulative summary may use up to 2,000 characters"
        )

    related = []
    res = resolver()
    raw_related = args.get("related_refs") or []
    if not isinstance(raw_related, list) or len(raw_related) > 3:
        raise ValueError("related_refs must contain at most three exact article refs")
    for raw in raw_related:
        note = res.by_ref.get(metadata_ref(str(raw)).lower())
        if note is None:
            raise ValueError(f"related_ref does not resolve exactly: {raw}")
        if note.ref not in related:
            related.append(note.ref)

    now = datetime.now(timezone.utc)
    conversation_id = str(runtime.get("conversation_id") or "").strip()
    active_conversation_id = str(
        runtime.get("active_conversation_id") or ""
    ).strip() or None
    with _WRITE_LOCK:
        for note in _temporary_notes(target):
            if str(note.meta.get("source_turn_id", "")) != turn_id:
                continue
            existing_text = (
                note.body.strip()
                if mode == "compaction"
                else re.sub(r"\s+", " ", note.body).strip()
            )
            if existing_text != text:
                raise ValueError("completed turn already has a different temporary observation")
            _removed, retained = _prune_temporary(
                target,
                active_conversation_id=active_conversation_id,
            )
            return {"status": "existing", "ref": note.ref, "retained": len(retained)}

        rel = target / f"{now.strftime('%Y%m%d-%H%M%S')}-{turn_id}.md"
        through_sequence = int(runtime.get("through_sequence") or 0)
        if mode == "compaction" and (not conversation_id or through_sequence < 1):
            raise ValueError("context compaction requires conversation and sequence identity")
        note_meta = {
            "title": (
                f"Conversation summary · {now.strftime('%Y-%m-%d %H:%M:%S UTC')}"
                if mode == "compaction"
                else f"Temporary observation {now.strftime('%Y-%m-%d %H:%M:%S UTC')}"
            ),
            "kind": "knowledge",
            "observation_scope": "temporary",
            "retrieval": False,
            "temporary": True,
            "compaction": mode == "compaction",
            "compaction_committed": mode != "compaction",
            "trust": "unverified",
            "label": "transient_unverified",
            "source_turn_id": turn_id,
            "observed_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=TEMPORARY_TTL_SECONDS)).isoformat(),
            "related_refs": [f"[[{ref}]]" for ref in related],
        }
        if conversation_id:
            note_meta["source_conversation_id"] = conversation_id
        if through_sequence:
            note_meta["through_sequence"] = through_sequence
        write_note(str(rel), note_meta, text)
        removed, retained = _prune_temporary(
            target,
            active_conversation_id=active_conversation_id,
        )
    retained_refs = {note.ref for note in retained}
    entry_ref = str(rel.with_suffix(""))
    if entry_ref not in retained_refs:
        raise ValueError("temporary observation could not be retained within the Obsidience limits")
    return {"status": "appended", "ref": entry_ref, "retained": len(retained), "removed": removed}


def latest_context_compaction(
    conversation_id: str,
    *,
    active: bool = False,
    prune: bool = True,
) -> Note | None:
    """Return the newest cumulative Temporary Observation for one conversation."""
    with _WRITE_LOCK:
        _removed, retained = _prune_temporary(
            EXECUTIVE_TEMPORARY_PATH,
            active_conversation_id=conversation_id if active else None,
            remove_expired=prune,
        )
    rows = [
        note for note in retained
        if note.meta.get("compaction") is True
        and note.meta.get("compaction_committed") is True
        and _valid_compaction_text(note.body.strip())
        and str(note.meta.get("source_conversation_id", "")) == conversation_id
        and int(note.meta.get("through_sequence") or 0) > 0
    ]
    return max(rows, key=lambda note: int(note.meta.get("through_sequence") or 0), default=None)


def promoted_context_sequence(conversation_id: str, *, active: bool = False) -> int:
    """Return the greatest conversation sequence already queued for promotion."""
    with _WRITE_LOCK:
        _removed, retained = _prune_temporary(
            EXECUTIVE_TEMPORARY_PATH,
            active_conversation_id=conversation_id if active else None,
        )
    return max(
        (
            int(note.meta.get("through_sequence") or 0)
            for note in retained
            if note.meta.get("compaction") is True
            and note.meta.get("compaction_committed") is True
            and _valid_compaction_text(note.body.strip())
            and str(note.meta.get("source_conversation_id", "")) == conversation_id
            and (
                str(note.meta.get("promotion_pending", ""))
                or str(note.meta.get("promotion_key", ""))
            )
        ),
        default=0,
    )


def _committed_context_compactions(conversation_id: str) -> list[Note]:
    """Return the exact committed Temporary summaries for one conversation."""
    with _WRITE_LOCK:
        _removed, retained = _prune_temporary(EXECUTIVE_TEMPORARY_PATH)
    return sorted(
        (
            note for note in retained
            if note.meta.get("compaction") is True
            and note.meta.get("compaction_committed") is True
            and _valid_compaction_text(note.body.strip())
            and str(note.meta.get("source_conversation_id", "")) == conversation_id
            and int(note.meta.get("through_sequence") or 0) > 0
            and not str(note.meta.get("promotion_pending", ""))
            and not str(note.meta.get("promotion_key", ""))
        ),
        key=lambda note: int(note.meta.get("through_sequence") or 0),
    )


def queue_temporary_promotion(conversation_id: str, *, session_boundary: str) -> dict:
    """Queue Alexandria once when a closed session has unpromoted Temporary context."""
    exact_conversation_id = str(conversation_id).strip()
    if not exact_conversation_id:
        raise ValueError("temporary promotion requires a conversation identity")
    notes = _committed_context_compactions(exact_conversation_id)
    if not notes:
        return {"state": "not_needed", "queued": 0}
    identities = [
        {
            "ref": note.ref,
            "through_sequence": int(note.meta.get("through_sequence") or 0),
            "body_sha256": hashlib.sha256(note.body.strip().encode()).hexdigest(),
        }
        for note in notes
    ]
    promotion_key = hashlib.sha256(json.dumps(
        [exact_conversation_id, identities],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()).hexdigest()[:20]
    params = {
        "activation_key": promotion_key,
        "promotion_key": promotion_key,
        "conversation_id": exact_conversation_id,
        "temporary_refs": [note.ref for note in notes],
        "through_sequence": max(item["through_sequence"] for item in identities),
        "session_boundary": str(session_boundary)[:80],
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "agent_ref": "Agents/Executive/Executive",
        # A new closed session must wait behind an unresolved earlier review,
        # not disappear merely because the same Task owns that review.
        "queue_after_review": True,
        # Chat and Realtime execute their Tasks outside the scheduler semaphore.
        # Promotion therefore waits for the complete ordinary executor surface.
        "wait_for_idle": True,
    }
    from ..execution.scheduler import enqueue_named_event

    occurrences = enqueue_named_event(TEMPORARY_PROMOTION_EVENT, params)
    if occurrences:
        queued_at = datetime.now(timezone.utc).isoformat()
        with _WRITE_LOCK:
            for note in notes:
                current = load_note(note.path)
                if current is None:
                    raise RuntimeError(f"promotion input disappeared: {note.ref}")
                meta = dict(current.meta)
                existing = str(meta.get("promotion_pending", ""))
                if existing and existing != promotion_key:
                    raise RuntimeError(f"promotion input already belongs to {existing}")
                meta["promotion_pending"] = promotion_key
                meta["promotion_queued_at"] = queued_at
                write_note(current.path, meta, current.body)
    return {
        "state": "queued" if occurrences else "not_configured",
        "queued": len(occurrences),
        "promotion_key": promotion_key,
        "temporary_refs": params["temporary_refs"],
        "occurrences": occurrences,
    }


def resolve_temporary_promotion_inputs(
    runtime: dict, accepted_resolver: Resolver | None = None,
) -> list[Note]:
    """Validate committed promotion inputs without inference, archival or mutation.

    Existing queued inputs may predate Compact's current completeness guard.
    Execution checks them before model acquisition; archival checks fresh inputs
    again at its effect boundary through this same owner.
    """
    if (
        str(runtime.get("origin_task_ref", "")) != TEMPORARY_PROMOTION_TASK_REF
        or str(runtime.get("event", "")) != TEMPORARY_PROMOTION_EVENT
    ):
        raise ValueError("temporary archive requires the exact Promote Task event")
    conversation_id = str(runtime.get("conversation_id", "")).strip()
    promotion_key = str(runtime.get("promotion_key", "")).strip()
    raw_refs = runtime.get("temporary_refs")
    try:
        through_sequence = int(runtime.get("through_sequence") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("temporary archive sequence is invalid") from exc
    if (
        not conversation_id
        or not re.fullmatch(r"[a-f0-9]{20}", promotion_key)
        or not isinstance(raw_refs, list)
        or not 1 <= len(raw_refs) <= TEMPORARY_MAX_ENTRIES
        or through_sequence < 1
    ):
        raise ValueError("temporary archive event identity is incomplete")

    notes: list[Note] = []
    seen: set[str] = set()
    res = accepted_resolver if accepted_resolver is not None else resolver()
    for raw_ref in raw_refs:
        note = res.resolve(str(raw_ref))
        if (
            note is None
            or note.ref in seen
            or not note.ref.startswith(f"{EXECUTIVE_TEMPORARY_PATH.as_posix()}/")
            or note.kind != "knowledge"
            or note.meta.get("observation_scope") != "temporary"
            or note.meta.get("temporary") is not True
            or note.meta.get("compaction") is not True
            or note.meta.get("compaction_committed") is not True
            or not _valid_compaction_text(note.body.strip())
            or str(note.meta.get("source_conversation_id", "")) != conversation_id
            or str(note.meta.get("promotion_pending", promotion_key)) != promotion_key
            or str(note.meta.get("promotion_key", promotion_key)) != promotion_key
        ):
            raise ValueError(f"temporary archive ref is not an exact committed input: {raw_ref}")
        seen.add(note.ref)
        notes.append(note)
    notes.sort(key=lambda note: int(note.meta.get("through_sequence") or 0))
    if max(int(note.meta.get("through_sequence") or 0) for note in notes) != through_sequence:
        raise ValueError("temporary archive sequence does not match its exact inputs")
    return notes


def archive_temporary_observations(args: dict, runtime: dict) -> dict:
    """Preserve exact event-bound Temporary Article snapshots in Source."""
    if args:
        raise ValueError("temporary archive takes no model-authored arguments")
    notes = resolve_temporary_promotion_inputs(runtime)
    conversation_id = str(runtime["conversation_id"]).strip()
    promotion_key = str(runtime["promotion_key"]).strip()
    through_sequence = int(runtime["through_sequence"])

    from ..knowledge.source import get_source, ingest_source

    source_ref = (
        "obsidience://observations/temporary/"
        f"{conversation_id}/{promotion_key}"
    )
    snapshots = []
    existing_citations = {
        str(note.meta.get("source_archive", "")) for note in notes
        if str(note.meta.get("source_archive", ""))
    }
    if len(existing_citations) > 1:
        raise ValueError("temporary archive inputs point at different Source bundles")
    for note in notes:
        material = (CONFIG.vault_dir / note.path).read_bytes()
        article_sha256 = str(note.meta.get("source_article_sha256", "")) or (
            "sha256:" + hashlib.sha256(material).hexdigest()
        )
        snapshots.append({
            "note": note,
            "article_sha256": article_sha256,
            "markdown": material.decode("utf-8", errors="strict"),
        })
    if existing_citations:
        source = get_source(next(iter(existing_citations)))
        if source["source_ref"] != source_ref:
            raise ValueError("temporary archive Source identity does not match the event")
        source = {**source, "created": False}
    else:
        sections = [
            "# Temporary Observation Bundle\n\n"
            f"Conversation: {conversation_id}\n"
            f"Through sequence: {through_sequence}\n"
            f"Promotion key: {promotion_key}\n"
            f"Article count: {len(snapshots)}"
        ]
        for item in snapshots:
            note = item["note"]
            sections.append(
                f"## [[{note.ref}]]\n\n"
                f"Through sequence: {int(note.meta.get('through_sequence') or 0)}\n"
                f"Original article SHA-256: {item['article_sha256']}\n\n"
                "### Canonical Markdown\n\n"
                f"{item['markdown']}"
            )
        source = ingest_source(
            source_type="document",
            source_ref=source_ref,
            media_type="text/markdown",
            captured_at=str(notes[-1].meta.get("observed_at") or "") or None,
            content="\n\n".join(sections),
        )
    archived = []
    for item in snapshots:
        note = item["note"]
        meta = dict(note.meta)
        meta.pop("promotion_pending", None)
        meta.pop("promotion_queued_at", None)
        meta.update({
            "promotion_key": promotion_key,
            "source_archive": source["citation"],
            "source_archive_sha256": source["content_sha256"],
            "source_article_sha256": item["article_sha256"],
            "source_archived_at": datetime.now(timezone.utc).isoformat(),
        })
        write_note(note.path, meta, note.body)
        archived.append({
            "ref": note.ref,
            "article_sha256": item["article_sha256"],
        })
    return {
        "status": "archived",
        "promotion_key": promotion_key,
        "conversation_id": conversation_id,
        "through_sequence": through_sequence,
        "source": {
            "citation": source["citation"],
            "content_sha256": source["content_sha256"],
            "created": source["created"],
            "article_count": len(archived),
        },
        "articles": archived,
    }


def commit_context_compaction(
    *, conversation_id: str, through_sequence: int, turn_id: str,
) -> Note:
    """Make one exact successful Compact Tool result visible to the context."""
    with _WRITE_LOCK:
        match = next((
            note for note in _temporary_notes(EXECUTIVE_TEMPORARY_PATH)
            if note.meta.get("compaction") is True
            and str(note.meta.get("source_conversation_id", "")) == conversation_id
            and int(note.meta.get("through_sequence") or 0) == through_sequence
            and str(note.meta.get("source_turn_id", "")) == turn_id
        ), None)
        if match is None:
            raise RuntimeError("Compact completed without its pending Temporary Observation")
        if not _valid_compaction_text(match.body.strip()):
            raise RuntimeError("Compact completed without a complete four-section Temporary Observation")
        if match.meta.get("compaction_committed") is not True:
            meta = dict(match.meta)
            meta["compaction_committed"] = True
            write_note(match.path, meta, match.body)
            refreshed = load_note(match.path)
            if refreshed is None:
                raise RuntimeError("the committed Temporary Observation disappeared")
            match = refreshed
        return match


def discard_pending_context_compaction(
    *, conversation_id: str, through_sequence: int, turn_id: str,
) -> bool:
    """Remove only the uncommitted Article emitted by one failed Compact attempt."""
    with _WRITE_LOCK:
        for note in _temporary_notes(EXECUTIVE_TEMPORARY_PATH):
            if (
                note.meta.get("compaction") is True
                and note.meta.get("compaction_committed") is not True
                and str(note.meta.get("source_conversation_id", "")) == conversation_id
                and int(note.meta.get("through_sequence") or 0) == through_sequence
                and str(note.meta.get("source_turn_id", "")) == turn_id
            ):
                (CONFIG.vault_dir / note.path).unlink()
                return True
    return False


def project_activation_context(agent_ref: str, task_ref: str, activation_id: str,
                               bindings: dict, evidence: list[dict], status: str = "running", *,
                               objective: str = "", context_refs: list[str] | None = None,
                               begin: bool = False) -> dict:
    """One Agent-owned readable view of controller context, never hidden reasoning."""
    if not agent_ref.startswith("Agents/") or agent_ref.count("/") != 2 or not activation_id:
        raise ValueError("Working context requires an exact Agent and activation")
    base = agent_ref.rsplit("/", 1)[0] + "/Observations/Immediate Observations"
    path = base + "/current-activation.md"
    ref = path.removesuffix(".md")
    latest = []
    for item in evidence[-8:]:
        if not isinstance(item, dict) or not item.get("tool"):
            continue
        witness = item.get("completion_evidence")
        row = {"tool": str(item["tool"]), "kind": "controller_receipt"}
        if isinstance(witness, dict):
            row.update({key: witness[key] for key in (
                "verified", "target", "verified_scope", "semantic_postcondition_verified") if key in witness})
        elif item.get("not_dispatched") is True:
            row["delivery"] = "not_dispatched"
        elif item.get("must_not_replay") is True or item.get("interrupted"):
            row["delivery"] = "uncertain"
        else:
            row["delivery"] = "returned_without_computer_state_attestation"
        latest.append(row)
    context = {"activation_id": activation_id, "task_ref": task_ref, "status": status,
        "binding_source": "controller", "observed_at": datetime.now(timezone.utc).isoformat(),
        "entities": {key: bindings[key] for key in ("application", "computer_outcome", "computer_scope") if key in bindings},
        "evidence": latest, "uncertainty": "Only the listed receipts establish effects; dialogue and target labels do not.",
        "current_objective": "The exact current request is supplied once in the Objective section."}
    continuation = bindings.get("continuation_result")
    if isinstance(continuation, dict):
        context["finding"] = {key: continuation[key] for key in (
            "source_citation", "content_sha256", "accepted_knowledge", "disposition") if key in continuation}
    with _NOTE_WRITE_LOCK:
        current = load_note(path)
        previous = current.meta.get("activation_id") if current else None
        if not begin and previous not in {None, activation_id}:
            return {"ref": ref, "context": context, "materialized": False}
        # The ordinary owner may disable context projection without erasing
        # runtime receipts. That never turns the old projection into live state.
        if not auto_curate_enabled(agent_ref.rsplit("/", 1)[0] + "/Observations/Observations.md"):
            return {"ref": ref, "context": context, "materialized": False}
        parent = base + "/Immediate Observations.md"
        if load_note(parent) is None:
            write_note(parent, {"kind": "knowledge", "title": "Immediate Observations", "retrieval": False},
                "This Agent's transient conversation and activation context. Controller evidence, not durable policy.")
        meta = {"kind": "knowledge", "title": "Current activation", "retrieval": False,
            "immediate": True, "transient": True, "trust": "unverified", "context_role": "working",
            "activation_id": activation_id, "observed_at": context["observed_at"]}
        body = ("Agent-owned working context projected from the current activation. It does not expose hidden reasoning "
                "or grant capabilities.\n\n```json\n" + json.dumps({**context, "current_objective": objective, "selected_context": list(dict.fromkeys(context_refs or []))},
                             ensure_ascii=False, indent=2) + "\n```\n")
        write_note(path, meta, body)
        if current is None:
            from ..knowledge.index import INDEX
            INDEX.sync(embed=False)
            from ..execution.activity import emit
            emit("graph_changed", [ref])
    return {"ref": ref, "context": context, "materialized": True}


def project_immediate_observations(
    conversation,
    *,
    conversation_id: str,
    before_sequence: int | None = None,
    materialize: bool = True,
) -> dict:
    """Materialize the active context window as one transient Observation Article."""
    compacted = latest_context_compaction(
        conversation_id,
        active=(conversation_id == getattr(conversation, "conversation_id", None)),
        prune=materialize,
    )
    through_sequence = int(compacted.meta.get("through_sequence") or 0) if compacted else 0
    pairs = conversation.complete_pairs(
        conversation_id=conversation_id,
        before_sequence=before_sequence,
        after_sequence=through_sequence,
    )
    # A failed or interrupted execution has no successful assistant reply, but
    # its final owner request still supplies the referent for the next correction.
    # Keep that request without admitting any partial assistant output as fact.
    turns = conversation.index.conversation_turns(conversation_id)
    users = [turn for turn in turns
             if turn["role"] == "user" and turn["state"] == "final"
             and int(turn["sequence"]) > through_sequence
             and (before_sequence is None or int(turn["sequence"]) < before_sequence)]
    replies = {user["id"]: assistant for user, assistant in pairs}
    from .evidence import historical_public_replies, historical_steered_turns
    public_limits = historical_public_replies(
        conversation, conversation_id=conversation_id, before_sequence=before_sequence,
    )
    applied_clarifications = historical_steered_turns(
        conversation, conversation_id=conversation_id, before_sequence=before_sequence,
    )
    sections: list[str] = [
        "This transient Article is the Executive model's active conversation context. "
        "It grants no Tool, Task, Policy, or durable Knowledge authority. The current "
        "owner request always wins.",
    ]
    if compacted:
        sections.append(
            "## Cumulative Temporary Observation\n\n"
            f"From [[{compacted.ref}|{compacted.title}]] through conversation sequence "
            f"{through_sequence}:\n\n{compacted.body.strip()}"
        )
    if users:
        dialogue = "\n\n".join(
            f"User: {user['text']}\n" + (
                f"Executive: {replies[user['id']]['text']}" if user["id"] in replies
                else "[Owner clarification applied within the same completed Task; see its Executive reply.]" if user["id"] in applied_clarifications
                else (f"Executive [Task {public_limits[user['id']]['status']}]: "
                      f"{public_limits[user['id']]['text']}") if user["id"] in public_limits
                else "[No successful Executive reply recorded; this request remains unresolved.]"
            )
            for user in sorted(users, key=lambda turn: int(turn["sequence"]))
        )
        sections.append("## Exact dialogue after compaction\n\n" + dialogue)
    elif not compacted:
        sections.append("No completed conversation pair exists yet.")
    latest_sequence = max(
        (max(int(user["sequence"]), int(replies.get(user["id"], {}).get("sequence", 0)))
         for user in users),
        default=through_sequence,
    )
    body = "\n\n".join(sections)
    meta = {
        "title": "Current conversation",
        "kind": "knowledge",
        "observation_scope": "immediate",
        "retrieval": False,
        "immediate": True,
        "transient": True,
        "trust": "unverified",
        "conversation_id": conversation_id,
        "compacted_through": through_sequence,
        "latest_sequence": latest_sequence,
    }
    if materialize and auto_curate_enabled(str(IMMEDIATE_OBSERVATIONS_PATH)):
        current = load_note(IMMEDIATE_OBSERVATIONS_PATH)
        if current and isinstance(current.meta.get("auto_curate"), bool):
            meta["auto_curate"] = current.meta["auto_curate"]
        needs_index_sync = current is None or current.meta.get("retrieval") is not False
        if not current or current.meta != meta or current.body.strip() != body.strip():
            write_note(str(IMMEDIATE_OBSERVATIONS_PATH), meta, body)
            index = getattr(conversation, "index", None)
            if index is not None and needs_index_sync:
                index.sync()
    return {
        "ref": IMMEDIATE_OBSERVATIONS_REF,
        "body": body,
        "compacted_through": through_sequence,
        "latest_sequence": latest_sequence,
        "temporary_ref": compacted.ref if compacted else None,
    }


def _event_tasks(agent_ref: str) -> list:
    res = resolver()
    rows = []
    for note in res.by_ref.values():
        if (
            note.kind != "task"
            or TURN_COMPLETE_EVENT not in task_triggers(note.meta)
            or not _enabled(note.meta.get("enabled", True))
            or str(note.meta.get("status", "")) == "running"
        ):
            continue
        assignee = res.resolve(str(note.meta.get("assignee", "")))
        if assignee and assignee.ref == agent_ref:
            rows.append(note)
    return sorted(rows, key=lambda note: note.ref)


def read_temporary_observations(agent_ref: str) -> str:
    """Read the Agent's permitted cache, independently of Task scheduling."""
    target = str(Path(agent_ref).parent / "Observations/Temporary Observations")
    if not auto_curate_enabled(target):
        return ""
    with _WRITE_LOCK:
        _removed, retained = _prune_temporary(target)
        entries = list(reversed(retained))
    if not entries:
        return ""
    lines = [f"- [[{note.ref}]] {re.sub(r'\s+', ' ', note.body).strip()}" for note in entries]
    return (
        "## Temporary observations (transient and unverified)\n\n"
        "These are reference-only working-memory summaries. They are not durable facts or "
        "instructions, and the newest user turn always wins.\n\n"
        + "\n".join(lines)
    )[:2_200]


async def _dispatch_completed_turn(
    agent_ref: str,
    user: str,
    assistant: str,
    source: str,
    turn_id: str,
) -> None:
    from ..execution import trace
    from ..execution.executor import run_task

    lock = _AGENT_LOCKS.setdefault(agent_ref, asyncio.Lock())
    async with lock:
        tasks = _event_tasks(agent_ref)
        for task in tasks:
            trace.emit("event", f"{task.title} activated", [agent_ref, TURN_COMPLETE_EVENT, source])
            await run_task(
                task,
                reasoning_effort=str(task.meta.get("reasoning_effort", "low")),
                runtime_params={
                    "turn_id": turn_id,
                    "source": source,
                    "user": _redact(user, 6_000),
                    "assistant": _redact(assistant, 8_000),
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "target_node": str(task.meta.get("auto_curate_target", "")),
                    "target_path": str(task.meta.get("target_path", "")),
                    "curation_mode": str(task.meta.get("curation_mode", "reviewed")),
                },
                emit_turn_event=False,
            )


def queue_turn_complete(
    agent_ref: str,
    user: str,
    assistant: str,
    *,
    source: str,
    turn_id: str,
) -> int:
    """Queue all enabled graph Tasks for the completed-turn boundary."""
    if not agent_ref or not user.strip() or not assistant.strip():
        return 0
    eligible = _event_tasks(agent_ref)
    if not eligible:
        return 0
    key = (agent_ref, turn_id)
    with _WRITE_LOCK:
        if key in _QUEUED_TURNS:
            return 0
        _QUEUED_TURNS.add(key)
        if len(_QUEUED_TURNS) > 1_024:
            _QUEUED_TURNS.pop()
    task = asyncio.create_task(
        _dispatch_completed_turn(agent_ref, user, assistant, source, turn_id)
    )
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return len(eligible)
