"""Small execution-ledger helpers; run state itself lives in SQLite."""

from __future__ import annotations

import hashlib
import math
import statistics
import time

from ..knowledge.vault import Note


def runbook_hash(runbook: Note) -> str:
    """Hash the exact Runbook revision used by a leaf Task session."""
    from ..config import CONFIG

    return hashlib.sha256((CONFIG.vault_dir / runbook.path).read_bytes()).hexdigest()


def runbook_tree_hash(runbooks: list[Note]) -> str:
    """Attest an ordered recursive Runbook tree while preserving leaf hashes."""
    if len(runbooks) == 1:
        return runbook_hash(runbooks[0])
    from ..config import CONFIG

    digest = hashlib.sha256()
    for runbook in runbooks:
        digest.update(runbook.ref.encode())
        digest.update(b"\0")
        digest.update((CONFIG.vault_dir / runbook.path).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def current_task_issue(task: Note) -> dict | None:
    """Separate unresolved current work from a terminal attempt's history.

    This is a projection of existing Task execution state, not a health store
    or a retry decision. Historical failed runs remain available unchanged.
    """
    if task.kind != "task":
        return None
    meta = task.meta
    status = str(meta.get("status", "draft"))
    params = meta.get("params")
    commitment = isinstance(params, dict) and bool(params.get("activation_key") or params.get("event"))
    waiting = meta.get("event_queue")
    queued = len(waiting) if isinstance(waiting, list) else 0
    if status in {"failed", "blocked"} and (commitment or queued):
        kind = "unresolved_occurrence"
        reason = meta.get("blocked_reason") or meta.get("summary") or "The previous attempt needs resolution."
    elif status == "blocked":
        kind = "blocked_configuration"
        reason = meta.get("blocked_reason") or meta.get("summary") or "Task configuration needs resolution."
    elif status == "draft" and meta.get("schedule"):
        kind = "scheduled_draft"
        reason = "Scheduled Task is still draft."
    else:
        return None
    return {"kind": kind, "reason": str(reason)[:500], "queued": queued}


HISTORY_WINDOW_DAYS = 7
HISTORY_RUN_LIMIT = 200
HISTORY_TOOL_LIMIT = 400
HISTORY_FINDING_LIMIT = 8
HISTORY_EVIDENCE_LIMIT = 3
HISTORY_MIN_RUNS = 3
HISTORY_MIN_FAILURES = 2
HISTORY_FAILURE_RATIO = 0.5
_HISTORY_STATUSES = ("completed", "failed", "blocked", "cancelled", "interrupted", "review")
_TOOL_HISTORY_STATUSES = ("started", "returned", "error", "rejected", "interrupted", "undispatched")


def run_history_findings(index, *, now: float | None = None) -> dict:
    """Project historical patterns from exact run metadata, never retry authority.

    Areev's run-outcome analyzer is the pattern reference: group by executable
    revision and require a meaningful sample. Obsidience keeps its existing
    ledger, health semantics and recorded outcome names. No result prose is read.
    """
    now = time.time() if now is None else now
    if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
        raise ValueError("Invalid history observation time")
    since = max(0.0, now - HISTORY_WINDOW_DAYS * 86_400)
    sample = index.run_history_sample(since=since, until=now, limit=HISTORY_RUN_LIMIT)
    counts = dict.fromkeys(_HISTORY_STATUSES, 0)
    excluded = {"unattested_revision": 0, "invalid_identity": 0, "invalid_time": 0,
                "other_status": 0}
    groups = {}
    for run in sample["runs"]:
        status = run["status"]
        if status not in counts:
            excluded["other_status"] += 1
            continue
        counts[status] += 1
        if any(not isinstance(run[key], str) or not 0 < len(run[key]) <= maximum
               for key, maximum in (("id", 128), ("task_ref", 512))):
            excluded["invalid_identity"] += 1
            continue
        revision = run["runbook_sha256"]
        if (not isinstance(run["runbook_ref"], str) or not 0 < len(run["runbook_ref"]) <= 512
                or not isinstance(revision, str) or len(revision) != 64
                or any(char not in "0123456789abcdef" for char in revision)):
            excluded["unattested_revision"] += 1
            continue
        started, finished = run["started"], run["finished"]
        if (type(started) not in (int, float) or type(finished) not in (int, float)
                or not math.isfinite(started) or not math.isfinite(finished)
                or not since <= started <= finished <= now):
            excluded["invalid_time"] += 1
            continue
        key = (run["task_ref"], run["runbook_ref"], revision)
        group = groups.setdefault(key, {"counts": dict.fromkeys(_HISTORY_STATUSES, 0),
                                       "evidence_run_ids": [], "durations": []})
        group["counts"][status] += 1
        if status in {"failed", "blocked"} and len(group["evidence_run_ids"]) < HISTORY_EVIDENCE_LIMIT:
            group["evidence_run_ids"].append(run["id"])
        if status in {"completed", "failed", "blocked"}:
            group["durations"].append(finished - started)

    findings = []
    for (task_ref, runbook_ref, revision), group in sorted(groups.items()):
        totals = group["counts"]
        failures = totals["failed"] + totals["blocked"]
        eligible = failures + totals["completed"]
        if (eligible < HISTORY_MIN_RUNS or failures < HISTORY_MIN_FAILURES
                or failures / eligible < HISTORY_FAILURE_RATIO):
            continue
        durations = group["durations"]
        findings.append({
            "kind": "recurring_unsuccessful_runs", "task_ref": task_ref,
            "runbook_ref": runbook_ref, "runbook_sha256": revision,
            "scope": "recorded_revision", "counts": totals, "eligible_runs": eligible,
            "failure_count": failures, "failure_ratio": round(failures / eligible, 3),
            "evidence_run_ids": group["evidence_run_ids"],
            "evidence_omitted": failures - len(group["evidence_run_ids"]),
            "duration_seconds": {"samples": len(durations),
                                 "median": round(statistics.median(durations), 3),
                                 "max": round(max(durations), 3)},
            "summary": (f"{task_ref}: {totals['failed']} failed and {totals['blocked']} blocked "
                        f"of {eligible} completed/failed/blocked attempts at recorded Runbook "
                        f"revision {revision[:12]}. Historical evidence, not a current fault."),
        })
    findings.sort(key=lambda finding: (-finding["failure_count"], -finding["failure_ratio"],
                                      finding["task_ref"], finding["runbook_ref"],
                                      finding["runbook_sha256"]))
    return {
        "version": 1, "window_basis": "run_started", "window_days": HISTORY_WINDOW_DAYS,
        "window_start": since, "window_end": now, "run_limit": HISTORY_RUN_LIMIT,
        "sampled_runs": len(sample["runs"]), "scan_complete": sample["scan_complete"],
        "counts": counts, "excluded": excluded, "revision_groups": len(groups),
        "threshold": {"min_eligible_runs": HISTORY_MIN_RUNS, "min_failures": HISTORY_MIN_FAILURES,
                      "min_failure_ratio": HISTORY_FAILURE_RATIO},
        "findings_limit": HISTORY_FINDING_LIMIT,
        "findings_omitted": max(0, len(findings) - HISTORY_FINDING_LIMIT),
        "findings": findings[:HISTORY_FINDING_LIMIT],
        "tools": _tool_history_findings(index, since=since, until=now),
    }


def _tool_history_findings(index, *, since: float, until: float) -> dict:
    """Exact receipt outcomes describe dispatch, not returned content or causes."""
    sample = index.tool_history_sample(since=since, until=until, limit=HISTORY_TOOL_LIMIT)
    counts = dict.fromkeys(_TOOL_HISTORY_STATUSES, 0)
    excluded = {"unattested_revision": 0, "invalid_identity": 0, "invalid_time": 0,
                "other_status": 0}
    groups = {}
    for call in sample["calls"]:
        status = call["status"]
        if status not in counts:
            excluded["other_status"] += 1
            continue
        counts[status] += 1
        if any(not isinstance(call[key], str) or not 0 < len(call[key]) <= maximum
               for key, maximum in (("run_id", 128), ("call_id", 256), ("task_ref", 512), ("tool", 256))):
            excluded["invalid_identity"] += 1
            continue
        revision = call["tool_sha256"]
        if (not isinstance(call["tool_ref"], str) or not 0 < len(call["tool_ref"]) <= 512
                or not isinstance(revision, str) or len(revision) != 64
                or any(char not in "0123456789abcdef" for char in revision)):
            excluded["unattested_revision"] += 1
            continue
        started, finished, duration = call["started"], call["finished"], call["duration_ms"]
        if (type(started) not in (int, float) or not math.isfinite(started) or not since <= started <= until
                or (status != "started" and (
                    type(finished) not in (int, float) or not math.isfinite(finished) or not started <= finished <= until
                    or type(duration) not in (int, float) or not math.isfinite(duration) or duration < 0))):
            excluded["invalid_time"] += 1
            continue
        key = (call["task_ref"], call["tool"], call["tool_ref"], revision)
        group = groups.setdefault(key, {"counts": dict.fromkeys(_TOOL_HISTORY_STATUSES, 0),
                                       "evidence_calls": [], "durations": []})
        group["counts"][status] += 1
        if status in {"error", "rejected"} and len(group["evidence_calls"]) < HISTORY_EVIDENCE_LIMIT:
            group["evidence_calls"].append({"run_id": call["run_id"], "call_id": call["call_id"]})
        if status in {"returned", "error", "rejected"}:
            group["durations"].append(duration)

    findings = []
    for (task_ref, tool, tool_ref, revision), group in groups.items():
        totals = group["counts"]
        errors = totals["error"] + totals["rejected"]
        eligible = errors + totals["returned"]
        if (eligible < HISTORY_MIN_RUNS or errors < HISTORY_MIN_FAILURES
                or errors / eligible < HISTORY_FAILURE_RATIO):
            continue
        durations = group["durations"]
        findings.append({
            "kind": "recurring_tool_dispatch_errors", "task_ref": task_ref,
            "tool": tool, "tool_ref": tool_ref, "tool_sha256": revision,
            "scope": "recorded_tool_revision", "counts": totals, "eligible_calls": eligible,
            "error_count": errors, "error_ratio": round(errors / eligible, 3),
            "evidence_calls": group["evidence_calls"],
            "evidence_omitted": errors - len(group["evidence_calls"]),
            "duration_ms": {"samples": len(durations), "median": round(statistics.median(durations), 3),
                            "max": round(max(durations), 3)},
            "summary": (f"{task_ref}, {tool}: {totals['error']} error and {totals['rejected']} rejected "
                        f"receipts of {eligible} returned/error/rejected calls at recorded Tool revision "
                        f"{revision[:12]}. Dispatch evidence does not establish semantic success or root cause."),
        })
    findings.sort(key=lambda finding: (-finding["error_count"], -finding["error_ratio"],
                                      finding["task_ref"], finding["tool"], finding["tool_ref"],
                                      finding["tool_sha256"]))
    return {"window_basis": "call_started", "call_limit": HISTORY_TOOL_LIMIT,
            "sampled_calls": len(sample["calls"]), "scan_complete": sample["scan_complete"],
            "counts": counts, "excluded": excluded, "revision_groups": len(groups),
            "threshold": {"min_eligible_calls": HISTORY_MIN_RUNS, "min_errors": HISTORY_MIN_FAILURES,
                          "min_error_ratio": HISTORY_FAILURE_RATIO},
            "findings_limit": HISTORY_FINDING_LIMIT,
            "findings_omitted": max(0, len(findings) - HISTORY_FINDING_LIMIT),
            "findings": findings[:HISTORY_FINDING_LIMIT]}
