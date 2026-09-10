"""Documentary freshness is evidence for maintenance, never self-granted trust."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from obsidience.harness.capabilities.vault import maintenance
from obsidience.harness.capabilities.vault.propose import _authored_metadata, stage_proposal
from obsidience.harness.knowledge import format as article_format, review
from obsidience.harness.knowledge.vault import load_note, write_note
from obsidience.tests.test_maintenance_outcomes import isolated, note  # noqa: F401
from obsidience.tests.test_okf_review import okf_vault  # noqa: F401


def test_explicit_deprecation_nominates_only_ordinary_leaf_knowledge(isolated):
    note("Articles/old", article_status="deprecated")
    note("Articles/Articles", article_status="deprecated")
    note("Articles/parent/parent", article_status="deprecated")
    note("Articles/parent/child")
    note("Observations/temporary", article_status="deprecated", temporary=True)
    note("Agents/executor", kind="agent", article_status="deprecated")
    leads = [row for row in maintenance._maintenance_candidates()["candidates"]
             if row["kind"] == "deprecated"]
    assert len(leads) == 1
    assert leads[0]["recommended_task"] == "Archive"
    assert leads[0]["refs"] == ["Articles/old"]
    assert leads[0]["signals"] == {"archive_ref": "Articles/old", "article_status": "deprecated"}
    assert load_note("Articles/old.md") is not None


def test_expired_instant_nominates_audit_without_archival_or_age_inference(isolated):
    now = datetime.now(timezone.utc)
    expired = (now - timedelta(hours=1)).astimezone(timezone(timedelta(hours=9))).isoformat()
    note("Articles/expired", stale_after=expired)
    note("Articles/future", stale_after=(now + timedelta(hours=1)).isoformat())
    note("Articles/old", generated={"by": "process:writer", "at": "2001-01-01T00:00:00Z"})
    leads = [row for row in maintenance._maintenance_candidates()["candidates"]
             if row["kind"] in {"stale_after", "deprecated", "superseded"}]
    assert len(leads) == 1
    assert leads[0]["recommended_task"] == "Audit"
    assert leads[0]["signals"] == {"stale_after": expired}
    assert load_note("Articles/expired.md") is not None


def test_review_preserves_native_documentary_metadata_without_verification(okf_vault):
    metadata = {
        "type": "knowledge", "status": "stable", "description": "Cited current account.",
        "resource": "https://example.org/story", "stale_after": "2026-09-07T00:00:00Z",
        "sources": [{"id": "story", "resource": "https://example.org/source", "title": "Source story"}],
        "generated": {"by": "process:isolated-writer", "at": "2026-09-06T00:00:00Z"},
    }
    result = stage_proposal({"target": "Knowledge/story.md", "action": "create", "title": "Story",
                            "body": "The cited account.[^story]\n\n[^story]: Source story.",
                            "metadata": metadata}, {})
    assert load_note("Knowledge/story.md") is None
    review.approve(Path(result["staged"]).name)
    raw, _ = article_format.parse((okf_vault / "Knowledge/story.md").read_text())
    for key, value in metadata.items():
        assert raw[key] == value
    assert "verified" not in raw and "trust" not in raw.get("obsidience", {})
    assert load_note("Knowledge/story.md").meta["article_status"] == "stable"


@pytest.mark.parametrize("metadata", [
    {"status": "approved"}, {"article_status": "stable"},
    {"stale_after": "2026-09-06"}, {"stale_after": "2026-09-06T00:00:00"},
    {"generated": {"at": "2026-09-06T00:00:00Z"}},
    {"generated": {"by": "writer", "at": "yesterday"}},
    {"sources": [{"title": "No resource"}]}, {"description": []},
    {"verified": {"by": "human:owner", "at": "2026-09-06T00:00:00Z"}},
    {"trust": "verified"}, {"obsidience": {"status": "stable"}},
    {"obsidience": {"stale_after": "2026-09-07T00:00:00Z"}},
])
def test_documentary_fields_do_not_bypass_shape_namespace_or_trust_validation(metadata):
    with pytest.raises(ValueError):
        _authored_metadata(metadata)


def test_archive_records_deprecation_reason_and_time_preserving_content(okf_vault):
    write_note("Knowledge/old.md", {"kind": "knowledge", "title": "Old", "article_status": "stable",
                                   "sources": [{"resource": "https://example.org/old"}],
                                   "foreign_field": {"retained": True}}, "Original historical content.\n")
    before = load_note("Knowledge/old.md")
    result = stage_proposal({"target": before.path, "action": "archive", "reason": "Explicitly superseded."}, {})
    review.approve(Path(result["staged"]).name)
    assert load_note(before.path) is None
    archived = load_note("_archived/" + before.path)
    assert archived.body == before.body
    assert archived.meta["sources"] == before.meta["sources"]
    assert archived.meta["foreign_field"] == before.meta["foreign_field"]
    assert archived.meta["article_status"] == "deprecated"
    assert archived.meta["archive_reason"] == "Explicitly superseded."
    assert datetime.fromisoformat(archived.meta["archived_at"]).utcoffset() is not None


@pytest.mark.parametrize("block", ["inbound", "revision"])
def test_archive_lifecycle_record_does_not_weaken_existing_rejection(okf_vault, block):
    result = stage_proposal({"target": "Knowledge/a.md", "action": "archive", "reason": "Superseded."}, {})
    if block == "inbound":
        write_note("Knowledge/referrer.md", {"kind": "knowledge"}, "Keep [A](/Knowledge/a.md).")
    else:
        write_note("Knowledge/a.md", {"kind": "knowledge"}, "Revised after proposal.")
    before = (okf_vault / "Knowledge/a.md").read_bytes()
    with pytest.raises(ValueError, match="inbound|changed"):
        review.approve(Path(result["staged"]).name)
    assert (okf_vault / "Knowledge/a.md").read_bytes() == before
    assert not (okf_vault / "_archived/Knowledge/a.md").exists()


def test_archive_metadata_write_failure_restores_original_location(okf_vault, monkeypatch):
    result = stage_proposal({"target": "Knowledge/a.md", "action": "archive", "reason": "Superseded."}, {})
    before = (okf_vault / "Knowledge/a.md").read_bytes()

    def fail(*_args, **_kwargs):
        raise OSError("Isolated write failure")

    monkeypatch.setattr(review, "mutate_note_metadata", fail)
    with pytest.raises(OSError, match="Isolated write failure"):
        review.approve(Path(result["staged"]).name)
    assert (okf_vault / "Knowledge/a.md").read_bytes() == before
    assert not (okf_vault / "_archived/Knowledge/a.md").exists()
