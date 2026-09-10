from copy import deepcopy

from obsidience.harness.config import CONFIG
from obsidience.harness.interfaces.api import app as server
from obsidience.harness.knowledge.vault import write_note


def node(ref, kind="knowledge", **fields):
    return {"id": ref, "kind": kind, **fields}


def group(identity, **fields):
    return {"id": identity, "root_ref": server.CHECKOUT_AGENTS.get(identity, "@library"),
            "subjects": [], **fields}


def members(nodes, *groups):
    before = deepcopy((nodes, groups))
    result = server._graph_article_membership(nodes, list(groups))
    assert (nodes, groups) == before
    assert all(refs == sorted(set(refs)) for refs in result.values())
    return {key: set(refs) for key, refs in result.items()}


def test_selected_descendants_and_ancestors_do_not_select_siblings():
    nodes = [
        node(server.CHECKOUT_AGENTS["executive"], "agent", dependencies={
            "tools": ["[[/Tools/selected.md#Usage|Selected]]", "Tools/child"],
        }),
        node("@library/Tools/root", "tool", children=["Tools/selected", "Tools/sibling"]),
        node("Tools/selected", "tool", children=["Tools/child", "Skills/unrelated"]),
        node("Tools/child", "tool"), node("Tools/sibling", "tool"),
        node("Skills/unrelated", "skill"),
    ]
    assert members(nodes, group("executive"))["executive"] == {
        server.CHECKOUT_AGENTS["executive"], "@library/Tools/root", "Tools/selected", "Tools/child",
    }


def test_physical_skill_checkout_selects_exact_display_alias_and_namespace():
    nodes = [
        node(server.CHECKOUT_AGENTS["curator"], "agent", dependencies={"skills": ["Skills/vault.read"]}),
        node("Skills/vault.read", "skill"), node("Skills/vault.write", "skill"),
        node("@library/Skills/vault", "skill", synthetic=True, children=[
            "@library/Skills/vault/read", "@library/Skills/vault/write",
        ]),
        node("@library/Skills/vault/read", "skill", synthetic=True, article_ref="Skills/vault.read"),
        node("@library/Skills/vault/write", "skill", synthetic=True, article_ref="Skills/vault.write"),
    ]
    assert members(nodes, group("curator"))["curator"] == {
        server.CHECKOUT_AGENTS["curator"], "@library/Skills/vault",
        "@library/Skills/vault/read", "Skills/vault.read",
    }


def test_assigned_specialist_task_includes_taxonomy_but_not_executive_assignments():
    nodes = [
        node(server.CHECKOUT_AGENTS["researcher"], "agent", dependencies={"tasks": ["Tasks/research/distill"]}),
        node(server.CHECKOUT_AGENTS["executive"], "agent"),
        node("@library/Tasks/research", tags=["task-taxonomy"],
             children=["Tasks/research/distill", "Tasks/research/unselected"]),
        node("Tasks/research/distill", "task", assignee="[[/Agents/Darwin/Darwin.md]]"),
        node("Tasks/research/unselected", "task"),
        node("Tasks/executive/unselected", "task", assignee=server.CHECKOUT_AGENTS["executive"]),
    ]
    result = members(nodes, group("researcher"), group("executive"))
    assert result["researcher"] == {
        server.CHECKOUT_AGENTS["researcher"], "@library/Tasks/research", "Tasks/research/distill",
    }
    assert result["executive"] == {server.CHECKOUT_AGENTS["executive"]}


def test_knowledge_scope_is_declared_and_does_not_cross_agent_boundaries():
    nodes = [
        node(server.CHECKOUT_AGENTS["executive"], "agent"),
        node(server.CHECKOUT_AGENTS["researcher"], "agent", source_scope_refs=[
            "Projects/Study/finding", "Agents/Alexandria/private",
        ]),
        node(server.CHECKOUT_AGENTS["curator"], "agent"),
        node("Agents/Executive/Architecture/Architecture"),
        node("Agents/Darwin/Observations/Observations"),
        node("Agents/Alexandria/private"),
        node("ADMECH Workstation/Hardware/Hardware"),
        node("News & Research/Top 10"), node("Projects/Study/finding"),
        node("Projects/Study/unselected"), node("Sources/research"),
        node("Library/private"),
    ]
    darwin = group("researcher", subjects=[{
        "id": "@sat/Darwin/domain", "path": "News & Research",
        "article_ref": "News & Research/News & Research",
    }])
    result = members(nodes, group("executive"), darwin, group("curator"))
    assert result["executive"] == {
        server.CHECKOUT_AGENTS["executive"], "Agents/Executive/Architecture/Architecture",
        "ADMECH Workstation/Hardware/Hardware", "News & Research/Top 10",
        "Projects/Study/finding", "Projects/Study/unselected",
    }
    assert result["researcher"] == {
        server.CHECKOUT_AGENTS["researcher"], "Agents/Darwin/Observations/Observations",
        "News & Research/Top 10", "Projects/Study/finding", "Sources/research", "@sat/Darwin/domain",
    }
    assert result["curator"] == {
        server.CHECKOUT_AGENTS["curator"], "Agents/Alexandria/private",
    }


