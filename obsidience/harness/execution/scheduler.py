"""Scheduler: one asyncio loop; cron for scheduled tasks, ready-queue for one-shots."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime

from croniter import croniter
from yaml import YAMLError

from ..capabilities.registry import READ_ONLY_CAPABILITIES
from ..config import CONFIG
from ..knowledge.index import INDEX
from ..knowledge.source import OBSERVATION_ARCHIVE_SOURCE_CLASS
from ..knowledge.tasks import task_triggers
from ..knowledge.vault import Note, Resolver, iter_notes, load_note, mutate_note_metadata, update_status
from ..models import runtime as model_runtime
from . import trace as action_trace
from .executor import run_task

_running: set[str] = set()
_background: set[asyncio.Task] = set()
_wake_loop: asyncio.AbstractEventLoop | None = None
_wake_event: asyncio.Event | None = None


def wake_scheduler() -> None:
    """Wake the existing scheduler for new work/results; never create a worker."""
    if _wake_loop is not None and _wake_event is not None:
        try:
            _wake_loop.call_soon_threadsafe(_wake_event.set)
        except RuntimeError:
            pass  # Shutdown already owns this loop.


def _background_finished(task: asyncio.Task) -> None:
    _background.discard(task)
    wake_scheduler()

_continuations_running: set[str] = set()
_last_fired: dict[str, float] = {}
_foreground_admissions = 0
_autonomous_interruptions: dict[str, asyncio.Event] = {}
_ACTIVE_EVENT_STATUSES = {"pending", "running"}
INTERRUPTED_RUN_SUMMARY = "interrupted by harness restart; outcome is unknown"
LEARN_TASK_REF = "Tasks/research/learn"
RESOURCE_WAIT_PREFIX = "Waiting for model hardware: "
_RETRY_READ_ONLY_TOOLS = READ_ONLY_CAPABILITIES
RESTART_DISPOSITION_REASON = "Restart requires disposition; Tool effects are unknown or retained."


def _retry_trace(run: dict) -> list[dict] | None:
    raw = run.get("trace")
    if not isinstance(raw, str):
        return None
    try:
        if len(raw.encode("utf-8")) > 2_000_000:
            return None
        entries = json.loads(raw)
    except (ValueError, RecursionError, UnicodeError):
        return None
    return entries if (
        isinstance(entries, list) and 0 < len(entries) <= 4096
        and all(isinstance(entry, dict) for entry in entries)
        and isinstance(entries[0].get("activation_packet"), list)
        and entries[0]["activation_packet"]
    ) else None


def _retry_binding_matches(note: Note, entries: list[dict]) -> bool:
    params = note.meta["params"]
    event = params["event"]
    if event == "task.create":
        identity = {key: params.get(key) for key in (
            "event", "activation_key", "created_by_task_ref", "created_by_run_id",
        )}
        if not all(isinstance(value, str) and value for value in identity.values()):
            return False
        activation = entries[0].get("task_activation")
        if isinstance(activation, dict):
            return all(activation.get(key) == value for key, value in identity.items())
        # Legacy executions predate task_activation. Their immutable creator's
        # actual successful Tool receipt must bind every original input exactly.
        creator = INDEX.run(identity["created_by_run_id"])
        if not creator or creator.get("task_ref") != identity["created_by_task_ref"]:
            return False
        trace = _retry_trace(creator)
        if trace is None:
            return False
        original = {key: value for key, value in params.items()
                    if key not in {*identity, "target_task"}}
        revision_key = hashlib.sha256(json.dumps(
            [note.ref, original.get("candidate_key"), original.get("candidate_revision")], sort_keys=True,
        ).encode()).hexdigest()[:20]
        if params["activation_key"] not in {original.get("candidate_key"), revision_key}:
            return False
        matches = []
        for entry in trace:
            args = entry.get("args")
            if (entry.get("tool") != "task.create" or not isinstance(args, dict)
                    or entry.get("interrupted") or entry.get("must_not_replay")):
                continue
            if args.get("task") != note.ref or args.get("params") != original:
                continue
            try:
                result = json.loads(entry.get("obs", ""))
            except (ValueError, TypeError):
                continue
            if isinstance(result, dict) and result.get("task") == note.ref and result.get("state") in {"started", "queued", "processed"}:
                matches.append(entry)
        return len(matches) == 1
    if event == "source.inbox":
        receipt = entries[0].get("source_inbox")
        if "source_inbox" not in entries[0]:
            # Older executor cancellation omitted this receipt. Only a settled
            # zero-Tool foreground interruption can recover its original inputs
            # from the immutable Source event owner; never infer them from prose.
            if (note.ref != "Tasks/ingest" or any("tool" in item for item in entries)
                    or not any(item.get("interruption_reason") == "foreground_admission"
                               and item.get("must_not_replay") is True for item in entries)):
                return False
            from ..knowledge.source import (
                _SOURCE_CITATION, parse_raw_source, research_handoff_origin,
            )
            origin = research_handoff_origin(params)
            source = INDEX.source(str(params.get("source_id", "")))
            if origin is None or source is None:
                return False
            raw = parse_raw_source(bytes(source["material"]))
            matches = list(_SOURCE_CITATION.finditer(raw.content))
            if not matches or raw.content.count("source://") != len(matches):
                return False
            citations = list(dict.fromkeys(
                f"source://{match.group('id').lower()}" for match in matches
            ))
            expected = {
                "event": "source.inbox", "activation_key": source["event_key"],
                "queue_after_review": True, "source_id": raw.source_id,
                "source_citation": f"source://{raw.source_id}",
                "source_path": f"obsidience/evidence/{source['path']}",
                "source_type": raw.source_type, "source_ref": raw.source_ref,
                "source_media_type": raw.media_type, "source_captured_at": raw.captured_at,
                "source_sha256": raw.content_sha256,
                "source_citations": citations,
                **origin,
            }
            return json.dumps(params, sort_keys=True) == json.dumps(expected, sort_keys=True)
        if not isinstance(receipt, dict) or not receipt.get("source_id"):
            return False
        if any(params.get(key) != value for key, value in receipt.items()):
            return False
        source = INDEX.source(str(receipt["source_id"]))
        return bool(
            source and source.get("event_key") == params["activation_key"]
            and source.get("content_sha256") == params.get("source_sha256")
            and source.get("material_sha256") == "sha256:" + hashlib.sha256(bytes(source["material"])).hexdigest()
        )
    if event == "observations.temporary.ready":
        from ..conversation.observations import resolve_temporary_promotion_inputs

        if params.get("promotion_key") != params["activation_key"]:
            return False
        notes = resolve_temporary_promotion_inputs({**params, "origin_task_ref": note.ref})
        return bool(notes) and all(
            not item.meta.get("source_archive")
            and item.meta.get("promotion_pending") == params["promotion_key"]
            for item in notes
        )
    return False


def retry_blocked_reason(note: Note, run: dict | None = None) -> str:
    """Explain whether an explicit owner retry can preserve this failed event."""
    from ..knowledge.vault import _NOTE_WRITE_LOCK

    with _NOTE_WRITE_LOCK, INDEX.lock:
        params = note.meta.get("params")
        if note.kind != "task" or note.meta.get("status") != "failed":
            return "Only a failed Task occurrence can be retried."
        if note.ref in _running:
            return "This Task already has an active executor claim."
        if (not isinstance(params, dict) or not isinstance(params.get("activation_key"), str)
                or not params["activation_key"] or params.get("event") not in task_triggers(note.meta)):
            return "The failed request has no exact durable event identity."
        last_run = note.meta.get("last_run")
        run = INDEX.run(last_run) if run is None and isinstance(last_run, str) else run
        if (not isinstance(run, dict) or run.get("id") != last_run or run.get("task_ref") != note.ref
                or not isinstance(run.get("status"), str)
                or run["status"] not in {"failed", "interrupted"}):
            return "The exact failed execution record is unavailable."
        started, finished = run.get("started"), run.get("finished")
        if (type(started) not in (int, float) or type(finished) not in (int, float)
                or not math.isfinite(started) or not math.isfinite(finished) or finished < started):
            return "The previous execution has not conclusively ended."
        if INDEX.tool_run_receipts(last_run) is not None:
            receipt_error = _receipt_retry_blocked_reason(note, last_run)
            if receipt_error:
                return receipt_error
        entries = _retry_trace(run)
        if entries is None:
            return "The previous execution trace is incomplete or unreadable."
        for entry in entries:
            if entry.get("created_tasks") or "task" in entry or entry.get("resource_blocked_after_effect"):
                return "The previous execution created work or may have committed effects."
            if "tool" in entry:
                if (not isinstance(entry["tool"], str) or entry["tool"] not in _RETRY_READ_ONLY_TOOLS
                        or not isinstance(entry.get("args"), dict)
                        or not isinstance(entry.get("obs"), str)
                        or set(entry) - {"tool", "args", "obs", "sig"}):
                    return "The previous execution contains an effect or uncertain Tool outcome."
            elif set(entry) - {
                "activation_id", "activation_packet", "retrieval_ms", "task_activation", "source_inbox", "created_tasks",
                "interactive_turn", "computer_request", "provider_metrics", "context_projection",
                "interruption_reason", "must_not_replay", "invalid", "parse_error", "finish_reason",
            }:
                return "The previous execution contains an unknown outcome record."
            if entry.get("must_not_replay") and entry.get("interruption_reason") != "foreground_admission":
                return "The previous execution requires explicit effect disposition."
        if INDEX.db.execute("SELECT 1 FROM review_decisions WHERE run_id=? LIMIT 1", (last_run,)).fetchone():
            return "The previous execution already has an owner review decision."
        from ..knowledge.format import loads
        try:
            for path in CONFIG.staging_dir.glob("*.md"):
                meta, _body = loads(path.read_text(encoding="utf-8"))
                if meta.get("run_id") == last_run or str(meta.get("task", "")).strip("[]") == note.ref:
                    return "This Task still has a pending proposal requiring disposition."
        except (OSError, ValueError):
            return "Pending review state could not be validated."
        try:
            binding_matches = _retry_binding_matches(note, entries)
        except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
            binding_matches = False
        if not binding_matches:
            return "The original event inputs cannot be attested or are no longer valid."
        from ..capabilities.vault.maintenance import candidate_invalidation
        from ..knowledge.vault import resolver
        if params.get("event") == "task.create" and candidate_invalidation(note.ref, params, resolver()):
            return "The maintenance inputs are invalidated; settle the old occurrence and let Curate inspect current Articles."
        return ""


def retry_failed_occurrence(note: Note, expected_run_id: str, *, require_receipts: bool = False) -> dict:
    """Requeue one exact occurrence; autonomous Repair requires durable coverage."""
    if not isinstance(expected_run_id, str) or not expected_run_id:
        raise ValueError("The exact failed run ID is required.")
    expected_params = json.dumps(note.meta.get("params"), sort_keys=True)
    expected_queue = json.dumps(note.meta.get("event_queue", []), sort_keys=True)
    result = {}

    def retry(meta: dict) -> None:
        if (meta.get("last_run") != expected_run_id
                or json.dumps(meta.get("params"), sort_keys=True) != expected_params
                or json.dumps(meta.get("event_queue", []), sort_keys=True) != expected_queue):
            raise ValueError("The Task occurrence changed; refresh before retrying.")
        already_pending = meta.get("status") == "pending"
        current = replace(note, meta={**meta, "status": "failed"} if already_pending else dict(meta))
        if require_receipts:
            from .repair import check_retry_transaction

            check_retry_transaction(current, already_pending=already_pending)
        reason = retry_blocked_reason(current)
        if reason:
            raise ValueError(reason)
        if not already_pending:
            meta["status"] = "pending"
            meta["status_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            meta.pop("blocked_reason", None)
        if require_receipts:
            from .repair import record_retry_transaction

            result["repair_receipt_id"] = record_retry_transaction(current, expected_run_id)
        result.update(task=note.ref, status="pending", retry_of_run=expected_run_id,
                      queue_depth=len(_event_queue(meta)), already_pending=already_pending)

    mutate_note_metadata(note, retry)
    return result


def _settle_occurrence(note: Note, *, kind: str, classify, summary_for, previous_safe=None) -> dict | None:
    """One controller receipt and FIFO transaction for an evidenced disposition."""
    from ..knowledge import review
    from ..knowledge.format import loads
    from ..knowledge.vault import _NOTE_WRITE_LOCK

    params = note.meta.get("params")
    if (note.kind != "task"
            or note.meta.get("status") not in {"pending", "failed"}
            or not isinstance(params, dict)
            or not isinstance(params.get("activation_key"), str) or not params["activation_key"]
            or note.ref in _running):
        return None
    expected = INDEX._runtime_fields(note.meta)
    with _NOTE_WRITE_LOCK:
        fresh = load_note(note.path)
        if fresh is None or INDEX._runtime_fields(fresh.meta) != expected:
            return None
        if _interactive_occurrence(note.ref, params):
            return None
        try:
            for path in CONFIG.staging_dir.glob("*.md"):
                meta, _body = loads(path.read_text(encoding="utf-8"))
                if (str(meta.get("task", "")).strip("[]") == note.ref
                        or (expected.get("last_run") and meta.get("run_id") == expected["last_run"])):
                    if not review._has_group_decision(path.name, meta):
                        return None
        except (OSError, ValueError):
            return None
        evidence = classify(params)
        if evidence is None:
            return None
        params_hash = hashlib.sha256(json.dumps(params, sort_keys=True).encode()).hexdigest()
        receipt_id = "settled-" + hashlib.sha256(
            (note.ref + "\0" + params["activation_key"] + "\0" + params_hash).encode()
        ).hexdigest()[:32]
        previous_id = str(expected.get("last_run", ""))
        trace = json.dumps([{"controller_disposition": {
            "kind": kind, "params_sha256": params_hash,
            "activation_key": params["activation_key"], "previous_run_id": previous_id,
            "effect_applied": False, "tools_executed": False, **evidence,
        }}], sort_keys=True)
        if len(trace.encode()) > 32_000:
            return None
        summary = summary_for(evidence)
        result = {}

        def settle(state: dict) -> None:
            if state != expected or note.ref in _running:
                return
            queue = state.get("event_queue", [])
            if not isinstance(queue, list) or any(not isinstance(item, dict) for item in queue):
                return
            if INDEX.db.execute("SELECT 1 FROM runs WHERE task_ref=? AND status IN ('running','pending') LIMIT 1",
                                (note.ref,)).fetchone():
                return
            if INDEX.db.execute(
                "SELECT 1 FROM task_continuations WHERE status NOT IN ('completed','failed','cancelled') "
                "AND ((?<>'' AND handoff_source_id=?) OR (?<>'' AND ingest_run_id=?) "
                "OR (target_task_ref=? AND target_activation_key=?)) LIMIT 1",
                (str(params.get("source_id", "")), str(params.get("source_id", "")), previous_id, previous_id,
                 note.ref, params["activation_key"]),
            ).fetchone():
                return
            previous = INDEX.run(previous_id) if previous_id else None
            if state["status"] == "failed":
                if (not previous or previous.get("task_ref") != note.ref
                        or previous.get("status") not in {"failed", "interrupted"}
                        or type(previous.get("finished")) not in (float, int)
                        or not math.isfinite(previous["finished"])):
                    return
            if previous_safe is not None and previous is not None and not previous_safe(
                previous, params, required=state["status"] == "failed",
            ):
                return
            existing = INDEX.run(receipt_id)
            if existing:
                try:
                    receipt = json.loads(existing.get("trace") or "[]")[0]["controller_disposition"]
                except (ValueError, TypeError, KeyError, IndexError):
                    return
                if (existing.get("task_ref") != note.ref or existing.get("agent") != "scheduler"
                        or existing.get("status") != "settled"
                        or receipt.get("kind") != kind
                        or receipt.get("params_sha256") != params_hash):
                    return
            else:
                now = time.time()
                INDEX.record_run(overwrite=False, commit=False, id=receipt_id, task_ref=note.ref,
                                 objective="Reconcile an evidenced Task commitment", agent="scheduler",
                                 started=now, finished=now, status="settled", summary=summary, trace=trace)
            state.update(status="pending" if queue else "completed", last_run=receipt_id,
                         summary=existing["summary"] if existing else summary,
                         status_updated=time.strftime("%Y-%m-%dT%H:%M:%S"))
            state.pop("blocked_reason", None)
            if queue:
                state["params"] = queue[0]
                state["triggered_at"] = state["status_updated"]
                if len(queue) > 1:
                    state["event_queue"] = queue[1:]
                else:
                    state.pop("event_queue", None)
            else:
                state.pop("event_queue", None)
            result.update(task=note.ref, status=state["status"], settlement_run_id=receipt_id,
                          disposition=evidence["disposition"], previous_run_id=previous_id,
                          promoted=bool(queue), queue_depth=max(0, len(queue) - 1))

        INDEX.mutate_task_runtime(note.ref, settle)
        if result:
            action_trace.emit("status", "Task occurrence settled", [json.dumps({
                "disposition": result["disposition"], "receipt": result["settlement_run_id"],
                "source_id": str(evidence.get("handoff", {}).get("id", "")),
                "accepted_source_id": str(evidence.get("accepted_handoff", {}).get("id", "")),
            }, sort_keys=True)])
        return result or None


def _maintenance_recorded_args(value, signals: dict) -> dict | None:
    """Recover bounded signal spelling for exact receipt-signature verification."""
    if not isinstance(value, dict) or not isinstance(value.get("params"), dict):
        return None
    recorded = value["params"].get("candidate_signals")
    if not isinstance(recorded, dict) or recorded.keys() != signals.keys():
        return None
    restored = {}
    for key, expected in signals.items():
        actual = recorded[key]
        if isinstance(expected, list):
            from .executor import MAX_TRACE_STRING_CHARS

            # Legacy index coverage carries up to seven child refs. The trace
            # may contain their complete Python representation at this depth;
            # match it exactly rather than evaluating or guessing truncated data.
            if (not 1 <= len(expected) <= 8
                    or any(not isinstance(item, str) or not item for item in expected)
                    or len(str(expected)) > MAX_TRACE_STRING_CHARS
                    or actual != expected and actual != str(expected)):
                return None
            restored[key] = list(expected)
            continue
        if type(expected) not in (type(None), bool, int, float, str):
            return None
        # The bounded run serializer stringifies scalar values at this depth.
        # Recover only a complete scalar; the signature below must still match
        # the exact original args, before canonical runtime params are compared.
        if isinstance(actual, str) and not isinstance(expected, str):
            if actual in {"True", "False", "None"}:
                actual = {"True": True, "False": False, "None": None}[actual]
            else:
                try:
                    actual = json.loads(actual)
                except (ValueError, RecursionError):
                    return None
        if type(actual) not in (type(None), bool, int, float, str):
            return None
        numeric = type(actual) in (int, float) and type(expected) in (int, float)
        if numeric:
            if (any(type(item) is float and not math.isfinite(item) for item in (actual, expected))
                    or actual != expected):
                return None
        elif type(actual) is not type(expected) or actual != expected:
            return None
        restored[key] = actual
    return {**value, "params": {**value["params"], "candidate_signals": restored}}


def _maintenance_creator_evidence(note: Note, params: dict) -> dict | None:
    """Match current inputs to a real, immutable Curate task.create receipt."""
    from ..capabilities.vault.maintenance import agent_structural_hub, candidate_invalidation
    from ..knowledge.vault import resolver
    from .executor import _bounded_trace_value
    from pathlib import PurePosixPath

    candidate_fields = {"candidate_key", "candidate_revision", "candidate_refs", "candidate_kind", "candidate_signals"}
    if (set(params) != candidate_fields | {"event", "target_task", "created_by_task_ref", "created_by_run_id", "activation_key"}
            or params.get("event") != "task.create" or params.get("target_task") != note.ref
            or params.get("created_by_task_ref") != "Tasks/curate"
            or any(not isinstance(params.get(key), str) or not params[key] for key in (
                "candidate_key", "candidate_revision", "candidate_kind", "created_by_run_id", "activation_key"))
            or not isinstance(params.get("candidate_signals"), dict)):
        return None
    raw = {key: params[key] for key in candidate_fields}
    revision_key = hashlib.sha256(json.dumps(
        [note.ref, params["candidate_key"], params["candidate_revision"]], sort_keys=True,
    ).encode()).hexdigest()[:20]
    if params["activation_key"] not in {params["candidate_key"], revision_key}:
        return None
    creator = INDEX.run(params["created_by_run_id"])
    if not creator or creator.get("task_ref") != params["created_by_task_ref"]:
        return None
    trace = _retry_trace(creator)
    if trace is None or any("trace_truncated" in entry for entry in trace):
        return None
    res = resolver()
    invalidated = candidate_invalidation(note.ref, params, res)
    if invalidated is None:
        return None
    matches = []
    for entry in trace:
        if entry.get("tool") != "task.create" or entry.get("interrupted") or entry.get("must_not_replay"):
            continue
        args = _maintenance_recorded_args(entry.get("args"), params["candidate_signals"])
        if args is None:
            continue
        sig = entry.get("sig", "")
        expected_legacy = "task.create:" + json.dumps(args, sort_keys=True)
        if sig == _bounded_trace_value(expected_legacy):
            # A bounded legacy signature includes the hash of its complete
            # controller string. Recompute that exact projection; never parse
            # or execute the truncated text.
            pass
        elif isinstance(sig, str) and sig.startswith("task.create:{"):
            try:
                args = json.loads(sig.removeprefix("task.create:"))
            except (ValueError, RecursionError):
                continue
            if sig != "task.create:" + json.dumps(args, sort_keys=True):
                continue
            if _maintenance_recorded_args(args, params["candidate_signals"]) is None:
                continue
        elif sig != "task.create:sha256:" + hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest():
            continue
        if (not isinstance(args, dict) or set(args) != {"task", "params"}
                or args["task"] != note.ref or not isinstance(args["params"], dict)
                or set(args["params"]) != candidate_fields):
            continue
        if entry.get("args") not in (args, _bounded_trace_value({"args": args})["args"]):
            continue
        original = dict(args["params"])
        old_refs = original.get("candidate_refs")
        if not isinstance(old_refs, list) or any(not isinstance(ref, str) for ref in old_refs):
            continue
        # The native OKF migration renamed reserved index Articles. Admit only
        # its exact same-parent transform for an accepted Agent structural hub;
        # never infer an arbitrary rename from a label or content similarity.
        canonical = []
        for ref in old_refs:
            path = PurePosixPath(ref)
            replacement = str(path.with_name(path.parent.name))
            if (path.name == "index" and res.resolve(ref) is None
                    and agent_structural_hub(res.resolve(replacement), res)):
                canonical.append(replacement)
            else:
                canonical.append(ref)
        original["candidate_refs"] = canonical
        if original != raw:
            continue
        try:
            result = json.loads(entry.get("obs", ""))
        except (ValueError, TypeError):
            continue
        if (not isinstance(result, dict) or result.get("task") != note.ref
                or result.get("created_by") != params["created_by_task_ref"]
                or result.get("state") not in {"started", "queued", "processed"}):
            continue
        matches.append(hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest())
    if len(matches) != 1:
        return None
    return {**invalidated, "creator_run_id": creator["id"], "creator_args_sha256": matches[0],
            "evidence": ["An actual Curate task.create receipt binds this occurrence; current accepted Article inputs invalidate it. No Tool is replayed."]}


def _maintenance_failure_clear(run: dict, params: dict, *, required: bool) -> bool:
    if not required and run.get("status") == "settled" and run.get("agent") == "scheduler":
        try:
            receipt = json.loads(run["trace"])[0]["controller_disposition"]
            return (receipt.get("kind") == "maintenance_invalidation"
                    and receipt.get("effect_applied") is False and receipt.get("tools_executed") is False)
        except (ValueError, KeyError, IndexError, TypeError):
            return False
    entries = _retry_trace(run)
    if entries is None:
        return False
    activation = entries[0].get("task_activation")
    fields = ("event", "activation_key", "created_by_task_ref", "created_by_run_id")
    if not isinstance(activation, dict) or not all(isinstance(activation.get(key), str) and activation[key] for key in fields):
        return False
    if any(activation[key] != params.get(key) for key in fields):
        return not required and activation["activation_key"] != params.get("activation_key")
    # Only a conclusively empty execution is automatically disposed here.
    # Reads, child work, truncated traces, unknown records and possible effects
    # remain available for an explicit owner decision.
    return all(not (set(entry) - {"activation_id", "activation_packet", "retrieval_ms", "task_activation",
                                 "provider_metrics", "context_projection"}) for entry in entries)


def settle_maintenance_occurrence(note: Note) -> dict | None:
    if note.ref not in {"Tasks/merge", "Tasks/link", "Tasks/improve", "Tasks/archive", "Tasks/audit"}:
        return None
    try:
        return _settle_occurrence(note, kind="maintenance_invalidation",
            classify=lambda params: _maintenance_creator_evidence(note, params),
            summary_for=lambda evidence: "Maintenance occurrence settled without execution: " + evidence["reason"] + ". Curate can inspect current Articles.",
            previous_safe=_maintenance_failure_clear)
    except (ValueError, TypeError, KeyError, AttributeError, OSError):
        return None


def foreground_pending() -> bool:
    """Controller demand, never a model-supplied Task parameter."""
    return _foreground_admissions > 0


@asynccontextmanager
async def foreground_admission(reason: str):
    """Yield running autonomous work at a safe executor boundary for live input."""
    global _foreground_admissions
    _foreground_admissions += 1
    try:
        for interruption in tuple(_autonomous_interruptions.values()):
            interruption.set()
        action_trace.emit("status", "Foreground admission requested", [json.dumps({
            "reason": reason if reason in {
                "conversation", "conversation.continuation", "realtime.start",
            } else "foreground",
            "active_admissions": _foreground_admissions,
            "autonomous_runs_signaled": len(_autonomous_interruptions),
        }, sort_keys=True)])
        yield
    finally:
        _foreground_admissions -= 1
        wake_scheduler()


def _autonomous_occurrence(note: Note) -> bool:
    params = note.meta.get("params")
    return _is_specialist_task(note) and not (
        isinstance(params, dict) and _interactive_occurrence(note.ref, params)
    )


def _trusted_research_handler(task_ref: str, run_id: str) -> bool:
    """Validate internal Source provenance for same-research Learn suppression."""
    if not task_ref.startswith("Tasks/research/") or not run_id:
        return False
    from ..knowledge.vault import resolver

    task = resolver().resolve(task_ref)
    if not task or task.kind != "task":
        return False
    agent = resolver().resolve(str(task.meta.get("assignee", "")))
    if not agent or agent.kind != "agent" or str(agent.meta.get("role", "")) != "researcher":
        return False
    if (
        str(task.meta.get("status", "")) == "running"
        and str(task.meta.get("last_run", "")) == run_id
    ):
        return True
    run = INDEX.run(run_id)
    return bool(run and run.get("task_ref") == task.ref)


def _is_specialist_task(note: Note, accepted_resolver: Resolver | None = None) -> bool:
    """Return true only for a Task assigned to a non-Executive Agent Article."""

    assignee = note.meta.get("assignee")
    if not assignee:
        return False
    from ..knowledge.vault import resolver

    res = accepted_resolver if accepted_resolver is not None else resolver()
    agent = res.resolve(str(assignee))
    return bool(agent and agent.kind == "agent" and str(agent.meta.get("role", "")) != "executive")


def _activation_receipt(task_ref: str, run_id: str) -> dict:
    """Read controller evidence from one exact execution, never Task parameters."""
    if not task_ref or not run_id:
        return {}
    run = INDEX.run(run_id)
    if not run or run.get("task_ref") != task_ref:
        return {}
    try:
        trace = json.loads(run.get("trace") or "[]")
    except (TypeError, ValueError):
        return {}
    return trace[0] if isinstance(trace, list) and trace and isinstance(trace[0], dict) else {}


def _interactive_delegation(task_ref: str, params: dict) -> bool:
    """Match an occurrence to the exact Tool receipt of a persisted user turn."""
    if params.get("event") != "task.create" or not params.get("activation_key"):
        return False
    receipt = _activation_receipt(
        str(params.get("created_by_task_ref", "")),
        str(params.get("created_by_run_id", "")),
    )
    binding = receipt.get("interactive_turn")
    created = receipt.get("created_tasks")
    if not isinstance(binding, dict) or not isinstance(created, list):
        return False
    user_turn = INDEX.conversation_turn(str(binding.get("reply_to_turn_id", "")))
    return bool(
        user_turn
        and user_turn.get("role") == "user"
        and user_turn.get("state") == "final"
        and user_turn.get("source") in {"text", "realtime"}
        and user_turn.get("conversation_id") == binding.get("conversation_id")
        and any(
            isinstance(item, dict)
            and item.get("target_task_ref") == task_ref
            and item.get("activation_key") == params["activation_key"]
            for item in created
        )
    )


def _interactive_occurrence(task_ref: str, params: dict) -> bool:
    if _interactive_delegation(task_ref, params):
        return True
    if params.get("event") == "task.assigned":
        from ..knowledge.links import metadata_ref
        from ..knowledge.vault import resolver

        res = resolver()
        generation = res.resolve(task_ref)
        target = res.resolve(str(params.get("target_task", "")))
        current = target.meta.get("params") if target else None
        return bool(
            generation and generation.kind == "task" and "task.assigned" in task_triggers(generation.meta)
            and target and target.kind == "task" and target.ref != task_ref
            and target.meta.get("status") == "pending"
            and metadata_ref(str(target.meta.get("assignee", ""))) == params.get("target_agent")
            and isinstance(current, dict) and current.get("event") in {"task.create", "source.inbox"}
            and _interactive_occurrence(target.ref, current)
        )
    if task_ref != "Tasks/ingest" or params.get("event") != "source.inbox":
        return False
    from ..knowledge.source import research_handoff_origin

    origin = research_handoff_origin(params)
    if not origin:
        return False
    receipt = _activation_receipt(origin["research_task"], origin["research_run_id"])
    activation = receipt.get("task_activation")
    return bool(
        isinstance(activation, dict)
        and _interactive_delegation(origin["research_task"], activation)
    )


def _realtime_allows(note: Note, accepted_resolver: Resolver | None = None) -> bool:
    """Prioritize foreground and speech transitions, not idle microphone time."""

    from ..realtime.runtime import RUNTIME

    if not (foreground_pending() or RUNTIME.scheduler_paused()) or not _is_specialist_task(note, accepted_resolver):
        return True
    if str(note.meta.get("status", "")) != "pending":
        return False
    params = note.meta.get("params")
    return isinstance(params, dict) and _interactive_occurrence(note.ref, params)


def _resource_error(note: Note, model: str | None = None) -> model_runtime.ModelResourceUnavailable | None:
    """Ask the model owner about the Task's unchanged selection before claim."""
    from ..knowledge.vault import resolver

    if note.meta.get("subtasks"):
        return None  # Containers do not lease their own model.
    res = resolver()
    agent = res.resolve(str(note.meta.get("assignee", "Agents/Executive/Executive")))
    agent_ref = (
        agent.ref if agent and (agent.kind == "agent" or agent.ref == "Agents/Executive/Executive")
        else "Agents/Executive/Executive"
    )
    try:
        spec = model_runtime.resolve_model(model if model is not None else note.meta.get("model"), agent_ref)
        model_runtime.check_resources(spec)
    except model_runtime.ModelResourceUnavailable as exc:
        return exc
    except ValueError:
        # Invalid Task configuration keeps the ordinary executor diagnosis;
        # only a temporary component reservation defers an otherwise due Task.
        pass
    return None


