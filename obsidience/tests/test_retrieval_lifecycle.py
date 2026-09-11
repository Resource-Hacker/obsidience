"""Current-context eligibility expires per activation, not per index refresh."""
from datetime import datetime, timezone

import pytest

from obsidience.harness.capabilities.vault import read
from obsidience.harness.knowledge import format as article_format, retrieval, vault
from obsidience.tests.test_vault_read_pages import page_parts
from obsidience.tests.test_source_retrieval_scope import _note


NOW = datetime(2026, 9, 6, 8, tzinfo=timezone.utc)


def test_current_context_excludes_deprecated_and_expired_direct_and_neighbor_hits(monkeypatch):
    notes = [
        _note("Knowledge/direct-old", body="Retired direct fact.", meta={"article_status": "deprecated"}),
        _note("Knowledge/direct-stale", body="Expired direct fact.", meta={"stale_after": "2000-01-01T00:00:00Z"}),
        _note("Knowledge/seed", body="Current direct fact.", links=["Knowledge/neighbor-old", "Knowledge/neighbor-stale", "Knowledge/neighbor-current"]),
        _note("Knowledge/neighbor-old", body="Retired neighbor fact.", meta={"article_status": "deprecated"}),
        _note("Knowledge/neighbor-stale", body="Expired neighbor fact.", meta={"stale_after": "2000-01-01T08:00:00+08:00"}),
        _note("Knowledge/neighbor-current", body="Current neighboring fact.", meta={"stale_after": "2999-01-01T00:00:00Z"}),
    ]
    monkeypatch.setattr(retrieval, "iter_notes", lambda: notes)
    monkeypatch.setattr(retrieval, "_lanes_for", lambda *_args, **_kwargs: [(1, [(note.ref, 1) for note in notes[:3]])])
    brief, refs = retrieval.fast_context_with_refs("fact", set(), limit=5,
                                                preferred={"Knowledge/direct-old", "Knowledge/direct-stale"})
    assert refs == ["Knowledge/seed", "Knowledge/neighbor-current"]
    assert "Retired" not in brief and "Expired" not in brief


@pytest.mark.parametrize("shared_snapshot", [False, True])
def test_expiration_refreshes_without_index_or_article_mutation(monkeypatch, shared_snapshot):
    class Clock:
        current = NOW

        @classmethod
        def now(cls, _tz):
            return cls.current

        fromisoformat = datetime.fromisoformat

    note = _note("Knowledge/timed", meta={"stale_after": "2026-09-06T09:00:00+00:00"})
    before = dict(note.meta)
    monkeypatch.setattr(retrieval, "datetime", Clock)
    monkeypatch.setattr(retrieval, "iter_notes", lambda: [note])
    monkeypatch.setattr(retrieval, "_lanes_for", lambda *_args, **_kwargs: [(1, [(note.ref, 1)])])
    monkeypatch.setattr(retrieval.INDEX, "sync", lambda: (_ for _ in ()).throw(AssertionError("unexpected index rebuild")))
    kwargs = {"accepted_resolver": vault.Resolver([note])} if shared_snapshot else {}
    if shared_snapshot:
        monkeypatch.setattr(retrieval, "iter_notes", lambda: pytest.fail("activation snapshot must not be rescanned"))
    assert retrieval.fast_context_with_refs("timed", set(), **kwargs)[1] == [note.ref]
    Clock.current = datetime(2026, 9, 6, 9, tzinfo=timezone.utc)
    assert retrieval.fast_context_with_refs("timed", set(), **kwargs) == ("", [])
    assert note.meta == before


def test_shared_activation_snapshot_excludes_system_articles_and_resolves_current_neighbor(monkeypatch):
    seed = _note("Knowledge/seed", body="Current seed.", links=["Neighbor"])
    hidden = [
        _note("_archived/neighbor", body="Archived history."),
        _note("_staging/neighbor", body="Pending proposal."),
        _note("raw/neighbor", body="Raw source."),
        _note("Knowledge/.private/neighbor", body="Hidden evidence."),
    ]
    neighbor = _note("Knowledge/neighbor", body="Accepted neighbor.")
    for note in [*hidden, neighbor]:
        note.title = "Neighbor"
    snapshot = vault.Resolver([*hidden, seed, neighbor])
    monkeypatch.setattr(retrieval, "iter_notes", lambda: pytest.fail("activation snapshot must not be rescanned"))
    monkeypatch.setattr(retrieval, "_lanes_for", lambda *_args, **_kwargs: [(1, [(note.ref, 1) for note in [*hidden, seed]])])

    brief, refs = retrieval.fast_context_with_refs("evidence", set(), accepted_resolver=snapshot)

    assert refs == [seed.ref, neighbor.ref]
    assert "Current seed." in brief and "Accepted neighbor." in brief
    assert all(note.body not in brief for note in hidden)


