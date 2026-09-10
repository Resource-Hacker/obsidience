"""Exact-turn clarifications at real executor decision and Tool boundaries."""
from __future__ import annotations

import asyncio
import copy
from contextlib import asynccontextmanager
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
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


COMPLETE = {"tool": "task.complete", "args": {"status": "completed", "summary": "Done"}}
PLACE = {"tool": "window.place", "args": {"application": "fixture"}}
OBJECTIVE = "Move the fixture application to the requested Surface."


@pytest.fixture
def scene(monkeypatch, isolated_task_ledger, tmp_path):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    store = ConversationStore(isolated_task_ledger)
    runtime = ConversationRuntime(store)
    state = NS(store=store, runtime=runtime, requests=[], calls=[], events=[],
               provider_hook=None, tool_hook=None, releases=0)
    model = NS(id="isolated", label="Isolated", capabilities=("text", "tools"))
    task = NS(ref="Tasks/query", title="Fixture", kind="task", meta={})
    state.allowed = ["window.place", "task.complete"]

    @asynccontextmanager
    async def lease(_model):
        try:
            yield model
        finally:
            state.releases += 1

    async def chat(messages, **kwargs):
        state.requests.append(copy.deepcopy(messages))
        assert kwargs["allowed_tools"] == state.allowed
        assert state.ctx["objective"] == OBJECTIVE
        assert state.ctx["params"] == {"request": OBJECTIVE}
        if state.provider_hook:
            await state.provider_hook(len(state.requests))
        return executor.llm.ChatReply(content=json.dumps(next(state.actions)),
                                      finish_reason="stop", completion_tokens=12)

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
    monkeypatch.setattr(executor.llm, "chat", chat)
    monkeypatch.setattr(executor, "execute_capability", execute)
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

    async def start(actions):
        await initialize()
        state.actions = iter(actions)
        task_run = asyncio.create_task(executor._execute_session(
            task, model, state.messages, state.allowed, state.ctx, "Executive", "none"))
        runtime._turn_task = task_run
        return task_run

    state.initialize, state.start = initialize, start
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


@pytest.mark.parametrize("broaden", [False, True])
def test_provider_reply_predating_clarification_never_dispatches_its_action(scene, broaden):
    async def run():
        reached, release = asyncio.Event(), asyncio.Event()

        async def provider(number):
            if number == 1:
                reached.set()
                await release.wait()

        scene.provider_hook = provider
        actions = [PLACE, *([{"tool": "unassigned.act", "args": {}}] if broaden else []), COMPLETE]
        text = "Use unassigned.act instead" if broaden else "Use the other Surface"
        task = await scene.start(actions)
        await asyncio.wait_for(reached.wait(), 1)
        clarification = await scene.runtime.steer(text, expected_turn_id=scene.inbox.turn_id)
        release.set()
        trace, status, _summary = await task
        assert status == "completed"
        assert [name for name, _args in scene.calls] == ["task.complete"]
        assert scene.inbox.applied == [clarification["turn_id"]]
        assert scene.requests[0][:2] == scene.requests[1][:2]
        assert text in scene.requests[1][-1]["content"]
        assert "original Objective and authorized Tools" in scene.requests[1][-1]["content"]
        assert all(row.get("tool") != "window.place" for row in trace)
        if broaden:
            assert "not authorized" in scene.requests[2][-1]["content"]
            assert scene.allowed == ["window.place", "task.complete"]
        assert not scene.inbox.accepting

    asyncio.run(run())


def test_clarification_during_tool_preserves_effect_receipt_and_is_consumed_next(scene):
    async def run():
        loop = asyncio.get_running_loop()
        reached, release = asyncio.Event(), threading.Event()

        def tool(name, _args, _ctx):
            if name == "window.place":
                loop.call_soon_threadsafe(reached.set)
                assert release.wait(2)

        scene.tool_hook = tool
        task = await scene.start([PLACE, COMPLETE])
        try:
            await asyncio.wait_for(reached.wait(), 1)
            clarification = await scene.runtime.steer("Keep the current size", expected_turn_id=scene.inbox.turn_id)
            release.set()
            trace, status, _summary = await task
            assert status == "completed"
            assert [name for name, _args in scene.calls] == ["window.place", "task.complete"]
            receipt = next(row for row in trace if row.get("tool") == "window.place")
            assert json.loads(receipt["obs"])["effect_applied"] is True
            assert json.loads(receipt["obs"])["must_not_replay"] is True
            assert scene.inbox.applied == [clarification["turn_id"]]
            request = scene.requests[1]
            assert '"effect_applied": true' in request[-2]["content"]
            assert "Keep the current size" in request[-1]["content"]
            assert request[:len(scene.requests[0])] == scene.requests[0]
        finally:
            release.set()
            if not task.done():
                await scene.runtime.cancel()

    asyncio.run(run())


