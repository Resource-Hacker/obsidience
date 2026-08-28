from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace

import pytest

from obsidience.harness.capabilities.source import handoff as handoff_capability
from obsidience.harness.capabilities.task import complete as task_complete_capability
from obsidience.harness import config
from obsidience.harness.execution import scheduler
from obsidience.harness.knowledge import index as source_index
from obsidience.harness.knowledge import source
from obsidience.harness.knowledge.tasks import (
    TASK_TAXONOMY_BY_PATH,
    task_triggers,
)
from obsidience.harness.knowledge.vault import resolver


class FakeSourceIndex:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def source_by_fingerprint(
        self,
        lane: str,
        source_type: str,
        source_ref: str,
        media_type: str,
        content_sha256: str,
    ) -> dict | None:
        return next((
            row for row in self.rows.values()
            if str(row["path"]).startswith(lane + "/")
            and row["source_type"] == source_type
            and row["source_ref"] == source_ref
            and row["media_type"] == media_type
            and row["content_sha256"] == content_sha256
        ), None)

    def record_source(self, **values) -> None:
        self.rows[str(values["id"])] = dict(values)

    def source(self, source_id: str) -> dict | None:
        return self.rows.get(source_id)

    def mark_source_event_dispatched(self, source_id: str, dispatched_at: float) -> None:
        row = self.rows[source_id]
        if row["event_key"] and row["event_dispatched_at"] is None:
            row["event_dispatched_at"] = dispatched_at

    def pending_source_events(self, limit: int = 100) -> list[dict]:
        return [
            row for row in self.rows.values()
            if row["event_key"] and row["event_dispatched_at"] is None
        ][:limit]

    def sources(self, limit: int = 500) -> list[dict]:
        return list(self.rows.values())[:limit]


def _runtime(monkeypatch, tmp_path) -> FakeSourceIndex:
    fake = FakeSourceIndex()
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        config.CONFIG, "vault_dir", tmp_path / "obsidience" / "vault"
    )
    monkeypatch.setattr(source_index, "INDEX", fake)
    return fake


def _route(calls: list[tuple[str, dict]]):
    def enqueue(
        event: str,
        params: dict,
        *,
        expected_task: str | None = None,
    ) -> list[dict]:
        calls.append((event, params))
        target = {
            "source.added": "Tasks/research/learn",
            "source.inbox": "Tasks/ingest",
        }[event]
        assert expected_task == target
        return [{"task": target, "state": "started"}]

    return enqueue


def test_raw_source_emits_learn_once(monkeypatch, tmp_path) -> None:
    _runtime(monkeypatch, tmp_path)
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(scheduler, "enqueue_named_event", _route(calls))

    result = source.ingest_source(
        source_type="document",
        source_ref="example.txt",
        media_type="text/plain",
        captured_at="2026-08-27T20:00:00Z",
        content="evidence",
    )

    assert result["created"] is True
    assert result["path"].startswith("raw/")
    assert (tmp_path / "obsidience" / "evidence" / result["path"]).is_file()
    assert [event for event, _params in calls] == ["source.added"]
    assert result["source_event"]["occurrences"] == [
        {"task": "Tasks/research/learn", "state": "started"}
    ]
    assert result["source_event"]["params"]["activation_key"] == (
        f"source.added:{result['id']}"
    )

    duplicate = source.ingest_source(
        source_type="document",
        source_ref="example.txt",
        media_type="text/plain",
        captured_at="2026-08-27T20:00:00Z",
        content="evidence",
    )
    assert duplicate["created"] is False
    assert duplicate["id"] == result["id"]
    assert duplicate["source_event"] is None
    assert len(calls) == 1


def test_research_handoff_uses_distinct_inbox_lane_and_ingest(monkeypatch, tmp_path) -> None:
    _runtime(monkeypatch, tmp_path)
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(scheduler, "enqueue_named_event", _route(calls))
    evidence = source.ingest_source(
        source_type="document",
        source_ref="manual.txt",
        media_type="text/plain",
        captured_at="2026-08-27T20:00:00Z",
        content="primary evidence",
    )
    finding = f"Bounded finding supported by {evidence['citation']}."
    calls.clear()

    handoff = source.handoff_source(
        title="Bounded finding",
        content=finding,
        captured_at="2026-08-27T20:05:00Z",
    )

    assert handoff["created"] is True
    assert handoff["path"].startswith("inbox/")
    assert (tmp_path / "obsidience" / "evidence" / handoff["path"]).is_file()
    assert handoff["source_citations"] == [evidence["citation"]]
    assert [event for event, _params in calls] == ["source.inbox"]
    assert handoff["source_event"]["occurrences"] == [
        {"task": "Tasks/ingest", "state": "started"}
    ]

    duplicate = source.handoff_source(
        title="Bounded finding",
        content=finding,
        captured_at="2026-08-27T20:05:00Z",
    )
    assert duplicate["created"] is False
    assert duplicate["source_event"] is None
    assert len(calls) == 1

    raw_copy = source.ingest_source(
        source_type="research",
        source_ref="Bounded finding",
        media_type="text/markdown",
        captured_at="2026-08-27T20:05:00Z",
        content=finding,
    )
    assert raw_copy["id"] != handoff["id"]
    assert raw_copy["path"].startswith("raw/")


