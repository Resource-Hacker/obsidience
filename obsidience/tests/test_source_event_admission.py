from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import pytest

from obsidience.harness import config
from obsidience.harness.execution import assignments, scheduler
from obsidience.harness.knowledge import index, source, vault


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config.CONFIG, "db_path", tmp_path / "index.sqlite3")
    monkeypatch.setattr(config.CONFIG, "vault_dir", tmp_path / "vault")
    current = index.Index()
    monkeypatch.setattr(index, "INDEX", current)
    monkeypatch.setattr(scheduler, "INDEX", current)
    monkeypatch.setattr(scheduler, "_resource_error", lambda _task, **_snapshot: None)
    monkeypatch.setattr(assignments, "ensure_task_runbook", lambda *_args: {"status": "ready"})
    for event, ref in source.SOURCE_EVENT_TASKS.items():
        vault.write_note(ref + ".md", {
            "kind": "task", "title": ref.rsplit("/", 1)[-1],
            "triggers": [event], "status": "completed",
        }, "Process the bound immutable Source.")
    yield current
    current.db.close()


def _capture(label="one"):
    return source.ingest_source(
        source_type="document", source_ref=f"{label}.txt", media_type="text/plain",
        captured_at="2026-09-09T12:00:00Z", content=f"Evidence {label}.",
    )


def _finish_and_clear(ref):
    task = vault.load_note(ref + ".md")

    def finish(state):
        state["status"] = "completed"
        state.pop("params", None)
        state.pop("event_queue", None)

    vault.mutate_note_metadata(task, finish)


def test_failed_source_receipt_rolls_back_fifo_and_replay_restores_file(ledger, monkeypatch):
    task_ref = source.SOURCE_EVENT_TASKS["source.added"]
    task = vault.load_note(task_ref + ".md")
    authored = (config.CONFIG.vault_dir / task.path).read_bytes()
    original_state = ledger.task_runtime(task_ref)
    ledger.db.execute("""
        CREATE TEMP TRIGGER fail_source_receipt
        BEFORE UPDATE OF event_dispatched_at ON source_evidence
        BEGIN SELECT RAISE(ABORT, 'receipt write interrupted'); END
    """)
    with pytest.raises(sqlite3.IntegrityError, match="receipt write interrupted"):
        _capture()
    pending = ledger.pending_source_events()
    assert len(pending) == 1
    row = pending[0]
    assert row["event_dispatched_at"] is None
    assert ledger.task_runtime(task_ref) == original_state
    assert (config.CONFIG.vault_dir / task.path).read_bytes() == authored
    evidence = config.CONFIG.source_dir / row["path"]
    assert evidence.read_bytes() == row["material"]
    evidence.unlink()
    ledger.db.execute("DROP TRIGGER fail_source_receipt")

    # A fresh connection reproduces process restart; raw bytes remain the same.
    restarted = index.Index()
    try:
        monkeypatch.setattr(index, "INDEX", restarted)
        monkeypatch.setattr(scheduler, "INDEX", restarted)
        assert source.dispatch_pending_source_events() == {
            "dispatched": [f"source://{row['id']}"], "issues": [],
        }
        assert evidence.read_bytes() == row["material"]
        assert restarted.source(row["id"])["event_dispatched_at"] is not None
        state = restarted.task_runtime(task_ref)
        assert state["params"]["source_id"] == row["id"]
        assert state["status"] == "pending"
        assert not state.get("event_queue")
        assert source.dispatch_pending_source_events() == {"dispatched": [], "issues": []}
    finally:
        restarted.db.close()


def test_lost_admission_reply_cannot_requeue_after_task_finished(ledger, monkeypatch):
    def lost_reply(*_args):
        raise ValueError("reply lost after Task admission")

    monkeypatch.setattr(assignments, "ensure_task_runbook", lost_reply)
    with pytest.raises(source.SourceError, match="reply lost"):
        _capture()
    row = ledger.sources()[0]
    task_ref = source.SOURCE_EVENT_TASKS["source.added"]
    assert row["event_dispatched_at"] is not None
    assert ledger.task_runtime(task_ref)["params"]["source_id"] == row["id"]
    _finish_and_clear(task_ref)
    completed = ledger.task_runtime(task_ref)
    monkeypatch.setattr(assignments, "ensure_task_runbook", lambda *_args: {"status": "ready"})

    restarted = index.Index()
    try:
        monkeypatch.setattr(index, "INDEX", restarted)
        monkeypatch.setattr(scheduler, "INDEX", restarted)
        assert _capture()["source_event"] is None
        # A caller may have retained a pre-admission snapshot even after restart.
        replay = source._source_event({**row, "event_dispatched_at": None})
        assert replay["occurrences"][0]["state"] == "processed"
        assert restarted.task_runtime(task_ref) == completed
        assert source.dispatch_pending_source_events() == {"dispatched": [], "issues": []}
    finally:
        restarted.db.close()


