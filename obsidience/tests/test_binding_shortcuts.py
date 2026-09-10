from pathlib import Path

import pytest

from obsidience.harness.config import CONFIG
from obsidience.harness.knowledge.vault import expand_primitive, resolver, write_note


@pytest.fixture
def binding_vault(tmp_path, monkeypatch, isolated_task_ledger):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    return isolated_task_ledger


def note(ref, kind, *, body="Article.", **meta):
    write_note(ref + ".md", {"kind": kind, "title": Path(ref).name, **meta}, body)


def pair(name):
    note("Tools/" + name, "tool", binding="capability:" + name,
         source="obsidience/harness/capabilities/" + name.replace(".", "/") + ".py")
    note("Skills/" + name, "skill", tool="[[Tools/" + name + "]]")


def basic():
    note("Agents/Executive/Executive", "agent")
    pair("vault.read")
    note("Runbooks/main", "runbook", skills=["[[Skills/vault.read]]"],
         for_agent="[[Agents/Executive/Executive]]")
    note("Tasks/example", "task", runbook="[[Runbooks/main]]",
         assignee="[[Agents/Executive/Executive]]")


def graph(ledger):
    ledger.sync(embed=False)
    return ledger.graph()


def derived(document, source=None, target=None):
    return [edge for edge in document["links"] if edge.get("derived")
            and (source is None or edge["source"] == source)
            and (target is None or edge["target"] == target)]


def test_graph_explains_exact_typed_spine_and_preserves_stored_links(binding_vault):
    basic()
    binding_vault.sync(embed=False)
    stored_before = list(binding_vault.db.execute("SELECT ref,links FROM notes ORDER BY ref"))
    document = binding_vault.graph()
    assert derived(document) == [
        {"source": "Runbooks/main", "target": "Tools/vault.read", "derived": True,
         "relation": "uses_tool", "via": ["Skills/vault.read"],
         "for_agent": "Agents/Executive/Executive"},
        {"source": "Tasks/example", "target": "Skills/vault.read", "derived": True,
         "relation": "requires_skill", "via": ["Runbooks/main"],
         "for_agent": "Agents/Executive/Executive"},
        {"source": "Tasks/example", "target": "Tools/vault.read", "derived": True,
         "relation": "uses_tool", "via": ["Runbooks/main", "Skills/vault.read"],
         "for_agent": "Agents/Executive/Executive"},
    ]
    assert {"source": "Tasks/example", "target": "Runbooks/main"} in document["links"]
    assert {"source": "Skills/vault.read", "target": "Tools/vault.read"} in document["links"]
    assert list(binding_vault.db.execute("SELECT ref,links FROM notes ORDER BY ref")) == stored_before
    assert binding_vault.graph() == document


def test_body_links_never_become_binding_shortcuts(binding_vault):
    pair("vault.read")
    note("Runbooks/main", "runbook", body="Read [the Skill](/Skills/vault.read.md).")
    note("Tasks/example", "task", body="Discuss [the Runbook](/Runbooks/main.md).")
    document = graph(binding_vault)
    assert {"source": "Runbooks/main", "target": "Skills/vault.read"} in document["links"]
    assert {"source": "Tasks/example", "target": "Runbooks/main"} in document["links"]
    assert derived(document) == []


def test_ancestor_runbook_skills_are_inherited_without_sibling_bindings(binding_vault):
    from obsidience.harness.execution.executor import _expand_primitive, resolve_spine

    assert _expand_primitive is expand_primitive
    for name in ("vault.read", "vault.search", "web.fetch", "task.complete"):
        pair(name)
    note("Runbooks/family", "runbook", subrunbooks=["[[Runbooks/child]]", "[[Runbooks/sibling]]"],
         skills=["[[Skills/vault.search]]"])
    note("Runbooks/child", "runbook", skills=["[[Skills/vault.read]]"])
    note("Runbooks/sibling", "runbook", skills=["[[Skills/web.fetch]]"])
    note("Tasks/example", "task", runbook="[[Runbooks/child]]")
    document = graph(binding_vault)
    shared, = derived(document, "Tasks/example", "Tools/vault.search")
    assert shared["via"] == ["Runbooks/child", "Runbooks/family", "Skills/vault.search"]
    inherited, = derived(document, "Runbooks/child", "Tools/vault.search")
    assert inherited["via"] == ["Runbooks/family", "Skills/vault.search"]
    assert derived(document, "Tasks/example", "Tools/web.fetch") == []
    assert derived(document, "Runbooks/child", "Tools/web.fetch") == []
    assert derived(document, "Runbooks/family", "Tools/web.fetch")
    res = resolver()
    spine = resolve_spine(res.resolve("Tasks/example"), res)
    assert spine["tools"] == ["task.complete", "vault.read", "vault.search"]
    # The existing interpreter floor is a Task dependency, not an authored Runbook edge.
    completion, = derived(document, "Tasks/example", "Tools/task.complete")
    assert completion["via"] == ["Skills/task.complete"]
    assert derived(document, "Runbooks/child", "Tools/task.complete") == []


