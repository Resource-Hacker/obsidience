"""Historical diagnostics stay bounded, revision-scoped and read-only."""

import json
import sqlite3

import pytest

from obsidience.harness.execution.ledger import run_history_findings

NOW = 2_000_000.0
REVISION = "a" * 64


def record(ledger, identifier, status="failed", **changes):
    values = dict(id=identifier, task_ref="Tasks/example", agent="fixture", started=NOW - 10,
                  finished=NOW - 1, status=status, summary="PRIVATE SUMMARY", trace="PRIVATE TRACE",
                  objective="PRIVATE OBJECTIVE", runbook_ref="Runbooks/example",
                  runbook_sha256=REVISION)
    values.update(changes)
    ledger.record_run(**values)


def receipt(ledger, identifier, status="error", *, task_ref="Tasks/example", revision=REVISION,
            tool="vault.read", started=NOW - 10):
    ledger.begin_tool_run(run_id=identifier, task_ref=task_ref, params={}, started=started)
    ledger.begin_tool_call(run_id=identifier, call_id=identifier + ":1", step=1, tool=tool,
                           signature="private-argument-signature", started=started,
                           tool_ref="Tools/" + tool, tool_sha256=revision)
    if status != "started":
        ledger.finish_tool_call(run_id=identifier, call_id=identifier + ":1", status=status,
                                finished=started + 1, duration_ms=1000.)


def test_empty_and_sparse_history_do_not_manufacture_a_pattern(isolated_task_ledger):
    ledger = isolated_task_ledger
    empty = run_history_findings(ledger, now=NOW)
    assert empty["findings"] == [] and empty["scan_complete"]
    for number in range(2):
        record(ledger, f"new-{number}")
    for number in range(10):
        record(ledger, f"old-{number}", started=NOW - 8 * 86_400, finished=NOW - 8 * 86_400 + 1)
    report = run_history_findings(ledger, now=NOW)
    assert report["sampled_runs"] == 2
    assert report["counts"]["failed"] == 2
    assert report["findings"] == []
    assert report["window_start"] == NOW - 7 * 86_400
    assert report["window_basis"] == "run_started"


def test_revision_groups_never_merge_or_claim_a_current_regression(isolated_task_ledger):
    ledger = isolated_task_ledger
    for number in range(3):
        record(ledger, f"older-{number}", started=NOW - 100, finished=NOW - 90)
        record(ledger, f"newer-{number}", "completed", runbook_sha256="b" * 64)
    for number in range(2):
        record(ledger, f"other-task-{number}", task_ref="Tasks/different")
        record(ledger, f"other-procedure-{number}", runbook_ref="Runbooks/different")
    report = run_history_findings(ledger, now=NOW)
    assert report["revision_groups"] == 4
    assert len(report["findings"]) == 1
    finding = report["findings"][0]
    assert finding["runbook_sha256"] == REVISION
    assert finding["scope"] == "recorded_revision"
    assert finding["task_ref"] == "Tasks/example"
    assert finding["eligible_runs"] == 3 and finding["failure_ratio"] == 1
    assert "Historical evidence, not a current fault." in finding["summary"]
    assert set(finding["evidence_run_ids"]) == {"older-0", "older-1", "older-2"}


def test_cancellation_interruption_and_review_are_distinct_nonfailures(isolated_task_ledger):
    ledger = isolated_task_ledger
    record(ledger, "failed")
    record(ledger, "blocked", "blocked")
    for status in ("cancelled", "interrupted", "review"):
        for number in range(5):
            record(ledger, f"{status}-{number}", status)
    report = run_history_findings(ledger, now=NOW)
    assert report["findings"] == []  # Only two eligible attempts, despite 15 other outcomes.
    record(ledger, "completed", "completed", started=NOW - 4, finished=NOW - 1)
    finding = run_history_findings(ledger, now=NOW)["findings"][0]
    assert finding["counts"] == {"completed": 1, "failed": 1, "blocked": 1,
                                  "cancelled": 5, "interrupted": 5, "review": 5}
    assert finding["eligible_runs"] == 3 and finding["failure_count"] == 2
    assert finding["failure_ratio"] == 0.667
    assert set(finding["evidence_run_ids"]) == {"failed", "blocked"}
    assert finding["duration_seconds"] == {"samples": 3, "median": 9.0, "max": 9.0}