def _resources_allow(note: Note, model: str | None = None) -> bool:
    error = _resource_error(note, model)
    reason = RESOURCE_WAIT_PREFIX + str(error) if error else ""
    previous = str(note.meta.get("blocked_reason", ""))
    if reason and previous != reason:
        changed = False

        def waiting(meta: dict) -> None:
            nonlocal changed
            if str(meta.get("status", "draft")) not in {"pending", "completed", "failed"}:
                return
            meta.update(status="pending", blocked_reason=reason)
            changed = True

        mutate_note_metadata(note, waiting)
        if changed:
            action_trace.emit("status", f"{note.title} is waiting for model hardware", [str(error)])
    elif not reason and previous.startswith(RESOURCE_WAIT_PREFIX):
        def ready(meta: dict) -> None:
            if str(meta.get("blocked_reason", "")).startswith(RESOURCE_WAIT_PREFIX):
                meta.pop("blocked_reason", None)

        mutate_note_metadata(note, ready)
    return error is None


def _run_needs_disposition(run: dict) -> bool:
    if run.get("status") == "interrupted" or run.get("summary") == INTERRUPTED_RUN_SUMMARY:
        return True
    try:
        entries = json.loads(run.get("trace") or "[]")
    except (ValueError, TypeError):
        return False
    return isinstance(entries, list) and any(
        isinstance(entry, dict)
        and entry.get("must_not_replay") is True
        and isinstance(entry.get("resource_blocked_after_effect"), dict)
        for entry in entries
    )


