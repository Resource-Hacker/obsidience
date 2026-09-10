"""Completed Check findings use the existing durable Task occurrence queue."""

from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from obsidience.harness.config import CONFIG
from obsidience.harness.execution import assignments, executor, scheduler
from obsidience.harness.knowledge import index, vault
from obsidience.tests.test_execution_cancellation import execution  # noqa: F401


@pytest.fixture
def health_ledger(tmp_path, monkeypatch, isolated_task_ledger):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    monkeypatch.setattr(scheduler, "_running", set())
    monkeypatch.setattr(scheduler, "_last_fired", {})
    monkeypatch.setattr(scheduler, "_resource_error", lambda _task: None)
    monkeypatch.setattr(assignments, "ensure_task_runbook", lambda *_args: {"status": "ready"})
    monkeypatch.setattr(scheduler.action_trace, "emit", lambda *_args: None)
    monkeypatch.setattr(scheduler, "launch", lambda *_args, **_kwargs: pytest.fail("Reconciliation must only admit an occurrence"))
    vault.write_note("Tasks/check.md", {"kind": "task", "title": "Check", "status": "completed"}, "Inspect Harness health.")
    vault.write_note("Tasks/repair.md", {"kind": "task", "title": "Repair", "status": "completed",
                    "triggers": ["harness.degraded"], "enabled": True}, "Repair only attested eligible work.")
    return isolated_task_ledger


def record_check(ledger, *, run_id="check-one", status="completed", task_ref="Tasks/check", trace=None):
    ledger.record_run(id=run_id, task_ref=task_ref, agent="Heimdall", started=1., finished=2., status=status,
                     summary="Degraded prose alone does not authorize Repair.",
                     trace=json.dumps([{"activation_packet": ["Tasks/check"],
                                        "harness_health": {"version": 1, "status": "degraded"}}]) if trace is None else trace)
    check = vault.load_note("Tasks/check.md")
    vault.mutate_note_metadata(check, lambda meta: meta.update(last_run=run_id, status=status))
    return ledger.run(run_id)


def receipt_id(run_id="check-one"):
    return "health-repair-" + hashlib.sha256(run_id.encode()).hexdigest()[:32]


def test_completed_degraded_check_admits_exact_repair_once(health_ledger):
    before = record_check(health_ledger)
    authored = (CONFIG.vault_dir / "Tasks/repair.md").read_bytes()
    result = scheduler.reconcile_check_health()
    assert result["task"] == "Tasks/repair" and result["state"] == "started"
    repair = vault.load_note("Tasks/repair.md")
    assert repair.meta["status"] == "pending"
    assert repair.meta["params"] == {"event": "harness.degraded", "check_run_id": "check-one",
                                     "activation_key": receipt_id(), "target_task": "Tasks/repair"}
    assert repair.meta.get("event_queue", []) == []
    marker = health_ledger.run(receipt_id())
    assert marker["status"] == "dispatched" and marker["task_ref"] == "Tasks/repair"
    assert health_ledger.run("check-one") == before
    assert (CONFIG.vault_dir / "Tasks/repair.md").read_bytes() == authored
    assert scheduler.reconcile_check_health() is None
    assert len(health_ledger.runs()) == 2


@pytest.mark.parametrize("status,task_ref,trace", [
    ("failed", "Tasks/check", None),
    ("blocked", "Tasks/check", None),
    ("review", "Tasks/check", None),
    ("interrupted", "Tasks/check", None),
    ("completed", "Tasks/other", None),
    ("completed", "Tasks/check", "not json"),
    ("completed", "Tasks/check", "null"),
    ("completed", "Tasks/check", "{}"),
    ("completed", "Tasks/check", "[]"),
    ("completed", "Tasks/check", '[{"harness_health":{"version":1,"status":"healthy"}}]'),
    ("completed", "Tasks/check", '[{"tool":"harness.status","obs":"degraded"}]'),
    ("completed", "Tasks/check", '[{"activation_packet":["Tasks/check"]},{"harness_health":{"version":1,"status":"degraded"}}]'),
    ("completed", "Tasks/check", '[{"harness_health":{"version":2,"status":"degraded"}}]'),
    ("completed", "Tasks/check", '[{"harness_health":{"version":true,"status":"degraded"}}]'),
])
def test_only_completed_exact_check_with_controller_signal_activates(health_ledger, status, task_ref, trace):
    record_check(health_ledger, status=status, task_ref=task_ref, trace=trace)
    before = health_ledger.task_runtime("Tasks/repair")
    assert scheduler.reconcile_check_health() is None
    assert health_ledger.task_runtime("Tasks/repair") == before
    assert health_ledger.run(receipt_id()) is None


