"""Real public trace projection and executor correlation, without live models."""
from __future__ import annotations

import asyncio
from collections import deque
from contextlib import asynccontextmanager
from copy import deepcopy
import hashlib
import json
import threading

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
    assert [part["key"] for part in parts] == ["header", "identity", "task", "objective", "tools", "skills", "runbook", "bindings", "knowledge", "immediate", "begin"]
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


def test_executor_pairs_reads_and_rejected_completion_before_actual_terminal_status(execution, stream, monkeypatch):
    execution.tools.append("vault.read")
    execution.task.meta["acceptance"] = "Requires owner confirmation."
    replies = iter([
        {"tool": "vault.read", "args": {"ref": "Knowledge/accepted"}},
        {"tool": "task.complete", "args": {"status": "completed", "summary": "First completion"}},
        {"tool": "task.complete", "args": {"status": "completed", "summary": "Second completion"}},
    ])
    complete_calls = 0
    body = "Actual Article evidence.\n" * 50

    async def reply(*_args, **_kwargs):
        return executor.llm.ChatReply(content=json.dumps(next(replies)), finish_reason="stop", completion_tokens=20, prompt_tokens=100)

    def tool(name, _args, _ctx):
        nonlocal complete_calls
        if name == "vault.read":
            return body
        complete_calls += 1
        return {"accepted": complete_calls == 2, "error": "Missing evidence", "status": "completed", "summary": "Accepted completion"}

    monkeypatch.setattr(executor.llm, "chat", reply)
    monkeypatch.setattr(executor, "execute_capability", tool)
    result = asyncio.run(execution.run())
    events = trace.history()
    assert all(row["run_id"] == result["run_id"] for row in events)
    assert all(row["task_ref"] == "Tasks/query" and row["agent_ref"] == "Agents/Executive/Executive" for row in events)
    tool_events = [row for row in events if row.get("payload", {}).get("kind") == "tool"]
    assert len(tool_events) == 6
    for index in range(3):
        start, returned = tool_events[index * 2:index * 2 + 2]
        assert start["call_id"] == returned["call_id"] == f"{result['run_id']}:{index + 1}"
        assert start["step"] == returned["step"] == index + 1
        assert start["payload"]["phase"] == "start" and returned["payload"]["phase"] == "result"
        assert returned["payload"]["duration_ms"] >= 0
    assert tool_events[1]["payload"]["result"] == body
    assert tool_events[3]["payload"]["status"] == "rejected"
    assert tool_events[5]["payload"]["result"]["status"] == "completed"
    assert events[-1]["payload"]["kind"] == "run"
    assert events[-1]["payload"]["status"] == result["status"] == "review"
    models = [row for row in events if row.get("payload", {}).get("kind") == "model"]
    assert [row["payload"]["phase"] for row in models] == ["waiting", "started", "result", "started", "result", "started", "result"]
    assert [row["call_id"] for row in models] == [
        f"{result['run_id']}:model:{step}" for step in (1, 1, 1, 2, 2, 3, 3)]
    trace.emit("event", "Later unrelated event")
    assert "run_id" not in trace.history()[-1]


def test_cancelled_tool_has_one_correlated_interruption_and_no_late_result(execution, stream, monkeypatch):
    async def exercise():
        loop = asyncio.get_running_loop()
        reached, finished = asyncio.Event(), asyncio.Event()
        release = threading.Event()

        def slow_tool(_name, _args, _ctx):
            loop.call_soon_threadsafe(reached.set)
            assert release.wait(3)
            loop.call_soon_threadsafe(finished.set)
            return {"status": "completed", "_private_image_png": b"LATE-PRIVATE-PIXELS"}

        async def reply(*_args, **_kwargs):
            return executor.llm.ChatReply(content='{"tool":"window.place","args":{}}', finish_reason="stop", completion_tokens=20)

        monkeypatch.setattr(executor, "execute_capability", slow_tool)
        monkeypatch.setattr(executor.llm, "chat", reply)
        turn = asyncio.create_task(execution.run())
        try:
            await asyncio.wait_for(reached.wait(), 2)
            turn.cancel()
            with pytest.raises(asyncio.CancelledError):
                await turn
            before = encoded(trace.history())
        finally:
            release.set()
            await asyncio.wait_for(finished.wait(), 2)
        await asyncio.sleep(0)
        assert encoded(trace.history()) == before

    asyncio.run(exercise())
    tools = [row for row in trace.history() if row.get("payload", {}).get("kind") == "tool"]
    assert len(tools) == 2 and tools[0]["call_id"] == tools[1]["call_id"]
    assert tools[1]["payload"]["status"] == "interrupted"
    assert trace.history()[-1]["payload"]["status"] == "interrupted"
    assert "LATE-PRIVATE-PIXELS" not in encoded(trace.history())


@pytest.mark.parametrize("outcome", ["success", "lease_error", "lease_cancel", "provider_error", "provider_cancel"])
def test_model_wait_is_visible_before_admission_and_lifecycle_stays_correlated(execution, stream, monkeypatch, outcome):
    provider_calls = []

    async def exercise():
        reached_lease, release_lease, reached_provider = asyncio.Event(), asyncio.Event(), asyncio.Event()

        @asynccontextmanager
        async def lease(_model):
            reached_lease.set()
            await release_lease.wait()
            if outcome == "lease_error":
                raise RuntimeError("Isolated lease failure")
            yield

        async def reply(*_args, **_kwargs):
            provider_calls.append(True)
            reached_provider.set()
            if outcome == "provider_error":
                raise RuntimeError("Isolated provider failure")
            if outcome == "provider_cancel":
                await asyncio.Event().wait()
            return await execution.reply()

        monkeypatch.setattr(executor.model_runtime, "lease", lease)
        monkeypatch.setattr(executor.llm, "chat", reply)
        turn = asyncio.create_task(execution.run())
        await asyncio.wait_for(reached_lease.wait(), 2)
        waiting = trace.history()[-1]
        assert waiting["payload"]["kind"] == "model" and waiting["payload"]["phase"] == "waiting"
        assert waiting["payload"]["model"] == "isolated" and waiting["payload"]["model_label"] == "Isolated"
        assert waiting["call_id"] == f"{waiting['run_id']}:model:1" and waiting["step"] == 1
        assert not provider_calls and not turn.done()
        if outcome == "lease_cancel":
            turn.cancel()
        else:
            release_lease.set()
        if outcome == "provider_cancel":
            await asyncio.wait_for(reached_provider.wait(), 2)
            turn.cancel()
        if outcome.endswith("cancel"):
            with pytest.raises(asyncio.CancelledError):
                await turn
        elif outcome == "lease_error":
            with pytest.raises(RuntimeError, match="Isolated lease failure"):
                await turn
        else:
            result = await turn
            assert result["status"] == ("failed" if outcome == "provider_error" else "completed")

    asyncio.run(exercise())
    events = trace.history()
    models = [row for row in events if row.get("payload", {}).get("kind") == "model"]
    phases = ["waiting"]
    if not outcome.startswith("lease_"):
        phases.append("started")
    phases.append("result" if outcome == "success" else "interrupted" if outcome.endswith("cancel") else "error")
    assert [row["payload"]["phase"] for row in models] == phases
    assert len({row["call_id"] for row in models}) == 1
    assert all(row["run_id"] == events[0]["run_id"] and row["step"] == 1 for row in models)
    assert len(provider_calls) == (0 if outcome.startswith("lease_") else 1)
    assert events[-1]["payload"]["status"] == (
        "completed" if outcome == "success" else "interrupted" if outcome.endswith("cancel") else "failed")
