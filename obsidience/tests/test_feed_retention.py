"""Feed retention uses exact Source ownership and the existing atomic Review."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest

from obsidience.harness.capabilities.vault import propose
from obsidience.harness.config import CONFIG
from obsidience.harness.knowledge import curation, review, source, vault
from obsidience.tests.test_feed_distill_publication import pipeline  # noqa: F401


@pytest.fixture
def retained(pipeline, monkeypatch):
    pipeline.current.update(max_active_articles=2, enabled=True, connection_enabled=True)
    from obsidience.harness.connections import runtime as connections

    @contextmanager
    def guard(feed_id, expected_ref=None):
        if (pipeline.current.get("deleted") or feed_id != pipeline.receipt["feed_id"]
                or expected_ref is not None and expected_ref != pipeline.current["destination_ref"]):
            raise connections.ConnectionsError("Feed destination mapping changed or was removed")
        yield pipeline.current

    monkeypatch.setattr(connections, "feed_destination_guard", guard)

    def add(number, *, feed_id=None, destination=None, native_id=None, publish=True):
        feed_id = feed_id or pipeline.receipt["feed_id"]
        destination = destination or pipeline.current["destination_ref"]
        if not vault.load_note(destination + ".md"):
            vault.write_note(destination + ".md", {"kind": "knowledge", "title": "Other", "auto_curate": True}, "Existing Knowledge node.\n")
        item = {**pipeline.item, "native_id": native_id or f"retained-{number}", "title": f"Story {number}"}
        key = hashlib.sha256(item["native_id"].encode()).hexdigest()
        captured_at = (datetime(2026, 9, 8, tzinfo=timezone.utc) + timedelta(minutes=number)).isoformat()
        raw = source.ingest_source(source_type="document", source_ref=f"feed://{feed_id}/{key}",
            media_type="application/json", content=json.dumps(item), captured_at=captured_at,
            feed_receipt={"feed_id": feed_id, "item_key": key, "destination_ref": destination})
        inbox = source.handoff_source(title=f"Story {number}", content=f"Complete preserved summary {number}.\n\nEvidence: {raw['citation']}",
            captured_at=captured_at, research_task=source.DISTILL_TASK, research_run_id="distill-run", feed_source_id=raw["id"])
        binding = source.feed_source_binding(raw["id"])
        article = curation._feed_article(inbox, binding)
        if publish:
            vault.write_note(article["target"], {**article["metadata"], "local_owner_field": "preserve", "stale_after": "2027-01-01T00:00:00Z"}, article["body"])
        return article, raw, inbox

    pipeline.add = add
    return pipeline


def active(feed_id):
    return curation._feed_members().get(feed_id, [])


def snapshot():
    return {path.relative_to(CONFIG.vault_dir).as_posix(): path.read_bytes() for path in CONFIG.vault_dir.rglob("*.md")}


def test_incoming_and_oldest_archive_commit_together_without_touching_shared_node(retained):
    old, raw, inbox = retained.add(1)
    retained.add(2)
    other, _, _ = retained.add(0, feed_id="b" * 32)
    ordinary = "Topics/Reports/owner-note.md"
    vault.write_note(ordinary, {"kind": "knowledge", "title": "Owner"}, "Unrelated accepted Knowledge.\n")
    before_other = (CONFIG.vault_dir / other["target"]).read_bytes()
    before_source = bytes(retained.index.source(raw["id"])["material"])
    assert "Article published" in propose.execute(retained.args, retained.ingest)
    assert len(active(retained.receipt["feed_id"])) == 2
    assert vault.load_note(old["target"]) is None
    archived = vault.load_note("_archived/" + old["target"])
    assert archived.body == old["body"]
    assert archived.meta["local_owner_field"] == "preserve"
    assert archived.meta["stale_after"] == "2027-01-01T00:00:00Z"
    assert archived.meta["article_status"] == "deprecated" and archived.meta["archived_at"]
    assert {item["resource"] for item in archived.meta["sources"]} == {raw["citation"], inbox["citation"]}
    assert (CONFIG.vault_dir / other["target"]).read_bytes() == before_other
    assert vault.load_note(ordinary) is not None
    assert bytes(retained.index.source(raw["id"])["material"]) == before_source
    assert retained.ingest["feed_publication_result"]["archived_count"] == 1


def test_updated_native_item_counts_once_and_same_version_preserves_owner_edits(retained):
    article, _, _ = retained.add(1, native_id=retained.item["native_id"])
    retained.add(2)
    assert "Article published" in propose.execute(retained.args, retained.ingest)
    assert len(active(retained.receipt["feed_id"])) == 2
    assert not (CONFIG.vault_dir / "_archived").exists()
    accepted = vault.load_note(article["target"])
    vault.write_note(accepted.path, accepted.meta, accepted.body + "\nOwner correction.\n")
    before = snapshot()
    assert "already published" in propose.execute(retained.args, retained.ingest)
    assert snapshot() == before


@pytest.mark.parametrize("field", ["max_active_articles", "destination_ref", "membership", "base"])
def test_delayed_group_review_rechecks_policy_full_membership_and_exact_bases(retained, field):
    old, _, _ = retained.add(1)
    retained.add(2)
    node = vault.load_note(retained.current["destination_ref"] + ".md")
    vault.mutate_note_metadata(node, lambda meta: meta.update(auto_curate=False))
    assert "staged for owner review" in propose.execute(retained.args, retained.ingest)
    pending = next(CONFIG.staging_dir.glob("*.md"))
    if field == "max_active_articles": retained.current[field] = 3
    elif field == "destination_ref": retained.current[field] = "Topics/Other/Other"
    elif field == "membership": retained.add(3)
    else:
        path = CONFIG.vault_dir / old["target"]
        path.write_text(path.read_text() + "Owner changed the accepted base.\n")
    before = snapshot()
    assert not review.list_proposals()[0]["approvable"]
    with pytest.raises(ValueError):
        review.approve(pending.name)
    assert snapshot() == before


def test_initially_below_cap_pending_publication_cannot_bypass_later_membership(retained):
    node = vault.load_note(retained.current["destination_ref"] + ".md")
    vault.mutate_note_metadata(node, lambda meta: meta.update(auto_curate=False))
    propose.execute(retained.args, retained.ingest)
    pending = next(CONFIG.staging_dir.glob("*.md"))
    retained.add(1)
    retained.add(2)
    with pytest.raises(ValueError, match="membership"):
        review.approve(pending.name)
    assert vault.load_note(retained.args["target"]) is None
    assert len(active(retained.receipt["feed_id"])) == 2


def test_inbound_reference_blocks_whole_rotation_and_is_visible_afterward(retained):
    old, _, _ = retained.add(1)
    retained.add(2)
    vault.write_note("Topics/Related.md", {"kind": "knowledge", "title": "Related"}, f"Still needs [[{old['target'][:-3]}]].\n")
    before = snapshot()
    assert "Proposal rejected" in propose.execute(retained.args, retained.ingest)
    assert snapshot() == before
    state = curation.feed_retention_state(retained.receipt["feed_id"], 2)
    assert state["retention_status"] == "within_limit"
    state = curation.feed_retention_state(retained.receipt["feed_id"], 1)
    assert state["retention_status"] == "blocked" and "Topics/Related" in state["retention_detail"]


def test_explicit_victim_policy_stages_one_review_and_preserves_all_old_articles(retained):
    old, _, _ = retained.add(1)
    retained.add(2)
    victim = vault.load_note(old["target"])
    vault.mutate_note_metadata(victim, lambda meta: meta.update(auto_curate=False))
    assert "staged for owner review" in propose.execute(retained.args, retained.ingest)
    assert len(active(retained.receipt["feed_id"])) == 2
    cards = review.list_proposals()
    assert len(cards) == 1 and cards[0]["member_count"] == 2
    state = curation.feed_retention_state(retained.receipt["feed_id"], 2)
    assert state["retention_status"] == "review_required"
    review.approve(cards[0]["file"])
    assert len(active(retained.receipt["feed_id"])) == 2 and vault.load_note(old["target"]) is None


def test_owner_save_reconciles_quiet_paused_feed_across_prior_destinations(retained):
    old, _, _ = retained.add(1, destination="Topics/Previous/Previous")
    retained.add(2)
    retained.add(3)
    retained.current.update(enabled=False, connection_enabled=False, max_active_articles=1)
    calls = []

    @contextmanager
    def guard():
        calls.append(True)
        yield retained.current

    result = curation.reconcile_feed_retention(retained.receipt["feed_id"], definition_guard=guard)
    assert result["archived_count"] == 2 and result["active_article_count"] == 1
    assert result["retention_status"] == "within_limit" and calls
    assert vault.load_note(old["target"]) is None
    assert not review.list_proposals()


def test_large_reduction_uses_bounded_archive_only_groups_and_is_idempotent(retained, monkeypatch):
    for number in range(28): retained.add(number)
    retained.current["max_active_articles"] = 1
    original = review.stage_group
    sizes = []

    def stage(specs, *args, **kwargs):
        sizes.append(len(specs))
        assert all(spec["action"] == "archive" for spec in specs)
        return original(specs, *args, **kwargs)

    monkeypatch.setattr(review, "stage_group", stage)
    result = curation.reconcile_feed_retention(retained.receipt["feed_id"])
    assert sizes == [24, 3] and result["archived_count"] == 27
    assert result["active_article_count"] == 1
    before = snapshot()
    assert curation.reconcile_feed_retention(retained.receipt["feed_id"])["archived_count"] == 0
    assert snapshot() == before


def test_large_reduction_stops_after_one_pending_group(retained):
    for number in range(28): retained.add(number)
    retained.current["max_active_articles"] = 1
    node = vault.load_note(retained.current["destination_ref"] + ".md")
    vault.mutate_note_metadata(node, lambda meta: meta.update(auto_curate=False))
    result = curation.reconcile_feed_retention(retained.receipt["feed_id"])
    assert result["active_article_count"] == 28 and result["retention_status"] == "review_required"
    cards = review.list_proposals()
    assert len(cards) == 1 and cards[0]["member_count"] == 24
    again = curation.reconcile_feed_retention(retained.receipt["feed_id"])
    assert again["pending_review"] and len(review.list_proposals()) == 1


def test_state_projection_is_read_only_batched_and_handles_unreadable_pending(retained, monkeypatch):
    retained.add(1)
    before = snapshot()
    scans = []
    original = curation.iter_notes
    monkeypatch.setattr(curation, "iter_notes", lambda: scans.append(True) or original())
    states = curation.feed_retention_states({retained.receipt["feed_id"]: 2, "b" * 32: 1}, index=retained.index)
    assert len(scans) == 1 and states[retained.receipt["feed_id"]]["active_article_count"] == 1
    assert states["b" * 32]["active_article_count"] == 0 and snapshot() == before
    CONFIG.staging_dir.mkdir(exist_ok=True)
    (CONFIG.staging_dir / "broken.md").write_text("---\nbroken: [\n---\n")
    assert curation.feed_retention_states({}, index=retained.index) == {}
    state = curation.feed_retention_state(retained.receipt["feed_id"], 2, index=retained.index)
    assert state["active_article_count"] == 1 and state["retention_status"] == "unavailable"


def test_failure_during_atomic_rotation_restores_all_files_and_decisions(retained, monkeypatch):
    retained.add(1)
    retained.add(2)
    original = review._atomic_write

    def fail(path, material):
        if path == CONFIG.vault_dir / retained.args["target"]:
            raise OSError("retention fixture write failure")
        return original(path, material)

    monkeypatch.setattr(review, "_atomic_write", fail)
    assert "staged for owner review" in propose.execute(retained.args, retained.ingest)
    assert len(active(retained.receipt["feed_id"])) == 2
    assert vault.load_note(retained.args["target"]) is None
    assert not list((CONFIG.vault_dir / "_archived").rglob("*.md"))
    assert retained.index.review_outcome("ingest-run")["approved_count"] == 0


def _large_pending(retained, *, incoming=True):
    for number in range(28): retained.add(number)
    retained.current["max_active_articles"] = 1
    node = vault.load_note(retained.current["destination_ref"] + ".md")
    vault.mutate_note_metadata(node, lambda meta: meta.update(auto_curate=False))
    if incoming:
        propose.execute(retained.args, retained.ingest)
        task = vault.load_note("Tasks/ingest.md")
        vault.mutate_note_metadata(task, lambda meta: meta.update(status="review"))
    else:
        curation.reconcile_feed_retention(retained.receipt["feed_id"])
    return review.list_proposals()[0]["file"]


@pytest.mark.parametrize("incoming", [True, False])
def test_manual_large_batch_stages_successor_before_task_settlement(retained, incoming):
    first = _large_pending(retained, incoming=incoming)
    review.approve(first)
    assert len(active(retained.receipt["feed_id"])) == 4
    assert vault.load_note(retained.args["target"]) is None
    if incoming:
        assert vault.load_note("Tasks/ingest.md").meta["status"] == "review"
    second = review.list_proposals()
    assert len(second) == 1 and second[0]["member_count"] == (5 if incoming else 3)
    review.approve(second[0]["file"])
    assert len(active(retained.receipt["feed_id"])) == 1 and not review.list_proposals()
    assert bool(vault.load_note(retained.args["target"])) == incoming
    if incoming:
        assert vault.load_note("Tasks/ingest.md").meta["status"] == "completed"


@pytest.mark.parametrize("after_staging", [False, True])
def test_restart_recovers_exact_successor_from_existing_review_journal(retained, monkeypatch, after_staging):
    first = _large_pending(retained)
    with monkeypatch.context() as crash:
        if after_staging:
            original = Path.unlink
            def cut(path, *args, **kwargs):
                if path.name.startswith(".review-transaction-"):
                    raise SystemExit("crash after successor staging")
                return original(path, *args, **kwargs)
            crash.setattr(Path, "unlink", cut)
        else:
            crash.setattr(review, "_resume_feed_retention", lambda *_args, **_kwargs: (_ for _ in ()).throw(SystemExit("crash after commit")))
        with pytest.raises(SystemExit):
            review.approve(first)
    assert len(active(retained.receipt["feed_id"])) == 4
    assert vault.load_note(retained.args["target"]) is None
    assert list(CONFIG.staging_dir.glob(".review-transaction-*.json"))
    assert review.reconcile_origin_review_task("Tasks/ingest") == "review"
    review.recover_groups()
    cards = review.list_proposals()
    assert len(cards) == 1 and cards[0]["member_count"] == 5
    assert vault.load_note("Tasks/ingest.md").meta["status"] == "review"
    before = snapshot()
    review.recover_groups()
    assert snapshot() == before
    review.approve(cards[0]["file"])
    assert len(active(retained.receipt["feed_id"])) == 1
    assert vault.load_note(retained.args["target"]) is not None


def test_rejecting_large_successor_stops_the_chain(retained):
    first = _large_pending(retained)
    review.approve(first)
    second = review.list_proposals()[0]["file"]
    review.reject(second, "Owner retains the remaining Articles")
    before = snapshot()
    review.recover_groups()
    assert snapshot() == before and not review.list_proposals()
    assert len(active(retained.receipt["feed_id"])) == 4
    assert vault.load_note(retained.args["target"]) is None


def test_automatic_large_rotation_publishes_incoming_only_after_capacity_exists(retained, monkeypatch):
    for number in range(28): retained.add(number)
    retained.current["max_active_articles"] = 1
    original = retained.index.record_review_decisions
    counts = []
    def record(rows, **kwargs):
        count = len(active(retained.receipt["feed_id"]))
        counts.append(count)
        if vault.load_note(retained.args["target"]):
            assert count == 1
        return original(rows, **kwargs)
    monkeypatch.setattr(retained.index, "record_review_decisions", record)
    assert "Article published" in propose.execute(retained.args, retained.ingest)
    assert counts == [4, 1]
    assert retained.ingest["feed_publication_result"]["archived_count"] == 28


def test_legacy_single_feed_review_cannot_bypass_new_cap(retained):
    node = vault.load_note(retained.current["destination_ref"] + ".md")
    vault.mutate_note_metadata(node, lambda meta: meta.update(auto_curate=False))
    plan = curation.prepare_feed_article(retained.args, retained.ingest)
    pending = propose.stage_proposal(plan["article"], {**retained.ingest, "_feed_compiling": True,
        "_feed_publication": plan["envelope"], "staged_proposals": []})
    retained.add(1)
    retained.add(2)
    with pytest.raises(ValueError, match="active Article limit"):
        review.approve(Path(pending["staged"]).name)
    assert vault.load_note(retained.args["target"]) is None


def test_retained_continuation_is_visible_and_owner_cap_save_resumes_it(retained, monkeypatch):
    first = _large_pending(retained)
    with monkeypatch.context() as fault:
        fault.setattr(curation, "stage_feed_retention", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("next-stage fixture blocker")))
        result = review.approve(first)
    assert result["committed"] and "next-stage fixture blocker" in result["retention_blocked"]
    # The new cap already permits all existing leaves, but the incoming work
    # is still held by its original journal and must remain visible.
    retained.current["max_active_articles"] = 10
    state = curation.feed_retention_state(retained.receipt["feed_id"], 10)
    assert state["active_article_count"] == 4 and state["retention_status"] == "blocked"
    assert "continuation" in state["retention_detail"]
    result = curation.reconcile_feed_retention(retained.receipt["feed_id"])
    assert result["retention_status"] == "review_required"
    cards = review.list_proposals()
    assert len(cards) == 1 and cards[0]["member_count"] == 1 and cards[0]["action"] == "create"
    assert not list(CONFIG.staging_dir.glob(".review-transaction-*.json"))
    assert vault.load_note("Tasks/ingest.md").meta["status"] == "review"
    review.approve(cards[0]["file"])
    assert len(active(retained.receipt["feed_id"])) == 5
    assert vault.load_note(retained.args["target"]) is not None


def test_retained_inbox_cannot_be_retargeted_by_destination_edit(retained, monkeypatch):
    first = _large_pending(retained)
    with monkeypatch.context() as fault:
        fault.setattr(curation, "stage_feed_retention", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("next-stage fixture blocker")))
        review.approve(first)
    retained.current["destination_ref"] = "Topics/Other/Other"
    vault.write_note("Topics/Other/Other.md", {"kind": "knowledge", "title": "Other", "auto_curate": True}, "Owner destination.\n")
    before = snapshot()
    result = curation.reconcile_feed_retention(retained.receipt["feed_id"])
    assert result["retention_status"] == "blocked" and "destination" in result["retention_detail"]
    assert snapshot() == before and not review.list_proposals()
    assert vault.load_note("Tasks/ingest.md").meta["status"] == "review"


def test_malformed_pending_feed_identity_does_not_break_state_projection(retained):
    CONFIG.staging_dir.mkdir(exist_ok=True)
    (CONFIG.staging_dir / "broken.md").write_text("---\nfeed_retention:\n  feed_id: []\n---\n")
    state = curation.feed_retention_state(retained.receipt["feed_id"], 2)
    assert state["retention_status"] == "unavailable"
