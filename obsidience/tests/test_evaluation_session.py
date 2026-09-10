"""Frozen trials use the actual executor loop without live dispatch or receipts."""

from __future__ import annotations

import asyncio
import copy
import json
import sys
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from obsidience.harness.capabilities.source import read as source_read
from obsidience.harness.capabilities.task import complete
from obsidience.harness.execution import executor


def action(name, **args):
    return {"tool": name, "args": args}


@pytest.fixture
def trial_runtime(monkeypatch):
    model = SimpleNamespace(id="fixture-model", capabilities=("text", "tools"))
    task = SimpleNamespace(ref="Tasks/check", title="Check", kind="task", meta={})
    state = SimpleNamespace(requests=[], emissions=[], leases=0, releases=0, calls=[], replies=[],
                            context={}, messages=[], chat_impl=None, handle_impl=None)

    def forbidden(*_args, **_kwargs):
        pytest.fail("a simulated action reached a live owner")

    for name in ("execute_capability", "execute_capability_async", "update_status"):
        monkeypatch.setattr(executor, name, forbidden)
    monkeypatch.setattr(source_read, "precondition_error", forbidden)
    for name in ("execute", "computer_completion_evidence", "computer_request_target_error"):
        monkeypatch.setattr(complete, name, forbidden)
    for name in ("begin_tool_run", "begin_tool_call", "finish_tool_call", "record_run",
                 "bind_continuation_handoff"):
        monkeypatch.setattr(executor.INDEX, name, forbidden)

    @asynccontextmanager
    async def lease(_spec):
        state.leases += 1
        try:
            yield model
        finally:
            state.releases += 1

    async def chat(messages, **kwargs):
        state.requests.append((copy.deepcopy(messages), kwargs))
        if state.chat_impl is not None:
            return await state.chat_impl(messages, **kwargs)
        reply = state.replies.pop(0)
        return executor.llm.ChatReply(
            content=reply if isinstance(reply, str) else json.dumps(reply),
            prompt_tokens=42, finish_reason="stop", completion_tokens=8,
        )

    async def handle(name, args):
        state.calls.append((name, copy.deepcopy(args)))
        if state.handle_impl is not None:
            return await state.handle_impl(name, args)
        return {"done": name == "task.complete", "observation": "Frozen fixture result",
                **({"status": "completed", "summary": "Simulated result"} if name == "task.complete" else {})}

    monkeypatch.setattr(executor.model_runtime, "configured_spec", lambda _id: model)
    monkeypatch.setattr(executor.model_runtime, "lease", lease)
    monkeypatch.setattr(executor.llm, "chat", chat)
    monkeypatch.setattr(executor.action_trace, "emit", lambda *args: state.emissions.append(args))
    monkeypatch.setattr(executor.action_trace, "latency", lambda *_a, **_k: None)
    state.evaluation = SimpleNamespace(max_steps=4, handle=handle)
    state.model, state.task = model, task

    async def run(replies, *, allowed=None, context=None, interruption_event=None):
        state.replies = list(replies)
        state.context = {} if context is None else context
        state.messages = [{"role": "system", "content": "Frozen packet"},
                          {"role": "user", "content": "Frozen objective"}]
        return await executor._execute_session(
            task, model, state.messages, allowed if allowed is not None else ["harness.status", "task.complete"],
            state.context, "Heimdall", "low", interruption_event, evaluation=state.evaluation,
        )

    state.run = run
    return state


@pytest.mark.parametrize("tool", [
    "source.read", "harness.status", "source.handoff", "task.create", "vault.propose",
    "computer.act", "task.complete", "model.configure",
])
def test_every_authorized_action_stays_in_frozen_handler(trial_runtime, tool):
    state = trial_runtime
    replies = [action(tool, fixture="exact")]
    if tool != "task.complete":
        replies.append(action("task.complete", status="completed", summary="Fixture finished"))
    trace, status, _summary = asyncio.run(state.run(replies, allowed=[tool, "task.complete"]))
    assert status == "completed"
    assert state.calls[0] == (tool, {"fixture": "exact"})
    assert all(row["simulated"] is True for row in trace)
    assert state.leases == state.releases == 1
    assert "_receipt_covered" not in state.context
    assert all(row[1].startswith("Simulation · ") for row in state.emissions)
    assert all(row[3]["payload"]["simulated"] is True for row in state.emissions)
    assert all(kwargs["model"] is state.model and kwargs["reasoning_effort"] == "low"
               for _messages, kwargs in state.requests)


