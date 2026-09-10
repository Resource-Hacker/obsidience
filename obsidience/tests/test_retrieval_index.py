from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from obsidience.harness.knowledge import index as indexer
from obsidience.harness.knowledge.vault import Note


class _FakeEncoder:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.fail = False
        self.block_text: str | None = None
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, texts: list[str]) -> np.ndarray:
        batch = tuple(texts)
        self.calls.append(batch)
        if self.fail:
            raise RuntimeError("synthetic encoder failure")
        if self.block_text in batch:
            self.entered.set()
            if not self.release.wait(timeout=5):
                raise RuntimeError("synthetic encoder was not released")
        return np.array(
            [
                [
                    float(sum(text.encode()) % 251 + 1),
                    float(sum(reversed(text.encode())) % 241 + len(text) + 1),
                ]
                for text in texts
            ],
            dtype=np.float32,
        )


def _note(
    *,
    title: str = "Alpha",
    body: str = "oldtoken alpha body",
    status: str = "ready",
) -> Note:
    return Note(
        path="Knowledge/alpha.md",
        title=title,
        meta={"kind": "knowledge", "title": title, "status": status},
        body=body,
    )


def _database_snapshot(ledger: indexer.Index) -> tuple[tuple, tuple, tuple]:
    return (
        tuple(ledger.db.execute("SELECT * FROM notes ORDER BY ref")),
        tuple(ledger.db.execute("SELECT ref,title,body FROM notes_fts ORDER BY ref")),
        tuple(ledger.db.execute("SELECT * FROM embeddings ORDER BY ref")),
    )


@pytest.fixture
def isolated_index(tmp_path, monkeypatch):
    state = {"notes": [], "model_hash": "model-a"}
    encoder = _FakeEncoder()
    monkeypatch.setattr(indexer.CONFIG, "db_path", tmp_path / "retrieval.sqlite3")
    monkeypatch.setattr(indexer, "iter_notes", lambda: list(state["notes"]))
    monkeypatch.setattr(indexer, "_embedding_model_hash", lambda: state["model_hash"])
    monkeypatch.setattr(indexer, "embed_texts", encoder)
    ledger = indexer.Index()
    try:
        yield ledger, state, encoder
    finally:
        ledger.db.close()


def _add_article(
    ledger: indexer.Index,
    *,
    ref: str,
    kind: str,
    vector: tuple[float, float],
) -> None:
    ledger.db.execute(
        "INSERT INTO notes(ref,path,title,kind,mtime,hash,meta,links) "
        "VALUES(?,?,?,?,?,?,?,?)",
        (ref, f"{ref}.md", ref, kind, 0.0, ref, "{}", "[]"),
    )
    ledger.db.execute(
        "INSERT INTO notes_fts(ref,title,body) VALUES(?,?,?)",
        (ref, "shared term", "shared term"),
    )
    value = np.array(vector, dtype=np.float32)
    ledger.db.execute(
        "INSERT INTO embeddings(ref,hash,dim,vec) VALUES(?,?,?,?)",
        (ref, ref, len(value), value.tobytes()),
    )


def test_search_lanes_filter_kind_before_ranking(tmp_path, monkeypatch) -> None:
    database = tmp_path / "retrieval.sqlite3"
    monkeypatch.setattr(indexer.CONFIG, "db_path", database)
    ledger = indexer.Index()
    try:
        _add_article(
            ledger,
            ref="Tools/crowding",
            kind="tool",
            vector=(1.0, 0.0),
        )
        _add_article(
            ledger,
            ref="Knowledge/eligible",
            kind="knowledge",
            vector=(0.9, 0.1),
        )
        ledger.db.commit()
        monkeypatch.setattr(
            indexer,
            "embed_texts",
            lambda _texts: np.array([[1.0, 0.0]], dtype=np.float32),
        )

        assert ledger.fts("shared term", 1, "knowledge")[0][0] == "Knowledge/eligible"
        assert ledger.vector("query", 1, "knowledge")[0][0] == "Knowledge/eligible"
        assert ledger.vector("query", 1)[0][0] == "Tools/crowding"
    finally:
        ledger.db.close()


