"""Native Feed lineage remains counted after owner moves or unexpected copies."""
from contextlib import contextmanager

import pytest

from obsidience.harness.capabilities.vault import propose
from obsidience.harness.config import CONFIG
from obsidience.harness.knowledge import curation, review, vault
from obsidience.tests.test_feed_distill_publication import pipeline  # noqa: F401
from obsidience.tests.test_feed_retention import retained, active, snapshot  # noqa: F401


def relocate(article, target):
    old = CONFIG.vault_dir / article["target"]
    moved = CONFIG.vault_dir / target
    moved.parent.mkdir(parents=True, exist_ok=True)
    old.rename(moved)
    return moved


def reconcile(retained):
    @contextmanager
    def guard():
        yield retained.current

    return curation.reconcile_feed_retention(retained.receipt["feed_id"], definition_guard=guard)


@pytest.mark.parametrize("target", ["Topics/Reports/renamed.md", "Topics/Kept/Kept.md"])
def test_moved_articles_and_converted_containers_still_count_read_only(retained, target):
    article, raw, inbox = retained.add(1)
    relocate(article, target)
    if target.endswith("Kept.md"):
        vault.write_note("Topics/Kept/child.md", {"kind": "knowledge", "title": "Child"}, "Owner child.\n")
    before = snapshot()
    evidence = {row["id"]: bytes(retained.index.source(row["id"])["material"]) for row in (raw, inbox)}
    members = active(retained.receipt["feed_id"])
    assert len(members) == 1 and members[0]["ref"] == target.removesuffix(".md")
    assert members[0]["retention_protection"] == "owner-reorganized placement"
    state = curation.feed_retention_state(retained.receipt["feed_id"], 2)
    assert state["active_article_count"] == 1 and state["retention_status"] == "within_limit"
    assert snapshot() == before
    assert evidence == {source_id: bytes(retained.index.source(source_id)["material"]) for source_id in evidence}


def test_oldest_moved_article_blocks_incoming_and_explicit_reduction(retained):
    article, _, _ = retained.add(1)
    retained.add(2)
    relocate(article, "Topics/Reports/owner-kept.md")
    before = snapshot()
    result = propose.execute(retained.args, retained.ingest)
    assert "Proposal rejected" in result and "owner-reorganized placement" in result
    assert snapshot() == before and not review.list_proposals()
    retained.current["max_active_articles"] = 1
    result = reconcile(retained)
    assert result["active_article_count"] == 2 and result["retention_status"] == "blocked"
    assert "owner-reorganized placement" in result["retention_detail"]
    assert snapshot() == before and not review.list_proposals()


def test_unexpected_copy_protects_both_copies_before_choosing_a_victim(retained):
    article, _, _ = retained.add(1)
    original = CONFIG.vault_dir / article["target"]
    duplicate = original.with_name("z-owner-copy.md")
    duplicate.write_bytes(original.read_bytes())
    members = active(retained.receipt["feed_id"])
    assert len(members) == 2 and members[0]["ref"] == article["target"].removesuffix(".md")
    assert all(row["retention_protection"].startswith("duplicate item") for row in members)
    before = snapshot()
    result = propose.execute(retained.args, retained.ingest)
    assert "Proposal rejected" in result and "duplicate item" in result
    assert snapshot() == before and original.is_file() and duplicate.is_file()


def test_newer_protected_article_does_not_prevent_eligible_oldest_retirement(retained):
    old, _, _ = retained.add(1)
    newer, _, _ = retained.add(2)
    moved = relocate(newer, "Topics/Reports/owner-kept.md")
    moved_bytes = moved.read_bytes()
    assert "Article published" in propose.execute(retained.args, retained.ingest)
    assert vault.load_note(old["target"]) is None
    assert len(active(retained.receipt["feed_id"])) == 2
    assert moved.read_bytes() == moved_bytes


def test_manual_review_cannot_retire_an_article_moved_after_staging(retained):
    old, _, _ = retained.add(1)
    retained.add(2)
    node = vault.load_note(retained.current["destination_ref"] + ".md")
    vault.mutate_note_metadata(node, lambda meta: meta.update(auto_curate=False))
    assert "staged for owner review" in propose.execute(retained.args, retained.ingest)
    card = review.list_proposals()[0]
    moved = relocate(old, "Topics/Reports/owner-kept.md")
    before = snapshot()
    with pytest.raises(ValueError, match="membership|accepted bytes"):
        review.approve(card["file"])
    assert snapshot() == before and moved.is_file()


def test_same_item_versions_at_attested_prior_destinations_remain_eligible(retained):
    old, _, _ = retained.add(1, destination="Topics/Previous/Previous", native_id="shared-item")
    retained.add(2, native_id="shared-item")
    members = active(retained.receipt["feed_id"])
    assert len(members) == 2 and all(not row.get("retention_protection") for row in members)
    assert "Article published" in propose.execute(retained.args, retained.ingest)
    assert vault.load_note(old["target"]) is None
    assert len(active(retained.receipt["feed_id"])) == 2
