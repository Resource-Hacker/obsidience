"""Admission reserves actual capacity, not a second backlog behind the model."""
from __future__ import annotations

import asyncio
from datetime import datetime

import pytest

from obsidience.harness.config import CONFIG
from obsidience.harness.execution import scheduler
from obsidience.harness.knowledge import vault
from obsidience.harness.realtime.runtime import RUNTIME
from obsidience.tests.test_scheduler_interactive_provenance import ledger  # noqa: F401


@pytest.fixture
def admission(ledger, monkeypatch):
    monkeypatch.setattr(CONFIG, "concurrency", 1)
    monkeypatch.setattr(scheduler, "_background", set())
    monkeypatch.setattr(scheduler, "_continuations_running", set())
    monkeypatch.setattr(scheduler, "_autonomous_interruptions", {})
    monkeypatch.setattr(scheduler, "_foreground_admissions", 0)
    monkeypatch.setattr(RUNTIME, "scheduler_paused", lambda: False)
    monkeypatch.setattr(scheduler, "_resource_error", lambda _note, _model=None: None)
    prepared = []
    monkeypatch.setattr(scheduler, "prepare_task", lambda note: prepared.append(note.ref) or True)
    return prepared


def waiting(ref, *, event=None, triggered="2026-09-01T00:00:00", schedule=None):
    path = ref + ".md"
    original = vault.load_note(path)
    meta = dict(original.meta) if original else {
        "kind": "task", "title": ref.rsplit("/", 1)[-1], "assignee": "[[Agents/Alexandria/Alexandria]]"}
    meta.update(status="pending", triggered_at=triggered)
    if event:
        meta["params"] = {"event": event, "activation_key": ref + ":first"}
    if schedule:
        meta["schedule"] = schedule
        scheduler._last_fired[ref] = 1.0
    vault.write_note(path, meta, "Bounded admission fixture.")
    return vault.load_note(path)


def install_executor(monkeypatch, gate, calls, on_finish=None):
    async def execute(note, **_kwargs):
        calls.append(note.ref)
        vault.update_status(note, "running")
        await gate.wait()
        if on_finish:
            on_finish(note)
        vault.update_status(vault.load_note(note.path), "completed")
        return {"status": "completed"}
    monkeypatch.setattr(scheduler, "run_task", execute)


def test_direct_owner_launch_occupies_scheduler_capacity(admission, monkeypatch):
    periodic = waiting("Tasks/audit", schedule="* * * * *")
    direct = vault.load_note("Tasks/research/question.md")
    calls = []

    async def exercise():
        gate = asyncio.Event()
        install_executor(monkeypatch, gate, calls)
        owner = scheduler.launch(direct)
        scheduler._launch_due_tasks()
        assert scheduler._running == {direct.ref}
        assert admission == []
        assert periodic.ref not in scheduler._last_fired or scheduler._last_fired[periodic.ref] == 1.0
        await asyncio.sleep(0)
        assert calls == [direct.ref]
        gate.set()
        await owner
        assert scheduler._running == set()

    asyncio.run(exercise())
    assert vault.load_note(periodic.path).meta["status"] == "pending"


def test_configured_slots_admit_only_that_many_without_hidden_waiters(admission, monkeypatch):
    monkeypatch.setattr(CONFIG, "concurrency", 2)
    pending = [waiting("Tasks/slot-" + str(i)) for i in range(3)]
    calls = []

    async def exercise():
        gate = asyncio.Event()
        install_executor(monkeypatch, gate, calls)
        scheduler._launch_due_tasks()
        scheduler._launch_due_tasks()  # another tick before either coroutine runs
        assert scheduler._running == {note.ref for note in pending[:2]}
        assert len(scheduler._background) == 2
        assert admission == [note.ref for note in pending[:2]]
        assert pending[2].ref not in scheduler._last_fired
        await asyncio.sleep(0)
        assert calls == [note.ref for note in pending[:2]]
        gate.set()
        await asyncio.gather(*scheduler._background)
        scheduler._launch_due_tasks()
        assert scheduler._running == {pending[2].ref}
        await asyncio.gather(*scheduler._background)
        assert scheduler._running == set()

    asyncio.run(exercise())


@pytest.mark.parametrize("owner", ["external_task", "continuation"])
def test_other_execution_owners_block_autonomous_preclaims(admission, owner):
    pending = waiting("Tasks/audit", schedule="* * * * *")
    if owner == "external_task":
        vault.update_status(vault.load_note("Tasks/query.md"), "running")
    else:
        scheduler._continuations_running.add("existing-continuation")
    scheduler._launch_due_tasks()
    assert scheduler._running == set() and not scheduler._background
    assert admission == []
    assert vault.load_note(pending.path).meta["status"] == "pending"
    assert scheduler._last_fired[pending.ref] == 1.0