def test_skill_container_expands_only_its_leaf_pairings(binding_vault):
    for name in ("vault.read", "vault.search"):
        pair(name)
    note("Skills/family", "skill", subskills=["[[Skills/vault.read]]", "[[Skills/vault.search]]"])
    note("Runbooks/main", "runbook", skills=["[[Skills/family]]"])
    note("Tasks/example", "task", runbook="[[Runbooks/main]]")
    document = graph(binding_vault)
    edge, = derived(document, "Tasks/example", "Tools/vault.read")
    assert edge["via"] == ["Runbooks/main", "Skills/family", "Skills/vault.read"]
    edge, = derived(document, "Tasks/example", "Skills/vault.search")
    assert edge["via"] == ["Runbooks/main", "Skills/family"]
    note("Runbooks/main", "runbook", skills=["[[Skills/vault.read]]"])
    document = graph(binding_vault)
    assert derived(document, "Tasks/example", "Tools/vault.search") == []


@pytest.mark.parametrize("invalid", ["duplicate", "plural", "multiple", "wrong_kind", "basename", "ambiguous_path"])
def test_invalid_or_ambiguous_pairings_never_create_shortcuts(binding_vault, invalid):
    basic()
    if invalid == "duplicate":
        note("Skills/duplicate", "skill", tool="[[Tools/vault.read]]")
    elif invalid == "plural":
        note("Skills/vault.read", "skill", tools=["[[Tools/vault.read]]"], tool="[[Tools/vault.read]]")
    elif invalid == "multiple":
        pair("vault.search")
        note("Skills/vault.read", "skill", tool=["[[Tools/vault.read]]", "[[Tools/vault.search]]"])
    elif invalid == "wrong_kind":
        note("Tools/vault.read", "knowledge")
    elif invalid == "basename":
        note("Skills/vault.read", "skill", tool="vault.read")
    elif invalid == "ambiguous_path":
        note("Tools/VAULT.READ", "tool")
    assert derived(graph(binding_vault)) == []


@pytest.mark.parametrize("field", ["runbook", "skills"])
def test_titles_or_basenames_are_not_authoritative_paths(binding_vault, field):
    basic()
    if field == "runbook":
        note("Tasks/example", "task", runbook="main")
        assert derived(graph(binding_vault), "Tasks/example") == []
    else:
        note("Runbooks/main", "runbook", skills=["vault.read"])
        assert derived(graph(binding_vault)) == []


def test_generated_variants_preserve_agent_scope_without_claiming_selected_execution(binding_vault):
    basic()
    note("Agents/Darwin/Darwin", "agent")
    note("Agents/Heimdall/Heimdall", "agent")
    # Applicability does not require adding checkout authority to either Agent.
    for agent in ("Darwin", "Heimdall"):
        note(f"Runbooks/Generated/{agent}/example", "runbook", task="[[Tasks/example]]",
             for_agent=f"[[Agents/{agent}/{agent}]]", skills=["[[Skills/vault.read]]"])
    document = graph(binding_vault)
    tool_edges = derived(document, "Tasks/example", "Tools/vault.read")
    assert {edge["for_agent"] for edge in tool_edges} == {
        "Agents/Executive/Executive", "Agents/Darwin/Darwin", "Agents/Heimdall/Heimdall",
    }
    generated, = derived(document, "Tasks/example", "Runbooks/Generated/Darwin/example")
    assert generated == {"source": "Tasks/example", "target": "Runbooks/Generated/Darwin/example",
                         "derived": True, "relation": "governed_by", "via": [],
                         "for_agent": "Agents/Darwin/Darwin"}
    assert {"source": "Runbooks/Generated/Darwin/example", "target": "Tasks/example"} in document["links"]


