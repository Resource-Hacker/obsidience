"""FastAPI daemon: REST + WebSocket surface for the UI and CLI."""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from croniter import croniter

from . import llm, retrieval, review, scheduler, trace, voice
from .config import CONFIG
from .executor import run_task
from .indexer import INDEX
from .task_taxonomy import (
    TASK_TAXONOMY_BY_PATH,
    TASK_TAXONOMY_NODES,
    canonical_members as task_taxonomy_members,
    child_ids as task_taxonomy_child_ids,
    descendant_count as task_taxonomy_descendant_count,
    node_id as task_taxonomy_node_id,
)
from .vault import iter_notes, load_note, resolver, write_note


# One-vault checkout ledger: each principal owns typed links to the accepted
# Library primitives it currently carries. Order is the owner's UI order.
CHECKOUT_AGENTS = {
    "executive": "Agent/Obsidience",
    "guardian": "Agents/Heimdall/Heimdall",
    "curator": "Agents/Alexandria/Alexandria",
    "researcher": "Agents/Darwin/Darwin",
}
CHECKOUT_FIELDS = {
    "tool": "tools",
    "skill": "skills",
    "runbook": "runbooks",
    "task": "tasks",
}


def _link_values(value) -> list[str]:
    if not value:
        return []
    return [str(item) for item in (value if isinstance(value, list) else [value])]


def _note_doc(note):
    return {"ref": note.ref, "title": note.title, "kind": note.kind,
            "meta": {k: str(v) for k, v in note.meta.items()}, "body": note.body}


def _folder_index(folder: str):
    """Resolve the authored hub a graph subject absorbs, if one exists."""
    return load_note(f"{folder}/index.md") or load_note(f"{folder}/README.md")


def _tool_namespace_catalog():
    tools = [note for note in iter_notes() if note.kind == "tool"]
    res = resolver()
    explicit_children = {
        child.ref
        for parent in tools for raw in parent.children
        if (child := res.resolve(raw)) and child.kind == "tool"
    }
    eligible = {
        note.ref.rsplit("/", 1)[-1]: note
        for note in tools
        if note.ref not in explicit_children and "." in note.ref.rsplit("/", 1)[-1]
    }
    namespaces = {
        ".".join(name.split(".")[:depth])
        for name in eligible for depth in range(1, len(name.split(".")))
    }
    return eligible, namespaces


def _tool_namespace_members(namespace: str) -> list:
    eligible, _namespaces = _tool_namespace_catalog()
    prefix = namespace + "."
    return [note for name, note in eligible.items() if name.startswith(prefix)]


def _tool_namespace_article(ref: str, namespace: str | None = None) -> dict:
    eligible, namespaces = _tool_namespace_catalog()
    prefix_parts = namespace.split(".") if namespace else []
    child_namespaces = sorted(
        child for child in namespaces
        if (not namespace or child.startswith(namespace + "."))
        and len(child.split(".")) == len(prefix_parts) + 1
    )
    child_tools = sorted(
        (name, note) for name, note in eligible.items()
        if name.split(".")[:len(prefix_parts)] == prefix_parts
        and len(name.split(".")) == len(prefix_parts) + 1
    )
    lines = [
        f"- [[@library/Tools/{child}|{child.rsplit('.', 1)[-1]}]] · tool index"
        for child in child_namespaces
    ]
    lines.extend(
        f"- [[{note.ref}|{name.rsplit('.', 1)[-1]}]] · tool"
        for name, note in child_tools
    )
    title = namespace.rsplit(".", 1)[-1] if namespace else "Library · Tools"
    summary = (f"The `{namespace}` Tool namespace." if namespace
               else "The Library's accepted tools shelf, grouped by callable namespace.")
    body = summary + "\n\n## Indexed articles\n\n" + ("\n".join(lines) or "*No tools are indexed here.*")
    article_count = len(_tool_namespace_members(namespace)) if namespace else len(eligible)
    return {"ref": ref, "title": title, "kind": "index",
            "meta": {"node": "true", "articles": str(article_count)}, "body": body}