def test_handoff_rejects_missing_source_before_writing(monkeypatch, tmp_path) -> None:
    fake = _runtime(monkeypatch, tmp_path)
    monkeypatch.setattr(
        scheduler,
        "enqueue_named_event",
        lambda *_args, **_kwargs: pytest.fail("invalid handoff emitted an event"),
    )

    with pytest.raises(source.SourceError, match="at least one source:// citation"):
        source.handoff_source(title="Unsupported", content="No evidence here.")

    assert fake.rows == {}
    assert not (tmp_path / "obsidience" / "evidence" / "inbox").exists()


def test_pending_source_event_replays_exactly_once(monkeypatch, tmp_path) -> None:
    fake = _runtime(monkeypatch, tmp_path)
    monkeypatch.setattr(
        scheduler,
        "enqueue_named_event",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("source.added must resolve exactly to Tasks/research/learn; got none")
        ),
    )

    with pytest.raises(source.SourceError, match="must resolve exactly"):
        source.ingest_source(
            source_type="document",
            source_ref="replay.txt",
            media_type="text/plain",
            captured_at="2026-08-27T20:00:00Z",
            content="durable before dispatch",
        )

    assert len(fake.rows) == 1
    row = next(iter(fake.rows.values()))
    assert row["event_dispatched_at"] is None
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(scheduler, "enqueue_named_event", _route(calls))

    first = source.dispatch_pending_source_events()
    second = source.dispatch_pending_source_events()
    assert first["dispatched"] == [f"source://{row['id']}"]
    assert first["issues"] == []
    assert second == {"dispatched": [], "issues": []}
    assert [event for event, _params in calls] == ["source.added"]


def test_source_ledger_precedes_physical_install_and_replay_restores(
    monkeypatch, tmp_path,
) -> None:
    fake = _runtime(monkeypatch, tmp_path)
    original_atomic_write = source._atomic_write
    monkeypatch.setattr(
        source,
        "_atomic_write",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk interrupted")),
    )
    monkeypatch.setattr(
        scheduler,
        "enqueue_named_event",
        lambda *_args, **_kwargs: pytest.fail("event preceded physical Source"),
    )

    with pytest.raises(OSError, match="disk interrupted"):
        source.ingest_source(
            source_type="document",
            source_ref="interrupted.txt",
            media_type="text/plain",
            captured_at="2026-08-27T20:00:00Z",
            content="ledger survives",
        )

    assert len(fake.rows) == 1
    row = next(iter(fake.rows.values()))
    assert row["event_dispatched_at"] is None
    assert not (
        tmp_path / "obsidience" / "evidence" / row["path"]
    ).exists()

    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(source, "_atomic_write", original_atomic_write)
    monkeypatch.setattr(scheduler, "enqueue_named_event", _route(calls))
    replay = source.dispatch_pending_source_events()

    assert replay["issues"] == []
    assert (tmp_path / "obsidience" / "evidence" / row["path"]).is_file()
    assert [event for event, _params in calls] == ["source.added"]


def test_source_ledger_failure_leaves_no_orphan_file(monkeypatch, tmp_path) -> None:
    fake = _runtime(monkeypatch, tmp_path)
    monkeypatch.setattr(
        fake,
        "record_source",
        lambda **_values: (_ for _ in ()).throw(sqlite3.IntegrityError("ledger failed")),
    )
    monkeypatch.setattr(
        scheduler,
        "enqueue_named_event",
        lambda *_args, **_kwargs: pytest.fail("failed Source emitted an event"),
    )

    with pytest.raises(sqlite3.IntegrityError, match="ledger failed"):
        source.ingest_source(
            source_type="document",
            source_ref="orphan.txt",
            media_type="text/plain",
            captured_at="2026-08-27T20:00:00Z",
            content="must not install",
        )

    assert not (tmp_path / "obsidience" / "evidence").exists()


