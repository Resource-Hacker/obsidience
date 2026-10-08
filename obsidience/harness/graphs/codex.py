"""Display-only Codex/Claude Code tool receipts and repository file-change notifications.

Observe new public tool-call records in the local Codex and Claude Code journals.
Reasoning, messages, arguments, source contents and command output never enter
the activity stream. This adapter cannot invoke a tool, alter either agent or
write either graph.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
import hashlib
import json
from pathlib import Path
import re

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from ..execution.activity import emit_operation

TOOLS = {"search_graph": ("search", "Found"), "search_code": ("search", "Found"),
         "trace_path": ("trace", "Traced"), "get_code_snippet": ("read", "Read"),
         "get_architecture": ("read", "Architecture"), "detect_changes": ("read", "Inspected changes"),
         "index_status": ("read", "Index status"), "check_index_coverage": ("read", "Checked coverage")}
IGNORED = {".git", "node_modules", "__pycache__", ".venv", ".artifacts", "out", ".pytest_cache",
           ".ruff_cache", "state", "vault", "evidence", "defaults"}
EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".mjs", ".qml", ".css", ".c", ".h", ".sh", ".toml"}


def result_refs(value, refs=None, depth=0):
    """Extract actual returned identities, including CBM's grouped JSON rows."""
    if refs is None:
        refs = set()
    if depth > 9 or len(refs) >= 128:
        return refs
    if isinstance(value, dict):
        if isinstance(value.get("qualified_name"), str):
            refs.add("qn:" + value["qualified_name"])
        groups = value.get("groups", [])
        if isinstance(groups, list):
            for group in groups[:128]:
                if not isinstance(group, dict):
                    continue
                prefix = group.get("qn_prefix", "")
                for row in group.get("rows", [])[:128]:
                    if isinstance(row, list) and row and isinstance(row[0], str):
                        refs.add("qn:" + (prefix + "." if prefix else "") + row[0])
        for key, child in list(value.items())[:150]:
            if key not in {"code", "source", "snippet", "arguments", "input", "reasoning", "messages"}:
                result_refs(child, refs, depth + 1)
    elif isinstance(value, list):
        for child in value[:500]:
            result_refs(child, refs, depth + 1)
    elif isinstance(value, str) and len(value) <= 2_000_000:
        try:
            parsed = json.loads(value)
        except (ValueError, RecursionError):
            parsed = None
        if parsed is not None:
            result_refs(parsed, refs, depth + 1)
        # CBM's default tree format carries the same exact qualified identities
        # as its grouped JSON. Only accept its explicit result-table header.
        prefix = None
        tree = "qn = group prefix" in value and "results:" in value
        for line in value.splitlines()[:400]:
            if len(refs) >= 128:
                break
            if tree:
                group = re.fullmatch(r"(.*?) \(.*\):", line)
                if group:
                    prefix = group[1]
                elif prefix is not None and line.startswith("  "):
                    name = line.strip().split(" ", 1)[0]
                    if name:
                        refs.add("qn:" + (prefix + "." if prefix else "") + name)
            text = line.strip()
            if text.startswith(("{", "[")):
                try:
                    result_refs(json.loads(text), refs, depth + 1)
                except (ValueError, RecursionError):
                    pass
    return refs


