"""FastAPI daemon: REST + WebSocket surface for the UI and CLI.

This composition root owns the lifespan, the local-client boundary, the router
includes and the /shell/knowledge mount. Each resource has one router under
routes/ over its domain owner.
"""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import PlainTextResponse
from starlette.datastructures import Headers

from ...conversation.store import CONVERSATION
from ...conversation import runtime as conversation_runtime
from ...execution import scheduler, trace
from ...knowledge import retrieval, source, system as system_knowledge
from ...knowledge.index import INDEX
from ...config import CONFIG
from ...models import runtime as model_runtime
from ...realtime import runtime as realtime
from ...shell_port import scene as shell_scene
from .routes import (
    activity, applications, chat, checkouts, discord, discord_presentation, graphs, hardware, knowledge, lights, media, memory, models,
    optimizations, realtime as realtime_routes, reviews, shell, sources, status, system, tasks, turns,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    from ...models import llm
    from ...knowledge.intake import SourceIntake

    async def stop_scheduler(task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await scheduler.shutdown()

    async with AsyncExitStack() as resources:
        trace.start(INDEX)
        resources.callback(trace.stop)
        from ...media.previews import clear_previews
        resources.callback(clear_previews)
        await llm.start_provider_client()
        resources.push_async_callback(llm.close_provider_client)
        from ...media import service as media_service
        await asyncio.to_thread(media_service.start)
        resources.push_async_callback(asyncio.to_thread, media_service.close)
        from ...memory.hindsight import MEMORY
        await MEMORY.start()
        resources.push_async_callback(MEMORY.close)
        await resources.enter_async_context(graphs.lifespan())
        scheduler.reconcile_interrupted_runs()
        source.list_sources()  # attest raw evidence before serving it
        # System facts are a deterministic projection of recorded evidence.
        # Publish before retrieval warming; this creates no model work or Task.
        await asyncio.to_thread(system_knowledge.refresh_system_knowledge, sync=False)
        INDEX.sync()
        await asyncio.to_thread(retrieval.prewarm_fast_context)
        resources.push_async_callback(model_runtime.shutdown)
        model_events = await model_runtime.initialize()
        from ...execution.adk import sessions as conversation_log
        await conversation_log.start()
        resources.push_async_callback(conversation_log.stop)
        await conversation_log.reconcile(CONVERSATION)
        await discord.start()
        resources.push_async_callback(discord.close)
        resources.push_async_callback(shell_scene.SCENE.stop)
        shell_scene.SCENE.start()
        intake = SourceIntake()
        resources.push_async_callback(asyncio.to_thread, intake.stop)
        await asyncio.to_thread(intake.start)
        resources.push_async_callback(realtime.RUNTIME.shutdown)
        from ...realtime import tracking as camera_tracking
        resources.push_async_callback(camera_tracking.close_lifecycle)
        await camera_tracking.open_lifecycle()
        await lights.open_lifecycle(realtime.RUNTIME)
        resources.push_async_callback(lights.close_lifecycle)
        await realtime.RUNTIME.restore()
        await asyncio.to_thread(camera_tracking.restore)
        resources.push_async_callback(conversation_runtime.RUNTIME.cancel)
        task = asyncio.create_task(scheduler.loop())
        resources.push_async_callback(stop_scheduler, task)
        for params in model_events:
            scheduler.enqueue_named_event("model.added", params)
        yield


app = FastAPI(title="Obsidience", lifespan=lifespan)
for resource in (memory, graphs, media, lights, discord, discord_presentation, shell, status, models, hardware, system, applications,
                 realtime_routes, knowledge, sources, checkouts, reviews, optimizations, turns, tasks,
                 activity, chat):
    app.include_router(resource.router)

# Workstation browsers visit arbitrary sites. Only non-browser local clients
# (Quickshell, CLI, turn bridges, Hindsight; no Origin) and pages served by
# this Harness may drive it. A loopback Host defeats DNS rebinding; a browser
# Origin or cross-site fetch must belong to this exact origin.
_LOCAL_HOSTS = frozenset(f"{host}:{CONFIG.port}" for host in (CONFIG.host, "127.0.0.1", "localhost"))
_LOCAL_ORIGINS = frozenset("http://" + host for host in _LOCAL_HOSTS)


class LocalClientsOnly:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in {"http", "websocket"}:
            headers = Headers(scope=scope)
            origin = headers.get("origin")
            if (headers.get("host") not in _LOCAL_HOSTS
                    or (origin is not None and origin not in _LOCAL_ORIGINS)
                    or headers.get("sec-fetch-site", "none") not in {"same-origin", "none"}):
                if scope["type"] == "websocket":
                    await send({"type": "websocket.close", "code": 1008})
                else:
                    await PlainTextResponse("Forbidden", status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


app.add_middleware(CORSMiddleware, allow_origins=sorted(_LOCAL_ORIGINS), allow_methods=["*"], allow_headers=["*"])
app.add_middleware(LocalClientsOnly)


class ShellKnowledgeFiles(StaticFiles):
    """Revalidate the mutable entry page while retaining hashed asset caching."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if path in {".", "", "index.html"} or response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Cache-Control"] = "no-cache"
        return response


app.mount(
    "/shell/knowledge",
    ShellKnowledgeFiles(
        directory=CONFIG.project_root / "obsidience" / "ui" / "out" / "renderer",
        html=True,
        check_dir=False,
    ),
    name="shell-knowledge",
)


def main():
    import sys
    import uvicorn

    # One event loop serves Realtime speech while worker threads run CPU-bound
    # projections. Each GIL-releasing call on the loop (SQLite, zlib, file I/O)
    # waits up to a switch interval to get the GIL back from such a thread;
    # 1 ms instead of 5 cut the loop's median stall ~8x and its tail ~2x in a
    # standalone reproduction, for ~10% more CPU in contended worker threads.
    sys.setswitchinterval(0.001)

    class HarnessServer(uvicorn.Server):
        def handle_exit(self, sig, frame):
            # Uvicorn drains connections before exiting the lifespan. Disarm
            # admission now so that drain cannot start another scheduled run.
            scheduler.stop_admission()
            super().handle_exit(sig, frame)

    # The native projection keeps trace/activity WebSockets open for its
    # lifetime. Development restarts must cancel those stale subscribers after
    # a short drain instead of waiting forever for the old renderer connection.
    # Every client is on this machine (LocalClientsOnly): per-message deflate
    # only spends event-loop time compressing frames for loopback.
    HarnessServer(uvicorn.Config(
        app,
        host=CONFIG.host,
        port=CONFIG.port,
        log_level="warning",
        timeout_graceful_shutdown=5,
        ws_per_message_deflate=False,
    )).run()


if __name__ == "__main__":
    main()
