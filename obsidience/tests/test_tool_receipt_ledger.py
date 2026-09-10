"""Controller receipts survive crash boundaries without authorizing effect replay."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

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


@pytest.mark.parametrize("boundary,effect_count,receipt_status", [
    ("after_intent", 0, "started"),
    ("after_effect_before_receipt", 1, "started"),
    ("after_receipt_before_finalization", 1, "returned"),
])
def test_executor_crash_boundaries_preserve_evidence_without_redispatch(
    occurrence, monkeypatch, boundary, effect_count, receipt_status,
):
    ledger, task = occurrence
    begin(ledger, task)
    ledger.db.execute("CREATE TABLE fixture_effects(run_id TEXT, arguments TEXT)")
    ledger.db.commit()
    article_before = (CONFIG.vault_dir / task.path).read_bytes()
    arguments = {"target": "Knowledge/fixture", "content": "One intended effect."}
    result = {"effect": "committed", "target": arguments["target"]}
    encoded_result = json.dumps(result, sort_keys=True).encode()
    model = SimpleNamespace(id="inert", capabilities=("text", "tools"))
    requests = []
    calls = []

    @asynccontextmanager
    async def lease(_model):
        yield model

    async def chat(*_args, **_kwargs):
        requests.append("provider")
        assert len(requests) == 1, "A crashed Tool must never request another decision."
        return SimpleNamespace(
            content=json.dumps({"tool": "vault.propose", "args": arguments}),
            prompt_tokens=100,
        )

    def capability(name, args, context):
        assert name == "vault.propose" and args == arguments
        calls.append(name)
        # This independent owner commits its effect before returning. Reopening
        # the ledger below must retain it even when its Tool result never lands.
        with sqlite3.connect(ledger.db_path) as effect_owner:
            effect_owner.execute("INSERT INTO fixture_effects VALUES(?,?)", (
                context["run_id"], json.dumps(args, sort_keys=True),
            ))
        return result

    original_begin = ledger.begin_tool_call
    original_finish = ledger.finish_tool_call

    def begin_with_crash(**values):
        created = original_begin(**values)
        if boundary == "after_intent":
            raise _ProcessCrash(boundary)
        return created

    def finish_with_crash(**values):
        if boundary == "after_effect_before_receipt":
            raise _ProcessCrash(boundary)
        original_finish(**values)
        if boundary == "after_receipt_before_finalization":
            raise _ProcessCrash(boundary)

    monkeypatch.setattr(ledger, "begin_tool_call", begin_with_crash)
    monkeypatch.setattr(ledger, "finish_tool_call", finish_with_crash)
    monkeypatch.setattr(executor.model_runtime, "configured_spec", lambda _id: model)
    monkeypatch.setattr(executor.model_runtime, "lease", lease)
    monkeypatch.setattr(executor.llm, "chat", chat)
    monkeypatch.setattr(executor, "execute_capability", capability)
    monkeypatch.setattr(executor.action_trace, "emit", lambda *_a, **_k: None)
    monkeypatch.setattr(executor.action_trace, "latency", lambda *_a, **_k: None)
    context = {
        "task": task.ref, "run_id": "crashed", "params": task.meta["params"],
        "_receipt_covered": True,
        "_tool_receipt_articles": {"vault.propose": ("Tools/vault.propose", "b" * 64)},
    }
    with pytest.raises(_ProcessCrash, match=boundary):
        asyncio.run(executor._execute_session(
            task, model, [{"role": "system", "content": "Inert test packet"}],
            ["vault.propose"], context, "fixture", "none",
        ))
    assert requests == ["provider"]
    assert calls == ["vault.propose"] * effect_count
    assert ledger.run("crashed") is None
    receipts_before = ledger.tool_run_receipts("crashed")
    assert len(receipts_before["calls"]) == 1
    receipt = receipts_before["calls"][0]
    assert receipt["call_id"] == "crashed:1" and receipt["step"] == 1
    assert receipt["signature"] == "vault.propose:sha256:" + hashlib.sha256(
        json.dumps(arguments, sort_keys=True).encode(),
    ).hexdigest()
    assert receipt["read_only"] is False
    assert receipt["tool_ref"] == "Tools/vault.propose"
    assert receipt["tool_sha256"] == "b" * 64
    assert receipt["status"] == receipt_status
    if receipt_status == "returned":
        assert receipt["result_sha256"] == hashlib.sha256(encoded_result).hexdigest()
        assert receipt["result_chars"] == len(encoded_result)
    else:
        assert receipt["finished"] is None and not receipt["result_sha256"]

    ledger.db.close()
    reopened = index.Index()
    try:
        monkeypatch.setattr(index, "INDEX", reopened)
        monkeypatch.setattr(scheduler, "INDEX", reopened)
        assert reopened.tool_run_receipts("crashed") == receipts_before
        effects_before = reopened.db.execute("SELECT * FROM fixture_effects").fetchall()
        assert effects_before == [("crashed", json.dumps(arguments, sort_keys=True))] * effect_count
        assert scheduler.reconcile_interrupted_runs() == [task.ref]
        current = vault.load_note(task.path)
        assert current.meta["status"] == "failed"
        assert current.meta["blocked_reason"] == scheduler.RESTART_DISPOSITION_REASON
        assert current.meta["params"] == task.meta["params"]
        assert current.meta["event_queue"] == task.meta["event_queue"]
        assert (CONFIG.vault_dir / task.path).read_bytes() == article_before
        # A dangling effectful intent is uncertain even when this test knows
        # its dispatch never happened. Restart may not invent that knowledge.
        assert scheduler.retry_blocked_reason(current) == "A Tool may have committed effects."
        with pytest.raises(ValueError, match="may have committed effects"):
            scheduler.retry_failed_occurrence(current, "crashed")
        monkeypatch.setattr(scheduler, "_realtime_allows", lambda *_a: True)
        monkeypatch.setitem(scheduler._last_fired, task.ref, 0.)  # Deliberately overdue cron.
        assert scheduler.due_tasks() == []
        final_run = reopened.run("crashed")
        assert final_run["status"] == "failed"
        assert final_run["task_ref"] == task.ref
        assert scheduler.reconcile_interrupted_runs() == []
        assert reopened.run("crashed") == final_run
        assert reopened.tool_run_receipts("crashed") == receipts_before
        assert reopened.db.execute("SELECT * FROM fixture_effects").fetchall() == effects_before
        assert calls == ["vault.propose"] * effect_count
    finally:
        reopened.db.close()


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
