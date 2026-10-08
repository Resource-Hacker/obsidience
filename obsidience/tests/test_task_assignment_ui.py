"""Task-only assignment controls and read-only, API-derived explorer branches."""
import json
import re
import subprocess
from pathlib import Path

from test_native_library_tree import _projection_functions


PRODUCT = Path(__file__).parents[1]


def _functions(source: str, names: tuple[str, ...], indent: str = "    ") -> str:
    return "\n".join(
        re.search(rf"^{indent}function {name}\(.*?^{indent}\}}", source, re.M | re.S)[0]
        for name in names
    )


def _node(code: str) -> None:
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", code],
        capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr


def test_reader_checkout_controls_share_revisioned_authoritative_state():
    source = (PRODUCT / "shell/qml/components/knowledge/ArticleCheckouts.qml").read_text()
    functions = source[source.index("    function key("):source.rfind("\n}")]
    _node(f"""
import {{strict as assert}} from 'node:assert';
import vm from 'node:vm';
const requests=[];
class XHR {{
  static DONE=4;
  open(method,path){{this.method=method;this.path=path;}}
  setRequestHeader(){{}}
  send(body){{this.body=body;requests.push(this);}}
  finish(status,payload){{this.status=status;this.responseText=JSON.stringify(payload);this.readyState=4;this.onreadystatechange();}}
}}
const task='Tasks/query', fact='Shared/fact', role={{id:'executive',role:'executive',title:'Executive'}};
const state={{nodes:[{{id:task,kind:'task'}},{{id:fact,kind:'knowledge'}},{{id:'Tools/read',kind:'tool'}}],
 rows:{{}},revisions:{{}},pending:false,active:true,error:'',generation:0,changes:0,
 changed(){{state.changes++;}},XMLHttpRequest:XHR}};
state.root=state;vm.createContext(state);vm.runInContext({json.dumps(functions)},state);
state.applyManifest({{revisions:{{executive:'r1'}},knowledge:[{{ref:fact,agent:'executive',checked:false,editable:true}}]}});
state.toggle({{ref:'Tools/read'}},role);assert.equal(requests.length,0);
state.toggle({{ref:task}},role);assert.equal(requests.length,1);
assert.deepEqual(JSON.parse(requests[0].body),{{agent:'executive',assigned:true,expected_revision:'r1'}});
assert.equal(state.state({{ref:task}},'executive').checked,false); // No optimistic grant.
state.toggle({{ref:fact}},role);assert.equal(requests.length,1); // Single flight.
requests[0].finish(409,{{detail:'stale'}});
assert.equal(state.pending,false);assert.match(state.error,/changed/);
assert.equal(requests[1].method,'GET');
requests[1].finish(200,{{revisions:{{executive:'r2'}},assignments:[{{ref:task,agent:'executive',direct:true,inherited:false}}]}});
assert.equal(state.state({{ref:task}},'executive').checked,true);
state.toggle({{ref:task}},role);assert.equal(JSON.parse(requests[2].body).assigned,false);
assert.equal(JSON.parse(requests[2].body).expected_revision,'r2');
requests[2].finish(200,{{}});assert.equal(state.changes,1);
requests[3].finish(200,{{revisions:{{executive:'r3'}},assignments:[{{ref:task,agent:'executive',direct:false,inherited:true}}]}});
state.toggle({{ref:task}},role);assert.equal(requests.length,4); // Inherited execution dependency is not a manual grant.
""")
    reader = (PRODUCT / "shell/qml/panes/reader/ReaderPane.qml").read_text()
    explorer = (PRODUCT / "shell/qml/panes/knowledge/KnowledgePane.qml").read_text()
    catalog = (PRODUCT / "shell/qml/panes/library/LibraryPane.qml").read_text()
    assert all("ArticleCheckouts {" in text and "AgentCheckoutButtons {" in text for text in (reader, explorer))
    assert "toggleAssignment" not in catalog and "/api/library/assignments" not in catalog
    assert 'text: "SKILL"' in catalog