@pytest.mark.parametrize("disabled", [False, "false", "off", 0])
def test_disabled_repair_is_skipped_without_losing_check(health_ledger, disabled):
    before = record_check(health_ledger)
    note = vault.load_note("Tasks/repair.md")
    vault.mutate_note_metadata(note, lambda meta: meta.update(enabled=disabled))
    assert scheduler.reconcile_check_health() is None
    assert health_ledger.run("check-one") == before
    assert health_ledger.run(receipt_id()) is None


@pytest.mark.parametrize("unavailable", ["missing", "wrong_kind", "wrong_trigger", "deprecated"])
def test_unavailable_repair_is_skipped(health_ledger, unavailable):
    record_check(health_ledger)
    path = CONFIG.vault_dir / "Tasks/repair.md"
    if unavailable == "missing":
        path.unlink()
    else:
        note = vault.load_note("Tasks/repair.md")
        values = {"wrong_kind": {"kind": "knowledge"}, "wrong_trigger": {"triggers": ["other.event"]},
                  "deprecated": {"article_status": "deprecated"}}[unavailable]
        vault.mutate_note_metadata(note, lambda meta: meta.update(values))
    assert scheduler.reconcile_check_health() is None
    assert health_ledger.run(receipt_id()) is None


def test_missing_check_or_run_is_not_an_activation(health_ledger):
    assert scheduler.reconcile_check_health() is None
    (CONFIG.vault_dir / "Tasks/check.md").unlink()
    assert scheduler.reconcile_check_health() is None
    assert health_ledger.runs() == []


@pytest.mark.parametrize("active_status", ["running", "failed", "blocked"])
def test_new_checks_queue_behind_existing_repair_fifo(health_ledger, active_status):
    repair = vault.load_note("Tasks/repair.md")
    active = {"event": "harness.degraded", "activation_key": "earlier-active", "check_run_id": "earlier"}
    waiting = {"event": "harness.degraded", "activation_key": "earlier-waiting", "check_run_id": "waiting"}
    vault.mutate_note_metadata(repair, lambda meta: meta.update(status=active_status, params=active, event_queue=[waiting]))
    record_check(health_ledger)
    first = scheduler.reconcile_check_health()
    assert first["state"] == "queued" and first["position"] == 2
    record_check(health_ledger, run_id="check-two")
    second = scheduler.reconcile_check_health()
    assert second["state"] == "queued" and second["position"] == 3
    current = vault.load_note(repair.path)
    assert current.meta["params"] == active
    assert current.meta["event_queue"][0] == waiting
    assert [row["check_run_id"] for row in current.meta["event_queue"]] == ["waiting", "check-one", "check-two"]
    before = health_ledger.task_runtime(repair.ref)
    assert scheduler.reconcile_check_health() is None
    assert health_ledger.task_runtime(repair.ref) == before


def test_repair_review_is_preserved_and_receipt_waits_for_admission(health_ledger):
    record_check(health_ledger)
    repair = vault.load_note("Tasks/repair.md")
    vault.mutate_note_metadata(repair, lambda meta: meta.update(status="review", params={"activation_key": "owner-review"}))
    before = health_ledger.task_runtime(repair.ref)
    assert scheduler.reconcile_check_health() is None
    assert health_ledger.task_runtime(repair.ref) == before
    assert health_ledger.run(receipt_id()) is None
    vault.update_status(vault.load_note(repair.path), "completed")
    assert scheduler.reconcile_check_health()["state"] == "started"
    assert health_ledger.run(receipt_id())["status"] == "dispatched"