def _other_task_active(task_ref: str) -> bool:
    """See every Task owner, including chat and Realtime outside this loop."""

    if any(ref != task_ref for ref in _running):
        return True
    return any(
        note.kind == "task"
        and note.ref != task_ref
        and str(note.meta.get("status", "")) == "running"
        for note in iter_notes()
    )


def _receipt_retry_blocked_reason(note: Note, run_id: str) -> str:
    """Only controller-written, complete dispatch coverage can authorize recovery."""
    coverage = INDEX.tool_run_receipts(run_id)
    if coverage is None:
        return "The execution predates durable Tool receipt coverage."
    try:
        same_params = coverage["params_sha256"] == INDEX.tool_params_sha256(note.meta.get("params") or {})
    except (TypeError, ValueError, RecursionError):
        same_params = False
    if coverage["task_ref"] != note.ref or not same_params:
        return "The Tool receipt does not attest these exact Task inputs."
    for call in coverage["calls"]:
        if call["status"] == "undispatched":
            continue
        if (call["read_only"] is not True or call["tool"] not in READ_ONLY_CAPABILITIES
                or not call["tool_ref"] or not call["tool_sha256"]):
            return "A Tool may have committed effects."
        if call["status"] not in {"started", "returned", "error", "rejected", "interrupted"}:
            return "A Tool receipt has an unknown lifecycle state."
    if INDEX.db.execute("SELECT 1 FROM review_decisions WHERE run_id=? LIMIT 1", (run_id,)).fetchone():
        return "The execution has an owner Review decision."
    if INDEX.db.execute(
        "SELECT 1 FROM task_continuations WHERE caller_run_id=? OR resumed_run_id=? LIMIT 1", (run_id, run_id),
    ).fetchone():
        return "The execution created a continuation."
    from ..knowledge.format import loads
    try:
        for path in CONFIG.staging_dir.glob("*.md"):
            meta, _body = loads(path.read_text(encoding="utf-8"))
            if meta.get("run_id") == run_id or str(meta.get("task", "")).strip("[]") == note.ref:
                return "The Task has a pending Review."
    except (OSError, ValueError, YAMLError):
        return "Pending Review state could not be validated."
    return ""