def test_unauthorized_action_fails_without_handler_or_live_fallback(trial_runtime):
    trace, status, summary = asyncio.run(trial_runtime.run([action("application.launch", app="unexpected")]))
    assert status == "failed" and "not authorized" in summary
    assert not trial_runtime.calls
    assert trace == [{"tool": "application.launch", "args": {"app": "unexpected"},
                      "simulated": True, "obs": summary, "not_dispatched": True}]
    assert trial_runtime.releases == 1


@pytest.mark.parametrize("context", [
    {"_receipt_covered": True}, {"_receipt_covered": False}, {"_tool_receipt_articles": {}},
    {"run_id": "live"}, {"task": "Tasks/check"}, {"params": {}}, {"event": "scheduled"},
    {"_steering": object()}, {"trace": [{"tool": "previous.effect"}]}, {"trace": None},
])
def test_live_context_and_imported_trace_rejected_before_model_admission(trial_runtime, context):
    with pytest.raises(ValueError, match="fresh context"):
        asyncio.run(trial_runtime.run([], context=context))
    assert trial_runtime.leases == 0 and not trial_runtime.requests


@pytest.mark.parametrize("budget", [True, 0, -1, 1.5, "2", 100000])
def test_invalid_budget_rejected_before_model_admission(trial_runtime, budget):
    trial_runtime.evaluation.max_steps = budget
    with pytest.raises(ValueError, match="decision budget"):
        asyncio.run(trial_runtime.run([]))
    assert trial_runtime.leases == 0


def test_trial_budget_and_frozen_observations_use_same_context_loop(trial_runtime):
    state = trial_runtime
    original_budget = executor.CONFIG.max_steps
    state.evaluation.max_steps = 2
    trace, status, summary = asyncio.run(state.run([action("harness.status"), action("harness.status")]))
    assert status == "failed" and "decision budget" in summary
    assert len(trace) == len(state.requests) == 2
    first, second = state.requests
    assert "2 model decisions remain" in first[0][-1]["content"]
    assert second[0][-1]["content"].startswith("Observation:\nFrozen fixture result")
    assert "1 model decision remains" in second[0][-1]["content"]
    assert first[1]["task_context"] is second[1]["task_context"]
    assert state.context["prompt_tokens"] == 42
    assert executor.CONFIG.max_steps == original_budget


def test_frozen_read_envelopes_remain_recoverable_in_task_context(trial_runtime):
    state = trial_runtime
    body = "Frozen evidence. " * 100
    page = ("source://00000000-0000-0000-0000-000000000001 · Fixture\n"
            "SHA-256: sha256:" + "a" * 64 + "\n"
            f"Characters 0-{len(body)} of {len(body)}. End of Source.\n\n" + body)

    async def handle(name, _args):
        return {"done": name == "task.complete", "observation": page if name == "source.read" else "Done"}

    state.handle_impl = handle
    asyncio.run(state.run([action("source.read"), action("task.complete")], allowed=["source.read", "task.complete"]))
    task_context = state.requests[-1][1]["task_context"]
    assert len(task_context.pages) == 1
    assert next(iter(task_context.pages.values())).body == body


@pytest.mark.parametrize("result", [
    None, {}, {"done": 1, "observation": "x"}, {"done": True, "observation": []},
    {"done": True, "observation": "x", "status": "successful"},
    {"done": True, "observation": "x", "status": []},
    {"done": True, "observation": "x", "summary": 7},
    {"done": True, "observation": "x", "live_dispatch": True},
])
def test_malformed_handler_result_fails_closed_and_releases_lease(trial_runtime, result):
    async def handle(_name, _args):
        return result

    trial_runtime.handle_impl = handle
    with pytest.raises(ValueError, match="invalid result"):
        asyncio.run(trial_runtime.run([action("task.complete")]))
    assert trial_runtime.releases == 1


def test_handler_error_propagates_without_live_fallback(trial_runtime):
    async def handle(_name, _args):
        raise ValueError("No exact frozen response exists")

    trial_runtime.handle_impl = handle
    with pytest.raises(ValueError, match="exact frozen response"):
        asyncio.run(trial_runtime.run([action("harness.status")]))
    assert trial_runtime.releases == 1
    assert "obs" not in trial_runtime.context["trace"][-1]


def test_handler_cannot_rewrite_the_recorded_model_action(trial_runtime):
    async def handle(_name, args):
        args["nested"]["value"] = "changed"
        return {"done": True, "observation": "Frozen result"}

    trial_runtime.handle_impl = handle
    trace, _status, _summary = asyncio.run(trial_runtime.run([
        action("task.complete", nested={"value": "original"}),
    ]))
    assert trace[0]["args"] == {"nested": {"value": "original"}}


