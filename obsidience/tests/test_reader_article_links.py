"""Reader link navigation consumes the graph, including exact display aliases."""
import json
import re
import subprocess
from pathlib import Path


def test_reader_connections_follow_canonical_edges_and_selection_lifecycle():
    source = (Path(__file__).parents[1] / "shell/qml/panes/reader/ReaderPane.qml").read_text()
    functions = "\n".join(
        re.search(rf"^    function {name}\([^\n]*\) \{{.*?^    \}}", source, re.M | re.S)[0]
        for name in ("articleLabel", "articleConnections", "resetDocument", "loadDocument", "loadArticleTitles")
    )
    result = subprocess.run([
        "node", "--input-type=module", "-e", f"""
import {{ strict as assert }} from 'node:assert';
import vm from 'node:vm';
const requests = [];
class Request {{
  static DONE = 4;
  open(method, url) {{ this.url = url; }}
  send() {{ requests.push(this); }}
  respond(data) {{ this.status = 200; this.readyState = 4;
    this.responseText = JSON.stringify(data); this.onreadystatechange(); }}
}}
const tool = 'Tools/vault.read', skill = 'Skills/vault.read', book = 'Runbooks/curate';
const mirror = '@library/Skills/vault/read';
const graph = {{nodes:[
  {{id:tool, title:'vault.read', kind:'tool'}},
  {{id:skill, title:'Using vault.read', kind:'skill'}},
  {{id:book, title:'Curate', kind:'runbook'}},
  {{id:mirror, title:'Read', kind:'skill', article_ref:skill}}
], links:[{{source:skill, target:tool}}, {{source:book, target:skill}},
  {{source:skill, target:tool}}, {{source:skill, target:skill}},
  {{source:skill, target:'Missing'}}], navigation:{{groups:[]}}}};
const state = {{XMLHttpRequest:Request, feedItemMode:false, feedItemId:'', sourceMode:false, sourceKey:'',
  previewMode:false, previewItem:{{}}, selectionKind:'article',
  articleRef:tool, graphId:'', requestGeneration:0}};
state.root = state;
vm.createContext(state);
vm.runInContext({json.dumps(functions)}, state);
const refs = incoming => Array.from(state.articleConnections(incoming), item => item.ref);
state.loadDocument();
requests.at(-2).respond(graph); // Graph can arrive before the Article.
requests.at(-1).respond({{ref:tool, title:'vault.read', kind:'tool', body:'Read'}});
assert.deepEqual(refs(true), [skill]);
assert.deepEqual(refs(false), []);
state.articleRef = mirror;
state.loadDocument();
assert.deepEqual(refs(true), []); // No prior selection's links while loading.
requests.at(-1).respond({{ref:mirror, title:'Read', kind:'skill', body:'Use'}});
requests.at(-2).respond(graph); // Article can also arrive before the graph.
assert.deepEqual(refs(true), [book]);
assert.deepEqual(refs(false), [tool]); // Exact, deduplicated, resolved and non-self.
state.articleRef = skill;
state.loadDocument();
const staleGraph = requests.at(-2);
state.articleRef = book;
state.loadDocument();
requests.at(-2).respond(graph);
requests.at(-1).respond({{ref:book, title:'Curate', kind:'runbook', body:'Procedure'}});
staleGraph.respond({{nodes:[], links:[], navigation:{{groups:[]}}}});
assert.deepEqual(refs(false), [skill]); // Stale selection cannot erase connections.
graph.nodes.push({{id:'Tasks/curate', title:'Curate Task', kind:'task'}});
graph.nodes.push({{id:'Agents/Alexandria/Alexandria', title:'Alexandria', kind:'agent'}});
graph.links.push({{source:book, target:tool, derived:true, via:[skill]}});
graph.links.push({{source:'Tasks/curate', target:tool, derived:true, via:[book,skill],
  for_agent:'Agents/Alexandria/Alexandria'}});
state.articleRef = tool;
state.loadDocument();
requests.at(-2).respond(graph);
requests.at(-1).respond({{ref:tool, title:'vault.read', kind:'tool', body:'Read'}});
assert.deepEqual(refs(true), [book, 'Tasks/curate', skill]);
const connections = state.articleConnections(true);
assert.equal(connections.find(item => item.ref === book).detail, 'via Using vault.read');
assert.equal(connections.find(item => item.ref === 'Tasks/curate').detail,
  'via Curate → Using vault.read · Alexandria');
// The same physical Tool belongs to multiple clouds; only the clicked cloud counts.
const executive = 'Agents/Executive/Executive', curator = 'Agents/Alexandria/Alexandria';
const ownBook = 'Runbooks/executive', ownTask = 'Tasks/query';
graph.nodes.push({{id:ownBook,title:'Executive procedure',kind:'runbook'}},
  {{id:ownTask,title:'Query',kind:'task'}},
  {{id:'Runbooks/shared',title:'Shared index',kind:'runbook'}});
graph.links.push({{source:ownBook,target:tool,derived:true,via:[skill]}},
  {{source:ownTask,target:tool,derived:true,via:[ownBook,skill],for_agent:executive}},
  {{source:ownTask,target:tool,derived:true,via:[book,skill],for_agent:curator}},
  {{source:'Runbooks/shared',target:tool,derived:true,via:[book,skill]}});
graph.navigation.groups = [
  {{id:'executive',root_ref:executive,article_refs:[tool,skill,mirror,ownBook,ownTask,'Runbooks/shared']}},
  {{id:'curator',root_ref:curator,article_refs:[tool,skill,mirror,book,'Tasks/curate',ownTask]}},
  {{id:'library',root_ref:'@library',article_refs:[tool,skill,mirror,ownTask,'Tasks/curate']}}
];
state.articleGraph = graph;
state.graphId = 'main';
assert.deepEqual(refs(true), [ownBook,ownTask,skill]);
// A shared ancestor does not make a foreign descendant's procedure local.
assert(!refs(true).includes('Runbooks/shared'));
assert(!state.articleConnections(true).find(item => item.ref === ownTask).detail.includes('Alexandria'));
state.graphId = 'Alexandria'; // Same Article; context change must recompute immediately.
assert.deepEqual(refs(true), [book,'Tasks/curate',ownTask,skill]);
assert(!state.articleConnections(true).find(item => item.ref === ownTask).detail.includes('Executive procedure'));
state.graphId = 'library';
assert.deepEqual(refs(true), ['Tasks/curate',ownTask,skill]); // No per-Agent Runbook shelf.
state.graphId = 'unknown';
assert.deepEqual(refs(true), []); // Unknown context never falls through to the global catalog.
state.sourceMode = true;
assert.deepEqual(refs(false), []); // Raw Source is not another graph Article.
"""], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert "root.presentArticle(connectionButton.modelData.ref)" in source
    assert "root.articleBacklinks" in source and "root.articleLinks" in source


def test_reader_selection_keeps_graph_context_during_navigation():
    product = Path(__file__).parents[1]
    reader = (product / "shell/qml/panes/reader/ReaderPane.qml").read_text()
    functions = "\n".join(
        re.search(rf"^    function {name}\([^\n]*\) \{{.*?^    \}}", reader, re.M | re.S)[0]
        for name in ("applyShellEvent", "presentArticle")
    )
    result = subprocess.run(["node", "--experimental-strip-types", "--input-type=module", "-e", f"""
import {{ strict as assert }} from 'node:assert';
import vm from 'node:vm';
globalThis.window = new EventTarget();
const {{openReader,onOpenReader}} = await import({json.dumps((product / 'ui/src/renderer/src/lib/api.ts').as_uri())});
openReader('Tools/vault.propose','main');
const selections = [];
const stop = onOpenReader((ref,graphId) => selections.push([ref,graphId]));
assert.deepEqual(selections, [['Tools/vault.propose','main']]); // Replay retains scope.
openReader('Tools/vault.propose','Alexandria');
assert.deepEqual(selections.at(-1), ['Tools/vault.propose','Alexandria']);
stop();
const sent = [];
const state = {{followShellSelection:true,requestGeneration:0,selectionKind:'article',
  articleRef:'',sourceKey:'',feedItemId:'',previewItem:{{}},graphId:'',
  Qt:{{callLater() {{}}}},loadDocument() {{}},WebSocket:{{Open:1}},
  shellSocket:{{status:1,sendTextMessage(text) {{sent.push(JSON.parse(text));}}}}}};
state.root = state;
vm.createContext(state);
vm.runInContext({json.dumps(functions)},state);
const event = selection => JSON.stringify({{schema:'obsidience.shell.event.v1',type:'pane.state',
  pane:{{pane_id:'reader'}},selection}});
state.applyShellEvent(event({{kind:'article',ref:'Tools/vault.propose',graph_id:'main'}}));
assert.equal(state.graphId,'main');
state.presentArticle('Skills/vault.propose');
assert.deepEqual(sent.at(-1).selection,{{kind:'article',ref:'Skills/vault.propose',graph_id:'main'}});
state.applyShellEvent(event({{kind:'article',ref:'Tools/vault.propose',graph_id:'Alexandria'}}));
assert.equal(state.graphId,'Alexandria');
state.applyShellEvent(event({{kind:'source',key:'obsidience/vault/Tools/vault.propose.md'}}));
assert.equal(state.graphId,'');
"""], capture_output=True,text=True,timeout=10)
    assert result.returncode == 0, result.stderr
    bridge = (product / "ui/src/renderer/src/surfaces/knowledge-desktop.tsx").read_text()
    assert "presentShellReader(ref, graphId)" in bridge
    server = (product / "shell/qml/api/ShellCommandServer.qml").read_text()
    assert 'graph_id: selection.kind === "article"' in server
    explorer = (product / "shell/qml/panes/knowledge/KnowledgePane.qml").read_text()
    assert '"graph_id": graphIdForGroup(group)' in explorer
