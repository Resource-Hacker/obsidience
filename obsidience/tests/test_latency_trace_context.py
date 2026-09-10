"""Public timing keeps exact turn identity without publishing transport contents."""
from __future__ import annotations

import asyncio
from collections import deque
import json

import pytest

from obsidience.harness.execution import trace

REAL_EMIT = trace.emit


@pytest.fixture
def latency_stream(monkeypatch):
    monkeypatch.setattr(trace, "_HISTORY", deque())
    monkeypatch.setattr(trace, "_HISTORY_CHARS", 0)
    monkeypatch.setattr(trace, "_SUBSCRIBERS", set())
    monkeypatch.setattr(trace, "_LEDGER", None)
    monkeypatch.setattr(trace, "_LOOP", None)
    monkeypatch.setattr(trace, "emit", REAL_EMIT)
    scope = trace.bind_turn("")
    try:
        yield
    finally:
        trace.reset(scope)


def test_parallel_turn_and_tool_workers_keep_exact_correlation(latency_stream):
    async def turn(name, sequence):
        scope = trace.bind_turn(name, speech_sequence=sequence, generation=7)
        try:
            trace.latency("input_final", monotonic_ns=1_000_000)
            run_scope = trace.bind("run-" + name, "Tasks/query", "Agents/Executive/Executive")
            try:
                await asyncio.to_thread(trace.latency, "model_complete", monotonic_ns=2_000_000)
            finally:
                trace.reset(run_scope)
            trace.latency("answer_committed", monotonic_ns=3_000_000, run_id="run-" + name)
        finally:
            trace.reset(scope)

    async def exercise():
        await asyncio.gather(turn("one", 1), turn("two", 2))
        trace.latency("preparation", monotonic_ns=4_000_000)

    asyncio.run(exercise())
    events = trace.history()
    for name, sequence in (("one", 1), ("two", 2)):
        rows = [row for row in events if row["payload"].get("turn_id") == name]
        assert [row["payload"]["stage"] for row in rows] == [
            "input_final", "model_complete", "answer_committed",
        ]
        assert all(row["payload"]["speech_sequence"] == sequence for row in rows)
        assert all(row["payload"]["generation"] == 7 for row in rows)
        assert "run_id" not in rows[0]
        assert rows[1]["run_id"] == rows[1]["payload"]["run_id"] == "run-" + name
        assert rows[1]["task_ref"] == "Tasks/query"
        assert rows[2]["run_id"] == rows[2]["payload"]["run_id"] == "run-" + name
        assert "task_ref" not in rows[2]
    assert events[-1]["payload"] == {
        "kind": "latency", "stage": "preparation", "monotonic_ms": 4.0,
    }
    assert all(row["channel"] == "measurement" and "step" not in row for row in events)


@pytest.mark.parametrize("kwargs", [
    {"stage": "invented"},
    {"monotonic_ns": True}, {"monotonic_ns": -1}, {"monotonic_ns": 2**63},
    {"duration_ms": True}, {"duration_ms": -0.1}, {"duration_ms": float("nan")},
    {"duration_ms": float("inf")}, {"duration_ms": 86_400_001},
])
def test_invalid_timing_does_not_create_plausible_public_measurement(latency_stream, kwargs):
    trace.latency(**{"stage": "selection", "monotonic_ns": 123_000_000, **kwargs})
    assert trace.history() == []


def test_timing_projection_drops_content_and_preserves_large_clock_precision(latency_stream):
    stamp = 2**53 + 1_234_567
    trace.latency("model_first_public", monotonic_ns=stamp, duration_ms=61.41234,
                  turn_id="turn", run_id="run", generation=True, speech_sequence=2**53,
                  transcript="PRIVATE-TRANSCRIPT", reasoning="PRIVATE-REASONING",
                  password="PRIVATE-CREDENTIAL", pixels=b"PRIVATE-PIXELS")
    entry = trace.history()[0]
    assert entry["payload"] == {
        "kind": "latency", "stage": "model_first_public", "monotonic_ms": stamp / 1_000_000,
        "duration_ms": 61.412, "turn_id": "turn", "run_id": "run",
    }
    assert abs(entry["payload"]["monotonic_ms"] * 1_000_000 - stamp) < 10
    assert "PRIVATE-" not in json.dumps(entry)
    assert "monotonic_ns" not in json.dumps(entry)


def test_latency_payload_allowlist_applies_to_direct_public_emission(latency_stream):
    trace.emit("measurement", "Observed timing", [], {"payload": {
        "kind": "latency", "stage": "speech_final", "monotonic_ms": 3.0,
        "text": "PRIVATE-TRANSCRIPT", "arguments": {"request": "PRIVATE-REQUEST"},
        "reasoning": "PRIVATE-REASONING", "audio": "PRIVATE-AUDIO",
    }})
    entry = trace.history()[0]
    assert entry["payload"] == {"kind": "latency", "stage": "speech_final", "monotonic_ms": 3.0}
    assert entry["truncated"] is True
    assert "PRIVATE-" not in json.dumps(entry)
