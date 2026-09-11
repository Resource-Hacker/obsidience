from __future__ import annotations

import json

import frontmatter
import numpy as np
import pytest

from obsidience.harness.knowledge import index as indexer
from obsidience.harness.knowledge import retrieval
from obsidience.harness.knowledge.vault import Resolver, iter_notes, load_note, move_vault_item


@pytest.fixture
def graph_index(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(indexer.CONFIG, "vault_dir", vault)
    monkeypatch.setattr(indexer.CONFIG, "db_path", tmp_path / "index.sqlite3")
    monkeypatch.setattr(indexer, "_embedding_model_hash", lambda: "test-model")
    encoded: list[str] = []

    def encode(texts: list[str]) -> np.ndarray:
        encoded.extend(texts)
        return np.array([[1.0, 0.0] for _ in texts], dtype=np.float32)

    def write(ref: str, body: str = "Article body", **meta):
        path = vault / f"{ref}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        metadata = {"kind": "knowledge", "title": ref.rsplit("/", 1)[-1], **meta}
        path.write_text(frontmatter.dumps(frontmatter.Post(body, **metadata)) + "\n")
        return path

    monkeypatch.setattr(indexer, "embed_texts", encode)
    ledger = indexer.Index()
    monkeypatch.setattr(retrieval, "INDEX", ledger)
    # Keep only the seed in search so this exercises actual graph expansion.
    monkeypatch.setattr(
        retrieval,
        "_lanes_for",
        lambda *_args, **_kwargs: [(1.0, [("Knowledge/seed", 1.0)])],
    )
    try:
        yield ledger, write, encoded
    finally:
        ledger.db.close()


def _edges(ledger) -> set[tuple[str, str]]:
    return {(edge["source"], edge["target"]) for edge in ledger.graph()["links"]}


def _context_refs() -> list[str]:
    return retrieval.fast_context_with_refs("seed", set(), limit=3)[1]


def test_changed_article_keeps_edge_to_unchanged_target(graph_index):
    ledger, write, encoded = graph_index
    write("Knowledge/seed", "Original [[Knowledge/target]]")
    write("Knowledge/target", "Retained target")
    ledger.sync()
    target_before = ledger.db.execute(
        "SELECT * FROM embeddings WHERE ref='Knowledge/target'"
    ).fetchone()
    encoded.clear()

    write("Knowledge/seed", "Revised [[Knowledge/target]]")
    assert ledger.sync() == {"total": 2, "added": 0, "updated": 1, "removed": 0}

    assert encoded == ["seed\nRevised [[Knowledge/target]]\n"]
    assert ledger.db.execute(
        "SELECT * FROM embeddings WHERE ref='Knowledge/target'"
    ).fetchone() == target_before
    assert _edges(ledger) == {("Knowledge/seed", "Knowledge/target")}
    assert _context_refs() == ["Knowledge/seed", "Knowledge/target"]


def test_frontmatter_links_replace_edges_without_reencoding(graph_index):
    ledger, write, encoded = graph_index
    write("Knowledge/seed", links=["[[Knowledge/old]]"])
    write("Knowledge/old")
    write("Knowledge/new")
    ledger.sync()
    encoded.clear()

    write("Knowledge/seed", links=["[[Knowledge/new#Details|New target]]"])
    result = ledger.sync()

    assert result["updated"] == 1
    assert encoded == []
    assert json.loads(ledger.db.execute(
        "SELECT links FROM notes WHERE ref='Knowledge/seed'"
    ).fetchone()[0]) == ["Knowledge/new"]
    assert _edges(ledger) == {("Knowledge/seed", "Knowledge/new")}
    assert _context_refs() == ["Knowledge/seed", "Knowledge/new"]


def test_new_target_resolves_preexisting_link_without_reencoding_seed(graph_index):
    ledger, write, encoded = graph_index
    write("Knowledge/seed", links=["[[Knowledge/target]]"])
    ledger.sync()
    assert _edges(ledger) == set()
    encoded.clear()

    write("Knowledge/target", "New target")
    ledger.sync()

    assert encoded == ["target\nNew target\n"]
    assert _edges(ledger) == {("Knowledge/seed", "Knowledge/target")}
    assert _context_refs() == ["Knowledge/seed", "Knowledge/target"]


def test_kind_change_reuses_embedding_but_invalidates_kind_filtered_cache(graph_index):
    ledger, write, encoded = graph_index
    write("Knowledge/seed", links=["[[Knowledge/target]]"])
    write("Knowledge/target", "uniquequery")
    ledger.sync()
    ledger._vector_corpus("knowledge")
    ledger._vector_corpus("tool")
    embedding_before = ledger.db.execute(
        "SELECT * FROM embeddings WHERE ref='Knowledge/target'"
    ).fetchone()
    encoded.clear()

    write("Knowledge/target", "uniquequery", kind="tool")
    ledger.sync()

    assert encoded == []
    assert ledger.db.execute(
        "SELECT * FROM embeddings WHERE ref='Knowledge/target'"
    ).fetchone() == embedding_before
    assert ledger.fts("uniquequery", 1, "knowledge") == []
    assert ledger.fts("uniquequery", 1, "tool")[0][0] == "Knowledge/target"
    assert ledger._vector_corpus("knowledge")[0] == ("Knowledge/seed",)
    assert ledger._vector_corpus("tool")[0] == ("Knowledge/target",)
    assert _context_refs() == ["Knowledge/seed"]


@pytest.mark.parametrize("metadata", [{"retrieval": False}, {"temporary": True}])
def test_retrieval_metadata_removes_both_lanes_and_neighbor_then_restores(
    graph_index, metadata,
):
    ledger, write, encoded = graph_index
    write("Knowledge/seed", links=["[[Knowledge/target]]"])
    write("Knowledge/target", "uniquequery")
    ledger.sync()
    ledger._vector_corpus("knowledge")
    encoded.clear()

    write("Knowledge/target", "uniquequery", **metadata)
    ledger.sync()

    assert encoded == []
    assert ledger.fts("uniquequery", 1) == []
    assert ledger._vector_corpus(None)[0] == ("Knowledge/seed",)
    assert _context_refs() == ["Knowledge/seed"]
    # Retrieval exclusion does not erase the Article or its authored graph edge.
    assert _edges(ledger) == {("Knowledge/seed", "Knowledge/target")}

    write("Knowledge/target", "uniquequery")
    ledger.sync()
    assert encoded == ["target\nuniquequery\n"]
    assert ledger.fts("uniquequery", 1)[0][0] == "Knowledge/target"
    assert _context_refs() == ["Knowledge/seed", "Knowledge/target"]


@pytest.mark.parametrize("operation", ["delete", "rename", "archive", "stage"])
def test_removed_target_leaves_no_stale_index_row_or_resolved_edge(
    graph_index, operation,
):
    ledger, write, encoded = graph_index
    write("Knowledge/seed", links=["[[Knowledge/target]]"])
    target = write("Knowledge/target", "uniquequery")
    ledger.sync()
    ledger._vector_corpus("knowledge")
    encoded.clear()

    if operation == "delete":
        target.unlink()
    else:
        ref = {
            "rename": "Knowledge/renamed",
            "archive": "_archived/target",
            "stage": "_staging/target",
        }[operation]
        destination = target.parent.parent / f"{ref}.md"
        destination.parent.mkdir(parents=True, exist_ok=True)
        target.rename(destination)
        if operation == "rename":
            # A raw external rename does not rewrite authored inbound links.
            write(ref, "uniquequery", title="Renamed")
    assert ledger.sync()["removed"] == 1

    for table in ("notes", "notes_fts", "embeddings"):
        assert ledger.db.execute(
            f"SELECT 1 FROM {table} WHERE ref='Knowledge/target'"
        ).fetchone() is None
    assert "Knowledge/target" not in ledger._vector_corpus("knowledge")[0]
    assert _edges(ledger) == set()
    assert _context_refs() == ["Knowledge/seed"]
    if operation != "rename":
        assert encoded == []
        assert ledger.fts("uniquequery", 1) == []


@pytest.mark.parametrize("operation", ["delete", "rename"])
def test_removed_exact_path_does_not_retarget_an_unrelated_basename(
    graph_index, operation,
):
    ledger, write, _encoded = graph_index
    write("Knowledge/seed", links=["[[Knowledge/Original/target]]"])
    target = write("Knowledge/Original/target", title="Original target")
    write("Knowledge/Unrelated/target", title="Unrelated target")
    ledger.sync()
    assert _edges(ledger) == {("Knowledge/seed", "Knowledge/Original/target")}

    if operation == "delete":
        target.unlink()
    else:
        target.rename(target.with_stem("renamed"))
    ledger.sync()

    assert _edges(ledger) == set()
    assert _context_refs() == ["Knowledge/seed"]


def test_resolver_preserves_pathless_names_and_explicit_aliases(graph_index):
    _ledger, write, _encoded = graph_index
    write("Knowledge/Original/target", title="Original target")
    resolver = Resolver(iter_notes())

    for raw in (
        "target", "target.md", "Original target",
        "[[Knowledge/Original/target.md#Details|Alias]]",
        "[[knowledge/original/TARGET]]",
    ):
        assert resolver.resolve(raw).ref == "Knowledge/Original/target"
    assert resolver.resolve("[[Knowledge/Missing/target#Details|Alias]]") is None


def test_managed_rename_rewrites_exact_links_before_index_sync(graph_index):
    ledger, write, _encoded = graph_index
    write(
        "Knowledge/seed", "See [[Knowledge/target.md#Details|the target]].",
        links=["[[Knowledge/target]]"],
    )
    write("Knowledge/target")
    ledger.sync()

    move_vault_item("Knowledge/target.md", "Knowledge", new_name="Renamed")
    ledger.sync()

    seed = load_note("Knowledge/seed.md")
    assert seed.body == "See [the target](/Knowledge/renamed.md#Details).\n"
    assert seed.meta["links"] == ["[[Knowledge/renamed]]"]
    assert _edges(ledger) == {("Knowledge/seed", "Knowledge/renamed")}
    assert _context_refs() == ["Knowledge/seed", "Knowledge/renamed"]