@pytest.mark.parametrize("via_parent", [False, True, "active"])
def test_shared_unscoped_procedure_shortcuts_follow_real_agent_task_membership(binding_vault, via_parent):
    for name in ("vault.read", "task.complete"):
        pair(name)
    note("Agents/Darwin/Darwin", "agent")
    note("Runbooks/shared", "runbook", skills=["Skills/vault.read"])
    note("Tasks/shared", "task", assignee="Agents/Darwin/Darwin", runbook="Runbooks/shared")
    note("Tasks/excluded", "task", runbook="Runbooks/shared")
    note("Tasks/parent", "task", subtasks=["Tasks/shared", "Tasks/excluded"], exclude_subtasks=["Tasks/excluded"])
    note("Agents/Executive/Executive", "agent", tasks=[] if via_parent == "active" else ["Tasks/parent" if via_parent else "Tasks/shared"])
    if via_parent == "active":
        note("Tasks/parent", "task", assignee="Agents/Executive/Executive", status="pending",
             subtasks=["Tasks/shared", "Tasks/excluded"], exclude_subtasks=["Tasks/excluded"])
    document = graph(binding_vault)
    shared_edges = derived(document, "Tasks/shared", "Tools/vault.read")
    assert {edge.get("for_agent") for edge in shared_edges} == {
        "Agents/Darwin/Darwin", "Agents/Executive/Executive",
    }
    assert any(edge.get("for_agent") == "Agents/Executive/Executive"
               for edge in derived(document, "Tasks/shared", "Skills/task.complete"))
    assert not any(edge.get("for_agent") == "Agents/Executive/Executive"
                   for edge in derived(document, "Tasks/excluded"))


def test_shortest_witness_is_deterministic_per_pair_and_scope(binding_vault):
    basic()
    note("Runbooks/earlier", "runbook", task="[[Tasks/example]]", skills=["[[Skills/vault.read]]"],
         for_agent="[[Agents/Executive/Executive]]")
    document = graph(binding_vault)
    edge, = derived(document, "Tasks/example", "Tools/vault.read")
    assert edge["via"] == ["Runbooks/earlier", "Skills/vault.read"]
    note("Runbooks/earlier", "runbook", task="[[Tasks/example]]", subrunbooks=["[[Runbooks/deeper]]"],
         for_agent="[[Agents/Executive/Executive]]")
    note("Runbooks/deeper", "runbook", skills=["[[Skills/vault.read]]"])
    edge, = derived(graph(binding_vault), "Tasks/example", "Tools/vault.read")
    assert edge["via"] == ["Runbooks/earlier", "Runbooks/deeper", "Skills/vault.read"]


def test_direct_same_direction_edge_wins_and_binding_removal_retracts_shortcuts(binding_vault):
    basic()
    note("Tasks/example", "task", runbook="[[Runbooks/main]]",
         body="Read [the Tool](/Tools/vault.read.md).")
    document = graph(binding_vault)
    assert {"source": "Tasks/example", "target": "Tools/vault.read"} in document["links"]
    assert derived(document, "Tasks/example", "Tools/vault.read") == []
    assert derived(document, "Runbooks/main", "Tools/vault.read")
    note("Runbooks/main", "runbook")
    document = graph(binding_vault)
    assert derived(document) == []
    assert {"source": "Tasks/example", "target": "Tools/vault.read"} in document["links"]


def test_cyclic_hierarchy_and_direct_tool_grants_do_not_create_derived_authority(binding_vault):
    basic()
    note("Runbooks/main", "runbook", subrunbooks=["[[Runbooks/main]]"], skills=["[[Skills/vault.read]]"])
    assert derived(graph(binding_vault)) == []
    note("Runbooks/main", "runbook", skills=["[[Skills/vault.read]]"], tools=["[[Tools/vault.read]]"])
    assert derived(graph(binding_vault)) == []


def test_shared_expansion_paths_choose_shortest_hierarchy_witness(binding_vault):
    note("Runbooks/root", "runbook", subrunbooks=["[[Runbooks/long]]", "[[Runbooks/leaf]]"])
    note("Runbooks/long", "runbook", subrunbooks=["[[Runbooks/leaf]]"])
    note("Runbooks/leaf", "runbook")
    res = resolver()
    paths = {}
    notes, error = expand_primitive(res.resolve("Runbooks/root"), res, "runbook", paths=paths)
    assert error is None
    assert [note.ref for note in notes] == ["Runbooks/root", "Runbooks/long", "Runbooks/leaf"]
    assert paths["Runbooks/leaf"] == ["Runbooks/root", "Runbooks/leaf"]