def reconcile_interrupted_runs() -> list[str]:
    """Close crashed attempts; only proven no-effect event work returns to pending."""
    from ..knowledge.vault import _NOTE_WRITE_LOCK

    with _NOTE_WRITE_LOCK, INDEX.lock:
        return _reconcile_interrupted_runs()


def _reconcile_interrupted_runs() -> list[str]:
    interrupted = []
    for note in iter_notes():
        if note.kind != "task":
            continue
        status = str(note.meta.get("status", ""))
        was_running = status == "running"
        params = note.meta.get("params")
        retry_event = bool(
            task_triggers(note.meta)
            and isinstance(params, dict)
            and (params.get("activation_key") or params.get("event"))
        )
        was_interrupted = (
            status == "failed"
            and str(note.meta.get("blocked_reason", "")) == INTERRUPTED_RUN_SUMMARY
            and retry_event
        )
        if not was_running and not was_interrupted:
            continue
        run_id = str(note.meta.get("last_run") or f"interrupted-{int(time.time())}")
        previous = INDEX.run(run_id)
        retry_safe = retry_event and not _receipt_retry_blocked_reason(note, run_id)
        if previous and previous.get("status") == "interrupted":
            # A finalized foreground interruption already requires explicit disposition.
            retry_safe = False
        if retry_safe:
            def requeue(meta: dict) -> None:
                meta["status"] = "pending"
                meta["status_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
                meta["summary"] = INTERRUPTED_RUN_SUMMARY
                meta.pop("blocked_reason", None)
                queue = _dedupe_waiting_events(meta)
                if queue:
                    meta["event_queue"] = queue
                else:
                    meta.pop("event_queue", None)

            mutate_note_metadata(note, requeue)
        else:
            update_status(note, "failed", {"blocked_reason": (
                RESTART_DISPOSITION_REASON if retry_event else INTERRUPTED_RUN_SUMMARY
            )})
        if was_running:
            INDEX.record_run(
                # A synthesized restart marker cannot erase exact Tool evidence
                # already finalized by the interrupted executor.
                overwrite=False,
                id=run_id,
                task_ref=note.ref,
                objective=note.title,
                agent="interpreter",
                started=note.mtime,
                finished=time.time(),
                status="failed",
                summary=INTERRUPTED_RUN_SUMMARY,
                trace="[]",
                reasoning_effort=str(note.meta.get("reasoning_effort", "")),
            )
        interrupted.append(note.ref)
    return interrupted


def _event_queue(meta: dict) -> list[dict]:
    raw = meta.get("event_queue")
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, dict)]


