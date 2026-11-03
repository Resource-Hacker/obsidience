"""Display-only Codex/Claude Code tool receipts and repository file-change notifications.

Observe new public tool-call records in the local Codex and Claude Code journals.
Reasoning, messages, source contents and command output never enter the activity
stream; of a call's arguments only a code lookup's tool and search terms do
(``lookup_detail``, owner request 2026-10-19). This adapter cannot invoke a
tool, alter either agent or write either graph.
"""
from __future__ import annotations

import asyncio
import ast
from collections import OrderedDict
import hashlib
import json
from pathlib import Path
import re
import shlex

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from ..execution.activity import emit_operation

TOOLS = {"search_graph": ("search", "Found"), "search_code": ("search", "Found"),
         "query_graph": ("search", "Queried"),
         "trace_path": ("trace", "Traced"), "get_code_snippet": ("read", "Read"),
         "get_architecture": ("read", "Architecture"), "detect_changes": ("read", "Inspected changes"),
         "index_status": ("read", "Index status"), "check_index_coverage": ("read", "Checked coverage")}
IGNORED = {".git", "node_modules", "__pycache__", ".venv", ".artifacts", "out",
           ".ruff_cache", "state", "vault", "evidence", "defaults"}
EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".mjs", ".qml", ".css", ".c", ".h", ".java", ".xml", ".sh", ".toml"}
# A lookup's public subject: the first of these present, then trace_path's route.
SUBJECTS = ("query", "name_pattern", "qn_pattern", "function_name", "qualified_name", "pattern", "semantic_query")


def _argument_object(value):
    """Read literal argument fields without evaluating journaled code."""
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        node = ast.parse(value.strip(), mode="eval").body
    except (SyntaxError, ValueError, RecursionError):
        return {}
    if not isinstance(node, ast.Dict):
        return {}
    fields = {}
    for key, child in zip(node.keys, node.values):
        key = key.id if isinstance(key, ast.Name) else key.value if isinstance(key, ast.Constant) else None
        if isinstance(key, str) and isinstance(child, ast.Constant) and isinstance(child.value, str):
            fields[key] = child.value
    return fields


def _quoted_end(text, start):
    quote, at = text[start], start + 1
    while at < len(text):
        if text[at] == "\\":
            at += 2
        elif text[at] == quote:
            return at + 1
        else:
            at += 1
    return len(text)


