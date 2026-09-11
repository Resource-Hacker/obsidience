"""Scoped discovery filters the real candidate corpus before both lane limits."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone

import numpy as np
import pytest

from obsidience.harness.capabilities.vault import search as adapter
from obsidience.harness.knowledge import index as indexer, retrieval, vault
from obsidience.harness.knowledge.vault import Note


SCOPE = {"kind": "knowledge", "current_only": True,
         "exclude_subtrees": ["News & Research/Top 10"]}


@pytest.fixture
def corpus(monkeypatch, isolated_task_ledger):
    ledger = isolated_task_ledger
    notes = []
    snapshots = []
    encoded = []

    def snapshot():
        snapshots.append(len(notes))
        return list(notes)

    def encode(texts):
        encoded.extend(texts)
        return np.array([[1.0, 0.0]] * len(texts), dtype=np.float32)

    def add(ref, *, kind="knowledge", meta=None, score=1.0, body="shared term"):
        note = Note(ref + ".md", ref, {"kind": kind, **(meta or {})}, body)
        notes.append(note)
        ledger.db.execute("INSERT INTO notes(ref,path,title,kind,mtime,hash,meta,links) VALUES(?,?,?,?,?,?,?,?)",
                          (ref, note.path, note.title, kind, 0, ref, json.dumps(note.meta), "[]"))
        ledger.db.execute("INSERT INTO notes_fts(ref,title,body) VALUES(?,?,?)", (ref, "shared term", body))
        ledger.db.execute("INSERT INTO embeddings(ref,hash,dim,vec) VALUES(?,?,?,?)",
                          (ref, ref, 2, np.array([score, 0.0], dtype=np.float32).tobytes()))
        ledger.db.commit()
        ledger._vector_cache.clear()
        return note

    monkeypatch.setattr(retrieval, "INDEX", ledger)
    monkeypatch.setattr(retrieval, "iter_notes", snapshot)
    monkeypatch.setattr(vault, "iter_notes", snapshot)
    monkeypatch.setattr(retrieval, "load_note", lambda path: next((note for note in notes if note.path == path), None))
    monkeypatch.setattr(indexer, "embed_texts", encode)
    return ledger, add, notes, snapshots, encoded


@pytest.mark.parametrize("lane", ["fts", "vector"])
def test_scope_selects_eligible_candidate_before_full_lane_limit(corpus, lane):
    ledger, add, _notes, _snapshots, _encoded = corpus
    for i in range(30):
        add(f"News & Research/Top 10/crowding-{i}")
    eligible = add("Knowledge/related", score=0.8, body="shared term " + "filler " * 100)
    assert eligible.ref not in dict(getattr(ledger, lane)("shared term", 24))
    assert list(dict(getattr(ledger, lane)("shared term", 24, eligible_refs={eligible.ref}))) == [eligible.ref]
    assert [hit["ref"] for hit in retrieval.search("shared term", scope=SCOPE)] == [eligible.ref]


def test_kind_lifecycle_and_subtree_masks_apply_before_tool_cap(corpus):
    _ledger, add, _notes, _snapshots, _encoded = corpus
    for i in range(8):
        add(f"News & Research/Top 10/crowd-{i}")
        add(f"Tools/crowd-{i}", kind="tool")
        add(f"Knowledge/deprecated-{i}", meta={"article_status": "deprecated"})
        add(f"Knowledge/expired-{i}", meta={"stale_after": "2000-01-01T00:00:00Z"})
    add("News & Research/Top 10")
    add("Knowledge/hidden", meta={"retrieval": False})
    add("Knowledge/immediate", meta={"immediate": True})
    add("Knowledge/temporary", meta={"temporary": True})
    eligible = add("News & Research/Top 100/related", score=0.7)
    context = {}
    results = json.loads(adapter.execute({"queries": ["shared term"], "scope": SCOPE}, context))["results"]
    assert results[0]["ok"] and eligible.ref in results[0]["result"]
    assert context["_vault_searches"] == {"shared term": {"refs": [eligible.ref], "scope": SCOPE}}


def test_scoped_batch_order_and_receipts_use_only_displayed_snapshot_hits(corpus):
    _ledger, add, _notes, snapshots, _encoded = corpus
    for i in range(8):
        add(f"Knowledge/{i}", score=1 - i * 0.01)
    args = {"queries": [" first headline ", "second headline"], "scope": {
        "exclude_subtrees": ["Z", "A"], "current_only": True, "kind": "knowledge"}}
    context = {}
    rows = json.loads(adapter.execute(args, context))["results"]
    assert [row["query"] for row in rows] == args["queries"]
    assert snapshots == [8]
    expected_scope = {"kind": "knowledge", "current_only": True, "exclude_subtrees": ["A", "Z"]}
    for row in rows:
        receipt = context["_vault_searches"][row["query"]]
        assert receipt["scope"] == expected_scope
        assert len(receipt["refs"]) == 5
        assert all(f"[[{ref}]]" in row["result"] for ref in receipt["refs"])
    args["scope"]["exclude_subtrees"].append("Knowledge")
    assert context["_vault_searches"][" first headline "]["scope"] == expected_scope
    context["_vault_searches"][" first headline "]["scope"]["exclude_subtrees"].append("Other")
    assert context["_vault_searches"]["second headline"]["scope"] == expected_scope
    assert "scope" not in rows[0] and "current_only" not in rows[0]["result"]


def test_scoped_empty_result_is_successful_examination_without_forced_candidates(corpus):
    _ledger, add, _notes, snapshots, encoded = corpus
    add("Tools/unrelated", kind="tool")
    add("News & Research/Top 10/current-story")
    context = {}
    rows = json.loads(adapter.execute({"queries": ["headline", "other headline"], "scope": SCOPE}, context))["results"]
    assert all(row["ok"] and row["result"] == "No results." for row in rows)
    assert context["_vault_searches"] == {query: {"refs": [], "scope": SCOPE}
                                        for query in ["headline", "other headline"]}
    assert snapshots == [2] and not encoded


def test_scoped_freshness_expires_without_index_rebuild(corpus, monkeypatch):
    ledger, add, _notes, _snapshots, _encoded = corpus

    class Clock:
        current = datetime(2026, 9, 7, tzinfo=timezone.utc)

        @classmethod
        def now(cls, _tz):
            return cls.current

    note = add("Knowledge/timed", meta={"stale_after": "2026-09-07T01:00:00Z"})
    monkeypatch.setattr(retrieval, "datetime", Clock)
    before = list(ledger.db.execute("SELECT * FROM notes"))
    assert retrieval.search("shared", scope=SCOPE)[0]["ref"] == note.ref
    matrix = ledger._vector_corpus("knowledge")[1]
    Clock.current = datetime(2026, 9, 7, 1, tzinfo=timezone.utc)
    assert retrieval.search("shared", scope=SCOPE) == []
    assert list(ledger.db.execute("SELECT * FROM notes")) == before
    assert ledger._vector_corpus("knowledge")[1] is matrix


def test_unscoped_search_keeps_mixed_kinds_and_historical_content(corpus):
    _ledger, add, _notes, snapshots, _encoded = corpus
    refs = [add("Tools/tool", kind="tool").ref,
            add("Knowledge/stale", meta={"stale_after": "2000-01-01T00:00:00Z"}).ref,
            add("Knowledge/old", meta={"article_status": "deprecated"}).ref]
    context = {}
    adapter.execute({"query": "shared"}, context)
    assert set(context["_vault_searches"]["shared"]["refs"]) == set(refs)
    assert "scope" not in context["_vault_searches"]["shared"] and len(snapshots) == 1
    assert {hit["ref"] for hit in retrieval.search("shared", scope={"kind": "knowledge"})} == set(refs[1:])


@pytest.mark.parametrize("scope", [
    None, [], "knowledge", {"unknown": True}, {"kind": "source"}, {"kind": []}, {"kind": None},
    {"current_only": 1}, {"current_only": "true"}, {"exclude_subtrees": "Knowledge"},
    {"exclude_subtrees": ["X"] * 11}, {"exclude_subtrees": ["X", "X"]},
    *[{"exclude_subtrees": [root]} for root in ["", "/X", "X/", "X//Y", "X/../Y", "./X", " X", "X /Y", "X.md", "[[X]]", "X#Y", "X|Y", "X\\Y", "X\nY", "X\x7fY", "X" * 301, None]],
])
def test_malformed_scope_rejected_without_retrieval_or_stale_receipt(corpus, scope):
    _ledger, _add, _notes, snapshots, encoded = corpus
    context = {"_vault_searches": {"headline": {"refs": ["Knowledge/old"], "scope": SCOPE},
                                   "unrelated": {"refs": []}}}
    result = adapter.execute({"query": "headline", "scope": scope}, context)
    assert result.startswith("Invalid search scope:")
    assert context["_vault_searches"] == {"unrelated": {"refs": []}}
    assert not snapshots and not encoded


def test_cancelled_scope_batch_never_attests_unshown_results(corpus):
    _ledger, add, _notes, snapshots, encoded = corpus
    add("Knowledge/current")
    cancel = threading.Event()
    cancel.set()
    context = {"_capability_cancel_event": cancel,
               "_vault_searches": {"headline": {"refs": ["Knowledge/current"], "scope": SCOPE}}}
    rows = json.loads(adapter.execute({"queries": ["headline", "next"], "scope": SCOPE}, context))["results"]
    assert all(not row["ok"] for row in rows)
    assert context["_vault_searches"] == {} and not snapshots and not encoded

pytestmark = pytest.mark.usefixtures("authorized_reader_scope")
