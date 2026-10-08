"""Actual ASGI streams with isolated receipts and inert execution/lifespan owners."""

from __future__ import annotations

import asyncio
from collections import deque
from importlib import import_module
import json
from types import SimpleNamespace
from urllib.parse import urlencode

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from obsidience.harness.config import CONFIG
from obsidience.harness.conversation.runtime import ConversationRuntime
from obsidience.harness.conversation.store import ConversationStore
from obsidience.harness.execution import trace


api = import_module("obsidience.harness.interfaces.api.app")
# LocalClientsOnly requires a loopback Host; websocket_connect ignores base_url.
LOCAL_HOST = f"{CONFIG.host}:{CONFIG.port}"


def receive(socket):
    # Bound failures using the TestClient session's existing in-memory transport.
    async def read():
        return await asyncio.wait_for(socket._send_rx.receive(), 3)

    message = socket.portal.call(read)
    if message["type"] == "websocket.close":
        raise WebSocketDisconnect(message["code"], message.get("reason", ""))
    return json.loads(message["text"])


@pytest.fixture
def stream_trace(monkeypatch, isolated_task_ledger):
    monkeypatch.setattr(trace, "_HISTORY", deque())
    monkeypatch.setattr(trace, "_HISTORY_CHARS", 0)
    monkeypatch.setattr(trace, "_SUBSCRIBERS", set())
    monkeypatch.setattr(trace, "_LEDGER", None)
    monkeypatch.setattr(trace, "_LOOP", None)
    monkeypatch.setattr(trace, "_JOURNAL_AVAILABLE", True)
    original_subscribe = trace.subscribe

    def subscribe():
        # TestClient has no app lifespan; hydrate on the actual socket owner loop.
        trace.start(isolated_task_ledger)
        return original_subscribe()

    monkeypatch.setattr(trace, "subscribe", subscribe)
    yield isolated_task_ledger
    trace.stop()


def test_trace_cursor_replay_live_delivery_and_reconnect(stream_trace):
    for number in range(4):
        stream_trace.append_trace({"id": str(number), "channel": "status", "line": str(number)})
    client = TestClient(api.app, headers={"host": LOCAL_HOST})  # No model/scheduler/scene lifespan.
    with client.websocket_connect("/ws/trace?after=2") as socket:
        frame = receive(socket)
        assert frame["type"] == "replay" and frame["gap"] is False
        assert [entry["seq"] for entry in frame["entries"]] == [3, 4]
        socket.portal.call(trace.emit, "status", "Live exact event")
        live = receive(socket)
        assert live["type"] == "entry" and live["cursor"] == 5
        assert live["entry"]["line"] == "Live exact event"
    assert not trace._SUBSCRIBERS
    with client.websocket_connect("/ws/trace?after=4") as socket:
        reconnect = receive(socket)
        assert reconnect["type"] == "replay"
        assert reconnect["entries"] == [live["entry"]]
    assert not trace._SUBSCRIBERS
    client.close()


@pytest.mark.parametrize("burst,expected_type,first_sequence", [(150, "replay", 2), (510, "snapshot", 12)])
def test_slow_trace_subscriber_recovers_gap_without_duplicate_delivery(stream_trace, burst, expected_type, first_sequence):
    stream_trace.append_trace({"id": "initial", "line": "Initial"})
    client = TestClient(api.app, headers={"host": LOCAL_HOST})
    with client.websocket_connect("/ws/trace?after=1") as socket:
        initial = receive(socket)
        assert initial["cursor"] == 1 and initial["entries"] == []

        def publish_burst():
            # No yield: the real 100-entry subscriber queue must overflow.
            for number in range(burst):
                trace.emit("status", f"Burst {number}")

        socket.portal.call(publish_burst)
        recovered = receive(socket)
        assert recovered["type"] == expected_type
        assert recovered["gap"] is (expected_type == "snapshot")
        assert recovered["cursor"] == burst + 1
        assert [entry["seq"] for entry in recovered["entries"]] == list(range(first_sequence, burst + 2))
        socket.portal.call(trace.emit, "status", "After recovered gap")
        next_entry = receive(socket)
        assert next_entry["type"] == "entry"
        assert next_entry["entry"]["line"] == "After recovered gap"
        assert next_entry["cursor"] == burst + 2
    assert not trace._SUBSCRIBERS
    client.close()


