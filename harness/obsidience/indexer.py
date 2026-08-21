"""SQLite index: notes table + FTS5 + embeddings (brute-force cosine, fine at vault scale).

Embeddings via fastembed (same lib/model family as the old authority); reuses the
machine's offline model dir when present, otherwise downloads once.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from pathlib import Path

import numpy as np

from .config import CONFIG
from .task_taxonomy import (
    TASK_TAXONOMY_NODES,
    child_ids,
    node_id,
)
from .vault import Note, iter_notes

_SCHEMA = """
CREATE TABLE IF NOT EXISTS notes(
  ref TEXT PRIMARY KEY, path TEXT, title TEXT, kind TEXT, mtime REAL,
  hash TEXT, meta TEXT, links TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
  ref UNINDEXED, title, body, tokenize='porter unicode61'
);
CREATE TABLE IF NOT EXISTS embeddings(
  ref TEXT PRIMARY KEY, hash TEXT, dim INTEGER, vec BLOB
);
CREATE TABLE IF NOT EXISTS runs(
  id TEXT PRIMARY KEY, task_ref TEXT, agent TEXT, started REAL, finished REAL,
  status TEXT, summary TEXT, receipt_path TEXT, trace TEXT
);
"""

_embedder = None
_embed_lock = threading.Lock()


def _meta_links(value) -> list[str]:
    if not value:
        return []
    return [str(item) for item in (value if isinstance(value, list) else [value])]


def _get_embedder():
    global _embedder
    with _embed_lock:
        if _embedder is None:
            from fastembed import TextEmbedding
            cache = CONFIG.embed_cache_dir
            kwargs = {"cache_dir": cache} if cache and Path(cache).exists() else {}
            _embedder = TextEmbedding(model_name=CONFIG.embed_model, **kwargs)
    return _embedder


def embed_texts(texts: list[str]) -> np.ndarray:
    vecs = np.array(list(_get_embedder().embed(texts)), dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / np.clip(norms, 1e-9, None)


class Index:
    def __init__(self):
        self.db = sqlite3.connect(CONFIG.db_path, check_same_thread=False)
        self.db.executescript(_SCHEMA)
        self.lock = threading.Lock()

    # ---------- sync ----------

    def sync(self, embed: bool = True) -> dict:
        notes = iter_notes()
        seen, added, updated = set(), 0, 0
        with self.lock:
            existing = {r[0]: r[1] for r in self.db.execute("SELECT ref, hash FROM notes")}
            to_embed: list[Note] = []
            for n in notes:
                seen.add(n.ref)
                h = hashlib.sha256((json.dumps(n.meta, sort_keys=True, default=str) + n.body).encode()).hexdigest()
                if existing.get(n.ref) == h:
                    continue
                added += n.ref not in existing
                updated += n.ref in existing
                self.db.execute(
                    "INSERT OR REPLACE INTO notes(ref,path,title,kind,mtime,hash,meta,links) VALUES(?,?,?,?,?,?,?,?)",
                    (n.ref, n.path, n.title, n.kind, n.mtime, h,
                     json.dumps(n.meta, default=str), json.dumps(n.links)),
                )
                self.db.execute("DELETE FROM notes_fts WHERE ref=?", (n.ref,))
                self.db.execute("INSERT INTO notes_fts(ref,title,body) VALUES(?,?,?)",
                                (n.ref, n.title, n.body))
                to_embed.append(n)
            removed = set(existing) - seen
            for ref in removed:
                self.db.execute("DELETE FROM notes WHERE ref=?", (ref,))
                self.db.execute("DELETE FROM notes_fts WHERE ref=?", (ref,))
                self.db.execute("DELETE FROM embeddings WHERE ref=?", (ref,))
            self.db.commit()
        if embed and to_embed:
            texts = [f"{n.title}\n{n.body[:4000]}" for n in to_embed]
            vecs = embed_texts(texts)
            with self.lock:
                for n, v in zip(to_embed, vecs):
                    self.db.execute(
                        "INSERT OR REPLACE INTO embeddings(ref,hash,dim,vec) VALUES(?,?,?,?)",
                        (n.ref, "", len(v), v.tobytes()),
                    )
                self.db.commit()
        return {"total": len(notes), "added": added, "updated": updated, "removed": len(removed)}

    # ---------- search lanes ----------

    def fts(self, query: str, k: int) -> list[tuple[str, float]]:
        q = " OR ".join(t for t in query.replace('"', " ").split() if len(t) > 1) or query
        try:
            rows = self.db.execute(
                "SELECT ref, bm25(notes_fts) FROM notes_fts WHERE notes_fts MATCH ? ORDER BY bm25(notes_fts) LIMIT ?",
                (q, k)).fetchall()
        except sqlite3.OperationalError:
            return []
        return [(r[0], -r[1]) for r in rows]

    def vector(self, query: str, k: int) -> list[tuple[str, float]]:
        rows = self.db.execute("SELECT ref, vec FROM embeddings").fetchall()
        if not rows:
            return []
        qv = embed_texts([query])[0]
        refs = [r[0] for r in rows]
        mat = np.stack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
        sims = mat @ qv
        order = np.argsort(-sims)[:k]
        return [(refs[i], float(sims[i])) for i in order]

    # ---------- graph ----------

    def graph(self) -> dict:
        nodes, links = [], []
        rows = self.db.execute("SELECT ref, title, kind, meta, links FROM notes").fetchall()
        known = {r[0] for r in rows}
        from .vault import Resolver, Note as _N
        stubs = [_N(path=r[0] + ".md", title=r[1], meta={}, body="") for r in rows]
        resolver = Resolver(stubs)
        for ref, title, kind, meta, link_json in rows:
            m = json.loads(meta)
            child_refs = [str(item).strip("[]") for item in _N(
                path=ref + ".md", title=title, meta=m, body="").children]
            nodes.append({"id": ref, "title": title, "kind": kind,
                          "status": m.get("status"), "assignee": m.get("assignee"),
                          "children": child_refs,
                          "subtasks": child_refs if kind == "task" else [],
                          "checkouts": {field: _meta_links(m.get(field))
                                        for field in ("tools", "skills", "runbooks", "tasks")
                                        if m.get(field)},
                          "tags": m.get("tags") or []})
            for target in json.loads(link_json):
                t = resolver.resolve(target)
                if t and t.ref in known and t.ref != ref:
                    links.append({"source": ref, "target": t.ref})

        # Dotted Tool names are callable namespaces, so project them as the
        # same expandable article hierarchy used by explicit sub* fields.
        tool_rows = [(ref, json.loads(meta)) for ref, _title, kind, meta, _links in rows
                     if kind == "tool"]
        explicit_children = set()
        for _ref, meta in tool_rows:
            for raw in _meta_links(meta.get("subtools")):
                target = resolver.resolve(raw)
                if target:
                    explicit_children.add(target.ref)
        tool_parts = {
            ref: ref.rsplit("/", 1)[-1].split(".")
            for ref, _meta in tool_rows if ref not in explicit_children and "." in ref.rsplit("/", 1)[-1]
        }
        namespaces = sorted({
            ".".join(parts[:depth])
            for parts in tool_parts.values() for depth in range(1, len(parts))
        })
        namespace_set = set(namespaces)
        for namespace in namespaces:
            prefix = namespace.split(".")
            child_namespaces = sorted(
                child for child in namespace_set
                if child.startswith(namespace + ".") and len(child.split(".")) == len(prefix) + 1
            )
            child_tools = sorted(
                ref for ref, parts in tool_parts.items()
                if parts[:len(prefix)] == prefix and len(parts) == len(prefix) + 1
            )
            nodes.append({
                "id": f"@library/Tools/{namespace}",
                "title": prefix[-1],
                "kind": "tool",
                "status": None,
                "assignee": None,
                "children": [*(f"@library/Tools/{child}" for child in child_namespaces), *child_tools],
                "subtasks": [],
                "checkouts": {},
                "tags": ["generated-index", "tool-namespace"],
                "synthetic": True,
            })

        # The owner's wiki/research ontology is a stateless Task index. Real
        # Task notes occupy matching leaves, but their authored subtasks remain
        # the interpreter's only executable control-flow edges.
        by_id = {node["id"]: node for node in nodes}
        for taxonomy_order, taxonomy_node in enumerate(TASK_TAXONOMY_NODES):
            projected_id = node_id(taxonomy_node.path, known)
            projected_children = child_ids(taxonomy_node.path, known)
            existing = by_id.get(projected_id)
            if existing:
                existing["title"] = taxonomy_node.title
                existing["children"] = projected_children
                existing["tags"] = [*existing.get("tags", []), "task-taxonomy"]
                existing["checkoutable"] = True
                existing["order"] = taxonomy_order
                continue
            projected = {
                "id": projected_id,
                "title": taxonomy_node.title,
                "kind": "task",
                "status": None,
                "assignee": None,
                "children": projected_children,
                "subtasks": [],
                "checkouts": {},
                "tags": ["generated-index", "task-taxonomy"],
                "synthetic": True,
                "checkoutable": True,
                "order": taxonomy_order,
            }
            nodes.append(projected)
            by_id[projected_id] = projected
        return {"nodes": nodes, "links": links}

    # ---------- runs ----------

    def record_run(self, **kw) -> None:
        with self.lock:
            self.db.execute(
                "INSERT OR REPLACE INTO runs(id,task_ref,agent,started,finished,status,summary,receipt_path,trace)"
                " VALUES(:id,:task_ref,:agent,:started,:finished,:status,:summary,:receipt_path,:trace)", kw)
            self.db.commit()

    def runs(self, limit: int = 50) -> list[dict]:
        cols = ["id", "task_ref", "agent", "started", "finished", "status", "summary", "receipt_path"]
        rows = self.db.execute(
            f"SELECT {','.join(cols)} FROM runs ORDER BY started DESC LIMIT ?", (limit,)).fetchall()
        return [dict(zip(cols, r)) for r in rows]


INDEX = Index()
