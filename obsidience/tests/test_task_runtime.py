from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import numpy as np
import pytest

from obsidience.harness import config
from obsidience.harness.execution import scheduler
from obsidience.harness.knowledge import index, vault
from obsidience.harness.knowledge.vault import Note


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(config.CONFIG, "db_path", tmp_path / "runtime.sqlite3")
    result = index.Index()
    monkeypatch.setattr(index, "INDEX", result)
    monkeypatch.setattr(scheduler, "INDEX", result)
    yield result
    result.db.close()


def semantic_runtime(state):
    if state.get("params") or state.get("last_run"):
        assert state.get("activation_id"), "An actual occurrence retains its exact identity"
    return {key: value for key, value in state.items() if key != "activation_id"}


def test_explicit_migration_preserves_runtime_and_cannot_overwrite_newer_work(ledger):
    original = {
        "status": "review", "last_run": "run-one", "summary": "Awaiting exact review.",
        "params": {"activation_key": "current", "created_by_run_id": "caller"},
        "event_queue": [{"activation_key": "next", "source_id": "source-one"}],
        "status_updated": "2026-09-05T01:02:03", "triggered_at": "2026-09-05T01:00:00",
    }
    assert semantic_runtime(ledger.seed_task_runtime("Tasks/ingest", {**original, "article_status": "stable"})) == original
    ledger.mutate_task_runtime("Tasks/ingest", lambda state: state.update(status="completed"))
    expected = {**original, "status": "completed"}
    assert semantic_runtime(ledger.seed_task_runtime("Tasks/ingest", original)) == expected
    second = index.Index()
    try:
        assert semantic_runtime(second.task_runtime("Tasks/ingest")) == expected
    finally:
        second.db.close()


def test_native_article_bytes_stay_fixed_through_queue_review_and_restart(ledger, tmp_path, monkeypatch):
    monkeypatch.setattr(config.CONFIG, "vault_dir", tmp_path / "vault")
    path = vault.write_note("Tasks/link.md", {
        "kind": "task", "title": "Link", "article_status": "stable",
        "status": "completed", "triggers": ["task.create"],
    }, "Maintain one exact relationship.")
    from pathlib import Path

    original = Path(path).read_bytes()
    task = vault.load_note("Tasks/link.md")
    first = {"event": "task.create", "activation_key": "first", "created_by_run_id": "caller-one"}
    second = {"event": "task.create", "activation_key": "second", "created_by_run_id": "caller-two"}
    scheduler.enqueue_event(task, first)
    scheduler.enqueue_event(task, second)
    vault.update_status(task, "review", {"last_run": "review-run", "summary": "Awaiting a decision."})
    assert Path(path).read_bytes() == original

    reopened = index.Index()
    try:
        monkeypatch.setattr(index, "INDEX", reopened)
        monkeypatch.setattr(scheduler, "INDEX", reopened)
        task = vault.load_note(task.path)
        assert task.meta["article_status"] == "stable"
        assert task.meta["status"] == "review"
        assert task.meta["params"] == first
        assert task.meta["event_queue"] == [second]
        vault.update_status(task, "completed")
        scheduler.advance_event_queue(task)
        current = vault.load_note(task.path)
        assert current.meta["status"] == "pending"
        assert current.meta["params"] == second
        assert "event_queue" not in current.meta
        assert Path(path).read_bytes() == original
    finally:
        reopened.db.close()


def test_read_projection_never_imports_or_resurrects_article_runtime(ledger):
    authored = {
        "kind": "task", "article_status": "stable", "model": "selected-model",
        "status": "running", "last_run": "stale", "params": {"activation_key": "old"},
    }
    assert ledger.project_task_runtime("Tasks/query", authored) == {
        "kind": "task", "article_status": "stable", "model": "selected-model", "status": "draft",
    }
    assert ledger.task_runtime("Tasks/query") is None
    ledger.seed_task_runtime("Tasks/query", {"status": "completed"})
    assert ledger.project_task_runtime("Tasks/query", authored)["status"] == "completed"
    assert "params" not in ledger.project_task_runtime("Tasks/query", authored)
    assert authored["status"] == "running"