def _event_key(params: dict) -> tuple[str, ...]:
    candidate_refs = params.get("candidate_refs")
    if params.get("event") == "task.create" and isinstance(candidate_refs, list):
        refs = tuple(sorted({str(ref).strip() for ref in candidate_refs if str(ref).strip()}))
        if refs:
            identity = ("task.create-candidate", str(params.get("target_task", "")), *refs)
            revision = params.get("candidate_revision")
            return (*identity, revision) if isinstance(revision, str) and revision else identity
    activation_key = str(params.get("activation_key", ""))
    if activation_key:
        return ("activation", activation_key)
    model_id = str(params.get("model_id", ""))
    if model_id:
        return (
            "model.added",
            model_id,
            str(params.get("model_fingerprint", "")),
        )
    source_ref = str(params.get("source_ref", ""))
    if source_ref:
        return (
            str(params.get("event", "source")),
            source_ref,
            str(params.get("source_sha256", "")),
        )
    return (
        str(params.get("target_agent", "")),
        str(params.get("target_task", "")),
        str(params.get("output_runbook", "")),
    )


def _dedupe_waiting_events(meta: dict) -> list[dict]:
    """Keep one FIFO occurrence per active event identity."""
    active = meta.get("params")
    seen = {_event_key(active)} if isinstance(active, dict) else set()
    queue = []
    for waiting in _event_queue(meta):
        key = _event_key(waiting)
        if key in seen:
            continue
        seen.add(key)
        queue.append(waiting)
    return queue


