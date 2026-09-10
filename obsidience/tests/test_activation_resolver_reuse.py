from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS

import pytest

from obsidience.harness.conversation.runtime import ConversationRuntime
from obsidience.harness.execution import executor
from obsidience.harness.knowledge import vault
from obsidience.harness.knowledge.vault import Note, Resolver
from obsidience.harness.models import runtime as models
from obsidience.tests.test_execution_cancellation import execution


def test_compiler_reuses_one_resolver_and_preserves_exact_packet_and_refs(monkeypatch):
    agent = Note("Agents/Executive/Executive.md", "Executive", {"kind": "agent"}, "Exact identity")
    task = Note("Tasks/query.md", "Query", {"kind": "task", "assignee": agent.ref}, "Exact Task")
    tool = Note("Tools/vault.read.md", "vault.read", {"kind": "tool"}, "Exact Tool")
    skill = Note("Skills/vault.read.md", "Read", {"kind": "skill", "tool": tool.ref}, "Exact Skill")
    book = Note("Runbooks/query.md", "Answer", {"kind": "runbook"}, "Exact Runbook")
    accepted = Resolver([agent, task, tool, skill, book])
    spine = {"runbooks": [book], "skills": [skill]}
    builds = []
    monkeypatch.setattr(executor, "resolver", lambda **_kwargs: builds.append(True) or accepted)
    monkeypatch.setattr(executor.source, "article_refs_for_trees", lambda *_args: [])
    monkeypatch.setattr(executor.shell_scene, "SCENE", NS(activation_binding=lambda: {}))
    monkeypatch.setattr(executor.retrieval, "fast_context_with_refs", lambda *_args, **_kwargs: ("Exact Knowledge", ["Knowledge/current"]))
    kwargs = dict(spine=spine, agent=agent, params={"request": "Exact Objective"},
                  conversation_context="Exact prior dialogue", emit_activity=False)

    preview = asyncio.run(executor.compile_activation(task, **kwargs))
    assert builds == [True]  # preview builds once, including paired Tool resolution
    builds.clear()
    activation = asyncio.run(executor.compile_activation(task, accepted_resolver=accepted, **kwargs))
    assert builds == []
    for key in ("packet", "provider_system", "provider_user", "refs", "objective", "bindings"):
        assert activation[key] == preview[key]
    assert activation["refs"][:5] == [agent.ref, task.ref, book.ref, skill.ref, tool.ref]
    assert activation["provider_system"].count("Exact Tool") == 1


def test_run_task_passes_its_exact_resolver_to_compiler(execution, monkeypatch):
    accepted = executor.resolver()
    builds = []
    monkeypatch.setattr(executor, "resolver", lambda **_kwargs: builds.append(True) or accepted)
    compile_packet = executor.compile_activation
    received = []

    async def capture(*args, **kwargs):
        received.append(kwargs.get("accepted_resolver"))
        return await compile_packet(*args, **kwargs)

    monkeypatch.setattr(executor, "compile_activation", capture)
    assert asyncio.run(execution.run())["status"] == "completed"
    assert builds == [True]
    assert received == [accepted]


@pytest.mark.parametrize("reference", [None, "Tasks/query", "Tasks/executive/operate"])
def test_context_model_loads_current_canonical_task_without_vault_scan(monkeypatch, reference):
    runtime = ConversationRuntime(NS())
    exact = reference or runtime._last_task_ref
    task = Note(exact + ".md", "Selected", {"kind": "task", "model": models.QWEN_Q8_MODEL,
                "assignee": "[[Agents/Research/Research]]"}, "")
    reads = []
    monkeypatch.setattr(vault, "load_note", lambda path: reads.append(path) or task)
    monkeypatch.setattr(vault, "resolver", lambda: pytest.fail("canonical lookup scanned the Vault"))
    selections = []
    monkeypatch.setattr(models, "resolve_model", lambda model, agent: selections.append((model, agent)) or model)
    assert runtime._context_model(reference) == models.QWEN_Q8_MODEL
    task.meta["model"] = models.EXECUTIVE_MODEL
    assert runtime._context_model(reference) == models.EXECUTIVE_MODEL
    assert reads == [exact + ".md", exact + ".md"]
    assert selections[-1] == (models.EXECUTIVE_MODEL, "Agents/Research/Research")


@pytest.mark.parametrize("reference,matched", [
    ("Query", True), ("tasks/query", True), ("[[Tasks/query]]", True),
    ("Tasks/missing", False), ("Tasks/../../outside", False),
])
def test_context_model_preserves_alias_and_missing_fallback(monkeypatch, reference, matched):
    runtime = ConversationRuntime(NS())
    task = Note("Tasks/query.md", "Query", {"kind": "task", "model": models.QWEN_Q8_MODEL}, "")
    reads, resolutions = [], []
    monkeypatch.setattr(vault, "load_note", lambda path: reads.append(path))
    monkeypatch.setattr(vault, "resolver", lambda: NS(resolve=lambda ref: resolutions.append(ref) or (task if matched else None)))
    monkeypatch.setattr(models, "resolve_model", lambda model, _agent: model)
    monkeypatch.setattr(models, "configured_spec", lambda model: model)
    assert runtime._context_model(reference) == (models.QWEN_Q8_MODEL if matched else models.EXECUTIVE_MODEL)
    assert resolutions == [reference]
    assert reads == (["Tasks/missing.md"] if reference == "Tasks/missing" else [])
