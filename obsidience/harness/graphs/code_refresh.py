"""Coalesced saved-file refreshes through the existing native index owner.

No parser, graph database, polling watcher or model is owned here. CodeActivity
supplies file events; the installed provider owns incremental indexing.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path

import httpx

from ..execution.activity import emit_operation


class CodeRefresh:
    def __init__(self, project: Path, project_id: str, url: str):
        self.project, self.project_id, self.url = project, project_id, url.rstrip("/")
        self.changed = asyncio.Event()
        self.task = None
        self.state = "snapshot"
        self.updated_at = ""
        self.error = ""

    def start(self):
        self.task = asyncio.create_task(self.run(), name="graph-code-refresh")

    def request(self, _path: str = ""):
        self.state, self.error = "updating", ""
        self.changed.set()

    def status(self):
        return {"state": self.state, "updated_at": self.updated_at, "error": self.error}

    async def close(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

    async def run(self):
        async with httpx.AsyncClient(timeout=10, trust_env=False) as client:
            while True:
                await self.changed.wait()
                # One bounded save-burst window. Further saves during a refresh
                # collapse into one subsequent pass, never concurrent indexers.
                await asyncio.sleep(0.75)
                self.changed.clear()
                process = None
                try:
                    # CLI must join the already-serving provider, not introduce
                    # a replacement daemon when that optional owner is absent.
                    response = await client.get(self.url + "/api/layout", params={"project": self.project_id, "max_nodes": 1})
                    response.raise_for_status()
                    binary = Path.home() / ".local/bin/codebase-memory-mcp"
                    process = await asyncio.create_subprocess_exec(
                        str(binary), "cli", "index_repository", "--repo-path", str(self.project),
                        "--mode", "full", "--persistence", "false",
                        cwd=self.project, env={**os.environ, "CBM_LOG_LEVEL": "warn"},
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    output, _ = await asyncio.wait_for(process.communicate(), timeout=120)
                    result = json.loads(output)
                    if process.returncode or not isinstance(result, dict) or result.get("status") not in {"indexed", "up_to_date"} or result.get("project") != self.project_id:
                        raise ValueError("Index refresh did not attest the selected project")
                    if self.changed.is_set():
                        continue  # Do not advertise an intermediate save as current.
                    self.state, self.error = "ready", ""
                    self.updated_at = datetime.now(timezone.utc).isoformat()
                    emit_operation("index", "completed", [], label="Saved code index refreshed",
                                   operation_id="code-index:" + self.project_id,
                                   graph_id="code:" + self.project_id, refresh=True)
                except (OSError, ValueError, httpx.HTTPError, asyncio.TimeoutError):
                    self.state, self.error = "stale", "Index refresh unavailable; showing the last provider snapshot."
                    emit_operation("index", "failed", [], label=self.error,
                                   operation_id="code-index:" + self.project_id,
                                   graph_id="code:" + self.project_id, refresh=True)
                finally:
                    if process is not None and process.returncode is None:
                        process.kill()
                        await process.communicate()
