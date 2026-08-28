"""SQLite index: notes table + FTS5 + embeddings (brute-force cosine, fine at vault scale).

Embeddings via fastembed (same lib/model family as the old authority); reuses the
machine's offline model dir when present, otherwise downloads once.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path

import numpy as np

from ..config import CONFIG
from .tasks import (
    CANONICAL_TASK_BY_PATH,
    TASK_TAXONOMY_BY_PATH,
    TASK_TAXONOMY_NODES,
    child_ids,
    node_id,
    task_triggers,
)
from .skills import (
    build_skill_mirror,
    namespace_title,
    node_id as skill_mirror_node_id,
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
  id TEXT PRIMARY KEY, task_ref TEXT, objective TEXT NOT NULL DEFAULT '',
  agent TEXT, started REAL, finished REAL,
  status TEXT, summary TEXT, trace TEXT,
  runbook_ref TEXT, runbook_sha256 TEXT, reasoning_effort TEXT, model TEXT
);
CREATE TABLE IF NOT EXISTS source_evidence(
  id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL, source_type TEXT NOT NULL,
  source_ref TEXT NOT NULL, media_type TEXT NOT NULL, captured_at TEXT NOT NULL,
  content_sha256 TEXT NOT NULL, material_sha256 TEXT UNIQUE NOT NULL,
  material BLOB NOT NULL, created_at REAL NOT NULL,
  event_key TEXT, event_dispatched_at REAL
);
CREATE TABLE IF NOT EXISTS conversations(
  id TEXT PRIMARY KEY, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS conversation_state(
  key TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversation_turns(
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id),
  sequence INTEGER NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
  source TEXT NOT NULL CHECK(source IN ('text', 'realtime')),
  text TEXT NOT NULL,
  run_id TEXT,
  reply_to TEXT,
  state TEXT NOT NULL CHECK(state IN ('final', 'failed', 'interrupted')),
  created_at REAL NOT NULL,
  UNIQUE(conversation_id, sequence)
);
CREATE INDEX IF NOT EXISTS conversation_turns_order
  ON conversation_turns(conversation_id, sequence);
"""

_embedder = None
_embed_lock = threading.Lock()


def _meta_links(value) -> list[str]:
    if not value:
        return []
    return [str(item) for item in (value if isinstance(value, list) else [value])]


