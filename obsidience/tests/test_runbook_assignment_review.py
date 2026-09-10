"""Generated Runbook approval preserves explicit Task-owned dependencies only."""

from pathlib import Path

import pytest

from obsidience.harness.capabilities.registry import binding, source
from obsidience.harness.capabilities.vault.propose import stage_proposal
from obsidience.harness.config import CONFIG
from obsidience.harness.knowledge import curation, format as article_format, review
from obsidience.harness.knowledge.dependencies import resolve_task_dependencies
from obsidience.harness.knowledge.vault import load_note, resolver, write_note


TARGET_AGENT = "Agents/Executive/Executive"
TARGET_TASK = "Tasks/example"
GENERATOR_TASK = "Tasks/generate/runbook"
OUTPUT = "Runbooks/Generated/executive/example.md"
SELECTED = ["[[Skills/vault.search]]", "[[Skills/task.complete]]"]


@pytest.fixture
def assignment_review(tmp_path, monkeypatch, isolated_task_ledger):
    from obsidience.harness.models import llm, runtime

    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    monkeypatch.setattr(CONFIG, "git_commit", False)
    monkeypatch.setattr(isolated_task_ledger, "sync", lambda *args, **kwargs: None)
    monkeypatch.setattr(review, "git_commit", lambda *args, **kwargs: None)
    monkeypatch.setattr(curation, "try_auto_approve", lambda result, args, context: result)

    def no_model(*args, **kwargs):
        pytest.fail("Runbook proposal/review must not call or lease a model")

    monkeypatch.setattr(llm, "chat", no_model)
    monkeypatch.setattr(runtime, "lease", no_model)
    catalog = ["vault.search", "web.search", "task.complete"]
    for name in catalog:
        write_note(f"Tools/{name}.md", {
            "kind": "tool", "title": name, "binding": binding(name), "source": source(name),
        }, "A bounded executable interface.")
        write_note(f"Skills/{name}.md", {
            "kind": "skill", "title": f"Using {name}", "tool": f"[[Tools/{name}]]",
        }, "Use the exact Tool contract and verify its result.")
    write_note(TARGET_AGENT + ".md", {
        "kind": "agent", "title": "JARVIS", "name": "JARVIS", "role": "executive",
        "tasks": [f"[[{TARGET_TASK}]]"], "source_scopes": ["obsidience/state/system"],
    }, "The owner's Executive identity and Knowledge scope.")
    write_note(TARGET_TASK + ".md", {
        "kind": "task", "title": "Example", "assignee": f"[[{TARGET_AGENT}]]",
    }, "Answer one exact evidence-backed question.")
    write_note("Runbooks/create-a-runbook.md", {
        "kind": "runbook", "title": "Generate procedure",
    }, "Generate the minimal sufficient accepted dependency set.")
    params = {
        "target_task": TARGET_TASK, "target_agent": TARGET_AGENT, "output_runbook": OUTPUT,
        "tools": [f"Tools/{name}" for name in catalog],
        "skills": [f"Skills/{name}" for name in catalog],
    }
    write_note(GENERATOR_TASK + ".md", {
        "kind": "task", "title": "Generate Runbook", "triggers": ["task.assigned"],
        "runbook": "[[Runbooks/create-a-runbook]]", "status": "review", "params": params,
    }, "Supply a reviewed procedure for the assigned Task.")
    return {"task": GENERATOR_TASK, "agent": "Darwin", "event": "task.assigned", "params": params}


def proposal(extra="", *, native=True):
    body = f"""## Prerequisites
The exact assigned Task and its question are available.

## Ordered Actions
1. Follow [search](/Skills/vault.search.md) and call `vault.search` for accepted evidence.
{extra}
2. Follow [complete](/Skills/task.complete.md) and call `task.complete` with the grounded result.

## Bounded Branches
If evidence is insufficient, report that exact gap.

## Stop Conditions
The answer is established or the evidence is insufficient.

## Completion Criteria
The answer names its evidence and remaining uncertainty.

## Verification
Check every factual claim against the retrieved evidence.

## Recovery
Stop on an unrecoverable Tool error without inventing a result.
"""
    metadata = {"type": "runbook", "obsidience": {"skills": list(SELECTED)}} if native else {
        "kind": "runbook", "skills": list(SELECTED),
    }
    return {"action": "create", "target": OUTPUT, "title": "Example procedure", "body": body,
            "reason": "An assigned Task needs a bounded procedure.", "metadata": metadata}


