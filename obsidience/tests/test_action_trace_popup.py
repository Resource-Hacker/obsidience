"""Exercise the native graph popup's trace projection and subscription lifecycle."""
import json
from pathlib import Path
import subprocess


UI = Path(__file__).parents[1] / "ui"
PANES = UI / "src/renderer/src/panes"


def node_check(script):
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def projection_check(script):
    node_check(
        "import { strict as assert } from 'node:assert';\n"
        f"import * as trace from {json.dumps((PANES / 'action-trace.ts').as_uri())};\n"
        + script
    )


def test_matrix_correlates_interleaved_runs_and_repeated_tools_by_exact_ids():
    projection_check(r"""
const event=(id,at,run_id,channel,payload,call_id)=>({id,at,run_id,channel,payload,call_id,line:'Public event',detail:[]});
const start=(id,at,run,call,ref)=>event(id,at,run,'tool',{kind:'tool',phase:'start',name:'vault.read',arguments:{ref}},call);
const result=(id,at,run,call,text)=>event(id,at,run,'result',{kind:'tool',phase:'result',name:'vault.read',status:'returned',result:text},call);
// Two repeated calls inside A, plus the same call ID in B. Completion order
// differs from call order; tool names and arrival order cannot bind results.
const rows=[
 event('a',100,'run-a','run',{kind:'run',task_title:'Query',agent_title:'Executive',status:'running'}),
 start('a1',101,'run-a','call-1','Article A'),
 event('b',102,'run-b','run',{kind:'run',task_title:'Ingest',agent_title:'Alexandria',status:'running'}),
 start('b1',103,'run-b','call-1','Article B'),
 start('a2',104,'run-a','call-2','Article C'),
 result('ra2',105,'run-a','call-2','C evidence'),
 result('rb1',106,'run-b','call-1','B evidence'),
 result('ra1',107,'run-a','call-1','A evidence'),
 result('orphan',108,'run-a','never-requested','Unpaired evidence'),
 {id:'legacy-tool',at:109,channel:'tool',line:'Executive → vault.read',detail:['Article D']},
 {id:'legacy-result',at:110,channel:'result',line:'vault.read returned',detail:['D evidence']},
];
const entries=trace.applyTraceFrame([],JSON.stringify({type:'snapshot',entries:rows}),100);
const runs=trace.traceRuns(entries);
const a=runs.find(r=>r.id==='run-a'),b=runs.find(r=>r.id==='run-b');
assert.equal(a.title,'Query');assert.equal(b.title,'Ingest');
assert.equal(a.rows.find(r=>r.id==='a1').result.payload.result,'A evidence');
assert.equal(a.rows.find(r=>r.id==='a2').result.payload.result,'C evidence');
assert.equal(b.rows.find(r=>r.id==='b1').result.payload.result,'B evidence');
assert.equal(a.rows.find(r=>r.id==='orphan').result,undefined);
assert(!a.entries.some(e=>e.runId==='run-b'));
const legacy=runs.find(r=>r.id==='unbound');
assert.equal(legacy.rows.length,2);assert(legacy.rows.every(r=>r.result===undefined));
""")


def test_stable_event_replay_keeps_disclosed_action_key_when_result_arrives():
    projection_check(r"""
const start={id:'request-event',at:100,channel:'tool',line:'Executive → vault.read',run_id:'r',call_id:'c',payload:{kind:'tool',phase:'start',name:'vault.read',arguments:{ref:'A'}}};
const frame=entry=>JSON.stringify({type:'entry',entry});
let entries=trace.applyTraceFrame([],frame(start),100);
const before=trace.traceRuns(entries)[0].rows[0];
assert.equal(trace.traceRowState(before),'Waiting');
const openDisclosureKeys=new Set([before.id]);
// Public IDs deduplicate overlapping replay even if the display label changes.
entries=trace.applyTraceFrame(entries,frame({...start,line:'Read A'}),100);
assert.equal(entries.length,1);assert.equal(entries[0].line,'Read A');
const result={id:'result-event',at:101,channel:'result',line:'vault.read returned',run_id:'r',call_id:'c',payload:{kind:'tool',phase:'result',name:'vault.read',status:'returned',result:{title:'A',content:'Full evidence'}}};
entries=trace.applyTraceFrame(entries,frame(result),100);
entries=trace.applyTraceFrame(entries,frame(result),100);
const after=trace.traceRuns(entries)[0].rows;
assert.equal(entries.length,2);assert.equal(after.length,1);
assert.equal(after[0].id,before.id);assert(openDisclosureKeys.has(after[0].id));
assert.equal(after[0].result.id,'result-event');
// Identical timestamps/labels with distinct IDs remain distinct observations.
entries=trace.applyTraceFrame(entries,frame({...result,id:'another-result',call_id:'other'}),100);
assert.equal(entries.length,3);
// Arrival order after reconnect can differ; event time still places the start
// before its later result without inventing a missing request.
const replay=trace.applyTraceFrame([],JSON.stringify({type:'snapshot',entries:[result,start]}),100);
assert.equal(trace.traceRuns(replay)[0].rows[0].id,'request-event');
assert.equal(trace.traceRuns(replay)[0].rows[0].result.id,'result-event');
""")


def test_tool_request_or_return_does_not_fabricate_task_completion():
    projection_check(r"""
const entries=trace.applyTraceFrame([],JSON.stringify({type:'snapshot',entries:[
 {id:'run',at:100,run_id:'r',channel:'run',line:'Task started',payload:{kind:'run',task_title:'Query',status:'running'}},
 {id:'call',at:101,run_id:'r',call_id:'c',channel:'tool',line:'Submit outcome',payload:{kind:'tool',phase:'start',name:'task.complete',arguments:{status:'completed',summary:'It worked'}}},
 {id:'out',at:102,run_id:'r',call_id:'c',channel:'result',line:'task.complete returned',payload:{kind:'tool',phase:'result',name:'task.complete',status:'rejected',result:'Completion rejected: missing evidence'}},
 {id:'claim',at:103,run_id:'r',channel:'status',line:'Model says completed',detail:['Task completed successfully']},
]}),100);
let run=trace.traceRuns(entries)[0];
assert.equal(run.status,'running');
assert.equal(trace.traceRowState(run.rows.find(r=>r.id==='call')),'Rejected');
assert.equal(trace.traceRowState(run.rows.find(r=>r.id==='claim')),'Recorded');
const accepted=trace.applyTraceFrame(entries,JSON.stringify({type:'entry',entry:{id:'accepted',at:104,run_id:'r',channel:'status',line:'Completion accepted',payload:{kind:'run',status:'review',summary:'Pending owner review'}}}),100);
run=trace.traceRuns(accepted)[0];assert.equal(run.status,'review');
assert.equal(run.summary,'Pending owner review');
const orphan={...entries[2],id:'orphan',callId:'unknown',payload:{kind:'tool',phase:'result',name:'application.launch',status:'returned',result:'Launch dispatched'}};
assert.equal(trace.traceRowState({id:orphan.id,entry:orphan}),'Returned');
assert.equal(trace.traceRuns([orphan])[0].status,'');
""")


