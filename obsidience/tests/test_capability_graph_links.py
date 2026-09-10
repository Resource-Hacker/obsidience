"""Authored capability edges survive the graph's exact Skill mirror projection."""
import json
import re
import subprocess
from pathlib import Path

import pytest

from obsidience.harness.config import CONFIG
from obsidience.harness.knowledge.index import Index
from obsidience.harness.knowledge.vault import write_note


@pytest.mark.parametrize("skill_count", [0, 1, 2])
def test_skill_mirror_publishes_only_an_unambiguous_article_ref(monkeypatch, tmp_path, skill_count):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    monkeypatch.setattr(CONFIG, "db_path", tmp_path / "index.sqlite3")
    monkeypatch.setattr(CONFIG, "git_commit", False)
    write_note("Tools/vault.read.md", {"kind": "tool", "title": "vault.read"}, "Read an Article.")
    for number in range(skill_count):
        ref = "Skills/vault.read" if number == 0 else "Skills/ambiguous"
        write_note(ref + ".md", {
            "kind": "skill", "title": "Using vault.read", "tool": "[[Tools/vault.read]]",
        }, "Use the exact reference.")
    write_note("Runbooks/read.md", {
        "kind": "runbook", "title": "Read", "skills": ["[[Skills/vault.read]]"],
    }, "Read and evaluate the result.")
    index = Index()
    try:
        index.sync(embed=False)
        graph = index.graph()
    finally:
        index.db.close()
    nodes = {node["id"]: node for node in graph["nodes"]}
    assert nodes["@library/Skills/vault/read"].get("article_ref") == (
        "Skills/vault.read" if skill_count == 1 else None
    )
    assert "article_ref" not in nodes["@library/Skills/vault"]
    if skill_count:
        # Canonical authority is not rewritten or duplicated by a UI alias.
        assert {"source": "Skills/vault.read", "target": "Tools/vault.read"} in graph["links"]
        assert {"source": "Runbooks/read", "target": "Skills/vault.read"} in graph["links"]
    assert not any(edge["source"].startswith("@") or edge["target"].startswith("@")
                   for edge in graph["links"])