class CodeActivity(FileSystemEventHandler):
    def __init__(self, project: Path, project_id: str = "", on_saved=None):
        self.project = project.resolve()
        self.on_saved = on_saved
        self.sessions = Path.home() / ".codex" / "sessions"
        # Claude Code keeps one journal per session, with subagents nested below it.
        self.claude = Path.home() / ".claude" / "projects"
        self.graph_id = "code:" + (project_id or str(self.project).strip("/").replace("/", "-"))
        self.offsets = {}
        self.pending = OrderedDict()
        self.observer = None
        self.task = None
        self.loop = None
        self.paths = set()
        self.changed = asyncio.Event()

    async def start(self):
        self.loop = asyncio.get_running_loop()
        # Attach at the live edge. Opening a view or restarting never replays
        # historical work as though the agent were doing it again.
        def live_edge():
            journals = list(self.sessions.glob("*/*/*/*.jsonl")) if self.sessions.is_dir() else []
            if self.claude.is_dir():
                journals += self.claude.glob("*/*.jsonl")
                journals += self.claude.glob("*/*/subagents/*.jsonl")
            return {str(p): p.stat().st_size for p in journals if p.is_file()}
        self.offsets = await asyncio.to_thread(live_edge)
        self.observer = Observer()
        for journals in (self.sessions, self.claude):
            if journals.is_dir():
                self.observer.schedule(self, str(journals), recursive=True)
        self.observer.schedule(self, str(self.project), recursive=False)
        for relative in ("obsidience/harness", "obsidience/shell/qml", "obsidience/shell/surfaces", "obsidience/ui/src", "obsidience/scripts"):
            directory = self.project / relative
            if directory.is_dir():
                self.observer.schedule(self, str(directory), recursive=True)
        self.observer.start()
        self.task = asyncio.create_task(self.run(), name="graph-code-activity")

    async def close(self):
        if self.observer:
            self.observer.stop()
            if self.observer.is_alive():
                await asyncio.to_thread(self.observer.join, 3)
            self.observer = None
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        for operation_id, action, label, _ in self.pending.values():
            emit_operation(action, "interrupted", [], label=label,
                           operation_id=operation_id, graph_id=self.graph_id)
        self.pending.clear()

    def on_modified(self, event):
        self.accept_path(event.src_path, event.is_directory)

    def on_created(self, event):
        self.accept_path(event.src_path, event.is_directory)

    def on_moved(self, event):
        self.accept_path(event.src_path, event.is_directory)
        self.accept_path(event.dest_path, event.is_directory)

    def on_deleted(self, event):
        self.accept_path(event.src_path, event.is_directory)

    def accept_path(self, value, directory):
        if directory or self.loop is None or self.loop.is_closed():
            return
        path = Path(value)
        if path.is_relative_to(self.sessions) or path.is_relative_to(self.claude):
            if path.suffix != ".jsonl":
                return
        elif path.is_relative_to(self.project):
            relative = path.relative_to(self.project)
            if any(p in IGNORED or p.startswith(".") for p in relative.parts) or path.suffix not in EXTENSIONS:
                return
        else:
            return
        def enqueue():
            if len(self.paths) < 256:
                self.paths.add(str(path))
                self.changed.set()
        self.loop.call_soon_threadsafe(enqueue)

    async def run(self):
        while True:
            await self.changed.wait()
            self.changed.clear()
            paths, self.paths = self.paths, set()
            for path in paths:
                try:
                    if Path(path).is_relative_to(self.sessions) or Path(path).is_relative_to(self.claude):
                        await asyncio.to_thread(self.consume, path)
                    else:
                        relative = str(Path(path).relative_to(self.project))
                        if self.on_saved:
                            self.on_saved(relative)
                        emit_operation("edit", "completed", ["file:" + relative],
                                       label="File changed · " + Path(path).name,
                                       operation_id="file:" + relative, graph_id=self.graph_id)
                except (OSError, ValueError, RecursionError):
                    # Observability cannot interrupt the operation being observed.
                    continue

    def consume(self, path):
        position = self.offsets.get(path, 0)
        with open(path, "rb") as stream:
            if stream.seek(0, 2) < position:
                position = 0
            stream.seek(position)
            while True:
                start = stream.tell()
                line = stream.readline(2_000_001)
                if not line:
                    break
                if not line.endswith(b"\n"):
                    if len(line) > 2_000_000:
                        while line and not line.endswith(b"\n"):
                            line = stream.readline(2_000_001)
                    else:
                        stream.seek(start)
                        break
                else:
                    try:
                        record = json.loads(line)
                        if record.get("type") == "response_item":
                            self.item(record.get("payload", {}), path)
                        elif record.get("type") in {"assistant", "user"}:
                            self.claude_blocks(record.get("message", {}), path)
                        elif record.get("type") == "event_msg" and record.get("payload", {}).get("type") in {"task_complete", "task_aborted"}:
                            for key in [key for key in self.pending if key[0] == path]:
                                operation_id, action, label, _ = self.pending.pop(key)
                                emit_operation(action, "interrupted", [], label=label,
                                               operation_id=operation_id, graph_id=self.graph_id)
                    except (ValueError, RecursionError):
                        pass
                self.offsets[path] = stream.tell()

    def claude_blocks(self, message, path):
        """Map Claude Code tool_use/tool_result blocks onto the Codex item shape."""
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            return
        for block in content[:64]:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                self.item({"type": "function_call", "call_id": block.get("id", ""),
                           "name": block.get("name", ""), "arguments": block.get("input", {})},
                          path, agent="Claude")
            elif block.get("type") == "tool_result":
                self.item({"type": "function_call_output", "call_id": block.get("tool_use_id", ""),
                           "output": block.get("content", "")}, path)

    def item(self, item, path, agent="Codex"):
        kind = item.get("type")
        call = str(item.get("call_id", ""))
        key = (path, call)
        if kind in {"function_call", "custom_tool_call"}:
            args = item.get("arguments", item.get("input", ""))
            if not isinstance(args, str):
                args = json.dumps(args)
            name = str(item.get("name", ""))
            matches = re.findall(r"obsidience_code__(\w+)", name + " " + args)
            if not matches and "codebase-memory-mcp" in args:
                matches = [tool for tool in TOOLS if re.search(r"\b" + tool + r"\b", args)]
            matches = list(dict.fromkeys(t for t in matches if t in TOOLS))
            if not matches:
                return
            scoped = str(self.project) in args or self.graph_id[5:] in args
            if not scoped:
                return
            operation_id = agent.lower() + ":" + hashlib.sha256((path + call).encode()).hexdigest()[:28]
            label = agent + " · " + ", ".join(TOOLS[t][1] for t in matches)
            action = TOOLS[matches[0]][0]
            self.pending[key] = (operation_id, action, label, scoped)
            while len(self.pending) > 128:
                _, (old_id, old_action, old_label, _) = self.pending.popitem(last=False)
                emit_operation(old_action, "interrupted", [], label=old_label,
                               operation_id=old_id, graph_id=self.graph_id)
            emit_operation(action, "running", [], label=label,
                           operation_id=operation_id, graph_id=self.graph_id)
        elif kind in {"function_call_output", "custom_tool_call_output"} and key in self.pending:
            operation_id, action, label, scoped = self.pending.pop(key)
            output = item.get("output", "")
            refs = sorted(result_refs(output)) if scoped else []
            emit_operation(action, "returned", refs, label=label,
                           operation_id=operation_id, graph_id=self.graph_id)
