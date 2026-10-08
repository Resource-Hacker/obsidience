"""Receipt-bound, once-per-occurrence recovery through the existing scheduler."""

from __future__ import annotations

import hashlib
import json
import re
import time
from functools import cache
from pathlib import Path

from ..knowledge.index import INDEX
from ..knowledge.vault import Note
from .ledger import current_task_issue

REPAIR_TASK = "Tasks/repair"
PLAN_LIMIT = 12
PASS_ATTEMPT_LIMIT = 8
ALREADY_RETRIED = "This occurrence already received its one automatic retry; further disposition is required."


def health_causes(notes: list[Note], source_issues: list | None = None) -> list[dict]:
    """Stable current-warning identities; queue growth and reads are not events."""
    causes = []
    for note in sorted(notes, key=lambda item: item.ref):
        issue = current_task_issue(note)
        if issue is None:
            continue
        identity = [note.ref, issue["kind"], note.meta.get("status"),
                    note.meta.get("last_run"), note.meta.get("params")]
        if issue["kind"] != "unresolved_occurrence":
            identity.append(issue["reason"])
        key = hashlib.sha256(json.dumps(identity, sort_keys=True, allow_nan=False).encode()).hexdigest()
        causes.append({"key": key, "task": note.ref, "run_id": str(note.meta.get("last_run") or ""),
                       "kind": issue["kind"]})
    for item in source_issues or []:
        key = hashlib.sha256(json.dumps(["source_integrity", item], sort_keys=True).encode()).hexdigest()
        causes.append({"key": key, "kind": "source_integrity",
                       "reason": str(item.get("detail") or item.get("error") or item.get("status") or "Source needs attention")[:1000],
                       "detail": str(item.get("path") or item.get("source") or "")[:1000]})
    from ..memory.hindsight import MEMORY
    return causes + MEMORY.health_findings()


@cache
def _code_revision() -> str:
    """A new repair implementation may reconsider an earlier blocked cycle."""
    return hashlib.sha256(b"".join((Path(__file__).parent / name).read_bytes()
                                   for name in ("repair.py", "scheduler.py", "executor.py",
                                                "../capabilities/registry.py", "../capabilities/harness/repair.py",
                                                "../capabilities/harness/status.py", "../memory/hindsight.py"))).hexdigest()


def definition_revision(notes: list[Note]) -> str:
    from ..knowledge.format import TASK_RUNTIME_FIELDS

    definitions = [(note.ref, note.body, {key: value for key, value in note.meta.items()
                                        if key not in TASK_RUNTIME_FIELDS})
                   for note in notes if note.kind in {"agent", "task", "runbook", "skill", "tool"}]
    return hashlib.sha256(json.dumps([_code_revision(), definitions], sort_keys=True, default=str).encode()).hexdigest()


def settle_superseded_repair(note: Note, notes: list[Note], causes: list[dict]) -> dict | None:
    """Retire an attested health pass when its evidence or code changes.

    This closes the old inspection, not its target work. A new health cycle
    still inspects current receipts and keeps every target's retry limit.
    """
    from . import scheduler

    params = note.meta.get("params") or {}
    if (note.ref != REPAIR_TASK or note.meta.get("status") != "failed"
            or params.get("event") != "harness.degraded"):
        return None
    cycle = INDEX.run(str(params.get("activation_key") or "")) or {}
    try:
        evidence = json.loads(cycle.get("trace") or "[]")[0]
        original = evidence["health_causes"]
        revision = evidence["definition_revision"]
        key = hashlib.sha256(json.dumps([sorted(cause["key"] for cause in original), revision]).encode()).hexdigest()
        if (cycle.get("id") != "health-cycle-" + key or cycle.get("task_ref") != REPAIR_TASK
                or cycle.get("agent") != "scheduler" or cycle.get("status") != "dispatched"
                or not original or original != params.get("health_causes")):
            return None
        current_revision = definition_revision(notes)
        current_keys = {cause["key"] for cause in causes}
        if revision == current_revision and any(cause["key"] in current_keys for cause in original):
            return None
    except (ValueError, TypeError, KeyError, IndexError):
        return None

    run_id = str(note.meta.get("last_run") or "")
    if scheduler._receipt_retry_blocked_reason(note, run_id, allow_retained_effects=True):
        return None
    disposition = {"disposition": "superseded_health_pass", "previous_cycle": cycle["id"],
                   "definition_revision": current_revision,
                   "retained_recovery": list(verified_retained_effects(note, run_id).values()),
                   "reason": "The prior Repair inspection is superseded; attested recovery dispositions are retained for a fresh health cycle."}
    return scheduler._settle_occurrence(
        note, kind="health_pass_settlement", classify=lambda _params: disposition,
        summary_for=lambda evidence: evidence["reason"],
        previous_safe=lambda run, _params, required: not scheduler._receipt_retry_blocked_reason(
            note, run["id"], allow_retained_effects=True))