def test_recursive_public_payload_is_readable_bounded_and_filters_private_fields():
    projection_check(r"""
let deep={value:'unreachable sentinel'};for(let i=0;i<15;i++)deep={next:deep};
const payload={kind:'tool',phase:'result',name:'vault.read',result:{
 content:'article text '.repeat(300),items:Array.from({length:240},(_,i)=>({title:'Item '+i})),
 _internal:'private-one',reasoning:'private-two',nested:{analysis:'private-three',chain_of_thought:'private-four',reasoning_content:'private-five',visible:'Public detail'},deep,
}};
const wire={id:'result',at:100,channel:'result',line:'Result',payload,truncated:true};
let entries=trace.applyTraceFrame([],JSON.stringify({type:'entry',entry:wire}),100);
const value=entries[0].payload.result;
assert.equal(value.content,payload.result.content); // Rich evidence no longer ends at360 characters.
assert.equal(value.items.length,200);assert.equal(value.nested.visible,'Public detail');
assert(!JSON.stringify(entries).includes('private-'));assert(!JSON.stringify(entries).includes('unreachable sentinel'));
assert(JSON.stringify(value.deep).includes('Display limit reached'));assert(entries[0].truncated);
const huge={kind:'tool',phase:'result',result:{one:'a'.repeat(60000),two:'b'.repeat(60000),three:'c'.repeat(60000)}};
const bounded=trace.applyTraceFrame([],JSON.stringify({type:'entry',entry:{...wire,payload:huge}}),100);
assert(JSON.stringify(bounded[0].payload).length<71000);
for(const bad of [null,[],{at:100,channel:'reasoning',line:'private-six'},
 {at:'100',channel:'tool',line:'wrong timestamp'},{at:100,channel:'tool',line:'  '}]) {
 assert.deepEqual(trace.applyTraceFrame(entries,JSON.stringify({type:'entry',entry:bad}),100),entries);
}
for(const malformed of [null,42,'unexpected',[]]) {
 const projected=trace.applyTraceFrame([],JSON.stringify({type:'entry',entry:{...wire,payload:malformed}}),100);
 assert.deepEqual(projected[0].payload,{});
}
assert.deepEqual(trace.applyTraceFrame(entries,'x'.repeat(4000001),100),entries);
""")


def test_explicit_tool_result_failure_is_visible_without_inferring_from_prose():
    projection_check(r"""
const project=result=>trace.applyTraceFrame([],JSON.stringify({type:'snapshot',entries:[
 {id:'run',at:100,run_id:'r',channel:'run',line:'Task started',payload:{kind:'run',status:'running'}},
 {id:'call',at:101,run_id:'r',call_id:'c',channel:'tool',line:'Act',payload:{kind:'tool',phase:'start',name:'computer.act',arguments:{}}},
 {id:'result',at:102,run_id:'r',call_id:'c',channel:'result',line:'Tool returned',payload:{kind:'tool',phase:'result',name:'computer.act',status:'returned',result}},
]}),100);
for(const [status,label] of Object.entries({failed:'Failed',error:'Error',blocked:'Blocked',rejected:'Rejected',degraded:'Degraded'})) {
 const entries=project({status,summary:'The transport returned normally'});
 const run=trace.traceRuns(entries)[0];
 assert.equal(trace.traceRowState(run.rows.find(row=>row.id==='call')),label);
 assert.equal(trace.traceRowState({id:'result',entry:entries[2]}),label); // Also visible without a retained request.
 assert.equal(run.status,'running'); // Tool health does not finalize its Task.
}
for(const result of [
 {status:'returned'}, {status:'completed'}, {status:'ready'},
 {summary:'failed error blocked rejected degraded',ok:false,error_count:5},
 'Task failed and is blocked', [{status:'failed'}], {nested:{status:'failed'}},
]) {
 const run=trace.traceRuns(project(result))[0];
 assert.equal(trace.traceRowState(run.rows.find(row=>row.id==='call')),'Returned');
 assert.equal(run.status,'running');
}
""")


def test_inspection_finding_is_separate_from_successful_tool_return():
    projection_check(r"""
const project=(name,result,status='returned')=>trace.traceRuns(trace.applyTraceFrame([],JSON.stringify({type:'snapshot',entries:[
 {id:'run',at:100,run_id:'r',channel:'run',line:'Audit started',payload:{kind:'run',task_title:'Audit',agent_title:'Heimdall',status:'running'}},
 {id:'call',at:101,run_id:'r',call_id:'c',channel:'tool',line:'Inspect',payload:{kind:'tool',phase:'start',name,arguments:{}}},
 {id:'result',at:102,run_id:'r',call_id:'c',channel:'result',line:'Inspection returned',payload:{kind:'tool',phase:'result',name,status,result}},
]}),100))[0];
for(const [name,result,finding] of [
 ['task.inspect',{task:'Tasks/Link',status:'failed',runs:[{status:'failed',summary:'Previous attempt failed'}]},'Inspected task: Failed'],
 ['task.inspect',{task:'Tasks/Link',status:'blocked'},'Inspected task: Blocked'],
 ['task.inspect',{task:'Tasks/Link',status:'completed',runs:[{status:'failed'}]},'Inspected task: Completed'],
 ['harness.status',{status:'degraded',recent_failures:2},'Harness health: Degraded'],
 ['harness.status',{status:'healthy'},'Harness health: Healthy'],
]) {
 const run=project(name,result),row=run.rows.find(row=>row.id==='call');
 assert.equal(trace.traceRowState(row),'Returned');assert.equal(trace.traceRowFinding(row),finding);
 assert.deepEqual(row.result.payload.result,result);assert.equal(run.status,'running');
 const orphan={id:row.result.id,entry:row.result};
 assert.equal(trace.traceRowState(orphan),'Returned');assert.equal(trace.traceRowFinding(orphan),finding);
 for(const [wrapper,label] of [['error','Error'],['rejected','Rejected'],['interrupted','Interrupted']]) {
   const failed=project(name,result,wrapper).rows.find(row=>row.id==='call');
   assert.equal(trace.traceRowState(failed),label);assert.equal(trace.traceRowFinding(failed),'');
 }
}
for(const name of ['task.inspect','harness.status']) {
 for(const result of [{},{status:null},{status:[]},{nested:{status:'failed'}},'status: failed']) {
   const row=project(name,result).rows.find(row=>row.id==='call');
   assert.equal(trace.traceRowState(row),'Returned');assert.equal(trace.traceRowFinding(row),'');
 }
}
// Exact existing contracts are distinguished; a tool name suffix is not evidence
// that its inner status refers to some other entity.
for(const name of ['computer.act','custom.inspect','task.inspect.extra']) {
 const row=project(name,{status:'failed',delivery:'not_dispatched'}).rows.find(row=>row.id==='call');
 assert.equal(trace.traceRowState(row),'Failed');assert.equal(trace.traceRowFinding(row),'');
}
""")