def test_source_event_columns_migrate_from_legacy_ledger(monkeypatch, tmp_path) -> None:
    database = tmp_path / "legacy-source.sqlite3"
    legacy = sqlite3.connect(database)
    legacy.execute(
        "CREATE TABLE source_evidence("
        "id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL, source_type TEXT NOT NULL, "
        "source_ref TEXT NOT NULL, media_type TEXT NOT NULL, captured_at TEXT NOT NULL, "
        "content_sha256 TEXT NOT NULL, material_sha256 TEXT UNIQUE NOT NULL, "
        "material BLOB NOT NULL, created_at REAL NOT NULL)"
    )
    legacy.execute(
        "INSERT INTO source_evidence VALUES(?,?,?,?,?,?,?,?,?,?)",
        ("old", "raw/old.md", "document", "old", "text/plain", "2026-08-01T00:00:00Z",
         "sha256:content", "sha256:material", b"legacy", 1.0),
    )
    legacy.commit()
    legacy.close()
    monkeypatch.setattr(source_index.CONFIG, "db_path", database)

    migrated = source_index.Index()
    columns = {
        row[1] for row in migrated.db.execute("PRAGMA table_info(source_evidence)")
    }
    old_row = migrated.db.execute(
        "SELECT event_key,event_dispatched_at FROM source_evidence WHERE id='old'"
    ).fetchone()

    assert {"event_key", "event_dispatched_at"} <= columns
    assert old_row == (None, None)
    migrated.record_source(
        id="new", path="raw/new.md", source_type="document", source_ref="new",
        media_type="text/plain", captured_at="2026-08-27T20:00:00Z",
        content_sha256="sha256:new-content", material_sha256="sha256:new-material",
        material=b"new", created_at=2.0, event_key="source.added:new",
        event_dispatched_at=None,
    )
    assert migrated.source("new")["event_key"] == "source.added:new"
    migrated.db.close()


def test_one_task_subscribes_to_multiple_events(monkeypatch) -> None:
    task = SimpleNamespace(
        kind="task",
        ref="Tasks/research/learn",
        meta={"triggers": ["source.added", "knowledge.gap"]},
    )
    monkeypatch.setattr(scheduler, "iter_notes", lambda: [task])
    monkeypatch.setattr(
        scheduler,
        "enqueue_event",
        lambda _task, params: {"state": "started", "event": params["event"]},
    )

    assert scheduler.enqueue_named_event("source.added", {}) == [{
        "task": task.ref,
        "state": "started",
        "event": "source.added",
    }]
    assert scheduler.enqueue_named_event("knowledge.gap", {}) == [{
        "task": task.ref,
        "state": "started",
        "event": "knowledge.gap",
    }]
    assert task_triggers({"triggers": ["a", "b", "a"]}) == ("a", "b")
    assert task_triggers({"event": "legacy"}) == ()


def test_reserved_event_validates_subscriber_before_mutation(monkeypatch) -> None:
    subscribers = [
        SimpleNamespace(kind="task", ref="Tasks/research/learn", meta={"triggers": ["source.added"]}),
        SimpleNamespace(kind="task", ref="Tasks/ingest", meta={"triggers": ["source.added"]}),
    ]
    mutations: list[str] = []
    monkeypatch.setattr(scheduler, "iter_notes", lambda: subscribers)
    monkeypatch.setattr(
        scheduler,
        "enqueue_event",
        lambda task, _params: mutations.append(task.ref) or {"state": "started"},
    )

    with pytest.raises(ValueError, match="must resolve exactly"):
        scheduler.enqueue_named_event(
            "source.added",
            {},
            expected_task="Tasks/research/learn",
        )
    assert mutations == []


def test_restart_retries_active_event_without_losing_fifo(monkeypatch) -> None:
    active = {"event": "source.inbox", "activation_key": "source.inbox:active"}
    waiting = {"event": "source.inbox", "activation_key": "source.inbox:waiting"}
    task = SimpleNamespace(
        kind="task",
        ref="Tasks/ingest",
        title="Ingest",
        path="Tasks/ingest.md",
        mtime=1.0,
        meta={
            "status": "running",
            "triggers": ["source.inbox"],
            "params": active,
            "event_queue": [waiting],
            "reasoning_effort": "high",
        },
    )
    recorded: list[dict] = []

    def update(_note, status: str, extra: dict | None = None) -> None:
        task.meta["status"] = status
        task.meta.update(extra or {})
        if status not in {"blocked", "failed"}:
            task.meta.pop("blocked_reason", None)

    monkeypatch.setattr(scheduler, "iter_notes", lambda: [task])
    monkeypatch.setattr(scheduler, "update_status", update)
    monkeypatch.setattr(scheduler.INDEX, "record_run", lambda **values: recorded.append(values))

    assert scheduler.reconcile_interrupted_runs() == ["Tasks/ingest"]
    assert task.meta["status"] == "pending"
    assert task.meta["params"] == active
    assert task.meta["event_queue"] == [waiting]
    assert recorded[0]["status"] == "failed"


