"""One Task-owned procedure projection for execution, assignment, and display."""

import asyncio
from copy import deepcopy
from pathlib import Path

import pytest

from obsidience.harness.config import CONFIG
from obsidience.harness.execution import assignments, executor, scheduler
from obsidience.harness.knowledge.dependencies import (
    agent_dependencies, assigned_tasks, resolve_task_dependencies, select_runbook,
)
from obsidience.harness.knowledge.vault import load_note, resolver, write_note


@pytest.fixture
def vault(tmp_path, monkeypatch, isolated_task_ledger):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    return isolated_task_ledger


def note(ref, kind, **meta):
    write_note(ref + ".md", {"kind": kind, "title": Path(ref).name, **meta}, "Procedure or task.")
    return load_note(ref + ".md")


def pair(name):
    note("Tools/" + name, "tool", binding="capability:" + name,
         source="obsidience/harness/capabilities/" + name.replace(".", "/") + ".py")
    note("Skills/" + name, "skill", tool="/Tools/" + name + ".md")


def baseline():
    for name in ("task.complete", "vault.read", "vault.search", "web.fetch"):
        pair(name)
    executive = note("Agents/Executive/Executive", "agent", role="executive", tasks=["Tasks/query"],
                     tools=["Tools/web.fetch"], runbooks=["Runbooks/unrelated"])
    darwin = note("Agents/Darwin/Darwin", "agent", role="researcher", tasks=["Tasks/query"])
    task = note("Tasks/query", "task", assignee=executive.ref, runbook="Runbooks/query")
    note("Runbooks/query", "runbook", for_agent=executive.ref, skills=["Skills/vault.read"])
    note("Runbooks/unrelated", "runbook", skills=["Skills/web.fetch"])
    return executive, darwin, task


def generation():
    note("Runbooks/generate", "runbook", skills=["Skills/vault.read"])
    return note("Tasks/generate/runbook", "task", assignee="Agents/Darwin/Darwin",
                triggers=["task.assigned"], runbook="Runbooks/generate")


def test_selected_task_derives_runbook_and_only_its_paired_capabilities(vault):
    executive, _darwin, task = baseline()
    deps = agent_dependencies(executive, resolver())
    assert deps["runbooks"] == ["Runbooks/query"]
    assert deps["skills"] == ["Skills/task.complete", "Skills/vault.read"]
    assert deps["tools"] == ["Tools/task.complete", "Tools/vault.read"]
    assert deps["errors"] == []
    assert executor.resolve_spine(task, resolver())["tools"] == ["task.complete", "vault.read"]


def test_skill_plural_tools_is_not_an_alternate_dependency_grant(vault):
    _executive, _darwin, task = baseline()
    note("Skills/vault.read", "skill", tool="Tools/vault.read", tools=["Tools/web.fetch"])
    dependency = resolve_task_dependencies(task, resolver())
    assert "plural tools" in dependency.get("error", "")
    assert executor.resolve_spine(task, resolver()).get("error") == dependency["error"]
    assert "Skills/vault.read" not in assignments.library_candidates(resolver())["skills"]


def test_shared_task_selects_exact_agent_variant_without_mutating_assignment(vault):
    executive, darwin, task = baseline()
    note("Runbooks/Generated/researcher/query", "runbook", task=task.ref, for_agent=darwin.ref,
         skills=["Skills/vault.search"])
    before = deepcopy(task.meta)
    assert select_runbook(task, resolver(), agent_ref=darwin.ref)[0].ref == "Runbooks/Generated/researcher/query"
    assert agent_dependencies(darwin, resolver())["tools"] == ["Tools/task.complete", "Tools/vault.search"]
    assert agent_dependencies(executive, resolver())["runbooks"] == ["Runbooks/query"]
    assert task.meta == before


def test_ambiguous_specializations_and_malformed_fallback_fail_closed(vault):
    executive, _darwin, task = baseline()
    for name in ("one", "two"):
        note("Runbooks/" + name, "runbook", task=task.ref, for_agent=executive.ref, skills=["Skills/vault.read"])
    assert "ambiguous" in select_runbook(task, resolver())[1]
    assert assignments.ensure_task_runbook(task, resolver())["status"] == "blocked"
    wrong = note("Tasks/wrong", "task", runbook="Runbooks/missing")
    assert "not found" in select_runbook(wrong, resolver())[1]


def test_foreign_authored_runbook_requires_generation_and_staged_variant_is_not_selected(vault):
    _executive, darwin, task = baseline()
    note("_staging/private", "runbook", task=task.ref, for_agent=darwin.ref, skills=["Skills/web.fetch"])
    assert select_runbook(task, resolver(), agent_ref=darwin.ref) == (None, None)


def test_malformed_agent_and_cross_agent_ancestor_are_not_a_generation_bypass(vault):
    executive, darwin, task = baseline()
    note("Runbooks/query", "runbook", for_agent="Agents/missing", skills=["Skills/vault.read"])
    assert assignments.ensure_task_runbook(task, resolver())["status"] == "blocked"
    note("Runbooks/query", "runbook", for_agent=executive.ref, skills=["Skills/vault.read"])
    note("Runbooks/foreign-parent", "runbook", for_agent=darwin.ref,
         subrunbooks=["Runbooks/query"], skills=["Skills/web.fetch"])
    assert "inapplicable" in resolve_task_dependencies(task, resolver())["error"]