def test_trace_replay_is_bounded_current_and_public():
    node_check(f"""
import {{ strict as assert }} from 'node:assert';
import {{ applyTraceFrame, TRACE_ENTRY_LIMIT, traceChannelLabel }} from {json.dumps((PANES / 'action-trace.ts').as_uri())};
const row = (at, channel, line, detail=[]) => ({{at, channel, line, detail}});
const frame = entry => JSON.stringify({{type:'entry', entry}});
const start = row(100, 'run', 'Executive started Query');
let entries = applyTraceFrame([], JSON.stringify({{type:'snapshot', entries:[
  row(99, 'error', 'old failure'), start,
  row(101, 'reasoning', 'private sentinel'),
  row(102, 'tool', 'Executive → vault.read', ['{{"ref":"Architecture"}}']),
  row(103, 'result', 'vault.read returned', ['The returned Article content']),
]}}), 100);
assert.equal(entries.length, 3);
assert(!JSON.stringify(entries).includes('old failure'));
assert(!JSON.stringify(entries).includes('private sentinel'));
assert.equal(entries.at(-1).detail, 'The returned Article content');
// Snapshot/queue overlap must not render the same result twice.
entries = applyTraceFrame(entries, frame(row(103, 'result', 'vault.read returned', ['The returned Article content'])), 100);
assert.equal(entries.length, 3);
for (const bad of ['{{', 'null', '[]', JSON.stringify({{type:'entry',entry:{{at:'104',channel:'error',line:'bad'}}}}), 'x'.repeat(4000001)]) {{
  assert.deepEqual(applyTraceFrame(entries,bad,100), entries);
}}
for (let at=104; at<360; at++) entries=applyTraceFrame(entries,frame(row(at,'result','result '+at,['x'.repeat(1000)])),100);
assert.equal(entries.length, TRACE_ENTRY_LIMIT);
assert.equal(entries[0].line, start.line); // Keep the real Task heading through a long run.
assert.equal(entries.at(-1).line, 'result 359');
assert.equal(entries.at(-1).detail.length,500); // Legacy previews remain bounded; rich fields use payload.
assert(entries.every(entry=>entry.detail.length<=6000 && entry.line.length<=300));
entries=applyTraceFrame(entries,frame(row(360,'model','Query provider timing',['Preflight: 1 ms','Public TTFT: 60 ms','Generation: 200 ms','Cached input tokens: 4096'])),100);
assert(entries.at(-1).detail.includes('Cached input tokens: 4096'));
assert.equal(traceChannelLabel('model'),'Model');
entries=applyTraceFrame(entries,frame(row(361,'status','Executive completion accepted for Query: completed')),100);
assert.equal(entries.at(-1).line,'Executive completion accepted for Query: completed');
entries=applyTraceFrame(entries,frame(row(362,'error','Query finalization failed',['The task was not completed.'])),100);
assert.equal(entries.at(-1).channel,'error');
assert.equal(entries.at(-1).detail,'The task was not completed.');
// Reconnect starts from server history, not a stale client tail.
entries=applyTraceFrame(entries,JSON.stringify({{type:'snapshot',entries:[row(200,'run','Darwin started News')]}}),200);
assert.deepEqual(entries.map(entry=>entry.line),['Darwin started News']);
""")