def test_direct_launch_plus_other_running_task_fill_configured_slots(admission, monkeypatch):
    monkeypatch.setattr(CONFIG, "concurrency", 2)
    waiting("Tasks/audit", schedule="* * * * *")
    scheduler._running.add("Tasks/direct-owner")
    vault.update_status(vault.load_note("Tasks/query.md"), "running")
    scheduler._launch_due_tasks()
    assert scheduler._running == {"Tasks/direct-owner"}
    assert admission == [] and not scheduler._background


def test_claim_and_its_running_task_are_counted_once(admission, monkeypatch):
    monkeypatch.setattr(CONFIG, "concurrency", 2)
    occupied = vault.load_note("Tasks/query.md")
    vault.update_status(occupied, "running")
    scheduler._running.add(occupied.ref)
    pending = waiting("Tasks/audit", schedule="* * * * *")
    calls = []

    async def exercise():
        gate = asyncio.Event()
        gate.set()
        install_executor(monkeypatch, gate, calls)
        scheduler._launch_due_tasks()
        assert scheduler._running == {occupied.ref, pending.ref}
        await asyncio.gather(*scheduler._background)
        assert scheduler._running == {occupied.ref}

    asyncio.run(exercise())


def test_inbox_delivery_precedes_older_maintenance_and_preserves_task_fifos(admission):
    periodic = waiting("Tasks/audit", schedule="* * * * *")
    later = waiting("Tasks/ingest", event="source.inbox", triggered="2026-09-02T00:00:00")
    earlier = waiting("Tasks/link", event="task.create", triggered="2026-09-01T00:00:00")
    fifo = {"event": "task.create", "activation_key": "later-occurrence"}
    scheduler.enqueue_event(earlier, fifo)
    inbox_fifo = {"event": "source.inbox", "activation_key": "later-handoff"}
    scheduler.enqueue_event(later, inbox_fifo)
    original = vault.load_note(earlier.path)
    original_inbox = vault.load_note(later.path)
    assert [note.ref for note in scheduler.due_tasks()] == [later.ref, earlier.ref, periodic.ref]
    unchanged = vault.load_note(earlier.path)
    assert unchanged.meta["params"] == original.meta["params"]
    assert unchanged.meta["event_queue"] == [fifo]
    unchanged_inbox = vault.load_note(later.path)
    assert unchanged_inbox.meta["params"] == original_inbox.meta["params"]
    assert unchanged_inbox.meta["event_queue"] == [inbox_fifo]


@pytest.mark.parametrize("event", ["source.inbox", "task.create"])
def test_competing_event_heads_keep_chronology_within_their_class(admission, event):
    later = waiting("Tasks/alpha", event=event, triggered="2026-09-02T00:00:00")
    earlier = waiting("Tasks/zeta", event=event, triggered="2026-09-01T00:00:00")
    assert [note.ref for note in scheduler.due_tasks()] == [earlier.ref, later.ref]


def test_pending_inbox_waits_for_active_link_then_precedes_its_next_fifo_head(admission, monkeypatch):
    link = waiting("Tasks/link", event="task.create")
    queue = [
        {"event": "task.create", "activation_key": "later-link-1"},
        {"event": "task.create", "activation_key": "later-link-2"},
    ]
    for params in queue:
        scheduler.enqueue_event(link, params)
    original = vault.load_note(link.path)
    calls = []

    async def exercise():
        gate = asyncio.Event()
        install_executor(monkeypatch, gate, calls)
        scheduler._launch_due_tasks()
        active = next(iter(scheduler._background))
        await asyncio.sleep(0)
        inbox = waiting("Tasks/ingest", event="source.inbox", triggered="2026-09-02T00:00:00")
        scheduler._launch_due_tasks()
        assert scheduler._running == {link.ref}
        assert calls == [link.ref] and admission == [link.ref]
        assert not active.done() and not active.cancelling()
        still_running = vault.load_note(link.path)
        assert still_running.meta["params"] == original.meta["params"]
        assert still_running.meta["event_queue"] == queue
        assert vault.load_note(inbox.path).meta["status"] == "pending"
        gate.set()
        await active
        scheduler._launch_due_tasks()
        assert scheduler._running == {inbox.ref}
        await asyncio.gather(*scheduler._background)
        assert calls == [link.ref, inbox.ref]
        remaining = vault.load_note(link.path)
        assert remaining.meta["status"] == "pending"
        assert remaining.meta["params"] == queue[0]
        assert remaining.meta["event_queue"] == queue[1:]

    asyncio.run(exercise())


