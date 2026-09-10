"""Library's Knowledge explorer is the canonical graph, not a second file tree."""
import json
import re
import subprocess
from pathlib import Path


def _projection_functions() -> str:
    source = (
        Path(__file__).parents[1] / "shell/qml/panes/knowledge/KnowledgePane.qml"
    ).read_text()
    return "\n".join(
        re.search(rf"^    function {name}\([^\n]*\) \{{.*?^    \}}", source, re.M | re.S)[0]
        for name in (
            "cleanRef", "graphMap", "graphNode", "projectionRoots", "buildFileTree",
            "subjectTree", "subjectByTitle", "groupFiles", "countRefs", "buildGroups",
        )
    )


def test_library_uses_one_canonical_paired_tool_and_task_hierarchy():
    result = subprocess.run([
        "node", "--input-type=module", "-e", f"""
import {{ strict as assert }} from 'node:assert';
import vm from 'node:vm';
const tool = 'Tools/web.fetch', skill = 'Skills/web.fetch';
const task = 'Tasks/research/distill';
const privateTool = 'Agents/Darwin/Tools/private.fetch';
const privateTask = 'Agents/Darwin/Tasks/private';
const nodes = [
  {{id:tool, title:'web.fetch', kind:'tool', children:[]}},
  {{id:skill, title:'Using web.fetch', kind:'skill', children:[]}},
  {{id:task, title:'Distill', kind:'task', children:[]}},
  {{id:'@library/Tools/web', title:'Web', kind:'tool', synthetic:true,
    tags:['tool-namespace'], children:[tool,privateTool]}},
  {{id:'@library/Skills/web', title:'Web', kind:'skill', synthetic:true,
    tags:['skill-tool-mirror'], children:['@library/Skills/web/fetch']}},
  {{id:'@library/Skills/web/fetch', title:'fetch', kind:'skill', synthetic:true,
    article_ref:skill, children:[]}},
  {{id:'@library/Tasks/research', title:'Research', kind:'knowledge', synthetic:true,
    tags:['task-taxonomy'], children:[task,privateTask]}},
  {{id:privateTool, title:'Private fetch', kind:'tool', children:[]}},
  {{id:privateTask, title:'Private Task', kind:'task', children:[]}},
  {{id:'Agents/Darwin/Tasks/another', title:'Another private Task', kind:'task', children:[]}},
  {{id:'Runbooks/research/distill', title:'Research procedure', kind:'runbook', children:[]}}
];
const state = {{graphNodes:nodes, files:[
  {{ref:tool, path:tool+'.md', title:'web.fetch', kind:'tool'}},
  {{ref:skill, path:skill+'.md', title:'Using web.fetch', kind:'skill'}},
  {{ref:task, path:task+'.md', title:'Distill', kind:'task'}},
  {{ref:'Tasks/raw-only', path:'Tasks/raw-only.md', title:'Unprojected file', kind:'task'}}
], navigation:{{groups:[{{id:'library', title:'Shared library', root_ref:'@library',
  article_refs:[tool,skill,task,'@library/Tools','@library/Tasks',
    '@library/Tools/web','@library/Tasks/research','@library/Skills/web','@library/Skills/web/fetch'],
  role:'library', subtitle:'Shared assets', subjects:[
    {{id:'@library/Tools', title:'Callable pairs', parent_id:null}},
    {{id:'@library/Tasks', title:'Reusable work', parent_id:null}}
  ]}}]}}, expandedPaths:{{}}, revealSelection() {{}}, rebuildRows() {{}}}};
state.root = state;
vm.createContext(state);
vm.runInContext({json.dumps(_projection_functions())}, state);
function snapshot() {{
  state.buildGroups();
  return JSON.parse(JSON.stringify(state.groups[0]));
}}
const group = snapshot();
assert.equal(group.label, 'Shared library');
assert.deepEqual(group.tree.map(row => [row.ref, row.name]), [
  ['@library/Tools','Callable pairs'], ['@library/Tasks','Reusable work']
]); // Navigation owns names and shelf identities; no raw Tools/Skills/Tasks append.
assert.deepEqual(group.tree[0].children.map(row => [row.ref, row.name]), [
  ['@library/Tools/web','Web']
]); // A Tool represents its paired Skill, matching the Library graph/card.
assert.deepEqual(group.tree[0].children[0].children.map(row => row.ref), [tool]);
assert.deepEqual(group.tree[1].children.map(row => [row.ref, row.name]), [
  ['@library/Tasks/research','Research']
]); // Knowledge-kind Task taxonomy indexes must not disappear or flatten.
assert.deepEqual(group.tree[1].children[0].children.map(row => row.ref), [task]);
const flatten = rows => rows.flatMap(row => [row, ...flatten(row.children || [])]);
const refs = flatten(group.tree).map(row => row.ref);
assert.equal(new Set(refs).size, refs.length);
assert.equal(refs.filter(ref => ref === tool).length, 1);
assert.equal(refs.filter(ref => ref === task).length, 1);
assert.equal(refs.some(ref => ref.startsWith('Skills/') || ref.startsWith('@library/Skills')), false);
assert.equal(refs.includes('Tasks/raw-only'), false);
assert.equal(refs.includes('Runbooks/research/distill'), false);
assert.equal(refs.some(ref => ref.startsWith('Agents/')), false); // Neither roots nor descendants bypass membership.
assert.equal(group.count, 2); // Physical accepted Articles, not generated indexes.
assert.deepEqual(snapshot(), group); // Repeated refresh must not accumulate duplicates.
state.files = [];
assert.deepEqual(snapshot(), group); // Raw Source/file inventory is not Library truth.
delete state.navigation.groups[0].article_refs;
assert.deepEqual(snapshot().tree.map(row => row.children), [[],[]]); // No inferred membership fallback.
state.navigation.groups[0].subjects = [];
assert.deepEqual(snapshot().tree, []); // No invented shelves when navigation is absent.
"""], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_canonical_research_articles_project_only_four_real_library_tasks(
    tmp_path, monkeypatch, isolated_task_ledger,
):
    from obsidience.harness.config import CONFIG

    canonical = Path(__file__).parents[1] / "vault/Tasks/research"
    expected = [
        ("Tasks/research/question", "Question"),
        ("Tasks/research/learn", "Learn"),
        ("Tasks/research/distill", "Distill"),
        ("Tasks/research/model", "Model"),
    ]
    assert {path.stem for path in canonical.glob("*.md")} == {
        ref.rsplit("/", 1)[-1] for ref, _title in expected
    }
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    destination = CONFIG.vault_dir / "Tasks/research"
    destination.mkdir(parents=True)
    for path in canonical.glob("*.md"):
        (destination / path.name).write_bytes(path.read_bytes())

    isolated_task_ledger.sync(embed=False)
    graph = isolated_task_ledger.graph()
    nodes = {node["id"]: node for node in graph["nodes"]}
    research = nodes["@library/Tasks/research"]
    assert research["children"] == [ref for ref, _title in expected]
    assert [(ref, nodes[ref]["title"]) for ref in research["children"]] == expected
    assert all(nodes[ref]["kind"] == "task" and not nodes[ref].get("synthetic")
               for ref, _title in expected)
    assert "Tasks/research/news" not in nodes
    assert "@library/Tasks/research/news" not in nodes

    result = subprocess.run([
        "node", "--input-type=module", "-e", f"""
import {{ strict as assert }} from 'node:assert';
import vm from 'node:vm';
const state = {{graphNodes:{json.dumps(graph['nodes'])}}};
state.root = state;
vm.createContext(state);
vm.runInContext({json.dumps(_projection_functions())}, state);
const expected = {json.dumps(expected)};
const allowed = ['@library/Tasks/research', ...expected.map(row => row[0])];
const tree = JSON.parse(JSON.stringify(state.projectionRoots(
  ['@library/Tasks/research'], 'Tasks', allowed
)));
assert.equal(tree.length, 1);
assert.equal(tree[0].name, 'Research');
assert.deepEqual(tree[0].children.map(row => [row.ref,row.name]), expected);
assert(tree[0].children.every(row => row.kind === 'task' && row.children.length === 0));
"""], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