def test_ancestor_context_without_unselected_siblings(vault):
    executive, _darwin, task = baseline()
    note("Runbooks/family", "runbook", subrunbooks=["Runbooks/query", "Runbooks/unrelated"],
         skills=["Skills/vault.search"])
    note("Tools/vault", "tool", subtools=["Tools/vault.read", "Tools/web.fetch"])
    deps = agent_dependencies(executive, resolver())
    assert deps["runbooks"] == ["Runbooks/family", "Runbooks/query"]
    assert "Tools/vault" in deps["tools"]
    assert "Tools/web.fetch" not in deps["tools"]
    assert executor.resolve_spine(task, resolver())["tools"] == ["task.complete", "vault.read", "vault.search"]


def test_assignment_roots_include_schedule_triggers_and_live_work_not_draft_or_foreign(vault):
    executive, darwin, _task = baseline()
    for name, meta in (("scheduled", {"schedule": "0 * * * *"}), ("triggered", {"triggers": ["source.inbox"]}),
                       ("live", {"status": "pending"}), ("draft", {}), ("old", {"status": "completed"})):
        note("Tasks/" + name, "task", assignee=darwin.ref, **meta)
    assert {task.ref for task in assigned_tasks(darwin, resolver())} == {
        "Tasks/query", "Tasks/scheduled", "Tasks/triggered", "Tasks/live",
    }
    assert {task.ref for task in assigned_tasks(executive, resolver())} == {"Tasks/query"}


def test_container_exclusion_does_not_return_excluded_child_capabilities(vault):
    executive, _darwin, _task = baseline()
    note("Tasks/excluded", "task", runbook="Runbooks/unrelated")
    note("Tasks/root", "task", subtasks=["Tasks/query", "Tasks/excluded"], exclude_subtasks=["Tasks/excluded"])
    executive.meta["tasks"] = ["Tasks/root"]
    deps = agent_dependencies(executive, resolver())
    assert deps["tasks"] == ["Tasks/query", "Tasks/root"]
    assert "Tools/web.fetch" not in deps["tools"]


def test_generation_is_stable_fifo_and_uses_shared_catalog_not_agent_grants(vault):
    _executive, darwin, task = baseline()
    generator = generation()
    before_task = deepcopy(task.meta)
    before_articles = {path: path.read_bytes() for path in CONFIG.vault_dir.rglob("*.md")}
    first = assignments.ensure_task_runbook(task, resolver(), agent_ref=darwin.ref)
    second = assignments.ensure_task_runbook(task, resolver(), agent_ref=darwin.ref)
    assert first["status"] == second["status"] == "queued"
    current = load_note(generator.path)
    params = deepcopy(current.meta["params"])
    assert params["event"] == "task.assigned"
    assert params["target_task"] == task.ref and params["target_agent"] == darwin.ref
    assert "Tools/web.fetch" in params["tools"]  # candidate only; not automatically granted
    assert current.meta.get("event_queue", []) == []
    task2 = note("Tasks/another", "task", assignee=darwin.ref)
    assignments.ensure_task_runbook(task2, resolver())
    assignments.ensure_task_runbook(task, resolver(), agent_ref=darwin.ref)
    current = load_note(generator.path)
    assert current.meta["params"] == params
    assert [item["target_task"] for item in current.meta["event_queue"]] == [task2.ref]
    assert load_note(task.path).meta == before_task
    assert all(path.read_bytes() == content for path, content in before_articles.items())


def test_waiting_scheduler_preserves_occurrence_then_proceeds_after_accepted_procedure(vault):
    _executive, darwin, _task = baseline()
    generation()
    task = note("Tasks/missing", "task", assignee=darwin.ref, status="pending",
                params={"event": "source.inbox", "activation_key": "original", "source_ref": "Source/original"},
                event_queue=[{"event": "source.inbox", "activation_key": "next"}])
    before = deepcopy(task.meta)
    assert scheduler.prepare_task(task) is False
    assert load_note(task.path).meta == before
    note("Runbooks/accepted", "runbook", task=task.ref, for_agent=darwin.ref, skills=["Skills/vault.read"])
    assert scheduler.prepare_task(load_note(task.path)) is True
    assert load_note(task.path).meta == before


def test_nested_container_exclusion_does_not_queue_unneeded_generation(vault):
    executive, _darwin, _task = baseline()
    generation()
    note("Tasks/missing", "task", assignee=executive.ref)
    note("Tasks/nested", "task", subtasks=["Tasks/query", "Tasks/missing"], exclude_subtasks=["Tasks/missing"])
    root = note("Tasks/root", "task", subtasks=["Tasks/nested"])
    assert assignments.ensure_task_runbook(root, resolver())["status"] == "ready"
    assert load_note("Tasks/generate/runbook.md").meta.get("params") is None


def test_direct_executor_and_compiler_queue_missing_runbook_without_model_attempt(vault, monkeypatch):
    _executive, darwin, _task = baseline()
    generation()
    task = note("Tasks/missing", "task", assignee=darwin.ref, status="pending")
    monkeypatch.setattr(executor.llm, "chat", lambda *_args, **_kwargs: pytest.fail("no procedure, no model"))
    result = asyncio.run(executor.run_task(task))
    assert result["status"] == "pending"
    assert vault.runs() == []
    with pytest.raises(RuntimeError, match="awaiting-runbook"):
        asyncio.run(executor.compile_activation(task))
    generator = load_note("Tasks/generate/runbook.md")
    assert generator.meta.get("event_queue", []) == []


def test_graph_dependency_projection_uses_current_runtime_without_article_mutation(vault):
    executive, _darwin, _task = baseline()
    before = {path: path.read_bytes() for path in CONFIG.vault_dir.rglob("*.md")}
    vault.sync(embed=False)
    node = next(node for node in vault.graph()["nodes"] if node["id"] == executive.ref)
    assert "checkouts" not in node
    assert node["dependencies"]["tools"] == ["Tools/task.complete", "Tools/vault.read"]
    assert all(path.read_bytes() == content for path, content in before.items())
