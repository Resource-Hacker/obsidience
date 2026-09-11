"""Display ancestry never widens the authoritative Agent access manifest."""
from copy import deepcopy
from obsidience.harness.config import CONFIG
from obsidience.harness.interfaces.api import app as server
from obsidience.harness.knowledge.vault import write_note


def node(ref, kind="knowledge", **fields):
    return {"id": ref, "kind": kind, **fields}


def group(role, refs=()):
    return {"id": role, "root_ref": server.CHECKOUT_AGENTS.get(role, "@library"),
            "subjects": [], "access_refs": list(refs)}


def members(nodes, *groups):
    before = deepcopy((nodes, groups))
    result = server._graph_article_membership(nodes, list(groups))
    assert (nodes, groups) == before
    assert all(refs == sorted(set(refs)) for refs in result.values())
    return {key: set(refs) for key, refs in result.items()}


def test_display_ancestors_do_not_select_siblings_or_new_descendants():
    nodes = [node("Tools/root", "tool", children=["Tools/child", "Tools/sibling"]),
             node("Tools/child", "tool"), node("Tools/sibling", "tool")]
    result = members(nodes, group("executive", ["Tools/child"]))["executive"]
    assert result == {server.CHECKOUT_AGENTS["executive"], "Tools/root", "Tools/child"}
    assert members(nodes, group("executive", ["Tools/root"]))["executive"] == {
        server.CHECKOUT_AGENTS["executive"], "Tools/root"}


def test_canonical_skill_uses_one_display_alias_without_selecting_neighbor():
    nodes = [node("Skills/vault.read", "skill"), node("Skills/vault.write", "skill"),
             node("@library/Skills/vault", "skill", children=["@library/Skills/vault/read", "@library/Skills/vault/write"]),
             node("@library/Skills/vault/read", "skill", article_ref="Skills/vault.read"),
             node("@library/Skills/vault/write", "skill", article_ref="Skills/vault.write")]
    assert members(nodes, group("curator", ["Skills/vault.read"]))["curator"] == {
        server.CHECKOUT_AGENTS["curator"], "Skills/vault.read", "@library/Skills/vault", "@library/Skills/vault/read"}


def test_missing_access_manifest_has_no_implicit_dependency_or_global_knowledge_fallback():
    nodes = [node(server.CHECKOUT_AGENTS["executive"], "agent", dependencies={"tools": ["Tools/read"]}),
             node("Tools/read", "tool"), node("Shared/fact"), node("Agents/Darwin/Observations/private")]
    assert members(nodes, group("executive"))["executive"] == {server.CHECKOUT_AGENTS["executive"]}
    assert members(nodes, group("executive", ["Shared/fact"]))["executive"] == {
        server.CHECKOUT_AGENTS["executive"], "Shared/fact"}


def test_owner_library_contains_all_accepted_content_without_assigning_it():
    nodes = [node("Tools/read", "tool"), node("Skills/read", "skill"), node("Runbooks/read", "runbook"),
             node("Tasks/query", "task"), node("Shared/fact"), node("Agents/Darwin/Observations/private")]
    result = members(nodes, group("library"), group("executive"))
    assert result["library"] == {"@library", *(n["id"] for n in nodes)}
    assert result["executive"] == {server.CHECKOUT_AGENTS["executive"]}


def test_missing_exact_reference_cannot_resolve_by_basename():
    nodes = [node("Tools/other/read", "tool")]
    assert members(nodes, group("executive", ["Tools/missing/read"]))["executive"] == {
        server.CHECKOUT_AGENTS["executive"]}


def test_graph_api_projects_membership_without_writes(monkeypatch, tmp_path, isolated_task_ledger):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    for ref, kind, meta in [
        (server.CHECKOUT_AGENTS["executive"], "agent", {"tasks": ["Tasks/query"], "knowledge": ["[[News & Research/News & Research]]"]}),
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
    assert "Runbooks/private" in groups["library"]["article_refs"]
    assert {path: path.read_bytes() for path in before} == before
    assert list(isolated_task_ledger.db.execute("SELECT * FROM task_runtime")) == runtime_before