@pytest.mark.parametrize("cursor", ["", "-1", "1.5", "abc", "١", "9" * 17])
def test_trace_rejects_invalid_cursor_before_subscribing(stream_trace, cursor):
    client = TestClient(api.app, headers={"host": LOCAL_HOST})
    with client.websocket_connect("/ws/trace?" + urlencode({"after": cursor})) as socket:
        with pytest.raises(WebSocketDisconnect) as error:
            receive(socket)
        assert error.value.code == 1008
    assert not trace._SUBSCRIBERS
    client.close()


def test_chat_accepts_and_steers_same_live_turn_without_waiting_for_completion(monkeypatch, stream_trace):
    store = ConversationStore(stream_trace)
    runtime = ConversationRuntime(store)
    monkeypatch.setattr(api, "CONVERSATION", store)
    monkeypatch.setattr(api.conversation_runtime, "RUNTIME", runtime)
    async def context_status():
        return {"type": "context", "used_tokens": 0}

    monkeypatch.setattr(runtime, "context_status", context_status)
    submissions, ended = [], []
    original_submit = runtime.submit

    async def submit(text, **kwargs):
        submissions.append((text, kwargs))
        assert kwargs == {"source": "text", "wait": False, "memory_writeback": True}
        return await original_submit(text, **kwargs)

    async def run(_text, _generation, _turn, **_kwargs):
        runtime._steering.activate("isolated-active-run")
        try:
            await asyncio.Event().wait()
        finally:
            ended.append(True)

    monkeypatch.setattr(runtime, "submit", submit)
    monkeypatch.setattr(runtime, "_run_turn", run)
    client = TestClient(api.app, headers={"host": LOCAL_HOST})
    with client.websocket_connect("/ws/chat") as socket:
        try:
            # Conversation first; the (possibly cold) context meter follows.
            assert [receive(socket)["type"] for _ in range(3)] == ["history", "active_turn", "context"]
            socket.send_json({"text": "Research the exact article"})
            original = receive(socket)
            assert original["type"] == "turn"
            active = receive(socket)
            assert active["type"] == "active_turn" and active["accepting_clarification"] is True
            assert active["turn_id"] == original["turn"]["id"]
            socket.send_json({"type": "steer", "text": "Use the updated date", "expected_turn_id": active["turn_id"]})
            clarification, receipt = receive(socket), receive(socket)
            assert clarification["type"] == "turn"
            assert clarification["turn"]["run_id"] == "isolated-active-run"
            assert receipt == {"type": "steering", "status": "queued",
                "turn_id": clarification["turn"]["id"], "active_turn_id": active["turn_id"]}
            assert runtime._turn_task is not None and not runtime._turn_task.done()
            assert [turn["text"] for turn in runtime._steering.pending] == ["Use the updated date"]
            socket.send_json({"type": "steer", "text": "Stale correction", "expected_turn_id": "old-turn"})
            rejected = receive(socket)
            assert rejected["type"] == "error" and "no longer accepting" in rejected["text"]
            assert [turn["text"] for turn in store.history()] == ["Research the exact article", "Use the updated date"]
            assert len(submissions) == 1
        finally:
            socket.portal.call(runtime.cancel)
    assert ended == [True] and not store._subscribers
    client.close()