def _task_taxonomy_article(ref: str, path: str | None = None) -> dict:
    known = {note.ref for note in iter_notes() if note.kind == "task"}
    if path is None:
        children = [node for node in TASK_TAXONOMY_NODES if "/" not in node.path]
        title = "Library · Tasks"
        summary = "The Task shelf, organized by the owner-defined wiki and research taxonomy."
        article_count = len(TASK_TAXONOMY_NODES)
    else:
        node = TASK_TAXONOMY_BY_PATH[path]
        children = [TASK_TAXONOMY_BY_PATH[child] for child in node.children]
        title = node.title
        summary = f"The `{path}` Task taxonomy node."
        article_count = task_taxonomy_descendant_count(path)
    lines = [
        f"- [[{task_taxonomy_node_id(child.path, known)}|{child.title}]] · task node"
        for child in children
    ]
    body = summary + "\n\n## Indexed subtasks\n\n" + (
        "\n".join(lines)
        if lines else "*No executable task is defined at this leaf yet.*"
    )
    return {
        "ref": ref,
        "title": title,
        "kind": "task" if path is not None else "index",
        "meta": {"node": "true", "articles": str(article_count), "generated": "true"},
        "body": body,
    }


def _primitive_closure(roots, catalog) -> list:
    """Project a checked-out/assigned primitive with all same-kind descendants."""
    by_ref = {note.ref.lower(): note for note in catalog}
    by_leaf = {note.ref.rsplit("/", 1)[-1].lower(): note for note in catalog}
    closure = {note.ref: note for note in roots}
    queue = list(closure.values())
    while queue:
        parent = queue.pop(0)
        for raw in parent.children:
            target = str(raw).strip().strip("[]").split("|", 1)[0].split("#", 1)[0]
            child = by_ref.get(target.lower()) or by_leaf.get(target.rsplit("/", 1)[-1].lower())
            if not child or child.kind != parent.kind or child.ref in closure:
                continue
            closure[child.ref] = child
            queue.append(child)
    return list(closure.values())


def _virtual_index(ref: str, title: str, summary: str, children) -> dict:
    unique = {note.ref: note for note in children}
    ordered = sorted(unique.values(), key=lambda note: (note.title.lower(), note.ref.lower()))
    by_ref = {note.ref.lower(): note for note in ordered}
    by_leaf = {note.ref.rsplit("/", 1)[-1].lower(): note for note in ordered}
    child_rows: dict[str, list] = {note.ref: [] for note in ordered}
    parent_of: dict[str, str] = {}

    def resolve_child(raw):
        target = str(raw).strip().strip("[]").split("|", 1)[0].split("#", 1)[0]
        target = target[:-3] if target.lower().endswith(".md") else target
        return by_ref.get(target.lower()) or by_leaf.get(target.rsplit("/", 1)[-1].lower())

    for parent in ordered:
        for raw in parent.children:
            child = resolve_child(raw)
            if not child or child.kind != parent.kind or child.ref == parent.ref or child.ref in parent_of:
                continue
            cursor, cyclic = parent.ref, False
            while cursor in parent_of:
                cursor = parent_of[cursor]
                if cursor == child.ref:
                    cyclic = True
                    break
            if cyclic:
                continue
            parent_of[child.ref] = parent.ref
            child_rows[parent.ref].append(child)

    lines, seen = [], set()

    def add(note, depth=0):
        if note.ref in seen:
            return
        seen.add(note.ref)
        lines.append(f"{'  ' * depth}- [[{note.ref}|{note.title}]] · {note.kind}")
        for child in child_rows[note.ref]:
            add(child, depth + 1)

    for note in ordered:
        if note.ref not in parent_of:
            add(note)
    for note in ordered:
        add(note)
    contents = "\n".join(lines)
    body = summary
    if contents:
        body += f"\n\n## Indexed articles\n\n{contents}"
    else:
        body += "\n\n*No articles are currently indexed beneath this node.*"
    return {"ref": ref, "title": title, "kind": "index",
            "meta": {"node": "true", "articles": str(len(ordered))}, "body": body}


@asynccontextmanager
async def lifespan(app: FastAPI):
    INDEX.sync()
    task = asyncio.create_task(scheduler.loop())
    yield
    task.cancel()


