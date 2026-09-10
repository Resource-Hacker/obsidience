"""Native OKF review preserves authored metadata and exact Markdown evidence."""

import hashlib
from pathlib import Path

import pytest

from obsidience.harness.capabilities.vault.propose import (
    GENERATED_RUNBOOK_SECTIONS,
    stage_proposal,
    validate_generated_runbook,
)
from obsidience.harness.config import CONFIG
from obsidience.harness.knowledge import curation, format as article_format, index, review
from obsidience.harness.knowledge.vault import load_note, write_note


@pytest.fixture
def okf_vault(tmp_path, monkeypatch, isolated_task_ledger):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    monkeypatch.setattr(CONFIG, "git_commit", False)
    monkeypatch.setattr(index.INDEX, "sync", lambda: None)
    monkeypatch.setattr(curation, "try_auto_approve", lambda result, args, context: result)
    write_note("Tasks/link.md", {
        "type": "task", "title": "Link", "taxonomy_path": "wiki/link",
    }, "Add one useful relationship.")
    write_note("Knowledge/a.md", {"type": "knowledge", "title": "A"}, "Original article.")
    write_note("Knowledge/b.md", {"type": "knowledge", "title": "B"}, "Supporting evidence.")
    write_note("Agents/darwin.md", {
        "type": "agent", "title": "Darwin", "runbooks": ["Runbooks/research"],
        "sources": [{"url": "https://example.org/identity"}],
    }, "Research identity.")
    write_note("Runbooks/research.md", {"type": "runbook", "title": "Research"}, "Research the request.")
    return CONFIG.vault_dir


def stage_link(body, **overrides):
    return stage_proposal({
        "action": "update", "target": "Knowledge/a.md", "title": "A", "body": body,
        **overrides,
    }, {"task": "Tasks/link", "agent": "Alexandria"})


def staged_path(result):
    return CONFIG.vault_dir / result["staged"]


@pytest.mark.parametrize("link", [
    "[[Knowledge/b#Details|B]]",
    "[B](/Knowledge/b.md#Details)",
    "[B](b.md#Details)",
])
def test_link_hashes_canonical_body_before_staging(okf_vault, link):
    result = stage_link(f"# A\n\nOriginal article.\n\nSee {link}.\n\n")
    path = staged_path(result)
    raw, body = article_format.parse(path.read_text())
    assert raw["type"] == "knowledge"
    assert raw["obsidience"]["authored_fields"] == []
    assert body == "Original article.\n\nSee [B](/Knowledge/b.md#Details).\n"
    assert raw["obsidience"]["proposal_body_sha256"] == hashlib.sha256(body.encode()).hexdigest()
    for _ in range(2):
        note = load_note(path.relative_to(okf_vault))
        write_note(note.path, note.meta, note.body)
    assert article_format.parse(path.read_text())[1] == body
    row, = review.list_proposals()
    assert row["approvable"], row["blocked_reason"]
    assert row["link_changes"] == {"added": ["Knowledge/b"], "removed": []}
    evidence, = row["link_evidence"]
    assert evidence["body_line"] == 3
    assert evidence["excerpt"] == "See [B](/Knowledge/b.md#Details)."
    assert review.approve(path.name)["approved"] == "Knowledge/a.md"
    accepted = load_note("Knowledge/a.md")
    assert accepted.body == body
    assert "authored_fields" not in accepted.meta
    assert "proposal_body_sha256" not in accepted.meta


def test_reference_links_use_full_document_scope_for_evidence(okf_vault):
    result = stage_link("Original article.\n\nSee [B][support].\n\n[support]: b.md#Details")
    row, = review.list_proposals()
    assert row["approvable"], row["blocked_reason"]
    evidence, = row["link_evidence"]
    assert evidence["ref"] == "Knowledge/b"
    assert evidence["body_line"] == 3
    assert evidence["excerpt"] == "See [B][support]."
    review.approve(Path(result["staged"]).name)
    assert "Knowledge/b" in load_note("Knowledge/a.md").links


