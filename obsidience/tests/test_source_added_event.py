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
from obsidience.harness.knowledge.vault import resolver, write_note


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
        source_event: tuple[str, str] | None = None,
    ) -> list[dict]:
        calls.append((event, params))
        target = {
            "source.added": "Tasks/research/learn",
            "source.inbox": "Tasks/ingest",
        }[event]
        assert expected_task == target
        assert source_event == (params["source_id"], params["activation_key"])
        source_index.INDEX.mark_source_event_dispatched(params["source_id"], 1.0)
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


def test_controller_bound_observation_archive_emits_without_learn(
    monkeypatch, tmp_path,
) -> None:
    _runtime(monkeypatch, tmp_path)
    conversation_id = "conversation-" + "a" * 32
    promotion_key = "b" * 20
    write_note(
        "Agents/Executive/Observations/Temporary Observations/archive.md",
        {
            "title": "Temporary archive input",
            "kind": "knowledge",
            "observation_scope": "temporary",
            "temporary": True,
            "compaction": True,
            "compaction_committed": True,
            "source_conversation_id": conversation_id,
            "promotion_pending": promotion_key,
        },
        "Controller-bound metadata, not this body, establishes the archive class.",
    )
    learn = SimpleNamespace(
        kind="task",
        ref="Tasks/research/learn",
        meta={"triggers": ["source.added"]},
    )
    monkeypatch.setattr(scheduler, "iter_notes", lambda: [learn])
    monkeypatch.setattr(
        scheduler,
        "enqueue_event",
        lambda *_args, **_kwargs: pytest.fail("observation archive activated Learn"),
    )

    result = source.ingest_source(
        source_type="document",
        source_ref=(
            "obsidience://observations/temporary/"
            f"{conversation_id}/{promotion_key}"
        ),
        media_type="text/markdown",
        captured_at="2026-09-04T20:00:00Z",
        content="The raw content does not classify itself.",
    )

    assert result["created"] is True
    assert result["source_event"]["name"] == "source.added"
    assert result["source_event"]["params"]["source_class"] == (
        source.OBSERVATION_ARCHIVE_SOURCE_CLASS
    )
    assert result["source_event"]["occurrences"] == []


@pytest.mark.parametrize(
    ("source_ref", "content"),
    [
        (
            "obsidience://observations/temporary/"
            f"conversation-{'c' * 32}/{'d' * 20}",
            "An unbound reserved-looking URI is still ordinary evidence.",
        ),
        (
            "ordinary-source.md",
            "# Temporary Observation Bundle\n\nRaw text cannot assign a Source class.",
        ),
    ],
)
def test_untrusted_source_identity_cannot_assign_observation_archive_class(
    monkeypatch, tmp_path, source_ref: str, content: str,
) -> None:
    _runtime(monkeypatch, tmp_path)
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(scheduler, "enqueue_named_event", _route(calls))

    result = source.ingest_source(
        source_type="document",
        source_ref=source_ref,
        media_type="text/markdown",
        captured_at="2026-09-04T20:00:00Z",
        content=content,
    )

    assert "source_class" not in result["source_event"]["params"]
    assert result["source_event"]["occurrences"] == [
        {"task": "Tasks/research/learn", "state": "started"}
    ]


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
    from obsidience.harness.execution import assignments
    monkeypatch.setattr(assignments, "ensure_task_runbook", lambda *_args: {"status": "ready"})
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
            {"source_class": source.OBSERVATION_ARCHIVE_SOURCE_CLASS},
            expected_task="Tasks/research/learn",
        )
    assert mutations == []


def test_observation_archive_filter_is_exact_and_learn_only(monkeypatch) -> None:
    from obsidience.harness.execution import assignments
    monkeypatch.setattr(assignments, "ensure_task_runbook", lambda *_args: {"status": "ready"})
    learn = SimpleNamespace(
        kind="task",
        ref="Tasks/research/learn",
        meta={"triggers": ["source.added"]},
    )
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(scheduler, "iter_notes", lambda: [learn])
    monkeypatch.setattr(
        scheduler,
        "enqueue_event",
        lambda task, params: calls.append((task.ref, params)) or {"state": "started"},
    )

    assert scheduler.enqueue_named_event(
        "source.added",
        {"source_class": source.OBSERVATION_ARCHIVE_SOURCE_CLASS},
        expected_task="Tasks/research/learn",
    ) == []
    assert calls == []

    ordinary = scheduler.enqueue_named_event(
        "source.added",
        {"source_class": "observation-archive"},
        expected_task="Tasks/research/learn",
    )
    assert ordinary == [{"task": learn.ref, "state": "started"}]
    assert calls == [(learn.ref, {"event": "source.added", "source_class": "observation-archive"})]


def test_observation_archive_and_promotion_completion_contracts_are_explicit() -> None:
    learn = resolver().resolve("Runbooks/research/learn")
    promote = resolver().resolve("Runbooks/observations/promote")
    promote_body = " ".join(promote.body.split()) if promote is not None else ""

    assert learn is not None
    assert "`source_class: observation_archive`" in learn.body
    assert "legacy queued observation archive" in learn.body
    assert promote is not None
    assert "Finish `review` when this execution staged" in promote_body
    assert (
        "Finish `completed` for explicitly published changes or an honest no-change/archival-only"
        in promote_body
    )


