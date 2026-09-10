"""The real idle WebSocket close must release its subscriber before shutdown."""

import ast
import asyncio
import json
from pathlib import Path
import socket
from types import SimpleNamespace

import pytest
import uvicorn
import websockets
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect


ROUTES = [
    ("realtime_ws", "/ws/realtime"),
    ("action_trace_ws", "/ws/trace"),
    ("knowledge_activity_ws", "/ws/activity"),
]


def route(runtime, name="realtime_ws"):
    # Isolate the actual route from the production app's model/scheduler lifespan.
    path = Path(__file__).parents[1] / "harness/interfaces/api/app.py"
    tree = ast.parse(path.read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
             and n.name in {"_serve_websocket_events", name}]
    for node in nodes:
        node.decorator_list = []
    namespace = {
        "asyncio": asyncio, "WebSocket": WebSocket, "WebSocketDisconnect": WebSocketDisconnect,
        "realtime": SimpleNamespace(RUNTIME=runtime),
        "trace": runtime, "knowledge_activity": runtime,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


@pytest.mark.parametrize("queued_event", [False, True])
@pytest.mark.parametrize("name,path", ROUTES)
@pytest.mark.parametrize("disconnect_side", ["client", "server"])
def test_idle_disconnect_releases_event_subscription(queued_event, name, path, disconnect_side):
    async def scenario():
        subscribers = set()
        finished = asyncio.Event()
        if name == "realtime_ws":
            event = {"type": "runtime", "reason": "input_level", "state": {"input_level": 0.25}}
            snapshot = {"type": "state", "state": {"phase": "off"}}
            delivered = event
        elif name == "action_trace_ws":
            event = {"id": "fixture", "seq": 1, "channel": "status", "line": "Fixture event"}
            snapshot = {"type": "snapshot", "entries": [], "cursor": 0,
                        "gap": False, "journal_available": True}
            delivered = {"type": "entry", "entry": event, "cursor": 1}
        else:
            event = {"phase": "query_started", "refs": ["Tasks/query"]}
            snapshot = {"type": "snapshot", "entries": []}
            delivered = {"type": "activity", **event}

        def subscribe():
            queue = asyncio.Queue()
            subscribers.add(queue)
            if queued_event:
                queue.put_nowait(event)
            return queue

        handler = route(SimpleNamespace(
            subscribe=subscribe, unsubscribe=subscribers.remove,
            snapshot=lambda: {"phase": "off"}, history=lambda: [],
            replay=lambda _after=None: snapshot,
        ), name)

        async def endpoint(ws):
            try:
                await handler(ws)
            finally:
                finished.set()

        app = Starlette(routes=[WebSocketRoute(path, endpoint)])
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        server = uvicorn.Server(uvicorn.Config(app, lifespan="off", log_level="critical"))
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async def ready():
                while not server.started:
                    if serving.done():
                        await serving
                    await asyncio.sleep(0)

            await asyncio.wait_for(ready(), 2)
            async with websockets.connect(f"ws://127.0.0.1:{listener.getsockname()[1]}{path}") as client:
                assert json.loads(await asyncio.wait_for(client.recv(), 1)) == snapshot
                if queued_event:
                    assert json.loads(await asyncio.wait_for(client.recv(), 1)) == delivered
                assert len(subscribers) == 1
                # This presentation-only route ignores client data and keeps
                # receiving until the genuine protocol disconnect arrives.
                await client.send("presentation-only client message")
                if disconnect_side == "server":
                    # Uvicorn must finish with its ordinary close handshake,
                    # while the event producer stays completely quiet.
                    server.should_exit = True
                    await asyncio.wait_for(serving, 1)
            await asyncio.wait_for(finished.wait(), 1)
            assert subscribers == set()
            if disconnect_side == "client":
                assert not serving.done(), "Cleanup must happen before server shutdown"
        finally:
            server.should_exit = True
            await asyncio.wait_for(serving, 3)
            listener.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("name,_path", ROUTES)
def test_handler_cancellation_joins_sender_and_disconnect_reader(name, _path):
    async def scenario():
        subscribers = set()
        started, reader_cancelled = asyncio.Event(), asyncio.Event()

        def subscribe():
            queue = asyncio.Queue()
            subscribers.add(queue)
            return queue

        async def accept():
            pass

        async def send_json(_payload):
            pass

        async def receive():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                reader_cancelled.set()

        handler = route(SimpleNamespace(
            subscribe=subscribe, unsubscribe=subscribers.remove, snapshot=lambda: {"phase": "off"},
            history=lambda: [],
            replay=lambda _after=None: {"type": "snapshot", "entries": [], "cursor": 0,
                                       "gap": False, "journal_available": True},
        ), name)
        running = asyncio.create_task(handler(SimpleNamespace(
            accept=accept, send_json=send_json, receive=receive, query_params={},
        )))
        await asyncio.wait_for(started.wait(), 1)
        running.cancel()
        await asyncio.wait_for(running, 1)
        assert reader_cancelled.is_set()
        assert subscribers == set()

    asyncio.run(scenario())