def _cli_lookups(command):
    """Only an actual provider CLI command head supplies project selectors."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()\n<>")
        lexer.whitespace = " \t\r"
        tokens = list(lexer)
    except ValueError:
        return []
    # One literal command only. Quoting is erased by shlex, so interpreting
    # separated clauses could turn printed examples or heredoc bodies into calls.
    if any(token and all(char in ";&|()\n<>" for char in token) for token in tokens):
        return []
    words = tokens
    if words[:1] == ["env"]:
        words = words[1:]
    while words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0]):
        words = words[1:]
    if (len(words) < 3 or Path(words[0]).name != "codebase-memory-mcp"
            or words[1] != "cli" or words[2] not in TOOLS):
        return []
    fields = {}
    for at, token in enumerate(words[3:], 3):
        flag, equals, value = token.partition("=")
        if flag in {"--project", "--repo-path"}:
            value = value if equals else words[at + 1] if at + 1 < len(words) else ""
            key = flag[2:].replace("-", "_")
            if key in fields and fields[key] != value:
                fields[key] = ""  # Conflicting selectors never attest one project.
            else:
                fields[key] = value
    return [(words[2], fields)]


def code_lookups(name, arguments):
    """Extract explicitly bound MCP/CLI calls, including functions.exec wrappers."""
    direct = re.fullmatch(r"(?:.*__)?obsidience_code__(\w+)", name)
    if direct and direct[1] in TOOLS:
        return [(direct[1], _argument_object(arguments))]
    if name.rsplit(".", 1)[-1] == "exec_command":
        return _cli_lookups(_argument_object(arguments).get("cmd", ""))
    if name.rsplit(".", 1)[-1] != "exec" or not isinstance(arguments, str):
        return []
    # Skip strings and comments: quoted/printed examples are not invocations.
    pattern = re.compile(r"tools\.(?:(?:mcp__)?obsidience_code__(\w+)|(exec_command))\s*\(\s*\{")
    result, at = [], 0
    while at < len(arguments):
        if arguments[at] in "\"'`":
            at = _quoted_end(arguments, at)
            continue
        if arguments.startswith("//", at):
            end = arguments.find("\n", at)
            at = len(arguments) if end < 0 else end + 1
            continue
        if arguments.startswith("/*", at):
            end = arguments.find("*/", at + 2)
            at = len(arguments) if end < 0 else end + 2
            continue
        match = (pattern.match(arguments, at)
                 if at == 0 or not (arguments[at - 1].isalnum() or arguments[at - 1] in "_.$") else None)
        if match is None:
            at += 1
            continue
        start, end, depth = match.end() - 1, match.end(), 1
        while end < len(arguments) and depth:
            if arguments[end] in "\"'`":
                end = _quoted_end(arguments, end)
                continue
            depth += (arguments[end] == "{") - (arguments[end] == "}")
            end += 1
        fields = _argument_object(arguments[start:end]) if depth == 0 else {}
        if match[1] in TOOLS:
            result.append((match[1], fields))
        elif match[2]:
            result.extend(_cli_lookups(fields.get("cmd", "")))
        at = end
    return result


def project_matches(fields, project, project_id):
    """Only exact explicit selectors bind activity to this repository."""
    selected = {key: fields[key] for key in ("project", "repo_path") if key in fields}
    if not selected:
        return False
    for key, value in selected.items():
        if key == "project" and value == project_id:
            continue
        if not isinstance(value, str) or not Path(value).is_absolute():
            return False
        try:
            if Path(value).resolve() != project:
                return False
        except (OSError, RuntimeError, ValueError):
            return False
    return True


def lookup_detail(tool, args, agent):
    """Who asked, which tool and what for: never the call's other arguments."""
    detail = {"agent": agent, "tool": tool}
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (ValueError, RecursionError):
            return detail
    if not isinstance(args, dict):
        return detail
    for key in SUBJECTS:
        value = args.get(key)
        if isinstance(value, list):
            value = " · ".join(str(item) for item in value[:8])
        if isinstance(value, str) and value.strip():
            detail["subject"] = " ".join(value.split())[:160]
            break
    if tool == "trace_path":
        for key in ("direction", "mode"):
            if isinstance(args.get(key), str):
                detail[key] = args[key][:24]
        if type(args.get("depth")) is int:
            detail["depth"] = args["depth"]
        if isinstance(args.get("edge_types"), list):
            detail["edge_types"] = [str(kind)[:32] for kind in args["edge_types"][:6]]
    return detail


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
        # BM25 search rows instead start with each full qualified name.
        flat = not tree and re.search(r"^results: \d+\s+\(cols: qn\b", value, re.M) is not None
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
            elif flat and line.startswith("  "):
                name = line.strip().split(" ", 1)[0]
                if "." in name:
                    refs.add("qn:" + name)
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
        for relative in ("obsidience/harness", "obsidience/lights", "obsidience/media", "obsidience/tv",
                         "obsidience/shell/qml", "obsidience/ui/src", "obsidience/scripts"):
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
        for operation_id, action, label, detail in self.pending.values():
            emit_operation(action, "interrupted", [], label=label,
                           operation_id=operation_id, graph_id=self.graph_id, detail=detail)
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
                                operation_id, action, label, detail = self.pending.pop(key)
                                emit_operation(action, "interrupted", [], label=label, operation_id=operation_id,
                                               graph_id=self.graph_id, detail=detail)
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
            lookups = code_lookups(str(item.get("name", "")), item.get("arguments", item.get("input", "")))
            # A wrapper's combined result cannot be split between project graphs.
            if not lookups or not all(project_matches(fields, self.project, self.graph_id[5:])
                                      for _tool, fields in lookups):
                return
            matches = list(dict.fromkeys(tool for tool, _fields in lookups))
            operation_id = agent.lower() + ":" + hashlib.sha256((path + call).encode()).hexdigest()[:28]
            label = agent + " · " + ", ".join(TOOLS[t][1] for t in matches)
            action = TOOLS[matches[0]][0]
            detail = lookup_detail(matches[0], lookups[0][1], agent)
            self.pending[key] = (operation_id, action, label, detail)
            while len(self.pending) > 128:
                _, (old_id, old_action, old_label, old_detail) = self.pending.popitem(last=False)
                emit_operation(old_action, "interrupted", [], label=old_label,
                               operation_id=old_id, graph_id=self.graph_id, detail=old_detail)
            emit_operation(action, "running", [], label=label,
                           operation_id=operation_id, graph_id=self.graph_id, detail=detail)
        elif kind in {"function_call_output", "custom_tool_call_output"} and key in self.pending:
            operation_id, action, label, detail = self.pending.pop(key)
            output = item.get("output", "")
            refs = sorted(result_refs(output))
            emit_operation(action, "returned", refs, label=label,
                           operation_id=operation_id, graph_id=self.graph_id, detail=detail)