def reconcile_check_health() -> dict | None:
    """Deliver the latest completed Check through the existing Task event queue.

    The small controller signal survives trace clipping and process restart.
    Queue admission precedes its receipt; a crash between them reattaches to
    the same event identity. No provider call or new polling loop is involved.
    """
    check = load_note("Tasks/check.md")
    if check is None:
        return None
    run = INDEX.run(str(check.meta.get("last_run", "")))
    if not run or run.get("task_ref") != check.ref or run.get("status") != "completed":
        return None
    receipt_id = "health-repair-" + hashlib.sha256(str(run["id"]).encode()).hexdigest()[:32]
    if INDEX.run(receipt_id) is not None:
        return None
    try:
        entries = json.loads(run.get("trace") or "[]")
    except (ValueError, TypeError):
        return None
    signal = entries[0].get("harness_health") if isinstance(entries, list) and entries and isinstance(entries[0], dict) else None
    if (not isinstance(signal, dict) or type(signal.get("version")) is not int
            or signal != {"version": 1, "status": "degraded"}):
        return None
    repair = load_note("Tasks/repair.md")
    if (repair is None or repair.kind != "task" or "harness.degraded" not in task_triggers(repair.meta)
            or repair.meta.get("enabled") is False
            or str(repair.meta.get("enabled", True)).strip().lower() in {"0", "false", "no", "off"}
            or repair.meta.get("article_status") == "deprecated"):
        return None
    params = {"check_run_id": run["id"], "activation_key": receipt_id,
              "target_task": repair.ref}
    results = enqueue_named_event("harness.degraded", params, expected_task=repair.ref)
    if len(results) != 1 or results[0]["state"] not in {"started", "queued", "processed"}:
        return None
    now = time.time()
    INDEX.record_run(id=receipt_id, task_ref=repair.ref, agent="scheduler", started=now,
                     finished=now, status="dispatched", objective="Repair follow-up to completed Check",
                     summary=f"Completed degraded Check {run['id']} admitted Repair through harness.degraded.",
                     trace=json.dumps([{"check_run_id": run["id"], "activation_key": receipt_id}]),
                     overwrite=False)
    action_trace.emit("status", "Check activated Repair", [str(run["id"]), repair.ref],
                      {"run_id": run["id"], "task_ref": check.ref, "agent_ref": "Agents/Heimdall/Heimdall"})
    return results[0]


def enqueue_named_event(
    event: str,
    params: dict,
    *,
    expected_task: str | None = None,
    handled_by_task_ref: str = "",
    handled_by_run_id: str = "",
    source_event: tuple[str, str] | None = None,
) -> list[dict]:
    """Route one occurrence only through ordinary enabled graph Tasks."""
    declared_subscribers = []
    for note in iter_notes():
        if note.kind != "task" or event not in task_triggers(note.meta):
            continue
        enabled = note.meta.get("enabled", True)
        if enabled is False or str(enabled).strip().lower() in {"0", "false", "no", "off"}:
            continue
        declared_subscribers.append(note)
    if expected_task is not None and [note.ref for note in declared_subscribers] != [expected_task]:
        if (event == "source.added" and expected_task in {LEARN_TASK_REF, "Tasks/research/distill"}
                and all(note.ref in {LEARN_TASK_REF, "Tasks/research/distill"} for note in declared_subscribers)):
            declared_subscribers = [note for note in declared_subscribers if note.ref == expected_task]
    if expected_task is not None and [note.ref for note in declared_subscribers] != [expected_task]:
        found = ", ".join(note.ref for note in declared_subscribers) or "none"
        raise ValueError(
            f"{event} must resolve exactly to {expected_task}; got {found}"
        )
    if source_event is not None and (
        expected_task is None or source_event != (
            params.get("source_id"), params.get("activation_key"),
        )
    ):
        raise ValueError("Source event requires its exact sole Task and parameters")
    handled_research = bool(
        event == "source.added"
        and _trusted_research_handler(handled_by_task_ref, handled_by_run_id)
    )
    subscribers = [
        note
        for note in declared_subscribers
        if not (
            event == "source.added"
            and note.ref in {LEARN_TASK_REF, "Tasks/research/distill"}
            and (
                params.get("source_class") == OBSERVATION_ARCHIVE_SOURCE_CLASS
                or handled_research
            )
        )
    ]
    admission = {"source_event": source_event} if source_event is not None else {}
    results = [
        {"task": note.ref, **enqueue_event(note, {"event": event, **params}, **admission)}
        for note in subscribers
    ]
    from .assignments import ensure_task_runbook
    from ..knowledge.vault import resolver
    res = resolver()
    for note in subscribers:
        ensure_task_runbook(note, res)
    return results


def _independent_occurrence(task: Note, incoming: dict) -> bool:
    """An unrelated request may pass a terminal occurrence, never replay it."""
    if str(task.meta.get("status")) not in {"failed", "blocked", "review", "interrupted"}:
        return False
    old = task.meta.get("params")
    if not isinstance(old, dict) or _event_key(old) == _event_key(incoming):
        return False
    def targets(params):
        exact = params.get("candidate_refs")
        if isinstance(exact, list) and exact and all(isinstance(ref, str) for ref in exact):
            return set(exact)
        for key in ("target", "target_ref", "destination_ref"):
            value = params.get(key)
            if isinstance(value, str) and value:
                return {value.removesuffix(".md")}
        return set()
    previous_targets, incoming_targets = targets(old), targets(incoming)
    if (str(task.meta.get("status")) == "review" and previous_targets and incoming_targets
            and not any(a == b or a.startswith(b + "/") or b.startswith(a + "/")
                        for a in previous_targets for b in incoming_targets)):
        return True  # Exact disjoint publication candidates retain separate Reviews.
    if str(task.meta.get("status")) == "review":
        return False  # Unknown publication target cannot be assumed independent.
    run_id = str(task.meta.get("last_run", ""))
    if not run_id:
        return False
    coverage = INDEX.tool_run_receipts(run_id)
    if not coverage or coverage.get("task_ref") != task.ref:
        return False  # Missing receipts are not evidence that no effect occurred.
    append_only = {"source.ingest", "source.handoff", "observations.temporary.append", "task.complete"}
    return all(call.get("status") == "returned" and (
        call.get("read_only") is True or call.get("read_only") == 1 or call.get("tool") in append_only
    ) for call in coverage["calls"])