def test_successes_below_the_failure_ratio_keep_history_quiet(isolated_task_ledger):
    ledger = isolated_task_ledger
    for number, status in enumerate(["failed"] * 2 + ["completed"] * 3):
        record(ledger, str(number), status)
    assert run_history_findings(ledger, now=NOW)["findings"] == []


def test_unattested_and_invalid_rows_are_explicitly_excluded(isolated_task_ledger):
    ledger = isolated_task_ledger
    for number, changes in enumerate([
        {"runbook_sha256": ""}, {"runbook_sha256": "unattested"}, {"runbook_ref": ""},
        {"id": "x" * 129}, {"task_ref": "x" * 513},
        {"finished": NOW + 1}, {"finished": NOW - 11}, {"finished": None},
        {"status": "running"}, {"status": "unknown"},
    ]):
        record(ledger, f"invalid-{number}", **changes)
    report = run_history_findings(ledger, now=NOW)
    assert report["sampled_runs"] == 10
    assert report["excluded"] == {"unattested_revision": 3, "invalid_identity": 2,
                                  "invalid_time": 3, "other_status": 2}
    assert report["findings"] == [] and report["revision_groups"] == 0


def test_window_limit_and_evidence_clipping_are_explicit(isolated_task_ledger):
    ledger = isolated_task_ledger
    for number in range(215):
        record(ledger, f"run-{number:03d}")
    report = run_history_findings(ledger, now=NOW)
    assert report["sampled_runs"] == report["run_limit"] == 200
    assert report["scan_complete"] is False
    finding = report["findings"][0]
    assert finding["failure_count"] == 200
    assert finding["evidence_run_ids"] == ["run-214", "run-213", "run-212"]
    assert finding["evidence_omitted"] == 197


def test_finding_limit_preserves_larger_patterns_and_reports_omissions(isolated_task_ledger):
    ledger = isolated_task_ledger
    for group in range(10):
        for number in range(3):
            record(ledger, f"{group}-{number}", task_ref=f"Tasks/group-{group}")
    record(ledger, "larger", task_ref="Tasks/group-9")
    report = run_history_findings(ledger, now=NOW)
    assert len(report["findings"]) == report["findings_limit"] == 8
    assert report["findings_omitted"] == 2 and report["scan_complete"]
    assert report["findings"][0]["task_ref"] == "Tasks/group-9"
    assert len(json.dumps(report)) < 12_000


def test_tool_receipts_group_exact_tool_and_task_revisions(isolated_task_ledger):
    ledger = isolated_task_ledger
    for number in range(3):
        receipt(ledger, f"older-{number}")
        receipt(ledger, f"newer-{number}", "returned", revision="b" * 64)
    for number in range(2):
        receipt(ledger, f"other-task-{number}", task_ref="Tasks/different")
        receipt(ledger, f"other-tool-{number}", tool="source.read")
    tools = run_history_findings(ledger, now=NOW)["tools"]
    assert tools["revision_groups"] == 4 and tools["sampled_calls"] == 10
    assert len(tools["findings"]) == 1
    finding = tools["findings"][0]
    assert finding["tool_ref"] == "Tools/vault.read" and finding["tool_sha256"] == REVISION
    assert finding["scope"] == "recorded_tool_revision"
    assert finding["error_count"] == 3 and finding["error_ratio"] == 1
    assert finding["duration_ms"] == {"samples": 3, "median": 1000., "max": 1000.}
    assert finding["evidence_calls"] == [
        {"run_id": f"older-{number}", "call_id": f"older-{number}:1"} for number in range(3)]
    assert "does not establish semantic success or root cause" in finding["summary"]


