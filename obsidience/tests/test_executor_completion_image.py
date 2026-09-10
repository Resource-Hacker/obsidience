"""Exercise ephemeral completion-image ownership through the real executor loop."""
from __future__ import annotations

import asyncio
import base64
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace as NS

import pytest

from obsidience.harness.capabilities.task import complete
from obsidience.harness.execution import executor
from obsidience.tests.test_execution_cancellation import execution  # noqa: F401

APP = {"kind": "application", "name": "click-fixture.py"}
MARKER = "_computer_response_observation"
FINDING = {"status": "established", "observation": "The fresh image shows the requested state."}


def action(name, **args):
    return {"tool": name, "args": args}


def finish(status="completed", *, finding=FINDING):
    return action("task.complete", status=status, summary="The requested state is established." if status == "completed" else "The state is not established.",
                  **({"verification": finding} if finding is not None else {}))


def image_result(pixels=b"before", *, clicked=False, target=APP):
    public_target = {**target, "surface": "usb-c"}
    result = {
        "observation": {"status": "observed", "target": public_target,
                        "visual_evidence": {"attached": True, "freshness": "validated_after_capture"}},
        "_private_image_png": pixels,
    }
    if clicked:
        result.update(status="completed", delivery="acknowledged", target=public_target,
                      effect={"kind": "click", "label": "Visible control", "verified": True})
    else:
        result["_private_observation_lease"] = {"capture": NS(image_png=pixels)}
    return result


OBSERVE = action("computer.observe", target=APP)
CLICK = action("computer.act", application=APP["name"], target="Visible control", point={"x": 500, "y": 500})


@pytest.fixture
def harness(monkeypatch):
    model = NS(id="inert", capabilities=("vision", "text", "tools"))
    task = NS(ref="Tasks/executive/operate", title="Computer Use", kind="task", meta={})
    state = NS(requests=[], provider_markers=[], capability_markers=[], decisions=[], lease_closed=False,
               messages=[], context={}, wait_at=None, waiting=None, release=None)

    @asynccontextmanager
    async def lease(_model):
        try:
            yield model
        finally:
            state.lease_closed = True

    monkeypatch.setattr(executor.model_runtime, "configured_spec", lambda _: model)
    monkeypatch.setattr(executor.model_runtime, "lease", lease)
    monkeypatch.setattr(executor.action_trace, "emit", lambda *_a, **_k: None)

    async def run(replies, results, *, trace=None):
        replies, results = iter(replies), iter(results)
        state.context = {
            "task": task.ref,
            "params": {"computer_outcome": "action", "computer_scope": "state", "application": APP["name"]},
            "trace": list(trace or []), MARKER: {"forged_previous_lifetime": True},
        }
        state.messages = [{"role": "system", "content": "Inert test packet"}]

        async def chat(messages, **_kwargs):
            state.requests.append(json.loads(json.dumps(messages)))
            state.provider_markers.append(state.context.get(MARKER))
            if state.wait_at == len(state.requests):
                state.waiting.set()
                await state.release.wait()
            reply = next(replies)
            if isinstance(reply, Exception):
                raise reply
            return executor.llm.ChatReply(content=reply if isinstance(reply, str) else json.dumps(reply),
                                          finish_reason="stop", completion_tokens=8)

        def execute(name, args, context):
            state.capability_markers.append((name, context.get(MARKER)))
            if name == "task.complete":
                decision = complete.execute(args, context)
                state.decisions.append(decision)
                return decision
            return next(results)

        monkeypatch.setattr(executor.llm, "chat", chat)
        monkeypatch.setattr(executor, "execute_capability", execute)
        return await executor._execute_session(task, model, state.messages,
            ["computer.observe", "computer.act", "harness.status", "task.complete"],
            state.context, "Executive", "none")

    state.run = run
    return state


def request_images(request):
    return [part["image_url"]["url"] for message in request if isinstance(message.get("content"), list)
            for part in message["content"] if part.get("type") == "image_url"]


def test_postimage_witness_reaches_only_its_completion_and_finding_is_persisted(harness):
    trace, status, _ = asyncio.run(harness.run([OBSERVE, CLICK, finish()],
        [image_result(), image_result(b"after", clicked=True)]))
    assert status == "completed"
    assert harness.provider_markers == [None, None, None]
    assert [marker for name, marker in harness.capability_markers if name != "task.complete"] == [None, None]
    assert harness.capability_markers[-1][1]["verified"] is True
    assert request_images(harness.requests[-1]) == ["data:image/png;base64," + base64.b64encode(b"after").decode()]
    assert trace[-1]["args"]["verification"] == FINDING
    assert harness.context["completion"]["verification"] == FINDING
    assert MARKER not in harness.context
    assert request_images(harness.messages) == []
    assert "_private_image" not in json.dumps(trace)
    assert harness.lease_closed