def test_failed_event_keeps_active_params_and_waiting_fifo(monkeypatch) -> None:
    active = {"event": "source.inbox", "activation_key": "source.inbox:active"}
    waiting = {"event": "source.inbox", "activation_key": "source.inbox:waiting"}
    task = SimpleNamespace(
        kind="task",
        ref="Tasks/ingest",
        title="Ingest",
        path="Tasks/ingest.md",
        mtime=1.0,
        meta={
            "status": "pending",
            "triggers": ["source.inbox"],
            "params": active,
            "event_queue": [waiting],
            "reasoning_effort": "high",
            "model": "auto",
        },
    )
    advanced: list[str] = []

    async def fail(_task, **_kwargs):
        raise RuntimeError("provider unavailable")

    def update(_note, status: str, extra: dict | None = None) -> None:
        task.meta["status"] = status
        task.meta.update(extra or {})

    monkeypatch.setattr(scheduler, "run_task", fail)
    monkeypatch.setattr(scheduler, "update_status", update)
    monkeypatch.setattr(scheduler, "load_note", lambda _path: task)
    monkeypatch.setattr(
        scheduler,
        "advance_event_queue",
        lambda note: advanced.append(note.ref) or {"promoted": True},
    )
    monkeypatch.setattr(scheduler.INDEX, "record_run", lambda **_values: None)

    asyncio.run(scheduler._run(task))
    assert task.meta["status"] == "failed"
    assert task.meta["params"] == active
    assert task.meta["event_queue"] == [waiting]
    assert advanced == []


@pytest.mark.parametrize("unresolved_status", ["failed", "blocked"])
def test_new_event_waits_behind_unresolved_active_occurrence(
    monkeypatch, unresolved_status,
) -> None:
    active = {"event": "source.inbox", "activation_key": "source.inbox:active"}
    waiting = {"event": "source.inbox", "activation_key": "source.inbox:waiting"}
    incoming = {"event": "source.inbox", "activation_key": "source.inbox:incoming"}
    task = SimpleNamespace(
        path="Tasks/ingest.md",
        meta={
            "status": unresolved_status,
            "params": active,
            "event_queue": [waiting],
        },
    )

    def mutate(_task, update) -> None:
        update(task.meta)

    monkeypatch.setattr(scheduler, "mutate_note_metadata", mutate)

    result = scheduler.enqueue_event(task, incoming)

    assert result["state"] == "queued"
    assert task.meta["status"] == unresolved_status
    assert task.meta["params"] == active
    assert task.meta["event_queue"] == [waiting, incoming]


def test_reserved_source_triggers_match_existing_tasks() -> None:
    learn = resolver().resolve("Tasks/research/learn")
    ingest = resolver().resolve("Tasks/ingest")
    assert learn is not None and task_triggers(learn.meta) == ("source.added",)
    assert ingest is not None and task_triggers(ingest.meta) == ("source.inbox",)
    assert TASK_TAXONOMY_BY_PATH["research/learn"].triggers == ("source.added",)
    assert TASK_TAXONOMY_BY_PATH["wiki/ingest"].triggers == ("source.inbox",)


def test_source_handoff_capability_is_darwin_research_only(monkeypatch) -> None:
    called = False

    def unexpected(**_kwargs):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(source, "handoff_source", unexpected)
    result = handoff_capability.execute(
        {"title": "Finding", "content": "source://12345678-1234-4234-9234-123456789abc"},
        {"agent": "Executive", "task": "Tasks/research/learn"},
    )
    assert "only Darwin Research Tasks" in result
    assert called is False


def test_task_completion_with_proposals_requires_review() -> None:
    task = SimpleNamespace(ref="Tasks/ingest", kind="task", meta={"auto_done": True})
    result = task_complete_capability.execute(
        {"status": "completed", "summary": "staged the article"},
        {
            "task_note": task,
            "staged_proposals": [{"target": "Articles/example", "action": "create"}],
        },
    )

    assert result["accepted"] is False
    assert result["status"] == "completed"
    assert 'must finish with status "review"' in result["error"]