def test_active_resolver_is_fresh_and_default_retains_historical_articles(monkeypatch, tmp_path):
    monkeypatch.setattr(vault.CONFIG, "vault_dir", tmp_path)
    vault.write_note("Knowledge/current.md", {"kind": "knowledge"}, "Original current body.")
    vault.write_note("_archived/history.md", {"kind": "knowledge"}, "Archived body.")
    vault.write_note("_staging/proposal.md", {"kind": "knowledge"}, "Proposed body.")
    before = vault.resolver(include_system=False)
    assert set(before.by_ref) == {"knowledge/current"}
    assert vault.resolver().resolve("_archived/history").body == "Archived body.\n"
    assert vault.resolver().resolve("_staging/proposal").body == "Proposed body.\n"

    vault.write_note("Knowledge/current.md", {"kind": "knowledge"}, "Corrected current body.")
    after = vault.resolver(include_system=False)
    assert before.resolve("Knowledge/current").body == "Original current body.\n"
    assert after.resolve("Knowledge/current").body == "Corrected current body.\n"


def test_native_lifecycle_is_separate_from_local_and_task_execution_status():
    assert retrieval._eligible_knowledge(_note("Knowledge/ordinary", meta={"status": "deprecated"}), NOW)
    assert not retrieval._eligible_knowledge(_note("Knowledge/retired", meta={"article_status": "deprecated", "status": "approved"}), NOW)
    task = _note("Tasks/work", kind="task", meta={"article_status": "stable", "status": "running"})
    before = dict(task.meta)
    assert not retrieval._eligible_knowledge(task, NOW)
    assert task.meta == before


def test_explicit_search_and_read_preserve_stale_deprecated_and_archived_content(monkeypatch, tmp_path):
    monkeypatch.setattr(vault.CONFIG, "vault_dir", tmp_path)
    rows = [
        ("Knowledge/deprecated", {"article_status": "deprecated"}, "Retained deprecated history."),
        ("Knowledge/stale", {"stale_after": "2000-01-01T00:00:00Z"}, "Retained expired evidence."),
        ("_archived/Knowledge/history", {"article_status": "deprecated"}, "Retained archive body."),
    ]
    for ref, meta, body in rows:
        vault.write_note(ref + ".md", {"kind": "knowledge", "title": ref, **meta}, body)
    monkeypatch.setattr(retrieval, "_lanes_for", lambda *_args, **_kwargs: [(1, [(ref, 1) for ref, _meta, _body in rows[:2]])])
    assert [hit["ref"] for hit in retrieval.search("retained")] == [row[0] for row in rows[:2]]
    for ref, _meta, body in rows:
        output = read.execute({"ref": ref}, {})
        assert ("Note not found" in output) if ref.startswith("_archived/") else (body in output)
        if not ref.startswith("_archived/"):
            assert ('"freshness": "stale"' if ref == "Knowledge/stale" else '"freshness": "deprecated"') in output
        assert body in vault.load_note(ref + ".md").body


def test_explicit_read_lifecycle_uses_native_alias_and_never_exposes_arbitrary_metadata(monkeypatch, tmp_path):
    monkeypatch.setattr(vault.CONFIG, "vault_dir", tmp_path)
    vault.write_note("Knowledge/old.md", {"kind": "knowledge", "article_status": "deprecated",
                                          "status": "approved", "private_field": "PRIVATE-MARKER",
                                          "verified": {"by": "human:PRIVATE-MARKER"}}, "Retained content.")
    output = read.execute({"ref": "Knowledge/old"}, {})
    assert '"status": "deprecated"' in output
    assert "approved" not in output and "PRIVATE-MARKER" not in output
    assert "Retained content." in output


def test_expiry_changes_explicit_read_revision_and_rejects_stale_pagination(monkeypatch, tmp_path):
    class Clock:
        current = NOW

        @classmethod
        def now(cls, _tz):
            return cls.current

        fromisoformat = datetime.fromisoformat

    monkeypatch.setattr(vault.CONFIG, "vault_dir", tmp_path)
    monkeypatch.setattr(article_format, "datetime", Clock)
    vault.write_note("Knowledge/timed.md", {"kind": "knowledge", "stale_after": "2026-09-06T09:00:00Z"}, "Evidence " * 2000)
    original = (tmp_path / "Knowledge/timed.md").read_bytes()
    identity, bounds, body = page_parts(read.execute({"ref": "Knowledge/timed"}, {}))
    assert '"freshness": "current"' in body
    Clock.current = datetime(2026, 9, 6, 9, tzinfo=timezone.utc)
    rejected = read.execute({"ref": identity["ref"], "offset": bounds[1], "expected_sha256": identity["view_sha256"]}, {})
    assert rejected.startswith("Article view changed:") and "lifecycle" in rejected
    fresh, _bounds, body = page_parts(read.execute({"ref": "Knowledge/timed"}, {}))
    assert fresh["view_sha256"] != identity["view_sha256"]
    assert '"freshness": "stale"' in body
    assert (tmp_path / "Knowledge/timed.md").read_bytes() == original

pytestmark = pytest.mark.usefixtures("authorized_reader_scope")