@pytest.mark.parametrize("intervening", [
    "malformed response",
    action("harness.status"),
    action("unauthorized.tool"),
    finish(finding={"status": "not_established", "observation": "The image is inconclusive."}),
    finish(finding={"status": "established"}),
])
def test_invalid_reply_intervening_tool_or_rejected_completion_consumes_image(harness, intervening):
    results = [image_result(), image_result(b"after", clicked=True)]
    if isinstance(intervening, dict) and intervening["tool"] == "harness.status":
        results.append({"healthy": True})
    _, status, _ = asyncio.run(harness.run([OBSERVE, CLICK, intervening, finish(), finish("failed")], results))
    assert status == "failed"
    assert harness.decisions[-2]["accepted"] is False
    assert "actual fresh post-action image" in harness.decisions[-2]["error"]
    assert all(marker is None for name, marker in harness.capability_markers if name != "task.complete")
    assert request_images(harness.requests[-2]) == []
    assert MARKER not in harness.context


def test_pre_action_observation_cannot_mint_state_evidence_from_imported_trace(harness):
    old = complete.computer_completion_evidence("computer.act", image_result(clicked=True), image_attached=True)
    _, status, _ = asyncio.run(harness.run([OBSERVE, finish(), finish("failed")], [image_result()],
        trace=[{"tool": "computer.act", "completion_evidence": old}]))
    assert status == "failed"
    assert harness.capability_markers[1] == ("task.complete", None)
    assert "actual fresh post-action image" in harness.decisions[0]["error"]


def test_fresh_readonly_post_action_observation_mints_new_single_response_witness(harness):
    _, status, _ = asyncio.run(harness.run([OBSERVE, CLICK, OBSERVE, finish()],
        [image_result(), image_result(b"immediate", clicked=True), image_result(b"later")]))
    assert status == "completed"
    assert harness.capability_markers[-1][1] == {"verified": True, "target": APP}
    assert request_images(harness.requests[-1]) == ["data:image/png;base64," + base64.b64encode(b"later").decode()]
    assert MARKER not in harness.context


def test_three_distinct_state_actions_can_each_receive_a_fresh_identical_observe_call(harness):
    second = action("computer.act", application=APP["name"], target="Second control", point={"x": 400, "y": 500})
    third = action("computer.act", application=APP["name"], target="Third control", point={"x": 300, "y": 500})
    _, status, _ = asyncio.run(harness.run([OBSERVE, CLICK, OBSERVE, second, OBSERVE, third, finish()],
        [image_result(b"pre1"), image_result(b"post1", clicked=True),
         image_result(b"pre2"), image_result(b"post2", clicked=True),
         image_result(b"pre3"), image_result(b"post3", clicked=True)]))
    assert status == "completed"
    assert [name for name, _ in harness.capability_markers].count("computer.observe") == 3
    assert request_images(harness.requests[-1]) == ["data:image/png;base64," + base64.b64encode(b"post3").decode()]


def test_state_observe_repeat_exception_does_not_admit_repeated_input(harness):
    trace, status, _ = asyncio.run(harness.run([OBSERVE, CLICK, OBSERVE, CLICK, OBSERVE, CLICK, finish(), finish("failed")],
        [image_result(b"pre1"), image_result(b"post1", clicked=True),
         image_result(b"pre2"), image_result(b"post2", clicked=True), image_result(b"pre3")]))
    assert status == "failed"
    assert [name for name, _ in harness.capability_markers].count("computer.act") == 2
    assert "repeated this exact call" in [row for row in trace if row.get("tool") == "computer.act"][-1]["obs"]


@pytest.mark.parametrize("change", ["wrong_target", "failed_action", "missing_image"])
def test_invalid_later_evidence_cannot_reuse_earlier_action_image(harness, change):
    replies = [OBSERVE, CLICK]
    results = [image_result(), image_result(b"after", clicked=True)]
    if change == "failed_action":
        replies.append(action("computer.act", application=APP["name"], target="Different control", point={"x": 400, "y": 500}))
        results.append({"status": "failed", "delivery": "uncertain"})
    replies += [OBSERVE, finish(), finish("failed")]
    later = image_result(b"later", target={"kind": "application", "name": "different.py"} if change == "wrong_target" else APP)
    if change == "missing_image":
        later.pop("_private_image_png")
    results.append(later)
    _, status, _ = asyncio.run(harness.run(replies, results))
    assert status == "failed"
    assert harness.capability_markers[-2] == ("task.complete", None)
    assert harness.decisions[0]["accepted"] is False