def test_invalid_model_actions_use_existing_protocol_recovery_budget(trial_runtime):
    trace, status, summary = asyncio.run(trial_runtime.run(["invalid"] * 3))
    assert status == "failed" and "three consecutive" in summary
    assert len(trace) == len(trial_runtime.requests) == 3
    assert not trial_runtime.calls and trial_runtime.releases == 1
    assert "No valid response object" in trial_runtime.requests[1][0][-1]["content"]


def test_provider_failure_is_failed_trial_without_fabricated_action(trial_runtime):
    async def chat(*_args, **_kwargs):
        raise TimeoutError("provider fixture timed out")

    trial_runtime.chat_impl = chat
    trace, status, summary = asyncio.run(trial_runtime.run([]))
    assert status == "failed" and "timed out" in summary
    assert not trace and not trial_runtime.calls and trial_runtime.releases == 1


@pytest.mark.parametrize("during", ["provider", "handler", "lease"])
def test_stop_cancels_frozen_trial_and_releases_model(trial_runtime, monkeypatch, during):
    state = trial_runtime

    async def exercise():
        entered = asyncio.Event()
        closed = asyncio.Event()

        async def wait(*_args, **_kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()

        if during == "provider":
            state.chat_impl = wait
        elif during == "handler":
            state.handle_impl = wait
        else:
            @asynccontextmanager
            async def lease(_model):
                await wait()
                yield state.model
            monkeypatch.setattr(executor.model_runtime, "lease", lease)
        pending = asyncio.create_task(state.run([action("task.complete")]))
        await asyncio.wait_for(entered.wait(), 1)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(pending, 1)
        assert closed.is_set()

    asyncio.run(exercise())
    assert state.releases == (0 if during == "lease" else 1)
    if during == "handler":
        assert state.context["trace"][-1]["interrupted"] is True


def test_foreground_request_cancels_provider_without_simulated_action(trial_runtime):
    state = trial_runtime

    async def exercise():
        interruption, entered, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()

        async def chat(*_args, **_kwargs):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                closed.set()

        state.chat_impl = chat
        pending = asyncio.create_task(state.run([], interruption_event=interruption))
        await asyncio.wait_for(entered.wait(), 1)
        interruption.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(pending, 1)
        assert closed.is_set()

    asyncio.run(exercise())
    assert not state.calls and state.releases == 1


def test_generate_activation_uses_only_controller_public_refinement_context(monkeypatch):
    public = {"objective": "Propose a bounded Runbook revision", "baseline_sha256": "a" * 64}
    seen = []

    def activation_context(case):
        seen.append(case)
        return public

    monkeypatch.setitem(sys.modules, "obsidience.harness.execution.refinement",
                        SimpleNamespace(activation_context=activation_context))
    task = SimpleNamespace(ref="Tasks/generate/runbook", title="Runbook")
    binding = executor.build_activation_binding(task, [], {"refinement_case": "fixed-case"})
    assert seen == ["fixed-case"]
    assert binding.objective == public["objective"]
    assert binding.bindings["refinement"] is public
    task.ref = "Tasks/other"
    ordinary = executor.build_activation_binding(task, [], {"refinement_case": "unrelated"})
    assert seen == ["fixed-case"] and "refinement" not in ordinary.bindings


def test_ordinary_capability_receives_private_foreground_event(trial_runtime, monkeypatch):
    state = trial_runtime
    interruption = asyncio.Event()
    state.replies = [action("harness.status"), action("task.complete")]
    context = {"task": "Tasks/check"}
    seen = []

    def execute(name, _args, ctx):
        seen.append(ctx.get("_foreground_interruption_event"))
        if name == "task.complete":
            return {"accepted": True, "status": "completed", "summary": "Finished"}
        return "Healthy"

    monkeypatch.setattr(executor, "execute_capability", execute)
    monkeypatch.setattr(source_read, "precondition_error", lambda *_a: None)
    monkeypatch.setattr(complete, "computer_request_target_error", lambda *_a: None)
    monkeypatch.setattr(complete, "computer_completion_evidence", lambda *_a, **_k: None)
    result = asyncio.run(executor._execute_session(
        state.task, state.model, [], ["harness.status", "task.complete"], context,
        "Heimdall", "low", interruption,
    ))
    assert result[1] == "completed" and seen == [interruption, interruption]
    assert "_foreground_interruption_event" not in context
