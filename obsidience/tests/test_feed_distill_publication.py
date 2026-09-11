"""One Feed Source, one Distill handoff, exact owner-selected publication."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from obsidience.harness import config
from obsidience.harness.capabilities.source import handoff, read
from obsidience.harness.capabilities.task import complete
from obsidience.harness.capabilities.vault import propose
from obsidience.harness.connections import runtime as connections
from obsidience.harness.execution import executor, scheduler
from obsidience.harness.knowledge import curation, review, source, vault


@pytest.fixture
def pipeline(monkeypatch, tmp_path, isolated_task_ledger, request):
    index = isolated_task_ledger
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config.CONFIG, "vault_dir", tmp_path / "obsidience/vault")
    monkeypatch.setattr(config.CONFIG, "git_commit", False)
    monkeypatch.setattr(index, "sync", lambda *_args, **_kwargs: {})
    feed_id = "a" * 32
    destination = "Topics/Reports/Reports"
    current = {"feed_id": feed_id, "destination_ref": destination, "destination_title": "Example",
               "auto_curate": True, "auto_curate_supported": True}
    events = []

    def enqueue(event, params, *, expected_task, source_event, **_kwargs):
        assert index.source(source_event[0]) is not None
        if params.get("feed_binding"):
            assert index.feed_source_binding(params["feed_binding"]["source_id"]) is not None
        index.mark_source_event_dispatched(source_event[0], 1.)
        events.append((event, deepcopy(params), expected_task))
        return [{"task": expected_task, "state": "queued"}]

    @contextmanager
    def guard(feed_id_value, expected_ref=None):
        if current.get("deleted") or feed_id_value != feed_id or expected_ref != current["destination_ref"]:
            raise connections.ConnectionsError("Feed destination mapping changed or was removed")
        yield current

    monkeypatch.setattr(scheduler, "enqueue_named_event", enqueue)
    monkeypatch.setattr(connections, "feed_destination_guard", guard)
    vault.write_note(destination + ".md", {"kind": "knowledge", "title": "Example", "auto_curate": True}, "Feed destination.")
    vault.write_note("Tasks/research/distill.md", {"kind": "task", "title": "Distill",
        "assignee": "[[Agents/Darwin/Darwin]]", "status": "running", "last_run": "distill-run"}, "Distill.")
    vault.write_note("Tasks/ingest.md", {"kind": "task", "title": "Ingest",
        "assignee": "[[Agents/Alexandria/Alexandria]]", "status": "running", "last_run": "ingest-run"}, "Ingest.")
    for name, role in (("Darwin", "researcher"), ("Alexandria", "curator")):
        vault.write_note(f"Agents/{name}/{name}.md", {"kind": "agent", "title": name,
            "role": role, "knowledge": [destination]}, name)
    item = {"record_type": "parsed_rss_item", "native_id": "report-1", "title": "Original headline",
            "reporting_url": "https://example.com/report", "published": "2026-09-09T10:00:00Z",
            "entry": {"summary": "A sparse report."}, "provenance": {"feed_id": feed_id}}
    key = hashlib.sha256(item["native_id"].encode()).hexdigest()
    receipt = {"feed_id": feed_id, "item_key": key, "destination_ref": destination}

    def capture():
        return source.ingest_source(source_type="document", source_ref=f"feed://{feed_id}/{key}",
            media_type="application/json", content=json.dumps(item), captured_at="2026-09-09T10:01:00Z",
            feed_receipt=receipt)

    raw = capture()
    params = {"event": "source.added", **events[-1][1]}
    research = {"_agent_ref": "Agents/Darwin/Darwin", "agent": "Darwin", "task": source.DISTILL_TASK, "run_id": "distill-run",
                "event": "source.added", "params": params}
    read.execute({"source": raw["citation"]}, research)
    summary = "# Complete finding\n\nExact summary with qualifications and dates.\n\nEvidence: " + raw["citation"]
    if getattr(request, "param", None) == "bracketed_source":
        summary += "\n\nSource: [[BBC News]](" + raw["citation"] + ")"

    def deliver():
        return handoff.execute({"title": "Complete finding", "content": summary}, research)

    assert "Research dropped" in deliver()
    inbox_params = {"event": "source.inbox", **events[-1][1]}
    ingest = {"_agent_ref": "Agents/Alexandria/Alexandria", "agent": "Alexandria", "task": "Tasks/ingest", "run_id": "ingest-run",
              "event": "source.inbox", "params": inbox_params,
              "task_note": vault.load_note("Tasks/ingest.md")}
    read.execute({"source": inbox_params["source_citation"]}, ingest)
    args = {"source": inbox_params["source_citation"], "target": curation.feed_article_target(params["feed_binding"])}
    return NS(index=index, raw=raw, research=research, ingest=ingest, params=params, inbox_params=inbox_params,
              receipt=receipt, current=current, events=events, capture=capture, deliver=deliver,
              summary=summary, args=args, item=item)


def test_capture_commits_feed_receipt_before_distill_and_inbox_admission(pipeline):
    assert [(event, task) for event, _params, task in pipeline.events] == [
        ("source.added", source.DISTILL_TASK), ("source.inbox", "Tasks/ingest")]
    assert pipeline.raw["feed_item_created"] is True
    inbox = pipeline.index.source(pipeline.inbox_params["source_id"])
    assert inbox["origin_source_id"] == pipeline.raw["id"]
    assert pipeline.params["feed_binding"] == pipeline.inbox_params["feed_binding"]


def test_repeated_capture_preserves_admitted_destination_and_does_not_dispatch(pipeline):
    pipeline.receipt["destination_ref"] = "Other/Reports/Reports"
    before = len(pipeline.events)
    repeated = pipeline.capture()
    assert repeated["id"] == pipeline.raw["id"] and repeated["feed_item_created"] is False
    assert len(pipeline.events) == before
    assert pipeline.index.feed_source_binding(repeated["id"])["destination_ref"] == "Topics/Reports/Reports"
    assert "already present" in pipeline.deliver() and len(pipeline.events) == before


def test_receipt_insert_fault_rolls_back_the_source_and_emits_nothing(pipeline):
    pipeline.index.db.execute("CREATE TRIGGER reject_feed BEFORE INSERT ON feed_items BEGIN SELECT RAISE(FAIL,'fixture'); END")
    pipeline.index.db.commit()
    previous = pipeline.index.db.execute("SELECT COUNT(*) FROM source_evidence").fetchone()[0]
    pipeline.item["title"] = "Changed item version"
    before = len(pipeline.events)
    with pytest.raises(Exception, match="fixture"):
        pipeline.capture()
    assert pipeline.index.db.execute("SELECT COUNT(*) FROM source_evidence").fetchone()[0] == previous
    assert len(pipeline.events) == before


def test_distill_is_exact_source_first_and_never_fetches_an_unrelated_url(pipeline):
    fresh = {key: value for key, value in pipeline.research.items() if key != "_source_reads"}
    assert read.precondition_error("web.fetch", {"url": pipeline.item["reporting_url"]}, fresh)
    assert read.precondition_error("web.fetch", {"url": pipeline.item["reporting_url"]}, pipeline.research) is None
    assert read.precondition_error("web.fetch", {"urls": ["https://other.example/report"]}, pipeline.research)
    binding = executor.build_activation_binding(NS(ref=source.DISTILL_TASK, title="Distill"), [], pipeline.params)
    assert binding.objective.startswith("Distill the exact activating Source")
    broken = deepcopy(pipeline.params)
    broken["feed_binding"]["destination_ref"] = "Other/Reports/Reports"
    with pytest.raises(source.SourceError):
        executor.build_activation_binding(NS(ref=source.DISTILL_TASK, title="Distill"), [], broken)


def test_automatic_publication_preserves_complete_summary_and_native_sources(pipeline):
    assert vault.load_note("Tasks/research/news.md") is None
    assert vault.load_note("News & Research/Top 10/Top 10.md") is None
    result = propose.execute(pipeline.args, pipeline.ingest)
    assert "Article published" in result
    article = vault.load_note(pipeline.args["target"])
    assert article.body.strip() == vault.normalize_article_body(pipeline.summary, "Complete finding").strip()
    assert article.meta["resource"] == pipeline.item["reporting_url"]
    assert {item["resource"] for item in article.meta["sources"]} == {
        pipeline.raw["citation"], pipeline.inbox_params["source_citation"]}
    assert article.meta["generated"]["by"] == curation.FEED_GENERATOR
    assert "stale_after" not in article.meta
    assert not list(config.CONFIG.staging_dir.glob("*.md"))
    assert complete.execute({"status": "completed", "summary": "Published."}, pipeline.ingest)["accepted"]


def test_handoff_rejects_retired_structured_stories_without_capturing(pipeline):
    before = len(pipeline.events)
    for args in ({"title": "Old batch", "stories": []},
                 {"title": "Mixed batch", "content": pipeline.summary, "stories": []}):
        assert "exactly title and content" in handoff.execute(args, pipeline.research)
    assert len(pipeline.events) == before


@pytest.mark.parametrize("pipeline", ["bracketed_source"], indirect=True)
def test_publication_preserves_markdown_source_label_without_inventing_publisher_article(pipeline):
    from obsidience.harness.knowledge.links import body_links

    original = dict(pipeline.index.source(pipeline.inbox_params["source_id"]))
    result = propose.execute(pipeline.args, pipeline.ingest)
    assert "Article published" in result
    article = vault.load_note(pipeline.args["target"])
    assert article.body.strip() == vault.normalize_article_body(pipeline.summary, "Complete finding").strip()
    assert body_links(article.body, article.path) == []
    assert vault.load_note("BBC News.md") is None
    assert not list(config.CONFIG.staging_dir.glob("*.md"))
    current = pipeline.index.source(pipeline.inbox_params["source_id"])
    assert current["material"] == original["material"]
    assert current["material_sha256"] == original["material_sha256"]
    assert len(pipeline.events) == 2


@pytest.mark.parametrize("fault", ["wrong_target", "rewrite", "metadata", "wrong_source", "unread", "partial"])
def test_model_cannot_rewrite_move_or_publish_unread_handoff(pipeline, fault):
    args = deepcopy(pipeline.args)
    if fault == "wrong_target": args["target"] = "Knowledge/Unsorted.md"
    if fault == "rewrite": args["body"] = "Replacement model summary"
    if fault == "metadata": args["metadata"] = {"type": "knowledge", "auto_curate": True}
    if fault == "wrong_source": args["source"] = pipeline.raw["citation"]
    if fault == "unread": pipeline.ingest.pop("_source_reads")
    if fault == "partial": pipeline.ingest["_source_reads"][args["source"]]["ranges"] = [[0, 1]]
    assert "Proposal rejected" in propose.execute(args, pipeline.ingest)
    assert not list(config.CONFIG.staging_dir.glob("*.md"))
    assert vault.load_note(pipeline.args["target"]) is None


def test_disabled_node_stages_review_and_later_owner_approval_uses_same_bytes(pipeline):
    node = vault.load_note(pipeline.current["destination_ref"] + ".md")
    vault.mutate_note_metadata(node, lambda meta: meta.update(auto_curate=False))
    assert "staged for owner review" in propose.execute(pipeline.args, pipeline.ingest)
    assert vault.load_note(pipeline.args["target"]) is None
    assert not complete.execute({"status": "completed", "summary": "Done", "outcome": "no_change",
                                 "evidence": [pipeline.inbox_params["source_citation"]]}, pipeline.ingest)["accepted"]
    pending = next(config.CONFIG.staging_dir.glob("*.md"))
    review.approve(pending.name)
    assert vault.load_note(pipeline.args["target"]).title == "Complete finding"


@pytest.mark.parametrize("change", ["mapping", "deleted", "body", "metadata", "action", "group"])
def test_pending_review_revalidates_current_mapping_and_exact_compiled_bytes(pipeline, change):
    node = vault.load_note(pipeline.current["destination_ref"] + ".md")
    vault.mutate_note_metadata(node, lambda meta: meta.update(auto_curate=False))
    propose.execute(pipeline.args, pipeline.ingest)
    pending = next(config.CONFIG.staging_dir.glob("*.md"))
    if change == "mapping": pipeline.current["destination_ref"] = "Other/Reports/Reports"
    if change == "deleted": pipeline.current["deleted"] = True
    if change in {"body", "metadata", "action", "group"}:
        note = vault.load_note(pending.relative_to(config.CONFIG.vault_dir))
        if change == "body": note.body += "\nNew unrelated claim."
        elif change == "metadata": note.meta["resource"] = "https://other.example/"
        elif change == "action": note.meta["action"] = "archive"
        else: note.meta["review_group"] = "unrelated-group"
        vault.write_note(note.path, note.meta, note.body)
    with pytest.raises(ValueError):
        review.approve(pending.name)
    assert pending.exists() and vault.load_note(pipeline.args["target"]) is None


def test_changed_destination_rejects_before_staging(pipeline):
    pipeline.current["destination_ref"] = "Other/Reports/Reports"
    assert "Proposal rejected" in propose.execute(pipeline.args, pipeline.ingest)
    assert not list(config.CONFIG.staging_dir.glob("*.md"))


def test_legacy_destination_migration_cannot_rewrite_existing_receipts(pipeline):
    with pytest.raises(ValueError, match="cannot be replaced"):
        pipeline.index.bind_feed_destination(pipeline.receipt["feed_id"], "Topics/Other/Other")
    pipeline.index.db.execute("UPDATE feed_items SET destination_ref='' WHERE feed_id=?", (pipeline.receipt["feed_id"],))
    pipeline.index.db.commit()
    assert pipeline.index.bind_feed_destination(pipeline.receipt["feed_id"], "Topics/Reports/Reports") == 1
    assert pipeline.index.bind_feed_destination(pipeline.receipt["feed_id"], "Topics/Reports/Reports") == 0


def test_pending_retry_reuses_exact_proposal_and_failed_approval_stays_review(pipeline, monkeypatch):
    monkeypatch.setattr(review, "approve_group", lambda _name, **_kwargs: (_ for _ in ()).throw(ValueError("fixture approval conflict")))
    first = propose.execute(pipeline.args, pipeline.ingest)
    assert "staged for owner review" in first and "fixture approval conflict" in first
    pending = list(config.CONFIG.staging_dir.glob("*.md"))
    assert len(pending) == 1
    assert "staged for owner review" in propose.execute(pipeline.args, pipeline.ingest)
    assert list(config.CONFIG.staging_dir.glob("*.md")) == pending
    assert pipeline.ingest["staged_proposals"][-1]["existing"]
    assert not complete.execute({"status": "completed", "summary": "Done"}, pipeline.ingest)["accepted"]


def test_repeated_published_source_preserves_owner_corrections_without_new_review(pipeline):
    assert "Article published" in propose.execute(pipeline.args, pipeline.ingest)
    note = vault.load_note(pipeline.args["target"])
    vault.write_note(note.path, note.meta, note.body + "\nOwner correction.\n")
    before = (config.CONFIG.vault_dir / note.path).read_bytes()
    fresh = {key: value for key, value in pipeline.ingest.items()
             if key not in {"staged_proposals", "feed_publication_result"}}
    assert "already published" in propose.execute(pipeline.args, fresh)
    assert (config.CONFIG.vault_dir / note.path).read_bytes() == before
    assert not list(config.CONFIG.staging_dir.glob("*.md"))
    assert complete.execute({"status": "completed", "summary": "Already accepted", "outcome": "no_change",
                             "evidence": [pipeline.inbox_params["source_citation"]]}, fresh)["accepted"]


def test_distill_cannot_change_a_committed_handoff_or_skip_it(pipeline):
    before = len(pipeline.events)
    result = handoff.execute({"title": "Different", "content": pipeline.summary + "\nReplacement"}, pipeline.research)
    assert "already handed off" in result
    assert len(pipeline.events) == before
    context = {key: value for key, value in pipeline.research.items() if key != "handoff_source_id"}
    context["task_note"] = vault.load_note("Tasks/research/distill.md")
    assert not complete.execute({"status": "completed", "summary": "Skipped", "outcome": "no_change",
                                 "evidence": [pipeline.raw["citation"]]}, context)["accepted"]
    assert complete.execute({"status": "failed", "summary": "Explicit blocked result"}, context)["accepted"]