def test_latest_healthy_check_does_not_reactivate_older_degraded_finding(health_ledger):
    record_check(health_ledger)
    record_check(health_ledger, run_id="latest-healthy", trace='[{"harness_health":{"version":1,"status":"healthy"}}]')
    assert scheduler.reconcile_check_health() is None
    assert health_ledger.run(receipt_id()) is None
    assert health_ledger.run(receipt_id("latest-healthy")) is None


def test_restart_after_queue_admission_before_receipt_reattaches_once(health_ledger, monkeypatch):
    record_check(health_ledger)
    original = health_ledger.record_run

    def crash_before_receipt(**kwargs):
        if kwargs["id"] == receipt_id():
            raise RuntimeError("simulated process loss after queue admission")
        return original(**kwargs)

    monkeypatch.setattr(health_ledger, "record_run", crash_before_receipt)
    with pytest.raises(RuntimeError, match="simulated process loss"):
        scheduler.reconcile_check_health()
    params = health_ledger.task_runtime("Tasks/repair")["params"]
    reopened = index.Index()
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(index, "INDEX", reopened)
            patch.setattr(scheduler, "INDEX", reopened)
            patch.setattr(scheduler, "_running", set())
            result = scheduler.reconcile_check_health()
            assert result["state"] == "started"
            assert reopened.task_runtime("Tasks/repair")["params"] == params
            assert reopened.task_runtime("Tasks/repair").get("event_queue", []) == []
            assert reopened.run(receipt_id())["status"] == "dispatched"
            assert scheduler.reconcile_check_health() is None
            assert len(reopened.runs()) == 2
    finally:
        reopened.db.close()


@pytest.mark.parametrize("task_ref,snapshot,expected", [
    ("Tasks/check", {"status": "degraded", "private_detail": "not a signal"}, {"version": 1, "status": "degraded"}),
    ("Tasks/check", {"status": "healthy"}, {"version": 1, "status": "healthy"}),
    ("Tasks/check", {"status": "unknown"}, None),
    ("Tasks/check", None, None),
    ("Tasks/query", {"status": "degraded"}, None),
])
def test_executor_handoff_uses_only_controller_snapshot(execution, health_ledger, monkeypatch, task_ref, snapshot, expected):
    execution.task.ref = task_ref

    async def session(_task, _model, _messages, _allowed, context, *_args, **_kwargs):
        context["_harness_snapshot"] = snapshot
        return [{"tool": "harness.status", "obs": '{"status":"degraded"}'}], "completed", "Degraded prose."

    monkeypatch.setattr(executor, "_execute_session", session)
    asyncio.run(execution.run())
    trace = json.loads(execution.records[0]["trace"])
    assert trace[0].get("harness_health") == expected
    assert "private_detail" not in trace[0].get("harness_health", {})


def test_executor_signal_survives_bounded_trace_retention(execution, health_ledger, monkeypatch):
    execution.task.ref = "Tasks/check"

    async def session(_task, _model, _messages, _allowed, context, *_args, **_kwargs):
        context["_harness_snapshot"] = {"status": "degraded"}
        return [{"tool": "fixture.read", "obs": "x" * 1000} for _ in range(200)], "completed", "Checked."

    monkeypatch.setattr(executor, "_execute_session", session)
    monkeypatch.setattr(executor, "MAX_RUN_TRACE_CHARS", 4096)
    asyncio.run(execution.run())
    trace = json.loads(execution.records[0]["trace"])
    assert len(execution.records[0]["trace"]) <= 4096
    assert trace[0]["harness_health"] == {"version": 1, "status": "degraded"}
    assert any("trace_truncated" in row for row in trace)
