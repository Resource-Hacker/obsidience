"""SQLite index: notes table + FTS5 + embeddings (brute-force cosine, fine at vault scale).

Embeddings via fastembed (same lib/model family as the old authority); reuses the
machine's offline model dir when present, otherwise downloads once.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import sqlite3
import threading
import time
import uuid
from collections import Counter
from collections.abc import Callable
from functools import cache
from importlib.metadata import version
from pathlib import Path

import numpy as np

from ..config import CONFIG
from .format import TASK_RUNTIME_FIELDS
from .links import metadata_ref
from .skills import (
    build_skill_mirror,
    callable_namespace,
    namespace_title,
)
from .skills import (
    node_id as skill_mirror_node_id,
)
from .tasks import (
    CANONICAL_TASK_BY_PATH,
    TASK_TAXONOMY_BY_PATH,
    TASK_TAXONOMY_NODES,
    child_ids,
    node_id,
    task_triggers,
)
from .vault import Note, Resolver, expand_primitive, iter_notes

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
CREATE INDEX IF NOT EXISTS runs_started_order ON runs(started DESC,id DESC);
CREATE TABLE IF NOT EXISTS task_runtime(
  task_ref TEXT PRIMARY KEY,
  state TEXT NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS task_activations(
  id TEXT PRIMARY KEY, task_ref TEXT NOT NULL, activation_key TEXT NOT NULL,
  state TEXT NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
  UNIQUE(task_ref,activation_key)
);
CREATE INDEX IF NOT EXISTS task_activations_task ON task_activations(task_ref,created_at);
CREATE TABLE IF NOT EXISTS tool_receipt_runs(
  run_id TEXT PRIMARY KEY, task_ref TEXT NOT NULL, params_sha256 TEXT NOT NULL,
  started REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS tool_receipts(
  run_id TEXT NOT NULL REFERENCES tool_receipt_runs(run_id), call_id TEXT NOT NULL,
  step INTEGER NOT NULL, tool TEXT NOT NULL, signature TEXT NOT NULL,
  read_only INTEGER NOT NULL CHECK(read_only IN (0,1)),
  tool_ref TEXT NOT NULL, tool_sha256 TEXT NOT NULL,
  status TEXT NOT NULL, started REAL NOT NULL, finished REAL,
  duration_ms REAL, result_sha256 TEXT NOT NULL DEFAULT '',
  result_chars INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY(run_id,call_id), UNIQUE(run_id,step)
);
CREATE INDEX IF NOT EXISTS tool_receipts_started_order ON tool_receipts(started DESC,run_id,step);
CREATE TABLE IF NOT EXISTS trace_events(
  seq INTEGER PRIMARY KEY AUTOINCREMENT, entry TEXT NOT NULL,
  encoded_bytes INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS source_evidence(
  id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL, source_type TEXT NOT NULL,
  source_ref TEXT NOT NULL, media_type TEXT NOT NULL, captured_at TEXT NOT NULL,
  content_sha256 TEXT NOT NULL, material_sha256 TEXT UNIQUE NOT NULL,
  material BLOB NOT NULL, created_at REAL NOT NULL,
  event_key TEXT, event_dispatched_at REAL,
  origin_source_id TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS feed_runtime(
  feed_id TEXT PRIMARY KEY, state TEXT NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS connection_runtime(
  connection_id TEXT PRIMARY KEY, state TEXT NOT NULL, updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS feed_items(
  feed_id TEXT NOT NULL, item_key TEXT NOT NULL, content_sha256 TEXT NOT NULL,
  source_id TEXT NOT NULL, source_path TEXT NOT NULL, captured_at TEXT NOT NULL,
  last_seen_at REAL NOT NULL DEFAULT 0, destination_ref TEXT NOT NULL DEFAULT '',
  distill_instructions TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(feed_id,item_key,content_sha256)
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
CREATE TABLE IF NOT EXISTS task_continuations(
  id TEXT PRIMARY KEY,
  caller_task_ref TEXT NOT NULL,
  caller_run_id TEXT NOT NULL UNIQUE,
  target_task_ref TEXT NOT NULL,
  target_activation_key TEXT NOT NULL,
  objective TEXT NOT NULL,
  conversation_id TEXT NOT NULL DEFAULT '',
  reply_to_turn_id TEXT NOT NULL DEFAULT '',
  reply_source TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL,
  handoff_source_id TEXT NOT NULL DEFAULT '',
  ingest_run_id TEXT NOT NULL DEFAULT '',
  result TEXT NOT NULL DEFAULT '{}',
  resumed_run_id TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  UNIQUE(target_task_ref, target_activation_key)
);
CREATE INDEX IF NOT EXISTS task_continuations_ready
  ON task_continuations(status, created_at);
CREATE TABLE IF NOT EXISTS review_decisions(
  proposal_id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL,
  task_ref TEXT NOT NULL,
  target TEXT NOT NULL,
  decision TEXT NOT NULL CHECK(decision IN ('approved', 'rejected')),
  decided_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS review_decisions_run
  ON review_decisions(run_id, decided_at);
CREATE TABLE IF NOT EXISTS deferred_observation_finalizations(
  conversation_id TEXT PRIMARY KEY,
  session_boundary TEXT NOT NULL,
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL,
  last_error TEXT NOT NULL DEFAULT ''
);
"""

_embedder = None
_embed_lock = threading.Lock()


def _meta_links(value) -> list[str]:
    if not value:
        return []
    return [str(item) for item in (value if isinstance(value, list) else [value])]


class _BindingResolver(Resolver):
    """Binding presentation accepts only unique full Article paths."""

    def __init__(self, notes: list[Note]):
        super().__init__(notes)
        counts = Counter(note.ref.casefold() for note in notes)
        self.ambiguous = {ref for ref, count in counts.items() if count > 1}

    def resolve(self, target: str) -> Note | None:
        ref = metadata_ref(target)
        if "/" not in ref or ref.startswith("@") or ref.casefold() in self.ambiguous:
            return None
        note = super().resolve(ref)
        return note if note and note.ref.casefold() == ref.casefold() else None


def _binding_shortcuts(notes: list[Note], direct_links: list[dict]) -> list[dict]:
    """Explain typed binding paths without altering stored links or authority."""
    from ..capabilities.registry import ALWAYS_ALLOWED, contract_error
    from .dependencies import agent_dependencies, resolve_dependencies, select_runbook

    res = _BindingResolver(notes)
    direct = {(link["source"], link["target"]) for link in direct_links}
    shortcuts: dict[tuple[str, str, str], dict] = {}

    def exact(value, kind: str) -> Note | None:
        refs = _meta_links(value)
        note = res.resolve(refs[0]) if len(refs) == 1 else None
        return note if note and note.kind == kind else None

    def scope(value) -> str | None:
        agent = exact(value, "agent")
        return agent.ref if agent else None

    def add(source: str, target: str, relation: str, via: list[str], agent: str | None) -> None:
        if source == target or (source, target) in direct:
            return
        edge = {"source": source, "target": target, "derived": True,
                "relation": relation, "via": via, **({"for_agent": agent} if agent else {})}
        key = (source, target, agent or "")
        previous = shortcuts.get(key)
        if previous is None or (len(via), via, relation) < (
            len(previous["via"]), previous["via"], previous["relation"],
        ):
            shortcuts[key] = edge

    paired: dict[str, Note] = {}
    pair_counts: Counter[str] = Counter()
    for skill in notes:
        if skill.kind != "skill" or skill.children or skill.meta.get("tools"):
            continue
        tool = exact(skill.meta.get("tool"), "tool")
        if tool and not tool.children:
            paired[skill.ref] = tool
            pair_counts[tool.ref] += 1
    paired = {skill: tool for skill, tool in paired.items() if pair_counts[tool.ref] == 1}

    # Paths are supplied by the same pure hierarchy expansion used at execution.
    # Ancestors supply shared guidance, but their unselected siblings never do.
    bindings: dict[str, list[tuple[Note, Note, list[str]]]] = {}
    runbooks = [note for note in notes if note.kind == "runbook"]
    for runbook in runbooks:
        agent = scope(runbook.meta.get("for_agent"))
        if runbook.meta.get("for_agent") and not agent:
            continue
        paths: dict[str, list[str]] = {}
        parts, error = expand_primitive(runbook, res, "runbook", paths=paths)
        if error or any(part.meta.get("tools") for part in parts):
            continue
        bindings[runbook.ref] = []
        for part in parts:
            for raw in _meta_links(part.meta.get("skills")):
                skill = exact(raw, "skill")
                if not skill:
                    continue
                skill_paths: dict[str, list[str]] = {}
                skills, error = expand_primitive(skill, res, "skill", paths=skill_paths)
                if error:
                    continue
                for leaf in skills:
                    tool = paired.get(leaf.ref)
                    if not tool:
                        continue
                    path = paths[part.ref] + skill_paths[leaf.ref]
                    bindings[runbook.ref].append((leaf, tool, path))
                    add(runbook.ref, tool.ref, "uses_tool", path[1:], agent)

    def task_bindings(task: Note, runbook: Note, agent: str | None) -> None:
        add(task.ref, runbook.ref, "governed_by", [], agent)
        for skill, tool, path in bindings.get(runbook.ref, []):
            add(task.ref, skill.ref, "requires_skill", path[:-1], agent)
            add(task.ref, tool.ref, "uses_tool", path, agent)
        declared_tools = {tool.ref for _skill, tool, _path in bindings.get(runbook.ref, [])}
        for skill_ref, tool in paired.items():
            if (tool.title not in ALWAYS_ALLOWED or tool.ref in declared_tools
                    or contract_error(tool.title, tool.meta.get("binding"), tool.meta.get("source"))):
                continue
            # This floor belongs to the interpreter, not the authored Runbook.
            add(task.ref, skill_ref, "requires_skill", [], agent)
            add(task.ref, tool.ref, "uses_tool", [skill_ref], agent)

    assigned_scopes: dict[str, set[str]] = {}
    for agent in (note for note in notes if note.kind == "agent"):
        for task_ref in agent_dependencies(agent, res)["tasks"]:
            assigned_scopes.setdefault(task_ref, set()).add(agent.ref)
        if agent.meta.get("skills"):
            dependency = resolve_dependencies(agent, res)
            if not dependency.get("error"):
                for skill in dependency["skills"]:
                    add(agent.ref, skill.ref, "requires_skill", [], agent.ref)
                    if tool := paired.get(skill.ref):
                        add(agent.ref, tool.ref, "uses_tool", [skill.ref], agent.ref)
    for task in (note for note in notes if note.kind == "task"):
        agent = scope(task.meta.get("assignee"))
        scopes = {agent} if not task.meta.get("assignee") or agent else set()
        scopes.update(assigned_scopes.get(task.ref, ()))
        scopes.update(scope(book.meta.get("for_agent")) for book in runbooks
                      if exact(book.meta.get("task"), "task") is task
                      and scope(book.meta.get("for_agent")))
        for agent in sorted(scopes, key=lambda value: value or ""):
            runbook, error = select_runbook(task, res, agent_ref=agent)
            if runbook and not error and runbook.ref in bindings:
                task_bindings(task, runbook, agent)
    return [shortcuts[key] for key in sorted(shortcuts)]


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


