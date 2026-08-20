"""FastAPI daemon: REST + WebSocket surface for the UI and CLI."""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from . import llm, retrieval, review, scheduler, voice
from .config import CONFIG
from .executor import run_task
from .indexer import INDEX
from .vault import iter_notes, load_note, resolver


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


@app.get("/api/notes/{ref:path}")
def get_note(ref: str):
    note = load_note(ref + ".md") or resolver().resolve(ref)
    if not note:
        raise HTTPException(404, f"note not found: {ref}")
    return {"ref": note.ref, "title": note.title, "kind": note.kind,
            "meta": {k: str(v) for k, v in note.meta.items()}, "body": note.body}


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
        out.append({"ref": n.ref, "title": n.title,
                    "status": n.meta.get("status", "draft"),
                    "assignee": str(n.meta.get("assignee", "")),
                    "runbook": str(n.meta.get("runbook", "")),
                    "subtasks": len(refs),
                    "subtask_refs": refs,
                    "reasoning_effort": effort,
                    "schedule": n.meta.get("schedule"),
                    "blocked_reason": n.meta.get("blocked_reason"),
                    "last_run": n.meta.get("last_run")})
    return out


@app.post("/api/tasks")
async def create_task(payload: dict):
    """Owner surface (Jobs pane / CLI): assign a task directly — trusted writer."""
    from .vault import slugify, write_note
    title = str(payload.get("title", "")).strip()
    if not title:
        raise HTTPException(400, "title required")
    ref = f"Tasks/{slugify(title)}.md"
    if load_note(ref):
        raise HTTPException(409, f"task already exists: {ref}")
    meta: dict = {"title": title, "kind": "task",
                  "status": "pending" if payload.get("start") else "draft"}
    if payload.get("assignee"):
        meta["assignee"] = str(payload["assignee"])
    if payload.get("runbook"):
        meta["runbook"] = str(payload["runbook"])
    if payload.get("subtasks"):
        meta["subtasks"] = [str(s) for s in payload["subtasks"]][:9]
    if payload.get("schedule"):
        meta["schedule"] = str(payload["schedule"])
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
    try:
        effort = llm.normalize_reasoning_effort(payload.get("reasoning_effort"))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    meta = dict(note.meta)
    meta["reasoning_effort"] = effort
    write_note(note.path, meta, note.body)
    INDEX.sync()
    return {"task": note.ref, "reasoning_effort": effort}


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
