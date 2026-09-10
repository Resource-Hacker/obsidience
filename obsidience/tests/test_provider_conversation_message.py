"""The current Objective follows its separate reusable conversation message."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest

from obsidience.harness.execution import executor
from obsidience.tests.test_execution_cancellation import execution  # noqa: F401


@pytest.mark.parametrize("prior", ["", "## Immediate Observations\nUser: TFT is already open.\nExecutive: It is open."])
def test_provider_conversation_remains_separate_and_before_current_objective(execution, monkeypatch, prior):
    compile_packet = executor.compile_activation
    requests, measured = [], []

    async def compile_with_conversation(*args, **kwargs):
        packet = await compile_packet(*args, **kwargs)
        packet["provider_conversation"] = prior
        return packet

    async def reply(messages, **kwargs):
        requests.append((deepcopy(messages), list(kwargs["allowed_tools"])))
        return await execution.reply()

    def count(text, _model):
        measured.append(text)
        return NS(tokens=100)

    monkeypatch.setattr(executor, "compile_activation", compile_with_conversation)
    monkeypatch.setattr(executor.llm, "chat", reply)
    monkeypatch.setattr(executor, "cached_text_count", count)
    result = asyncio.run(execution.run(conversation_context=prior))
    assert result["status"] == "completed"
    messages, offered = requests[0]
    assert offered == execution.tools
    assert messages[0]["role"] == "system"
    assert "Isolated fixed instructions" in messages[0]["content"]
    assert executor.llm.PROTOCOL in messages[0]["content"]
    expected_context = [
        *([{"role": "user", "content": prior}] if prior else []),
        {"role": "user", "content": "Move the requested application"},
    ]
    assert messages[1:1 + len(expected_context)] == expected_context
    assert len(messages) == len(expected_context) + 2
    assert messages[-1]["content"].startswith("Execution budget:")
    if prior:
        assert prior not in messages[0]["content"]
        assert measured[0].count(prior) == 1
    assert measured[0].endswith(prior + "Move the requested application")
    assert execution.contexts[0]["objective"] == "Move the requested application"