def test_removed_markdown_links_report_accepted_evidence(okf_vault):
    write_note("Knowledge/a.md", {"type": "knowledge", "title": "A"},
               "See [B](/Knowledge/b.md).")
    result = stage_link("Original article without a relationship.")
    row, = review.list_proposals()
    evidence, = row["link_evidence"]
    assert evidence["change"] == "removed"
    assert evidence["derivation"] == "accepted_wikilink"  # Existing presentation enum.
    assert evidence["excerpt"] == "See [B](/Knowledge/b.md)."
    review.approve(Path(result["staged"]).name)


def test_code_and_external_urls_are_not_article_relationships(okf_vault):
    with pytest.raises(ValueError, match="no relationship change"):
        stage_link("Original article. `[B](/Knowledge/b.md)`\n\n"
                   "```md\n[[Knowledge/b]]\n```\n\n[B](https://example.org/Knowledge/b.md)")


def test_implicit_proposal_type_preserves_agent_metadata(okf_vault):
    result = stage_proposal({
        "action": "update", "target": "Agents/darwin.md", "title": "Darwin",
        "body": "Updated research identity.",
    }, {})
    raw, _ = article_format.parse(staged_path(result).read_text())
    assert raw["type"] == "knowledge"
    review.approve(Path(result["staged"]).name)
    accepted = load_note("Agents/darwin.md")
    assert accepted.kind == "agent"
    assert accepted.meta["runbooks"] == ["Runbooks/research"]
    assert accepted.meta["sources"] == [{"url": "https://example.org/identity"}]


def test_link_implicit_type_preserves_agent_identity(okf_vault):
    result = stage_link("Research identity. See [[Knowledge/b]].",
                        target="Agents/darwin.md", title="Darwin")
    review.approve(Path(result["staged"]).name)
    assert load_note("Agents/darwin.md").kind == "agent"


def test_public_type_and_safe_namespace_create_task(okf_vault):
    result = stage_proposal({
        "target": "Tasks/example.md", "title": "Example", "body": "Find the answer.",
        "metadata": {"type": "task", "obsidience": {
            "assignee": "/Agents/darwin.md", "runbook": "/Runbooks/research.md",
            "taxonomy_path": "research/question", "acceptance": ["A source-backed answer."],
        }},
    }, {})
    raw, _ = article_format.parse(staged_path(result).read_text())
    assert raw["type"] == "task"
    assert "kind" not in raw
    assert raw["obsidience"]["authored_fields"] == [
        "acceptance", "assignee", "kind", "runbook", "taxonomy_path",
    ]
    review.approve(Path(result["staged"]).name)
    accepted = load_note("Tasks/example.md")
    assert accepted.kind == "task"
    assert accepted.meta["assignee"] == "/Agents/darwin.md"
    persisted, _ = article_format.parse((okf_vault / accepted.path).read_text())
    assert "status" not in persisted
    assert "status" not in persisted["obsidience"]
    write_note(accepted.path, {**accepted.meta, "status": "completed"}, accepted.body)
    update = stage_proposal({
        "target": accepted.path, "action": "update", "title": accepted.title,
        "body": "An updated outcome definition.",
    }, {})
    assert article_format.parse(staged_path(update).read_text())[0]["type"] == "knowledge"
    review.approve(staged_path(update).name)
    updated = load_note(accepted.path)
    assert updated.kind == "task"
    assert updated.meta["status"] == "completed"
    assert updated.meta["acceptance"] == ["A source-backed answer."]


@pytest.mark.parametrize("metadata", [
    {"type": "task", "kind": "agent"},
    {"type": "unknown"},
    {"status": "running"},
    {"obsidience": {"auto_curate": True}},
    {"obsidience": {"status": "completed"}},
    {"obsidience": {"verified": True}},
    {"obsidience": {"authored_fields": []}},
    {"obsidience": {"review_class": "article"}},
    {"obsidience": {"type": "agent"}},
    {"tool": "Tools/a", "obsidience": {"tool": "Tools/b"}},
])
def test_native_projection_cannot_bypass_metadata_allowlist(okf_vault, metadata):
    with pytest.raises(ValueError, match="metadata"):
        stage_proposal({"target": "Knowledge/new.md", "body": "A claim.", "metadata": metadata}, {})
    assert not list(CONFIG.staging_dir.glob("*.md"))


def test_link_rejects_even_explicit_knowledge_type(okf_vault):
    with pytest.raises(ValueError, match="authority metadata"):
        stage_link("See [[Knowledge/b]].", metadata={"type": "knowledge"})


