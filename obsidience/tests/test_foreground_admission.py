"""Foreground admission exercises the real executor without live effects."""

from __future__ import annotations

import asyncio

import pytest

from obsidience.harness.execution import executor, scheduler
from obsidience.harness.knowledge import vault
from obsidience.harness.realtime.runtime import RUNTIME
from obsidience.tests.test_execution_cancellation import execution  # noqa: F401
from obsidience.tests.test_scheduler_interactive_provenance import ledger  # noqa: F401


def test_nested_admission_and_cancel_release_gate_without_unpausing_outer(monkeypatch):
    monkeypatch.setattr(scheduler, "_foreground_admissions", 0)
    demand = asyncio.Event()
    monkeypatch.setattr(scheduler, "_autonomous_interruptions", {"Tasks/research/news": demand})

    async def exercise():
        async with scheduler.foreground_admission("conversation"):
            assert demand.is_set()
            assert scheduler.foreground_pending()
            with pytest.raises(RuntimeError):
                async with scheduler.foreground_admission("realtime.start"):
                    raise RuntimeError("isolated startup failure")
            assert scheduler.foreground_pending()
        assert not scheduler.foreground_pending()

        entered = asyncio.Event()

        async def canceled():
            async with scheduler.foreground_admission("conversation"):
                entered.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(canceled())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not scheduler.foreground_pending()

    asyncio.run(exercise())


def test_claim_waiting_for_slot_cannot_start_after_foreground_arrives(ledger, monkeypatch):
    monkeypatch.setattr(RUNTIME, "scheduler_paused", lambda: False)
    monkeypatch.setattr(scheduler, "_foreground_admissions", 0)
    task = vault.load_note("Tasks/link.md")
    vault.update_status(task, "pending")
    task = vault.load_note(task.path)
    calls = []

    async def unexpected(*_args, **_kwargs):
        calls.append(True)

    monkeypatch.setattr(scheduler, "run_task", unexpected)

    async def exercise():
        scheduler._claim(task)
        async with scheduler.foreground_admission("conversation"):
            await scheduler._run_claimed(task)

    asyncio.run(exercise())
    assert calls == []
    assert scheduler._running == set()
    assert vault.load_note(task.path).meta["status"] == "pending"
    assert task.ref not in scheduler._last_fired


def test_explicit_launch_reports_pause_before_claim_instead_of_false_started(ledger):
    task = vault.load_note("Tasks/link.md")
    with pytest.raises(RuntimeError, match="paused"):
        scheduler.launch(task)
    assert scheduler._running == set()


def test_interrupted_bound_occurrence_and_later_fifo_are_not_replayed_by_cron(ledger, monkeypatch):
    monkeypatch.setattr(RUNTIME, "scheduler_paused", lambda: False)
    task = vault.load_note("Tasks/link.md")
    first = {"event": "task.create", "activation_key": "first"}
    later = {"event": "task.create", "activation_key": "later"}
    scheduler.enqueue_event(task, first)
    scheduler.enqueue_event(task, later)
    vault.update_status(task, "failed", {"last_run": "interrupted-run", "schedule": "* * * * *"})
    ledger.record_run(
        id="interrupted-run", task_ref=task.ref, agent="test", started=1.0, finished=2.0,
        status="interrupted", summary="Retain committed effects.", trace="[]",
    )
    scheduler._last_fired[task.ref] = 1.0
    assert scheduler.due_tasks() == []
    current = vault.load_note(task.path)
    assert current.meta["params"] == first
    assert current.meta["event_queue"] == [later]


def test_scheduler_registers_only_autonomous_specialist_for_interruption(ledger, monkeypatch):
    from obsidience.tests.test_scheduler_interactive_provenance import delegate

    monkeypatch.setattr(RUNTIME, "scheduler_paused", lambda: False)
    monkeypatch.setattr(scheduler, "_autonomous_interruptions", {})
    # Model admission measures live GPU memory; this test covers interruption only.
    monkeypatch.setattr(scheduler, "_resource_error", lambda *_args, **_kwargs: None)
    calls = []

    async def run(note, **kwargs):
        calls.append((note.ref, kwargs.get("interruption_event")))
        async with scheduler.foreground_admission("conversation"):
            if kwargs.get("interruption_event") is not None:
                assert kwargs["interruption_event"].is_set()

    monkeypatch.setattr(scheduler, "run_task", run)
    autonomous = vault.load_note("Tasks/link.md")
    interactive, _receipt = delegate(ledger)

    async def exercise():
        await scheduler._run(autonomous)
        await scheduler._run(interactive)

    asyncio.run(exercise())
    assert calls[0][1] is not None
    assert calls[1][1] is None
    assert scheduler._autonomous_interruptions == {}