def test_popup_keeps_results_and_closes_its_only_subscription():
    node_check(rf"""
import {{ strict as assert }} from 'node:assert';
import fs from 'node:fs';
import vm from 'node:vm';
import {{ createRequire }} from 'node:module';
import * as trace from {json.dumps((PANES / 'action-trace.ts').as_uri())};
const require=createRequire({json.dumps((UI / 'package.json').as_uri())});
const ts=require('typescript');
const source=fs.readFileSync({json.dumps(str(PANES / 'action-trace-popup.tsx'))},'utf8');
const compiled=ts.transpileModule(source,{{compilerOptions:{{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}}}).outputText;
const state=[]; let cursor=0; const effects=[]; const sockets=[]; const timers=[]; const cleared=[];
const react={{useState(initial){{const index=cursor++;if(!(index in state))state[index]=initial;return[state[index],next=>{{state[index]=typeof next==='function'?next(state[index]):next;}}];}},useRef(initial){{const index=cursor++;if(!(index in state))state[index]={{current:initial}};return state[index];}},useEffect(fn){{effects.push(fn);}}}};
const jsx=(type,props,key)=>typeof type==='function'?{{...type(props),key}}:({{type,props,key}});
class Socket {{constructor(url){{this.url=url;sockets.push(this);}}close(){{this.closed=true;this.onclose?.();}}}}
const module={{exports:{{}}}};
vm.runInNewContext(compiled,{{module,exports:module.exports,WebSocket:Socket,
  setTimeout:fn=>{{timers.push(fn);return timers.length;}},clearTimeout:id=>cleared.push(id),
  require:name=>name==='react'?react:name==='react/jsx-runtime'?{{jsx,jsxs:jsx}}:
    name==='@/lib/api'?{{WS_BASE:'ws://127.0.0.1:8765'}}:name==='./action-trace'?trace:(()=>{{throw Error(name);}})(),
}});
const kept=[];let closed=0;
const render=(since,keptOpen=false)=>{{cursor=0;return module.exports.ActionTracePopup({{since,keptOpen,onKeepOpen:value=>kept.push(value),onClose:()=>closed++}});}};
const nodes=value=>Array.isArray(value)?value.flatMap(nodes):value&&typeof value==='object'?[value,...nodes(value.props?.children)]:[];
const words=value=>Array.isArray(value)?value.map(words).join(' '):value&&typeof value==='object'?words(value.props?.children):value==null?'':String(value);
render(100); const cleanup=effects[0]();
assert.equal(sockets.length,1);
assert.equal(sockets[0].url,'ws://127.0.0.1:8765/ws/trace');
sockets[0].onopen();
const packetSections=[
 {{key:'header',title:'Internal heading',text:'Header should not appear as a packet section'}},
 {{key:'agent',title:'Agent Identity',text:'## Agent Identity\nExecutive is responsible.',chars:45}},
 {{key:'objective',title:'Objective',text:'## Objective\nFind the current launch policy.',chars:48}},
 {{key:'bindings',title:'Bindings',text:'## Bindings\n'+JSON.stringify({{source_ref:'source://captured',current_only:true,nested:{{ref:'Architecture/Launch'}}}}),chars:110}},
];
sockets[0].onmessage({{data:JSON.stringify({{type:'snapshot',entries:[
  {{id:'run-event',run_id:'query-run',at:100,channel:'run',line:'Executive started Query',payload:{{kind:'run',task_title:'Query',agent_title:'Executive',status:'running'}}}},
  {{id:'packet-event',run_id:'query-run',at:101,channel:'activation',line:'Packet prepared',payload:{{kind:'packet',sections:packetSections}}}},
  {{id:'model-wait',run_id:'query-run',call_id:'query-run:model:1',step:1,at:101.1,channel:'model',line:'Lease waiting',payload:{{kind:'model',phase:'waiting'}}}},
  {{id:'model-start',run_id:'query-run',call_id:'query-run:model:1',step:1,at:101.6,channel:'model',line:'Provider started',payload:{{kind:'model',phase:'started'}}}},
  {{id:'model-return',run_id:'query-run',call_id:'query-run:model:1',step:1,at:102,channel:'model',line:'Provider returned',payload:{{kind:'model',phase:'result'}}}},
  {{id:'read-event',run_id:'query-run',call_id:'read-call',step:1,at:102,channel:'tool',line:'vault.read',payload:{{kind:'tool',phase:'start',name:'vault.read',arguments:{{ref:'Architecture/Launch'}}}}}},
]}})}});
const waiting=render(100);
assert(words(waiting).includes('Waiting for a result. A requested action does not establish that it succeeded.'));
const beforeRow=nodes(waiting).find(node=>node.type==='details'&&node.key==='read-event');
assert(beforeRow);assert.equal(beforeRow.props.open,undefined); // Native, uncontrolled disclosure.
// The provider return and resulting Tool can share an integer millisecond.
// Follow must still find the Tool emitted afterward, without changing its key.
assert.equal(beforeRow.props['data-trace-event'],'read-event');
const tiedFollow=[];
nodes(waiting).find(node=>node.props?.['aria-label']==='Task steps').props.ref.current={{
 querySelectorAll:()=>nodes(waiting).filter(node=>node.props?.['data-trace-event']).map(node=>({{
   dataset:{{traceEvent:node.props['data-trace-event']}},
   scrollIntoView:()=>tiedFollow.push(node.props['data-trace-event']),
 }})),
}};
effects.at(-1)();assert.deepEqual(tiedFollow,['read-event']);
sockets[0].onmessage({{data:JSON.stringify({{type:'entry',entry:{{
 id:'result-event',run_id:'query-run',call_id:'read-call',at:103,channel:'result',line:'vault.read returned',
 payload:{{kind:'tool',phase:'result',name:'vault.read',status:'returned',duration_ms:12,result:{{content:'Actual returned evidence',nested:{{source_ref:'source://captured',ok:true,results:[{{ref:'Architecture/Launch',why:'The accepted launch route'}}]}}}}}},
}}}})}});
const arrived=render(100);
let rendered=JSON.stringify(arrived);
assert(rendered.includes('Actual returned evidence'));
assert(rendered.includes('Executive'));
assert(rendered.includes('pointer-events-auto'));
assert(rendered.includes('Expand any row to see the evidence'));
assert(rendered.includes('LIVE'));
const afterRow=nodes(arrived).find(node=>node.type==='details'&&node.key==='read-event');
assert.equal(afterRow.key,beforeRow.key);assert.equal(afterRow.props.open,undefined);
assert(!nodes(arrived).some(node=>node.type==='details'&&node.key==='result-event'));
assert(words(afterRow).includes('What was requested'));assert(words(afterRow).includes('What came back'));
assert(words(afterRow).includes('Source file'));assert(words(afterRow).includes('Item 1'));
assert(words(afterRow).includes('The accepted launch route'));assert(!words(afterRow).includes('Waiting for a result'));
const packet=nodes(arrived).find(node=>node.type==='details'&&node.key==='packet-event');
const packetItems=nodes(packet).filter(node=>node.type==='li');
assert.deepEqual(packetItems.map(item=>item.key),['agent','objective','bindings']);
assert(words(packet).includes('Who is responsible'));assert(words(packet).includes('Current facts and constraints'));
assert(words(packet).includes('Source file'));assert(words(packet).includes('Current only'));
assert(!words(packet).includes('Header should not appear'));assert(!words(packet).includes('"source_ref"'));
// Follow mode scrolls only until reading starts; new rows cannot move the
// reading position. The same existing control explicitly resumes following.
const scroll=nodes(arrived).find(node=>node.props?.['aria-label']==='Task steps').props.ref;
const scrolled=[];let dom=arrived;
scroll.current={{querySelectorAll(selector){{
 assert.equal(selector,'[data-trace-event]');
 return nodes(dom).filter(node=>node.props?.['data-trace-event']).map(node=>({{
   dataset:{{traceEvent:node.props['data-trace-event']}},
   scrollIntoView(options){{scrolled.push({{id:node.props['data-trace-event'],block:options.block}});}},
 }}));
}}}};
effects.at(-1)();assert.deepEqual(scrolled,[{{id:'result-event',block:'nearest'}}]);
let stopped=0;
render(100).props.onPointerDown({{stopPropagation:()=>stopped++}});
render(100).props.onWheel({{stopPropagation:()=>stopped++}});
render(100).props.onFocusCapture({{target:{{tagName:'SUMMARY'}}}});
render(100).props.onKeyDown({{key:'Escape',stopPropagation:()=>stopped++}});
assert.deepEqual(kept,[true,true,true]);assert.equal(stopped,3);assert.equal(closed,1);
let paused=render(100);effects.at(-1)();assert.equal(scrolled.length,1);
let follow=nodes(paused).find(node=>node.type==='button'&&words(node)==='Follow latest');
assert.equal(follow.props['aria-pressed'],false);follow.props.onClick();
render(100);effects.at(-1)();assert.equal(scrolled.length,2);
render(100).props.onClickCapture({{target:{{closest:selector=>selector==='summary'?{{}}:null}}}});
render(100);effects.at(-1)();assert.equal(scrolled.length,2);
assert(JSON.stringify(render(100,true)).includes('Stays open while you read'));
// The footer follows the latest event's exact run even if another run was
// inserted later in the grouped matrix.
sockets[0].onmessage({{data:JSON.stringify({{type:'entry',entry:{{id:'second-run',run_id:'news-run',at:104,channel:'run',line:'News started',payload:{{kind:'run',task_title:'News',agent_title:'Darwin',status:'running'}}}}}})}});
sockets[0].onmessage({{data:JSON.stringify({{type:'entry',entry:{{id:'timing',run_id:'query-run',call_id:'query-run:model:1',step:1,at:105,channel:'model',line:'Timing',payload:{{kind:'model',phase:'result',metrics:{{generation_ms:200,first_public_delta_ms:60}}}}}}}})}});
const footer=nodes(render(100)).find(node=>node.props?.['aria-live']==='polite');
assert(words(footer).startsWith('Executive · '));assert(!words(footer).includes('Darwin'));
const measured=render(100);
const measuredRow=nodes(measured).find(node=>node.type==='details'&&node.key==='read-event');
assert.equal(measuredRow.key,beforeRow.key);assert.equal(measuredRow.props.open,undefined);
assert(words(measuredRow).includes('Response measurements'));
assert(words(measuredRow).includes('Time to first text (ms)'));
assert(words(measuredRow).includes('First text 60 ms · Generation 200 ms · Resource wait 0.5 ms'));
assert(!nodes(measured).some(node=>node.type==='details'&&node.key==='query-run:model:1'));
assert(!words(measured).includes('Generate the next response'));
nodes(render(100)).find(node=>node.type==='button'&&words(node)==='Follow latest').props.onClick();
dom=render(100);effects.at(-1)();
assert.deepEqual(scrolled.at(-1),{{id:measuredRow.props['data-trace-event'],block:'nearest'}});
const numberedKeys=tree=>nodes(tree).filter(node=>node.type==='details'
 &&[node.props.children].flat().some(child=>child?.type==='summary'
   &&child.props.className?.includes('grid-cols-['))).map(node=>node.key);
const beforeOrphan=numberedKeys(dom);
assert.deepEqual(beforeOrphan,['run-event','packet-event','read-event','second-run']);
for(const [id,at,phase,label] of [
 ['orphan-wait',106,'waiting','Waiting for model availability'],
 ['orphan-start',107,'started','Preparing the next response'],
]) {{
 sockets[0].onmessage({{data:JSON.stringify({{type:'entry',entry:{{id,at,run_id:'query-run',call_id:'query-run:model:2',step:2,channel:'model',line:'Provider lifecycle',payload:{{kind:'model',phase}}}}}})}});
 const active=render(100);
 assert(nodes(active).some(node=>node.type==='p'&&node.props.role==='status'&&words(node).includes(label)));
 assert.deepEqual(numberedKeys(active),beforeOrphan);
}}
sockets[0].onmessage({{data:JSON.stringify({{type:'entry',entry:{{id:'orphan-error',run_id:'query-run',call_id:'query-run:model:2',step:2,at:108,channel:'model',line:'Provider failed',payload:{{kind:'model',phase:'error',error:'Provider unavailable for step two'}}}}}})}});
const withOrphan=render(100);
assert(words(withOrphan).includes('Provider unavailable for step two'));
assert(words(withOrphan).includes('1 failed or interrupted'));
assert.deepEqual(numberedKeys(withOrphan),beforeOrphan); // Diagnostic does not consume an action number.
assert(!words(nodes(withOrphan).find(node=>node.type==='details'&&node.key==='read-event')).includes('Provider unavailable for step two'));
// Heimdall successfully observing a failed Task is not a failed inspection.
// The finding remains explicit beside the authoritative returned-call state.
for(const entry of [
 {{id:'audit-run',run_id:'audit',at:109,channel:'run',line:'Audit started',payload:{{kind:'run',task_title:'Audit',agent_title:'Heimdall',status:'running'}}}},
 {{id:'inspect',run_id:'audit',call_id:'inspect-call',at:110,channel:'tool',line:'Inspect Task',payload:{{kind:'tool',phase:'start',name:'task.inspect',arguments:{{task:'Tasks/Link'}}}}}},
 {{id:'inspect-result',run_id:'audit',call_id:'inspect-call',at:111,channel:'result',line:'Inspection returned',payload:{{kind:'tool',phase:'result',name:'task.inspect',status:'returned',result:{{task:'Tasks/Link',status:'failed',runs:[{{summary:'Previous source lookup failed'}}]}}}}}},
 {{id:'health',run_id:'audit',call_id:'health-call',at:112,channel:'tool',line:'Inspect health',payload:{{kind:'tool',phase:'start',name:'harness.status',arguments:{{}}}}}},
 {{id:'health-result',run_id:'audit',call_id:'health-call',at:113,channel:'result',line:'Health returned',payload:{{kind:'tool',phase:'result',name:'harness.status',status:'returned',result:{{status:'degraded',recent_failures:2}}}}}},
 {{id:'bad-inspect',run_id:'audit',call_id:'bad-inspect-call',at:114,channel:'tool',line:'Inspect Task',payload:{{kind:'tool',phase:'start',name:'task.inspect',arguments:{{task:'Tasks/Link'}}}}}},
 {{id:'bad-inspect-result',run_id:'audit',call_id:'bad-inspect-call',at:115,channel:'result',line:'Inspection error',payload:{{kind:'tool',phase:'result',name:'task.inspect',status:'error',result:{{error:'Evidence store unavailable'}}}}}},
]) sockets[0].onmessage({{data:JSON.stringify({{type:'entry',entry}})}});
const inspected=render(100);
for(const [id,finding,state] of [['inspect','Inspected task: Failed','Returned'],['health','Harness health: Degraded','Returned'],['bad-inspect','Evidence store unavailable','Error']]) {{
 const row=nodes(inspected).find(node=>node.type==='details'&&node.key===id);
 const summary=[row.props.children].flat().find(node=>node?.type==='summary');
 assert.equal(words(summary.props.children[2]),state);
 assert(words(row).includes(finding));
 if(state==='Returned') assert(words(summary).includes(finding));
 else assert(!words(summary).includes('Inspected task:'));
}}
assert(words(nodes(inspected).find(node=>node.type==='details'&&node.key==='inspect')).includes('Previous source lookup failed'));
// Changing the activation hides old rows before the effect resets state.
assert(!JSON.stringify(render(200)).includes('Actual returned evidence'));
sockets[0].onclose();assert.equal(timers.length,1);
cleanup();assert.equal(sockets[0].closed,true);assert.deepEqual(cleared,[1]);
timers[0]();assert.equal(sockets.length,1); // A queued callback cannot reopen after unmount.
const afterCleanup=JSON.stringify(state);
sockets[0].onmessage({{data:JSON.stringify({{type:'entry',entry:{{at:300,channel:'result',line:'late'}}}})}});
assert.equal(JSON.stringify(state),afterCleanup);
""")


