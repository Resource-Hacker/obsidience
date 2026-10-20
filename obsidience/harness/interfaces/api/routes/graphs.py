"""HTTP routes of the Memory and Code graph views (projections: ``graphs/memory.py``, ``graphs/codebase.py``)."""
from __future__ import annotations

import json
from typing import Literal
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from ....graphs import codebase, memory as memory_projection
from ....memory.hindsight import MEMORY, memory_ref
from ....knowledge.vault import load_note
from ....knowledge.projection import agent_scene

router = APIRouter(prefix="/api/graphs")


def _graph_response(content: dict) -> Response:
    """JSONResponse's exact bytes for a graph whose last keys are nodes and edges.

    One json.dumps of a complete memory graph (tens of MB) holds the GIL for
    a quarter second, stalling the event loop; slices let it run in between.
    """
    encode = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode
    parts = [encode({key: value for key, value in content.items() if key not in ("nodes", "edges")})[:-1]]
    for key in ("nodes", "edges"):
        items = content[key]
        parts += [f',"{key}":[', ",".join(encode(items[i:i + 2000])[1:-1] for i in range(0, len(items), 2000)), "]"]
    return Response("".join(parts + ["}"]).encode(), media_type="application/json")


@router.get("/memory/banks")
def banks(agent_ref: str = "", bank: str = "", scene: Literal["executive", "all"] = "executive"):
    result = []
    selected_bank = bank
    for bank, ref in MEMORY.banks.items():
        note = load_note(ref + ".md")
        if note and (not agent_ref or ref == agent_ref) and (not selected_bank or bank == selected_bank) \
                and (agent_ref or selected_bank or scene == "all" or agent_scene(ref) == scene):
            result.append({"id": bank, "name": note.title, "agent_ref": ref, "scene": agent_scene(ref),
                           "count": len(MEMORY.records.get(bank, {}))})
    return {"banks": sorted(result, key=lambda b: ("Executive" not in b["agent_ref"], b["name"])),
            "status": MEMORY.status()["status"]}


@router.get("/memory")
def memory_graph(bank: str, q: str = "", limit: int | None = Query(None, ge=1, le=5000), since: str = ""):
    try:
        content = memory_projection.project(bank, q, limit, since)
    except KeyError:
        raise HTTPException(404, "Select an available Agent memory bank") from None
    except memory_projection.MemoryGraphUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc
    return JSONResponse(content) if content.get("delta") else _graph_response(content)


@router.get("/memory/record")
async def memory_record(bank: str, id: str):
    if bank not in MEMORY.banks or not id or "/" in id:
        raise HTTPException(404, "Unknown memory identity")
    try:
        doc = await MEMORY.api("GET", quote(bank, safe="") + "/memories/" + quote(id, safe=""))
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(503, "Memory record is unavailable") from exc
    from ....execution.activity import emit_operation
    emit_operation("read", "returned", [memory_ref(bank, id)], label="Reading memory",
                   graph_id="memory:" + bank)
    return doc


@router.get("/code")
def code_graph(limit: int = Query(14000, ge=100, le=20000)):
    try:
        return JSONResponse(codebase.project(limit))
    except codebase.CodeGraphUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc


@router.post("/code/refresh", status_code=202)
async def refresh_code_graph():
    state = codebase.request_refresh()
    if state is None:
        raise HTTPException(503, "Code graph adapter is starting")
    return state