@cache
def _embedding_model_hash() -> str:
    """Fingerprint the loaded FastEmbed artifact once per process."""
    model = _get_embedder().model
    root = Path(model._model_dir)
    digest = hashlib.sha256(f"{model.model_name}\0{version('fastembed')}".encode())
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(str(path.relative_to(root)).encode())
            with path.open("rb") as stream:
                digest.update(hashlib.file_digest(stream, "sha256").digest())
    return digest.hexdigest()


def _embedding_text(title: str, body: str) -> str:
    return f"{title}\n{body[:4000]}"


from contextvars import ContextVar

_ACTIVE_OCCURRENCE: ContextVar[tuple[str, str] | None] = ContextVar("obsidience_activation", default=None)


class Index:
    def __init__(self):
        self.db_path = str(CONFIG.db_path)
        # SQLite serializes native connection calls, but CPython's shared
        # statement cache can reuse a statement across concurrent cursors
        # (python/cpython#118172), producing mixed rows or SQLITE_MISUSE.
        # Keep private cursors and existing transaction ownership; do not add
        # additional Source-read locks or alter publication lock ownership.
        if sqlite3.threadsafety != 3:
            raise RuntimeError("The shared ledger requires serialized SQLite support")
        self.db = sqlite3.connect(self.db_path, check_same_thread=False, cached_statements=0)
        self.db.executescript(_SCHEMA)
        self._migrate()
        self.lock = threading.RLock()
        self._vector_revision = 0
        self._vector_cache: dict[
            str | None,
            tuple[tuple[int, int], tuple[str, ...], np.ndarray],
        ] = {}

    def _invalidate_vector_cache_locked(self) -> None:
        self._vector_revision += 1
        self._vector_cache.clear()

    def _migrate(self) -> None:
        """Keep the development ledger forward-compatible without a framework."""
        continuation_columns = {row[1] for row in self.db.execute("PRAGMA table_info(task_continuations)")}
        if "await_publication" not in continuation_columns:
            # Existing waits retain their reviewed publication contract. New
            # caller requests choose evidence-first explicitly at creation.
            self.db.execute("ALTER TABLE task_continuations ADD COLUMN await_publication INTEGER NOT NULL DEFAULT 1")
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
            "activation_id",
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
        if "origin_source_id" not in source_columns:
            self.db.execute("ALTER TABLE source_evidence ADD COLUMN origin_source_id TEXT NOT NULL DEFAULT ''")
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS source_event_receipts "
            "ON source_evidence(event_key,event_dispatched_at)"
        )
        feed_columns = {row[1] for row in self.db.execute("PRAGMA table_info(feed_items)")}
        if "last_seen_at" not in feed_columns:
            self.db.execute("ALTER TABLE feed_items ADD COLUMN last_seen_at REAL NOT NULL DEFAULT 0")
        if "destination_ref" not in feed_columns:
            self.db.execute("ALTER TABLE feed_items ADD COLUMN destination_ref TEXT NOT NULL DEFAULT ''")
        if "distill_instructions" not in feed_columns:
            self.db.execute("ALTER TABLE feed_items ADD COLUMN distill_instructions TEXT NOT NULL DEFAULT ''")
        # Materialize legacy active/FIFO occurrences once without admitting or
        # replaying any work. task_runtime remains only their compatibility head.
        for ref, raw in self.db.execute("SELECT task_ref,state FROM task_runtime").fetchall():
            state = json.loads(raw)
            if not state.get("activation_id"):
                state = self._persist_occurrences(ref, state)
                self.db.execute("UPDATE task_runtime SET state=? WHERE task_ref=?",
                    (json.dumps(state, sort_keys=True, default=str), ref))
        self.db.commit()

    # ---------- sync ----------

    def sync(self, embed: bool = True) -> dict:
        # All publishers acquire the Article lock before the process sync lock.
        # Group Review and graph readers share this order; the ledger lock is
        # still released while encoding. flock is released even on failure.
        from .vault import _NOTE_WRITE_LOCK

        with _NOTE_WRITE_LOCK, Path(self.db_path + ".sync.lock").open("a") as lockfile:
            fcntl.flock(lockfile, fcntl.LOCK_EX)
            return self._sync(embed)

    def _sync(self, embed: bool) -> dict:
        notes = iter_notes()
        with self.lock:
            existing = {
                ref: (stored_hash, stored_kind)
                for ref, stored_hash, stored_kind in self.db.execute("SELECT ref, hash, kind FROM notes")
            }
            indexed_text = {
                ref: (title, body)
                for ref, title, body in self.db.execute("SELECT ref, title, body FROM notes_fts")
            }
            stored_vectors = dict(self.db.execute("SELECT ref, hash FROM embeddings"))

        retrievable = {
            n.ref for n in notes
            if n.meta.get("retrieval", True) is not False
            and n.meta.get("temporary") is not True
        }
        authored_meta = {
            n.ref: (
                {key: value for key, value in n.meta.items() if key not in TASK_RUNTIME_FIELDS}
                if n.kind == "task" else n.meta
            )
            for n in notes
        }
        hashes = {
            n.ref: hashlib.sha256(
                (json.dumps(authored_meta[n.ref], sort_keys=True, default=str) + n.body).encode()
            ).hexdigest()
            for n in notes
        }
        changed = {
            n.ref for n in notes if existing.get(n.ref) != (hashes[n.ref], n.kind)
        }
        desired_refs = {n.ref for n in notes}
        removed = (existing.keys() | indexed_text.keys() | stored_vectors.keys()) - desired_refs
        vector_hashes = {}
        vectors = {}
        if embed and retrievable:
            model_hash = _embedding_model_hash()
            vector_hashes = {
                n.ref: hashlib.sha256(
                    f"{model_hash}\0{_embedding_text(n.title, n.body)}".encode()
                ).hexdigest()
                for n in notes if n.ref in retrievable
            }
            to_embed = [
                n for n in notes if n.ref in retrievable
                and stored_vectors.get(n.ref) != vector_hashes[n.ref]
            ]
            if to_embed:
                vectors = dict(zip(
                    (n.ref for n in to_embed),
                    embed_texts([_embedding_text(n.title, n.body) for n in to_embed]),
                    strict=True,
                ))

        # Publish the complete replacement once. Searches retain the previous
        # complete index during encoding; an encoder failure changes no rows.
        vectors_changed = bool(vectors) or bool(removed & stored_vectors.keys())
        with self.lock, self.db:
            for ref in removed:
                self.db.execute("DELETE FROM notes WHERE ref=?", (ref,))
                self.db.execute("DELETE FROM notes_fts WHERE ref=?", (ref,))
                self.db.execute("DELETE FROM embeddings WHERE ref=?", (ref,))
            for n in notes:
                if n.ref in changed:
                    self.db.execute(
                        "INSERT OR REPLACE INTO notes(ref,path,title,kind,mtime,hash,meta,links) VALUES(?,?,?,?,?,?,?,?)",
                        (n.ref, n.path, n.title, n.kind, n.mtime, hashes[n.ref],
                         json.dumps(authored_meta[n.ref], default=str), json.dumps(n.links)),
                    )
                    if n.ref in stored_vectors and existing.get(n.ref, (None, None))[1] != n.kind:
                        vectors_changed = True
                old_text = indexed_text.get(n.ref)
                new_text = (n.title, n.body) if n.ref in retrievable else None
                if old_text != new_text:
                    self.db.execute("DELETE FROM notes_fts WHERE ref=?", (n.ref,))
                    if new_text is not None:
                        self.db.execute(
                            "INSERT INTO notes_fts(ref,title,body) VALUES(?,?,?)",
                            (n.ref, *new_text),
                        )
                if n.ref in vectors:
                    v = vectors[n.ref]
                    self.db.execute(
                        "INSERT OR REPLACE INTO embeddings(ref,hash,dim,vec) VALUES(?,?,?,?)",
                        (n.ref, vector_hashes[n.ref], len(v), v.tobytes()),
                    )
                elif n.ref in stored_vectors and (
                    new_text is None
                    or (not embed and (
                        old_text is None
                        or _embedding_text(*old_text) != _embedding_text(*new_text)
                    ))
                ):
                    self.db.execute("DELETE FROM embeddings WHERE ref=?", (n.ref,))
                    vectors_changed = True
            # The connection context commits before the next reader acquires
            # this lock. Invalidating on a rollback is harmless (a cache miss).
            if vectors_changed:
                self._invalidate_vector_cache_locked()
        return {
            "total": len(notes), "added": len(changed - existing.keys()),
            "updated": len(changed & existing.keys()), "removed": len(removed & existing.keys()),
        }

    # ---------- search lanes ----------

    def fts(
        self,
        query: str,
        k: int,
        kind: str | None = None,
        *,
        eligible_refs: set[str] | None = None,
    ) -> list[tuple[str, float]]:
        # User text is literal FTS text, including dotted Tools and DP-4 names.
        terms = [term.replace('"', '""') for term in query.split() if len(term) > 1]
        q = " OR ".join(f'"{term}"' for term in terms)
        if not q or eligible_refs == set():
            return []
        predicates = ""
        params: list = [q]
        if kind is not None:
            predicates += "AND notes.kind=? "
            params.append(kind)
        if eligible_refs is not None:
            # One bounded-by-vault JSON parameter avoids SQLite's host-variable
            # limit while filtering the candidate corpus before lexical top-k.
            predicates += "AND notes.ref IN (SELECT value FROM json_each(?)) "
            params.append(json.dumps(sorted(eligible_refs)))
        params.append(k)
        try:
            with self.lock:
                rows = self.db.execute(
                    "SELECT notes_fts.ref, bm25(notes_fts) FROM notes_fts "
                    "JOIN notes ON notes.ref=notes_fts.ref "
                    "WHERE notes_fts MATCH ? "
                    + predicates
                    + "ORDER BY bm25(notes_fts) LIMIT ?",
                    params,
                ).fetchall()
        except sqlite3.OperationalError:
            return []
        return [(r[0], -r[1]) for r in rows]

    def _vector_corpus(
        self,
        kind: str | None,
    ) -> tuple[tuple[str, ...], np.ndarray]:
        with self.lock:
            # data_version detects other connections; local changes explicitly
            # invalidate the cache. This token is private, not a graph revision.
            data_version = int(self.db.execute("PRAGMA data_version").fetchone()[0])
            revision = (self._vector_revision, data_version)
            cached = self._vector_cache.get(kind)
            if cached and cached[0] == revision:
                return cached[1], cached[2]
            rows = self.db.execute(
                "SELECT embeddings.ref, embeddings.vec FROM embeddings "
                "JOIN notes ON notes.ref=embeddings.ref "
                + ("WHERE notes.kind=? " if kind is not None else "")
                + "ORDER BY embeddings.ref",
                (kind,) if kind is not None else (),
            ).fetchall()
            refs = tuple(row[0] for row in rows)
            matrix = (
                np.stack([np.frombuffer(row[1], dtype=np.float32) for row in rows])
                if rows
                else np.empty((0, 0), dtype=np.float32)
            )
            matrix.setflags(write=False)
            self._vector_cache[kind] = (revision, refs, matrix)
            return refs, matrix

    def vector(
        self,
        query: str,
        k: int,
        kind: str | None = None,
        *,
        eligible_refs: set[str] | None = None,
    ) -> list[tuple[str, float]]:
        refs, mat = self._vector_corpus(kind)
        if not refs:
            return []
        eligible = None
        if eligible_refs is not None:
            eligible = np.array([i for i, ref in enumerate(refs) if ref in eligible_refs], dtype=np.intp)
            if not len(eligible):
                return []
        qv = embed_texts([query])[0]
        sims = mat @ qv
        order = (np.argsort(-sims)[:k] if eligible is None
                 else eligible[np.argsort(-sims[eligible])[:k]])
        return [(refs[i], float(sims[i])) for i in order]

    # ---------- graph ----------

    def graph(self) -> dict:
        nodes, links = [], []
        with self.lock:
            rows = self.db.execute("SELECT ref, title, kind, meta, links FROM notes").fetchall()
            runtime_states = {
                ref: self._hydrate_occurrence(ref, json.loads(state))
                for ref, state in self.db.execute("SELECT task_ref,state FROM task_runtime")
            }
        known = {r[0] for r in rows}
        from .source import article_refs_for_trees, normalize_source_tree, SourceError
        from .vault import Resolver, Note as _N
        from .dependencies import DependencyResolver, agent_dependencies

        stubs = [_N(path=ref + ".md", title=title,
                    meta={**json.loads(meta), **(runtime_states.get(ref, {}) if kind == "task" else {})}, body="")
                 for ref, title, kind, meta, _links in rows]
        resolver = Resolver(stubs)
        dependencies = DependencyResolver(stubs)
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
            child_refs = [metadata_ref(str(item)) for item in _N(
                path=ref + ".md", title=title, meta=m, body="").children]
            nodes.append({"id": ref, "title": title, "kind": kind,
                          "status": (
                              runtime_states.get(ref, {}).get("status", "draft")
                              if kind == "task" else m.get("article_status")
                          ), "assignee": metadata_ref(str(m["assignee"])) if m.get("assignee") else None,
                          "triggers": list(task_triggers(m)) if kind == "task" else [],
                          "children": child_refs,
                          "dependencies": agent_dependencies(dependencies.resolve(ref), dependencies)
                          if kind == "agent" and dependencies.resolve(ref) else {},
                          "source_scopes": source_scopes,
                          "source_scope_refs": article_refs_for_trees(source_scopes),
                          "tags": m.get("tags") or []})
            for target in dict.fromkeys(json.loads(link_json)):
                t = resolver.resolve(target)
                if t and t.ref in known and t.ref != ref:
                    links.append({"source": ref, "target": t.ref})

        # Shared Library grouping supplies the expandable Tool hierarchy;
        # callable identity is independent of its displayed parent.
        tool_rows = [(ref, json.loads(meta)) for ref, _title, kind, meta, _links in rows
                     if kind == "tool"]
        explicit_children = set()
        for _ref, meta in tool_rows:
            for raw in _meta_links(meta.get("subtools")):
                target = resolver.resolve(metadata_ref(raw))
                if target:
                    explicit_children.add(target.ref)
        tool_parts = {
            ref: [*callable_namespace(ref.rsplit("/", 1)[-1]).split("."), ref.rsplit(".", 1)[-1]]
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
                "tags": ["tool-namespace"],
                "synthetic": True,
            })

        # Skills mirror dotted callable Tools one-for-one. Each generated leaf
        # is an article about how to use its Tool; authored technique notes are
        # retained as its guidance sources and remain canonical at runtime.
        note_stubs = stubs
        links.extend(_binding_shortcuts(note_stubs, links))
        for skill_order, skill_node in enumerate(build_skill_mirror(note_stubs)):
            nodes.append({
                "id": skill_mirror_node_id(skill_node.path),
                **({"article_ref": skill_node.source_skills[0]}
                   if len(skill_node.source_skills) == 1 else {}),
                "title": skill_node.title,
                "kind": "skill",
                "status": None,
                "assignee": None,
                "children": [skill_mirror_node_id(child) for child in skill_node.children],
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

    # ---------- activation occurrences and compatible Task projection ----------

    @staticmethod
    def _occurrence_key(task_ref: str, params: dict, last_run: str = "") -> str:
        if params.get("activation_key"):
            return "event:" + str(params["activation_key"])
        if params.get("reply_to_turn_id"):
            return "turn:" + str(params["reply_to_turn_id"])
        if last_run:
            return "run:" + last_run
        return "legacy:" + hashlib.sha256(json.dumps(
            [task_ref, params], sort_keys=True, default=str).encode()).hexdigest()

    def _persist_occurrences(self, task_ref: str, state: dict) -> dict:
        """Atomic normalization behind the legacy Task-status/FIFO projection."""
        state = dict(state)
        if not state.get("params") and not state.get("last_run") and not state.get("activation_id") and not state.get("event_queue"):
            return state
        now = time.time()
        params = state.get("params") if isinstance(state.get("params"), dict) else {}
        existing = self.db.execute("SELECT task_ref,activation_key,state FROM task_activations WHERE id=?",
            (state.get("activation_id", ""),)).fetchone()
        same = bool(existing and existing[0] == task_ref and ("params" not in state or json.loads(existing[2]).get("params", {}) == params))
        key = existing[1] if same else self._occurrence_key(task_ref, params, str(state.get("last_run", "")))
        identifier = state["activation_id"] if same else "activation-" + hashlib.sha256(
            (task_ref + "\0" + key).encode()).hexdigest()[:24]
        state["activation_id"] = identifier
        active = {k: v for k, v in state.items() if k not in {"event_queue", "_queue_ids", "_params_hidden"}}
        if "params" in state:
            active["params"] = params
            state.pop("_params_hidden", None)
        elif same and "params" in json.loads(existing[2]):
            active["params"] = json.loads(existing[2])["params"]
            state["_params_hidden"] = True
        self.db.execute("INSERT INTO task_activations(id,task_ref,activation_key,state,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at",
            (identifier, task_ref, key, json.dumps(active, sort_keys=True, default=str), now, now))
        queue_ids = []
        for waiting in state.get("event_queue", []):
            key = self._occurrence_key(task_ref, waiting)
            queue_id = "activation-" + hashlib.sha256((task_ref + "\0" + key).encode()).hexdigest()[:24]
            if queue_id == identifier or queue_id in queue_ids:
                continue
            queue_ids.append(queue_id)
            queued = {"activation_id": queue_id, "status": "pending", "params": waiting}
            self.db.execute("INSERT OR IGNORE INTO task_activations(id,task_ref,activation_key,state,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?)", (queue_id, task_ref, key, json.dumps(queued, sort_keys=True, default=str), now, now))
        if queue_ids:
            state["_queue_ids"] = queue_ids
        else:
            state.pop("_queue_ids", None)
        return state

    def _hydrate_occurrence(self, task_ref: str, projection: dict) -> dict:
        binding = _ACTIVE_OCCURRENCE.get()
        identifier = binding[1] if binding and binding[0] == task_ref else projection.get("activation_id")
        if not identifier:
            return projection
        row = self.db.execute("SELECT state FROM task_activations WHERE id=? AND task_ref=?", (identifier, task_ref)).fetchone()
        if row is None:
            raise ValueError("Task projection lost its authoritative activation")
        state = json.loads(row[0])
        queue = []
        if identifier == projection.get("activation_id"):
            for queue_id in projection.get("_queue_ids", []):
                item = self.db.execute("SELECT state FROM task_activations WHERE id=? AND task_ref=?", (queue_id, task_ref)).fetchone()
                if item is None:
                    raise ValueError("Task queue lost an activation")
                queue.append(json.loads(item[0])["params"])
        if queue or identifier == projection.get("activation_id") and "event_queue" in projection:
            state["event_queue"] = queue
        if identifier == projection.get("activation_id") and projection.get("_params_hidden"):
            state.pop("params", None)
        return state

    def begin_activation(self, task_ref: str, params: dict, run_id: str, *, queued: bool = False) -> tuple[str, object]:
        """Bind this attempt to one immutable occurrence identity in the same DB."""
        clean = {key: value for key, value in params.items() if key not in {"activation_id", "_activation_id"}}
        key = self._occurrence_key(task_ref, clean, "" if queued else run_id)
        identifier = "activation-" + hashlib.sha256((task_ref + "\0" + key).encode()).hexdigest()[:24]
        with self.lock, self.db:
            row = self.db.execute("SELECT state FROM task_activations WHERE id=?", (identifier,)).fetchone()
            prior = json.loads(row[0]) if row else {}
            if prior.get("status") == "running" and prior.get("last_run") != run_id:
                raise ValueError("This exact activation already has a running attempt")
            if prior.get("status") == "completed":
                raise ValueError("This activation already completed; it cannot be implicitly replayed")
            if prior.get("params", {}).get("request") not in {None, clean.get("request")}:
                raise ValueError("An activation cannot change its original objective")
            state = {**prior, "activation_id": identifier, "params": clean,
                     "status": "running", "last_run": run_id}
            now = time.time()
            self.db.execute("INSERT INTO task_activations(id,task_ref,activation_key,state,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at",
                (identifier, task_ref, key, json.dumps(state, sort_keys=True, default=str), now, now))
            head = self.db.execute("SELECT state FROM task_runtime WHERE task_ref=?", (task_ref,)).fetchone()
            projected = json.loads(head[0]) if head else {}
            # A scheduled claim keeps its FIFO; a direct user occurrence does
            # not consume unrelated queued events from this reusable Task.
            for field in ("event_queue", "_queue_ids"):
                if field in projected:
                    state[field] = projected[field]
            self.db.execute("INSERT INTO task_runtime(task_ref,state,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(task_ref) DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at",
                (task_ref, json.dumps(state, sort_keys=True, default=str), now))
        return identifier, _ACTIVE_OCCURRENCE.set((task_ref, identifier))

    @staticmethod
    def reset_activation(token) -> None:
        _ACTIVE_OCCURRENCE.reset(token)

    def activation(self, identifier: str) -> dict | None:
        with self.lock:
            row = self.db.execute("SELECT id,task_ref,activation_key,state,created_at,updated_at "
                "FROM task_activations WHERE id=?", (identifier,)).fetchone()
        return {"id":row[0],"task_ref":row[1],"activation_key":row[2],
                **json.loads(row[3]),"created_at":row[4],"updated_at":row[5]} if row else None

    def activation_id_for(self, task_ref: str, params: dict) -> str:
        """Resolve this admitted occurrence, not the Task's possibly different head."""
        key = self._occurrence_key(task_ref, params)
        with self.lock:
            row = self.db.execute("SELECT id FROM task_activations WHERE task_ref=? AND activation_key=?",
                                  (task_ref, key)).fetchone()
        return str(row[0]) if row else ""

    def activations(self, task_ref: str, limit: int = 50) -> list[dict]:
        if not 1 <= limit <= 200:
            raise ValueError("Activation history is bounded to 200 occurrences")
        with self.lock:
            rows = self.db.execute("SELECT id FROM task_activations WHERE task_ref=? ORDER BY created_at DESC,id DESC LIMIT ?",
                (task_ref, limit)).fetchall()
        return [self.activation(row[0]) for row in rows]

    def complete_review_occurrences(self, task_ref: str, pending_run_ids: set[str]) -> None:
        """Publication decisions settle their exact occurrences, not a newer head."""
        with self.lock, self.db:
            for identifier, material in self.db.execute("SELECT id,state FROM task_activations WHERE task_ref=?", (task_ref,)).fetchall():
                state = json.loads(material)
                if state.get("status") == "review" and state.get("last_run") not in pending_run_ids:
                    state.update(status="completed", publication_disposition="review_resolved")
                    self.db.execute("UPDATE task_activations SET state=?,updated_at=? WHERE id=?",
                        (json.dumps(state, sort_keys=True, default=str),time.time(),identifier))


    # ---------- current Task execution state ----------

    @staticmethod
    def _runtime_fields(meta: dict) -> dict:
        return {key: value for key, value in meta.items() if key in TASK_RUNTIME_FIELDS}

    def task_runtime(self, task_ref: str) -> dict | None:
        with self.lock:
            row = self.db.execute(
                "SELECT state FROM task_runtime WHERE task_ref=?", (task_ref,),
            ).fetchone()
        with self.lock:
            return self._hydrate_occurrence(task_ref, json.loads(row[0])) if row else None

    def seed_task_runtime(self, task_ref: str, legacy_meta: dict) -> dict:
        """Import an explicit initial state once; replay never overwrites live work."""
        state = self._runtime_fields(legacy_meta)
        state.setdefault("status", "draft")
        payload = json.dumps(state, sort_keys=True, separators=(",", ":"), default=str)
        with self.lock, self.db:
            if self.db.execute("SELECT 1 FROM task_runtime WHERE task_ref=?", (task_ref,)).fetchone() is None:
                state = self._persist_occurrences(task_ref, state)
                payload = json.dumps(state, sort_keys=True, separators=(",", ":"), default=str)
            self.db.execute(
                "INSERT OR IGNORE INTO task_runtime(task_ref,state,updated_at) VALUES(?,?,?)",
                (task_ref, payload, time.time()),
            )
            row = self.db.execute(
                "SELECT state FROM task_runtime WHERE task_ref=?", (task_ref,),
            ).fetchone()
        with self.lock:
            return self._hydrate_occurrence(task_ref, json.loads(row[0]))

    def project_task_runtime(self, task_ref: str, meta: dict) -> dict:
        """Project current work without importing state from Article reads."""
        authored = {key: value for key, value in meta.items() if key not in TASK_RUNTIME_FIELDS}
        return {**authored, "status": "draft", **(self.task_runtime(task_ref) or {})}

    def mutate_task_runtime(
        self,
        task_ref: str,
        mutate: Callable[[dict], None],
        *,
        initial: dict | None = None,
        source_event: tuple[str, str] | None = None,
    ) -> dict:
        """Serialize one Task state/FIFO mutation in the existing execution ledger."""
        with self.lock:
            try:
                self.db.execute("BEGIN IMMEDIATE")
                row = self.db.execute(
                    "SELECT state FROM task_runtime WHERE task_ref=?", (task_ref,),
                ).fetchone()
                projection = json.loads(row[0]) if row else self._runtime_fields(initial or {})
                state = self._hydrate_occurrence(task_ref, projection) if row else projection
                state.setdefault("status", "draft")
                if source_event is not None:
                    source_id, event_key = source_event
                    source = self.db.execute(
                        "SELECT event_key,event_dispatched_at FROM source_evidence WHERE id=?",
                        (source_id,),
                    ).fetchone()
                    if not source or not event_key or source[0] != event_key:
                        raise ValueError("Source event admission identity changed")
                    receipt = self.db.execute(
                        "SELECT event_dispatched_at FROM source_evidence "
                        "WHERE event_key=? AND event_dispatched_at IS NOT NULL LIMIT 1",
                        (event_key,),
                    ).fetchone()
                    if receipt is not None:
                        # A completed occurrence may no longer be in params or
                        # the FIFO. Captures from the same research activation
                        # also share that logical event's existing receipt.
                        if source[1] is None:
                            self.db.execute(
                                "UPDATE source_evidence SET event_dispatched_at=? WHERE id=?",
                                (receipt[0], source_id),
                            )
                        self.db.commit()
                        return state
                mutate(state)
                state = self._persist_occurrences(task_ref, self._runtime_fields(state))
                payload = json.dumps(state, sort_keys=True, separators=(",", ":"), default=str)
                binding = _ACTIVE_OCCURRENCE.get()
                is_head = not binding or binding[0] != task_ref or binding[1] == projection.get("activation_id")
                if is_head and (row is None or row[0] != payload):
                    self.db.execute(
                        "INSERT INTO task_runtime(task_ref,state,updated_at) VALUES(?,?,?) "
                        "ON CONFLICT(task_ref) DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at",
                        (task_ref, payload, time.time()),
                    )
                if source_event is not None:
                    occurrences = [state.get("params"), *(state.get("event_queue") or [])]
                    if not any(
                        isinstance(item, dict)
                        and item.get("activation_key") == event_key
                        and (
                            item.get("source_id") == source_id
                            or self.db.execute(
                                "SELECT 1 FROM source_evidence WHERE id=? AND event_key=?",
                                (item.get("source_id"), event_key),
                            ).fetchone() is not None
                        )
                        for item in occurrences
                    ):
                        raise ValueError("Source event was not admitted to its Task")
                    # The receipt and its only subscriber's FIFO commit together.
                    # A failure rolls both back; replay can never resurrect work
                    # that was admitted and subsequently completed.
                    self.db.execute(
                        "UPDATE source_evidence SET event_dispatched_at=? WHERE id=?",
                        (time.time(), source_id),
                    )
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise
        return json.loads(payload)

    def remap_task_runtime(self, mapping: dict[str, str]) -> dict[str, str]:
        """Move current state with an Article; preserve every historical receipt."""
        moves = {old: new for old, new in mapping.items() if old != new}
        if not moves:
            return {}
        with self.lock:
            try:
                self.db.execute("BEGIN IMMEDIATE")
                rows = {
                    ref: (state, updated_at)
                    for ref, state, updated_at in self.db.execute(
                        "SELECT task_ref,state,updated_at FROM task_runtime"
                    )
                }
                destinations = list(moves.values())
                if len(set(destinations)) != len(destinations) or any(
                    new in rows and new not in moves for new in destinations
                ):
                    raise ValueError("destination already owns Task runtime state")
                moves = {old: new for old, new in moves.items() if old in rows}
                for old in moves:
                    self.db.execute("DELETE FROM task_runtime WHERE task_ref=?", (old,))
                for old, new in moves.items():
                    self.db.execute("UPDATE task_activations SET task_ref=? WHERE task_ref=?", (new, old))
                    state, updated_at = rows[old]
                    self.db.execute(
                        "INSERT INTO task_runtime(task_ref,state,updated_at) VALUES(?,?,?)",
                        (new, state, updated_at),
                    )
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise
        return moves

    # ---------- execution receipts and public trace ----------

    @staticmethod
    def tool_params_sha256(params: dict) -> str:
        if not isinstance(params, dict):
            raise ValueError("Tool receipt parameters must be an object")
        return hashlib.sha256(json.dumps(
            params, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode()).hexdigest()

    @staticmethod
    def _receipt_time(value: float) -> bool:
        return type(value) in (int, float) and math.isfinite(value) and value >= 0

    def begin_tool_run(self, *, run_id: str, task_ref: str, params: dict, started: float) -> None:
        """Attest that every subsequent Tool dispatch uses this receipt protocol."""
        if (not isinstance(run_id, str) or not 0 < len(run_id) <= 128
                or not isinstance(task_ref, str) or not 0 < len(task_ref) <= 1024
                or not self._receipt_time(started)):
            raise ValueError("Invalid Tool receipt run identity")
        values = (task_ref, self.tool_params_sha256(params), started)
        with self.lock:
            previous = self.db.execute(
                "SELECT task_ref,params_sha256,started FROM tool_receipt_runs WHERE run_id=?", (run_id,),
            ).fetchone()
            if previous is not None:
                if previous != values:
                    raise ValueError("Tool receipt run identity changed")
                return
            if self.db.in_transaction:
                raise ValueError("Tool receipt must commit outside another owner transaction")
            self.db.execute("INSERT INTO tool_receipt_runs VALUES(?,?,?,?)", (run_id, *values))
            self.db.commit()

    def begin_tool_call(
        self, *, run_id: str, call_id: str, step: int, tool: str, signature: str,
        started: float, read_only: bool = False, tool_ref: str = "", tool_sha256: str = "",
    ) -> bool:
        """Commit exact intent before dispatch; a missing completion is uncertainty."""
        from ..capabilities.registry import READ_ONLY_CAPABILITIES

        if (not isinstance(call_id, str) or not 0 < len(call_id) <= 256
                or type(step) is not int or not 1 <= step <= 4096
                or not isinstance(tool, str) or not 0 < len(tool) <= 256
                or not isinstance(signature, str) or not 0 < len(signature) <= 512
                or type(read_only) is not bool or not self._receipt_time(started)
                or not isinstance(tool_ref, str) or len(tool_ref) > 1024
                or not isinstance(tool_sha256, str)
                or (tool_sha256 and (len(tool_sha256) != 64 or any(c not in "0123456789abcdef" for c in tool_sha256)))
                or (read_only and (tool not in READ_ONLY_CAPABILITIES or not tool_ref or not tool_sha256))):
            raise ValueError("Invalid Tool call receipt")
        values = (step, tool, signature, int(read_only), tool_ref, tool_sha256, started)
        with self.lock:
            if not self.db.execute("SELECT 1 FROM tool_receipt_runs WHERE run_id=?", (run_id,)).fetchone():
                raise ValueError("Tool call has no covered execution")
            previous = self.db.execute(
                "SELECT step,tool,signature,read_only,tool_ref,tool_sha256,started "
                "FROM tool_receipts WHERE run_id=? AND call_id=?", (run_id, call_id),
            ).fetchone()
            if previous is not None:
                if previous != values:
                    raise ValueError("Tool call receipt identity changed")
                return False
            if self.db.in_transaction:
                raise ValueError("Tool receipt must commit outside another owner transaction")
            try:
                self.db.execute(
                    "INSERT INTO tool_receipts(run_id,call_id,step,tool,signature,read_only,"
                    "tool_ref,tool_sha256,started,status) VALUES(?,?,?,?,?,?,?,?,?,'started')",
                    (run_id, call_id, *values),
                )
                self.db.commit()
                return True
            except sqlite3.IntegrityError as exc:
                self.db.rollback()
                raise ValueError("Tool step already has an exact call identity") from exc

    def finish_tool_call(
        self, *, run_id: str, call_id: str, status: str, finished: float,
        duration_ms: float, result_sha256: str = "", result_chars: int = 0,
    ) -> None:
        """Finish once; exact duplicate acknowledgements cannot rewrite evidence."""
        if (not isinstance(status, str) or status not in {"returned", "error", "rejected", "interrupted", "undispatched"}
                or not self._receipt_time(finished) or not self._receipt_time(duration_ms)
                or type(result_chars) is not int or result_chars < 0
                or not isinstance(result_sha256, str)
                or (result_sha256 and (len(result_sha256) != 64 or any(c not in "0123456789abcdef" for c in result_sha256)))):
            raise ValueError("Invalid Tool completion receipt")
        values = (status, finished, duration_ms, result_sha256, result_chars)
        with self.lock:
            previous = self.db.execute(
                "SELECT status,finished,duration_ms,result_sha256,result_chars,started "
                "FROM tool_receipts WHERE run_id=? AND call_id=?", (run_id, call_id),
            ).fetchone()
            if previous is None or finished < previous[5]:
                raise ValueError("Tool completion has no matching started call")
            if previous[0] != "started":
                if previous[:5] != values:
                    raise ValueError("Tool completion receipt cannot be changed")
                return
            if self.db.in_transaction:
                raise ValueError("Tool receipt must commit outside another owner transaction")
            self.db.execute(
                "UPDATE tool_receipts SET status=?,finished=?,duration_ms=?,result_sha256=?,result_chars=? "
                "WHERE run_id=? AND call_id=? AND status='started'", (*values, run_id, call_id),
            )
            self.db.commit()

    def tool_run_receipts(self, run_id: str) -> dict | None:
        """Read bounded metadata, never arguments, pixels, or Tool result bodies."""
        with self.lock:
            run = self.db.execute(
                "SELECT run_id,task_ref,params_sha256,started FROM tool_receipt_runs WHERE run_id=?", (run_id,),
            ).fetchone()
            if run is None:
                return None
            columns = "call_id,step,tool,signature,read_only,tool_ref,tool_sha256,status,started,finished,duration_ms,result_sha256,result_chars"
            rows = self.db.execute(
                f"SELECT {columns} FROM tool_receipts WHERE run_id=? ORDER BY step", (run_id,),
            ).fetchall()
        result = dict(zip(("run_id", "task_ref", "params_sha256", "started"), run))
        result["calls"] = [dict(zip(columns.split(","), row)) for row in rows]
        for call in result["calls"]:
            call["read_only"] = bool(call["read_only"])
        return result

    def append_trace(self, entry: dict, *, max_events: int = 500, max_chars: int = 2_097_152) -> int:
        """Journal an already-sanitized display event; never execution authority."""
        if (not isinstance(entry, dict) or type(max_events) is not int or not 1 <= max_events <= 500
                or type(max_chars) is not int or not 1 <= max_chars <= 2_097_152):
            raise ValueError("Invalid public trace bounds")
        # Validate before opening a transaction; bytes/opaque objects are forbidden.
        json.dumps(entry, allow_nan=False)
        with self.lock:
            if self.db.in_transaction:
                raise ValueError("Public trace must commit outside another owner transaction")
            try:
                cursor = self.db.execute("INSERT INTO trace_events(entry,encoded_bytes) VALUES('',0)")
                seq = cursor.lastrowid
                payload = json.dumps({**entry, "seq": seq}, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
                size = len(payload.encode("utf-8"))
                if size > max_chars:
                    raise ValueError("Public trace event exceeds retained byte budget")
                self.db.execute("UPDATE trace_events SET entry=?,encoded_bytes=? WHERE seq=?", (payload, size, seq))
                rows = self.db.execute("SELECT seq,encoded_bytes FROM trace_events ORDER BY seq DESC").fetchall()
                total, retained = 0, 0
                for item_seq, item_size in rows:
                    if retained >= max_events or total + item_size > max_chars:
                        self.db.execute("DELETE FROM trace_events WHERE seq<=?", (item_seq,))
                        break
                    total += item_size
                    retained += 1
                self.db.commit()
                return seq
            except Exception:
                self.db.rollback()
                raise

    def trace_snapshot(self, after_seq: int | None = None) -> dict:
        if after_seq is not None and (type(after_seq) is not int or after_seq < 0):
            raise ValueError("Invalid public trace cursor")
        with self.lock:
            oldest, latest = self.db.execute("SELECT MIN(seq),MAX(seq) FROM trace_events").fetchone()
            rows = self.db.execute(
                "SELECT entry FROM trace_events WHERE seq>? ORDER BY seq", (-1 if after_seq is None else after_seq,),
            ).fetchall()
        return {"oldest_seq": oldest, "latest_seq": latest, "events": [json.loads(row[0]) for row in rows]}

    def trace_history(self, after_seq: int | None = None) -> list[dict]:
        return self.trace_snapshot(after_seq)["events"]

    def trace_bounds(self) -> dict:
        with self.lock:
            oldest, latest = self.db.execute("SELECT MIN(seq),MAX(seq) FROM trace_events").fetchone()
        return {"oldest_seq": oldest, "latest_seq": latest}

    # ---------- runs ----------

    def record_run(self, *, overwrite: bool = True, commit: bool = True, **kw) -> None:
        values = {
            "objective": "",
            "activation_id": (_ACTIVE_OCCURRENCE.get() or ("", ""))[1]
                if (_ACTIVE_OCCURRENCE.get() or ("", ""))[0] == kw.get("task_ref") else "",
            "runbook_ref": "",
            "runbook_sha256": "",
            "reasoning_effort": "",
            "model": "",
            **kw,
        }
        with self.lock:
            if not commit and not self.db.in_transaction:
                raise ValueError("controller receipt requires an active owner transaction")
            self.db.execute(
                f"INSERT OR {'REPLACE' if overwrite else 'IGNORE'} INTO runs("
                "id,task_ref,objective,agent,started,finished,status,summary,trace,"
                "runbook_ref,runbook_sha256,reasoning_effort,model,activation_id) VALUES("
                ":id,:task_ref,:objective,:agent,:started,:finished,:status,:summary,:trace,"
                ":runbook_ref,:runbook_sha256,:reasoning_effort,:model,:activation_id)", values)
            if commit:
                self.db.commit()

    def runs(self, limit: int = 50) -> list[dict]:
        cols = [
            "id", "task_ref", "objective", "agent", "started", "finished", "status", "summary",
            "runbook_ref", "runbook_sha256", "reasoning_effort", "model", "activation_id",
        ]
        with self.lock:
            rows = self.db.execute(
                f"SELECT {','.join(cols)} FROM runs ORDER BY started DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(zip(cols, r)) for r in rows]

    def run_history_sample(self, *, since: float, until: float, limit: int = 200) -> dict:
        """Read one bounded diagnostic window without objectives or trace bodies."""
        if (not self._receipt_time(since) or not self._receipt_time(until) or since > until
                or type(limit) is not int or not 1 <= limit <= 200):
            raise ValueError("Invalid run history sample bounds")
        columns = "id,task_ref,started,finished,status,runbook_ref,runbook_sha256"
        with self.lock:
            rows = self.db.execute(
                f"SELECT {columns} FROM runs WHERE started>=? AND started<=? "
                "ORDER BY started DESC,id DESC LIMIT ?", (since, until, limit + 1),
            ).fetchall()
        return {"runs": [dict(zip(columns.split(","), row)) for row in rows[:limit]],
                "scan_complete": len(rows) <= limit}

    def tool_history_sample(self, *, since: float, until: float, limit: int = 400) -> dict:
        """Read bounded controller receipt metadata, including unfinished calls."""
        if (not self._receipt_time(since) or not self._receipt_time(until) or since > until
                or type(limit) is not int or not 1 <= limit <= 400):
            raise ValueError("Invalid Tool history sample bounds")
        columns = ("run_id", "task_ref", "call_id", "tool", "tool_ref", "tool_sha256", "started",
                   "finished", "status", "duration_ms")
        with self.lock:
            rows = self.db.execute(
                "SELECT t.run_id,r.task_ref,t.call_id,t.tool,t.tool_ref,t.tool_sha256,t.started,"
                "t.finished,t.status,t.duration_ms FROM tool_receipts t JOIN tool_receipt_runs r "
                "ON r.run_id=t.run_id WHERE t.started>=? AND t.started<=? "
                "ORDER BY t.started DESC,t.run_id,t.step LIMIT ?", (since, until, limit + 1),
            ).fetchall()
        return {"calls": [dict(zip(columns, row)) for row in rows[:limit]],
                "scan_complete": len(rows) <= limit}

    _RUN_COLUMNS = (
        "id", "task_ref", "objective", "agent", "started", "finished",
        "status", "summary", "trace", "runbook_ref", "runbook_sha256",
        "reasoning_effort", "model", "activation_id",
    )

    def run(self, run_id: str) -> dict | None:
        """Return one exact run row without interpreting its evidence."""
        with self.lock:
            row = self.db.execute(
                f"SELECT {','.join(self._RUN_COLUMNS)} FROM runs WHERE id=?",
                (run_id,),
            ).fetchone()
        return dict(zip(self._RUN_COLUMNS, row)) if row else None

    @staticmethod
    def _owner_maintenance_no_change_key(
        run_id: str, task_ref: str, trace: list,
    ) -> tuple[str, str, str] | None:
        """Read an explicit owner disposition without implying model execution."""
        if len(trace) != 1 or not isinstance(trace[0], dict) or set(trace[0]) != {"controller_disposition"}:
            return None
        receipt = trace[0]["controller_disposition"]
        if not isinstance(receipt, dict):
            return None

        def digest(value, length=64):
            return isinstance(value, str) and len(value) == length and all(char in "0123456789abcdef" for char in value)

        def exact_ref(value):
            return (isinstance(value, str) and 0 < len(value) <= 1024
                    and metadata_ref(value) == value and "\\" not in value
                    and not any(ord(char) < 32 for char in value)
                    and all(part and not part.startswith((".", "_")) for part in value.split("/")))

        params = receipt.get("candidate_params")
        fields = {"candidate_key", "candidate_revision", "candidate_refs", "candidate_kind", "candidate_signals",
                  "event", "target_task", "created_by_task_ref", "created_by_run_id", "activation_key"}
        if (receipt.get("kind") != "owner_maintenance_resolution"
                or receipt.get("disposition") != "no_change"
                or receipt.get("authorization") != "explicit_owner_request"
                or receipt.get("reviewed_by") != "Codex"
                or receipt.get("effect_applied") is not False or receipt.get("tools_executed") is not False
                or not isinstance(receipt.get("reason"), str) or not receipt["reason"].strip()
                or not exact_ref(task_ref) or not task_ref.startswith("Tasks/")
                or receipt.get("target_task") != task_ref
                or not isinstance(params, dict) or set(params) != fields
                or params.get("event") != "task.create" or params.get("target_task") != task_ref
                or params.get("created_by_task_ref") != "Tasks/curate"
                or not isinstance(params.get("created_by_run_id"), str) or not params["created_by_run_id"].strip()
                or not isinstance(params.get("candidate_kind"), str) or not params["candidate_kind"].strip()
                or not isinstance(params.get("candidate_signals"), dict)
                or not digest(params.get("candidate_key"), 20)
                or not digest(receipt.get("reviewed_candidate_key"), 20)
                or not digest(params.get("candidate_revision")) or not digest(receipt.get("reviewed_revision"))):
            return None
        refs = params.get("candidate_refs")
        articles = receipt.get("reviewed_articles")
        if (not isinstance(refs, list) or len(refs) != 2 or not all(exact_ref(ref) for ref in refs)
                or len({ref.casefold() for ref in refs}) != 2
                or not isinstance(articles, list) or len(articles) != 2
                or any(not isinstance(article, dict) or set(article) != {"ref", "sha256"}
                       or not exact_ref(article.get("ref")) or not digest(article.get("sha256")) for article in articles)
                or {article["ref"] for article in articles} != set(refs)):
            return None
        revision_key = hashlib.sha256(json.dumps(
            [task_ref, params["candidate_key"], params["candidate_revision"]], sort_keys=True,
        ).encode()).hexdigest()[:20]
        activation_key = params.get("activation_key")
        if (not isinstance(activation_key, str)
                or activation_key not in {params["candidate_key"], revision_key}
                or receipt.get("activation_key") != activation_key):
            return None
        try:
            params_hash = hashlib.sha256(json.dumps(params, sort_keys=True, allow_nan=False).encode()).hexdigest()
        except (TypeError, ValueError):
            return None
        expected_id = "settled-" + hashlib.sha256(
            (task_ref + "\0" + activation_key + "\0" + params_hash).encode()
        ).hexdigest()[:32]
        if receipt.get("params_sha256") != params_hash or run_id != expected_id:
            return None
        return task_ref, receipt["reviewed_candidate_key"], receipt["reviewed_revision"]

    def maintenance_no_change_keys(self) -> set[tuple[str, str, str]]:
        """Return only controller-bound, evidenced maintenance no-change results."""
        with self.lock:
            rows = self.db.execute(
                "SELECT id,task_ref,status,trace FROM runs WHERE status='completed' "
                "OR (status='settled' AND agent='scheduler')"
            ).fetchall()
        completed: set[tuple[str, str, str]] = set()
        for run_id, task_ref, status, raw_trace in rows:
            if status == "settled" and (not isinstance(raw_trace, str) or len(raw_trace.encode()) > 32_000):
                continue
            try:
                trace = json.loads(raw_trace or "[]")
            except (TypeError, ValueError, RecursionError):
                continue
            if not isinstance(trace, list):
                continue
            if status == "settled":
                owner_key = self._owner_maintenance_no_change_key(run_id, task_ref, trace)
                if owner_key is not None:
                    completed.add(owner_key)
                continue
            activation = next(
                (
                    item.get("maintenance_candidate")
                    for item in trace
                    if isinstance(item, dict)
                    and isinstance(item.get("maintenance_candidate"), dict)
                ),
                None,
            )
            terminal = next(
                (
                    item
                    for item in reversed(trace)
                    if isinstance(item, dict) and item.get("tool") == "task.complete"
                ),
                None,
            )
            if not activation or not terminal or terminal.get("accepted") is not True:
                continue
            args = terminal.get("args")
            evidence = args.get("evidence") if isinstance(args, dict) else None
            if not (
                isinstance(args, dict)
                and args.get("status") == "completed"
                and args.get("outcome") == "no_change"
                and isinstance(evidence, list)
                and any(isinstance(item, str) and item.strip() for item in evidence)
            ):
                continue
            candidate_key = str(activation.get("candidate_key", ""))
            candidate_revision = str(activation.get("candidate_revision", ""))
            candidate_refs = activation.get("candidate_refs")
            if not (
                str(task_ref).startswith("Tasks/")
                and activation.get("target_task") == task_ref
                and candidate_key
                and candidate_revision
                and isinstance(candidate_refs, list)
                and candidate_refs
            ):
                continue
            completed.add((str(task_ref), candidate_key, candidate_revision))
        return completed

    # ---------- durable peer continuations ----------

    _CONTINUATION_COLUMNS = (
        "id", "caller_task_ref", "caller_run_id", "target_task_ref",
        "target_activation_key", "objective", "conversation_id",
        "reply_to_turn_id", "reply_source", "status", "handoff_source_id",
        "ingest_run_id", "result", "resumed_run_id", "created_at", "updated_at", "await_publication",
    )

    def _continuation_row(self, row) -> dict | None:
        return dict(zip(self._CONTINUATION_COLUMNS, row)) if row else None

    @staticmethod
    def _continuation_result(value: dict) -> str:
        payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
        if len(payload) > 16_000:
            raise ValueError("continuation result exceeds its durable bound")
        return payload

    def create_continuation(
        self,
        *,
        caller_task_ref: str,
        caller_run_id: str,
        target_task_ref: str,
        target_activation_key: str,
        objective: str,
        conversation_id: str = "",
        reply_to_turn_id: str = "",
        reply_source: str = "",
        await_publication: bool = False,
    ) -> dict:
        """Create one immutable causal wait, idempotently by caller run."""
        continuation_id = "continuation-" + hashlib.sha256(
            "\0".join((caller_run_id, target_task_ref, target_activation_key)).encode()
        ).hexdigest()[:24]
        now = time.time()
        values = {
            "id": continuation_id,
            "caller_task_ref": caller_task_ref,
            "caller_run_id": caller_run_id,
            "target_task_ref": target_task_ref,
            "target_activation_key": target_activation_key,
            "objective": objective,
            "conversation_id": conversation_id,
            "reply_to_turn_id": reply_to_turn_id,
            "reply_source": reply_source,
            "await_publication": int(await_publication),
            "status": "waiting",
            "handoff_source_id": "",
            "ingest_run_id": "",
            "result": "{}",
            "resumed_run_id": "",
            "created_at": now,
            "updated_at": now,
        }
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                existing = self.db.execute(
                    f"SELECT {','.join(self._CONTINUATION_COLUMNS)} "
                    "FROM task_continuations WHERE caller_run_id=?",
                    (caller_run_id,),
                ).fetchone()
                if existing:
                    row = self._continuation_row(existing)
                    immutable = {
                        "caller_task_ref": caller_task_ref,
                        "target_task_ref": target_task_ref,
                        "target_activation_key": target_activation_key,
                        "objective": objective,
                        "conversation_id": conversation_id,
                        "reply_to_turn_id": reply_to_turn_id,
                        "reply_source": reply_source,
                        "await_publication": int(await_publication),
                    }
                    if any(row[key] != value for key, value in immutable.items()):
                        raise ValueError("caller run is already bound to a different continuation")
                    self.db.commit()
                    return row
                self.db.execute(
                    "INSERT INTO task_continuations("
                    + ",".join(self._CONTINUATION_COLUMNS)
                    + ") VALUES("
                    + ",".join(f":{name}" for name in self._CONTINUATION_COLUMNS)
                    + ")",
                    values,
                )
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
        return values

    def continuation_for_caller(self, caller_run_id: str) -> dict | None:
        with self.lock:
            row = self.db.execute(
                f"SELECT {','.join(self._CONTINUATION_COLUMNS)} "
                "FROM task_continuations WHERE caller_run_id=?",
                (caller_run_id,),
            ).fetchone()
        return self._continuation_row(row)

    def bind_continuation_handoff(self, caller_run_id: str, source_id: str) -> dict | None:
        """Bind Darwin's exact handoff Source to its waiting caller."""
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                row = self.db.execute(
                    f"SELECT {','.join(self._CONTINUATION_COLUMNS)} "
                    "FROM task_continuations WHERE caller_run_id=?",
                    (caller_run_id,),
                ).fetchone()
                current = self._continuation_row(row)
                if current is None:
                    self.db.commit()
                    return None
                if current["handoff_source_id"] and current["handoff_source_id"] != source_id:
                    raise ValueError("continuation is already bound to another handoff Source")
                self.db.execute(
                    "UPDATE task_continuations SET handoff_source_id=?,status='ingesting',"
                    "updated_at=? WHERE id=? AND status IN ('waiting','ingesting')",
                    (source_id, time.time(), current["id"]),
                )
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
        return self.continuation_for_caller(caller_run_id)

    def bind_continuation_ingest(self, source_id: str, ingest_run_id: str) -> dict | None:
        """Bind Alexandria's exact Ingest run before proposals can be decided."""
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                row = self.db.execute(
                    f"SELECT {','.join(self._CONTINUATION_COLUMNS)} "
                    "FROM task_continuations WHERE handoff_source_id=?",
                    (source_id,),
                ).fetchone()
                current = self._continuation_row(row)
                if current is None:
                    self.db.commit()
                    return None
                if not current["await_publication"]:
                    self.db.commit()
                    return current
                if current["ingest_run_id"] and current["ingest_run_id"] != ingest_run_id:
                    raise ValueError("continuation is already bound to another Ingest run")
                self.db.execute(
                    "UPDATE task_continuations SET ingest_run_id=?,status='ingesting',"
                    "updated_at=? WHERE id=? AND status IN ('ingesting','waiting')",
                    (ingest_run_id, time.time(), current["id"]),
                )
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
        return self.continuation_for_caller(current["caller_run_id"])

    def _ready_continuation(self, continuation_id: str, result: dict) -> None:
        payload = self._continuation_result(result)
        with self.lock:
            self.db.execute(
                "UPDATE task_continuations SET status='ready',result=?,updated_at=? "
                "WHERE id=? AND status IN ('waiting','ingesting')",
                (payload, time.time(), continuation_id),
            )
            self.db.commit()

    def resolve_research_finding(self, caller_run_id: str, research_run_id: str, source: dict) -> bool:
        """Resume from an attested finding, without falsely claiming publication."""
        row = self.continuation_for_caller(caller_run_id)
        run = self.run(research_run_id)
        if not row or row["await_publication"] or row["status"] not in {"waiting", "ingesting"}:
            return False
        if (not run or run.get("status") != "completed" or run.get("task_ref") != row["target_task_ref"]
                or source.get("id") != row["handoff_source_id"] or source.get("immutable") is not True
                or source.get("citation") != "source://" + str(source.get("id"))):
            raise ValueError("Research finding lacks its exact completed run and immutable handoff")
        content = source.get("content")
        if not isinstance(content, str) or source.get("content_sha256") != "sha256:" + hashlib.sha256(content.encode()).hexdigest():
            raise ValueError("Research finding content does not match its attested Source hash")
        self._ready_continuation(row["id"], {
            "disposition": "evidenced_finding", "publication": "not_required_for_reply",
            "accepted_knowledge": False, "research_run_id": research_run_id,
            "source_id": source["id"], "source_citation": source["citation"],
            "content_sha256": source["content_sha256"], "captured_at": source.get("captured_at"),
            "finding": content[:10000], "finding_truncated": len(content) > 10000,
        })
        return True

    def resolve_research_failure(self, caller_run_id: str, research_run_id: str) -> bool:
        row = self.continuation_for_caller(caller_run_id)
        run = self.run(research_run_id)
        if not row or not run or run.get("task_ref") != row["target_task_ref"] or run.get("status") not in {"failed", "blocked"}:
            return False
        self._ready_continuation(row["id"], {"disposition": "research_failed", "accepted_knowledge": False,
            "research_run_id": research_run_id, "summary": str(run.get("summary", ""))[:2000],
            "rule": "Report the exact blocker; no successful research or publication was established."})
        return True

    def resolve_research_no_change(
        self,
        caller_run_id: str,
        research_run_id: str,
        evidence: dict,
    ) -> bool:
        row = self.continuation_for_caller(caller_run_id)
        if not row or row["handoff_source_id"]:
            return False
        self._ready_continuation(row["id"], {
            "disposition": "no_change",
            "research_run_id": research_run_id,
            **evidence,
        })
        return True

    def resolve_ingest_no_change(
        self,
        source_id: str,
        ingest_run_id: str,
        evidence: dict,
    ) -> bool:
        with self.lock:
            row = self.db.execute(
                f"SELECT {','.join(self._CONTINUATION_COLUMNS)} "
                "FROM task_continuations WHERE handoff_source_id=? AND ingest_run_id=?",
                (source_id, ingest_run_id),
            ).fetchone()
        continuation = self._continuation_row(row)
        if continuation is None:
            return False
        self._ready_continuation(continuation["id"], {
            "disposition": "no_change",
            "source_id": source_id,
            "ingest_run_id": ingest_run_id,
            **evidence,
        })
        return True

    def record_review_decision(
        self,
        *,
        proposal_id: str,
        run_id: str,
        task_ref: str,
        target: str,
        decision: str,
    ) -> dict:
        self.record_review_decisions([dict(
            proposal_id=proposal_id, run_id=run_id, task_ref=task_ref,
            target=target, decision=decision,
        )])
        return self.review_outcome(run_id)

    def record_review_decisions(self, decisions: list[dict], *, commit: bool = True) -> None:
        """Record one bounded Review disposition, optionally in its owner's transaction."""
        if not isinstance(decisions, list) or not 1 <= len(decisions) <= 24:
            raise ValueError("a review disposition requires 1-24 decisions")
        if any(row.get("decision") not in {"approved", "rejected"} for row in decisions):
            raise ValueError("invalid review decision")
        with self.lock:
            if commit:
                self.db.execute("BEGIN IMMEDIATE")
            elif not self.db.in_transaction:
                raise ValueError("group review requires an active owner transaction")
            try:
                for row in decisions:
                    values = tuple(row[key] for key in (
                        "proposal_id", "run_id", "task_ref", "target", "decision",
                    )) + (time.time(),)
                    existing = self.db.execute(
                        "SELECT run_id,task_ref,target,decision,decided_at "
                        "FROM review_decisions WHERE proposal_id=?", (values[0],),
                    ).fetchone()
                    if existing and existing[:4] != values[1:5]:
                        raise ValueError("proposal already has a different review decision")
                    if not existing:
                        self.db.execute(
                            "INSERT INTO review_decisions("
                            "proposal_id,run_id,task_ref,target,decision,decided_at"
                            ") VALUES(?,?,?,?,?,?)", values,
                        )
                if commit:
                    self.db.commit()
            except Exception:
                if commit:
                    self.db.rollback()
                raise

    def review_outcome(self, run_id: str) -> dict:
        with self.lock:
            rows = self.db.execute(
                "SELECT decision,target FROM review_decisions "
                "WHERE run_id=? ORDER BY decided_at,proposal_id",
                (run_id,),
            ).fetchall()
        approved = [target for decision, target in rows if decision == "approved"]
        rejected = [target for decision, target in rows if decision == "rejected"]
        return {
            "run_id": run_id,
            "approved_count": len(approved),
            "rejected_count": len(rejected),
            "approved_targets": approved,
            "rejected_targets": rejected,
        }

    def review_decision(self, proposal_id: str) -> dict | None:
        columns = ("proposal_id", "run_id", "task_ref", "target", "decision", "decided_at")
        with self.lock:
            row = self.db.execute(
                "SELECT " + ",".join(columns)
                + " FROM review_decisions WHERE proposal_id=?",
                (proposal_id,),
            ).fetchone()
        return dict(zip(columns, row)) if row else None

    def resolve_ingest_review(self, ingest_run_id: str) -> str:
        outcome = self.review_outcome(ingest_run_id)
        with self.lock:
            row = self.db.execute(
                f"SELECT {','.join(self._CONTINUATION_COLUMNS)} "
                "FROM task_continuations WHERE ingest_run_id=?",
                (ingest_run_id,),
            ).fetchone()
        continuation = self._continuation_row(row)
        if continuation is None:
            return ""
        if outcome["approved_count"]:
            self._ready_continuation(continuation["id"], {
                "disposition": "approved",
                "source_id": continuation["handoff_source_id"],
                "ingest_run_id": ingest_run_id,
                "review": outcome,
            })
            return "ready"
        if outcome["rejected_count"]:
            payload = self._continuation_result({
                "disposition": "rejected",
                "source_id": continuation["handoff_source_id"],
                "ingest_run_id": ingest_run_id,
                "review": outcome,
            })
            with self.lock:
                self.db.execute(
                    "UPDATE task_continuations SET status='rejected',result=?,updated_at=? "
                    "WHERE id=? AND status IN ('waiting','ingesting')",
                    (payload, time.time(), continuation["id"]),
                )
                self.db.commit()
            return "rejected"
        return ""

    def ready_continuations(self, limit: int = 20) -> list[dict]:
        with self.lock:
            rows = self.db.execute(
                f"SELECT {','.join(self._CONTINUATION_COLUMNS)} "
                "FROM task_continuations WHERE status='ready' "
                "ORDER BY created_at LIMIT ?",
                (max(0, limit),),
            ).fetchall()
        return [self._continuation_row(row) for row in rows]

    def claim_continuation(self, continuation_id: str) -> dict | None:
        """Claim at most once; a crash never automatically replays the resumed Task."""
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                changed = self.db.execute(
                    "UPDATE task_continuations SET status='claimed',updated_at=? "
                    "WHERE id=? AND status='ready'",
                    (time.time(), continuation_id),
                ).rowcount
                row = self.db.execute(
                    f"SELECT {','.join(self._CONTINUATION_COLUMNS)} "
                    "FROM task_continuations WHERE id=?",
                    (continuation_id,),
                ).fetchone()
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
        return self._continuation_row(row) if changed else None

    def finish_continuation(
        self,
        continuation_id: str,
        *,
        resumed_run_id: str,
        completed: bool,
    ) -> None:
        with self.lock:
            self.db.execute(
                "UPDATE task_continuations SET status=?,resumed_run_id=?,updated_at=? "
                "WHERE id=? AND status='claimed'",
                (
                    "resumed" if completed else "resume_failed",
                    resumed_run_id,
                    time.time(),
                    continuation_id,
                ),
            )
            self.db.commit()

    # ---------- deferred observation finalization ----------

    def defer_observation_finalization(
        self,
        conversation_id: str,
        session_boundary: str,
        *,
        error: str = "",
    ) -> None:
        now = time.time()
        with self.lock:
            self.db.execute(
                "INSERT INTO deferred_observation_finalizations("
                "conversation_id,session_boundary,created_at,updated_at,last_error"
                ") VALUES(?,?,?,?,?) ON CONFLICT(conversation_id) DO UPDATE SET "
                "session_boundary=excluded.session_boundary,updated_at=excluded.updated_at,"
                "last_error=excluded.last_error",
                (conversation_id, session_boundary, now, now, error[:1000]),
            )
            self.db.commit()

    def deferred_observation_finalizations(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute(
                "SELECT conversation_id,session_boundary,created_at,updated_at,last_error "
                "FROM deferred_observation_finalizations ORDER BY created_at"
            ).fetchall()
        columns = ("conversation_id", "session_boundary", "created_at", "updated_at", "last_error")
        return [dict(zip(columns, row)) for row in rows]

    def complete_observation_finalization(self, conversation_id: str) -> None:
        with self.lock:
            self.db.execute(
                "DELETE FROM deferred_observation_finalizations WHERE conversation_id=?",
                (conversation_id,),
            )
            self.db.commit()

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

    def conversation_turn(self, turn_id: str) -> dict | None:
        with self.lock:
            row = self.db.execute(
                "SELECT " + ",".join(self._CONVERSATION_TURN_COLUMNS)
                + " FROM conversation_turns WHERE id=?",
                (turn_id,),
            ).fetchone()
        return dict(zip(self._CONVERSATION_TURN_COLUMNS, row)) if row else None

    def assistant_reply_for(self, user_turn_id: str) -> dict | None:
        with self.lock:
            row = self.db.execute(
                "SELECT " + ",".join(self._CONVERSATION_TURN_COLUMNS)
                + " FROM conversation_turns WHERE reply_to=? AND role='assistant' "
                "AND state='final' ORDER BY sequence LIMIT 1",
                (user_turn_id,),
            ).fetchone()
        return dict(zip(self._CONVERSATION_TURN_COLUMNS, row)) if row else None

    # ---------- feed intake receipts, never a second content store ----------

    def connection_runtime(self, connection_id: str) -> dict:
        with self.lock:
            row = self.db.execute("SELECT state FROM connection_runtime WHERE connection_id=?", (connection_id,)).fetchone()
        return json.loads(row[0]) if row else {}

    def update_connection_runtime(self, connection_id: str, **fields) -> None:
        with self.lock, self.db:
            row = self.db.execute("SELECT state FROM connection_runtime WHERE connection_id=?", (connection_id,)).fetchone()
            state = json.loads(row[0]) if row else {}
            state.update(fields)
            self.db.execute(
                "INSERT INTO connection_runtime(connection_id,state,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(connection_id) DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at",
                (connection_id, json.dumps(state, sort_keys=True, allow_nan=False), time.time()),
            )

    def feed_runtime(self, feed_id: str) -> dict:
        with self.lock:
            row = self.db.execute("SELECT state FROM feed_runtime WHERE feed_id=?", (feed_id,)).fetchone()
        return json.loads(row[0]) if row else {}

    def update_feed_runtime(self, feed_id: str, **fields) -> dict:
        with self.lock, self.db:
            row = self.db.execute("SELECT state FROM feed_runtime WHERE feed_id=?", (feed_id,)).fetchone()
            state = json.loads(row[0]) if row else {}
            state.update(fields)
            self.db.execute(
                "INSERT INTO feed_runtime(feed_id,state,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(feed_id) DO UPDATE SET state=excluded.state,updated_at=excluded.updated_at",
                (feed_id, json.dumps(state, sort_keys=True, allow_nan=False), time.time()),
            )
        return state

    def record_feed_item(self, feed_id: str, item_key: str, source: dict, destination_ref: str = "",
                         distill_instructions: str = "") -> bool:
        """Remember one already-durable Source version; repeat capture is harmless."""
        with self.lock, self.db:
            cursor = self.db.execute(
                "INSERT OR IGNORE INTO feed_items(feed_id,item_key,content_sha256,source_id,source_path,captured_at,destination_ref,distill_instructions) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (feed_id, item_key, source["content_sha256"], source["id"], source["path"], source["captured_at"], destination_ref, distill_instructions),
            )
            created = cursor.rowcount == 1
            self.db.execute(
                "UPDATE feed_items SET last_seen_at=? WHERE feed_id=? AND item_key=? AND content_sha256=?",
                (time.time(), feed_id, item_key, source["content_sha256"]),
            )
        return created

    def feed_source_binding(self, source_id: str) -> dict | None:
        """Read controller-written provenance, never provider-authored routing."""
        with self.lock:
            rows = self.db.execute(
                "SELECT f.feed_id,f.item_key,f.destination_ref,f.source_id,f.content_sha256,f.distill_instructions "
                "FROM feed_items f JOIN source_evidence s ON s.id=f.source_id "
                "WHERE f.source_id=? AND f.content_sha256=s.content_sha256 AND f.source_path=s.path",
                (source_id,),
            ).fetchall()
        if not rows:
            return None
        if len(rows) != 1:
            raise ValueError("Feed Source has ambiguous controller receipts")
        return dict(zip(("feed_id", "item_key", "destination_ref", "source_id", "source_sha256", "distill_instructions"), rows[0]))

    def bind_feed_destination(self, feed_id: str, destination_ref: str) -> int:
        """Migration-only binding for legacy receipts without a destination."""
        if not destination_ref:
            raise ValueError("Feed destination must be nonempty")
        with self.lock, self.db:
            if self.db.execute("SELECT 1 FROM feed_items WHERE feed_id=? AND destination_ref NOT IN ('',?)",
                               (feed_id, destination_ref)).fetchone():
                raise ValueError("A captured Feed destination cannot be replaced")
            return self.db.execute("UPDATE feed_items SET destination_ref=? WHERE feed_id=? AND destination_ref=''",
                                   (destination_ref, feed_id)).rowcount

    def feed_item_summary(self, feed_id: str) -> dict:
        with self.lock:
            counts = self.db.execute(
                "SELECT COUNT(DISTINCT item_key),COUNT(*) FROM feed_items WHERE feed_id=?", (feed_id,),
            ).fetchone()
            latest = self.db.execute(
                "SELECT source_id,source_path FROM feed_items WHERE feed_id=? ORDER BY last_seen_at DESC,rowid DESC LIMIT 1",
                (feed_id,),
            ).fetchone()
        return {"item_count": counts[0], "source_count": counts[1],
                "last_source": "source://" + latest[0] if latest else "",
                "last_source_id": latest[0] if latest else "",
                "last_source_path": "obsidience/evidence/" + latest[1] if latest else ""}

    def feed_item_sources(self, *, feed_id: str | None = None, source_id: str | None = None,
                          limit: int = 100) -> list[dict]:
        """Read existing Source material; list only the latest native-item versions."""
        conditions, arguments = [], []
        if feed_id is not None:
            conditions.append("f.feed_id=?")
            arguments.append(feed_id)
        if source_id is not None:
            conditions.append("f.source_id=?")
            arguments.append(source_id)
        else:
            conditions.append("NOT EXISTS (SELECT 1 FROM feed_items newer WHERE "
                              "newer.feed_id=f.feed_id AND newer.item_key=f.item_key AND "
                              "(newer.last_seen_at>f.last_seen_at OR "
                              "(newer.last_seen_at=f.last_seen_at AND newer.rowid>f.rowid)))")
        columns = ("feed_id", "item_key", *self._SOURCE_COLUMNS)
        with self.lock:
            rows = self.db.execute(
                "SELECT f.feed_id,f.item_key," + ",".join("s." + name for name in self._SOURCE_COLUMNS)
                + " FROM feed_items f JOIN source_evidence s ON s.id=f.source_id WHERE "
                + " AND ".join(conditions) + " ORDER BY f.last_seen_at DESC,f.rowid DESC LIMIT ?", (*arguments, limit),
            ).fetchall()
        return [dict(zip(columns, row)) for row in rows]

    # ---------- immutable source evidence ----------

    _SOURCE_COLUMNS = (
        "id", "path", "source_type", "source_ref", "media_type", "captured_at",
        "content_sha256", "material_sha256", "material", "created_at",
        "event_key", "event_dispatched_at", "origin_source_id",
    )

    def record_source(self, *, feed_receipt: dict | None = None, **kw) -> bool:
        with self.lock:
            try:
                self.db.execute("BEGIN IMMEDIATE")
                self.db.execute(
                    "INSERT INTO source_evidence(" + ",".join(self._SOURCE_COLUMNS)
                    + ") VALUES(" + ",".join(f":{name}" for name in self._SOURCE_COLUMNS) + ")",
                    {"origin_source_id": "", **kw},
                )
                created = False
                if feed_receipt is not None:
                    cursor = self.db.execute(
                        "INSERT INTO feed_items(feed_id,item_key,content_sha256,source_id,source_path,captured_at,last_seen_at,destination_ref,distill_instructions) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                        (feed_receipt["feed_id"], feed_receipt["item_key"], kw["content_sha256"], kw["id"],
                         kw["path"], kw["captured_at"], time.time(), feed_receipt["destination_ref"],
                         feed_receipt.get("distill_instructions", "")),
                    )
                    created = cursor.rowcount == 1
                self.db.commit()
                return created
            except BaseException:
                self.db.rollback()
                raise

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

    def source_by_event_key(self, event_key: str) -> dict | None:
        row = self.db.execute(
            f"SELECT {','.join(self._SOURCE_COLUMNS)} FROM source_evidence WHERE event_key=?",
            (event_key,),
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
