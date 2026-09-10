"""Foreground admission exercises the real executor without live effects."""

from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace as NS

import pytest

from obsidience.harness.execution import executor, scheduler
from obsidience.harness.knowledge import vault
from obsidience.harness.realtime.runtime import RUNTIME
from obsidience.tests.test_execution_cancellation import execution  # noqa: F401
from obsidience.tests.test_scheduler_interactive_provenance import ledger  # noqa: F401


def test_foreground_interrupts_and_joins_only_provider(execution, monkeypatch):
    async def exercise():
        demand, entered, joined = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def provider(*_args, **_kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                joined.set()

        monkeypatch.setattr(executor.llm, "chat", provider)
        turn = asyncio.create_task(execution.run(interruption_event=demand))
        await asyncio.wait_for(entered.wait(), 2)
        demand.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(turn, 2)
        assert joined.is_set()
        assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]

    asyncio.run(exercise())
    assert execution.calls == []
    assert execution.releases == 1
    assert execution.statuses == ["running", "failed"]
    assert len(execution.records) == 1
    row = execution.records[0]
    assert row["status"] == "interrupted"
    assert json.loads(row["trace"])[-1] == {
        "interruption_reason": "foreground_admission", "must_not_replay": True,
    }


@pytest.mark.parametrize("tool", ["window.place", "task.complete"])
def test_in_flight_tool_finishes_before_yield_and_accepted_completion_wins(
    execution, monkeypatch, tool,
):
    async def exercise():
        demand, entered = asyncio.Event(), asyncio.Event()
        release = threading.Event()
        loop = asyncio.get_running_loop()
        original = executor.execute_capability

        async def provider(*_args, **_kwargs):
            return NS(content=json.dumps({"tool": tool, "args": {
                "status": "completed", "summary": "Done.",
            } if tool == "task.complete" else {}}), prompt_tokens=100)

        def slow_tool(name, args, ctx):
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(3)
            return original(name, args, ctx)

        monkeypatch.setattr(executor.llm, "chat", provider)
        monkeypatch.setattr(executor, "execute_capability", slow_tool)
        turn = asyncio.create_task(execution.run(interruption_event=demand))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            demand.set()
            await asyncio.sleep(0)
            assert not turn.done(), "foreground admission must not cancel a Tool thread"
        finally:
            release.set()
        if tool == "task.complete":
            assert (await asyncio.wait_for(turn, 2))["status"] == "completed"
        else:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(turn, 2)

    asyncio.run(exercise())
    assert len(execution.calls) == 1
    assert execution.calls[0][0] == tool
    assert execution.releases == 1
    row = execution.records[0]
    if tool == "window.place":
        assert row["status"] == "interrupted"
        effects = [entry for entry in json.loads(row["trace"]) if entry.get("tool") == tool]
        assert len(effects) == 1
        assert json.loads(effects[0]["obs"])["effect_applied"] is True
        assert "outcome is unknown" not in row["trace"]
    else:
        assert row["status"] == "completed"
        assert "foreground_admission" not in row["trace"]


def test_pending_demand_prevents_inference_and_lease_acquisition(execution):
    async def exercise():
        demand = asyncio.Event()
        demand.set()
        with pytest.raises(asyncio.CancelledError):
            await execution.run(interruption_event=demand)

    asyncio.run(exercise())
    assert execution.calls == []
    assert execution.releases == 0
    assert execution.records[0]["status"] == "interrupted"


def test_external_cancellation_joins_provider_and_demand_waiter(execution, monkeypatch):
    async def exercise():
        demand, entered, joined = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def provider(*_args, **_kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                joined.set()

        monkeypatch.setattr(executor.llm, "chat", provider)
        turn = asyncio.create_task(execution.run(interruption_event=demand))
        await asyncio.wait_for(entered.wait(), 2)
        turn.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(turn, 2)
        assert joined.is_set()
        assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]

    asyncio.run(exercise())
    assert execution.records[0]["status"] == "interrupted"
    assert execution.releases == 1


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
