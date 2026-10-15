"""Public-safe Discord graph and real activity; never the general trace stream."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket

from ....discord.presentation import ActivityProjection, opaque, snapshot
from ....execution import activity
from ..streams import serve_websocket_events

router = APIRouter(prefix='/api/discord/presentation', tags=['discord-presentation'])


@router.get('')
async def graph():
    try:
        return (await asyncio.to_thread(snapshot)).graph
    except Exception:
        return {'available': False, 'nodes': [], 'links': [], 'group': None}


@router.websocket('/activity')
async def graph_activity(ws: WebSocket):
    await ws.accept()
    queue = activity.subscribe()

    async def send_events():
        filtered = None
        replayed = {}

        async def send_snapshot():
            nonlocal filtered, replayed
            view = await asyncio.to_thread(snapshot)
            filtered = ActivityProjection(view)
            history = activity.history()
            operations = activity.operations()
            # Replay the current coherent transactions, never animate completed
            # historical turns as though they were happening on camera now.
            events = [event for entry in history if (event := filtered.project(entry)) is not None]
            active = {opaque(run) for run in filtered.runs}
            replayed = {id(entry): entry for entry in history}
            replayed.update({id(operation): operation for operation in operations})
            await ws.send_json({'type': 'graph', 'graph': view.graph})
            for event in events:
                if event['run_id'] in active:
                    await ws.send_json(event)
            for operation in operations:
                if (event := filtered.project({'type': 'operation', 'operation': operation})) is not None:
                    await ws.send_json(event)

        await send_snapshot()
        while True:
            entry = await queue.get()
            if id(entry) in replayed or id(entry.get('operation')) in replayed:
                continue
            if entry.get('phase') == 'graph_changed' or (entry.get('type') == 'operation'
                    and entry.get('operation', {}).get('refresh') is True
                    and entry['operation'].get('graph_id') == filtered.view.memory_graph_id):
                # Permission changes replace the graph and replay only currently
                # active runs under its newly accepted scope.
                await send_snapshot()
            elif (event := filtered.project(entry)) is not None:
                await ws.send_json(event)

    try:
        await serve_websocket_events(ws, send_events)
    finally:
        activity.unsubscribe(queue)