class AlreadyProcessed(ValueError):
    def __init__(self, receipt_id: str):
        super().__init__(ALREADY_RETRIED)
        self.receipt_id = receipt_id


def _result_matches(call: dict, result: str) -> bool:
    encoded = json.dumps(result, sort_keys=True).encode()
    return (call.get("status") == "returned" and call.get("result_chars") == len(encoded)
            and call.get("result_sha256") == hashlib.sha256(encoded).hexdigest())


def _reviewed_tool(call: dict) -> bool:
    from ..config import CONFIG

    ref = "Tools/" + str(call.get("tool"))
    try:
        return (call.get("tool_ref") == ref and call.get("tool_sha256")
                == hashlib.sha256((CONFIG.vault_dir / (ref + ".md")).read_bytes()).hexdigest())
    except OSError:
        return False


def _verified_memory_repair_dispositions(note: Note, run_id: str, coverage: dict, entries: list[dict]) -> dict:
    """Retain exact native recovery or pre-mutation refusals, never replay them."""
    if note.ref != REPAIR_TASK or coverage.get("run_id") != run_id:
        return {}
    # Executor steps include rejected completion and repeat-blocked calls. A
    # missing/truncated trace cannot accidentally bind a later dispatch here.
    steps = {step: entry for step, entry in enumerate(
        (entry for entry in entries if "tool" in entry), 1)}
    grouped = {}
    for call in coverage["calls"]:
        if call["tool"] == "harness.repair":
            grouped.setdefault(call["signature"], []).append(call)
    retained = {}
    for signature, calls in grouped.items():
        evidence = []
        for call in calls:
            entry = steps.get(call["step"], {})
            args = entry.get("args")
            if (call["status"] != "returned" or not _reviewed_tool(call)
                    or call["call_id"] != f"{run_id}:{call['step']}"
                    or entry.get("tool") != "harness.repair" or entry.get("sig") != signature
                    or entry.get("not_dispatched") or entry.get("interrupted") or entry.get("must_not_replay")
                    or not isinstance(args, dict) or not _result_matches(call, str(entry.get("obs")))
                    or signature != "harness.repair:sha256:" + hashlib.sha256(
                        json.dumps(args, sort_keys=True).encode()).hexdigest()):
                break
            try:
                result = json.loads(entry["obs"])
            except (ValueError, TypeError):
                break
            if not isinstance(result, dict):
                break
            if args == {"component": "hindsight"}:
                operations = result.get("operations")
                if (result.get("status") != "requeued" or not isinstance(operations, list)
                        or len(operations) != 1 or not isinstance(operations[0], dict)
                        or operations[0].get("accepted") is not True):
                    break
                identifier = operations[0].get("operation_id")
                if not isinstance(identifier, str) or not re.fullmatch(
                        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", identifier):
                    break
                with INDEX.lock:
                    intent = INDEX.db.execute("SELECT attempted_at FROM memory_retries WHERE operation_id=?",
                                              (identifier,)).fetchone()
                if not intent or not call["started"] <= intent[0] <= call["finished"]:
                    break
                evidence.append({"disposition": "native_memory_recovery_retained",
                                 "operation_id": identifier, "call_id": call["call_id"]})
            elif (set(args) == {"task", "run_id"} and result.get("status") == "blocked"
                  and result.get("reason") == "A Tool may have committed effects."
                  and all(result.get(key) == value for key, value in args.items())):
                # The inspected blocked plan returns before the scheduler's
                # mutation path; this does not disposition the target's effects.
                evidence.append({"disposition": "rejected_recovery", "call_id": call["call_id"], **args})
            else:
                break
        else:
            # Signature-wide consumers must cover every sibling; an interrupted
            # or omitted call may not inherit another call's retained evidence.
            siblings = [(step, entry) for step, entry in steps.items()
                        if entry.get("sig") == signature]
            receipt_steps = {call["step"] for call in calls}
            refusal = ("You have repeated this exact call three times; the result will not change. "
                       "Vary your approach or call task.complete now with your best status.")
            if any(step not in receipt_steps and not (
                    entry.get("tool") == "harness.repair" and entry.get("not_dispatched") is True
                    and entry.get("repeat_blocked") is True and entry.get("obs") == refusal)
                   for step, entry in siblings):
                continue
            identifiers = [item["operation_id"] for item in evidence if "operation_id" in item]
            if len(set(identifiers)) != len(identifiers):
                continue
            retained[signature] = {"disposition": "repair_calls_retained", "calls": evidence}
    return retained


def verified_retained_effects(note: Note, run_id: str) -> dict:
    """Completed handoffs/manifests may be retained during settlement, never replayed."""
    from ..config import CONFIG
    from .scheduler import _maintenance_recorded_args, _retry_trace

    coverage = INDEX.tool_run_receipts(run_id)
    entries = _retry_trace(INDEX.run(run_id) or {})
    if not coverage or entries is None:
        return {}
    params = note.meta.get("params") or {}
    retained = _verified_memory_repair_dispositions(note, run_id, coverage, entries)
    for call in coverage["calls"]:
        if call["status"] != "returned" or not _reviewed_tool(call):
            continue
        matches = [entry for entry in entries if entry.get("tool") == call["tool"]
                   and entry.get("sig") == call["signature"]]
        if len(matches) != 1 or not isinstance(matches[0].get("args"), dict):
            continue
        entry = matches[0]
        args = entry["args"]
        if note.ref == REPAIR_TASK and call["tool"] == "harness.repair":
            if set(args) != {"task", "run_id"} or not _result_matches(call, str(entry.get("obs"))):
                continue
            try:
                result = json.loads(entry["obs"])
            except (ValueError, TypeError):
                continue
            if not isinstance(result, dict) or any(result.get(key) != value for key, value in args.items()):
                continue
            if result.get("status") == "blocked" and result.get("reason") == "controller receipt requires an active owner transaction":
                from ..knowledge.vault import load_note
                child = load_note(args["task"] + ".md")
                if (not child or child.meta.get("status") != "failed" or child.meta.get("last_run") != args["run_id"]
                        or retry_receipt(child) is not None):
                    continue
                evidence = {"disposition": "rejected_recovery", "task": child.ref, "run_id": args["run_id"]}
            elif (result.get("status") == "blocked" and result.get("reason")
                  == "The exact occurrence is absent or ambiguous in the inspected plan."):
                # The exact attested adapter result precedes every mutation.
                # A stale warning cannot turn this refusal into an unknown effect.
                evidence = {"disposition": "rejected_recovery", **args}
            elif result.get("status") == "requeued":
                receipt = INDEX.run(str(result.get("repair_receipt_id") or "")) or {}
                try:
                    applied = json.loads(receipt.get("trace") or "[]")[0]["controller_disposition"]
                except (ValueError, TypeError, KeyError, IndexError):
                    continue
                child_coverage = INDEX.tool_run_receipts(args["run_id"])
                if (receipt.get("agent") != "scheduler" or receipt.get("task_ref") != args["task"]
                        or receipt.get("status") != "requeued" or applied.get("kind") != "automatic_retry"
                        or applied.get("previous_run_id") != args["run_id"] or not child_coverage
                        or applied.get("params_sha256") != child_coverage["params_sha256"]):
                    continue
                evidence = {"disposition": "recovery_retained", "repair_receipt_id": receipt["id"], **args}
            else:
                continue
        elif note.ref == "Tasks/curate" and call["tool"] == "task.create":
            if not _result_matches(call, str(entry.get("obs"))):
                continue
            try:
                result = json.loads(entry["obs"])
            except (ValueError, TypeError):
                continue  # A rejected activation can return plain text, with no handoff.
            if not isinstance(result, dict):
                continue
            activation = INDEX.activation(str(result.get("activation_id", "")))
            if (not activation or result.get("state") not in {"started", "queued", "processed"}
                    or result.get("waiting_for_result") is not False or result.get("continuation_id")
                    or result.get("created_by") != note.ref
                    or activation["task_ref"] != result.get("task")):
                continue
            child = activation["params"]
            args = _maintenance_recorded_args(args, child.get("candidate_signals", {}))
            if (args is None or set(args) != {"task", "params"} or args["task"] != activation["task_ref"]
                    or child.get("created_by_run_id") != run_id or child.get("created_by_task_ref") != note.ref
                    or child != {**args["params"], "event": "task.create", "target_task": args["task"],
                                 "created_by_run_id": run_id, "created_by_task_ref": note.ref,
                                 "activation_key": child.get("activation_key")}):
                continue
            evidence = {"disposition": "handoff_retained", "activation_id": activation["id"],
                        "child_task": activation["task_ref"], "child_status": activation["status"]}
        elif note.ref == "Tasks/research/distill" and call["tool"] == "source.handoff":
            from ..knowledge.source import _row_doc

            source_id = params.get("source_id")
            if (params.get("event") != "source.added" or not isinstance(source_id, str)
                    or not _result_matches(call, str(entry.get("obs")))):
                continue
            identity = hashlib.sha256(source_id.encode()).hexdigest()[:20]
            row = INDEX.source_by_event_key(f"source.inbox:research:{run_id}:{note.ref}:{identity}")
            if (not row or row.get("origin_source_id") != source_id
                    or row.get("source_type") != "research" or not row["path"].startswith("inbox/")
                    or not row.get("event_dispatched_at")
                    or row["material_sha256"] != "sha256:" + hashlib.sha256(bytes(row["material"])).hexdigest()):
                continue
            try:
                handoff = _row_doc(row, include_content=True)
            except (ValueError, TypeError, KeyError):
                continue
            if (handoff["content_sha256"] != row["content_sha256"]
                    or handoff["citation"] not in str(entry.get("obs"))
                    or handoff["content_sha256"] not in str(entry.get("obs"))):
                continue
            # The immutable Inbox reconstructs long arguments that the display
            # trace may truncate. Its exact digest must still match the intent.
            args = {"title": handoff["source_ref"], "content": handoff["content"]}
            evidence = {"disposition": "research_handoff_retained", "source": handoff["citation"],
                        "source_sha256": handoff["content_sha256"]}
        elif note.ref == "Tasks/research/model" and call["tool"] in {"model.inspect", "model.source", "model.benchmark"}:
            model_id = params.get("model_id")
            fingerprint = params.get("model_fingerprint")
            if (params.get("event") != "model.added" or not isinstance(model_id, str)
                    or not re.fullmatch(r"[A-Za-z0-9_.-]+", model_id)
                    or not isinstance(fingerprint, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", fingerprint)
                    or args.get("model_id") != model_id):
                continue
            relative = f"models/{model_id}/artifact--{fingerprint[7:23]}.json"
            source_path = "obsidience/evidence/" + relative
            if params.get("source_path") != source_path:
                continue
            try:
                manifest = json.loads((CONFIG.source_dir / relative).read_text())
                identity = {key: value for key, value in manifest.items() if key != "fingerprint"}
                actual = "sha256:" + hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            except (OSError, ValueError, TypeError):
                continue
            if actual != fingerprint or manifest.get("fingerprint") != fingerprint or manifest.get("model_id") != model_id:
                continue
            if call["tool"] == "model.benchmark":
                # This legacy adapter rejected external hardware before a lease
                # or measurement. Every other benchmark failure remains unknown.
                if (manifest.get("hardware_assignable") is not False or set(args) != {"model_id", "devices"}
                        or not _result_matches(call, "Model benchmark failed: host model hardware is managed on Windows.")):
                    continue
            elif set(args) != {"model_id"}:
                continue
            elif call["tool"] == "model.source" and not _result_matches(
                    call, f"Model artifact registered at {source_path} ({fingerprint})."):
                continue
            evidence = {"disposition": "manifest_retained", "model_id": model_id,
                        "source_path": source_path, "fingerprint": fingerprint}
        else:
            continue
        signature = call["tool"] + ":sha256:" + hashlib.sha256(json.dumps(args, sort_keys=True).encode()).hexdigest()
        if signature == call["signature"]:
            retained[signature] = evidence
    return retained


def retired_model_evidence(note: Note) -> dict | None:
    """A model.added occurrence whose model left the catalog can never run."""
    from ..models.runtime import MODELS

    params = note.meta.get("params") or {}
    model_id = params.get("model_id")
    if (note.ref != "Tasks/research/model" or note.meta.get("status") not in {"pending", "failed"}
            or params.get("event") != "model.added" or not isinstance(model_id, str) or model_id in MODELS):
        return None
    return {"disposition": "retired_model", "model_id": model_id,
            "model_fingerprint": params.get("model_fingerprint"),
            "reason": "The event model is no longer registered; no benchmark or configuration can apply. "
                      "Earlier receipts and manifests are retained and no Tool was replayed."}


def settlement_evidence(note: Note) -> dict | None:
    from . import scheduler

    if note.meta.get("status") != "failed":
        return None
    run_id = str(note.meta.get("last_run") or "")
    run = INDEX.run(run_id) or {}
    params = note.meta.get("params") or {}
    if (run.get("task_ref") != note.ref or run.get("status") not in {"failed", "interrupted"}
            or not run.get("finished") or scheduler._receipt_retry_blocked_reason(
                note, run_id, allow_retained_effects=True,
                allow_source_captures=note.ref == "Tasks/research/distill")):
        return None
    retained = list(verified_retained_effects(note, run_id).values())
    if note.ref == "Tasks/audit":
        return scheduler._resolved_input_evidence(note, params)
    if note.ref == "Tasks/curate":
        if (len(retained) == 1 and retained[0]["disposition"] == "handoff_retained"
                and scheduler._retry_binding_matches(note, scheduler._retry_trace(run) or [])):
            return {**retained[0], "reason": "Curate already handed off its one child; its outcome remains separate."}
    elif note.ref == "Tasks/research/distill":
        if (len(retained) == 1 and retained[0]["disposition"] == "research_handoff_retained"
                and scheduler._retry_binding_matches(note, scheduler._retry_trace(run) or [])):
            return {**retained[0], "reason": "Distill delivered its verified Source Inbox before interruption; Ingest owns publication and no research or handoff is replayed."}
    elif note.ref == "Tasks/research/model":
        return retired_model_evidence(note)
    else:
        evidence = scheduler._maintenance_creator_evidence(note, params)
        if evidence and scheduler._maintenance_failure_clear(run, params, required=True):
            return evidence
    return None


def settle_failed_occurrence(note: Note, expected_run_id: str) -> dict:
    from . import scheduler

    if note.meta.get("last_run") != expected_run_id:
        raise ValueError("The failed execution changed after inspection.")
    result = scheduler._settle_occurrence(
        note, kind="repair_settlement", classify=lambda params: settlement_evidence(note),
        summary_for=lambda evidence: evidence["reason"],
        previous_safe=lambda run, params, required: settlement_evidence(note) is not None)
    if result is None:
        raise ValueError("The settlement evidence or Task queue changed; refresh health.")
    return result


def _retry_correction(note: Note) -> str:
    """One additional retry for an exact, reviewed proposal-scope correction."""
    from .scheduler import _preflight_rejection, _retry_trace

    params = note.meta.get("params") or {}
    if note.ref == "Tasks/curate" and params.get("event") == "observations.memory.ready":
        correction = "memory-curate-scope-v1"
    elif note.ref == "Tasks/ingest" and params.get("event") == "source.inbox" and not params.get("feed_binding"):
        correction = "ingest-create-update-v1"
    else:
        return ""
    run_id = str(note.meta.get("last_run") or "")
    coverage = INDEX.tool_run_receipts(run_id)
    if correction == "memory-curate-scope-v1" and any(
            call["tool"] == "vault.propose" and _preflight_rejection(call, note)
            == "Proposal rejected: Memory recommendation must cite its exact bound observation Source."
            for call in (coverage or {}).get("calls", [])):
        return correction
    for entry in _retry_trace(INDEX.run(run_id) or {}) or []:
        if (entry.get("tool") == "vault.propose" and entry.get("args", {}).get("action") == "archive"
                and not entry.get("args", {}).get("body") and any(
                    call["signature"] == entry.get("sig") and _preflight_rejection(call, note)
                    for call in (coverage or {}).get("calls", []))):
            return correction
    return ""


def verified_source_captures(note: Note, run_id: str) -> dict:
    """Attest completed public fetches against their full immutable results.

    A Source capture remains an effect. Only Repair may explicitly retain it
    while retrying research; an interrupted/partial capture is never eligible.
    The shortened trace locates evidence, but the durable full-result digest
    and Source bytes, not trace prose, authorize this disposition.
    """
    from ..capabilities.web.fetch import _render_batch, _render_result
    from ..knowledge.source import _row_doc
    from .scheduler import _retry_trace

    if note.ref not in {"Tasks/research/learn", "Tasks/research/distill"}:
        return {}
    params = note.meta.get("params") or {}
    if params.get("event") != "source.added":
        return {}
    coverage = INDEX.tool_run_receipts(run_id)
    entries = _retry_trace(INDEX.run(run_id) or {})
    if not coverage or entries is None:
        return {}
    captures = {}
    for call in coverage["calls"]:
        if (call["tool"] != "web.fetch" or call["status"] != "returned"
                or call["tool_ref"] != "Tools/web.fetch" or not call["tool_sha256"]):
            continue
        matches = [entry for entry in entries if entry.get("tool") == "web.fetch"
                   and entry.get("sig") == call["signature"]]
        if len(matches) != 1:
            continue
        entry = matches[0]
        args = entry.get("args")
        if not isinstance(args, dict) or set(args) not in ({"url"}, {"urls"}):
            continue
        urls = args["urls"] if "urls" in args else [args["url"]]
        if (not isinstance(urls, list) or len(urls) != 1 or not isinstance(urls[0], str)
                or not urls[0].startswith(("https://", "http://"))
                or call["signature"] != "web.fetch:sha256:" + hashlib.sha256(
                    json.dumps(args, sort_keys=True).encode()).hexdigest()):
            continue
        if params.get("feed_binding") and urls[0] != params["feed_binding"].get("reporting_url"):
            continue
        found = re.search(r"source://([0-9a-f-]{36})", str(entry.get("obs", "")))
        row = INDEX.source(found[1]) if found else None
        if (not row or not row["path"].startswith("raw/") or row["source_type"] != "tool"
                or row.get("event_key") != params.get("activation_key")
                or row["material_sha256"] != "sha256:" + hashlib.sha256(bytes(row["material"])).hexdigest()):
            continue
        try:
            source = _row_doc(row, include_content=True)
        except (ValueError, KeyError, TypeError):
            continue
        if source["content_sha256"] != row["content_sha256"] or source["id"] != row["id"]:
            continue
        for created in (True, False):
            result = {**source, "url": source["source_ref"], "created": created}
            rendered = _render_batch(urls, [result]) if "urls" in args else _render_result(result)
            encoded = json.dumps(rendered, sort_keys=True).encode()
            if (len(encoded) == call["result_chars"]
                    and hashlib.sha256(encoded).hexdigest() == call["result_sha256"]):
                captures[call["signature"]] = {
                    "call_id": call["call_id"], "source": source["citation"],
                    "source_sha256": source["content_sha256"],
                }
                break
    return captures if len(captures) <= 8 else {}


def repair_attempt_count(context: dict) -> int:
    """Count this executor's actual Repair calls, not model-authored evidence."""
    trace = context.get("trace")
    if not isinstance(trace, list):
        return 0
    return sum(isinstance(entry, dict) and entry.get("tool") == "harness.repair"
               and entry.get("not_dispatched") is not True for entry in trace)


def available_tools(allowed: list[str], context: dict) -> list[str]:
    """Expose the same fresh-inspection prerequisite as Repair completion."""
    if context.get("task") == REPAIR_TASK and "harness.status" in allowed:
        snapshot = context.get("_harness_snapshot")
        if not isinstance(snapshot, dict):
            return ["harness.status"]
        plan = snapshot.get("repair_plan")
        if (repair_attempt_count(context) >= PASS_ATTEMPT_LIMIT
                or not isinstance(plan, list)
                or not any(isinstance(row, dict) and row.get("operation") in {"retry", "settle"}
                           for row in plan)):
            return [name for name in allowed if name != "harness.repair"]
    return allowed


def occurrence_key(note: Note) -> str:
    """A later run ID does not create a new original event commitment."""
    params = note.meta.get("params")
    # Event identity survives a changed/normalized parameter spelling. The
    # receipt separately pins every original parameter, so such drift blocks
    # recovery instead of granting a second retry for the same commitment.
    event_key = (params.get("activation_key") or params.get("model_event_id")
                 if isinstance(params, dict) else None)
    identity = ([params["event"], event_key]
                if isinstance(params, dict) and isinstance(params.get("event"), str)
                and params["event"] and isinstance(event_key, str) and event_key else params)
    encoded = json.dumps([note.ref, identity], sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def retry_receipt(note: Note) -> dict | None:
    key = occurrence_key(note)
    correction = _retry_correction(note)
    receipt = INDEX.run("repair-" + key + ("-" + correction if correction else ""))
    if receipt is None:
        return None
    try:
        raw = receipt.get("trace")
        if not isinstance(raw, str) or len(raw) > 4096:
            raise ValueError
        evidence = json.loads(raw)[0]["controller_disposition"]
        if (not isinstance(evidence, dict)
                or receipt.get("task_ref") != note.ref or receipt.get("agent") != "scheduler"
                or receipt.get("status") != "requeued" or evidence.get("kind") != "automatic_retry"
                or evidence.get("occurrence_key") != key
                or evidence.get("correction", "") != correction
                or evidence.get("params_sha256") != INDEX.tool_params_sha256(note.meta.get("params"))
                or evidence.get("effect_applied") is not True
                or not isinstance(evidence.get("previous_run_id"), str) or not evidence["previous_run_id"]):
            raise ValueError
    except (ValueError, TypeError, IndexError, KeyError):
        raise ValueError("Existing automatic repair receipt cannot be attested.") from None
    return {"id": receipt["id"], "previous_run_id": evidence["previous_run_id"]}


def _blocked_reason(note: Note) -> str:
    from . import scheduler

    if note.ref == REPAIR_TASK:
        return "Repair cannot retry itself."
    if retry_receipt(note) is not None:
        return ALREADY_RETRIED
    # The owner Retry API retains its historical compatibility path. Autonomous
    # Repair cannot infer missing dispatch coverage from that legacy trace.
    reason = scheduler._receipt_retry_blocked_reason(
        note, str(note.meta.get("last_run") or ""), allow_source_captures=True,
        allow_retained_effects=note.ref == "Tasks/research/model")
    return reason or scheduler.retry_blocked_reason(note, allow_source_captures=True,
                                                   allow_retained_effects=note.ref == "Tasks/research/model")


def repair_plan(notes: list[Note], *, limit: int = PLAN_LIMIT) -> list[dict]:
    """Bounded guidance for current issues, never authority to replay an effect."""
    eligible, blocked = [], []
    for note in sorted(notes, key=lambda item: item.ref):
        issue = current_task_issue(note)
        if note.ref == REPAIR_TASK or issue is None:
            continue
        try:
            key = occurrence_key(note)
            settlement = settlement_evidence(note) if issue["kind"] == "unresolved_occurrence" else None
            reason = ("" if settlement else _blocked_reason(note) if issue["kind"] == "unresolved_occurrence"
                      else "Repair does not change Task configuration: " + issue["reason"])
        except (ValueError, TypeError, RecursionError):
            key, settlement, reason = "", None, "The occurrence or existing recovery evidence cannot be attested."
        target = blocked if reason else eligible
        if len(target) < limit:
            target.append({"task": note.ref, "run_id": str(note.meta.get("last_run") or ""),
                           "occurrence_key": key, "operation": "blocked" if reason else "settle" if settlement else "retry",
                           "reason": reason or (settlement["reason"] if settlement else "Exact durable receipts permit one retry through normal Task admission.")})
        # Blocked rows cannot conceal later eligible work. Both temporary lists
        # and the final display stay bounded; ties retain exact Task order.
        if len(eligible) == limit:
            break
    return eligible + blocked[:limit - len(eligible)]


def check_retry_transaction(note: Note, *, already_pending: bool) -> None:
    """Recheck at the existing Task-runtime transaction's mutation boundary."""
    if not INDEX.db.in_transaction:
        raise ValueError("Automatic retry requires the Task owner transaction.")
    receipt = retry_receipt(note)
    if receipt is not None:
        raise AlreadyProcessed(receipt["id"])
    if already_pending:
        raise ValueError("The Task occurrence is already pending; no automatic retry was applied.")
    reason = _blocked_reason(note)
    if reason:
        raise ValueError(reason)


def record_retry_transaction(note: Note, previous_run_id: str) -> str:
    """The controller receipt and pending state commit or roll back together."""
    key = occurrence_key(note)
    correction = _retry_correction(note)
    receipt_id = "repair-" + key + ("-" + correction if correction else "")
    now = time.time()
    retained = list(verified_source_captures(note, previous_run_id).values())
    manifests = list(verified_retained_effects(note, previous_run_id).values()) if note.ref == "Tasks/research/model" else []
    INDEX.record_run(overwrite=False, commit=False, id=receipt_id, task_ref=note.ref,
                     agent="scheduler", started=now, finished=now, status="requeued",
                     objective="Requeue one receipt-attested Task occurrence",
                     summary="One automatic retry queued; the target outcome remains unverified.",
                     trace=json.dumps([{"controller_disposition": {
                         "kind": "automatic_retry", "occurrence_key": key, "correction": correction,
                         "params_sha256": INDEX.tool_params_sha256(note.meta.get("params")),
                         "activation_key": note.meta["params"].get("activation_key") or note.meta["params"].get("model_event_id"),
                         "previous_run_id": previous_run_id, "effect_applied": True,
                         "effect": "task_requeued", "tools_replayed": False,
                         "retained_source_captures": retained,
                         "retained_model_manifests": manifests,
                     }}], sort_keys=True))
    return receipt_id