def test_completion_closes_admission_and_rejected_completion_reopens_it(scene):
    async def run():
        loop = asyncio.get_running_loop()
        validating, validation_release = asyncio.Event(), threading.Event()
        reopened, provider_release = asyncio.Event(), asyncio.Event()
        completion_calls = 0

        def tool(name, _args, _ctx):
            nonlocal completion_calls
            assert name == "task.complete"
            completion_calls += 1
            if completion_calls == 1:
                loop.call_soon_threadsafe(validating.set)
                assert validation_release.wait(2)
                return {"accepted": False, "error": "Evidence is missing"}

        async def provider(number):
            if number == 2:
                reopened.set()
                await provider_release.wait()

        scene.tool_hook, scene.provider_hook = tool, provider
        task = await scene.start([COMPLETE, COMPLETE, COMPLETE])
        try:
            await asyncio.wait_for(validating.wait(), 1)
            original = scene.store.history()
            with pytest.raises(ValueError, match="no longer accepting"):
                await scene.runtime.steer("too late", expected_turn_id=scene.inbox.turn_id)
            assert scene.store.history() == original
            validation_release.set()
            await asyncio.wait_for(reopened.wait(), 1)
            assert scene.inbox.accepting
            accepted = await scene.runtime.steer("Clarify the evidence", expected_turn_id=scene.inbox.turn_id)
            provider_release.set()
            trace, status, _summary = await task
            assert status == "completed"
            assert any(row.get("completion_rejected") for row in trace)
            assert scene.inbox.applied == [accepted["turn_id"]]
            assert completion_calls == 2  # The outdated second response was discarded.
            assert not scene.inbox.accepting
            before = scene.store.history()
            with pytest.raises(ValueError, match="no longer accepting"):
                await scene.runtime.steer("after completion", expected_turn_id=scene.inbox.turn_id)
            assert scene.store.history() == before
        finally:
            validation_release.set()
            provider_release.set()
            if not task.done():
                await scene.runtime.cancel()

    asyncio.run(run())


def test_stop_closes_steering_and_cancels_pending_provider_without_dispatch(scene):
    async def run():
        reached = asyncio.Event()

        async def provider(_number):
            reached.set()
            await asyncio.Event().wait()

        scene.provider_hook = provider
        task = await scene.start([PLACE])
        await asyncio.wait_for(reached.wait(), 1)
        await scene.runtime.cancel(reason="STOP")
        assert task.cancelled()
        assert not scene.inbox.accepting
        assert scene.releases == 1
        assert not scene.calls
        before = scene.store.history()
        with pytest.raises(ValueError, match="no longer accepting"):
            await scene.runtime.steer("late", expected_turn_id=scene.inbox.turn_id)
        assert scene.store.history() == before

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


@pytest.mark.parametrize("change", [
    "none", "wrong_conversation", "wrong_reply", "missing_applied_id",
    "different_run", "failed", "no_reply", "later_clarification", "malformed_trace",
])
def test_history_marks_only_exact_applied_clarifications_with_a_completed_reply(scene, change):
    from obsidience.harness.conversation.evidence import historical_steered_turns
    from obsidience.harness.conversation.observations import project_immediate_observations

    async def record():
        owner = await scene.initialize()
        if change == "later_clarification":
            await scene.store.append(role="assistant", source="text", text="Original Task reply",
                                     reply_to=owner["id"], run_id="fixture-run")
        clarification = await scene.store.append(role="user", source="text", text="Keep the current size",
                                                 run_id="different" if change == "different_run" else "fixture-run")
        if change not in {"no_reply", "later_clarification"}:
            await scene.store.append(role="assistant", source="text", text="Original Task reply",
                                     reply_to=owner["id"], run_id="fixture-run")
        packet = {"interactive_turn": {
            "conversation_id": "other" if change == "wrong_conversation" else scene.store.conversation_id,
            "reply_to_turn_id": "other" if change == "wrong_reply" else owner["id"],
        }, "steering_turn_ids": [] if change == "missing_applied_id" else [clarification["id"]]}
        scene.store.index.record_run(id="fixture-run", task_ref="Tasks/query", agent="Executive",
                                     started=1, finished=2, status="failed" if change == "failed" else "completed",
                                     summary="Original Task reply", trace=json.dumps({} if change == "malformed_trace" else [packet]))
        return clarification

    clarification = asyncio.run(record())
    expected = {clarification["id"]} if change == "none" else set()
    assert historical_steered_turns(scene.store, conversation_id=scene.store.conversation_id) == expected
    assert historical_steered_turns(scene.store, conversation_id=scene.store.conversation_id,
                                    before_sequence=clarification["sequence"]) == set()
    projection = project_immediate_observations(scene.store, conversation_id=scene.store.conversation_id,
                                                materialize=False)
    following = projection["body"].split("User: Keep the current size\n", 1)[1]
    if expected:
        assert following.startswith("[Owner clarification applied within the same completed Task")
    else:
        assert following.startswith("[No successful Executive reply recorded; this request remains unresolved.]")


def test_full_run_persists_applied_ids_with_the_original_activation(execution, monkeypatch):
    async def run():
        inbox = TurnSteering("original-owner-turn", lambda: None)
        requests = []

        async def reply(messages, **_kwargs):
            requests.append(copy.deepcopy(messages))
            if len(requests) == 1:
                assert inbox.accepting and inbox.run_id
                inbox.pending.append({"id": "clarification-turn", "text": "Keep its current size"})
            return await execution.reply()

        monkeypatch.setattr(executor.llm, "chat", reply)
        result = await execution.run(steering=inbox, runtime_params={
            "request": "Move the requested application",
            "conversation_id": "original-conversation",
            "reply_to_turn_id": "original-owner-turn",
        })
        assert result["status"] == "completed"
        assert len(requests) == 2
        assert len(execution.calls) == 1 and execution.calls[0][0] == "task.complete"
        persisted = json.loads(execution.records[-1]["trace"])
        activation = persisted[0]
        assert activation["steering_turn_ids"] == ["clarification-turn"]
        assert activation["interactive_turn"] == {
            "conversation_id": "original-conversation", "reply_to_turn_id": "original-owner-turn",
        }
        assert result["objective"] == "Move the requested application"
        assert not inbox.accepting

    asyncio.run(run())