def test_cleared_queue_survives_migration_replay(ledger):
    old = {"status": "pending", "params": {"activation_key": "one"}, "event_queue": [{"activation_key": "two"}]}
    ledger.seed_task_runtime("Tasks/link", old)

    def finish(state):
        state["status"] = "completed"
        state.pop("params")
        state.pop("event_queue")

    ledger.mutate_task_runtime("Tasks/link", finish)
    assert semantic_runtime(ledger.seed_task_runtime("Tasks/link", old)) == {"status": "completed"}


def test_state_mutation_rolls_back_on_failure_and_allows_ledger_reads(ledger):
    ledger.seed_task_runtime("Tasks/link", {"status": "pending", "event_queue": []})

    def rejected(state):
        assert ledger.task_runtime("Tasks/link")["status"] == "pending"
        state["event_queue"].append({"activation_key": "must-not-persist"})
        raise ValueError("The exact commitment changed")

    with pytest.raises(ValueError, match="commitment changed"):
        ledger.mutate_task_runtime("Tasks/link", rejected)
    assert semantic_runtime(ledger.task_runtime("Tasks/link")) == {"status": "pending", "event_queue": []}


def test_task_move_keeps_pending_state_and_rejects_destination_collision(ledger):
    state = {"status": "pending", "params": {"activation_key": "exact"}, "last_run": "historical"}
    ledger.seed_task_runtime("Tasks/original", state)
    ledger.record_run(
        id="historical", task_ref="Tasks/original", agent="test", started=1.0, finished=2.0,
        status="completed", summary="Original attempt.", trace="[]",
    )
    ledger.remap_task_runtime({"Tasks/original": "Tasks/renamed"})
    assert ledger.task_runtime("Tasks/original") is None
    assert semantic_runtime(ledger.task_runtime("Tasks/renamed")) == state
    assert ledger.run("historical")["task_ref"] == "Tasks/original"

    ledger.seed_task_runtime("Tasks/occupied", {"status": "review"})
    with pytest.raises(ValueError, match="already owns"):
        ledger.remap_task_runtime({"Tasks/renamed": "Tasks/occupied"})
    assert semantic_runtime(ledger.task_runtime("Tasks/renamed")) == state
    assert semantic_runtime(ledger.task_runtime("Tasks/occupied")) == {"status": "review"}

    ledger.remap_task_runtime({"Tasks/renamed": "Tasks/original"})
    assert semantic_runtime(ledger.task_runtime("Tasks/original")) == state
    assert ledger.task_runtime("Tasks/renamed") is None


def test_concurrent_connections_keep_every_fifo_occurrence(ledger):
    ledger.seed_task_runtime("Tasks/link", {"status": "pending", "event_queue": []})
    second = index.Index()

    def append_lane(owner, lane):
        for number in range(12):
            owner.mutate_task_runtime("Tasks/link", lambda state: state["event_queue"].append({
                "lane": lane, "position": number,
            }))

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(append_lane, owner, lane) for owner, lane in ((ledger, "a"), (second, "b"))]
            for future in futures:
                future.result(timeout=5)
        queue = ledger.task_runtime("Tasks/link")["event_queue"]
        assert len(queue) == 24
        for lane in ("a", "b"):
            assert [item["position"] for item in queue if item["lane"] == lane] == list(range(12))
    finally:
        second.db.close()


def test_graph_status_updates_without_resync_or_embedding_changes(ledger):
    meta = {"kind": "task", "article_status": "stable", "title": "Query"}
    with ledger.db:
        ledger.db.execute(
            "INSERT INTO notes(ref,path,title,kind,mtime,hash,meta,links) VALUES(?,?,?,?,?,?,?,?)",
            ("Tasks/query", "Tasks/query.md", "Query", "task", 100.0, "authored-hash", json.dumps(meta), "[]"),
        )
        ledger.db.execute("INSERT INTO embeddings(ref,hash,dim,vec) VALUES(?,?,?,?)", ("Tasks/query", "vector-hash", 1, b"unchanged"))
    ledger.seed_task_runtime("Tasks/query", {"status": "pending"})
    assert next(node for node in ledger.graph()["nodes"] if node["id"] == "Tasks/query")["status"] == "pending"
    ledger.mutate_task_runtime("Tasks/query", lambda state: state.update(status="completed"))
    assert next(node for node in ledger.graph()["nodes"] if node["id"] == "Tasks/query")["status"] == "completed"
    assert ledger.db.execute("SELECT mtime,hash,meta FROM notes WHERE ref='Tasks/query'").fetchone() == (100.0, "authored-hash", json.dumps(meta))
    assert ledger.db.execute("SELECT hash,vec FROM embeddings WHERE ref='Tasks/query'").fetchone() == ("vector-hash", b"unchanged")