def test_display_spine_uses_exact_aliases_and_keeps_parent_article_endpoints():
    pane_dir = Path(__file__).parents[1] / "ui/src/renderer/src/panes"
    backdrop = (pane_dir / "graph-backdrop.tsx").read_text()
    endpoint = re.search(r"^function isArticleEndpoint\(.*?^\}", backdrop, re.M | re.S)[0]
    # Execute the existing endpoint guard, not a test-only approximation of it.
    endpoint = endpoint.replace("node: GraphNode", "node").replace("): boolean {", ") {")
    assert "const linkPairs = projectedArticleLinks(graph.links, displayAliases);" in backdrop
    assert 'visibleArticleLinks(linkPairs, executiveArticleIds, "Agents/Executive/Executive",' in backdrop
    assert "visibleArticleLinks(linkPairs, satelliteArticleIds, identityRef," in backdrop
    assert "visibleArticleLinks(linkPairs, libraryArticleIds)" in backdrop
    result = subprocess.run([
        "node", "--experimental-strip-types", "--input-type=module", "-e", f"""
import {{ strict as assert }} from 'node:assert';
import {{ articleDisplayAliases, projectedArticleLinks }} from {json.dumps((pane_dir / 'graph-links.ts').as_uri())};
{endpoint}
const tool = 'Tools/vault.read', skill = 'Skills/vault.read';
const mirror = '@library/Skills/vault/read', runbook = 'Runbooks/read';
const nodes = [
  {{id:tool, kind:'tool'}}, {{id:skill, kind:'skill'}},
  {{id:mirror, kind:'skill', article_ref:skill}},
  {{id:runbook, kind:'runbook'}},
  {{id:'@library/Skills/vault', kind:'skill', children:[mirror]}},
];
const canonical = [{{source:runbook, target:skill}}, {{source:skill, target:tool}}];
const before = JSON.stringify(canonical);
const aliases = articleDisplayAliases(nodes);
const projected = projectedArticleLinks(canonical, aliases);
assert.deepEqual(projected, [{{source:runbook, target:mirror}}, {{source:mirror, target:tool}}]);
assert.equal(JSON.stringify(canonical), before);
// Both Executive and specialist clouds use the same endpoint membership rule.
const agentIds = new Set(nodes.filter(node => node.id !== skill
  && isArticleEndpoint(node)).map(node => node.id));
assert.equal(projected.filter(link => agentIds.has(link.source) && agentIds.has(link.target)).length, 2);
// Partial checkouts do not manufacture an endpoint or execution permission.
agentIds.delete(runbook);
assert.equal(projected.filter(link => agentIds.has(link.source) && agentIds.has(link.target)).length, 1);
// Library still displays the paired Tools shelf, not agent-owned Runbooks.
const libraryIds = new Set([tool]);
assert.equal(projected.filter(link => libraryIds.has(link.source) && libraryIds.has(link.target)).length, 0);
// No basename/title guessing or new links from pairing metadata alone.
const unrelated = [{{source:'Other/vault.read', target:tool}}];
assert.deepEqual(projectedArticleLinks(unrelated, aliases), unrelated);
assert.deepEqual(projectedArticleLinks([], aliases), []);
assert.deepEqual(projectedArticleLinks(canonical, new Map()), canonical);
for (const node of [
  {{id:'Knowledge/index', kind:'knowledge'}},
  {{id:'Knowledge/README', kind:'knowledge'}},
  {{id:'Knowledge/Hub', kind:'knowledge', tags:['index-hub']}},
  {{id:'Runbooks/parent', kind:'runbook', children:[runbook]}},
]) assert(isArticleEndpoint(node), node.id);
assert(!isArticleEndpoint({{id:'Agents/Executive/Executive', kind:'agent'}}));
"""], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_absorbed_article_aliases_do_not_duplicate_hierarchy_or_self_edges():
    module = Path(__file__).parents[1] / "ui/src/renderer/src/panes/graph-links.ts"
    result = subprocess.run([
        "node", "--experimental-strip-types", "--input-type=module", "-e", f"""
import {{strict as assert}} from 'node:assert';
import {{articleDisplayAliases, projectedArticleLinks, visibleArticleLinks, withoutTaxonomyLinks}}
  from {json.dumps(module.as_uri())};
const aliases = articleDisplayAliases([
  {{id:'Knowledge/Topic/Topic'}},
  {{id:'@branch/Knowledge/Topic', article_ref:'Knowledge/Topic/Topic'}},
]);
const links = projectedArticleLinks([
  {{source:'Knowledge/Topic/Topic',target:'Knowledge/Topic/leaf'}},
  {{source:'Knowledge/Topic/leaf',target:'Knowledge/Topic/Topic'}},
  {{source:'Knowledge/Topic/Topic',target:'@branch/Knowledge/Topic'}},
  {{source:'Knowledge/Topic/Topic',target:'Tools/read'}},
],aliases);
const ids = new Set(['@branch/Knowledge/Topic','Knowledge/Topic/leaf','Tools/read']);
const visible = visibleArticleLinks(links,ids);
assert.equal(visible.length,2);
assert.deepEqual(withoutTaxonomyLinks(visible,[
  {{id:'Knowledge/Topic/leaf',parentId:'@branch/Knowledge/Topic'}},
]),[{{source:'@branch/Knowledge/Topic',target:'Tools/read'}}]);
assert.deepEqual(withoutTaxonomyLinks([links[1]],[
  {{id:'Knowledge/Topic/leaf',parentId:'@branch/Knowledge/Topic'}},
]),[]);
"""], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_derived_edges_reach_desktop_clouds_with_agent_scope_and_no_duplicate_lines():
    module = Path(__file__).parents[1] / "ui/src/renderer/src/panes/graph-links.ts"
    result = subprocess.run([
        "node", "--experimental-strip-types", "--input-type=module", "-e", f"""
import {{ strict as assert }} from 'node:assert';
import {{ projectedArticleLinks, visibleArticleLinks }} from {json.dumps(module.as_uri())};
const task = 'Tasks/query', book = 'Runbooks/query', skill = 'Skills/computer.observe';
const tool = 'Tools/computer.observe', mirror = '@library/Skills/computer/observe';
const executive = 'Agents/Executive/Executive', darwin = 'Agents/Darwin/Darwin';
const canonical = [
  {{source:skill, target:tool}},
  {{source:book, target:tool, derived:true, relation:'uses_tool', via:[skill]}},
  {{source:task, target:tool, derived:true, relation:'uses_tool', via:[book, skill], for_agent:darwin}},
  {{source:task, target:tool, derived:true, relation:'uses_tool', via:[book, skill], for_agent:executive}},
];
const before = JSON.stringify(canonical);
const links = projectedArticleLinks(canonical, new Map([[skill, mirror]]));
assert.equal(JSON.stringify(canonical), before);
assert.equal(links[0].source, mirror);
assert.deepEqual(links[1].via, [skill]); // Evidence retains physical Article refs.
const ids = new Set([task, book, mirror, tool]);
const scopeRefs = new Set([...ids, skill]);
for (const owner of [executive, darwin]) {{
  const visible = visibleArticleLinks(links, ids, owner, scopeRefs);
  assert.equal(visible.length, 3);
  assert.equal(visible.find(link => link.source === task).for_agent, owner);
}}
assert.equal(visibleArticleLinks(links, ids, 'Agents/Heimdall/Heimdall', scopeRefs).length, 2);
// Library combines Tool+Skill and Tasks; it gets the derived Task-to-Tool line
// without inventing a shared Runbook node or drawing a line twice per variant.
const library = visibleArticleLinks(links, new Set([task, tool]));
assert.equal(library.length, 1);
assert.equal(library[0].source, task);
assert.equal(library[0].target, tool);
assert.deepEqual(visibleArticleLinks(links, new Set([tool])), []);
// Lines have no arrowheads: inverse authored/applicable bindings still paint
// once, while their directions and evidence remain intact in the API/Reader.
assert.equal(visibleArticleLinks([
  {{source:book, target:task}},
  {{source:task, target:book, derived:true, relation:'governed_by', via:[]}},
], new Set([task, book])).length, 1);
"""], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_activity_and_reader_selection_share_exact_display_identity():
    pane_dir = Path(__file__).parents[1] / "ui/src/renderer/src/panes"
    backdrop = (pane_dir / "graph-backdrop.tsx").read_text()
    activity_body = re.search(
        r"const renderedActivityRefs = useMemo\(\(\) => \{(.*?)^  \},", backdrop, re.M | re.S,
    )[1]
    selection = re.search(r"const selectNode = .*?^  \};", backdrop, re.M | re.S)[0]
    selection = selection.replace("id: string, read: boolean", "id, read")
    assert "buildThinkingRoute(model, renderedActivityRefs)" in backdrop
    assert "buildThinkingRoute(satellite, renderedActivityRefs)" in backdrop
    result = subprocess.run([
        "node", "--experimental-strip-types", "--input-type=module", "-e", f"""
import {{ strict as assert }} from 'node:assert';
import {{ articleDisplayAliases }} from {json.dumps((pane_dir / 'graph-links.ts').as_uri())};
const physical = 'Skills/vault.read', mirror = '@library/Skills/vault/read';
const hub = 'Agents/Executive/Observations/index';
const graph = {{nodes:[
  {{id:mirror, article_ref:physical}},
  {{id:hub, navigation_ref:'@agent/Observations'}},
]}};
const displayAliases = articleDisplayAliases(graph.nodes);
let activity = {{refs:[physical, hub, 'Other/vault.read']}};
const activityRefs = () => {{ {activity_body} }};
assert.deepEqual(activityRefs(), [mirror, '@agent/Observations', 'Other/vault.read']);
activity = null;
assert.deepEqual(activityRefs(), []);
let selected = '', opened = '', selectedGraph = '', readerGraph = '';
const MAIN_GRAPH_ID = 'main';
const parseKnowledgeAgentNodeId = id => id.startsWith('agent:Darwin/')
  ? {{agentId:'Darwin', nodeId:id.slice('agent:Darwin/'.length)}} : {{nodeId:id}};
const setSelectedId = id => {{selected = id;}};
const setNodeMenu = () => {{}};
const selectGraph = id => {{selectedGraph = id;}};
const openReader = (ref, graphId) => {{opened = ref; readerGraph = graphId;}};
{selection}
for (const id of [mirror, 'agent:Darwin/' + mirror]) {{
  opened = '';
  selectNode(id, false);
  assert.equal(selected, id); // Camera/selection retain their displayed identity.
  assert.equal(opened, '');
  selectNode(id, true);
  assert.equal(selected, id);
  assert.equal(opened, physical); // Reader/Source/edit use the actual Article.
  assert.equal(readerGraph, id.startsWith('agent:') ? 'Darwin' : 'main');
}}
assert.equal(selectedGraph, 'Darwin');
selectNode('Tools/vault.read', true);
assert.equal(opened, 'Tools/vault.read');
assert.equal(readerGraph, 'main');
selectNode('@library/Skills/vault', true);
assert.equal(opened, '@library/Skills/vault'); // Real namespace index still opens.
"""], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
