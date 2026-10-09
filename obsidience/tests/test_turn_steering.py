"""Exact-turn clarifications at real executor decision and Tool boundaries."""
from __future__ import annotations

import asyncio
import copy
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS

import pytest

# The imported runtime constructs its default ConversationStore at import time.
# Isolate that first construction before pytest's per-test ledger fixture exists.
from obsidience.harness.config import CONFIG

_bootstrap = TemporaryDirectory(prefix="obsidience-steering-tests-")
_previous_db = CONFIG.db_path
CONFIG.db_path = Path(_bootstrap.name) / "bootstrap.sqlite3"
try:
    from obsidience.harness.conversation.runtime import ConversationRuntime, TurnSteering
    from obsidience.harness.conversation.store import ConversationStore
    from obsidience.harness.execution import executor
    from obsidience.tests.test_execution_cancellation import execution  # noqa: F401
finally:
    CONFIG.db_path = _previous_db


OBJECTIVE = "Move the fixture application to the requested Surface."


@pytest.fixture
def scene(monkeypatch, isolated_task_ledger, tmp_path):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    store = ConversationStore(isolated_task_ledger)
    runtime = ConversationRuntime(store)
    state = NS(store=store, runtime=runtime, requests=[], calls=[], events=[],
               provider_hook=None, tool_hook=None, releases=0)
    model = NS(id="isolated", label="Isolated", capabilities=("text", "tools"))
    state.allowed = ["window.place", "task.complete"]

    @asynccontextmanager
    async def lease(_model):
        try:
            yield model
        finally:
            state.releases += 1

    def execute(name, args, ctx):
        state.calls.append((name, copy.deepcopy(args)))
        if state.tool_hook:
            result = state.tool_hook(name, args, ctx)
            if result is not None:
                return result
        if name == "task.complete":
            return {"accepted": True, "status": "completed", "summary": "Done"}
        return {"status": "completed", "effect_applied": True, "must_not_replay": True}

    monkeypatch.setattr(executor.model_runtime, "configured_spec", lambda _: model)
    monkeypatch.setattr(executor.model_runtime, "lease", lease)
    monkeypatch.setattr(executor, "execute_capability", execute)

    async def execute_async(name, args, ctx):
        # The executor dispatches through the async registry entry; never reach real Tools.
        return await asyncio.to_thread(execute, name, args, ctx)

    monkeypatch.setattr(executor, "execute_capability_async", execute_async)
    monkeypatch.setattr(executor.action_trace, "emit", lambda *args: state.events.append(args))

    async def initialize():
        owner = await store.append(role="user", source="text", text=OBJECTIVE)
        state.inbox = TurnSteering(owner["id"], runtime._publish_active_turn)
        runtime._steering = state.inbox
        state.inbox.activate("fixture-run")
        state.ctx = {"objective": OBJECTIVE, "params": {"request": OBJECTIVE},
                     "run_id": "fixture-run", "_steering": state.inbox}
        state.messages = [{"role": "system", "content": "Exact assigned Tool authority"},
                          {"role": "user", "content": OBJECTIVE}]
        return owner

    state.initialize = initialize
    return state


@pytest.mark.parametrize("invalid", ["wrong_turn", "closed", "finished", "absent"])
def test_stale_steering_target_never_appends_a_public_turn(scene, invalid):
    async def run():
        owner = await scene.initialize()
        task = asyncio.create_task(asyncio.Event().wait())
        scene.runtime._turn_task = task
        if invalid == "closed":
            scene.inbox.close()
        elif invalid == "finished":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        elif invalid == "absent":
            scene.runtime._steering = None
        original = scene.store.history()
        try:
            with pytest.raises(ValueError, match="no longer accepting"):
                await scene.runtime.steer("Clarification", expected_turn_id=(
                    "different-turn" if invalid == "wrong_turn" else owner["id"]))
            assert scene.store.history() == original
            assert not scene.inbox.pending
        finally:
            await scene.runtime.cancel()

    asyncio.run(run())


def test_clarification_limits_count_applied_and_pending_without_truncation(scene):
    async def run():
        owner = await scene.initialize()
        scene.runtime._turn_task = asyncio.create_task(asyncio.Event().wait())
        try:
            for number in range(8):
                text = str(number) + "x" * 1999
                result = await scene.runtime.steer(text, expected_turn_id=owner["id"])
                assert result["active_turn_id"] == owner["id"]
                if number == 3:
                    assert len(scene.inbox.take()) == 4
            before = scene.store.history()
            with pytest.raises(ValueError, match="clarification limit"):
                await scene.runtime.steer("ninth", expected_turn_id=owner["id"])
            for bad in ("", "   ", "x" * 2001):
                with pytest.raises(ValueError, match="1–2000"):
                    await scene.runtime.steer(bad, expected_turn_id=owner["id"])
            assert scene.store.history() == before
            assert len(scene.inbox.applied) == len(scene.inbox.pending) == 4
            assert [len(turn["text"]) for turn in before[1:]] == [2000] * 8
            assert all(turn["run_id"] == "fixture-run" for turn in before[1:])
        finally:
            await scene.runtime.cancel()

    asyncio.run(run())


@pytest.mark.parametrize("ending", ["completion", "STOP"])
def test_task_closing_during_append_saves_message_but_never_queues_it(scene, ending):
    async def run():
        await scene.initialize()
        scene.runtime._turn_task = asyncio.create_task(asyncio.Event().wait())
        original = scene.store.history()
        # Exercise the real Store lock instead of replacing append with a stub.
        async with scene.store._lock:
            submission = asyncio.create_task(scene.runtime.steer(
                "Received while completion was settling", expected_turn_id=scene.inbox.turn_id))
            await asyncio.sleep(0)
            assert not submission.done()
            if ending == "STOP":
                await scene.runtime.cancel(reason="STOP")
            else:
                scene.inbox.close()
        try:
            with pytest.raises(ValueError, match="saved but not applied"):
                await submission
            saved = scene.store.history()
            assert len(saved) == len(original) + 1
            assert saved[-1]["text"] == "Received while completion was settling"
            assert not scene.inbox.pending and not scene.inbox.applied
            assert not scene.calls
        finally:
            await scene.runtime.cancel()

    asyncio.run(run())