def test_vector_matrix_is_reused_until_database_changes(
    tmp_path,
    monkeypatch,
) -> None:
    database = tmp_path / "retrieval-cache.sqlite3"
    monkeypatch.setattr(indexer.CONFIG, "db_path", database)
    ledger = indexer.Index()
    try:
        _add_article(
            ledger,
            ref="Knowledge/first",
            kind="knowledge",
            vector=(1.0, 0.0),
        )
        ledger.db.commit()
        monkeypatch.setattr(
            indexer,
            "embed_texts",
            lambda _texts: np.array([[1.0, 0.0]], dtype=np.float32),
        )
        real_stack = indexer.np.stack
        stack_calls = 0

        def counted_stack(*args, **kwargs):
            nonlocal stack_calls
            stack_calls += 1
            return real_stack(*args, **kwargs)

        monkeypatch.setattr(indexer.np, "stack", counted_stack)
        kind = "knowledge"

        assert ledger.vector("first", 2, kind)[0][0] == "Knowledge/first"
        assert ledger.vector("second", 2, kind)[0][0] == "Knowledge/first"
        assert stack_calls == 1

        external = sqlite3.connect(database)
        value = np.array((0.8, 0.2), dtype=np.float32)
        external.execute(
            "INSERT INTO notes(ref,path,title,kind,mtime,hash,meta,links) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (
                "Knowledge/second",
                "Knowledge/second.md",
                "Second",
                "knowledge",
                0.0,
                "second",
                "{}",
                "[]",
            ),
        )
        external.execute(
            "INSERT INTO embeddings(ref,hash,dim,vec) VALUES(?,?,?,?)",
            ("Knowledge/second", "second", len(value), value.tobytes()),
        )
        external.commit()
        external.close()

        assert len(ledger.vector("third", 2, kind)) == 2
        assert stack_calls == 2
    finally:
        ledger.db.close()


def test_metadata_only_sync_reuses_embedding_and_cached_matrix(
    isolated_index,
) -> None:
    ledger, state, encoder = isolated_index
    state["notes"] = [_note()]
    ledger.sync()
    ledger._vector_corpus("knowledge")
    embedding_before = ledger.db.execute(
        "SELECT hash,dim,vec FROM embeddings WHERE ref='Knowledge/alpha'"
    ).fetchone()
    cache_before = ledger._vector_cache["knowledge"]
    revision_before = ledger._vector_revision
    encoder.calls.clear()

    state["notes"] = [_note(status="running")]
    result = ledger.sync()

    assert result["updated"] == 1
    assert encoder.calls == []
    assert (
        ledger.db.execute(
            "SELECT hash,dim,vec FROM embeddings WHERE ref='Knowledge/alpha'"
        ).fetchone()
        == embedding_before
    )
    assert ledger._vector_revision == revision_before
    ledger._vector_corpus("knowledge")
    assert ledger._vector_cache["knowledge"] is cache_before


def test_body_change_after_embedding_cutoff_updates_only_fts(
    isolated_index,
) -> None:
    ledger, state, encoder = isolated_index
    prefix = "a" * 4000
    state["notes"] = [_note(body=prefix + " oldtailtoken")]
    ledger.sync()
    ledger._vector_corpus("knowledge")
    embedding_before = ledger.db.execute(
        "SELECT hash,dim,vec FROM embeddings WHERE ref='Knowledge/alpha'"
    ).fetchone()
    cache_before = ledger._vector_cache["knowledge"]
    revision_before = ledger._vector_revision
    encoder.calls.clear()

    state["notes"] = [_note(body=prefix + " newtailtoken")]
    ledger.sync()

    assert encoder.calls == []
    assert ledger.fts("oldtailtoken", 1, "knowledge") == []
    assert ledger.fts("newtailtoken", 1, "knowledge")[0][0] == "Knowledge/alpha"
    assert (
        ledger.db.execute(
            "SELECT hash,dim,vec FROM embeddings WHERE ref='Knowledge/alpha'"
        ).fetchone()
        == embedding_before
    )
    assert ledger._vector_revision == revision_before
    assert ledger._vector_cache["knowledge"] is cache_before


@pytest.mark.parametrize("change", ["body", "title", "model"])
def test_embedding_inputs_trigger_reencoding(isolated_index, change: str) -> None:
    ledger, state, encoder = isolated_index
    state["notes"] = [_note()]
    ledger.sync()
    first_hash = ledger.db.execute(
        "SELECT hash FROM embeddings WHERE ref='Knowledge/alpha'"
    ).fetchone()[0]
    revision_before = ledger._vector_revision
    encoder.calls.clear()

    if change == "body":
        state["notes"] = [_note(body="newtoken revised body")]
    elif change == "title":
        state["notes"] = [_note(title="Beta")]
    else:
        state["model_hash"] = "model-b"

    ledger.sync()

    expected = indexer._embedding_text(
        state["notes"][0].title,
        state["notes"][0].body,
    )
    assert encoder.calls == [(expected,)]
    assert (
        ledger.db.execute(
            "SELECT hash FROM embeddings WHERE ref='Knowledge/alpha'"
        ).fetchone()[0]
        != first_hash
    )
    assert ledger._vector_revision == revision_before + 1