@pytest.mark.parametrize("failure", ["review", "model", "intake", "realtime", "enqueue"])
def test_lifespan_startup_failure_unwinds_all_acquired_owners(monkeypatch, isolated_task_ledger, failure):
    from contextlib import asynccontextmanager
    from obsidience.harness.execution.deepseek import bridge, sessions
    from obsidience.harness.graphs import api as graph_views
    from obsidience.harness.knowledge import intake
    from obsidience.harness.memory import hindsight
    from obsidience.harness.models import llm
    from obsidience.harness.realtime import tracking

    calls = []

    def record(name, fail_at=None, result=None):
        def operation(*_args, **_kwargs):
            calls.append(name)
            if failure == fail_at:
                raise RuntimeError("isolated startup failure: " + failure)
            return result
        return operation

    def asynchronous(name, fail_at=None, result=None):
        async def operation(*args, **kwargs):
            return record(name, fail_at, result)(*args, **kwargs)
        return operation

    monkeypatch.setattr(api.trace, "start", record("trace.start"))
    monkeypatch.setattr(api.trace, "stop", record("trace.stop"))
    monkeypatch.setattr(llm, "start_provider_client", asynchronous("provider.start"))
    monkeypatch.setattr(llm, "close_provider_client", asynchronous("provider.close"))
    monkeypatch.setattr(hindsight.MEMORY, "start", asynchronous("memory.start"))
    monkeypatch.setattr(hindsight.MEMORY, "close", asynchronous("memory.close"))

    @asynccontextmanager
    async def graph_views_lifespan():
        calls.append("graphs.start")
        try:
            yield
        finally:
            calls.append("graphs.stop")

    monkeypatch.setattr(graph_views, "lifespan", graph_views_lifespan)
    monkeypatch.setattr(bridge, "BRIDGE", SimpleNamespace(start=asynchronous("bridge.start"), close=asynchronous("bridge.close")))
    monkeypatch.setattr(sessions, "reconcile", asynchronous("native.reconcile"))
    monkeypatch.setattr(tracking, "restore", record("camera.restore"))
    monkeypatch.setattr(tracking, "stop", record("camera.stop"))
    monkeypatch.setattr(api.review, "recover_groups", record("review", "review"))
    monkeypatch.setattr(api.scheduler, "reconcile_interrupted_runs", record("reconcile"))
    monkeypatch.setattr(api.source, "list_sources", record("sources"))
    def publish_system(*, sync):
        assert sync is False
        calls.append("system.publish")
        return {"status": "ready", "changed": 0}
    monkeypatch.setattr(api.system_knowledge, "refresh_system_knowledge", publish_system)
    monkeypatch.setattr(api.INDEX, "sync", record("index.sync"))
    monkeypatch.setattr(api.retrieval, "prewarm_fast_context", record("prewarm"))
    monkeypatch.setattr(api.model_runtime, "initialize", asynchronous("model.initialize", "model", [{}]))
    monkeypatch.setattr(api.model_runtime, "shutdown", asynchronous("model.shutdown"))
    monkeypatch.setattr(api.shell_scene, "SCENE", SimpleNamespace(start=record("scene.start"), stop=asynchronous("scene.stop")))
    monkeypatch.setattr(intake, "SourceIntake", lambda: SimpleNamespace(start=record("intake.start", "intake"), stop=record("intake.stop")))
    monkeypatch.setattr(api.realtime, "RUNTIME", SimpleNamespace(restore=asynchronous("realtime.restore", "realtime"), shutdown=asynchronous("realtime.shutdown")))
    monkeypatch.setattr(api.conversation_runtime, "RUNTIME", SimpleNamespace(cancel=asynchronous("conversation.cancel")))
    monkeypatch.setattr(api.scheduler, "shutdown", asynchronous("scheduler.shutdown"))
    monkeypatch.setattr(api.scheduler, "enqueue_named_event", record("enqueue", "enqueue"))

    async def loop():
        await asyncio.Event().wait()

    monkeypatch.setattr(api.scheduler, "loop", loop)

    async def exercise():
        with pytest.raises(RuntimeError, match="isolated startup failure"):
            async with api.lifespan(api.app):
                pytest.fail("startup unexpectedly succeeded")

    asyncio.run(exercise())
    cleanup = [name for name in calls if name.endswith((".stop", ".shutdown", ".close", ".cancel"))]
    base = ["graphs.stop", "memory.close", "provider.close", "trace.stop"]
    native = ["bridge.close", "model.shutdown", *base]
    expected = {
        "review": base,
        "model": ["model.shutdown", *base],
        "intake": ["intake.stop", "scene.stop", *native],
        "realtime": ["camera.stop", "realtime.shutdown", "intake.stop", "scene.stop", *native],
        "enqueue": ["scheduler.shutdown", "conversation.cancel", "camera.stop", "realtime.shutdown",
                    "intake.stop", "scene.stop", *native],
    }
    assert cleanup == expected[failure]
    if failure != "review":
        assert calls.index("sources") < calls.index("system.publish") < calls.index("index.sync")
        assert calls.index("index.sync") < calls.index("prewarm")
