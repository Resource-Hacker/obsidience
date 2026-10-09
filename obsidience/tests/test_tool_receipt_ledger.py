"""Controller receipts survive crash boundaries without authorizing effect replay."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from obsidience.harness.capabilities.task import inspect as task_inspect
from obsidience.harness.config import CONFIG
from obsidience.harness.execution import executor, scheduler
from obsidience.harness.execution.executor import serialize_run_trace
from obsidience.harness.knowledge import index, vault


@pytest.fixture
def occurrence(tmp_path, monkeypatch, isolated_task_ledger):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    monkeypatch.setattr(CONFIG, "git_commit", False)
    vault.write_note("Tasks/ingest.md", {"kind": "task", "title": "Ingest", "status": "running",
        "last_run": "crashed", "triggers": ["source.inbox"],
        "params": {"event": "source.inbox", "activation_key": "exact-inbox", "source_id": "original"},
        "event_queue": [{"event": "source.inbox", "activation_key": "later-inbox"}],
        "schedule": "* * * * *"}, "Ingest accepted research.")
    task = vault.load_note("Tasks/ingest.md")
    return isolated_task_ledger, task


def begin(ledger, task):
    ledger.begin_tool_run(run_id="crashed", task_ref=task.ref, params=task.meta["params"], started=1.)


def call(ledger, *, tool="vault.propose", read_only=False, **changes):
    values = dict(run_id="crashed", call_id="crashed:tool:1", step=1, tool=tool,
                  signature="sha256:" + "a" * 64, started=2., read_only=read_only,
                  tool_ref="Tools/" + tool, tool_sha256="b" * 64)
    values.update(changes)
    return ledger.begin_tool_call(**values)


def finish(ledger, **changes):
    values = dict(run_id="crashed", call_id="crashed:tool:1", status="returned",
                  finished=3., duration_ms=1000., result_sha256="c" * 64, result_chars=6000)
    values.update(changes)
    ledger.finish_tool_call(**values)


def test_receipt_is_visible_to_reopened_owner_before_run_finalization(occurrence, monkeypatch):
    ledger, task = occurrence
    begin(ledger, task)
    assert call(ledger) is True
    monkeypatch.setattr(CONFIG, "db_path", Path(ledger.db_path))
    reopened = index.Index()
    try:
        assert reopened.run("crashed") is None
        assert reopened.tool_run_receipts("crashed")["calls"][0]["status"] == "started"
        finish(ledger)
        assert reopened.tool_run_receipts("crashed")["calls"][0]["result_sha256"] == "c" * 64
    finally:
        reopened.db.close()


def test_identity_and_terminal_receipts_cannot_be_rewritten(occurrence):
    ledger, task = occurrence
    begin(ledger, task)
    begin(ledger, task)
    with pytest.raises(ValueError, match="identity changed"):
        ledger.begin_tool_run(run_id="crashed", task_ref=task.ref, params={"changed": True}, started=1.)
    assert call(ledger) is True
    assert call(ledger) is False  # Caller must not dispatch an already recorded call.
    with pytest.raises(ValueError, match="identity changed"):
        call(ledger, signature="different")
    with pytest.raises(ValueError, match="exact call identity"):
        call(ledger, call_id="different-call")
    finish(ledger)
    finish(ledger)
    before = ledger.tool_run_receipts("crashed")
    with pytest.raises(ValueError, match="cannot be changed"):
        finish(ledger, status="undispatched")
    assert ledger.tool_run_receipts("crashed") == before


def test_receipts_do_not_commit_another_owner_transaction(occurrence):
    ledger, task = occurrence
    begin(ledger, task)
    ledger.db.execute("INSERT INTO conversation_state VALUES('fixture','uncommitted')")
    with pytest.raises(ValueError, match="another owner transaction"):
        call(ledger)
    assert ledger.db.in_transaction
    ledger.db.rollback()
    call(ledger)
    ledger.db.execute("INSERT INTO conversation_state VALUES('fixture','uncommitted')")
    with pytest.raises(ValueError, match="another owner transaction"):
        finish(ledger)
    assert ledger.db.in_transaction
    ledger.db.rollback()
    assert ledger.tool_run_receipts("crashed")["calls"][0]["status"] == "started"


@pytest.mark.parametrize("changes", [
    {"read_only": 1}, {"read_only": True}, {"step": True}, {"step": 0},
    {"step": 4097}, {"started": float("nan")},
    {"tool": "vault.read", "read_only": True, "tool_sha256": ""},
])
def test_invalid_or_unattested_read_classification_rejected(occurrence, changes):
    ledger, task = occurrence
    begin(ledger, task)
    with pytest.raises(ValueError):
        call(ledger, **changes)
    assert ledger.tool_run_receipts("crashed")["calls"] == []


@pytest.mark.parametrize("terminal", [None, "returned", "error", "rejected", "interrupted"])
def test_restart_never_replays_possible_or_completed_effect(occurrence, terminal):
    ledger, task = occurrence
    begin(ledger, task)
    call(ledger)
    if terminal:
        finish(ledger, status=terminal)
    article_before = (CONFIG.vault_dir / task.path).read_bytes()
    assert scheduler.reconcile_interrupted_runs() == [task.ref]
    current = vault.load_note(task.path)
    assert current.meta["status"] == "failed"
    assert current.meta["blocked_reason"] == scheduler.RESTART_DISPOSITION_REASON
    assert current.meta["params"] == task.meta["params"]
    assert current.meta["event_queue"] == task.meta["event_queue"]
    assert (CONFIG.vault_dir / task.path).read_bytes() == article_before
    assert ledger.run("crashed")["status"] == "failed"
    assert scheduler._run_needs_disposition(ledger.run("crashed"))
    assert scheduler.reconcile_interrupted_runs() == []


class _ProcessCrash(BaseException):
    """Leave committed state intact without ordinary exception finalization."""


@pytest.mark.parametrize("kind", ["no_tool", "read_started", "read_returned", "undispatched"])
def test_restart_requeues_only_covered_no_effect_occurrence_preserving_fifo(occurrence, kind):
    ledger, task = occurrence
    begin(ledger, task)
    if kind.startswith("read"):
        call(ledger, tool="vault.read", read_only=True)
        if kind == "read_returned":
            finish(ledger)
    elif kind == "undispatched":
        call(ledger)
        finish(ledger, status="undispatched")
    assert scheduler.reconcile_interrupted_runs() == [task.ref]
    current = vault.load_note(task.path)
    assert current.meta["status"] == "pending"
    assert current.meta["params"] == task.meta["params"]
    assert current.meta["event_queue"] == task.meta["event_queue"]
    assert ledger.run("crashed")["status"] == "failed"


@pytest.mark.parametrize("obstacle", ["no_coverage", "params", "review", "malformed_review", "decision"])
def test_missing_coverage_changed_inputs_or_owner_review_blocks_restart(occurrence, obstacle):
    ledger, task = occurrence
    if obstacle != "no_coverage":
        begin(ledger, task)
    if obstacle == "params":
        vault.mutate_note_metadata(task, lambda meta: meta["params"].update(source_id="changed"))
    elif obstacle in {"review", "malformed_review"}:
        CONFIG.staging_dir.mkdir(parents=True)
        (CONFIG.staging_dir / "review.md").write_text(
            "---\nrun_id: [bad\n---\nPending\n" if obstacle == "malformed_review"
            else "---\nrun_id: crashed\n---\nPending\n")
    elif obstacle == "decision":
        ledger.db.execute("INSERT INTO review_decisions VALUES(?,?,?,?,?,?)",
                          ("proposal", "crashed", task.ref, "Knowledge/one", "approved", 2.))
        ledger.db.commit()
    scheduler.reconcile_interrupted_runs()
    assert vault.load_note(task.path).meta["status"] == "failed"


def test_public_trace_cannot_supply_missing_dispatch_coverage(occurrence):
    ledger, task = occurrence
    ledger.append_trace({"id": "pretend", "run_id": "crashed", "payload": {"kind": "tool", "status": "undispatched"}})
    scheduler.reconcile_interrupted_runs()
    assert vault.load_note(task.path).meta["status"] == "failed"


def test_inspection_exposes_omitted_entries_and_existing_field_clipping(occurrence):
    ledger, task = occurrence
    trace = [{"activation_packet": [task.ref]}] + [
        {"tool": "vault.read", "args": {str(i): "a" * 500 for i in range(24)}, "obs": "r" * 600}
        for _ in range(20)
    ] + [{"terminal": "completed"}]
    ledger.record_run(id="crashed", task_ref=task.ref, agent="fixture", started=1., finished=2.,
                      status="completed", summary="Done", trace=serialize_run_trace(trace))
    row = json.loads(task_inspect.execute({"task": task.ref, "run_id": "crashed"}, {}))["runs"][0]
    assert row["tool_count"] < 20
    assert row["tool_count_complete"] is False
    assert row["evidence_truncated"] is True
    assert row["tool_evidence"][0]["truncated"] is True


def test_exact_receipt_count_and_status_survive_clipped_inspection(occurrence):
    ledger, task = occurrence
    begin(ledger, task)
    call(ledger, tool="vault.read", read_only=True)
    finish(ledger)
    ledger.record_run(id="crashed", task_ref=task.ref, agent="fixture", started=1., finished=3.,
                      status="interrupted", summary="Stopped", trace="[]")
    row = json.loads(task_inspect.execute({"task": task.ref, "run_id": "crashed"}, {}))["runs"][0]
    assert row["tool_count"] == 1 and row["tool_count_complete"] is True
    assert row["evidence_truncated"] is True
    assert row["tool_receipts"][0]["call_id"] == "crashed:tool:1"
    assert row["tool_receipts"][0]["status"] == "returned"
    assert row["tool_receipts"][0]["result_sha256"] == "c" * 64


def test_single_truncated_result_is_not_presented_as_complete(occurrence):
    ledger, task = occurrence
    trace = [{"tool": "vault.read", "args": {}, "obs": "r" * 600}]
    ledger.record_run(id="crashed", task_ref=task.ref, agent="fixture", started=1., finished=3.,
                      status="completed", summary="Done", trace=serialize_run_trace(trace))
    row = json.loads(task_inspect.execute({"task": task.ref, "run_id": "crashed"}, {}))["runs"][0]
    assert row["tool_evidence"][0]["truncated"] is True
    assert row["evidence_truncated"] is True


def test_legacy_empty_restart_trace_does_not_prove_zero_tools(occurrence):
    ledger, task = occurrence
    ledger.record_run(id="crashed", task_ref=task.ref, agent="fixture", started=1., finished=3.,
                      status="failed", summary=scheduler.INTERRUPTED_RUN_SUMMARY, trace="[]")
    row = json.loads(task_inspect.execute({"task": task.ref, "run_id": "crashed"}, {}))["runs"][0]
    assert row["tool_count"] == 0
    assert row["tool_count_complete"] is False
    assert row["evidence_truncated"] is True