def test_embed_false_removes_stale_vector_then_later_repairs_it(
    isolated_index,
) -> None:
    ledger, state, encoder = isolated_index
    state["notes"] = [_note()]
    ledger.sync()
    encoder.calls.clear()

    state["notes"] = [_note(body="newtoken replacement body")]
    ledger.sync(embed=False)

    assert encoder.calls == []
    assert (
        ledger.db.execute(
            "SELECT count(*) FROM embeddings WHERE ref='Knowledge/alpha'"
        ).fetchone()[0]
        == 0
    )
    assert ledger.fts("newtoken", 1, "knowledge")[0][0] == "Knowledge/alpha"

    ledger.sync()

    assert encoder.calls == [
        (indexer._embedding_text("Alpha", "newtoken replacement body"),)
    ]
    assert (
        ledger.db.execute(
            "SELECT count(*) FROM embeddings WHERE ref='Knowledge/alpha'"
        ).fetchone()[0]
        == 1
    )


def test_encoder_failure_publishes_nothing(isolated_index) -> None:
    ledger, state, encoder = isolated_index
    state["notes"] = [_note()]
    ledger.sync()
    ledger._vector_corpus("knowledge")
    database_before = _database_snapshot(ledger)
    cache_before = ledger._vector_cache["knowledge"]

    state["notes"] = [_note(body="newtoken unpublished body")]
    encoder.fail = True
    with pytest.raises(RuntimeError, match="synthetic encoder failure"):
        ledger.sync()

    assert _database_snapshot(ledger) == database_before
    assert ledger._vector_cache["knowledge"] is cache_before


def test_reader_sees_complete_old_index_while_encoder_is_blocked(
    isolated_index,
) -> None:
    ledger, state, encoder = isolated_index
    state["notes"] = [_note()]
    ledger.sync()
    old_matrix = ledger._vector_corpus("knowledge")[1].copy()
    state["notes"] = [_note(body="newtoken beta replacement")]
    encoder.block_text = indexer._embedding_text(
        state["notes"][0].title,
        state["notes"][0].body,
    )
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(ledger.sync)
        entered = encoder.entered.wait(timeout=2)
        try:
            assert entered
            assert ledger.fts("oldtoken", 1, "knowledge")[0][0] == "Knowledge/alpha"
            assert ledger.fts("newtoken", 1, "knowledge") == []
            assert (
                ledger.vector("reader query", 1, "knowledge")[0][0] == "Knowledge/alpha"
            )
            assert np.array_equal(ledger._vector_corpus("knowledge")[1], old_matrix)
        finally:
            encoder.release.set()
        future.result(timeout=3)

    assert ledger.fts("oldtoken", 1, "knowledge") == []
    assert ledger.fts("newtoken", 1, "knowledge")[0][0] == "Knowledge/alpha"
    assert not np.array_equal(ledger._vector_corpus("knowledge")[1], old_matrix)


