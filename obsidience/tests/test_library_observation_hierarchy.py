"""Library grouping follows graph children while execution identities stay exact."""

import json
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from obsidience.harness.capabilities import registry
from obsidience.harness.config import CONFIG
from obsidience.harness.interfaces.api import app as api
from obsidience.harness.knowledge import skills, tasks, vault
from obsidience.harness.knowledge.dependencies import paired_leaf_skills
from test_native_library_tree import _projection_functions


CALLABLES = ("observations.temporary.append", "observations.temporary.archive")
TASKS = {
    "observations/compact": "Tasks/observations/immediate/compact",
    "observations/promote": "Tasks/observations/durable/promote",
}


@pytest.fixture
def library(tmp_path, monkeypatch, isolated_task_ledger):
    canonical = Path(__file__).parents[1] / "vault"
    refs = [*(f"{kind}/{name}" for name in CALLABLES for kind in ("Tools", "Skills")), *TASKS.values()]
    material = {ref: (canonical / (ref + ".md")).read_bytes() for ref in refs}
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    monkeypatch.setattr(CONFIG, "git_commit", False)
    for ref, content in material.items():
        path = CONFIG.vault_dir / (ref + ".md")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    vault.write_note("Tools/example.deep.read.md", {"kind": "tool", "title": "example.deep.read"}, "Unrelated nested callable.")
    vault.write_note("Skills/example.deep.read.md", {
        "kind": "skill", "title": "Nested guidance", "tool": "[[Tools/example.deep.read]]",
    }, "Keep this namespace depth.")
    isolated_task_ledger.sync(embed=False)
    return isolated_task_ledger, material


def _mirror(name):
    return "@library/Skills/" + name.replace(".", "/")


@pytest.mark.parametrize("name,expected", [
    ("observations.temporary.append", "observations"),
    ("observations.temporary.archive", "observations"),
    ("example.deep.read", "example.deep"),
    ("other.temporary.append", "other.temporary"),
    ("observations.temporary_history.read", "observations.temporary_history"),
    ("observations.temporary.deep.read", "observations.temporary.deep"),
])
def test_display_namespace_exception_is_exact(name, expected):
    assert skills.callable_namespace(name) == expected


def test_index_places_observation_callables_and_skills_directly_under_observations(library):
    graph = library[0].graph()
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert len(nodes) == len(graph["nodes"])
    tool_refs = sorted("Tools/" + name for name in CALLABLES)
    skill_refs = sorted(_mirror(name) for name in CALLABLES)
    assert nodes["@library/Tools/observations"]["children"] == tool_refs
    assert nodes["@library/Skills/observations"]["children"] == skill_refs
    assert "@library/Tools/observations.temporary" not in nodes
    assert "@library/Skills/observations/temporary" not in nodes
    for name in CALLABLES:
        assert nodes[_mirror(name)]["article_ref"] == "Skills/" + name
        assert nodes[_mirror(name)]["children"] == []
        assert {"source": "Skills/" + name, "target": "Tools/" + name} in graph["links"]
        for ref in ("Tools/" + name, _mirror(name)):
            parents = [node["id"] for node in nodes.values() if ref in node["children"]]
            expected = "@library/Tools/observations" if ref.startswith("Tools/") else "@library/Skills/observations"
            assert parents == [expected]
    assert nodes["@library/Tools/example"]["children"] == ["@library/Tools/example.deep"]
    assert nodes["@library/Tools/example.deep"]["children"] == ["Tools/example.deep.read"]
    assert nodes["@library/Skills/example"]["children"] == ["@library/Skills/example/deep"]
    assert nodes["@library/Skills/example/deep"]["children"] == [_mirror("example.deep.read")]
    assert all(child in nodes and child != node["id"] for node in nodes.values() for child in node["children"])


def test_reader_uses_same_direct_children_and_preserves_canonical_guidance(library):
    tool_parent = api.get_article("@library/Tools/observations")
    skill_parent = api.get_article("@library/Skills/observations")
    assert tool_parent["children"] == sorted("Tools/" + name for name in CALLABLES)
    assert skill_parent["children"] == sorted(_mirror(name) for name in CALLABLES)
    assert tool_parent["meta"]["articles"] == skill_parent["meta"]["articles"] == "2"
    for name in CALLABLES:
        mirror = api.get_article(_mirror(name))
        assert mirror["ref"] == _mirror(name)
        assert mirror["meta"]["tool"] == "Tools/" + name
        assert mirror["meta"]["source_skills"] == "Skills/" + name
        assert vault.load_note("Skills/" + name + ".md").body.strip() in mirror["body"]
        assert api.get_article("Tools/" + name)["ref"] == "Tools/" + name
    for ref in ("@library/Tools/observations.temporary", "@library/Skills/observations/temporary"):
        with pytest.raises(HTTPException) as caught:
            api.get_article(ref)
        assert caught.value.status_code == 404
    assert api.get_article("@library/Tools/example")["children"] == ["@library/Tools/example.deep"]
    assert api.get_article("@library/Skills/example")["children"] == ["@library/Skills/example/deep"]