def test_runtime_changes_do_not_reindex_or_reembed_the_authored_task(ledger, monkeypatch):
    task = Note(
        path="Tasks/query.md", title="Query", body="Answer the exact user request.",
        meta={"kind": "task", "article_status": "stable", "status": "pending"},
    )
    encoded = []

    def embed(texts):
        encoded.append(texts)
        return np.array([[1.0, 0.0] for _ in texts], dtype=np.float32)

    monkeypatch.setattr(index, "iter_notes", lambda: [task])
    monkeypatch.setattr(index, "_embedding_model_hash", lambda: "model-fixture")
    monkeypatch.setattr(index, "embed_texts", embed)
    assert ledger.sync()["added"] == 1
    task.meta.update(status="completed", params={"activation_key": "one"}, summary="Done.")
    assert ledger.sync()["updated"] == 0
    assert len(encoded) == 1
    stored = json.loads(ledger.db.execute("SELECT meta FROM notes WHERE ref='Tasks/query'").fetchone()[0])
    assert stored == {"kind": "task", "article_status": "stable"}


def test_graph_non_task_status_is_article_lifecycle_not_local_review_or_trust(ledger, monkeypatch):
    note = Note(
        path="Knowledge/Article.md", title="Article", body="An ordinary Article.",
        meta={"kind": "knowledge", "article_status": "stable", "status": "review", "trust": "untrusted"},
    )
    monkeypatch.setattr(index, "iter_notes", lambda: [note])
    ledger.sync(embed=False)
    node = next(node for node in ledger.graph()["nodes"] if node["id"] == note.ref)
    assert node["status"] == "stable"
    assert note.meta["trust"] == "untrusted"


@pytest.mark.parametrize("historical_ref", ["Tasks/check", "Tasks/original-name"])
def test_scheduler_restart_uses_recorded_firing_time_without_article_writes(ledger, monkeypatch, historical_ref):
    task = SimpleNamespace(
        ref="Tasks/check", kind="task", title="Check", mtime=1.0,
        meta={"status": "completed", "last_run": "latest", "schedule": "0 * * * *"},
    )
    ledger.record_run(
        id="latest", task_ref=historical_ref, agent="test", started=3900.0, finished=3901.0,
        status="completed", summary="Checked.", trace="[]",
    )
    monkeypatch.setattr(scheduler, "iter_notes", lambda: [task])
    monkeypatch.setattr(scheduler, "_realtime_allows", lambda _task, _res=None: True)
    monkeypatch.setattr(scheduler, "_running", set())
    monkeypatch.setattr(scheduler, "_last_fired", {})
    monkeypatch.setattr(scheduler.time, "time", lambda: 4000.0)
    assert scheduler.due_tasks() == []
    monkeypatch.setattr(scheduler.time, "time", lambda: 7201.0)
    assert scheduler.due_tasks() == [task]


def test_scheduler_preserves_an_executor_terminal_receipt(ledger, monkeypatch):
    task = SimpleNamespace(ref="Tasks/query", path="Tasks/query.md", title="Query", meta={})
    current = SimpleNamespace(meta={"status": "failed", "last_run": "exact-attempt"})
    monkeypatch.setattr(scheduler, "load_note", lambda _path: current)
    monkeypatch.setattr(scheduler, "_last_fired", {})
    monkeypatch.setattr(scheduler.time, "time", lambda: 20.0)

    async def failed(_task):
        ledger.record_run(
            id="exact-attempt", task_ref=task.ref, agent="test", started=20.0, finished=21.0,
            status="failed", summary="Exact failure", trace='[{"tool":"window.place","accepted":true}]',
        )
        raise RuntimeError("Exact failure")

    monkeypatch.setattr(scheduler, "run_task", failed)
    asyncio.run(scheduler._run(task))
    assert [row["id"] for row in ledger.runs()] == ["exact-attempt"]
    assert json.loads(ledger.run("exact-attempt")["trace"])[0]["accepted"] is True
