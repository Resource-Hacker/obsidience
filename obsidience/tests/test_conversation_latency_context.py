"""Turn timing crosses the existing executor without entering dialogue or authority."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
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

    runtime.speech = NS(snapshot=lambda: {"ready": True}, _send_worker=send, _publish=publish)

    async def prepare(_turn, **_kwargs):
        return "User: The earlier exact context."

    async def select(text, source, **kwargs):
        state.selections.append(deepcopy(kwargs))
        event = "voice.activation" if source == "voice" else "chat.request"
        return execution.task, {"request": text, "event": event, "source": source,
                                "computer_outcome": "answer"}, event

    @asynccontextmanager
    async def admitted(owner):
        state.admissions.append(owner)
        yield

    run_task = executor.run_task

    async def run(task, **kwargs):
        state.calls.append(deepcopy(kwargs["runtime_params"]))
        return await run_task(task, **kwargs)

    monkeypatch.setattr(runtime, "_context_model", lambda *_args: "isolated")
    monkeypatch.setattr(runtime, "prepare_immediate_observations", prepare)
    monkeypatch.setattr(runtime, "record_prompt_usage", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runtime, "publish_context", lambda: None)
    monkeypatch.setattr(conversation_runtime, "historical_evidence", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(conversation_runtime, "select_task", select)
    monkeypatch.setattr(scheduler, "foreground_admission", admitted)
    monkeypatch.setattr(executor, "run_task", run)
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


@pytest.mark.parametrize("source", ["text", "realtime"])
def test_completed_turn_correlates_timing_without_changing_task_or_dialogue(lane, source):
    timing = speech_timing()
    result = asyncio.run(lane.runtime.submit("Hello", source=source, speech_timing=timing))
    assert result["status"] == "completed"
    assert lane.admissions == ["conversation"]
    user, answer = lane.memory.turns
    assert [(row["role"], row["text"]) for row in lane.memory.turns] == [
        ("user", "Hello"), ("assistant", "Done."),
    ]
    assert answer["reply_to"] == user["id"] and answer["run_id"] == result["run_id"]
    events = [row for row in trace.history() if row.get("payload", {}).get("kind") == "latency"]
    stages = [row["payload"]["stage"] for row in events]
    assert stages[0] == "input_final" and stages[-1] == "answer_committed"
    assert stages.index("preparation") < stages.index("selection") < stages.index("activation")
    assert stages.index("activation") < stages.index("answer_committed")
    assert all(row["payload"]["turn_id"] == user["id"] for row in events)
    assert all(row["payload"]["generation"] == lane.runtime._generation for row in events)
    assert events[-1]["payload"]["run_id"] == result["run_id"]
    assert events[-1]["run_id"] == result["run_id"]
    expected_input = timing["stages"] if source == "realtime" else []
    input_rows = [row["payload"] for row in events if row["payload"]["stage"].startswith("speech_")
                  or row["payload"]["stage"] == "first_partial"]
    assert [(row["stage"], row["monotonic_ms"]) for row in input_rows] == [
        (edge["stage"], edge["monotonic_ns"] / 1_000_000) for edge in expected_input
    ]
    assert all(("speech_sequence" in row["payload"]) == (source == "realtime") for row in events)
    spoken = [message for message in lane.worker if message["type"] == "speak"]
    if source == "realtime":
        assert spoken == [{"type": "speak", "generation": lane.runtime._generation,
                           "text": "Done.", "turn_id": user["id"], "run_id": result["run_id"],
                           "speech_sequence": 9}]
    else:
        assert spoken == []
    persisted = json.dumps([lane.memory.turns, lane.memory.events, lane.calls, lane.selections])
    assert "speech_timing" not in persisted and "monotonic" not in persisted
    assert "speech_sequence" not in persisted and "PRIVATE-" not in persisted
    assert "PRIVATE-" not in json.dumps(trace.history())
    trace.latency("preparation", monotonic_ns=1_000_000)
    assert "turn_id" not in trace.history()[-1]["payload"]


def test_malformed_speech_timing_is_ignored_without_rejecting_public_input(lane):
    timing = speech_timing()
    timing["stages"].reverse()
    result = asyncio.run(lane.runtime.submit("Hello", source="realtime", speech_timing=timing))
    assert result["status"] == "completed"
    events = [row["payload"] for row in trace.history() if row.get("payload", {}).get("kind") == "latency"]
    assert not any(row["stage"] in {"speech_onset", "first_partial", "speech_final"} for row in events)
    assert all("speech_sequence" not in row for row in events)
    assert all("speech_sequence" not in message for message in lane.worker)


@pytest.mark.parametrize("cancelled", [False, True])
def test_uncommitted_outcome_never_emits_answer_commit_or_leaks_turn_scope(lane, monkeypatch, cancelled):
    async def outcome(*_args, **_kwargs):
        if cancelled:
            raise asyncio.CancelledError
        return {"status": "failed", "run_id": "failed-run", "summary": "Internal outcome"}

    monkeypatch.setattr(executor, "run_task", outcome)

    async def exercise():
        result = await lane.runtime.submit("Hello", source="text")
        trace.latency("selection", monotonic_ns=1_000_000)
        return result

    result = asyncio.run(exercise())
    assert result["status"] == ("interrupted" if cancelled else "failed")
    assert [row["role"] for row in lane.memory.turns] == ["user"]
    events = [row["payload"] for row in trace.history() if row.get("payload", {}).get("kind") == "latency"]
    assert not any(row["stage"] == "answer_committed" for row in events)
    assert "turn_id" not in events[-1]
