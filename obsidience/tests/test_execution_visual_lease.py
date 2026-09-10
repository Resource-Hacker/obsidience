"""One image, one following model response, one private action lease."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import copy
import json
import threading
from types import SimpleNamespace as NS

import pytest

from obsidience.harness.execution import executor

POINT = {"x": 731.125, "y": 283.875}
OBSERVE = {"tool": "computer.observe", "args": {"target": {"kind": "application", "name": "teamfight_tactics"}, "query": "Locate Play"}}
ACT = {"tool": "computer.act", "args": {"application": "teamfight_tactics", "target": "Play", "point": POINT}}
COMPLETE = {"tool": "task.complete", "args": {"status": "completed", "summary": "Finished."}}


def image_count(messages):
    return sum(
        part.get("type") == "image_url"
        for message in messages if isinstance(message.get("content"), list)
        for part in message["content"] if isinstance(part, dict)
    )


@pytest.fixture
def run(monkeypatch):
    task = NS(ref="Tasks/query", title="Fixture", kind="task", meta={})
    model = NS(id="isolated", capabilities=("text", "vision", "tools"))
    state = NS(requests=[], calls=[], events=[], contexts=[], leases=[],
               messages=[{"role": "system", "content": "Isolated fixture"}],
               context={}, results=[], provider_hook=None, tool_hook=None,
               allowed=["computer.observe", "computer.act", "window.activate", "task.complete"])

    @asynccontextmanager
    async def lease(_model):
        yield model

    async def chat(messages, **kwargs):
        state.requests.append(copy.deepcopy(messages))
        assert "_computer_observation_lease" not in state.context
        if state.provider_hook:
            await state.provider_hook(len(state.requests))
        reply = next(state.replies)
        if isinstance(reply, Exception):
            raise reply
        return executor.llm.ChatReply(content=reply if isinstance(reply, str) else json.dumps(reply),
                                      finish_reason="stop", completion_tokens=8)

    def execute(name, args, context):
        state.calls.append((name, copy.deepcopy(args)))
        if name == "task.complete":
            assert "_computer_observation_lease" not in context
            return {"accepted": args.get("status") != "reject", "status": "completed",
                    "summary": "Finished.", "error": "Fixture completion rejected"}
        state.contexts.append((name, context.get("_computer_observation_lease")))
        if state.tool_hook:
            custom = state.tool_hook(name, args, context)
            if custom is not None:
                return custom
        if name == "computer.observe":
            if state.results:
                return state.results.pop(0)
            result = observation(len(state.leases))
            state.leases.append(result["_private_observation_lease"])
            return result
        if name == "computer.act":
            context.pop("_computer_observation_lease", None)
        return {"status": "failed", "delivery": "not_dispatched"}

    monkeypatch.setattr(executor.model_runtime, "configured_spec", lambda _: model)
    monkeypatch.setattr(executor.model_runtime, "lease", lease)
    monkeypatch.setattr(executor.llm, "chat", chat)
    monkeypatch.setattr(executor, "execute_capability", execute)
    monkeypatch.setattr(executor.action_trace, "emit", lambda *args: state.events.append(args))

    async def execute_session(actions):
        state.replies = iter(actions)
        state.trace, state.status, state.summary = await executor._execute_session(
            task, model, state.messages, state.allowed, state.context, "Executive", "none",
        )
        return state
    state.execute = execute_session
    return state


def observation(index=0):
    image = f"private-fixture-pixels-{index}".encode()
    return {
        "observation": {"status": "observed",
                        "target": {"kind": "application", "name": "teamfight_tactics", "surface": "samsung"},
                        "visual_evidence": {"attached": True, "freshness": "validated_after_capture"}},
        "_private_image_png": image,
        "_private_observation_lease": {
            "target": NS(private_identity=f"private-lease-identity-{index}"),
            "capture": NS(image_png=image), "process_start_time": 987654321,
        },
    }


def assert_private_output_absent(state):
    public = json.dumps([state.context.get("trace"), state.events, state.messages], default=str)
    for private in ("_private_observation_lease", "_computer_observation_lease",
                    "private-lease-identity", "private-fixture-pixels", "image_url",
                    '"point"', "731.125", "283.875", "987654321"):
        assert private not in public
    assert "_computer_observation_lease" not in state.context
    assert image_count(state.messages) == 0


def test_exact_next_response_receives_one_matching_private_lease_and_no_public_point(run):
    result = asyncio.run(run.execute([OBSERVE, ACT, COMPLETE]))
    assert [image_count(request) for request in result.requests] == [0, 1, 0]
    assert result.contexts[0] == ("computer.observe", None)
    assert result.contexts[1][0] == "computer.act"
    assert result.contexts[1][1] is result.leases[0]
    assert result.calls[1][1]["point"] == POINT
    action_entry = next(row for row in result.trace if row.get("tool") == "computer.act")
    assert action_entry["args"] == {"application": "teamfight_tactics", "target": "Play"}
    assert action_entry["sig"].startswith("computer.act:sha256:")
    assert len(action_entry["sig"].split(":")[-1]) == 64
    assert_private_output_absent(result)


@pytest.mark.parametrize("intervening", [
    {"tool": "window.activate", "args": {}},
    {"tool": "not.authorized", "args": {}},
    {"tool": "task.complete", "args": {"status": "reject"}},
    '{"tool":"computer.act","args":{"point":{"x":731.125,"y":283.875}',
])
def test_any_intervening_response_consumes_the_observation_lease(run, intervening):
    result = asyncio.run(run.execute([OBSERVE, intervening, ACT, COMPLETE]))
    assert next(context for name, context in result.contexts if name == "computer.act") is None
    assert [image_count(request) for request in result.requests] == [0, 1, 0, 0]
    assert_private_output_absent(result)


def test_a_second_observation_replaces_the_first_response_lease(run):
    result = asyncio.run(run.execute([OBSERVE, OBSERVE, ACT, COMPLETE]))
    assert [image_count(request) for request in result.requests] == [0, 1, 1, 0]
    assert result.contexts[:2] == [("computer.observe", None), ("computer.observe", None)]
    assert result.contexts[2][1] is result.leases[1]
    assert result.contexts[2][1] is not result.leases[0]
    assert_private_output_absent(result)


@pytest.mark.parametrize("change", ["missing_image", "bad_image", "different_image", "failed", "pane", "missing_lease"])
def test_lease_is_admitted_only_with_its_successful_application_image(run, change):
    supplied = observation()
    if change == "missing_image":
        supplied.pop("_private_image_png")
    elif change == "bad_image":
        supplied["_private_image_png"] = "invalid-text-image"
    elif change == "different_image":
        supplied["_private_image_png"] = b"different-private-image"
    elif change == "failed":
        supplied["observation"]["status"] = "unavailable"
    elif change == "pane":
        supplied["observation"]["target"] = {"kind": "pane", "name": "reader"}
    else:
        supplied.pop("_private_observation_lease")
    run.results = [supplied]
    result = asyncio.run(run.execute([OBSERVE, ACT, COMPLETE]))
    assert next(context for name, context in result.contexts if name == "computer.act") is None
    assert_private_output_absent(result)


def test_provider_failure_discards_image_and_lease_without_action(run):
    result = asyncio.run(run.execute([OBSERVE, RuntimeError("provider unavailable")]))
    assert result.status == "failed"
    assert [name for name, args in result.calls] == ["computer.observe"]
    assert_private_output_absent(result)


def test_completion_without_using_observation_releases_private_lease(run):
    result = asyncio.run(run.execute([OBSERVE, COMPLETE]))
    assert result.status == "completed"
    assert_private_output_absent(result)


def test_untrusted_preexisting_context_lease_is_never_admitted(run):
    run.context["_computer_observation_lease"] = observation()["_private_observation_lease"]
    result = asyncio.run(run.execute([ACT, COMPLETE]))
    assert result.contexts == [("computer.act", None)]
    assert_private_output_absent(result)


def test_cancellation_during_the_image_request_clears_private_state(run):
    async def exercise():
        reached = asyncio.Event()
        async def block(count):
            if count == 2:
                reached.set()
                await asyncio.Event().wait()
        run.provider_hook = block
        pending = asyncio.create_task(run.execute([OBSERVE, ACT]))
        await reached.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
    asyncio.run(exercise())
    assert [name for name, args in run.calls] == ["computer.observe"]
    assert_private_output_absent(run)


def test_three_invalid_visual_responses_keep_only_bounded_structural_diagnostics(run):
    invalid = '{"tool":"computer.act","args":{"point":{"x":731.125,"y":283.875}'
    result = asyncio.run(run.execute([OBSERVE, invalid, invalid, invalid]))
    assert result.status == "failed"
    invalid_rows = [row for row in result.trace if "invalid" in row]
    assert len(invalid_rows) == 3 and all(row["reply_chars"] == len(invalid) for row in invalid_rows)
    assert all(len(row["reply_sha256"]) == 64 for row in invalid_rows)
    assert_private_output_absent(result)


@pytest.mark.parametrize("cancel_tool", ["computer.observe", "computer.act"])
def test_cancelled_worker_cannot_publish_a_late_lease_or_private_action_trace(run, cancel_tool):
    async def exercise():
        loop = asyncio.get_running_loop()
        reached = asyncio.Event()
        finished = asyncio.Event()
        release = threading.Event()
        cancellation = []

        def worker(name, args, context):
            if name != cancel_tool:
                return None
            if name == "computer.act":
                assert context.pop("_computer_observation_lease", None) is run.leases[0]
            cancellation.append(context["_capability_cancel_event"])
            loop.call_soon_threadsafe(reached.set)
            assert release.wait(2), "cancelled fixture worker was not released"
            loop.call_soon_threadsafe(finished.set)
            return observation() if name == "computer.observe" else {"status": "failed"}

        run.tool_hook = worker
        pending = asyncio.create_task(run.execute([OBSERVE, ACT, COMPLETE]))
        try:
            await reached.wait()
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert cancellation[0].is_set()
            assert_private_output_absent(run)
        finally:
            release.set()
            await finished.wait()
        # Let the discarded thread result settle on the original event loop.
        await asyncio.sleep(0)
        assert_private_output_absent(run)

    asyncio.run(exercise())
    interrupted = [row for row in run.context["trace"] if row.get("interrupted")]
    assert len(interrupted) == 1 and interrupted[0]["must_not_replay"] is True


def test_predispatch_application_mismatch_consumes_the_image_lease(run):
    run.context["params"] = {"application": "microsoft_edge"}
    focused = {"tool": "computer.observe", "args": {"target": {"kind": "focused"}, "query": "Locate Play"}}
    corrected = copy.deepcopy(ACT)
    corrected["args"]["application"] = "microsoft_edge"
    result = asyncio.run(run.execute([focused, ACT, corrected, COMPLETE]))
    assert [name for name, args in result.calls] == ["computer.observe", "computer.act", "task.complete"]
    assert next(context for name, context in result.contexts if name == "computer.act") is None
    assert_private_output_absent(result)