def _projected_checkout_links(field: str, value) -> list[str]:
    """Exclude descriptive Task-family roots from executable checkout projection."""
    links = _meta_links(value)
    if field != "tasks":
        return links
    projected = []
    for raw in links:
        ref = raw.strip()
        if ref.startswith("[[") and ref.endswith("]]"):
            ref = ref[2:-2]
        ref = ref.split("|", 1)[0]
        prefix = "@library/Tasks/"
        if ref.startswith(prefix):
            taxonomy_node = TASK_TAXONOMY_BY_PATH.get(ref.removeprefix(prefix))
            if taxonomy_node and taxonomy_node.kind != "task":
                continue
        projected.append(raw)
    return projected


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
        self._migrate()
        self.lock = threading.Lock()

    def _migrate(self) -> None:
        """Keep the development ledger forward-compatible without a framework."""
        run_columns = {row[1] for row in self.db.execute("PRAGMA table_info(runs)")}
        if "objective" not in run_columns:
            self.db.execute(
                "ALTER TABLE runs ADD COLUMN objective TEXT NOT NULL DEFAULT ''"
            )
        for name in (
            "runbook_ref",
            "runbook_sha256",
            "reasoning_effort",
            "model",
        ):
            if name not in run_columns:
                self.db.execute(f"ALTER TABLE runs ADD COLUMN {name} TEXT")
        turn_columns = {
            row[1] for row in self.db.execute("PRAGMA table_info(conversation_turns)")
        }
        if turn_columns and "reply_to" not in turn_columns:
            self.db.execute("ALTER TABLE conversation_turns ADD COLUMN reply_to TEXT")
        source_columns = {
            row[1] for row in self.db.execute("PRAGMA table_info(source_evidence)")
        }
        if "event_key" not in source_columns:
            self.db.execute("ALTER TABLE source_evidence ADD COLUMN event_key TEXT")
        if "event_dispatched_at" not in source_columns:
            self.db.execute(
                "ALTER TABLE source_evidence ADD COLUMN event_dispatched_at REAL"
            )
        self.db.commit()

    # ---------- sync ----------

    def sync(self, embed: bool = True) -> dict:
        notes = iter_notes()
        seen, added, updated = set(), 0, 0
        with self.lock:
            existing = {
                ref: (stored_hash, stored_kind)
                for ref, stored_hash, stored_kind in self.db.execute("SELECT ref, hash, kind FROM notes")
            }
            to_embed: list[Note] = []
            for n in notes:
                seen.add(n.ref)
                retrievable = (
                    n.meta.get("retrieval", True) is not False
                    and n.meta.get("temporary") is not True
                )
                payload = json.dumps(n.meta, sort_keys=True, default=str) + n.body
                h = hashlib.sha256(payload.encode()).hexdigest()
                transitional_h = hashlib.sha256((n.kind + "\0" + payload).encode()).hexdigest()
                prior = existing.get(n.ref)
                if prior and prior[0] in {h, transitional_h}:
                    if prior != (h, n.kind):
                        self.db.execute(
                            "UPDATE notes SET kind=?, hash=? WHERE ref=?",
                            (n.kind, h, n.ref),
                        )
                    if not retrievable:
                        self.db.execute("DELETE FROM notes_fts WHERE ref=?", (n.ref,))
                        self.db.execute("DELETE FROM embeddings WHERE ref=?", (n.ref,))
                    continue
                added += n.ref not in existing
                updated += n.ref in existing
                self.db.execute(
                    "INSERT OR REPLACE INTO notes(ref,path,title,kind,mtime,hash,meta,links) VALUES(?,?,?,?,?,?,?,?)",
                    (n.ref, n.path, n.title, n.kind, n.mtime, h,
                     json.dumps(n.meta, default=str), json.dumps(n.links)),
                )
                self.db.execute("DELETE FROM notes_fts WHERE ref=?", (n.ref,))
                self.db.execute("DELETE FROM embeddings WHERE ref=?", (n.ref,))
                if retrievable:
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
        from .source import article_refs_for_trees, normalize_source_tree, SourceError
        from .vault import Resolver, Note as _N
        stubs = [_N(path=r[0] + ".md", title=r[1], meta={}, body="") for r in rows]
        resolver = Resolver(stubs)
        for ref, title, kind, meta, link_json in rows:
            m = json.loads(meta)
            raw_scopes = _meta_links(m.get("source_trees")) if kind == "agent" else []
            source_scopes = []
            for raw_scope in raw_scopes:
                try:
                    scope = normalize_source_tree(raw_scope)
                except SourceError:
                    continue
                if scope not in source_scopes:
                    source_scopes.append(scope)
            child_refs = [str(item).strip("[]") for item in _N(
                path=ref + ".md", title=title, meta=m, body="").children]
            nodes.append({"id": ref, "title": title, "kind": kind,
                          "status": m.get("status"), "assignee": m.get("assignee"),
                          "triggers": list(task_triggers(m)) if kind == "task" else [],
                          "children": child_refs,
                          "checkouts": {field: _projected_checkout_links(field, m.get(field))
                                        for field in ("tools", "skills", "runbooks", "tasks")
                                        if m.get(field)},
                          "source_scopes": source_scopes,
                          "source_scope_refs": article_refs_for_trees(source_scopes),
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
                "title": namespace_title(prefix[-1]),
                "kind": "tool",
                "status": None,
                "assignee": None,
                "children": [*(f"@library/Tools/{child}" for child in child_namespaces), *child_tools],
                "checkouts": {},
                "tags": ["tool-namespace"],
                "synthetic": True,
            })

        # Skills mirror dotted callable Tools one-for-one. Each generated leaf
        # is an article about how to use its Tool; authored technique notes are
        # retained as its guidance sources and remain canonical at runtime.
        note_stubs = [
            _N(path=ref + ".md", title=title, meta=json.loads(meta), body="")
            for ref, title, _kind, meta, _links in rows
        ]
        for skill_order, skill_node in enumerate(build_skill_mirror(note_stubs)):
            nodes.append({
                "id": skill_mirror_node_id(skill_node.path),
                "title": skill_node.title,
                "kind": "skill",
                "status": None,
                "assignee": None,
                "children": [skill_mirror_node_id(child) for child in skill_node.children],
                "checkouts": {},
                "tags": ["skill-tool-mirror"],
                "synthetic": True,
                "order": skill_order,
            })

        # One Task article tree: semantic kind says what a node is, while its
        # direct children alone determine whether it presents as an index.
        # Canonical Task notes absorb their matching generated article identity.
        by_id = {node["id"]: node for node in nodes}
        for taxonomy_order, taxonomy_node in enumerate(TASK_TAXONOMY_NODES):
            projected_id = node_id(taxonomy_node.path, known)
            projected_children = child_ids(taxonomy_node.path, known)
            existing = by_id.get(projected_id)
            if existing:
                existing["title"] = taxonomy_node.title
                existing["kind"] = taxonomy_node.kind
                existing["children"] = projected_children
                existing["tags"] = list(dict.fromkeys([
                    *existing.get("tags", []), "task-taxonomy",
                ]))
                existing["order"] = taxonomy_order
                if taxonomy_node.triggers:
                    existing["triggers"] = list(taxonomy_node.triggers)
                    existing["tags"] = [*existing.get("tags", []), "event-triggered"]
                if taxonomy_node.routing:
                    existing["routing"] = taxonomy_node.routing
                continue
            projected = {
                "id": projected_id,
                "title": taxonomy_node.title,
                "kind": taxonomy_node.kind,
                "status": None,
                "assignee": None,
                "children": projected_children,
                "checkouts": {},
                "tags": ["task-taxonomy"],
                "synthetic": True,
                "order": taxonomy_order,
            }
            if taxonomy_node.triggers:
                projected["triggers"] = list(taxonomy_node.triggers)
                projected["tags"].append("event-triggered")
            if taxonomy_node.routing:
                projected["routing"] = taxonomy_node.routing
            nodes.append(projected)
            by_id[projected_id] = projected

        # Auto-curation and future generated Tasks declare presentation-only
        # placement without becoming operational subtasks of the taxonomy.
        for node in list(nodes):
            if node.get("kind") != "task" or node.get("synthetic"):
                continue
            row = next((row for row in rows if row[0] == node["id"]), None)
            meta = json.loads(row[3]) if row else {}
            taxonomy_path = str(meta.get("taxonomy_path", ""))
            if CANONICAL_TASK_BY_PATH.get(taxonomy_path) == node["id"]:
                # This real note already absorbed the taxonomy article at the
                # same identity. Treating that path as a placement parent would
                # make the canonical leaf its own child.
                continue
            parent_id = node_id(taxonomy_path, known) if taxonomy_path in TASK_TAXONOMY_BY_PATH else None
            parent = by_id.get(parent_id) if parent_id else None
            if parent and node["id"] not in parent["children"]:
                parent["children"].append(node["id"])
        return {"nodes": nodes, "links": links}

    # ---------- runs ----------

    def record_run(self, **kw) -> None:
        values = {
            "objective": "",
            "runbook_ref": "",
            "runbook_sha256": "",
            "reasoning_effort": "",
            "model": "",
            **kw,
        }
        with self.lock:
            self.db.execute(
                "INSERT OR REPLACE INTO runs("
                "id,task_ref,objective,agent,started,finished,status,summary,trace,"
                "runbook_ref,runbook_sha256,reasoning_effort,model) VALUES("
                ":id,:task_ref,:objective,:agent,:started,:finished,:status,:summary,:trace,"
                ":runbook_ref,:runbook_sha256,:reasoning_effort,:model)", values)
            self.db.commit()

    def runs(self, limit: int = 50) -> list[dict]:
        cols = [
            "id", "task_ref", "objective", "agent", "started", "finished", "status", "summary",
            "runbook_ref", "runbook_sha256", "reasoning_effort", "model",
        ]
        rows = self.db.execute(
            f"SELECT {','.join(cols)} FROM runs ORDER BY started DESC LIMIT ?", (limit,)).fetchall()
        return [dict(zip(cols, r)) for r in rows]

    # ---------- Executive conversation ----------

    _CONVERSATION_TURN_COLUMNS = (
        "id", "conversation_id", "sequence", "role", "source", "text",
        "run_id", "reply_to", "state", "created_at",
    )

    def active_conversation_id(self) -> str:
        """Return the persisted Executive conversation, creating it once."""
        with self.lock:
            row = self.db.execute(
                "SELECT value FROM conversation_state WHERE key='executive.active'"
            ).fetchone()
            if row:
                return str(row[0])

            conversation_id = f"conversation-{uuid.uuid4().hex}"
            self.db.execute("BEGIN IMMEDIATE")
            try:
                row = self.db.execute(
                    "SELECT value FROM conversation_state WHERE key='executive.active'"
                ).fetchone()
                if row:
                    self.db.commit()
                    return str(row[0])
                self.db.execute(
                    "INSERT INTO conversations(id,created_at) VALUES(?,?)",
                    (conversation_id, time.time()),
                )
                self.db.execute(
                    "INSERT INTO conversation_state(key,value) VALUES('executive.active',?)",
                    (conversation_id,),
                )
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
            return conversation_id

    def new_conversation(self) -> str:
        """Select a fresh Executive conversation without deleting older turns."""
        conversation_id = f"conversation-{uuid.uuid4().hex}"
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                self.db.execute(
                    "INSERT INTO conversations(id,created_at) VALUES(?,?)",
                    (conversation_id, time.time()),
                )
                self.db.execute(
                    "INSERT INTO conversation_state(key,value) VALUES('executive.active',?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (conversation_id,),
                )
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
        return conversation_id

    def append_conversation_turn(
        self,
        *,
        conversation_id: str,
        role: str,
        source: str,
        text: str,
        run_id: str | None,
        reply_to: str | None,
        state: str,
    ) -> dict:
        """Atomically append the next ordered turn to one conversation."""
        if state != "final":
            raise ValueError("only final public conversation turns may be persisted")
        if role == "user" and reply_to is not None:
            raise ValueError("a user turn cannot reply to another turn")
        if role == "assistant" and reply_to is None:
            raise ValueError("an assistant turn must reply to one exact user turn")
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                known = self.db.execute(
                    "SELECT 1 FROM conversations WHERE id=?", (conversation_id,)
                ).fetchone()
                if not known:
                    raise ValueError(f"unknown conversation: {conversation_id}")
                if reply_to is not None:
                    parent = self.db.execute(
                        "SELECT conversation_id,role FROM conversation_turns WHERE id=?",
                        (reply_to,),
                    ).fetchone()
                    if not parent or parent != (conversation_id, "user"):
                        raise ValueError("reply_to must name a user turn in this conversation")
                    if state == "final" and self.db.execute(
                        "SELECT 1 FROM conversation_turns WHERE reply_to=? "
                        "AND role='assistant' AND state='final'",
                        (reply_to,),
                    ).fetchone():
                        raise ValueError("user turn already has a final assistant reply")
                sequence = int(self.db.execute(
                    "SELECT COALESCE(MAX(sequence),0)+1 FROM conversation_turns "
                    "WHERE conversation_id=?",
                    (conversation_id,),
                ).fetchone()[0])
                row = {
                    "id": f"turn-{uuid.uuid4().hex}",
                    "conversation_id": conversation_id,
                    "sequence": sequence,
                    "role": role,
                    "source": source,
                    "text": text,
                    "run_id": run_id,
                    "reply_to": reply_to,
                    "state": state,
                    "created_at": time.time(),
                }
                self.db.execute(
                    "INSERT INTO conversation_turns("
                    + ",".join(self._CONVERSATION_TURN_COLUMNS)
                    + ") VALUES("
                    + ",".join(f":{name}" for name in self._CONVERSATION_TURN_COLUMNS)
                    + ")",
                    row,
                )
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
        return row

    def conversation_turns(
        self,
        conversation_id: str,
        *,
        before_sequence: int | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        """Read turns in chronological order, optionally selecting the newest N."""
        where = "conversation_id=?"
        params: list[object] = [conversation_id]
        if before_sequence is not None:
            where += " AND sequence<?"
            params.append(before_sequence)
        columns = ",".join(self._CONVERSATION_TURN_COLUMNS)
        if limit is None:
            query = f"SELECT {columns} FROM conversation_turns WHERE {where} ORDER BY sequence"
        else:
            query = (
                f"SELECT {columns} FROM (SELECT {columns} FROM conversation_turns "
                f"WHERE {where} ORDER BY sequence DESC LIMIT ?) ORDER BY sequence"
            )
            params.append(max(0, limit))
        with self.lock:
            rows = self.db.execute(query, params).fetchall()
        return [dict(zip(self._CONVERSATION_TURN_COLUMNS, row)) for row in rows]

    # ---------- immutable source evidence ----------

    _SOURCE_COLUMNS = (
        "id", "path", "source_type", "source_ref", "media_type", "captured_at",
        "content_sha256", "material_sha256", "material", "created_at",
        "event_key", "event_dispatched_at",
    )

    def record_source(self, **kw) -> None:
        with self.lock:
            self.db.execute(
                "INSERT INTO source_evidence("
                + ",".join(self._SOURCE_COLUMNS)
                + ") VALUES("
                + ",".join(f":{name}" for name in self._SOURCE_COLUMNS)
                + ")",
                kw,
            )
            self.db.commit()

    def _source_row(self, row) -> dict | None:
        return dict(zip(self._SOURCE_COLUMNS, row)) if row else None

    def source(self, source_id: str) -> dict | None:
        row = self.db.execute(
            f"SELECT {','.join(self._SOURCE_COLUMNS)} FROM source_evidence WHERE id=?",
            (source_id,),
        ).fetchone()
        return self._source_row(row)

    def source_by_material(self, material_sha256: str) -> dict | None:
        row = self.db.execute(
            f"SELECT {','.join(self._SOURCE_COLUMNS)} FROM source_evidence "
            "WHERE material_sha256=?",
            (material_sha256,),
        ).fetchone()
        return self._source_row(row)

    def source_by_fingerprint(
        self, lane: str, source_type: str, source_ref: str,
        media_type: str, content_sha256: str,
    ) -> dict | None:
        row = self.db.execute(
            f"SELECT {','.join(self._SOURCE_COLUMNS)} FROM source_evidence WHERE "
            "source_type=? AND source_ref=? AND media_type=? AND content_sha256=? "
            "AND path LIKE ? "
            "ORDER BY created_at LIMIT 1",
            (source_type, source_ref, media_type, content_sha256, f"{lane}/%"),
        ).fetchone()
        return self._source_row(row)

    def pending_source_events(self, limit: int = 100) -> list[dict]:
        rows = self.db.execute(
            f"SELECT {','.join(self._SOURCE_COLUMNS)} FROM source_evidence "
            "WHERE event_key IS NOT NULL AND event_dispatched_at IS NULL "
            "ORDER BY created_at LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._source_row(row) for row in rows]

    def mark_source_event_dispatched(self, source_id: str, dispatched_at: float) -> None:
        with self.lock:
            self.db.execute(
                "UPDATE source_evidence SET event_dispatched_at=? "
                "WHERE id=? AND event_key IS NOT NULL AND event_dispatched_at IS NULL",
                (dispatched_at, source_id),
            )
            self.db.commit()

    def sources(self, limit: int = 500) -> list[dict]:
        rows = self.db.execute(
            f"SELECT {','.join(self._SOURCE_COLUMNS)} FROM source_evidence "
            "ORDER BY captured_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._source_row(row) for row in rows]


INDEX = Index()