def test_graph_reconnect_before_packet_retains_task_trace_start():
    node_check(rf"""
import {{ strict as assert }} from 'node:assert';
import fs from 'node:fs';
import vm from 'node:vm';
import {{ createRequire }} from 'node:module';
import {{ applyTraceFrame }} from {json.dumps((PANES / 'action-trace.ts').as_uri())};
const require=createRequire({json.dumps((UI / 'package.json').as_uri())});
const ts=require('typescript');
const source=fs.readFileSync({json.dumps(str(PANES / 'graph-backdrop.tsx'))},'utf8');
const tree=ts.createSourceFile('graph.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const functions=tree.statements.filter(node=>ts.isFunctionDeclaration(node)
  && ['activityFromWire','latestActivityTransaction'].includes(node.name?.text));
let callback;
const visit=node=>{{
  if(ts.isCallExpression(node)&&node.expression.getText(tree)==='onKnowledgeActivity') callback=node.arguments[0];
  ts.forEachChild(node,visit);
}};
visit(tree);
assert.equal(functions.length,2);assert(callback);
let state=null;let now=1788665811270;const timers=[];
const context={{setActivity:next=>{{state=typeof next==='function'?next(state):next;}},
  activityKey:{{current:0}},lingerTimer:{{current:null}},FOCUS_LINGER_MS:6000,MAIN_GRAPH_ID:'main',
  Date:{{now:()=>now}},window:{{clearTimeout(){{}},setTimeout(fn,ms){{timers.push({{fn,ms}});return timers.length;}}}}}};
const compiled=ts.transpileModule(functions.map(node=>node.getText(tree)).join('\n')
  +'\n({{replay:latestActivityTransaction,fromWire:activityFromWire,receive:'+callback.getText(tree)+'}})',
  {{compilerOptions:{{target:ts.ScriptTarget.ESNext}}}}).outputText;
const {{replay,fromWire,receive}}=vm.runInNewContext(compiled,context);
const wire=(phase,at)=>({{phase,at,query:'Harness health',graph_id:'main',refs:[]}});
const start=wire('query_started',1788665807345);
// The presenter connects after query_started but before packet compilation.
// Exercise the real replay function and the real GraphBackdrop event callback.
const snapshot=replay([start]);assert.equal(snapshot.length,1);
snapshot.forEach(receive);assert.equal(state.startedAt,start.at);
receive(fromWire(wire('path',1788665807518)));assert.equal(state.startedAt,start.at);
const entries=applyTraceFrame([],JSON.stringify({{type:'snapshot',entries:[
  {{at:1788665807000,channel:'run',line:'Old Task',detail:[]}},
  {{at:1788665807353,channel:'run',line:'JARVIS started Query',detail:[]}},
  {{at:1788665807518,channel:'activation',line:'JARVIS packet for Query',detail:[]}},
  {{at:1788665808961,channel:'tool',line:'JARVIS → harness.status',detail:['{{}}']}},
  {{at:1788665809430,channel:'result',line:'harness.status returned',detail:['status=degraded']}},
  {{at:1788665810849,channel:'model',line:'Query provider timing',detail:['Public TTFT: 436 ms']}},
]}}),state.startedAt);
assert.equal(entries.findLast(entry=>entry.channel==='run')?.line,'JARVIS started Query');
assert(!entries.some(entry=>entry.line==='Old Task'));
assert.equal(entries.find(entry=>entry.channel==='result')?.detail,'status=degraded');
receive(fromWire(wire('query_completed',now)));
assert.equal(state.startedAt,start.at);assert.equal(timers.at(-1).ms,6000);
timers.at(-1).fn();assert.equal(state,null);
// A failure before packet compilation still gets its bounded terminal linger;
// a cleared or expired transaction cannot resurrect the popup on reconnect.
assert.equal(replay([start,wire('query_completed',now)]).length,2);
assert.equal(replay([start,wire('cleared',now)]).length,0);
assert.equal(replay([start,wire('query_completed',now-6000)]).length,0);
receive(fromWire(wire('query_started',now+1)));assert.equal(state.startedAt,now+1);
""")


