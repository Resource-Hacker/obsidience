"""Task executions retain the Vault sync.

The answer-only skip now applies only to native Executive conversation turns
(run_conversation); the retired Query Task path always reconciles the Vault.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace as NS

import pytest

from obsidience.harness.execution import executor
from obsidience.tests.test_execution_cancellation import execution


def _params(event="chat.request"):
    return {"event": event, "source": "text" if event == "chat.request" else "voice",
            "request": "Say hello.", "computer_outcome": "answer",
            "conversation_id": "isolated-conversation", "reply_to_turn_id": "isolated-owner-turn"}


def _scan_counter(execution, monkeypatch):
    scans = []
    # A snapshot parameter is supported by the production resolver. This fixture
    # deliberately supplies only the already admitted isolated Executive.
    agent = NS(ref="Agents/Executive/Executive", title="Executive", kind="agent", meta={}, body="")
    monkeypatch.setattr(executor, "resolver", lambda **_kwargs: NS(resolve=lambda _ref: agent))
    monkeypatch.setattr(executor.INDEX, "sync", lambda: scans.append(True))
    return scans


@pytest.mark.parametrize("change", [
    {"event": "task.continue"}, {"event": "turn.complete"},
    {"computer_outcome": "observe"}, {"computer_outcome": None},
    {"conversation_id": ""}, {"reply_to_turn_id": ""},
])
def test_uncovered_request_origin_retains_index_sync(execution, monkeypatch, change):
    scans = _scan_counter(execution, monkeypatch)
    asyncio.run(execution.run(runtime_params={**_params(), **change}))
    assert scans == [True]


@pytest.mark.parametrize("variant", ["other_task", "noninteractive", "failed", "invalid_then_complete", "tool_then_complete", "rejected_then_complete"])
def test_any_other_execution_retains_index_sync(execution, monkeypatch, variant):
    scans = _scan_counter(execution, monkeypatch)
    run_kwargs = {"runtime_params": _params()}
    if variant == "other_task":
        execution.task.ref = "Tasks/other"
    elif variant == "noninteractive":
        run_kwargs["interactive"] = False
    replies = []
    if variant == "failed":
        replies.append({"tool": "task.complete", "args": {"status": "failed", "summary": "Cannot answer."}})
    elif variant == "invalid_then_complete":
        replies.append("Invalid public response")
    elif variant == "tool_then_complete":
        replies.append({"tool": "window.place", "args": {}})
    elif variant == "rejected_then_complete":
        replies.append({"tool": "task.complete", "args": {"status": "invalid", "summary": "Rejected."}})
    replies.append({"tool": "task.complete", "args": {"status": "completed", "summary": "Hello."}})

    async def response(*_args, **_kwargs):
        value = replies.pop(0)
        return NS(content=json.dumps(value) if isinstance(value, dict) else value,
                  prompt_tokens=100, finish_reason="stop", completion_tokens=20)

    monkeypatch.setattr(executor.llm, "chat", response)
    asyncio.run(execution.run(**run_kwargs))
    assert scans == [True]
