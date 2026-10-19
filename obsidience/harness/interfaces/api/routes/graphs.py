"""Presentation adapters for native Hindsight and codebase-memory-mcp graphs."""
from __future__ import annotations

from array import array
from collections import Counter, deque
from contextlib import asynccontextmanager, nullcontext
import hashlib
import json
import logging
import threading
from typing import Literal
from urllib.parse import quote
import uuid

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse, Response

from ....config import CONFIG
from ....memory.hindsight import MEMORY, hindsight_auth_headers, memory_ref
from ....knowledge.vault import load_note
from ....knowledge.projection import agent_scene

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
    client fetch can still continue by delta. The latest revision also keeps
    its records, so other clients of the same bank continue from it without
    another provider read.
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
        for source, target, kind, weight, color in edges:
            ends = []
            for name in (source, target):
                index = self.ids.get(name)
                if index is None:
                    index = self.ids[name] = len(self.names)
                    self.names.append(name)
                ends.append(index)
            style = (kind, weight, color)
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

    def latest(self, entry: dict, nodes: list[dict]) -> None:
        """Make `entry` the newest revision; only it keeps the displayed records."""
        for index, revision in enumerate(self.revisions):
            if revision is entry:
                del self.revisions[index]
                break
        for revision in self.revisions:
            revision.pop("shown", None)
        entry["shown"] = {node["id"]: node for node in nodes}
        self.revisions.append(entry)

    def since(self, base: dict, latest: dict) -> dict | None:
        """The exact change from a retained revision to the latest, without a provider read."""
        if base is latest:
            return {"nodes": [], "removed": [], "edges": [], "removed_edges": []}
        shown = latest.get("shown")
        touched = (base["nodes"].keys() - latest["nodes"].keys()) | {
            name for name, value in latest["nodes"].items() if base["nodes"].get(name) != value}
        if shown is None or len(touched) > len(shown) // 2:
            return None
        before, after = Counter(base["edges"]), Counter(latest["edges"])
        return {"nodes": [shown[name] for name in latest["nodes"] if name in touched],
                "removed": [name for name in base["nodes"] if name not in latest["nodes"]],
                "edges": [self.edge(key) for key in (after - before).elements()],
                "removed_edges": [self.edge(key) for key in (before - after).elements()]}


def _edge_dicts(edges) -> list[dict]:
    return [{"source": source, "target": target, "kind": kind, "weight": weight, "color": color}
            for source, target, kind, weight, color in edges]


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


MEMORY_VIEWS: dict[str, MemoryView] = {}


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
            # Hindsight caches its stats briefly, so right after a write they
            # trail the synchronized record list; size from the larger count.
            count = max(stats["total_nodes"], len(MEMORY.records.get(bank, {})))
            # Read before the graph: a write between them only causes a re-read.
            probe = (tuple(stats.get(key) for key in MEMORY_PROBE), MEMORY.updated_at)
            latest = view.revisions[-1] if view and view.revisions else None
            base = next((entry for entry in view.revisions if since and entry["revision"] == since), None) \
                if latest and probe == latest["probe"] else None
            change = view.since(base, latest) if base else None
            if change is not None:
                # Unchanged provider: a client at an older retained revision
                # continues from the latest one another client already read.
                return JSONResponse({"provider": "hindsight", "graph_id": "memory:" + bank, "delta": True,
                                     "since": since, "revision": latest["revision"], **change,
                                     "total": latest["total"], "limited": latest["limited"],
                                     "updated_at": MEMORY.updated_at})
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
    nodes, refs = [], {}
    for entry in doc.get("nodes", []):
        item = entry["data"]
        identifier = str(item["id"])
        refs[identifier] = memory_ref(bank, identifier)
        record = records.get(identifier, {})
        row = rows.get(identifier, record)
        kind = row.get("fact_type", "memory")
        text = str(item.get("text", item.get("label", "")))
        nodes.append({"id": refs[identifier], "name": text[:100],
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
                      "ref": refs[identifier]})
    ids = set(refs.values())
    # Edges stay (source, target, kind, weight, color) tuples: a delta needs
    # only their keys, and only a complete response builds their dicts.
    edges = []
    for entry in doc.get("edges", []):
        item = entry["data"]
        source, target = refs.get(str(item["source"])), refs.get(str(item["target"]))
        if source is not None and target is not None:
            edges.append((source, target, item.get("linkType", "related"),
                          item.get("weight", 1), item.get("color", "#6d8baa")))
    # Native observation support IDs are provenance edges owned by Hindsight.
    # Its graph endpoint currently omits them; list records supply exact pairs.
    for node in nodes:
        for support in node["support"]:
            if support in ids and support != node["id"]:
                edges.append((support, node["id"], "supports", 1, "#a78bfa"))
    result = {"provider": "hindsight", "graph_id": "memory:" + bank,
              "total": doc.get("total_units", len(nodes)),
              "limited": len(nodes) < doc.get("total_units", len(nodes)),
              "updated_at": MEMORY.updated_at}
    if view is None:
        return _graph_response({**result, "nodes": nodes, "edges": _edge_dicts(edges)})
    try:
        keys = view.edge_keys(edges)
    except OverflowError:
        return _graph_response({**result, "nodes": nodes, "edges": _edge_dicts(edges)})
    hashes = {node["id"]: hash(json.dumps(node, sort_keys=True, separators=(",", ":"))) for node in nodes}
    base = next((entry for entry in view.revisions if since and entry["revision"] == since), None)
    touched = set() if base is None else (base["nodes"].keys() - hashes.keys()) | {
        name for name, value in hashes.items() if base["nodes"].get(name) != value}
    if base is not None and not touched:
        # Same records. Hindsight re-samples its capped direct links (equal
        # weights, LIMIT 10000) and tied entity windows on every read; that
        # churn is not a change, so the shown sample stays.
        view.latest(base, nodes)
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
        view.latest({"revision": uuid.uuid4().hex, "probe": probe, "nodes": hashes, "edges": state,
                     "total": result["total"], "limited": result["limited"]}, nodes)
        return JSONResponse({**result, "delta": True, "since": since, "revision": view.revisions[-1]["revision"],
                             "nodes": [node for node in nodes if node["id"] in touched],
                             "removed": [name for name in base["nodes"] if name not in hashes],
                             "edges": [view.edge(key) for key in (after - before).elements()],
                             "removed_edges": [view.edge(key) for key in (before - after).elements()]})
    # First load, Harness restart, expired cursor or a reset bank: complete graph.
    view.latest({"revision": uuid.uuid4().hex, "probe": probe, "nodes": hashes, "edges": keys,
                 "total": result["total"], "limited": result["limited"]}, nodes)
    return _graph_response({**result, "revision": view.revisions[-1]["revision"], "nodes": nodes,
                            "edges": _edge_dicts(edges)})


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
