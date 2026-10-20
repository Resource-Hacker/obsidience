"""The Code graph's adapter to the local codebase-memory-mcp provider.

The unmodified provider (``obsidience-code-graph.service``) owns indexing, its
graph store and the native ``/api/layout``; this module owns the one
connection to it: the configured URL and project (``[graphs]``
``codebase_url``/``codebase_project``), the layout client, the saved-file
refresh (``code_refresh.py``) and the agent-activity listener
(``agent_activity.py``), all acquired and released by ``lifespan``. ``project``
returns the display projection; the API route only serializes it.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
import hashlib
import logging

import httpx

from ..config import CONFIG

DEFAULT_URL = "http://127.0.0.1:9749"
_client: httpx.Client | None = None
_refresh = None


class CodeGraphUnavailable(RuntimeError):
    """The provider could not be read; nothing was projected."""


def _settings() -> dict:
    return CONFIG.extras.get("graphs", {})


def project_id() -> str:
    """The provider project: ``codebase_project``, else the repository path with ``/`` replaced by ``-``."""
    return str(_settings().get("codebase_project", str(CONFIG.project_root).strip("/").replace("/", "-")))


def url() -> str:
    return str(_settings().get("codebase_url", DEFAULT_URL)).rstrip("/")


def status() -> dict | None:
    """The saved-file refresh state, or None outside the adapter's lifetime."""
    return _refresh.status() if _refresh else None


def request_refresh() -> dict | None:
    if _refresh is None:
        return None
    _refresh.request()
    return _refresh.status()


@asynccontextmanager
async def lifespan():
    global _client, _refresh
    from .agent_activity import CodeActivity
    from .code_refresh import CodeRefresh
    with httpx.Client(timeout=20, trust_env=False) as client:
        _client = client
        project = project_id()
        _refresh = CodeRefresh(CONFIG.project_root, project, url())
        _refresh.start()
        capture = CodeActivity(CONFIG.project_root, project, _refresh.request)
        try:
            try:
                await capture.start()
            except OSError:
                logging.getLogger(__name__).warning("Code graph activity listener unavailable", exc_info=True)
                await capture.close()
            yield
        finally:
            await capture.close()
            await _refresh.close()
            _refresh = None
            _client = None


def project(limit: int) -> dict:
    """The provider's layout as display nodes and edges with stable identities."""
    client = _client
    if client is None:
        raise CodeGraphUnavailable("Code graph adapter is starting")
    project = project_id()
    try:
        # The native provider gives the complete response a one-second send
        # deadline. Callers run this in a worker thread (FastAPI's pool), so the
        # large transfer and its projection stay off the conversational loop.
        response = client.get(url() + "/api/layout", params={"project": project, "max_nodes": limit})
        response.raise_for_status()
        doc = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logging.getLogger(__name__).warning("Code graph unavailable: %s; project=%s; status=%s; detail=%s",
            type(exc).__name__, project, getattr(getattr(exc, "response", None), "status_code", "transport"), str(exc)[:240])
        raise CodeGraphUnavailable("Codebase MCP graph is unavailable (" + type(exc).__name__ + "). Enable its local graph viewer.") from exc
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
    index = _refresh.status() if _refresh else {"state": "snapshot"}
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
    return {"provider": "codebase-memory-mcp", "graph_id": "code:" + project,
            "nodes": nodes, "edges": edges, "total": doc.get("total_nodes", len(nodes)),
            "limited": len(nodes) < doc.get("total_nodes", len(nodes)),
            "missed": len(doc.get("missed_graph", {}).get("nodes", [])), "project": project, "index": index}


