"""Real public trace projection and executor correlation, without live models."""
from __future__ import annotations

import asyncio
from collections import deque
from copy import deepcopy
import hashlib
import json

import pytest

from obsidience.harness.execution import executor, trace
from obsidience.tests.test_conversation_context_bindings import graph
from obsidience.tests.test_execution_cancellation import execution  # noqa: F401

REAL_EMIT = trace.emit


@pytest.fixture
def stream(monkeypatch):
    monkeypatch.setattr(trace, "_HISTORY", deque())
    monkeypatch.setattr(trace, "_HISTORY_CHARS", 0)
    monkeypatch.setattr(trace, "_SUBSCRIBERS", set())
    monkeypatch.setattr(trace, "emit", REAL_EMIT)
    token = trace.bind("", "", "")
    yield
    trace.reset(token)


def encoded(value):
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def test_structured_tool_and_legacy_detail_share_private_boundary(stream):
    result = {"body": "Visible evidence " * 90, "password": "SECRET-PASSWORD",
              "nested": {"_private_image_png": b"PRIVATE-PIXELS", "point": [731.125, 283.875],
                         "token": "SECRET-TOKEN", "lease": object()},
              "encoded": json.dumps({"api_key": "SECRET-API", "_computer_observation_lease": "PRIVATE-LEASE"}),
              "reasoning_content": "PRIVATE-MODEL-REASONING",
              "prose": 'Authorization: Bearer abcd1234567890123456\npassword="SECRET-IN-PROSE"',
              "number": float("nan")}
    before = deepcopy(result)
    trace.emit("result", "Tool returned", [str(result)], {"run_id": "run-one", "call_id": "run-one:1",
        "step": 1, "payload": {"kind": "tool", "name": "vault.read", "phase": "result", "result": result}})
    entry = trace.history()[0]
    wire = encoded(entry)
    for private in ("SECRET-PASSWORD", "SECRET-TOKEN", "SECRET-API", "SECRET-IN-PROSE",
                    "abcd1234567890123456", "PRIVATE-PIXELS", "PRIVATE-LEASE", "731.125", "283.875",
                    "_private_image_png", "_computer_observation_lease", "PRIVATE-MODEL-REASONING", "object at"):
        assert private not in wire
    assert entry["payload"]["result"]["body"] == before["body"]
    assert entry["run_id"] == "run-one" and entry["call_id"] == "run-one:1"
    assert entry["truncated"] is True
    assert result["nested"]["point"] == before["nested"]["point"]
    assert result["password"] == "SECRET-PASSWORD"


def test_packet_keeps_compiler_sections_and_marks_every_clipped_section(stream):
    sections = {key: "## " + key + "\n" + "日本語\\\"" * 15_000 for key in (
        "identity", "task", "objective", "tools", "skills", "runbook", "knowledge", "immediate", "begin")}
    sections["bindings"] = "## Bindings\n" + json.dumps({"application": "test", "password": "HIDDEN", "_private_image_png": "PIXELS"})
    trace.emit("activation", "Packet", [], {"payload": trace.packet_payload(sections, ["Tasks/query"], 2.5)})
    entry = trace.history()[0]
    assert len(encoded(entry)) <= trace.MAX_EVENT_CHARS
    assert entry["truncated"] is True
    assert [part["key"] for part in entry["payload"]["sections"]] == list(sections)
    for part in entry["payload"]["sections"]:
        assert part["chars"] == len(sections[part["key"]])
        assert part["sha256"] == hashlib.sha256(sections[part["key"]].encode()).hexdigest()
        assert part["truncated"] is True
    assert "HIDDEN" not in encoded(entry) and "PIXELS" not in encoded(entry)