def test_task_display_paths_flatten_without_changing_canonical_task_identity(library):
    nodes = {node["id"]: node for node in library[0].graph()["nodes"]}
    expected = list(TASKS.values())
    assert nodes["@library/Tasks/observations"]["children"] == expected
    assert api.get_article("@library/Tasks/observations")["children"] == expected
    assert set(path for path in tasks.TASK_TAXONOMY_BY_PATH if path.startswith("observations/")) == set(TASKS)
    for path, ref in TASKS.items():
        assert tasks.CANONICAL_TASK_BY_PATH[path] == ref
        assert api.TASK_TAXONOMY_PATH_BY_REF[ref] == path
        note = vault.load_note(ref + ".md")
        assert note.meta["taxonomy_path"] == path
        assert nodes[ref]["kind"] == "task" and not nodes[ref].get("synthetic")
        assert nodes[ref]["children"] == []
        assert [node["id"] for node in nodes.values() if ref in node["children"]] == ["@library/Tasks/observations"]
        assert api.get_article(ref)["ref"] == ref
        assert "@library/Tasks/" + path not in nodes
    assert nodes[TASKS["observations/promote"]]["triggers"] == ["observations.temporary.ready"]
    assert all("@library/Tasks/observations/" + suffix not in nodes for suffix in ("immediate", "temporary", "durable"))


def test_projection_keeps_exact_tool_binding_guidance_and_accepted_bytes(library):
    ledger, material = library
    res = vault.resolver()
    for name in CALLABLES:
        tool = res.resolve("Tools/" + name)
        assert tool.title == name
        assert tool.meta["binding"] == registry.binding(name) == "capability:" + name
        assert tool.meta["source"] == registry.source(name)
        assert [note.ref for note in paired_leaf_skills(tool, res)] == ["Skills/" + name]
    ledger.graph()
    api.get_article("@library/Tools/observations")
    api.get_article("@library/Skills/observations")
    api.get_article("@library/Tasks/observations")
    assert all((CONFIG.vault_dir / (ref + ".md")).read_bytes() == content for ref, content in material.items())
    assert ledger.db.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
    assert ledger.db.execute("SELECT COUNT(*) FROM task_runtime").fetchone()[0] == 0


def test_native_projection_uses_real_children_not_preserved_leaf_path_segments(library):
    graph = library[0].graph()
    allowed = [node["id"] for node in graph["nodes"]]
    expected = {
        "Tools": sorted("Tools/" + name for name in CALLABLES),
        "Skills": sorted(_mirror(name) for name in CALLABLES),
        "Tasks": list(TASKS.values()),
    }
    result = subprocess.run([
        "node", "--input-type=module", "-e", f"""
import {{strict as assert}} from 'node:assert';
import vm from 'node:vm';
const state = {{graphNodes:{json.dumps(graph['nodes'])}}};
state.root = state;
vm.createContext(state);
vm.runInContext({json.dumps(_projection_functions())}, state);
const expected = {json.dumps(expected)}, allowed = {json.dumps(allowed)};
for (const [shelf, children] of Object.entries(expected)) {{
  // Request leaves, including stable /observations/temporary/ Skill IDs.
  // The real graph parent map must produce exactly one Observations parent.
  const tree = JSON.parse(JSON.stringify(state.projectionRoots(children, shelf, allowed)));
  assert.equal(tree.length, 1);
  assert.equal(tree[0].ref, '@library/' + shelf + '/observations');
  assert.equal(tree[0].name, 'Observations');
  assert.deepEqual(tree[0].children.map(row => row.ref), children);
  assert(tree[0].children.every(row => row.children.length === 0 && !row.folder));
  const refs = [tree[0].ref, ...tree[0].children.map(row => row.ref)];
  assert.equal(new Set(refs).size, refs.length);
  assert.deepEqual(JSON.parse(JSON.stringify(state.projectionRoots(children, shelf, allowed))), tree);
}}
"""], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
