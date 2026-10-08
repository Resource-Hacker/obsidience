"""Presentation adapters for native Hindsight and codebase-memory-mcp graphs."""
from __future__ import annotations

from array import array
from collections import Counter, deque
from contextlib import asynccontextmanager, nullcontext
import hashlib
import json
import logging
import threading
from urllib.parse import quote
import uuid

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from ..config import CONFIG
from ..memory.hindsight import MEMORY, hindsight_auth_headers, memory_ref
from ..knowledge.vault import load_note

router = APIRouter(prefix="/api/graphs")
CODE_PROJECT = str(CONFIG.project_root).strip("/").replace("/", "-")
CLIENT: httpx.Client | None = None
CODE_REFRESH = None
# Stats that move whenever Hindsight writes, links or consolidates a bank.
MEMORY_PROBE = ("total_nodes", "total_links", "total_documents", "total_observations",
                "last_memory_write_at", "last_consolidated_at")


class MemoryView:
    """Compact identities of a bank's recent complete graph projections.

    Hindsight has no graph delta API, and its derived entity edges slide when a
    memory is added, so a change still re-reads the provider once. The display
    then receives only changed records and their changed edges. Each revision
    is exactly what a client holding it shows; a few are kept so an aborted
    client fetch can still continue by delta.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.reset()

    def reset(self):
        self.revisions = deque(maxlen=4)
        self.ids: dict[str, int] = {}
        self.names: list[str] = []
        self.styles: dict[tuple, int] = {}
        self.style_list: list[tuple] = []

    def edge_keys(self, edges) -> array:
        keys = array("Q")
        for edge in edges:
            ends = []
            for name in (edge["source"], edge["target"]):
                index = self.ids.get(name)
                if index is None:
                    index = self.ids[name] = len(self.names)
                    self.names.append(name)
                ends.append(index)
            style = (edge["kind"], edge["weight"], edge["color"])
            code = self.styles.get(style)
            if code is None:
                code = self.styles[style] = len(self.style_list)
                self.style_list.append(style)
            keys.append(ends[0] << 36 | ends[1] << 16 | code)
        if len(self.names) > 1 << 20 or len(self.style_list) > 1 << 16:
            # Identities no longer fit their key fields; start a fresh cursor.
            self.reset()
            raise OverflowError("memory graph identities exceed the delta key space")
        return keys

    def edge(self, key: int) -> dict:
        kind, weight, color = self.style_list[key & 0xFFFF]
        return {"source": self.names[key >> 36], "target": self.names[key >> 16 & 0xFFFFF],
                "kind": kind, "weight": weight, "color": color}


MEMORY_VIEWS: dict[str, MemoryView] = {}


@asynccontextmanager
async def lifespan():
    global CLIENT, CODE_REFRESH
    from .codex import CodeActivity
    from .code_refresh import CodeRefresh
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
def banks():
    result = []
    for bank, ref in MEMORY.banks.items():
        note = load_note(ref + ".md")
        if note:
            result.append({"id": bank, "name": note.title, "agent_ref": ref,
                           "count": len(MEMORY.records.get(bank, {}))})
    return {"banks": sorted(result, key=lambda b: ("Executive" not in b["agent_ref"], b["name"])),
            "status": MEMORY.status()["status"]}


@router.get("/memory")
def memory_graph(bank: str, q: str = "", limit: int | None = Query(None, ge=1, le=5000), since: str = ""):
    if bank not in MEMORY.banks:
        raise HTTPException(404, "Select an available Agent memory bank")
    if CLIENT is None:
        raise HTTPException(503, "Memory graph adapter is starting")
    # Only the complete default view has a revision cursor; filtered views stay
    # one-shot. One projection per bank at a time, so its revisions stay ordered.
    view = MEMORY_VIEWS.setdefault(bank, MemoryView()) if not q and limit is None else None
    with view.lock if view else nullcontext():
        return _memory_graph(bank, q, limit, since, view)


def _memory_graph(bank: str, q: str, limit: int | None, since: str, view: MemoryView | None):
    # Like Code, decode and serialize the full graph in FastAPI's worker pool.
    # Large historical banks must not block the conversational event loop.
    url = CONFIG.extras["memory"]["hindsight_url"].rstrip("/") + "/v1/default/banks/" + quote(bank, safe="")

    def read(path, **params):
        # Same-machine transport: avoid upstream synchronous gzip work on a
        # full graph while that server is also answering recall requests.
        result = CLIENT.get(url + path, params=params,
                            headers={"Accept-Encoding": "identity", **hindsight_auth_headers()})
        result.raise_for_status()
        return result.json()

    try:
        # Native /graph is newest-first, not a representative timeline sample.
        # Size the default request from the provider, so an older day cannot
        # disappear just because more recent memories filled a fixed page.
        count = limit
        if count is None:
            stats = read("/stats")
            count = stats["total_nodes"]
            # Read before the graph: a write between them only causes a re-read.
            probe = (tuple(stats.get(key) for key in MEMORY_PROBE), MEMORY.updated_at)
            latest = view.revisions[-1] if view and view.revisions else None
            if latest and since == latest["revision"] and probe == latest["probe"]:
                return JSONResponse({"provider": "hindsight", "graph_id": "memory:" + bank, "delta": True,
                                     "since": since, "revision": since, "nodes": [], "removed": [],
                                     "edges": [], "removed_edges": [], "total": latest["total"],
                                     "limited": latest["limited"], "updated_at": MEMORY.updated_at})
        doc = read("/graph", limit=count, q=q[:300])
        if limit is None and len(doc.get("nodes", [])) < doc.get("total_units", 0):
            doc = read("/graph", limit=doc["total_units"], q=q[:300])
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(503, "Hindsight graph is unavailable") from exc
    records = MEMORY.records.get(bank, {})
    # A native consolidation may commit a new observation before its final
    # webhook refreshes the shared cache. Resolve those exact visible records
    # from the same provider so their types and evidence remain accurate.
    visible = {str(entry["data"]["id"]) for entry in doc.get("nodes", [])}
    if visible - records.keys():
        records = dict(records)
        offset = 0
        while visible - records.keys():
            page = read("/memories/list", limit=1000, offset=offset)
            records.update({str(r["id"]): r for r in page["items"]})
            offset += len(page["items"])
            if not page["items"] or offset >= page["total"]:
                break
    rows = {str(row["id"]): row for row in doc.get("table_rows", [])}
    nodes = []
    for entry in doc.get("nodes", []):
        item = entry["data"]
        identifier = str(item["id"])
        record = records.get(identifier, {})
        row = rows.get(identifier, record)
        kind = row.get("fact_type", "memory")
        text = str(item.get("text", item.get("label", "")))
        nodes.append({"id": memory_ref(bank, identifier), "name": text[:100],
                      "text": text, "kind": kind,
                      "color": {"observation": "#c4b5fd", "experience": "#38bdf8", "world": "#5eead4"}.get(kind, "#94a3b8"),
                      # Operational history follows when a fact was mentioned.
                      # A cited historical event has its own occurrence date;
                      # neither that date nor import time moves the discussion.
                      "date": row.get("mentioned_at") or "",
                      "occurred_start": row.get("occurred_start"),
                      "occurred_end": row.get("occurred_end"),
                      "entities": item.get("entities", ""),
                      "tags": row.get("tags", []), "proof_count": row.get("proof_count", 0),
                      "support": [memory_ref(bank, str(s)) for s in record.get("source_memory_ids") or []],
                      "ref": memory_ref(bank, identifier)})
    ids = {node["id"] for node in nodes}
    edges = []
    for entry in doc.get("edges", []):
        item = entry["data"]
        source, target = (memory_ref(bank, str(item[k])) for k in ("source", "target"))
        if source in ids and target in ids:
            edges.append({"source": source, "target": target, "kind": item.get("linkType", "related"),
                          "weight": item.get("weight", 1), "color": item.get("color", "#6d8baa")})
    # Native observation support IDs are provenance edges owned by Hindsight.
    # Its graph endpoint currently omits them; list records supply exact pairs.
    for node in nodes:
        for support in node["support"]:
            if support in ids and support != node["id"]:
                edges.append({"source": support, "target": node["id"], "kind": "supports",
                              "weight": 1, "color": "#a78bfa"})
    result = {"provider": "hindsight", "graph_id": "memory:" + bank,
              "total": doc.get("total_units", len(nodes)),
              "limited": len(nodes) < doc.get("total_units", len(nodes)),
              "updated_at": MEMORY.updated_at}
    if view is None:
        return JSONResponse({**result, "nodes": nodes, "edges": edges})
    try:
        keys = view.edge_keys(edges)
    except OverflowError:
        return JSONResponse({**result, "nodes": nodes, "edges": edges})
    hashes = {node["id"]: hash(json.dumps(node, sort_keys=True, separators=(",", ":"))) for node in nodes}
    base = next((entry for entry in view.revisions if since and entry["revision"] == since), None)
    touched = set() if base is None else (base["nodes"].keys() - hashes.keys()) | {
        name for name, value in hashes.items() if base["nodes"].get(name) != value}
    if base is not None and not touched:
        # Same records. Hindsight re-samples its capped direct links (equal
        # weights, LIMIT 10000) and tied entity windows on every read; that
        # churn is not a change, so the shown sample stays.
        view.revisions.remove(base)
        view.revisions.append(base)
        base["probe"] = probe
        return JSONResponse({**result, "delta": True, "since": since, "revision": since,
                             "nodes": [], "removed": [], "edges": [], "removed_edges": []})
    if base is not None and len(touched) <= len(nodes) // 2:
        # Edges at changed, added or removed records come from this read; the
        # rest keep the client's sample until the next complete load.
        ends = {view.ids[name] for name in touched if name in view.ids}

        def at(key):
            return key >> 36 in ends or key >> 16 & 0xFFFFF in ends

        before = Counter(key for key in base["edges"] if at(key))
        after = Counter(key for key in keys if at(key))
        state = array("Q", [key for key in base["edges"] if not at(key)])
        state.extend(after.elements())
        view.revisions.append({"revision": uuid.uuid4().hex, "probe": probe, "nodes": hashes, "edges": state,
                               "total": result["total"], "limited": result["limited"]})
        return JSONResponse({**result, "delta": True, "since": since, "revision": view.revisions[-1]["revision"],
                             "nodes": [node for node in nodes if node["id"] in touched],
                             "removed": [name for name in base["nodes"] if name not in hashes],
                             "edges": [view.edge(key) for key in (after - before).elements()],
                             "removed_edges": [view.edge(key) for key in (before - after).elements()]})
    # First load, Harness restart, expired cursor or a reset bank: complete graph.
    view.revisions.append({"revision": uuid.uuid4().hex, "probe": probe, "nodes": hashes, "edges": keys,
                           "total": result["total"], "limited": result["limited"]})
    return JSONResponse({**result, "revision": view.revisions[-1]["revision"], "nodes": nodes, "edges": edges})


@router.get("/memory/record")
async def memory_record(bank: str, id: str):
    if bank not in MEMORY.banks or not id or "/" in id:
        raise HTTPException(404, "Unknown memory identity")
    try:
        doc = await MEMORY.api("GET", quote(bank, safe="") + "/memories/" + quote(id, safe=""))
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(503, "Memory record is unavailable") from exc
    from ..execution.activity import emit_operation
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