def test_actual_parent_retains_inspection_after_activity_linger_and_clears_on_hide():
    node_check(rf"""
import {{ strict as assert }} from 'node:assert';
import fs from 'node:fs';
import vm from 'node:vm';
import {{ createRequire }} from 'node:module';
const require=createRequire({json.dumps((UI / 'package.json').as_uri())});
const ts=require('typescript');
const source=fs.readFileSync({json.dumps(str(PANES / 'graph-backdrop.tsx'))},'utf8');
const tree=ts.createSourceFile('graph.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
let receive,visibilityEffect,popup;
const visit=node=>{{
 if(ts.isCallExpression(node)&&node.expression.getText(tree)==='onKnowledgeActivity') receive=node.arguments[0];
 if(ts.isCallExpression(node)&&node.expression.getText(tree)==='useEffect'
    &&node.arguments[0]?.getText(tree).includes('setTraceInspectionSince')
    &&node.arguments[1]?.getText(tree).includes('lockMode')) visibilityEffect=node.arguments[0];
 if(ts.isJsxSelfClosingElement(node)&&node.tagName.getText(tree)==='ActionTracePopup') {{
   popup=node.parent;
   while(popup&&!ts.isConditionalExpression(popup)) popup=popup.parent;
 }}
 ts.forEachChild(node,visit);
}};
visit(tree);assert(receive);assert(visibilityEffect);assert(popup);
const timers=[];
const context={{activity:null,traceInspectionSince:null,traceDismissedSince:null,
 visible:true,lockMode:false,activityKey:{{current:0}},lingerTimer:{{current:null}},FOCUS_LINGER_MS:6000,
 Date:{{now:()=>1000}},ActionTracePopup:'ActionTracePopup',exports:{{}},
 window:{{clearTimeout(){{}},setTimeout(fn,ms){{timers.push({{fn,ms}});return timers.length;}}}},
 require:name=>{{assert.equal(name,'react/jsx-runtime');return{{jsx:(type,props)=>({{type,props}})}}}},
}};
context.setActivity=next=>{{context.activity=typeof next==='function'?next(context.activity):next;}};
context.setTraceInspectionSince=next=>{{context.traceInspectionSince=next;}};
context.setTraceDismissedSince=next=>{{context.traceDismissedSince=next;}};
const compiled=ts.transpileModule('const receive='+receive.getText(tree)
 +';const visibilityEffect='+visibilityEffect.getText(tree)
 +';function popup(){{return '+popup.getText(tree)+';}};({{receive,visibilityEffect,popup}})',
 {{compilerOptions:{{target:ts.ScriptTarget.ESNext,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}}}).outputText;
const actual=vm.runInNewContext(compiled,context);
const event=(phase,at)=>({{phase,at,query:'Harness health',graphId:'main',refs:[]}});
assert.equal(actual.popup(),null);
actual.receive(event('query_started',100));
let view=actual.popup();assert.equal(view.props.since,100);assert.equal(view.props.keptOpen,false);
view.props.onKeepOpen(true);assert.equal(context.traceInspectionSince,100);
actual.receive(event('query_completed',1000));
assert.equal(timers.at(-1).ms,6000);timers.at(-1).fn();
assert.equal(context.activity,null); // The graph itself actually stops thinking.
view=actual.popup();assert(view);assert.equal(view.props.since,100);assert.equal(view.props.keptOpen,true);
// Keeping a previous trace does not freeze, replace or alter new Task activity.
actual.receive(event('query_started',1100));
assert.equal(context.activity.startedAt,1100);assert.equal(actual.popup().props.since,100);
actual.popup().props.onClose();
assert.equal(context.traceInspectionSince,null);assert.equal(context.traceDismissedSince,1100);
assert.equal(actual.popup(),null);
actual.receive(event('path',1150));assert.equal(actual.popup(),null); // Same dismissed Task stays closed.
actual.receive(event('query_started',1200));assert.equal(actual.popup().props.since,1200);
actual.popup().props.onKeepOpen(true);
actual.receive(event('cleared',1250));assert.equal(context.activity,null);assert(actual.popup());
actual.popup().props.onKeepOpen(false);assert.equal(actual.popup(),null);
// Visibility and secure-lock boundaries hide the component immediately, then
// reset only its disposable inspection state through the actual parent effect.
for(const boundary of ['visible','lockMode']) {{
 actual.receive(event('query_started',1300));actual.popup().props.onKeepOpen(true);
 if(boundary==='visible') context.visible=false;else context.lockMode=true;
 assert.equal(actual.popup(),null);actual.visibilityEffect();
 assert.equal(context.traceInspectionSince,null);assert.equal(context.traceDismissedSince,null);
 assert.equal(context.activity.startedAt,1300);
 context.visible=true;context.lockMode=false;
}}
""")