@pytest.mark.parametrize("native", [False, True])
def test_approval_persists_only_selected_skills_and_never_agent_grants(assignment_review, native):
    agent_path = CONFIG.vault_dir / (TARGET_AGENT + ".md")
    agent_before = agent_path.read_bytes()
    task_path = CONFIG.vault_dir / (TARGET_TASK + ".md")
    task_before = task_path.read_bytes()
    result = stage_proposal(proposal(native=native), assignment_review)
    assert not (CONFIG.vault_dir / OUTPUT).exists()
    assert resolve_task_dependencies(load_note(TARGET_TASK + ".md"), resolver())["missing"]
    staged = load_note((CONFIG.vault_dir / result["staged"]).relative_to(CONFIG.vault_dir))
    assert staged.meta["skills"] == SELECTED
    assert staged.meta["event_context"]["skills"] == assignment_review["params"]["skills"]

    approved = review.approve(Path(result["staged"]).name)
    assert approved["approved"] == OUTPUT
    assert approved["for_agent"] == TARGET_AGENT
    raw, _ = article_format.parse((CONFIG.vault_dir / OUTPUT).read_text())
    assert raw["type"] == "runbook" and "kind" not in raw
    assert raw["obsidience"]["skills"] == SELECTED
    assert raw["obsidience"]["task"] == f"[[{TARGET_TASK}]]"
    assert raw["obsidience"]["for_agent"] == f"[[{TARGET_AGENT}]]"
    assert "event_context" not in raw["obsidience"]
    assert agent_path.read_bytes() == agent_before
    assert task_path.read_bytes() == task_before
    assert not {"tools", "skills", "runbooks"} & load_note(TARGET_AGENT + ".md").meta.keys()
    dependencies = resolve_task_dependencies(load_note(TARGET_TASK + ".md"), resolver())
    assert "error" not in dependencies
    assert dependencies["runbook"].ref == OUTPUT.removesuffix(".md")
    assert {tool.ref for tool in dependencies["tool_articles"]} == {
        "Tools/vault.search", "Tools/task.complete",
    }
    assert load_note(GENERATOR_TASK + ".md").meta["status"] == "completed"
    assert not list(CONFIG.staging_dir.glob("*.md"))


@pytest.mark.parametrize("call", [
    "Call `web.search` for fresh evidence.",
    "Use [external search](/Tools/web.search.md).",
])
def test_candidate_catalog_cannot_authorize_a_tool_outside_selected_skills(assignment_review, call):
    assert "Tools/web.search" in assignment_review["params"]["tools"]
    assert "Skills/web.search" in assignment_review["params"]["skills"]
    with pytest.raises(ValueError, match="Tools outside its selected Skills: web.search"):
        stage_proposal(proposal(call), assignment_review)
    assert not (CONFIG.vault_dir / OUTPUT).exists()
    assert not list(CONFIG.staging_dir.glob("*.md"))


def test_approval_rechecks_selected_skill_boundary_after_proposal_change(assignment_review):
    result = stage_proposal(proposal(), assignment_review)
    staged = load_note((CONFIG.vault_dir / result["staged"]).relative_to(CONFIG.vault_dir))
    write_note(staged.path, staged.meta, staged.body + "\nCall `web.search` for fresh evidence.\n")
    with pytest.raises(ValueError, match="Tools outside its selected Skills: web.search"):
        review.approve(Path(result["staged"]).name)
    assert not (CONFIG.vault_dir / OUTPUT).exists()
    assert (CONFIG.vault_dir / staged.path).exists()
    assert not {"tools", "skills", "runbooks"} & load_note(TARGET_AGENT + ".md").meta.keys()
