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


def test_native_assignments_require_real_tasks_and_preserve_inherited_ownership():
    source = (PRODUCT / "shell/qml/panes/library/LibraryPane.qml").read_text()
    functions = _functions(source, ("assignmentKey", "canAssign", "assignmentHint", "toggleAssignment"))
    _node(f"""
import {{strict as assert}} from 'node:assert';
import vm from 'node:vm';
const task='Tasks/query', tool='Tools/web.fetch';
const requests=[];
const state={{nodes:[{{id:task,kind:'task'}},{{id:tool,kind:'tool'}},
  {{id:'@library/Tasks/future',kind:'task',synthetic:true}}],
  assignments:{{}},busyAssignments:{{}},navigationAgents:[{{role:'executive',title:'Executive'}}],
  refresh(){{}},requestJson(method,path,body,callback){{requests.push({{method,path,body,callback}});}}}};
vm.createContext(state);
vm.runInContext({json.dumps(functions)},state);
const key=state.assignmentKey(task,'executive');
for(const ref of [tool,'@library/Tasks/future','Tasks/missing'])state.toggleAssignment(ref,'executive');
assert.equal(requests.length,0);
state.assignments[key]={{kind:'task',direct:false,inherited:true}};
state.toggleAssignment(task,'executive');
assert.equal(requests.length,0);
assert.match(state.assignmentHint(task,'executive'),/Edit the Task in Reader/);
delete state.assignments[key];
state.toggleAssignment(task,'executive');
assert.equal(requests.length,1);
assert.equal(requests[0].path,'/api/library/assignments/Tasks/query');
assert.deepEqual(JSON.parse(JSON.stringify(requests[0].body)),{{agent:'executive',assigned:true}});
assert.equal(state.assignments[key],undefined); // No optimistic grant.
state.toggleAssignment(task,'executive');
assert.equal(requests.length,1); // Single flight.
requests[0].callback(true,{{ref:task,agent:'executive',kind:'task',direct:true,inherited:true,assignment_changed:true}},'');
assert.equal(state.assignments[key].direct,true);
state.toggleAssignment(task,'executive');
assert.equal(requests[1].body.assigned,false);
requests[1].callback(false,null,'Rejected');
assert.equal(state.assignments[key].direct,true); // Failure preserves accepted state.
state.toggleAssignment(task,'executive');
requests[2].callback(true,{{ref:task,agent:'executive',kind:'task',direct:false,inherited:true,assignment_changed:true}},'');
assert.equal(state.assignments[key].inherited,true);
assert.equal(state.assignments[key].direct,false);
assert.match(state.assignmentNotice,/ownership remains/);
state.toggleAssignment(task,'executive');
assert.equal(requests.length,3); // The remaining inherited assignment is read-only.
delete state.assignments[key];
state.toggleAssignment(task,'executive');
requests[3].callback(true,{{ref:task,agent:'executive',kind:'task',direct:true,inherited:false,
  assignment_changed:true,activation_state:'queued',activation_error:'awaiting-runbook: ordinary Runbook generation is pending'}},'');
assert.equal(state.assignmentError,''); // Normal queued generation is not a failure.
assert.match(state.assignmentNotice,/Runbook generation is queued for review/);
assert.equal(state.assignmentNotice.includes('undefined'),false);
""")
    assert 'model: root.canAssign(libraryRow.modelData.node) ? root.navigationAgents : []' in source
    assert 'text: "SKILL"' in source
    assert "/api/library/checkouts" not in source and '"checked_out"' not in source


def test_native_library_fetches_only_task_assignments_and_canonical_members():
    source = (PRODUCT / "shell/qml/panes/library/LibraryPane.qml").read_text()
    functions = _functions(source, ("assignmentKey", "refresh"))
    _node(f"""
import {{strict as assert}} from 'node:assert';
import vm from 'node:vm';
const requests=[];
const state={{updateCounts(){{}},rebuildRows(){{}},requestJson(method,path,body,callback){{requests.push({{method,path,callback}});}}}};
vm.createContext(state);vm.runInContext({json.dumps(functions)},state);state.refresh();
const respond=(path,data)=>requests.find(row=>row.path===path).callback(true,data,'');
respond('/api/graph',{{nodes:[{{id:'Tasks/query',kind:'task'}},{{id:'Tools/read',kind:'tool'}},
  {{id:'Agents/Darwin/Tasks/private',kind:'task'}}],navigation:{{groups:[
  {{id:'library',role:'library',article_refs:['Tasks/query','Tools/read']}},
  {{id:'executive',role:'executive'}}]}}}});
assert.deepEqual(Array.from(state.nodes,row=>row.id),['Tasks/query','Tools/read']);
respond('/api/library/assignments',{{assignments:[
  {{ref:'Tasks/query',agent:'executive',kind:'task',direct:false,inherited:true}},
  {{ref:'Tools/read',agent:'executive',kind:'tool',direct:true}}],
  dependencies:[{{ref:'Tools/read',agent:'executive',kind:'tool'}}]}});
assert.deepEqual(Object.keys(state.assignments),[state.assignmentKey('Tasks/query','executive')]);
assert.equal(requests.some(row=>row.path.includes('checkouts')),false);
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
    assert 'return node.kind === "task" && node.synthetic !== true;' in library
    assert 'disabled={busy.has(key) || inheritedOnly}' in library
    assert 'isAssignmentable(node) ? (' in library
    assert "setCheckout" not in library and "checked_out" not in library