def test_long_run_retains_its_task_and_thinking_packet():
    node_check(f"""
import {{ strict as assert }} from 'node:assert';
import {{ applyTraceFrame, TRACE_ENTRY_LIMIT }} from {json.dumps((PANES / 'action-trace.ts').as_uri())};
const event=(id,channel,payload={{}})=>({{id:String(id),at:id,channel,line:'event'+id,run_id:'long-run',payload}});
let entries=[];
for(const entry of [event(1,'run',{{kind:'run'}}),event(2,'activation',{{kind:'packet',sections:[{{key:'objective',text:'The actual objective.'}}]}}),
  ...Array.from({{length:500}},(_,i)=>event(i+3,'result'))]) {{
  entries=applyTraceFrame(entries,JSON.stringify({{type:'entry',entry}}),1);
}}
assert.equal(entries.length,TRACE_ENTRY_LIMIT);
assert.equal(entries[0].id,'1'); assert.equal(entries[1].id,'2');
assert.equal(entries.at(-1).id,'502');
assert.equal(entries[1].payload.sections[0].text,'The actual objective.');
""")


def test_model_lifecycle_attaches_to_the_resulting_action_without_numbered_rows():
    projection_check(r"""
let entries=[];
const receive=entry=>{
 entries=trace.applyTraceFrame(entries,JSON.stringify({type:'entry',entry}),0);
 return trace.traceRuns(entries)[0];
};
const model=(id,at,phase,extra={})=>({id,at,channel:'model',line:'Provider lifecycle',
 run_id:'run',call_id:'run:model:1',step:1,payload:{kind:'model',phase,model:'selected-model',...extra}});
let run=receive(model('wait',100,'waiting'));
assert.equal(run.rows.length,0);assert.equal(run.modelRequests.length,1);
const requestId=run.modelRequests[0].id;
run=receive(model('start',110,'started'));
assert.equal(run.rows.length,0);assert.equal(run.modelRequests.length,1);
assert.equal(run.modelRequests[0].id,requestId);
run=receive(model('measurement',140,'result',{metrics:{first_public_delta_ms:61.4,generation_ms:200}}));
assert.equal(run.rows.length,0);assert.equal(run.modelRequests.length,1);
assert.deepEqual(run.modelRequests[0].entries.map(entry=>entry.id),['wait','start','measurement']);
run=receive({id:'action',at:150,run_id:'run',call_id:'run:1',step:1,channel:'tool',line:'Read article',
 payload:{kind:'tool',phase:'start',name:'vault.read',arguments:{ref:'Article A'}}});
assert.equal(run.rows.length,1);assert.equal(run.rows[0].id,'action');
assert.equal(run.rows[0].model.id,requestId);assert.equal(run.modelRequests.length,0);
assert.equal(trace.traceRowState(run.rows[0]),'Waiting'); // Measured generation is not a Tool result.
assert.equal(run.rows[0].result,undefined);
run=receive({id:'tool-result',at:160,run_id:'run',call_id:'run:1',step:1,channel:'result',line:'Read returned',
 payload:{kind:'tool',phase:'result',name:'vault.read',status:'returned',result:'Accepted article text'}});
assert.equal(run.rows.length,1);assert.equal(run.rows[0].id,'action');
assert.equal(run.rows[0].result.id,'tool-result');assert.equal(run.rows[0].model.id,requestId);
assert.equal(trace.traceRowState(run.rows[0]),'Returned');
assert(!run.rows.some(row=>row.entry.channel==='model'));
""")


def test_model_measurements_keep_exact_run_step_binding_through_replay_and_late_results():
    projection_check(r"""
const model=(id,at,run,step,phase,ms)=>({id,at,run_id:run,step,call_id:'model:'+step,
 channel:'model',line:'Provider',payload:{kind:'model',phase,metrics:{generation_ms:ms}}});
const action=(id,at,run,step,name='vault.read')=>({id,at,run_id:run,step,call_id:'tool:'+step,
 channel:'tool',line:'Tool requested',payload:{kind:'tool',phase:'start',name,arguments:{}}});
const wires=[
 model('a-wait',100,'a',1,'waiting',1),model('b-wait',101,'b',1,'waiting',2),
 model('a-start',102,'a',1,'started',3),model('b-result',103,'b',1,'result',4),
 action('b-action',104,'b',1),action('a-action',105,'a',1),
 model('a-step2',106,'a',2,'result',20),action('a-response',107,'a',2,'task.complete'),
];
let entries=trace.applyTraceFrame([],JSON.stringify({type:'snapshot',entries:wires}),0);
let runs=trace.traceRuns(entries);
const actionKeys=runs.flatMap(run=>run.rows.map(row=>row.id));
const late=model('a-late',108,'a',1,'result',10);
entries=trace.applyTraceFrame(entries,JSON.stringify({type:'entry',entry:late}),0);
entries=trace.applyTraceFrame(entries,JSON.stringify({type:'entry',entry:late}),0);
runs=trace.traceRuns(entries);
assert.deepEqual(runs.flatMap(run=>run.rows.map(row=>row.id)),actionKeys);
const a=runs.find(run=>run.id==='a'),b=runs.find(run=>run.id==='b');
assert.deepEqual(a.rows.find(row=>row.id==='a-action').model.entries.map(entry=>entry.id),['a-wait','a-start','a-late']);
assert.deepEqual(b.rows[0].model.entries.map(entry=>entry.id),['b-wait','b-result']);
assert.deepEqual(a.rows.find(row=>row.id==='a-response').model.entries.map(entry=>entry.id),['a-step2']);
assert.equal(a.rows.find(row=>row.id==='a-response').model.entries[0].payload.metrics.generation_ms,20);
assert(runs.every(run=>run.modelRequests.length===0));
assert(runs.every(run=>run.rows.every(row=>row.entry.payload.kind==='tool')));
// Snapshot arrival order and duplicate delivery cannot change a valid explicit association.
const replay=trace.traceRuns(trace.applyTraceFrame([],JSON.stringify({type:'snapshot',entries:[late,...wires].reverse()}),0));
assert.deepEqual(replay,runs);
""")