def test_native_catalog_uses_only_declared_members_and_has_no_assignment_writer():
    source = (PRODUCT / "shell/qml/panes/library/LibraryPane.qml").read_text()
    functions = _functions(source, ("refresh",))
    _node(f"""
import {{strict as assert}} from 'node:assert';
import vm from 'node:vm';
const requests=[];
const state={{updateCounts(){{}},rebuildRows(){{}},requestJson(method,path,body,callback){{requests.push({{method,path,callback}});}}}};
vm.createContext(state);vm.runInContext({json.dumps(functions)},state);state.refresh();
requests.find(row=>row.path==='/api/graph').callback(true,{{nodes:[{{id:'Tasks/query',kind:'task'}},
 {{id:'Tools/read',kind:'tool'}},{{id:'Agents/Darwin/Tasks/private',kind:'task'}}],navigation:{{groups:[
 {{id:'library',role:'library',article_refs:['Tasks/query','Tools/read']}}]}}}},'');
assert.deepEqual(Array.from(state.nodes,row=>row.id),['Tasks/query','Tools/read']);
assert.equal(requests.some(row=>row.path.includes('assignments')),false);
""")


def test_native_and_react_explorers_use_dependencies_not_manual_capability_lists():
    native = (PRODUCT / "shell/qml/panes/knowledge/KnowledgePane.qml").read_text()
    _node(f"""
import {{strict as assert}} from 'node:assert';
import vm from 'node:vm';
const executive='Agents/Executive/Executive',tool='Tools/web.fetch',skill='Skills/web.fetch',task='Tasks/research/news';
const alias='@library/Skills/web/fetch';
const graphNodes=[{{id:executive,title:'Executive',kind:'agent',
  checkouts:{{tools:['Tools/unrelated']}},dependencies:{{tools:[tool,'Agents/Darwin/Tools/private'],skills:[skill],tasks:[task],runbooks:[]}}}},
  {{id:tool,title:'web.fetch',kind:'tool',children:[]}},
  {{id:'Tools/unrelated',title:'Unrelated',kind:'tool',children:[]}},
  {{id:'Agents/Darwin/Tools/private',title:'Private',kind:'tool',children:[]}},
  {{id:'@library/Tools/web',title:'Web',kind:'tool',children:[tool,'Tools/unrelated']}},
  {{id:skill,title:'Using web.fetch',kind:'skill',children:[]}},
  {{id:alias,title:'fetch',kind:'skill',article_ref:skill,children:[]}},
  {{id:'@library/Skills/web',title:'Web',kind:'skill',children:[alias]}},
  {{id:task,title:'News',kind:'task',children:[]}},
  {{id:'@library/Tasks/research',title:'Research',kind:'knowledge',tags:['task-taxonomy'],children:[task]}}
];
const members=graphNodes.filter(row=>!['Tools/unrelated','Agents/Darwin/Tools/private'].includes(row.id)).map(row=>row.id);
const group={{id:'executive',root_ref:executive,article_refs:members,subjects:[
  {{id:'@branch/Tools',title:'Executable interfaces',parent_id:null}},
  {{id:'@branch/Skills',title:'Usage guidance',parent_id:null}},
  {{id:'@branch/Tasks',title:'Assigned work',parent_id:null}},
  {{id:'@branch/Runbooks',title:'Procedures',parent_id:null}}
]}};
const state={{graphNodes,files:[],navigation:{{groups:[group]}},expandedPaths:{{}},revealSelection(){{}},rebuildRows(){{}}}};
vm.createContext(state);vm.runInContext({json.dumps(_projection_functions())},state);state.buildGroups();
const flatten=rows=>rows.flatMap(row=>[row,...flatten(row.children||[])]);
const refs=flatten(state.groups[0].tree).map(row=>row.ref);
assert.equal(refs.includes('Tools/unrelated'),false);
assert.equal(refs.includes('Agents/Darwin/Tools/private'),false);
assert.equal(refs.includes(alias),true);
assert.equal(refs.includes(skill),false); // Physical dependency uses the one canonical display alias.
assert.equal(refs.includes('@library/Tasks/research'),true);
delete graphNodes[0].dependencies;
state.buildGroups();
assert.equal(flatten(state.groups[0].tree).some(row=>row.ref===tool),false); // Old checkouts are never fallback authority.
""")
    assert "identity.checkouts" not in native