def test_compiler_emits_actual_ordered_sections_without_reparsing_article_headings(stream, monkeypatch):
    res, agent, tasks = graph()
    tasks[0].body = "Accepted Task body.\n## Objective\nAn authored heading is still Task text."
    monkeypatch.setattr(executor.source, "article_refs_for_trees", lambda *_args: [])
    monkeypatch.setattr(executor.shell_scene.SCENE, "activation_binding", lambda: {})
    monkeypatch.setattr(executor.retrieval, "fast_context_with_refs", lambda *_args, **_kwargs: ("Accepted cited Knowledge.", ["Knowledge/accepted"]))
    monkeypatch.setattr(executor.knowledge_activity, "emit", lambda *_args, **_kwargs: None)
    token = trace.bind("actual-run", tasks[0].ref, agent.ref)
    try:
        activation = asyncio.run(executor.compile_activation(tasks[0], agent=agent, accepted_resolver=res,
            params={"request": "The current exact objective."}, conversation_context="Owner: Earlier context."))
    finally:
        trace.reset(token)
    event = trace.history()[0]
    parts = event["payload"]["sections"]
    assert "\n\n".join(part["text"] for part in parts) == activation["packet"]
    assert event["run_id"] == "actual-run"
    assert event["task_ref"] == tasks[0].ref and event["agent_ref"] == agent.ref
    assert [part["key"] for part in parts] == ["header", "identity", "task", "objective", "tools", "skills", "runbook", "bindings", "knowledge", "conversation", "begin"]
    assert next(part["text"] for part in parts if part["key"] == "objective") == "## Objective\nThe current exact objective."
    assert "An authored heading" in next(part["text"] for part in parts if part["key"] == "task")
    assert all(not part["truncated"] for part in parts) and not event["truncated"]


def test_event_history_and_slow_subscriber_have_hard_bounds_and_stable_ids(stream):
    queue = trace.subscribe()
    for index in range(160):
        trace.emit("result", "Result", [], {"payload": {"kind": "tool", "name": "web.fetch", "phase": "result",
            "result": {"results": [{"url": f"https://example.org/{i}", "ok": i != 1,
                                   "result": "日本語\\\"" * 7_000} for i in range(10)]}}})
    history = trace.history()
    assert len(history) < 160
    assert sum(len(encoded(row)) for row in history) <= trace.MAX_HISTORY_CHARS
    assert all(len(encoded(row)) <= trace.MAX_EVENT_CHARS and row["truncated"] for row in history)
    assert all(row["payload"]["result"]["results"][1]["ok"] is False for row in history)
    assert queue.qsize() == 100
    queued = [queue.get_nowait() for _ in range(queue.qsize())]
    assert queued[-1]["id"] == history[-1]["id"]
    assert len({row["id"] for row in queued}) == len(queued)
    trace.unsubscribe(queue)
    assert queue not in trace._SUBSCRIBERS


def test_execution_context_is_task_local_and_private_channels_are_absent(stream):
    async def send(run_id):
        token = trace.bind(run_id, "Tasks/" + run_id, "Agents/" + run_id)
        try:
            await asyncio.sleep(0)
            trace.emit("run", "Started")
            trace.emit("reasoning", "NEVER-PUBLIC")
            trace.emit("analysis", "NEVER-PUBLIC")
        finally:
            trace.reset(token)

    async def exercise():
        await asyncio.gather(send("one"), send("two"))
        trace.emit("status", "Outside either execution")

    asyncio.run(exercise())
    one, two, outside = trace.history()
    assert one["run_id"] == "one" and one["task_ref"] == "Tasks/one"
    assert two["run_id"] == "two" and two["agent_ref"] == "Agents/two"
    assert "run_id" not in outside
    assert "NEVER-PUBLIC" not in encoded(trace.history())


def test_long_tool_result_preserves_failure_metadata_and_complete_preview_has_no_false_flag(stream):
    trace.emit("result", "Rejected", [], {"payload": {"kind": "tool", "result": "大" * 90_000,
        "status": "rejected", "duration_ms": 42.0, "phase": "result", "name": "vault.propose"}})
    entry = trace.history()[-1]
    assert entry["payload"]["status"] == "rejected"
    assert entry["payload"]["duration_ms"] == 42.0
    assert entry["truncated"] is True
    body = "Complete displayed evidence. " * 150
    trace.emit("result", "Read", [], {"payload": {"kind": "tool", "name": "vault.read", "phase": "result", "result": body}})
    entry = trace.history()[-1]
    assert entry["payload"]["result"] == body
    assert len(entry["detail"][0]) == 500 and entry["truncated"] is False


