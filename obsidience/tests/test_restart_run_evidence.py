"""Restart placeholders must not overwrite finalized execution evidence."""

from __future__ import annotations

import json

import pytest

from obsidience.harness.execution import scheduler
from obsidience.harness.knowledge import index as indexer
from obsidience.harness.knowledge.vault import Note


@pytest.fixture
def recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(indexer.CONFIG, "db_path", tmp_path / "index.sqlite3")
    ledger = indexer.Index()
    task = Note(
        path="Tasks/link.md",
        title="Link",
        body="",
        mtime=100.0,
        meta={"kind": "task", "status": "running", "last_run": "interrupted-test"},
    )

    def update(note, status, extra=None):
        note.meta.update({"status": status, **(extra or {})})

    monkeypatch.setattr(scheduler, "INDEX", ledger)
    monkeypatch.setattr(scheduler, "iter_notes", lambda: [task])
    monkeypatch.setattr(scheduler, "update_status", update)
    monkeypatch.setattr(scheduler, "mutate_note_metadata", lambda note, edit: edit(note.meta))
    try:
        yield ledger, task
    finally:
        ledger.db.close()


def configure_event(task, event_triggered):
    if event_triggered:
        active = {"event": "task.create", "activation_key": "active"}
        waiting = {"event": "task.create", "activation_key": "waiting"}
        task.meta.update(
            triggers=["task.create"],
            params=active,
            event_queue=[active, waiting, waiting],
            blocked_reason="stale reason",
        )


def assert_recovery_policy(task, event_triggered):
    if event_triggered:
        assert task.meta["status"] == "failed"
        assert task.meta["params"] == {"event": "task.create", "activation_key": "active"}
        assert task.meta["event_queue"] == [
            {"event": "task.create", "activation_key": "active"},
            {"event": "task.create", "activation_key": "waiting"},
            {"event": "task.create", "activation_key": "waiting"},
        ]
        assert task.meta["blocked_reason"] == scheduler.RESTART_DISPOSITION_REASON
    else:
        assert task.meta["status"] == "failed"
        assert task.meta["blocked_reason"] == scheduler.INTERRUPTED_RUN_SUMMARY
    assert task.meta["last_run"] == "interrupted-test"
    assert scheduler.reconcile_interrupted_runs() == []


@pytest.mark.parametrize("event_triggered", [False, True])
def test_restart_preserves_every_field_of_existing_interrupted_run(recovery, event_triggered):
    ledger, task = recovery
    configure_event(task, event_triggered)
    ledger.record_run(
        id="interrupted-test", task_ref=task.ref,
        objective="Link the two specifically requested Articles",
        agent="Alexandria", started=101.25, finished=102.5,
        status="interrupted", summary="Interrupted after a returned Tool effect.",
        trace=json.dumps([{
            "tool": "vault.propose", "args": {"target": "Knowledge/one"},
            "obs": "The proposal was staged.", "must_not_replay": True,
        }]),
        runbook_ref="Runbooks/link", runbook_sha256="a" * 64,
        reasoning_effort="high", model="test-model",
    )
    before = ledger.db.execute("SELECT rowid, * FROM runs").fetchall()

    assert scheduler.reconcile_interrupted_runs() == [task.ref]

    assert ledger.db.execute("SELECT rowid, * FROM runs").fetchall() == before
    assert_recovery_policy(task, event_triggered)
    assert ledger.db.execute("SELECT rowid, * FROM runs").fetchall() == before


@pytest.mark.parametrize("event_triggered", [False, True])
def test_restart_inserts_fallback_only_when_run_is_absent(recovery, event_triggered):
    ledger, task = recovery
    configure_event(task, event_triggered)

    assert scheduler.reconcile_interrupted_runs() == [task.ref]

    rows = ledger.runs()
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "interrupted-test"
    assert row["task_ref"] == task.ref
    assert row["objective"] == task.title
    assert row["agent"] == "interpreter"
    assert row["started"] == task.mtime
    assert row["status"] == "failed"
    assert row["summary"] == scheduler.INTERRUPTED_RUN_SUMMARY
    assert ledger.db.execute("SELECT trace FROM runs").fetchone() == ("[]",)
    assert_recovery_policy(task, event_triggered)
    assert ledger.runs() == rows