def test_provider_failure_discards_pending_postimage_and_marker(harness):
    _, status, _ = asyncio.run(harness.run([OBSERVE, CLICK, RuntimeError("inert provider failure")],
        [image_result(), image_result(b"after", clicked=True)]))
    assert status == "failed"
    assert MARKER not in harness.context
    assert request_images(harness.messages) == []
    assert harness.decisions == []
    assert harness.lease_closed


def test_cancel_during_postimage_provider_request_discards_image_and_completion_authority(harness):
    async def scenario():
        harness.wait_at = 3
        harness.waiting, harness.release = asyncio.Event(), asyncio.Event()
        task = asyncio.create_task(harness.run([OBSERVE, CLICK, finish()],
            [image_result(), image_result(b"after", clicked=True)]))
        await asyncio.wait_for(harness.waiting.wait(), 1)
        assert MARKER not in harness.context
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(scenario())
    assert MARKER not in harness.context
    assert request_images(harness.messages) == []
    assert harness.decisions == []
    assert harness.lease_closed


def test_immutable_computer_request_projection_omits_unrelated_and_private_params():
    original = {"computer_outcome": "action", "computer_scope": "state", "application": "click-fixture.py",
                "operation": "computer_use", "request": "private request", "point": {"x": 123},
                "conversation_id": "private conversation", "window_id": "private window"}
    projected = executor._computer_request_evidence(original)
    assert projected == {key: original[key] for key in ("computer_outcome", "computer_scope", "application", "operation")}
    original["computer_scope"] = "input"
    assert projected["computer_scope"] == "state"


@pytest.mark.parametrize("params", [
    None, {}, {"computer_outcome": "answer"}, {"computer_outcome": []},
    {"computer_outcome": "action"}, {"computer_outcome": "action", "computer_scope": "unknown"},
    {"computer_outcome": "focus", "computer_scope": "state"},
    {"computer_outcome": "focus", "application": "x" * 257},
    {"computer_outcome": "focus", "application": "bad\nname"},
    {"computer_outcome": "focus", "operation": "launch"},
])
def test_invalid_or_answer_binding_is_not_saved_as_computer_request(params):
    assert executor._computer_request_evidence(params) is None


@pytest.mark.parametrize("terminal_path", ["returned", "error", "cancelled"])
def test_actual_run_preserves_original_controller_binding_before_execution(execution, monkeypatch, terminal_path):
    params = {"request": "Establish the requested state", "computer_outcome": "action", "computer_scope": "state",
              "application": "click-fixture.py", "operation": "computer_use",
              "conversation_id": "conversation", "reply_to_turn_id": "turn"}
    expected = executor._computer_request_evidence(params)

    async def session(*_args, **_kwargs):
        params["computer_scope"] = "input"
        if terminal_path == "error":
            raise RuntimeError("isolated execution failure")
        if terminal_path == "cancelled":
            raise asyncio.CancelledError
        return [], "failed", "No state was established."

    monkeypatch.setattr(executor, "_execute_session", session)
    if terminal_path == "returned":
        asyncio.run(execution.run(runtime_params=params))
    else:
        with pytest.raises(RuntimeError if terminal_path == "error" else asyncio.CancelledError):
            asyncio.run(execution.run(runtime_params=params))
    trace = json.loads(execution.records[0]["trace"])
    assert trace[0]["computer_request"] == expected
    assert trace[0]["computer_request"]["computer_scope"] == "state"
    assert trace[0]["interactive_turn"] == {"conversation_id": "conversation", "reply_to_turn_id": "turn"}


def test_current_authored_task_params_do_not_fabricate_historical_controller_binding(execution, monkeypatch):
    execution.task.meta["params"] = {"computer_outcome": "action", "computer_scope": "state", "application": "click-fixture.py"}

    async def session(*_args, **_kwargs):
        return [], "failed", "No state was established."

    monkeypatch.setattr(executor, "_execute_session", session)
    asyncio.run(execution.run(runtime_params=None))
    assert "computer_request" not in json.loads(execution.records[0]["trace"])[0]