def test_duplicate_proposal_does_not_ignore_metadata_changes(okf_vault):
    args = {"target": "Knowledge/new.md", "body": "A claim."}
    staged = stage_proposal(args, {})
    assert stage_proposal(args, {})["existing"] is True
    with pytest.raises(ValueError, match="pending review"):
        stage_proposal({**args, "metadata": {"type": "agent"}}, {})
    with pytest.raises(ValueError, match="metadata"):
        stage_proposal({**args, "metadata": {"verified": True}}, {})
    assert staged_path(staged).exists()


@pytest.mark.parametrize("tamper", [{"kind": "agent"}, {"skills": ["Skills/vault.propose"]},
                                   {"authored_fields": None}])
def test_link_rechecks_native_envelope_before_approval(okf_vault, tamper):
    result = stage_link("See [[Knowledge/b]].")
    path = staged_path(result)
    proposal = load_note(path.relative_to(okf_vault))
    write_note(proposal.path, {**proposal.meta, **tamper}, proposal.body)
    with pytest.raises(ValueError, match="authority metadata"):
        review.approve(path.name)
    assert load_note("Knowledge/a.md").body == "Original article.\n"


def test_generated_runbook_accepts_md_paths_without_widening_checkout():
    body = "\n\n".join(f"## {section}\nBounded procedure." for section in GENERATED_RUNBOOK_SECTIONS)
    body += "\nUse [search](/Skills/vault.search.md) with [Tool](/Tools/vault.search.md)."
    params = {"output_runbook": "Runbooks/example.md", "skills": ["Skills/vault.search"],
              "tools": ["Tools/vault.search"]}
    validate_generated_runbook("Runbooks/example.md", body, params, params["skills"])
    with pytest.raises(ValueError, match="Tools outside its selected Skills"):
        validate_generated_runbook("Runbooks/example.md", body + " [read](/Tools/vault.read.md).", params, params["skills"])


def test_tool_documentary_sources_do_not_replace_executable_source(okf_vault):
    # Tool indexes never execute; a provenance list is still valid OKF data.
    review._validate_capability_metadata("Tools/group.md", {
        "kind": "tool", "subtools": ["Tools/vault.search"],
        "sources": [{"url": "https://example.org/reference"}],
    })
    with pytest.raises(ValueError, match="not executable"):
        review._validate_capability_metadata("Tools/missing.md", {
            "kind": "tool", "title": "missing", "sources": [{"url": "https://example.org/reference"}],
        })


def test_native_pending_skill_pairs_resolve_md_paths(okf_vault):
    from obsidience.harness.capabilities.registry import binding, source

    tool_name = "application.launch"
    tool_result = stage_proposal({
        "target": f"Tools/{tool_name}.md", "title": tool_name, "body": "Launch an application.",
        "metadata": {"type": "tool", "obsidience": {
            "binding": binding(tool_name), "source": source(tool_name),
        }},
    }, {})
    stage_proposal({
        "target": f"Skills/{tool_name}.md", "title": "Launch an application",
        "body": "Invoke and verify application launch.",
        "metadata": {"type": "skill", "obsidience": {"tool": f"/Tools/{tool_name}.md"}},
    }, {})
    result = review.approve(staged_path(tool_result).name)
    assert result["paired_skill"] == f"Skills/{tool_name}.md"
    assert load_note(f"Skills/{tool_name}.md").meta["tool"] == f"/Tools/{tool_name}.md"
    assert not list(CONFIG.staging_dir.glob("*.md"))


def test_legacy_flat_proposal_remains_readable_for_review(okf_vault):
    CONFIG.staging_dir.mkdir()
    path = CONFIG.staging_dir / "legacy.md"
    # A historical envelope intentionally has no implicit type or authored_fields.
    path.write_text(article_format.serialize({
        "proposal": True, "action": "update", "target": "Agents/darwin.md",
        "title": "Darwin", "agent": "Alexandria", "task": "", "review_class": "article",
    }, "Legacy proposed research identity.\n"))
    row, = review.list_proposals()
    assert row["target"] == "Agents/darwin.md"
    review.approve(path.name)
    assert load_note("Agents/darwin.md").kind == "agent"
