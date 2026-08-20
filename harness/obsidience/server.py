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
        out.append({"ref": n.ref, "title": n.title,
                    "status": n.meta.get("status", "draft"),
                    "assignee": str(n.meta.get("assignee", "")),
                    "runbook": str(n.meta.get("runbook", "")),
                    "schedule": n.meta.get("schedule"),
                    "blocked_reason": n.meta.get("blocked_reason"),
                    "last_run": n.meta.get("last_run")})
    return out


@app.post("/api/tasks/{ref:path}/run")
async def run_now(ref: str):
    note = load_note(ref + ".md") or resolver().resolve(ref)
    if not note or note.kind != "task":
        raise HTTPException(404, f"task not found: {ref}")
    return await run_task(note)


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
    charter = res.resolve("Operator")
    system = ("You are the Obsidience Operator — the voice of this Obsidian vault. "
              "Ground answers in the vault context provided; cite notes as [[wikilinks]]. "
              "Be concise and direct.\n\n" + (charter.body if charter else ""))
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