def test_uncertain_and_undispatched_tools_are_not_counted_as_errors(isolated_task_ledger):
    ledger = isolated_task_ledger
    for status in ("started", "interrupted", "undispatched"):
        for number in range(4):
            receipt(ledger, f"{status}-{number}", status)
    receipt(ledger, "error")
    receipt(ledger, "rejected", "rejected")
    assert run_history_findings(ledger, now=NOW)["tools"]["findings"] == []
    receipt(ledger, "returned", "returned")
    finding = run_history_findings(ledger, now=NOW)["tools"]["findings"][0]
    assert finding["counts"] == {"started": 4, "interrupted": 4, "undispatched": 4,
                                 "returned": 1, "error": 1, "rejected": 1}
    assert finding["eligible_calls"] == 3 and finding["error_count"] == 2
    assert finding["error_ratio"] == 0.667


def test_tool_window_and_evidence_are_bounded(isolated_task_ledger):
    ledger = isolated_task_ledger
    receipt(ledger, "old", started=NOW - 8 * 86_400)
    receipt(ledger, "unattested", revision="")
    first = run_history_findings(ledger, now=NOW)["tools"]
    assert first["sampled_calls"] == 1 and first["excluded"]["unattested_revision"] == 1
    for number in range(405):
        receipt(ledger, f"call-{number:03d}")
    tools = run_history_findings(ledger, now=NOW)["tools"]
    assert tools["sampled_calls"] == tools["call_limit"] == 400
    assert tools["scan_complete"] is False
    finding = tools["findings"][0]
    assert finding["error_count"] == 400
    assert len(finding["evidence_calls"]) == 3 and finding["evidence_omitted"] == 397


def test_tool_findings_omissions_are_explicit(isolated_task_ledger):
    ledger = isolated_task_ledger
    for group in range(10):
        for number in range(3):
            receipt(ledger, f"{group}-{number}", task_ref=f"Tasks/group-{group}")
    tools = run_history_findings(ledger, now=NOW)["tools"]
    assert len(tools["findings"]) == tools["findings_limit"] == 8
    assert tools["findings_omitted"] == 2
    assert len(json.dumps(tools)) < 15_000


def test_history_reads_only_metadata_and_cannot_write(isolated_task_ledger):
    ledger = isolated_task_ledger
    for number in range(3):
        record(ledger, str(number))
        receipt(ledger, str(number))
    before = ledger.db.total_changes
    ledger.db.execute("PRAGMA query_only=ON")

    def authorize(action, table, column, _database, _trigger):
        if action == sqlite3.SQLITE_READ and table == "runs" and column in {"objective", "summary", "trace"}:
            return sqlite3.SQLITE_DENY
        if action == sqlite3.SQLITE_READ and table == "tool_receipts" and column == "signature":
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    ledger.db.set_authorizer(authorize)
    try:
        report = run_history_findings(ledger, now=NOW)
        assert len(report["findings"]) == 1
        assert len(report["tools"]["findings"]) == 1
        assert "PRIVATE" not in json.dumps(report)
        assert ledger.db.total_changes == before
    finally:
        ledger.db.set_authorizer(None)
        ledger.db.execute("PRAGMA query_only=OFF")


@pytest.mark.parametrize("changes", [{"limit": 0}, {"limit": 201}, {"limit": True},
                                     {"since": -1}, {"until": float("inf")}, {"since": NOW + 1}])
def test_sample_rejects_unbounded_queries(isolated_task_ledger, changes):
    bounds = {"since": NOW - 100, "until": NOW, "limit": 200, **changes}
    with pytest.raises(ValueError, match="sample bounds"):
        isolated_task_ledger.run_history_sample(**bounds)


@pytest.mark.parametrize("limit", [0, 401, True])
def test_tool_sample_rejects_unbounded_queries(isolated_task_ledger, limit):
    with pytest.raises(ValueError, match="sample bounds"):
        isolated_task_ledger.tool_history_sample(since=NOW - 100, until=NOW, limit=limit)


@pytest.mark.parametrize("now", [True, -1, float("nan"), float("inf"), "today"])
def test_observation_time_must_be_finite_and_attested(isolated_task_ledger, now):
    with pytest.raises(ValueError, match="observation time"):
        run_history_findings(isolated_task_ledger, now=now)
