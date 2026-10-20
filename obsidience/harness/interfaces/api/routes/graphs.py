"""Presentation adapters for native Hindsight and codebase-memory-mcp graphs."""
from __future__ import annotations

from contextlib import asynccontextmanager
import hashlib
import json
import logging
from typing import Literal
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from ....config import CONFIG
from ....graphs import memory as memory_projection
from ....memory.hindsight import MEMORY, memory_ref
from ....knowledge.vault import load_note
from ....knowledge.projection import agent_scene

router = APIRouter(prefix="/api/graphs")
CODE_PROJECT = str(CONFIG.project_root).strip("/").replace("/", "-")
CLIENT: httpx.Client | None = None
CODE_REFRESH = None


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


@asynccontextmanager
async def lifespan():
    global CLIENT, CODE_REFRESH
    from ....graphs.agent_activity import CodeActivity
    from ....graphs.code_refresh import CodeRefresh
    with httpx.Client(timeout=20, trust_env=False) as client:
        CLIENT = client
        project = str(CONFIG.extras.get("graphs", {}).get("codebase_project", CODE_PROJECT))
        CODE_REFRESH = CodeRefresh(CONFIG.project_root, project,
            str(CONFIG.extras.get("graphs", {}).get("codebase_url", "http://127.0.0.1:9749")))
        CODE_REFRESH.start()
        capture = CodeActivity(CONFIG.project_root, project, CODE_REFRESH.request)
        try:
            try:
                await capture.start()
            except OSError:
                logging.getLogger(__name__).warning("Code graph activity listener unavailable", exc_info=True)
                await capture.close()
            yield
        finally:
            await capture.close()
            await CODE_REFRESH.close()
            CODE_REFRESH = None
            CLIENT = None


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
    if CLIENT is None:
        raise HTTPException(503, "Code graph adapter is starting")
    url = str(CONFIG.extras.get("graphs", {}).get("codebase_url", "http://127.0.0.1:9749")).rstrip("/")
    project = str(CONFIG.extras.get("graphs", {}).get("codebase_project", CODE_PROJECT))
    try:
        # The native provider gives the complete response a one-second send
        # deadline. FastAPI's existing worker pool keeps this large transfer
        # and its JSON projection independent of the conversational event loop.
        response = CLIENT.get(url + "/api/layout", params={"project": project, "max_nodes": limit})
        response.raise_for_status()
        doc = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logging.getLogger(__name__).warning("Code graph unavailable: %s; project=%s; status=%s; detail=%s",
            type(exc).__name__, project, getattr(getattr(exc, "response", None), "status_code", "transport"), str(exc)[:240])
        raise HTTPException(503, "Codebase MCP graph is unavailable (" + type(exc).__name__ + "). Enable its local graph viewer.") from exc
    # Native row numbers can change after indexing. Qualified names are the
    # provider's stable symbol identity and the identity returned by its Tools.
    # Compact display keys avoid repeating long qualified names on every edge.
    identities = {str(n["id"]): "code:" + hashlib.sha256(n["qualified_name"].encode()).hexdigest()[:24] if n.get("qualified_name")
                  else "code:" + str(n["id"]) for n in doc.get("nodes", [])}
    nodes = [{"id": identities[str(n["id"])], "name": n.get("name", ""),
              "kind": n.get("label", "symbol"), "file": n.get("file_path", ""),
              "qualified_name": n.get("qualified_name", ""),
              "start_line": n.get("start_line", 0), "end_line": n.get("end_line", 0),
              "x": n["x"], "y": n["y"], "z": n["z"],
              "size": n.get("size", 4), "color": n.get("color", "#67e8f9")}
             for n in doc.get("nodes", [])]
    # Private fingerprints of the saved source span, never source text in the
    # activity/catalog stream. Read each in-repository file once per snapshot.
    # While indexing, keep the old display; do not compare stale symbol spans.
    index = CODE_REFRESH.status() if CODE_REFRESH else {"state": "snapshot"}
    if index["state"] in {"ready", "snapshot"}:
        files = {}
        root = CONFIG.project_root.resolve()
        for node in nodes:
            relative = node["file"]
            if not relative or not (node["kind"] == "File" or node["start_line"] > 0):
                continue
            if relative not in files:
                try:
                    path = (root / relative).resolve()
                    if not path.is_relative_to(root) or path.stat().st_size > 4_000_000:
                        raise ValueError("Outside code scope")
                    files[relative] = path.read_bytes().splitlines(keepends=True)
                except (OSError, ValueError):
                    files[relative] = []
            lines = files[relative]
            start, end = node["start_line"], node["end_line"]
            span = lines if node["kind"] == "File" else lines[start - 1:end] if 0 < start <= end <= len(lines) else []
            if span:
                node["body_hash"] = hashlib.sha256(b"".join(span)).hexdigest()[:24]
    edges = [{"source": identities[str(e["source"])], "target": identities[str(e["target"])],
              "kind": e.get("type", "related")} for e in doc.get("edges", [])
             if str(e["source"]) in identities and str(e["target"]) in identities]
    nodes.sort(key=lambda node: node["id"])
    edges.sort(key=lambda edge: (edge["source"], edge["target"], edge["kind"]))
    return JSONResponse({"provider": "codebase-memory-mcp", "graph_id": "code:" + project,
            "nodes": nodes, "edges": edges, "total": doc.get("total_nodes", len(nodes)),
            "limited": len(nodes) < doc.get("total_nodes", len(nodes)),
            "missed": len(doc.get("missed_graph", {}).get("nodes", [])), "project": project, "index": index})


@router.post("/code/refresh", status_code=202)
async def refresh_code_graph():
    if CODE_REFRESH is None:
        raise HTTPException(503, "Code graph adapter is starting")
    CODE_REFRESH.request()
    return CODE_REFRESH.status()
