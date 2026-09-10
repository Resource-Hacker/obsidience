"""Deferred Feed publication never overwrites newer accepted item evidence."""
import pytest

from obsidience.harness.config import CONFIG
from obsidience.harness.knowledge import curation, review, source, vault
from obsidience.tests.test_feed_distill_publication import pipeline  # noqa: F401
from obsidience.tests.test_feed_retention import retained, active, snapshot, _large_pending  # noqa: F401


def publication(retained):
    return curation.prepare_feed_article(retained.args, retained.ingest)["envelope"]


def test_deferred_plan_refuses_newer_accepted_same_item_version(retained):
    envelope = publication(retained)
    newer, _, _ = retained.add(2100, native_id=retained.item["native_id"])
    before = snapshot()
    with pytest.raises(source.SourceError, match="newer Feed item version"):
        curation._retention_plan(retained.receipt["feed_id"], retained.current,
                                active(retained.receipt["feed_id"]), envelope)
    assert snapshot() == before and vault.load_note(newer["target"]).body == newer["body"]


def test_same_source_already_published_is_noop_and_preserves_owner_corrections(retained):
    prepared = curation.prepare_feed_article(retained.args, retained.ingest)
    article = prepared["article"]
    body = article["body"] + "\nOwner correction retained.\n"
    vault.write_note(article["target"], {**article["metadata"], "owner_field": "keep"}, body)
    before = snapshot()
    plan = curation._retention_plan(retained.receipt["feed_id"], retained.current,
                                   active(retained.receipt["feed_id"]), prepared["envelope"])
    assert plan["changes"] == []
    assert snapshot() == before and vault.load_note(article["target"]).body == body


def test_deferred_plan_preserves_independently_maintained_target(retained):
    envelope = publication(retained)
    vault.write_note(retained.args["target"], {"kind": "knowledge", "title": "Owner"}, "Owner's Article.\n")
    before = snapshot()
    with pytest.raises(source.SourceError, match="independently maintained"):
        curation._retention_plan(retained.receipt["feed_id"], retained.current, [], envelope)
    assert snapshot() == before


def test_committed_retention_journal_cannot_replay_over_a_newer_publication(retained, monkeypatch):
    first = _large_pending(retained)
    with monkeypatch.context() as crash:
        crash.setattr(review, "_resume_feed_retention", lambda *_args, **_kwargs:
                      (_ for _ in ()).throw(SystemExit("crash after committed archives")))
        with pytest.raises(SystemExit):
            review.approve(first)
    newer, _, _ = retained.add(2100, native_id=retained.item["native_id"])
    accepted_path = CONFIG.vault_dir / newer["target"]
    accepted_bytes = accepted_path.read_bytes()
    result = review.recover_groups()
    assert any("newer Feed item version" in text for text in result["blocked_continuations"])
    assert accepted_path.read_bytes() == accepted_bytes
    assert list(CONFIG.staging_dir.glob(".review-transaction-*.json"))
    assert review.reconcile_origin_review_task("Tasks/ingest") == "review"
    assert not review.list_proposals()