def test_model_errors_missing_identity_and_ambiguous_steps_stay_unnumbered():
    projection_check(r"""
const model={id:'model',at:100,run_id:'r',call_id:'model:1',step:1,channel:'model',line:'Provider unavailable',
 payload:{kind:'model',phase:'error',error:'Provider unavailable'}};
const action={id:'action',at:110,run_id:'r',call_id:'tool:1',step:1,channel:'tool',line:'Tool requested',
 payload:{kind:'tool',phase:'start',name:'vault.read',arguments:{}}};
const project=entries=>trace.traceRuns(trace.applyTraceFrame([],JSON.stringify({type:'snapshot',entries}),0));
for(const phase of ['waiting','started','result','error','interrupted']) {
 const run=project([{...model,payload:{...model.payload,phase}}])[0];
 assert.equal(run.rows.length,0);assert.equal(run.modelRequests.length,1);
 assert.equal(run.modelRequests[0].entries[0].payload.phase,phase);
 assert.equal(run.status,'');
}
const cases=[
 [model,{...action,step:2}],
 [{...model,step:undefined},action], [model,{...action,step:undefined}],
 [{...model,call_id:undefined},action], [model,{...action,call_id:undefined}],
 [{...model,run_id:undefined},{...action,run_id:undefined}],
 [model,{...action,run_id:'other'}],
 [model,{...model,id:'other-model',at:101,call_id:'model:retry'},action],
 [model,{...model,id:'inconsistent-step',at:101,step:2},action],
 [model,action,{...action,id:'other-action',at:111,call_id:'tool:other'}],
 ...[0,-1,1.5].map(step=>[{...model,step},{...action,step}]),
];
for(const wires of cases) {
 const runs=project(wires);
 assert(runs.every(run=>run.rows.every(row=>row.model===undefined)),JSON.stringify(wires));
 assert(runs.every(run=>run.rows.every(row=>row.entry.payload.kind!=='model')));
 assert(runs.some(run=>run.modelRequests.length>0));
 const diagnostic=runs.flatMap(run=>run.modelRequests.flatMap(request=>request.entries));
 assert(diagnostic.some(entry=>entry.payload.error==='Provider unavailable'));
}
// Model call identity alone cannot associate a request with a differently numbered action.
assert.equal(project([model,{...action,call_id:model.call_id,step:2}])[0].rows[0].model,undefined);
const legacy=project([{id:'legacy-model',at:100,channel:'model',line:'Provider timing',detail:['Public TTFT: 61.4 ms']}])[0];
assert.equal(legacy.rows.length,0);assert.equal(legacy.modelRequests.length,1);
assert.equal(legacy.modelRequests[0].entries[0].detail,'Public TTFT: 61.4 ms');
""")


def test_packet_discloses_knowledge_omission_and_exact_excerpt_without_action_rows():
    node_check(rf"""
import {{ strict as assert }} from 'node:assert';
import fs from 'node:fs';
import vm from 'node:vm';
import {{ createRequire }} from 'node:module';
import * as trace from {json.dumps((PANES / 'action-trace.ts').as_uri())};
const require=createRequire({json.dumps((UI / 'package.json').as_uri())});
const ts=require('typescript');
const source=fs.readFileSync({json.dumps(str(PANES / 'action-trace-popup.tsx'))},'utf8');
const compiled=ts.transpileModule(source+'\nmodule.exports.TestPacket = Packet;',{{compilerOptions:{{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}}}).outputText;
const jsx=(type,props,key)=>typeof type==='function'?type(props):({{type,props,key}});
const module={{exports:{{}}}};
vm.runInNewContext(compiled,{{module,exports:module.exports,require:name=>
 name==='react'?{{}}:name==='react/jsx-runtime'?{{jsx,jsxs:jsx}}:name==='@/lib/api'?{{}}:
 name==='./action-trace'?trace:(()=>{{throw Error(name);}})(),
}});
const nodes=value=>Array.isArray(value)?value.flatMap(nodes):value&&typeof value==='object'?[value,...nodes(value.props?.children)]:[];
const words=value=>Array.isArray(value)?value.map(words).join(''):value&&typeof value==='object'?words(value.props?.children):value==null?'':String(value);
const accounting={{version:1,status:'selected',considered_count:6,included_count:2,omitted_count:4,entries_omitted:3,
 estimated_used_tokens:950,estimated_budget_tokens:1200,entries:[
 {{ref:'Knowledge/Full',title:'Complete article',origin:'direct',decision:'included',reason:'selected',content:'full',body_start:0,body_end:400,body_chars:400,omitted_chars:0,included_estimated_tokens:120}},
 {{ref:'Knowledge/Excerpt',title:'Excerpt article',origin:'graph',seed_ref:'Knowledge/Full',decision:'included',reason:'selected',content:'excerpt',body_start:3,body_end:1200,body_chars:1500,omitted_chars:303,included_estimated_tokens:830}},
 {{ref:'Knowledge/Omitted',title:'Omitted article',origin:'direct',decision:'omitted',reason:'token_budget',content:'none',body_start:null,body_end:null,body_chars:500,omitted_chars:500,included_estimated_tokens:0}},
]}};
const packet=data=>module.exports.TestPacket({{entry:{{payload:{{kind:'packet',sections:[
 {{key:'knowledge',title:'Relevant Knowledge',text:'## Relevant Knowledge\nExact original supplied text.',chars:59}},
],...(data?{{knowledge_accounting:data}}:{{}})}}}}}});
const tree=packet(accounting), text=words(tree);
assert(text.includes('6 considered · 2 supplied · 4 omitted'));
assert(text.includes('950 of 1,200'));
assert(text.includes('Full Article'));assert(text.includes('Excerpt'));
assert(text.includes('Body characters 4–1200 supplied of 1,500'));
assert(text.includes('Linked from Knowledge/Full'));
assert(text.includes('Did not fit the Knowledge budget'));
assert(text.includes('3 additional candidate details'));
assert(text.includes('Exact original supplied text.'));
assert.equal(nodes(tree).filter(node=>node.type==='li').length,1); // Diagnostics stay inside Knowledge.
assert(!words(packet()).includes('What Knowledge reached'));
assert(!words(packet({{...accounting,version:2}})).includes('What Knowledge reached'));
const empty=words(packet({{...accounting,status:'no_matches',considered_count:0,included_count:0,omitted_count:0,entries:[],entries_omitted:0}}));
assert(empty.includes('No eligible Knowledge matched this search.'));
assert(!empty.includes('Did not fit'));assert(!empty.includes('additional candidate'));
// A bounded public projection can keep the identity but remove later fields.
const clipped=words(packet({{...accounting,truncated:true,entries_omitted:0,entries:[
 {{ref:'Knowledge/Clipped',title:'Clipped article'}},
 {{ref:'Knowledge/Included',title:'Included article',decision:'included'}},
]}}));
assert(clipped.includes('Decision not reported'));
assert(clipped.includes('Search origin not reported'));
assert(clipped.includes('Body details not reported'));
assert(clipped.includes('Candidate details were shortened'));
assert(!clipped.includes('Omitted'));assert(!clipped.includes('Direct search match'));
assert(!clipped.includes('No body supplied'));
""")
