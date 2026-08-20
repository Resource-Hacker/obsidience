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
            nodes.append({"id": ref, "title": title, "kind": kind,
                          "status": m.get("status"), "assignee": m.get("assignee"),
                          "tags": m.get("tags") or []})
            for target in json.loads(link_json):
                t = resolver.resolve(target)
                if t and t.ref in known and t.ref != ref:
                    links.append({"source": ref, "target": t.ref})
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