def test_restart_retries_active_event_without_losing_fifo(monkeypatch, tmp_path) -> None:
    # This synthetic no-effect run owns an empty Review scope. The workstation
    # or copied integration Vault may contain unrelated real Ingest proposals.
    monkeypatch.setattr(config.CONFIG, "vault_dir", tmp_path / "vault")
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
            "last_run": "covered-restart",
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

    def mutate(_note, operation) -> None:
        operation(task.meta)

    monkeypatch.setattr(scheduler, "iter_notes", lambda: [task])
    monkeypatch.setattr(scheduler, "update_status", update)
    monkeypatch.setattr(scheduler, "mutate_note_metadata", mutate)
    monkeypatch.setattr(scheduler.INDEX, "record_run", lambda **values: recorded.append(values))
    scheduler.INDEX.begin_tool_run(run_id="covered-restart", task_ref=task.ref, params=active, started=1.)

    assert scheduler.reconcile_interrupted_runs() == ["Tasks/ingest"]
    assert task.meta["status"] == "pending"
    assert task.meta["params"] == active
    assert task.meta["event_queue"] == [waiting]
    assert recorded[0]["status"] == "failed"


def test_restart_recovers_covered_failed_interruption_and_dedupes_candidate_pair(
    monkeypatch,
) -> None:
    active = {
        "event": "task.create",
        "activation_key": "a" * 20,
        "target_task": "Tasks/link",
        "candidate_refs": ["Knowledge/one", "Knowledge/two"],
    }
    duplicate = {
        "event": "task.create",
        "activation_key": "b" * 20,
        "target_task": "Tasks/link",
        "candidate_refs": ["Knowledge/two", "Knowledge/one"],
    }
    waiting = {
        "event": "task.create",
        "activation_key": "c" * 20,
        "target_task": "Tasks/link",
        "candidate_refs": ["Knowledge/one", "Knowledge/three"],
    }
    task = SimpleNamespace(
        kind="task",
        ref="Tasks/link",
        title="Link",
        path="Tasks/link.md",
        mtime=1.0,
        meta={
            "status": "failed",
            "last_run": "covered-failed-restart",
            "blocked_reason": "interrupted by harness restart; outcome is unknown",
            "triggers": ["task.create"],
            "params": active,
            "event_queue": [duplicate, waiting],
            "reasoning_effort": "xhigh",
        },
    )
    recorded: list[dict] = []

    def mutate(_note, operation) -> None:
        operation(task.meta)

    monkeypatch.setattr(scheduler, "iter_notes", lambda: [task])
    monkeypatch.setattr(scheduler, "mutate_note_metadata", mutate)
    monkeypatch.setattr(scheduler.INDEX, "record_run", lambda **values: recorded.append(values))
    scheduler.INDEX.begin_tool_run(run_id="covered-failed-restart", task_ref=task.ref, params=active, started=1.)

    assert scheduler.reconcile_interrupted_runs() == ["Tasks/link"]
    assert task.meta["status"] == "pending"
    assert "blocked_reason" not in task.meta
    assert task.meta["params"] == active
    assert task.meta["event_queue"] == [waiting]
    assert recorded == []


def test_restart_does_not_retry_an_ordinary_failed_event(monkeypatch) -> None:
    task = SimpleNamespace(
        kind="task",
        ref="Tasks/link",
        title="Link",
        path="Tasks/link.md",
        mtime=1.0,
        meta={
            "status": "failed",
            "blocked_reason": "provider unavailable",
            "triggers": ["task.create"],
            "params": {
                "event": "task.create",
                "activation_key": "a" * 20,
            },
        },
    )
    monkeypatch.setattr(scheduler, "iter_notes", lambda: [task])

    assert scheduler.reconcile_interrupted_runs() == []
    assert task.meta["status"] == "failed"


def test_advancing_candidate_event_skips_same_pair_with_a_new_content_key(
    monkeypatch,
) -> None:
    active = {
        "event": "task.create",
        "activation_key": "a" * 20,
        "target_task": "Tasks/link",
        "candidate_refs": ["Knowledge/one", "Knowledge/two"],
    }
    duplicate = {
        "event": "task.create",
        "activation_key": "b" * 20,
        "target_task": "Tasks/link",
        "candidate_refs": ["Knowledge/two", "Knowledge/one"],
    }
    waiting = {
        "event": "task.create",
        "activation_key": "c" * 20,
        "target_task": "Tasks/link",
        "candidate_refs": ["Knowledge/one", "Knowledge/three"],
    }
    task = SimpleNamespace(
        path="Tasks/link.md",
        meta={
            "status": "completed",
            "params": active,
            "event_queue": [duplicate, waiting],
        },
    )

    def mutate(_task, operation) -> None:
        operation(task.meta)

    monkeypatch.setattr(scheduler, "mutate_note_metadata", mutate)

    result = scheduler.advance_event_queue(task)

    assert result == {"promoted": True, "queue_depth": 0}
    assert task.meta["status"] == "pending"
    assert task.meta["params"] == waiting
    assert "event_queue" not in task.meta


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
    assert learn is not None and task_triggers(learn.meta) == (
        "source.added",
        "task.create",
    )
    assert ingest is not None and task_triggers(ingest.meta) == ("source.inbox",)
    assert TASK_TAXONOMY_BY_PATH["research/learn"].triggers == (
        "source.added",
        "task.create",
    )
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


def test_task_completion_with_proposals_requires_review(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(config.CONFIG, "vault_dir", tmp_path / "vault")
    staged = config.CONFIG.vault_dir / "_staging/pending.md"
    staged.parent.mkdir(parents=True)
    staged.write_text("pending")
    task = SimpleNamespace(ref="Tasks/ingest", kind="task", meta={"auto_done": True})
    result = task_complete_capability.execute(
        {"status": "completed", "summary": "staged the article"},
        {
            "task_note": task,
            "staged_proposals": [{
                "staged": "_staging/pending.md",
                "target": "Articles/example",
                "action": "create",
            }],
        },
    )

    assert result["accepted"] is False
    assert result["status"] == "completed"
    assert 'must finish with status "review"' in result["error"]