def test_two_indexes_serialize_snapshot_and_publication_with_flock(
    tmp_path,
    monkeypatch,
) -> None:
    database = tmp_path / "shared-retrieval.sqlite3"
    monkeypatch.setattr(indexer.CONFIG, "db_path", database)
    first = indexer.Index()
    second = indexer.Index()
    encoder = _FakeEncoder()
    first_note = _note(body="firsttoken initial body")
    second_note = _note(body="secondtoken replacement body")
    encoder.block_text = indexer._embedding_text(first_note.title, first_note.body)
    first_published = threading.Event()
    second_started_sync = threading.Event()
    second_attempted_lock = threading.Event()
    second_read_snapshot = threading.Event()
    second_snapshot_after_publish: list[bool] = []
    sync_role = threading.local()

    def notes_for_sync() -> list[Note]:
        if sync_role.name == "first":
            return [first_note]
        assert sync_role.name == "second"
        second_read_snapshot.set()
        second_snapshot_after_publish.append(first_published.is_set())
        return [second_note]

    original_first_sync = first._sync

    def marked_first_sync(embed: bool) -> dict:
        result = original_first_sync(embed)
        first_published.set()
        return result

    real_flock = indexer.fcntl.flock

    def observed_flock(lockfile, operation) -> None:
        if sync_role.name == "second":
            second_attempted_lock.set()
        real_flock(lockfile, operation)

    monkeypatch.setattr(indexer, "iter_notes", notes_for_sync)
    monkeypatch.setattr(indexer, "_embedding_model_hash", lambda: "model-a")
    monkeypatch.setattr(indexer, "embed_texts", encoder)
    monkeypatch.setattr(first, "_sync", marked_first_sync)
    monkeypatch.setattr(indexer.fcntl, "flock", observed_flock)

    def synchronize(ledger: indexer.Index, role: str) -> dict:
        sync_role.name = role
        if role == "second":
            second_started_sync.set()
        return ledger.sync()

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(synchronize, first, "first")
            assert encoder.entered.wait(timeout=2)
            second_future = pool.submit(synchronize, second, "second")
            assert second_started_sync.wait(timeout=2)
            # Group Review shares the Article lock: the second synchronizer
            # waits before flock and before taking its source snapshot.
            assert not second_attempted_lock.is_set()
            assert not second_read_snapshot.is_set()

            encoder.release.set()
            first_future.result(timeout=3)
            second_future.result(timeout=3)

        assert second_attempted_lock.is_set()
        assert second_snapshot_after_publish == [True]
        assert second.fts("firsttoken", 1, "knowledge") == []
        assert second.fts("secondtoken", 1, "knowledge")[0][0] == "Knowledge/alpha"
    finally:
        encoder.release.set()
        first.db.close()
        second.db.close()


def test_sync_repairs_missing_fts_without_reencoding_valid_vector(
    isolated_index,
) -> None:
    ledger, state, encoder = isolated_index
    state["notes"] = [_note(body="repairtoken retained vector")]
    ledger.sync()
    ledger._vector_corpus("knowledge")
    embedding_before = ledger.db.execute(
        "SELECT hash,dim,vec FROM embeddings WHERE ref='Knowledge/alpha'"
    ).fetchone()
    cache_before = ledger._vector_cache["knowledge"]
    revision_before = ledger._vector_revision
    ledger.db.execute("DELETE FROM notes_fts WHERE ref='Knowledge/alpha'")
    ledger.db.commit()
    encoder.calls.clear()

    ledger.sync()

    assert encoder.calls == []
    assert ledger.fts("repairtoken", 1, "knowledge")[0][0] == "Knowledge/alpha"
    assert (
        ledger.db.execute(
            "SELECT hash,dim,vec FROM embeddings WHERE ref='Knowledge/alpha'"
        ).fetchone()
        == embedding_before
    )
    assert ledger._vector_revision == revision_before
    assert ledger._vector_cache["knowledge"] is cache_before


def test_sync_removes_embedding_without_a_note(isolated_index) -> None:
    ledger, state, encoder = isolated_index
    state["notes"] = [_note()]
    ledger.sync()
    orphan = np.array([1.0, 0.0], dtype=np.float32)
    ledger.db.execute(
        "INSERT INTO embeddings(ref,hash,dim,vec) VALUES(?,?,?,?)",
        ("Knowledge/orphan", "orphan", len(orphan), orphan.tobytes()),
    )
    ledger.db.commit()
    encoder.calls.clear()

    ledger.sync()

    assert encoder.calls == []
    assert (
        ledger.db.execute(
            "SELECT count(*) FROM embeddings WHERE ref='Knowledge/orphan'"
        ).fetchone()[0]
        == 0
    )
    assert (
        ledger.db.execute(
            "SELECT count(*) FROM embeddings WHERE ref='Knowledge/alpha'"
        ).fetchone()[0]
        == 1
    )


@pytest.mark.parametrize(
    "query",
    ["DP-4", '"DP-4"', "window.place", '"quoted phrase"'],
)
def test_fts_treats_punctuation_and_quotes_as_literal_text(
    isolated_index,
    query: str,
) -> None:
    ledger, state, _encoder = isolated_index
    state["notes"] = [
        _note(body='Use window.place on DP-4 after the operator says "quoted phrase".')
    ]
    ledger.sync(embed=False)

    assert ledger.fts(query, 1, "knowledge")[0][0] == "Knowledge/alpha"
