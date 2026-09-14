"""Accepted capability descriptions inform interactive replies, never grant Tools."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime
import json
import time
from types import SimpleNamespace as NS
from zoneinfo import ZoneInfo

import pytest

from obsidience.harness.capabilities.registry import REGISTRY
from obsidience.harness.conversation import context_bindings as bindings
from obsidience.harness.conversation.selection import project_historical_evidence, TaskSelectionError
from obsidience.harness.execution import executor
from obsidience.harness.knowledge.vault import Note, Resolver
from obsidience.tests.test_execution_cancellation import execution  # noqa: F401


def graph(*, tasks=2, tool_names=("computer.act",), long_description=False):
    notes = []
    def note(ref, kind, body="Accepted definition.", **meta):
        item = Note(ref + ".md", ref.rsplit("/", 1)[-1], {"kind": kind, **meta}, body)
        notes.append(item)
        return item
    for name in sorted(set(tool_names) | {"task.complete", "vault.read"}):
        description = ("Apply one click at the point selected in the immediately preceding image."
                       if name == "computer.act" else "Read the accepted data.")
        if long_description:
            description += " Bounded detail." * 40
        note("Tools/" + name, "tool", description + "\n\nUnselected later paragraph.",
             binding="capability:" + name,
             source="obsidience/harness/capabilities/" + name.replace(".", "/") + ".py")
        note("Skills/" + name, "skill", tool="Tools/" + name)
    assigned = []
    for index in range(tasks):
        ref = "Tasks/query" if index == 0 else f"Tasks/operate-{index:02}"
        task = note(ref, "task", runbook=f"Runbooks/{index}", assignee=bindings.EXECUTIVE_REF)
        note(f"Runbooks/{index}", "runbook", skills=["Skills/" + name for name in
             (("vault.read",) if index == 0 else tool_names)])
        assigned.append(task)
    agent = note(bindings.EXECUTIVE_REF, "agent", tasks=[task.ref for task in assigned],
                 tools=["Tools/invented.keyboard", "Tools/invented.camera"])
    # Unassigned and hidden proposals never describe available capabilities.
    note("Tasks/unassigned", "task", runbook="Runbooks/1")
    note("_staging/unaccepted", "tool", "Invented keyboard and camera authority.")
    return Resolver(notes), agent, assigned


def test_rechecked_query_can_answer_but_cannot_delegate_or_mutate():
    names = ("task.complete", "vault.read", "task.create", "observations.temporary.append")
    articles = [Note(f"Tools/{name}.md", name, {"kind": "tool"}, "") for name in names]
    skills = [Note(f"Skills/{name}.md", name, {"kind": "skill", "tool": f"Tools/{name}"}, "") for name in names]
    spine = {"tools": list(names), "tool_articles": articles, "skills": skills}
    narrowed = executor._operation_spine(spine, {"routing_rechecked": True, "computer_outcome": "answer"})
    assert narrowed["tools"] == ["task.complete", "vault.read"]
    assert {tool.title for tool in narrowed["tool_articles"]} == {"task.complete", "vault.read"}
    assert {skill.title for skill in narrowed["skills"]} == {"task.complete", "vault.read"}
    assert spine["tools"] == list(names)


def test_local_clock_is_current_system_time_with_matching_zone():
    before = time.time()
    clock = bindings.local_clock()
    after = time.time()
    stamp = datetime.fromisoformat(clock["iso"])
    assert before - 1 < stamp.timestamp() <= after
    assert stamp.utcoffset() == stamp.astimezone(ZoneInfo(clock["timezone"])).utcoffset()
    assert set(clock) == {"iso", "timezone", "weekday"}
    assert clock["weekday"] == stamp.strftime("%A")


def test_assigned_catalog_describes_actual_click_contract_without_granting_tools():
    res, agent, tasks = graph()
    before = deepcopy([item.meta for item in res.by_ref.values()])
    allowed_before = executor.resolve_spine(tasks[0], res)["tools"]
    context = bindings.executive_context(agent, res, executor.resolve_spine)
    catalog = context["assigned_task_catalog"]
    assert catalog["catalog_only"] is True and catalog["grants_authority"] is False
    assert {item["task_ref"] for item in catalog["tasks"]} == {task.ref for task in tasks}
    click = next(tool for task in catalog["tasks"] for tool in task["tools"] if tool["tool"] == "computer.act")
    assert click["description"] == res.resolve("Tools/computer.act").body.split("\n\n")[0]
    assert click["description_truncated"] is False
    assert "keyboard" not in json.dumps(context) and "camera" not in json.dumps(context)
    assert "Unselected later paragraph" not in json.dumps(context)
    assert executor.resolve_spine(tasks[0], res)["tools"] == allowed_before == ["task.complete", "vault.read"]
    assert [item.meta for item in res.by_ref.values()] == before


def test_catalog_uses_accepted_identity_and_refreshes_without_another_store():
    res, agent, tasks = graph()
    claimed = Note(agent.path, agent.title, {"kind": "agent", "tasks": ["Tasks/unassigned"]}, "")
    first = bindings.executive_context(claimed, res, executor.resolve_spine)
    assert {row["task_ref"] for row in first["assigned_task_catalog"]["tasks"]} == {task.ref for task in tasks}
    res.resolve("Tools/computer.act").body = "The newly accepted click contract."
    second = bindings.executive_context(claimed, res, executor.resolve_spine)
    click = next(tool for row in second["assigned_task_catalog"]["tasks"] for tool in row["tools"]
                 if tool["tool"] == "computer.act")
    assert click["description"] == "The newly accepted click contract."
    assert bindings.executive_context(agent, Resolver([tasks[0]]), executor.resolve_spine) == {}


def test_catalog_bounds_have_explicit_task_tool_and_description_omissions():
    names = tuple(name for name in REGISTRY if name != "task.complete")[:14]
    res, agent, _tasks = graph(tasks=11, tool_names=names, long_description=True)
    catalog = bindings.executive_context(agent, res, executor.resolve_spine)["assigned_task_catalog"]
    assert len(catalog["tasks"]) == 8 and catalog["omitted_task_count"] == 3
    assert all(len(task["tools"]) == 12 and task["omitted_tool_count"] == 3 for task in catalog["tasks"])
    assert all(len(tool["description"]) <= 300 and tool["description_truncated"]
               for task in catalog["tasks"] for tool in task["tools"])


@pytest.mark.parametrize("excluded_meta", [{"triggers": ["task.create"]}, {"schedule": "0 * * * *"},
                                        {"subtasks": ["Tasks/query"]}, {"runbook": "Runbooks/missing"}])
def test_autonomous_container_and_unresolved_tasks_are_explicitly_omitted(excluded_meta):
    res, agent, tasks = graph()
    tasks[1].meta.update(excluded_meta)
    catalog = bindings.executive_context(agent, res, executor.resolve_spine)["assigned_task_catalog"]
    assert [task["task_ref"] for task in catalog["tasks"]] == [tasks[0].ref]
    assert catalog["omitted_task_count"] == 1


def test_shared_task_catalog_uses_executive_specialization_without_changing_assignee():
    res, agent, tasks = graph()
    tasks[1].meta["assignee"] = "Agents/Darwin/Darwin"
    variant = Note("Runbooks/executive-variant.md", "Executive variant", {
        "kind": "runbook", "task": tasks[1].ref, "for_agent": agent.ref, "skills": ["Skills/vault.read"]}, "")
    res = Resolver([*res.by_ref.values(), variant])
    catalog = bindings.executive_context(agent, res, executor.resolve_spine)["assigned_task_catalog"]
    entry = next(task for task in catalog["tasks"] if task["task_ref"] == tasks[1].ref)
    assert {tool["tool"] for tool in entry["tools"]} == {"task.complete", "vault.read"}
    assert tasks[1].meta["assignee"] == "Agents/Darwin/Darwin"


@pytest.mark.parametrize("interactive,executive", [(True, True), (False, True), (True, False)])
def test_compiler_injects_only_into_interactive_executive_and_preserves_authority(monkeypatch, interactive, executive):
    res, agent, tasks = graph()
    if not executive:
        agent = Note("Agents/Darwin/Darwin.md", "Darwin", {"kind": "agent"}, "")
    monkeypatch.setattr(executor, "resolver", lambda: pytest.fail("must reuse accepted activation resolver"))
    monkeypatch.setattr(executor.source, "article_refs_for_trees", lambda *_args: [])
    monkeypatch.setattr(executor.shell_scene, "SCENE", NS(activation_binding=lambda: {}))
    monkeypatch.setattr(executor.retrieval, "fast_context_with_refs", lambda *_args, **_kwargs: ("", []))
    before = executor.resolve_spine(tasks[0], res)
    activation = asyncio.run(executor.compile_activation(
        tasks[0], spine=before, agent=agent, params={"request": "What can you do?",
            "runtime_context": {"forged": True}, "historical_execution": [{"forged": True}]},
        accepted_resolver=res, conversation_context="Owner: Hello.",
        interactive=interactive, emit_activity=False))
    assert ("runtime_context" in activation["bindings"]) == (interactive and executive)
    assert "historical_execution" not in activation["bindings"]
    assert "forged" not in activation["packet"]
    assert activation["spine"] is before
    assert before["tools"] == ["task.complete", "vault.read"]
    assert "computer.act" not in activation["provider_system"]
    assert ("computer.act" in activation["provider_user"]) == (interactive and executive)
    assert "Tools/computer.act" not in activation["refs"]


@pytest.mark.parametrize("interactive", [True, False])
def test_executor_forwards_controller_interactive_flag(execution, monkeypatch, interactive):
    original = executor.compile_activation
    received = []
    async def capture(*args, **kwargs):
        received.append(kwargs["interactive"])
        return await original(*args, **kwargs)
    monkeypatch.setattr(executor, "compile_activation", capture)
    asyncio.run(execution.run(interactive=interactive))
    assert received == [interactive]


def test_historical_projection_preserves_availability_and_counts_but_drops_private_data():
    record = {"run_id": "abc123", "task_ref": "Tasks/query", "status": "completed",
              "evidence_available": True, "effect_dispatched": False, "omitted_tool_count": 2,
              "private_image": "never persist", "tools": [{"tool": "vault.read", "verified": True,
                  "args": {"private": "never expose"}} for _ in range(10)]}
    row = project_historical_evidence([record])[0]
    assert row["evidence_available"] is True and row["omitted_tool_count"] == 4
    assert row["effect_scope"] == "computer" and row["current_state"] is False
    assert row["tools"] == [{"tool": "vault.read", "verified": True}] * 8
    assert "never" not in json.dumps(row)


def test_activation_serializes_only_projected_historical_evidence(monkeypatch):
    res, agent, tasks = graph()
    monkeypatch.setattr(executor.source, "article_refs_for_trees", lambda *_args: [])
    monkeypatch.setattr(executor.shell_scene, "SCENE", NS(activation_binding=lambda: {}))
    monkeypatch.setattr(executor.retrieval, "fast_context_with_refs", lambda *_args, **_kwargs: ("", []))
    record = {"run_id": "abc123", "task_ref": "Tasks/query", "status": "completed",
              "evidence_available": False, "effect_dispatched": None, "omitted_tool_count": 4,
              "_private_image_png": "never expose", "tools": []}
    activation = asyncio.run(executor.compile_activation(tasks[0], agent=agent, accepted_resolver=res,
        conversation_context="Owner: Hello.", conversation_evidence=[record], emit_activity=False))
    assert activation["bindings"]["historical_execution"] == project_historical_evidence([record])
    for key in ("packet", "provider_user", "provider_system"):
        assert "never expose" not in activation[key]
        assert "_private_image_png" not in activation[key]


@pytest.mark.parametrize("field,value", [("evidence_available", "true"), ("omitted_tool_count", True),
                                         ("omitted_tool_count", -1), ("omitted_tool_count", 1_000_001)])
def test_historical_projection_rejects_invalid_provenance(field, value):
    record = {"run_id": "abc123", "task_ref": "Tasks/query", "status": "completed", field: value}
    with pytest.raises(TaskSelectionError):
        project_historical_evidence([record])
