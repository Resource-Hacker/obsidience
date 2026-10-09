"""Turn timing crosses the existing executor without entering dialogue or authority."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import time
from types import SimpleNamespace as NS

import pytest

from obsidience.harness.conversation import runtime as conversation_runtime
from obsidience.harness.execution import executor, scheduler, trace
from obsidience.tests.test_execution_cancellation import execution  # noqa: F401
from obsidience.tests.test_latency_trace_context import latency_stream  # noqa: F401
from obsidience.tests.test_realtime_graph_integration import MemoryConversation


@pytest.fixture
def lane(execution, latency_stream, monkeypatch):
    memory = MemoryConversation()
    runtime = conversation_runtime.ConversationRuntime(memory)
    state = NS(runtime=runtime, memory=memory, worker=[], admissions=[], selections=[], calls=[])

    async def send(payload):
        state.worker.append(deepcopy(payload))

    async def publish(*_args, **_kwargs):
        pass

    # Replies are spoken through speech.speak(); control messages use _send_worker.
    runtime.speech = NS(snapshot=lambda: {"ready": True}, _send_worker=send, speak=send, _publish=publish)

    async def prepare(_turn, **_kwargs):
        return "User: The earlier exact context."

    @asynccontextmanager
    async def admitted(owner):
        state.admissions.append(owner)
        yield

    run_task = executor.run_task

    async def run(_executive, **kwargs):
        # The turn admits the Executive itself (run_conversation); execute the
        # isolated fixture Task through the real executor instead.
        state.calls.append(deepcopy(kwargs["runtime_params"]))
        return await run_task(execution.task, **kwargs)

    monkeypatch.setattr(runtime, "_context_model", lambda *_args: "isolated")
    monkeypatch.setattr(runtime, "prepare_conversation_context", prepare)
    monkeypatch.setattr(runtime, "record_prompt_usage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runtime, "publish_context", lambda: None)
    monkeypatch.setattr(conversation_runtime, "historical_evidence", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(scheduler, "foreground_admission", admitted)
    monkeypatch.setattr(executor, "run_conversation", run)
    return state


def speech_timing():
    final = time.monotonic_ns() - 1_000_000
    return {
        "speech_sequence": 9,
        "stages": [
            {"stage": "speech_onset", "monotonic_ns": final - 2_000_000},
            {"stage": "first_partial", "monotonic_ns": final - 1_000_000},
            {"stage": "speech_final", "monotonic_ns": final},
        ],
        "text": "PRIVATE-TRANSPORT-TEXT", "reasoning": "PRIVATE-REASONING",
        "credentials": "PRIVATE-CREDENTIALS",
    }


@pytest.mark.parametrize("cancelled", [False, True])
def test_uncommitted_outcome_never_emits_answer_commit_or_leaks_turn_scope(lane, monkeypatch, cancelled):
    async def outcome(*_args, **_kwargs):
        if cancelled:
            raise asyncio.CancelledError
        return {"status": "failed", "run_id": "failed-run", "summary": "Internal outcome"}

    monkeypatch.setattr(executor, "run_conversation", outcome)

    async def exercise():
        result = await lane.runtime.submit("Hello", source="text")
        trace.latency("activation", monotonic_ns=1_000_000)
        return result

    result = asyncio.run(exercise())
    assert result["status"] == ("interrupted" if cancelled else "failed")
    assert [row["role"] for row in lane.memory.turns] == ["user"]
    events = [row["payload"] for row in trace.history() if row.get("payload", {}).get("kind") == "latency"]
    assert not any(row["stage"] == "answer_committed" for row in events)
    assert "turn_id" not in events[-1]
