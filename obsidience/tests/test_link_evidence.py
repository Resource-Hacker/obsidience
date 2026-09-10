from pathlib import Path

import pytest

from obsidience.harness.capabilities.vault.propose import stage_proposal
from obsidience.harness.config import CONFIG
from obsidience.harness.knowledge import index, review
from obsidience.harness.knowledge.vault import load_note, write_note


@pytest.fixture
def link_vault(tmp_path, monkeypatch):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path)
    monkeypatch.setattr(CONFIG, "git_commit", False)
    monkeypatch.setattr(index.INDEX, "sync", lambda: None)
    write_note("Tasks/link.md", {"kind": "task", "title": "Link", "taxonomy_path": "wiki/link"}, "Add a useful relationship.")
    write_note("Knowledge/a.md", {"kind": "knowledge", "title": "A"}, "Original article.")
    write_note("Knowledge/b.md", {"kind": "knowledge", "title": "B"}, "Related evidence.")
    return tmp_path


def stage(body="Original article.\n\nUse [[Knowledge/b#Details|B]] for the supporting evidence.", **kwargs):
    args = {"action": "update", "target": "Knowledge/a.md", "title": "A", "body": body,
            "reason": "B supplies the supporting evidence.", **kwargs}
    return Path(stage_proposal(args, {"task": "Tasks/link", "agent": "Alexandria", "run_id": "test"})["staged"]).name


def test_link_review_captures_exact_location_and_revision(link_vault):
    name = stage()
    row, = review.list_proposals()
    evidence, = row["link_evidence"]
    assert row["approvable"] is True
    assert row["link_changes"] == {"added": ["Knowledge/b"], "removed": []}
    assert evidence["derivation"] == "proposed_wikilink"
    assert evidence["body_line"] == 3
    assert evidence["excerpt"] == "Use [B](/Knowledge/b.md#Details) for the supporting evidence."
    assert len(evidence["endpoint_sha256"]) == 64
    assert "confidence" not in evidence
    assert review.approve(name)["approved"] == "Knowledge/a.md"
    accepted = load_note("Knowledge/a.md")
    assert "link_evidence" not in accepted.meta
    assert "proposal_body_sha256" not in accepted.meta
    assert "[B](/Knowledge/b.md#Details)" in accepted.body


@pytest.mark.parametrize("change", ["delete", "proposal"])
def test_link_rejects_stale_evidence_before_any_write(link_vault, change):
    name = stage()
    original = (link_vault / "Knowledge/a.md").read_bytes()
    if change == "delete":
        (link_vault / "Knowledge/b.md").unlink()
    elif change == "proposal":
        proposal = load_note(f"_staging/{name}")
        write_note(proposal.path, proposal.meta, proposal.body + "\nUnreviewed extra assertion.")
    row, = review.list_proposals()
    assert row["approvable"] is False
    with pytest.raises(ValueError, match="Link"):
        review.approve(name)
    assert (link_vault / "Knowledge/a.md").read_bytes() == original
    assert (link_vault / "_staging" / name).exists()


@pytest.mark.parametrize("metadata", [{}, {"retrieval": False}])
def test_endpoint_edits_are_visible_without_rewriting_proposal(link_vault, metadata):
    name = stage()
    before = (CONFIG.staging_dir / name).read_bytes()
    write_note("Knowledge/b.md", {"kind": "knowledge", "title": "B", **metadata}, "Revised accepted evidence.")
    row, = review.list_proposals()
    assert row["approvable"] is True
    assert "Knowledge/b" in row["evidence_warning"]
    assert (CONFIG.staging_dir / name).read_bytes() == before


def test_reciprocal_same_run_links_remain_reviewable(link_vault):
    first = stage()
    second = stage("Related evidence. See [[Knowledge/a]].", target="Knowledge/b.md", title="B")
    review.approve(first)
    row, = review.list_proposals()
    assert row["approvable"] is True
    assert "Knowledge/a" in row["evidence_warning"]
    assert review.approve(second)["approved"] == "Knowledge/b.md"


def test_disappearing_endpoint_does_not_crash_review_queue(link_vault, monkeypatch):
    stage()
    original = Path.read_bytes

    def read(path):
        if path == link_vault / "Knowledge/b.md":
            raise FileNotFoundError(path)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", read)
    row, = review.list_proposals()
    assert row["approvable"] is False
    assert "Link endpoint is unavailable" in row["blocked_reason"]


@pytest.mark.parametrize("metadata", [{"kind": "agent"}, {"skills": ["[[Skills/vault.propose]]"]}])
def test_link_approval_rechecks_body_only_contract(link_vault, metadata):
    name = stage()
    proposal = load_note(f"_staging/{name}")
    write_note(proposal.path, {**proposal.meta, **metadata}, proposal.body)
    row, = review.list_proposals()
    assert row["approvable"] is False
    with pytest.raises(ValueError, match="authority metadata"):
        review.approve(name)
    assert load_note("Knowledge/a.md").kind == "knowledge"


@pytest.mark.parametrize("metadata", [{"kind": "task"}, {"kind": "knowledge", "temporary": True}])
def test_link_approval_rechecks_endpoint_eligibility(link_vault, metadata):
    name = stage()
    write_note("Knowledge/b.md", {"title": "B", **metadata}, "Changed endpoint eligibility.")
    row, = review.list_proposals()
    assert row["approvable"] is False
    with pytest.raises(ValueError, match="Link endpoint"):
        review.approve(name)


@pytest.mark.parametrize("target", ["Knowledge/missing", "Knowledge/a", "Tasks/link", "Knowledge/runtime"])
def test_link_rejects_invalid_or_runtime_endpoints(link_vault, target):
    write_note("Knowledge/runtime.md", {"kind": "knowledge", "temporary": True}, "Runtime summary.")
    with pytest.raises(ValueError, match="Link endpoint"):
        stage(f"Original article. See [[{target}]].")
    assert not list(CONFIG.staging_dir.glob("*.md"))


def test_link_cannot_author_authority_or_noop(link_vault):
    with pytest.raises(ValueError, match="authority metadata"):
        stage(metadata={"kind": "agent"})
    with pytest.raises(ValueError, match="no relationship change"):
        stage("Original article.")
    with pytest.raises(ValueError, match="invalid metadata fields"):
        stage(metadata={"link_evidence": [{"derivation": "verified"}]})


def test_removed_link_is_accepted_text_not_new_model_evidence(link_vault):
    write_note("Knowledge/a.md", {"kind": "knowledge", "title": "A"}, "See [[Knowledge/b]].")
    name = stage("Original article without that link.")
    row, = review.list_proposals()
    evidence, = row["link_evidence"]
    assert evidence["change"] == "removed"
    assert evidence["derivation"] == "accepted_wikilink"
    assert evidence["excerpt"] == "See [b](/Knowledge/b.md)."
    assert review.approve(name)["approved"] == "Knowledge/a.md"


@pytest.mark.parametrize("prefix,suffix", [("\n\n", "\n"), ("  ", "  "), ("# A\n\n", "\n\n")])
def test_link_evidence_uses_persisted_body_whitespace(link_vault, prefix, suffix):
    name = stage(prefix + "See [[Knowledge/b]]." + suffix)
    row, = review.list_proposals()
    assert row["approvable"] is True
    assert row["link_evidence"][0]["body_line"] == 1
    assert review.approve(name)["approved"] == "Knowledge/a.md"