def test_missing_explicit_child_does_not_resolve_by_shared_basename():
    nodes = [
        node(server.CHECKOUT_AGENTS["executive"], "agent", dependencies={"tools": ["Tools/root"]}),
        node("Tools/root", "tool", children=["Tools/missing/read"]),
        node("Tools/other/read", "tool"),
    ]
    assert members(nodes, group("executive"))["executive"] == {
        server.CHECKOUT_AGENTS["executive"], "Tools/root",
    }


def test_alias_does_not_import_another_agents_physical_article():
    nodes = [
        node(server.CHECKOUT_AGENTS["curator"], "agent", dependencies={
            "skills": ["@library/Skills/private"], "runbooks": ["Agents/Darwin/Runbooks/private"],
        }),
        node("@library/Skills/private", "skill", article_ref="Agents/Darwin/Skills/private"),
        node("Agents/Darwin/Skills/private", "skill"),
        node("Agents/Darwin/Runbooks/private", "runbook"),
    ]
    result = members(nodes, group("curator"), group("library"))
    assert result["curator"] == {server.CHECKOUT_AGENTS["curator"]}
    assert result["library"] == {"@library"}


def test_library_contains_shared_pairs_and_tasks_not_runbooks_or_agent_local_content():
    nodes = [
        node("Tools/vault.read", "tool"), node("Skills/vault.read", "skill"),
        node("@library/Skills/vault/read", "skill", synthetic=True, article_ref="Skills/vault.read"),
        node("@library/Tools/vault", "tool", synthetic=True),
        node("@library/Tasks/research", tags=["task-taxonomy"]),
        node("Tasks/research/distill", "task"), node("Runbooks/research/distill", "runbook"),
        node("Agents/Darwin/Runbooks/private", "runbook"),
        node("Agents/Darwin/Tasks/private", "task"),
        node("Agents/Darwin/private"), node(server.CHECKOUT_AGENTS["researcher"], "agent"),
    ]
    assert members(nodes, group("library"))["library"] == {
        "@library", "@library/Tools/vault", "Tools/vault.read", "Skills/vault.read",
        "@library/Skills/vault/read", "@library/Tasks/research", "Tasks/research/distill",
    }


def test_graph_api_projects_membership_without_writes(monkeypatch, tmp_path, isolated_task_ledger):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    for ref, kind, meta in [
        (server.CHECKOUT_AGENTS["executive"], "agent", {"tasks": ["Tasks/query"]}),
        (server.CHECKOUT_AGENTS["researcher"], "agent", {}),
        ("Tools/vault.read", "tool", {"binding": "capability:vault.read",
            "source": "obsidience/harness/capabilities/vault/read.py"}),
        ("Tools/task.complete", "tool", {"binding": "capability:task.complete",
            "source": "obsidience/harness/capabilities/task/complete.py"}),
        ("Skills/task.complete", "skill", {"tool": "[[Tools/task.complete]]"}),
        ("Tools/vault.write", "tool", {}),
        ("Skills/vault.read", "skill", {"tool": "[[Tools/vault.read]]"}),
        ("Tasks/query", "task", {"runbook": "Runbooks/query"}),
        ("Runbooks/query", "runbook", {"skills": ["Skills/vault.read"]}),
        ("Tasks/custom", "task", {"assignee": server.CHECKOUT_AGENTS["researcher"],
                                  "triggers": ["task.create"]}),
        ("Runbooks/private", "runbook", {}),
        ("News & Research/News & Research", "knowledge", {}),
    ]:
        body = "[An unselected related Tool](/Tools/vault.write.md)." if kind == "agent" else "Article."
        write_note(ref + ".md", {"kind": kind, "title": ref.rsplit("/", 1)[-1], **meta}, body)
    isolated_task_ledger.sync(embed=False)
    before = {path: path.read_bytes() for path in CONFIG.vault_dir.rglob("*.md")}
    runtime_before = list(isolated_task_ledger.db.execute("SELECT * FROM task_runtime"))
    result = server.graph()
    groups = {row["id"]: row for row in result["navigation"]["groups"]}
    assert {"Tools/vault.read", "Skills/vault.read", "@library/Skills/vault/read",
            "@library/Tools/vault", "News & Research/News & Research"} <= set(groups["executive"]["article_refs"])
    assert "Tools/vault.write" not in groups["executive"]["article_refs"]
    assert "Tasks/custom" in groups["researcher"]["article_refs"]
    assert "Runbooks/private" not in groups["library"]["article_refs"]
    assert {path: path.read_bytes() for path in before} == before
    assert list(isolated_task_ledger.db.execute("SELECT * FROM task_runtime")) == runtime_before