def _promote_independent_event(task: Note) -> bool:
    waiting = _event_queue(task.meta)
    selected = next((entry for entry in waiting if _independent_occurrence(task, entry)), None)
    if selected is None:
        return False
    prior_id = task.meta.get("activation_id")
    def promote(meta):
        if meta.get("activation_id") != prior_id or str(meta.get("status")) not in {"failed", "blocked", "review", "interrupted"}:
            return
        queue = _event_queue(meta)
        if selected not in queue:
            return
        queue.remove(selected)
        meta.update(params=selected, status="pending", triggered_at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        for key in ("last_run", "summary", "blocked_reason", "activation_id"):
            meta.pop(key, None)
        if queue:
            meta["event_queue"] = queue
        else:
            meta.pop("event_queue", None)
    mutate_note_metadata(task, promote)
    return True


def enqueue_event(
    task: Note, params: dict, *, source_event: tuple[str, str] | None = None,
) -> dict:
    """Append an event occurrence to its ordinary Task's durable FIFO.

    The active occurrence remains in ``params``. Waiting occurrences live in
    ``event_queue`` on that same graph Task, so restarts and rapid UI events do
    not require a second hidden event system.
    """
    result = {"state": "queued", "status": "pending", "position": 1, "queue_depth": 1}
    applied = False
    new_occurrence = False

    def mutate(meta: dict) -> None:
        nonlocal applied, new_occurrence
        applied = True
        queue = _event_queue(meta)
        current_status = str(meta.get("status", "draft"))
        key = _event_key(params)
        active_params = meta.get("params")
        if (
            params.get("activation_key")
            and isinstance(active_params, dict)
            and _event_key(active_params) == key
        ):
            result.update(
                state="started" if current_status in _ACTIVE_EVENT_STATUSES else "processed",
                status=current_status,
                position=0,
                queue_depth=len(queue),
            )
            return
        if current_status == "review":
            if params.get("queue_after_review") is True or _independent_occurrence(task, params):
                for index, waiting in enumerate(queue):
                    if _event_key(waiting) == key:
                        result.update(
                            state="queued", status="review", position=index + 1,
                            queue_depth=len(queue),
                        )
                        return
                new_occurrence = True
                queue.append(dict(params))
                meta["event_queue"] = queue
                result.update(
                    state="queued", status="review", position=len(queue),
                    queue_depth=len(queue),
                )
                return
            # Review is unresolved runtime state, not an idle Task definition.
            # Curate will see the same lead again on a later pass; do not stack
            # or overwrite another Merge while its owner decision is pending.
            result.update(
                state="deferred",
                status="review",
                reason="target_awaiting_review",
                position=0,
                queue_depth=len(queue),
            )
            return
        # A failed or blocked event occurrence is still the unresolved active
        # commitment. New occurrences wait behind it until it is retried or
        # explicitly resolved; they must never overwrite its bound inputs.
        active = current_status in _ACTIVE_EVENT_STATUSES or (
            current_status in {"failed", "blocked"}
            and isinstance(active_params, dict)
            and bool(active_params.get("activation_key") or active_params.get("event"))
        )
        if active and isinstance(active_params, dict) and _event_key(active_params) == key:
            result.update(state="started", position=0, queue_depth=len(queue))
            return
        for index, waiting in enumerate(queue):
            if _event_key(waiting) == key:
                result.update(state="queued", position=index + 1, queue_depth=len(queue))
                return
        new_occurrence = True
        queue.append(dict(params))
        if active:
            result.update(state="queued", position=len(queue), queue_depth=len(queue))
        else:
            meta["params"] = queue.pop(0)
            meta["status"] = "pending"
            meta["triggered_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            meta.pop("blocked_reason", None)
            result.update(state="started", position=0, queue_depth=len(queue))
        if queue:
            meta["event_queue"] = queue
        else:
            meta.pop("event_queue", None)

    admission = {"source_event": source_event} if source_event is not None else {}
    mutate_note_metadata(task, mutate, **admission)
    current = load_note(task.path) or task
    if applied and _promote_independent_event(current):
        current = load_note(task.path) or current
        result.update(state="queued", status="pending", reason="independent_activation", position=0)
    if not applied:
        result.update(
            state="processed", status=str(current.meta.get("status", "draft")),
            position=0, queue_depth=len(_event_queue(current.meta)),
        )
    if result["state"] in {"started", "queued"}:
        error = _resource_error(current)
        if error:
            # The existing Tool result can describe why its durable occurrence
            # is queued. It never changes the chosen model or creator receipt.
            result.update(state="queued", reason=RESOURCE_WAIT_PREFIX + str(error))
            if str(current.meta.get("status", "")) == "pending":
                _resources_allow(current)
    result["activation_id"] = INDEX.activation_id_for(task.ref, params)
    if new_occurrence:
        wake_scheduler()
    return result


def advance_event_queue(task: Note) -> dict:
    """Promote the next queued occurrence after the active run finishes."""
    result = {"promoted": False, "queue_depth": 0}

    def mutate(meta: dict) -> None:
        queue = _event_queue(meta)
        active_params = meta.get("params")
        if isinstance(active_params, dict):
            active_key = _event_key(active_params)
            queue = [waiting for waiting in queue if _event_key(waiting) != active_key]
        if not queue:
            meta.pop("event_queue", None)
            return
        meta["params"] = queue.pop(0)
        meta["status"] = "pending"
        meta["triggered_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        meta.pop("blocked_reason", None)
        if queue:
            meta["event_queue"] = queue
        else:
            meta.pop("event_queue", None)
        result.update(promoted=True, queue_depth=len(queue))

    mutate_note_metadata(task, mutate)
    return result


def _promote_interactive_event(task: Note) -> bool:
    """Keep paused background occurrences behind a pending user commitment."""
    if str(task.meta.get("status", "")) != "pending" or not any(
        _interactive_occurrence(task.ref, waiting) for waiting in _event_queue(task.meta)
    ):
        return False
    promoted = False

    def mutate(meta: dict) -> None:
        nonlocal promoted
        if str(meta.get("status", "")) != "pending":
            return
        current = meta.get("params")
        if not isinstance(current, dict):
            return
        if _interactive_occurrence(task.ref, current):
            promoted = True
            return
        queue = _event_queue(meta)
        for index, waiting in enumerate(queue):
            if _interactive_occurrence(task.ref, waiting):
                meta["params"] = queue.pop(index)
                meta["event_queue"] = [dict(current), *queue]
                promoted = True
                return

    mutate_note_metadata(task, mutate)
    return promoted


def prepare_task(note: Note) -> bool:
    """Prepare a procedure without claiming or consuming the waiting occurrence."""
    from .assignments import ensure_task_runbook
    from ..knowledge.vault import resolver

    readiness = ensure_task_runbook(note, resolver())
    if readiness["status"] == "ready":
        return True
    reason = readiness.get("error", "awaiting-runbook")
    if readiness["status"] == "blocked" and (
        note.meta.get("status") != "blocked" or note.meta.get("blocked_reason") != reason
    ):
        update_status(note, "blocked", {"blocked_reason": reason})
    return False


def due_tasks(notes: list[Note] | None = None) -> list:
    from ..realtime.runtime import RUNTIME

    now = time.time()
    notes = iter_notes() if notes is None else notes
    # One tick owns one Agent-role snapshot. Admission is still checked again
    # at claim/execution, and no resolver survives into the next tick.
    accepted_resolver = (
        Resolver(notes) if foreground_pending() or RUNTIME.scheduler_paused() else None
    )
    due = []
    for note in notes:
        if note.kind != "task" or note.ref in _running:
            continue
        if settle_maintenance_occurrence(note):
            # Attest invalidated input before admitting an independent successor.
            continue
        if _promote_independent_event(note):
            note = load_note(note.path) or note
        if not _realtime_allows(note, accepted_resolver):
            if not _event_queue(note.meta) or not _promote_interactive_event(note):
                continue
            note = load_note(note.path)
            if note is None or not _realtime_allows(note, accepted_resolver):
                continue
        params = note.meta.get("params")
        if (
            isinstance(params, dict)
            and params.get("wait_for_idle") is True
            and _other_task_active(note.ref)
        ):
            continue
        status = str(note.meta.get("status", "draft"))
        schedule = note.meta.get("schedule")
        if (
            status == "pending"
            and isinstance(params, dict)
            and params.get("event")
            and params.get("activation_key")
        ):
            # Deliver finished research before admitting other event work.
            # Each Task FIFO remains authoritative; only competing heads are
            # ordered, chronologically within each event class.
            since = note.mtime
            try:
                since = datetime.fromisoformat(str(note.meta.get("triggered_at")
                    or note.meta.get("status_updated") or "").replace("Z", "+00:00")).timestamp()
            except (ValueError, OverflowError, OSError):
                pass
            priority = 0 if params["event"] == "source.inbox" else 1
            due.append((priority, since, note.ref, note))
        elif schedule and status in ("pending", "completed", "review", "failed"):
            if (
                status == "failed" and isinstance(params, dict)
                and params.get("event") and params.get("activation_key")
            ):
                previous = INDEX.run(str(note.meta.get("last_run", "")))
                if previous and _run_needs_disposition(previous):
                    # Retain this occurrence and the later FIFO for explicit
                    # disposition. A cron tick must not replay committed effects.
                    continue
            base = _last_fired.get(note.ref)
            if base is None:
                previous = INDEX.run(str(note.meta.get("last_run", "")))
                base = max(
                    note.mtime,
                    float(previous.get("started") or 0)
                    if previous else 0,
                )
            try:
                nxt = croniter(str(schedule), base).get_next(float)
            except (ValueError, KeyError):
                continue
            if nxt <= now and status != "review":
                due.append((2, nxt, note.ref, note))
        elif not schedule and status == "pending":
            due.append((2, note.mtime, note.ref, note))
    return [note for _kind, _since, _ref, note in sorted(due, key=lambda item: item[:3])
            if _resources_allow(note)]


async def _run(note, **run_kwargs) -> None:
    # Foreground demand can arrive after admission and before the coroutine
    # starts. Do not start or consume that occurrence when admission shut.
    if not _realtime_allows(note):
        return
    ephemeral = run_kwargs.get("interactive") is True or any(
        run_kwargs.get(key) is not None for key in ("model", "reasoning_effort", "runtime_params")
    )
    # A direct launch already checked before claim. If reservations changed,
    # the executor must reject its exact ephemeral request, not enqueue a new
    # occurrence with the saved Task's potentially different model or inputs.
    if not ephemeral and not _resources_allow(note):
        return
    if (note.meta.get("schedule") and note.meta.get("status") != "pending"
            and not ephemeral):
        previous = INDEX.run(str(note.meta.get("last_run", "")))
        base = _last_fired.get(note.ref, max(note.mtime, float((previous or {}).get("started") or 0)))
        firing = croniter(str(note.meta["schedule"]), base).get_next(float)
        enqueue_event(note, {"event": "schedule", "activation_key": f"schedule:{note.ref}:{firing}"})
        note = load_note(note.path) or note
        if note.meta.get("status") != "pending":
            return
    interruption = None
    if _autonomous_occurrence(note):
        interruption = asyncio.Event()
        _autonomous_interruptions[note.ref] = interruption
    prior_firing = _last_fired.get(note.ref)
    _last_fired[note.ref] = time.time()
    try:
        if interruption is not None:
            run_kwargs["interruption_event"] = interruption
        result = await run_task(note, **run_kwargs)
        if isinstance(result, dict) and result.get("resource_blocked") is True:
            # A reservation may arrive while the packet is being prepared.
            # With no Tool effect, the executor retains this exact occurrence.
            if prior_firing is None:
                _last_fired.pop(note.ref, None)
            else:
                _last_fired[note.ref] = prior_firing
    except Exception as exc:  # noqa: BLE001 — a failed runtime must close its Task state
        current = load_note(note.path)
        recorded = INDEX.run(str(current.meta.get("last_run", ""))) if current else None
        if (
            recorded
            and recorded.get("task_ref") == note.ref
            and float(recorded.get("started") or 0) >= _last_fired[note.ref]
            and recorded.get("status") not in {"pending", "running"}
        ):
            # The executor finalized this exact attempt before propagating the
            # error. Preserve its identity and completed Tool evidence.
            print(f"[scheduler] {note.ref} failed: {exc}")
            return
        run_id = f"failed-{uuid.uuid4().hex[:12]}"
        summary = f"execution failed before completion: {exc}"
        update_status(note, "failed", {
            "blocked_reason": summary,
            "last_run": run_id,
            "summary": summary,
        })
        INDEX.record_run(
            id=run_id,
            task_ref=note.ref,
            objective=(
                " ".join(str((run_kwargs.get("runtime_params") or {}).get("request") or "").split())
                or note.title
            ),
            agent="runtime",
            started=_last_fired[note.ref],
            finished=time.time(),
            status="failed",
            summary=summary,
            trace="[]",
            reasoning_effort=str(
                run_kwargs.get("reasoning_effort") or note.meta.get("reasoning_effort", "")
            ),
            model=str(run_kwargs.get("model") or note.meta.get("model", "")),
        )
        print(f"[scheduler] {note.ref} failed: {exc}")
    finally:
        if interruption is not None:
            _autonomous_interruptions.pop(note.ref, None)
        current = load_note(note.path)
        active_params = None if current is None else current.meta.get("params")
        queued_occurrence = bool(
            task_triggers(note.meta)
            or (isinstance(active_params, dict) and active_params.get("event") == "task.create")
        )
        if queued_occurrence:
            # Review is unresolved Task state. Preserve the waiting FIFO until
            # the owner has decided every proposal from this activation. A
            # failed occurrence retains its bound params for an explicit retry.
            if current and str(current.meta.get("status")) == "completed":
                advance_event_queue(current)


def _claim(note: Note) -> None:
    """Reserve one admitted Task identity before scheduling its coroutine."""
    if note.ref in _running:
        raise RuntimeError(f"{note.ref} is already queued or running")
    _running.add(note.ref)


async def _run_claimed(note: Note, **run_kwargs) -> None:
    try:
        await _run(note, **run_kwargs)
    finally:
        _running.discard(note.ref)


async def _resume_claimed(continuation: dict) -> None:
    """Resume one durable caller once; uncertain completion is never replayed."""
    continuation_id = str(continuation["id"])
    try:
        from ..conversation.runtime import RUNTIME

        result = await RUNTIME.resume_continuation(continuation)
        INDEX.finish_continuation(
            continuation_id,
            resumed_run_id=str(result.get("run_id", "")),
            completed=result.get("status") == "completed",
        )
    except asyncio.CancelledError:
        INDEX.finish_continuation(
            continuation_id,
            resumed_run_id="",
            completed=False,
        )
        raise
    except Exception as exc:  # noqa: BLE001 - preserve at-most-once disposition
        INDEX.finish_continuation(
            continuation_id,
            resumed_run_id="",
            completed=False,
        )
        print(f"[scheduler] continuation {continuation_id} failed: {exc}")
    finally:
        _continuations_running.discard(continuation_id)


def _claim_ready_continuation() -> dict | None:
    """Claim the oldest resumable continuation without competing with live work."""
    from ..conversation.runtime import RUNTIME

    if CONFIG.concurrency <= 0 or _running or _continuations_running or not RUNTIME.continuation_resume_available():
        return None
    for row in INDEX.ready_continuations():
        if _other_task_active(str(row["caller_task_ref"])):
            continue
        claimed = INDEX.claim_continuation(str(row["id"]))
        if claimed is not None:
            _continuations_running.add(str(claimed["id"]))
            return claimed
    return None


def launch(note, **run_kwargs) -> asyncio.Task:
    """Start one tracked Task through the same failure boundary as the scheduler."""
    if not _realtime_allows(note):
        raise RuntimeError("task is paused while foreground input owns execution")
    error = _resource_error(note, run_kwargs.get("model"))
    if error:
        raise error
    _claim(note)
    task = asyncio.create_task(_run_claimed(note, **run_kwargs))
    _background.add(task)
    task.add_done_callback(_background_finished)
    return task


async def shutdown() -> None:
    """Cancel and join active Task launches before the harness event loop closes."""
    active = [task for task in _background if not task.done()]
    for task in active:
        task.cancel()
    if active:
        await asyncio.gather(*active, return_exceptions=True)


def _launch_due_tasks() -> None:
    """Admit only free executor capacity; overdue work stays in its Task."""
    notes = iter_notes()
    active = _running | {note.ref for note in notes
                         if note.kind == "task" and str(note.meta.get("status", "")) == "running"}
    available = 0 if _continuations_running else max(0, CONFIG.concurrency - len(active))
    # Reconcile evidenced FIFO heads even while execution is occupied. No
    # semaphore waiter or Task claim is created until a slot actually exists.
    for note in due_tasks(notes):
        if available <= 0:
            break
        if not prepare_task(note):
            continue
        launch(note)
        available -= 1


async def loop() -> None:
    global _wake_loop, _wake_event
    _wake_loop, _wake_event = asyncio.get_running_loop(), asyncio.Event()
    try:
        while True:
            _wake_event.clear()
            try:
                from ..knowledge.source import dispatch_pending_source_events
                dispatch_pending_source_events()
                INDEX.sync()
                reconcile_check_health()
                from .refinement import reconcile_candidates
                reconcile_candidates()
                continuation = _claim_ready_continuation()
                if continuation is not None:
                    task = asyncio.create_task(_resume_claimed(continuation))
                    _background.add(task)
                    task.add_done_callback(_background_finished)
                else:
                    _launch_due_tasks()
            except Exception as exc:  # A failed tick must not lose queued work.
                print(f"[scheduler] tick error: {exc}")
            try:
                await asyncio.wait_for(_wake_event.wait(), timeout=CONFIG.tick_seconds)
            except TimeoutError:
                pass
    finally:
        _wake_loop, _wake_event = None, None
