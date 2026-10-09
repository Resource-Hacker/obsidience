"""Controller computer-request bindings survive the actual executor run."""
from __future__ import annotations

import asyncio
import json

import pytest

from obsidience.harness.execution import executor
from obsidience.harness.execution.adk import runner as adk_runner
from obsidience.tests.test_execution_cancellation import execution  # noqa: F401


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

    monkeypatch.setattr(adk_runner, "run_adk_session", session)
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

    monkeypatch.setattr(adk_runner, "run_adk_session", session)
    asyncio.run(execution.run(runtime_params=None))
    assert "computer_request" not in json.loads(execution.records[0]["trace"])[0]
