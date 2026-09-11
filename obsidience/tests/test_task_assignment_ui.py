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
    react = (PRODUCT / "ui/src/renderer/src/panes/reader-pane.tsx").read_text()
    functions = _functions(react, ("cleanLink", "graphProjectionNode", "graphProjectionRoots"), "")
    _node(f"""
import {{strict as assert}} from 'node:assert';
import {{createRequire}} from 'node:module';
import vm from 'node:vm';
const ts=createRequire({json.dumps(str(PRODUCT / 'ui/package.json'))})('typescript');
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
const reactState={{}};vm.createContext(reactState);
vm.runInContext(ts.transpileModule({json.dumps(functions)},{{compilerOptions:{{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.None}}}}).outputText,reactState);
for(const [field,subjectRef] of [['tools','@branch/Tools'],['skills','@branch/Skills'],['tasks','@branch/Tasks']]){{
  const projected=reactState.graphProjectionRoots(graphNodes[0].dependencies[field],graphNodes.filter(row=>members.includes(row.id)),field);
  const nativeRows=state.groups[0].tree.find(row=>row.ref===subjectRef).children;
  assert.deepEqual(Array.from(flatten(projected),row=>row.ref),Array.from(flatten(nativeRows),row=>row.ref));
}}
delete graphNodes[0].dependencies;
state.buildGroups();
assert.equal(flatten(state.groups[0].tree).some(row=>row.ref===tool),false); // Old checkouts are never fallback authority.
""")
    assert "identity.checkouts" not in native
    assert "identity?.checkouts" not in react
    assert "sourceCheckouts" in react and "setSourceCheckout" in react


def test_browser_assignment_api_uses_task_contract_and_keeps_source_scope_separate():
    _node(f"""
import {{strict as assert}} from 'node:assert';
const calls=[];
globalThis.fetch=async(path,options)=>{{calls.push({{path,options}});return {{ok:true,json:async()=>({{assignments:[],dependencies:[]}})}};}};
const {{api}}=await import({json.dumps((PRODUCT / 'ui/src/renderer/src/lib/api.ts').as_uri())});
await api.assignments();
assert.equal(calls[0].path,'http://127.0.0.1:8765/api/library/assignments');
await api.setAssignment('Tasks/query','executive',true);
assert.equal(calls[1].path,'http://127.0.0.1:8765/api/library/assignments/Tasks/query');
assert.deepEqual(JSON.parse(calls[1].options.body),{{agent:'executive',assigned:true}});
await api.setSourceCheckout('obsidience/evidence','researcher',true);
assert.deepEqual(JSON.parse(calls[2].options.body),{{agent:'researcher',checked_out:true}});
""")
    library = (PRODUCT / "ui/src/renderer/src/panes/library-pane.tsx").read_text()
    assert "toggleAssignment" not in library and "api.setAssignment" not in library
    assert "openReader" in library