def test_periodic_work_keeps_actual_cron_due_order(admission):
    later = waiting("Tasks/audit", schedule="* * * * *")
    earlier = waiting("Tasks/z-check", schedule="* * * * *")
    scheduler._last_fired[later.ref] = datetime(2026, 9, 2).timestamp()
    scheduler._last_fired[earlier.ref] = datetime(2026, 9, 1).timestamp()
    assert [note.ref for note in scheduler.due_tasks()] == [earlier.ref, later.ref]


def test_completed_old_event_metadata_does_not_gain_commitment_priority(admission):
    old = waiting("Tasks/audit", event="task.create", schedule="* * * * *")
    vault.update_status(old, "completed")
    active = waiting("Tasks/ingest", event="source.inbox")
    assert [note.ref for note in scheduler.due_tasks()] == [active.ref, old.ref]


def test_new_event_followup_runs_before_overdue_periodic_after_owner_finishes(admission, monkeypatch):
    periodic = waiting("Tasks/audit", schedule="* * * * *")
    direct = vault.load_note("Tasks/research/question.md")
    ingest = vault.load_note("Tasks/ingest.md")
    calls = []

    async def exercise():
        gate = asyncio.Event()

        def finish(note):
            if note.ref == direct.ref:
                scheduler.enqueue_event(ingest, {"event": "source.inbox", "activation_key": "actual-new-handoff"})

        install_executor(monkeypatch, gate, calls, finish)
        owner = scheduler.launch(direct)
        await asyncio.sleep(0)
        scheduler._launch_due_tasks()
        assert scheduler._running == {direct.ref}
        gate.set()
        await owner
        scheduler._launch_due_tasks()
        assert scheduler._running == {ingest.ref}
        assert periodic.ref not in scheduler._running
        await asyncio.gather(*scheduler._background)
        assert calls == [direct.ref, ingest.ref]
        assert vault.load_note(periodic.path).meta["status"] == "pending"
        assert scheduler._last_fired[periodic.ref] == 1.0

    asyncio.run(exercise())


def test_unprepared_head_does_not_consume_free_capacity(admission, monkeypatch):
    blocked = waiting("Tasks/ingest", event="source.inbox")
    ready = waiting("Tasks/link", event="task.create", triggered="2026-09-02T00:00:00")
    monkeypatch.setattr(scheduler, "prepare_task", lambda note: note.ref != blocked.ref)
    calls = []

    async def exercise():
        gate = asyncio.Event()
        gate.set()
        install_executor(monkeypatch, gate, calls)
        scheduler._launch_due_tasks()
        assert scheduler._running == {ready.ref}
        await asyncio.gather(*scheduler._background)

    asyncio.run(exercise())
    assert calls == [ready.ref]


def test_resource_wait_remains_pending_and_does_not_reserve_slot(admission, monkeypatch):
    inbox = waiting("Tasks/ingest", event="source.inbox")
    ready = waiting("Tasks/link", event="task.create", triggered="2026-09-02T00:00:00")
    monkeypatch.setattr(scheduler, "_resources_allow", lambda note, _model=None: note.ref != inbox.ref)
    calls = []

    async def exercise():
        gate = asyncio.Event()
        gate.set()
        install_executor(monkeypatch, gate, calls)
        scheduler._launch_due_tasks()
        assert scheduler._running == {ready.ref} and admission == [ready.ref]
        await asyncio.gather(*scheduler._background)

    asyncio.run(exercise())
    assert calls == [ready.ref]
    assert vault.load_note(inbox.path).meta["status"] == "pending"
    assert vault.load_note(inbox.path).meta["params"] == inbox.meta["params"]
    assert inbox.ref not in scheduler._last_fired


def test_foreground_arrival_after_admission_prevents_execution(admission, monkeypatch):
    pending = waiting("Tasks/link", event="task.create")
    calls = []

    async def exercise():
        gate = asyncio.Event()
        gate.set()
        install_executor(monkeypatch, gate, calls)
        scheduler._launch_due_tasks()
        assert scheduler._running == {pending.ref}
        async with scheduler.foreground_admission("conversation"):
            await asyncio.gather(*scheduler._background)
        assert scheduler._running == set()

    asyncio.run(exercise())
    assert calls == []
    assert vault.load_note(pending.path).meta["status"] == "pending"
    assert pending.ref not in scheduler._last_fired


def test_zero_configured_capacity_does_not_claim_tasks_or_continuations(admission, monkeypatch):
    monkeypatch.setattr(CONFIG, "concurrency", 0)
    waiting("Tasks/link", event="task.create")
    monkeypatch.setattr(scheduler.INDEX, "ready_continuations", lambda: pytest.fail("zero capacity must not claim a continuation"))
    assert scheduler._claim_ready_continuation() is None
    scheduler._launch_due_tasks()
    assert scheduler._running == set() and not scheduler._background
    assert admission == []