def test_receipt_survives_advancing_fifo_and_preserves_later_event(ledger):
    first = _capture("first")
    second = _capture("second")
    task_ref = source.SOURCE_EVENT_TASKS["source.added"]
    task = vault.load_note(task_ref + ".md")
    vault.update_status(task, "completed")
    scheduler.advance_event_queue(task)
    before = ledger.task_runtime(task_ref)
    assert before["params"]["source_id"] == second["id"]
    source._source_event(ledger.source(first["id"]))
    assert ledger.task_runtime(task_ref) == before


def test_inbox_admission_uses_same_atomic_receipt(ledger):
    raw = _capture()
    handoff = source.handoff_source(
        title="Finding", content=f"Supported by {raw['citation']}.",
        captured_at="2026-09-09T12:05:00Z",
    )
    task_ref = source.SOURCE_EVENT_TASKS["source.inbox"]
    assert ledger.task_runtime(task_ref)["params"]["source_id"] == handoff["id"]
    _finish_and_clear(task_ref)
    completed = ledger.task_runtime(task_ref)
    source._source_event(ledger.source(handoff["id"]))
    assert ledger.task_runtime(task_ref) == completed


def test_research_handoff_activation_stays_deduplicated_when_retitled(ledger, monkeypatch):
    raw = _capture()
    monkeypatch.setattr(source, "_research_owner", lambda *_args: True)
    content = f"Same finding supported by {raw['citation']}."
    first = source.handoff_source(
        title="First title", content=content,
        research_task="Tasks/research/learn", research_run_id="same-research",
    )
    task_ref = source.SOURCE_EVENT_TASKS["source.inbox"]
    _finish_and_clear(task_ref)
    completed = ledger.task_runtime(task_ref)
    second = source.handoff_source(
        title="Clarified title", content=content,
        research_task="Tasks/research/learn", research_run_id="same-research",
    )
    assert first["id"] != second["id"]
    assert ledger.source(first["id"])["event_key"] == ledger.source(second["id"])["event_key"]
    assert ledger.source(second["id"])["event_dispatched_at"] is not None
    assert ledger.task_runtime(task_ref) == completed
    assert second["source_event"]["occurrences"][0]["state"] == "processed"


def test_unrelated_events_keep_existing_admission_semantics(ledger):
    ref = "Tasks/other"
    vault.write_note(ref + ".md", {
        "kind": "task", "title": "Other", "status": "completed",
        "triggers": ["knowledge.gap"],
    }, "Handle a different event.")
    params = {"activation_key": "non-source-occurrence"}
    assert scheduler.enqueue_named_event("knowledge.gap", params)[0]["state"] == "started"
    _finish_and_clear(ref)
    assert scheduler.enqueue_named_event("knowledge.gap", params)[0]["state"] == "started"


def test_receipt_requires_exact_source_and_successful_task_admission(ledger):
    captured = _capture()
    row = ledger.source(captured["id"])
    ref = source.SOURCE_EVENT_TASKS["source.added"]
    before = ledger.task_runtime(ref)
    with pytest.raises(ValueError, match="identity changed"):
        ledger.mutate_task_runtime(ref, lambda state: state.clear(), source_event=(row["id"], "wrong"))
    assert ledger.task_runtime(ref) == before

    # A pending Source cannot be stamped if the callback did not retain its
    # exact occurrence, including a silently deferred Review mutation.
    with ledger.db:
        ledger.db.execute("UPDATE source_evidence SET event_dispatched_at=NULL WHERE id=?", (row["id"],))
    with pytest.raises(ValueError, match="not admitted"):
        ledger.mutate_task_runtime(
            ref, lambda state: state.clear(), source_event=(row["id"], row["event_key"]),
        )
    assert ledger.task_runtime(ref) == before
    assert ledger.source(row["id"])["event_dispatched_at"] is None
    with pytest.raises(ValueError, match="not admitted"):
        ledger.mutate_task_runtime(ref, lambda state: state.update(params={
            "activation_key": row["event_key"], "source_id": "different-unbound-source",
        }), source_event=(row["id"], row["event_key"]))
    assert ledger.task_runtime(ref) == before


def test_two_connections_admit_one_source_once(ledger):
    captured = _capture()
    row = ledger.source(captured["id"])
    ref = source.SOURCE_EVENT_TASKS["source.added"]
    params = deepcopy(ledger.task_runtime(ref)["params"])
    _finish_and_clear(ref)
    with ledger.db:
        ledger.db.execute("UPDATE source_evidence SET event_dispatched_at=NULL WHERE id=?", (row["id"],))
    second = index.Index()
    callbacks = []

    def admit(owner):
        def mutate(state):
            callbacks.append(owner)
            state.update(status="pending", params=params)

        return owner.mutate_task_runtime(ref, mutate, source_event=(row["id"], row["event_key"]))

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(admit, owner) for owner in (ledger, second)]
            assert [result.result(timeout=5)["params"] for result in results] == [params, params]
        assert len(callbacks) == 1
        assert ledger.source(row["id"])["event_dispatched_at"] is not None
    finally:
        second.db.close()