app = FastAPI(title="Obsidience", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/status")
def status():
    notes = iter_notes()
    tasks = [n for n in notes if n.kind == "task"]
    return {
        "name": "obsidience", "vault": str(CONFIG.vault_dir),
        "notes": len(notes), "tasks": len(tasks),
        "tasks_by_status": _count_by(tasks),
        "proposals_pending": len(review.list_proposals()),
        "voice": voice.available(),
        "llm": {"base_url": CONFIG.llm_base_url, "model": CONFIG.llm_model},
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def _count_by(tasks):
    out: dict[str, int] = {}
    for t in tasks:
        s = str(t.meta.get("status", "draft"))
        out[s] = out.get(s, 0) + 1
    return out


@app.get("/api/graph")
def graph():
    return INDEX.graph()


@app.get("/api/articles/{ref:path}")
def get_article(ref: str):
    """Resolve real notes and graph subject nodes through one Reader path."""
    note = load_note(ref + ".md") or resolver().resolve(ref)
    if note:
        return _note_doc(note)

    # Match the main graph's visible vault pool. Receipts are regular graph
    # articles too, so their generated subject index must retain them.
    notes = [item for item in iter_notes() if not item.ref.startswith("Agents/")]
    if ref == "@vault":
        home = load_note("Home.md")
        return _note_doc(home) if home else _virtual_index(
            ref, "Obsidience", "The root index for this vault.", notes)
    if ref == "@library":
        primitives = [item for item in notes if item.kind in CHECKOUT_FIELDS]
        body = (
            "The curated canonical repository for Tools, Skills, Runbooks, and Tasks.\n\n"
            "## Indexed shelves\n\n"
            "- [[@library/Tools|Tools]]\n"
            "- [[@library/Skills|Skills]]\n"
            "- [[@library/Runbooks|Runbooks]]\n"
            "- [[@library/Tasks|Tasks]]"
        )
        return {"ref": ref, "title": "Library", "kind": "index",
                "meta": {"node": "true", "articles": str(len(primitives))}, "body": body}
    if ref.startswith("@library/"):
        relative = ref.removeprefix("@library/").strip("/")
        if relative == "Tools":
            return _tool_namespace_article(ref)
        if relative.startswith("Tools/"):
            namespace = relative.removeprefix("Tools/")
            if namespace not in _tool_namespace_catalog()[1]:
                raise HTTPException(404, f"tool namespace not found: {namespace}")
            return _tool_namespace_article(ref, namespace)
        if relative == "Tasks":
            return _task_taxonomy_article(ref)
        if relative.startswith("Tasks/"):
            path = relative.removeprefix("Tasks/")
            if path not in TASK_TAXONOMY_BY_PATH:
                raise HTTPException(404, f"task taxonomy node not found: {path}")
            return _task_taxonomy_article(ref, path)
        folder = relative
        kind = folder.rstrip("s").lower()
        if kind not in CHECKOUT_FIELDS:
            raise HTTPException(404, f"library node not found: {ref}")
        authored = _folder_index(folder)
        if authored:
            return _note_doc(authored)
        return _virtual_index(
            ref, f"Library · {folder}",
            f"The Library's accepted {folder.lower()} shelf.",
            [item for item in notes if item.kind == kind],
        )
    if ref.startswith("@branch/"):
        folder = ref.removeprefix("@branch/").strip("/")
        authored = _folder_index(folder)
        if authored:
            return _note_doc(authored)
        kind = folder.rstrip("s").lower()
        if kind in CHECKOUT_FIELDS:
            res = resolver()
            identity = res.resolve(CHECKOUT_AGENTS["executive"])
            raw_checkouts = _link_values(identity.meta.get(CHECKOUT_FIELDS[kind])) if identity else []
            roots = [target for raw in raw_checkouts
                     if (target := res.resolve(raw)) and target.kind == kind]
            children = _primitive_closure(roots, [item for item in notes if item.kind == kind])
        else:
            children = [item for item in notes if item.ref.startswith(f"{folder}/")]
        return _virtual_index(ref, folder, f"The {folder} index node.", children)
    if ref.startswith("@sat/"):
        parts = ref.split("/")
        if len(parts) != 3:
            raise HTTPException(404, f"agent node not found: {ref}")
        _, agent_name, folder_key = parts
        folder = folder_key.capitalize()
        kind = folder.rstrip("s").lower()
        if kind not in CHECKOUT_FIELDS:
            raise HTTPException(404, f"agent node not found: {ref}")
        identity = resolver().resolve(f"Agents/{agent_name}/{agent_name}")
        if not identity:
            raise HTTPException(404, f"agent not found: {agent_name}")
        res = resolver()
        children = [target for raw in _link_values(identity.meta.get(CHECKOUT_FIELDS[kind]))
                    if (target := res.resolve(raw)) and target.kind == kind]
        if kind == "task":
            children.extend(item for item in notes if item.kind == "task" and
                            f"Agents/{agent_name}" in str(item.meta.get("assignee", "")))
        children = _primitive_closure(children, [item for item in notes if item.kind == kind])
        return _virtual_index(
            ref, f"{agent_name} · {folder}",
            f"{agent_name}'s active and checked-out {folder.lower()}.",
            children,
        )
    raise HTTPException(404, f"article not found: {ref}")


@app.get("/api/library/checkouts")
def library_checkouts():
    """Return exact accepted Library assignments for all four principals."""
    res = resolver()
    assignments = []
    for agent, identity_ref in CHECKOUT_AGENTS.items():
        identity = res.resolve(identity_ref)
        if not identity:
            continue
        for kind, field in CHECKOUT_FIELDS.items():
            selected = set()
            for raw in _link_values(identity.meta.get(field)):
                target = res.resolve(raw)
                if target and target.kind == kind:
                    assignments.append({"agent": agent, "ref": target.ref, "kind": kind})
                    selected.add(target.ref)
            if kind == "tool":
                _eligible, namespaces = _tool_namespace_catalog()
                for namespace in sorted(namespaces):
                    members = {note.ref for note in _tool_namespace_members(namespace)}
                    if members and members <= selected:
                        assignments.append({
                            "agent": agent,
                            "ref": f"@library/Tools/{namespace}",
                            "kind": "tool",
                        })
            if kind == "task":
                known = {note.ref for note in iter_notes() if note.kind == "task"}
                for path in TASK_TAXONOMY_BY_PATH:
                    synthetic_ref = f"@library/Tasks/{path}"
                    if task_taxonomy_node_id(path, known) != synthetic_ref:
                        continue
                    members = set(task_taxonomy_members(path, known))
                    if members and members <= selected:
                        assignments.append({
                            "agent": agent,
                            "ref": synthetic_ref,
                            "kind": "task",
                        })
    return {"assignments": assignments}


@app.put("/api/library/checkouts/{ref:path}")
def set_library_checkout(ref: str, payload: dict):
    """Owner toggle for one typed Library item on one principal."""
    agent = str(payload.get("agent") or "").strip().lower()
    if agent not in CHECKOUT_AGENTS:
        raise HTTPException(400, f"unknown checkout agent: {agent or '(empty)'}")
    checked_out = payload.get("checked_out")
    if not isinstance(checked_out, bool):
        raise HTTPException(400, "checked_out must be boolean")

    res = resolver()
    namespace = ref.removeprefix("@library/Tools/") if ref.startswith("@library/Tools/") else None
    task_path = ref.removeprefix("@library/Tasks/") if ref.startswith("@library/Tasks/") else None
    if task_path and task_path not in TASK_TAXONOMY_BY_PATH:
        raise HTTPException(404, f"task taxonomy node not found: {task_path}")
    known_tasks = {note.ref for note in iter_notes() if note.kind == "task"}
    if namespace:
        targets = _tool_namespace_members(namespace)
    elif task_path:
        targets = [
            target for target_ref in task_taxonomy_members(task_path, known_tasks)
            if (target := res.resolve(target_ref))
        ]
    else:
        targets = []
    if namespace and namespace not in _tool_namespace_catalog()[1]:
        raise HTTPException(404, f"tool namespace not found: {namespace}")
    if task_path and not targets:
        raise HTTPException(409, "task taxonomy node has no executable tasks to check out yet")
    target = res.resolve(ref) if not namespace and not task_path else None
    if not targets and (not target or target.kind not in CHECKOUT_FIELDS):
        raise HTTPException(404, f"library item not found: {ref}")
    identity = res.resolve(CHECKOUT_AGENTS[agent])
    if not identity:
        raise HTTPException(500, f"checkout identity missing: {CHECKOUT_AGENTS[agent]}")

    kind = "tool" if namespace else "task" if task_path else target.kind
    field = CHECKOUT_FIELDS[kind]
    current = _link_values(identity.meta.get(field))
    retained = []
    target_refs = {item.ref for item in targets} if namespace or task_path else {target.ref}
    for raw in current:
        resolved = res.resolve(raw)
        if not resolved or resolved.ref not in target_refs:
            retained.append(raw)
    if checked_out:
        retained.extend(f"[[{target_ref}]]" for target_ref in sorted(target_refs))

    meta = dict(identity.meta)
    if retained:
        meta[field] = retained
    else:
        meta.pop(field, None)
    write_note(identity.path, meta, identity.body)
    INDEX.sync()
    return {"agent": agent, "ref": ref if namespace or task_path else target.ref,
            "kind": kind, "checked_out": checked_out}


@app.get("/api/notes/{ref:path}")
def get_note(ref: str):
    note = load_note(ref + ".md") or resolver().resolve(ref)
    if not note:
        raise HTTPException(404, f"note not found: {ref}")
    return _note_doc(note)


@app.get("/api/search")
def search(q: str):
    return retrieval.search(q)


@app.get("/api/tasks")
def tasks():
    out = []
    for n in iter_notes():
        if n.kind != "task":
            continue
        subtasks = n.meta.get("subtasks") or []
        refs = [str(x).strip("[]") for x in subtasks] if isinstance(subtasks, list) else []
        effort = str(n.meta.get("reasoning_effort", "medium")).lower()
        if effort not in llm.REASONING_BUDGETS:
            effort = "medium"
        status = str(n.meta.get("status", "draft"))
        schedule = n.meta.get("schedule")
        next_run = None
        if schedule and status in ("pending", "completed", "failed", "running"):
            try:
                next_run = croniter(str(schedule), time.time()).get_next(float)
            except (ValueError, KeyError):
                pass
        out.append({"ref": n.ref, "title": n.title,
                    "status": n.meta.get("status", "draft"),
                    "assignee": str(n.meta.get("assignee", "")),
                    "runbook": str(n.meta.get("runbook", "")),
                    "subtasks": len(refs),
                    "subtask_refs": refs,
                    "reasoning_effort": effort,
                    "schedule": schedule,
                    "next_run": next_run,
                    "blocked_reason": n.meta.get("blocked_reason"),
                    "last_run": n.meta.get("last_run")})
    return out


@app.post("/api/tasks")
async def create_task(payload: dict):
    """Owner surface (Jobs pane / CLI): create a scheduled task directly."""
    from .vault import slugify, write_note
    title = str(payload.get("title", "")).strip()
    if not title:
        raise HTTPException(400, "title required")
    schedule = str(payload.get("schedule") or "").strip()
    if schedule:
        try:
            croniter(schedule, time.time()).get_next(float)
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, f"invalid cron schedule: {schedule}") from exc
    res = resolver()
    assignee = None
    if payload.get("assignee"):
        assignee = res.resolve(str(payload["assignee"]))
        if not assignee or assignee.kind != "agent":
            raise HTTPException(400, f"agent not found: {payload['assignee']}")
    runbook = None
    if payload.get("runbook"):
        runbook = res.resolve(str(payload["runbook"]))
        if not runbook or runbook.kind != "runbook":
            raise HTTPException(400, f"runbook not found: {payload['runbook']}")
    ref = f"Tasks/{slugify(title)}.md"
    if load_note(ref):
        raise HTTPException(409, f"task already exists: {ref}")
    meta: dict = {"title": title, "kind": "task",
                  "status": "pending" if payload.get("start") or payload.get("schedule") else "draft"}
    if assignee:
        meta["assignee"] = f"[[{assignee.ref}]]"
    if runbook:
        meta["runbook"] = f"[[{runbook.ref}]]"
    if payload.get("subtasks"):
        meta["subtasks"] = [str(s) for s in payload["subtasks"]][:9]
    if schedule:
        meta["schedule"] = schedule
    if payload.get("reasoning_effort"):
        try:
            meta["reasoning_effort"] = llm.normalize_reasoning_effort(payload["reasoning_effort"])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    if payload.get("params"):
        meta["params"] = payload["params"]
    write_note(ref, meta, str(payload.get("body", "")))
    INDEX.sync()
    return {"created": ref[:-3], "status": meta["status"]}


@app.patch("/api/tasks/{ref:path}/reasoning")
async def set_task_reasoning(ref: str, payload: dict):
    """Persist an owner-selected inference setting on one task."""
    from .vault import write_note

    note = load_note(ref + ".md") or resolver().resolve(ref)
    if not note or note.kind != "task":
        raise HTTPException(404, f"task not found: {ref}")
    if str(note.meta.get("status", "draft")) == "running":
        raise HTTPException(409, "cannot edit a running task")
    try:
        effort = llm.normalize_reasoning_effort(payload.get("reasoning_effort"))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    meta = dict(note.meta)
    meta["reasoning_effort"] = effort
    write_note(note.path, meta, note.body)
    INDEX.sync()
    return {"task": note.ref, "reasoning_effort": effort}


@app.patch("/api/tasks/{ref:path}/assignee")
async def set_task_assignee(ref: str, payload: dict):
    """Persist an owner-selected agent on one executable task."""
    from .vault import write_note

    note = load_note(ref + ".md") or resolver().resolve(ref)
    if not note or note.kind != "task":
        raise HTTPException(404, f"task not found: {ref}")
    if str(note.meta.get("status", "draft")) == "running":
        raise HTTPException(409, "cannot edit a running task")
    requested = str(payload.get("assignee", "")).strip()
    agent = resolver().resolve(requested)
    if not requested or not agent or agent.kind != "agent":
        raise HTTPException(400, f"agent not found: {requested or '(empty)'}")
    assignee = f"[[{agent.ref}]]"
    meta = dict(note.meta)
    meta["assignee"] = assignee
    write_note(note.path, meta, note.body)
    INDEX.sync()
    return {"task": note.ref, "assignee": assignee}


@app.patch("/api/tasks/{ref:path}")
async def update_task(ref: str, payload: dict):
    """Owner editor for task instructions and scheduler-facing fields."""
    from .vault import write_note

    note = load_note(ref + ".md") or resolver().resolve(ref)
    if not note or note.kind != "task":
        raise HTTPException(404, f"task not found: {ref}")
    if str(note.meta.get("status", "draft")) == "running":
        raise HTTPException(409, "cannot edit a running task")
    meta = dict(note.meta)

    if "title" in payload:
        title = str(payload["title"]).strip()
        if not title:
            raise HTTPException(400, "title required")
        meta["title"] = title

    if "schedule" in payload:
        schedule = str(payload.get("schedule") or "").strip()
        if schedule:
            try:
                croniter(schedule, time.time()).get_next(float)
            except (ValueError, KeyError) as exc:
                raise HTTPException(400, f"invalid cron schedule: {schedule}") from exc
            meta["schedule"] = schedule
            if str(meta.get("status", "draft")) == "draft":
                meta["status"] = "pending"
        else:
            meta.pop("schedule", None)

    res = resolver()
    if "assignee" in payload:
        requested = str(payload.get("assignee") or "").strip()
        if requested:
            agent = res.resolve(requested)
            if not agent or agent.kind != "agent":
                raise HTTPException(400, f"agent not found: {requested}")
            meta["assignee"] = f"[[{agent.ref}]]"
        else:
            meta.pop("assignee", None)

    if "runbook" in payload:
        requested = str(payload.get("runbook") or "").strip()
        if requested:
            runbook = res.resolve(requested)
            if not runbook or runbook.kind != "runbook":
                raise HTTPException(400, f"runbook not found: {requested}")
            meta["runbook"] = f"[[{runbook.ref}]]"
        else:
            meta.pop("runbook", None)

    if "reasoning_effort" in payload:
        try:
            meta["reasoning_effort"] = llm.normalize_reasoning_effort(payload["reasoning_effort"])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    body = str(payload["body"]) if "body" in payload else note.body
    write_note(note.path, meta, body)
    INDEX.sync()
    return {"task": note.ref, "updated": True}


@app.post("/api/tasks/{ref:path}/run")
async def run_now(ref: str, payload: dict | None = None):
    note = load_note(ref + ".md") or resolver().resolve(ref)
    if not note or note.kind != "task":
        raise HTTPException(404, f"task not found: {ref}")
    try:
        requested_effort = (payload or {}).get("reasoning_effort", note.meta.get("reasoning_effort"))
        effort = llm.normalize_reasoning_effort(requested_effort)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    asyncio.create_task(run_task(note, reasoning_effort=effort))
    return {"started": note.ref, "reasoning_effort": effort}


@app.get("/api/runs")
def runs():
    return INDEX.runs()


@app.get("/api/trace")
def action_trace():
    return trace.history()


@app.websocket("/ws/trace")
async def action_trace_ws(ws: WebSocket):
    await ws.accept()
    queue = trace.subscribe()
    try:
        await ws.send_json({"type": "snapshot", "entries": trace.history()})
        while True:
            await ws.send_json({"type": "entry", "entry": await queue.get()})
    except WebSocketDisconnect:
        return
    finally:
        trace.unsubscribe(queue)


@app.get("/api/reviews")
def reviews():
    return review.list_proposals()


@app.post("/api/reviews/{name}/approve")
def approve(name: str):
    try:
        return review.approve(name)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/reviews/{name}/reject")
def reject(name: str, reason: str = ""):
    try:
        return review.reject(name, reason)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.post("/api/voice/transcribe")
async def transcribe(file: UploadFile):
    avail = voice.available()
    if not avail.get("stt"):
        raise HTTPException(503, avail.get("reason", "voice disabled"))
    data = await file.read()
    try:
        return {"text": voice.transcribe_wav(data)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"transcription failed: {exc}") from exc


@app.websocket("/ws/chat")
async def chat_ws(ws: WebSocket):
    """Operator chat: per-turn vault briefing + streamed reply."""
    await ws.accept()
    history: list[dict] = []
    res = resolver()
    # "Answer the user" is a runbook (the taxonomy's own example): the chat
    # session is the interpreter running it continuously, with its skills.
    runbook = res.resolve("Runbooks/answer-the-user")
    skill_bodies = []
    if runbook:
        for ref in (runbook.meta.get("skills") or []):
            skill = res.resolve(str(ref))
            if skill:
                skill_bodies.append(f"### Skill: {skill.title}\n{skill.body.strip()[:1500]}")
    system = "\n\n".join(filter(None, [
        "You are the Obsidience interpreter in conversation with the owner. "
        "Ground answers in the vault context provided; cite notes as [[wikilinks]]. "
        "Be concise and direct.",
        f"# Runbook: {runbook.title}\n{runbook.body.strip()}" if runbook else "",
        "\n\n".join(skill_bodies),
    ]))
    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            text = str(msg.get("text", "")).strip()
            if not text:
                continue
            brief = retrieval.briefing([text], exclude=set(), budget=1200)
            history.append({"role": "user", "content": (brief + "\n\n" if brief else "") + text})
            messages = [{"role": "system", "content": system}] + history[-12:]
            full = ""
            await ws.send_json({"type": "start"})
            async for delta in llm.chat_stream(messages):
                full += delta
                await ws.send_json({"type": "delta", "text": delta})
            history.append({"role": "assistant", "content": full})
            await ws.send_json({"type": "end", "text": full})
    except WebSocketDisconnect:
        return


def main():
    import uvicorn
    uvicorn.run(app, host=CONFIG.host, port=CONFIG.port, log_level="warning")


if __name__ == "__main__":
    main()
