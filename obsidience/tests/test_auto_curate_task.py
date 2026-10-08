from __future__ import annotations

import pytest
from fastapi import HTTPException

from obsidience.harness.config import CONFIG
from obsidience.harness.capabilities.vault import maintenance
from obsidience.harness.interfaces.api import app as server
from obsidience.harness.knowledge import auto_curate, curation, review
from obsidience.harness.knowledge.links import canonical_body
from obsidience.harness.knowledge.vault import load_note, write_note


@pytest.fixture
def vault(monkeypatch, tmp_path):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path)
    monkeypatch.setattr(server.INDEX, "sync", lambda: None)
    for agent in ("Executive", "Alexandria", "Darwin", "Heimdall"):
        write_note(f"Agents/{agent}/{agent}.md", {
            "title": agent, "kind": "agent", "auto_curate": agent != "Executive",
        }, "The accepted agent identity.")
    write_note("Agents/Executive/Observations/Observations.md", {
        "title": "Observations", "kind": "knowledge", "auto_curate": True,
    }, "Owner-enabled observation lifecycle.")
    return tmp_path


def test_maintenance_claim_identity_is_the_stable_article_pair():
    assert maintenance._candidate_identity({"candidate_key": "a", "refs": ["K/a", "K/b"]}) == maintenance._candidate_identity({"candidate_key": "b", "candidate_refs": ["K/b", "K/a"]})


def test_permission_inherits_with_nearest_explicit_child_override(vault):
    target = "Agents/Darwin/Observations/Temporary Observations/example"
    assert auto_curate.enabled(target)
    write_note("Agents/Darwin/Observations/Observations.md", {"kind": "knowledge", "auto_curate": False}, "Require review.")
    assert not auto_curate.enabled(target)
    write_note(target + ".md", {"kind": "knowledge", "auto_curate": True}, "Explicit child.")
    assert auto_curate.enabled(target)
    assert not auto_curate.enabled("Tools/web.fetch")
    assert not auto_curate.enabled("Agents/Executive/Architecture/example")


def test_toggle_specialist_subject_writes_real_index_without_task(vault):
    result = server.set_article_auto_curate("@branch/Agents/Darwin/Observations", {"enabled": False})
    assert result == {"article": "@branch/Agents/Darwin/Observations", "enabled": False, "task": None}
    assert load_note("Agents/Darwin/Observations/Observations.md").meta["auto_curate"] is False
    assert not list(vault.glob("Tasks/**/*.md"))
    server.set_article_auto_curate("@branch/Agents/Darwin/Observations", {"enabled": True})
    assert load_note("Agents/Darwin/Observations/Observations.md").meta["auto_curate"] is True


@pytest.mark.parametrize("ref", ["@library", "@sat/Darwin/tools", "@sat/Darwin/tasks"])
def test_capability_checkout_containers_are_not_auto_curated(vault, ref):
    assert not server.get_article(ref)["auto_curate_supported"]
    with pytest.raises(HTTPException, match="capability definitions"):
        server.set_article_auto_curate(ref, {"enabled": True})


def test_scoped_knowledge_approval_uses_permission_and_normal_review(vault, monkeypatch):
    write_note("Tasks/query.md", {"kind": "task", "assignee": "[[Agents/Darwin/Darwin]]", "status": "running", "last_run": "run1"}, "Research.")
    calls = []
    monkeypatch.setattr(review, "approve", lambda name: calls.append(name) or {"target": "accepted"})
    result = {"target": "Agents/Darwin/Observations/finding.md", "action": "create", "staged": "_staging/test.md"}
    args = {"body": "A bounded source workflow finding. [[Agents/Darwin/Darwin]]", "metadata": {"kind": "knowledge"}}
    context = {"task": "Tasks/query", "run_id": "run1", "agent": "Darwin"}
    assert curation.try_auto_approve(result, args, context)["auto_approved"]
    assert calls == ["test.md"]
    for bad in (
        {**result, "target": "Agents/Heimdall/Observations/finding.md"},
        {**result, "target": "Agents/Darwin/Darwin.md"},
        {**result, "action": "archive"},
    ):
        assert not curation.try_auto_approve(bad, args, context).get("auto_approved")
    assert not curation.try_auto_approve(result, {**args, "metadata": {"kind": "knowledge", "auto_curate": True}}, context).get("auto_approved")
    assert not curation.try_auto_approve(result, args, {**context, "run_id": "forged"}).get("auto_approved")
    server.set_article_auto_curate("@branch/Agents/Darwin/Observations", {"enabled": False})
    assert not curation.try_auto_approve(result, args, context).get("auto_approved")
    assert calls == ["test.md"]


def test_graph_and_reader_use_the_same_effective_permission(vault, monkeypatch):
    for relative, meta in (("Observations", {}), ("child", {}), ("private/private", {"auto_curate": False}), ("private/child", {})):
        write_note(f"Agents/Darwin/Observations/{relative}.md", {"kind": "knowledge", **meta}, "Working knowledge.")
    monkeypatch.setattr(server.INDEX, "graph", lambda: {"nodes": [], "edges": []})
    graph = server.graph()
    assert graph["auto_curate_resolved"]
    active = set(graph["auto_curated"])
    assert {"Agents/Darwin/Darwin", "@branch/Agents/Darwin/Observations", "Agents/Darwin/Observations/child"} <= active
    assert "@sat/Darwin/tools" not in active
    assert "Agents/Darwin/Observations/private/child" not in active
    assert not server.get_article("Agents/Darwin/Observations/private/child")["auto_curate"]


def test_real_proposal_path_publishes_once_and_records_normal_review(vault, monkeypatch):
    from obsidience.harness.capabilities.vault.propose import stage_proposal
    from obsidience.harness.knowledge import index

    monkeypatch.setattr(CONFIG, "db_path", vault / "test.sqlite3")
    monkeypatch.setattr(CONFIG, "git_commit", False)
    ledger = index.Index()
    monkeypatch.setattr(index, "INDEX", ledger)
    monkeypatch.setattr(ledger, "sync", lambda: None)
    write_note("Tasks/query.md", {
        "kind": "task", "assignee": "[[Agents/Darwin/Darwin]]",
        "status": "running", "last_run": "run1",
    }, "Research.")
    body = "Darwin preserves research evidence in Source. [[Agents/Darwin/Darwin]]"
    result = stage_proposal({
        "target": "Agents/Darwin/Observations/evidence.md", "action": "create",
        "title": "Evidence", "body": body, "reason": "Existing role contract.",
        "metadata": {"kind": "knowledge"},
    }, {"task": "Tasks/query", "agent": "Darwin", "run_id": "run1"})
    assert result["auto_approved"]
    assert load_note(result["target"]).body.strip() == canonical_body(body, result["target"])
    assert not (vault / result["staged"]).exists()
    assert ledger.review_outcome("run1")["approved_count"] == 1
