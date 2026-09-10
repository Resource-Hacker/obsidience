"""Latency is exact correlated measurement data, never another action step."""

import json

from obsidience.tests.test_action_trace_popup import PANES, UI, node_check, projection_check


FACTORY = r"""
const latency=(id,at,stage,monotonic_ms,fields={})=>({id,at,channel:'measurement',line:'Measured phase',
 payload:{kind:'latency',stage,monotonic_ms,...fields}});
const frame=entry=>JSON.stringify({type:'entry',entry});
const snapshot=entries=>JSON.stringify({type:'snapshot',entries});
const task=(run_id,at)=>({id:run_id+'-start',run_id,at,channel:'run',line:'Task started',
 payload:{kind:'run',task_title:run_id,status:'running'}});
"""


def test_early_measurements_attach_only_after_exact_unique_turn_run_binding():
    projection_check(FACTORY + r"""
let entries=trace.applyTraceFrame([],snapshot([
 latency('first',100,'first_partial',120,{turn_id:'turn-a'}),
 latency('onset',101,'speech_onset',100,{turn_id:'turn-a'}),
 task('unrelated',102),
 latency('final',103,'input_final',130,{turn_id:'turn-a',duration_ms:7.5}),
]),100);
let runs=trace.traceRuns(entries);
assert.equal(runs.find(r=>r.id==='unrelated').latencyEntries.length,0);
let early=runs.find(r=>r.id==='latency:turn:turn-a');
assert.equal(early.rows.length,0);
assert.deepEqual(early.latencyEntries.map(e=>e.id),['onset','first','final']);
assert.equal(early.latencyEntries[0].latency.durationMs,undefined);
entries=trace.applyTraceFrame(entries,frame(task('actual',104)),100);
assert.equal(trace.traceRuns(entries).find(r=>r.id==='actual').latencyEntries.length,0);
entries=trace.applyTraceFrame(entries,frame({...latency('binding',105,'activation',140,
 {turn_id:'turn-a',run_id:'actual',duration_ms:2}),run_id:'actual'}),100);
runs=trace.traceRuns(entries);
assert(!runs.some(r=>r.id==='latency:turn:turn-a'));
const actual=runs.find(r=>r.id==='actual');
assert.deepEqual(actual.latencyEntries.map(e=>e.id),['onset','first','final','binding']);
assert.equal(actual.rows.length,1);assert.equal(actual.rows[0].id,'actual-start');
assert.equal(actual.at,104); // Early speech timing does not change the Task start.
assert.equal(runs.find(r=>r.id==='unrelated').latencyEntries.length,0);
""")


def test_interleaved_turns_conflicts_and_missing_identity_do_not_guess():
    projection_check(FACTORY + r"""
const entries=trace.applyTraceFrame([],snapshot([
 latency('a-early',100,'input_final',100,{turn_id:'a'}),
 latency('b-early',101,'input_final',101,{turn_id:'b'}),
 latency('a-bind',102,'activation',102,{turn_id:'a',run_id:'run-a'}),
 latency('b-bind',103,'activation',103,{turn_id:'b',run_id:'run-b'}),
 latency('conflict',104,'activation',104,{turn_id:'a',run_id:'run-c'}),
 latency('orphan1',105,'speech_onset',105,{speech_sequence:3,generation:1}),
 latency('orphan2',106,'first_partial',106,{speech_sequence:3,generation:1}),
]),100);
const runs=trace.traceRuns(entries);
assert.deepEqual(runs.find(r=>r.id==='latency:turn:a').latencyEntries.map(e=>e.id),['a-early']);
assert.deepEqual(runs.find(r=>r.id==='run-a').latencyEntries.map(e=>e.id),['a-bind']);
assert.deepEqual(runs.find(r=>r.id==='run-c').latencyEntries.map(e=>e.id),['conflict']);
assert.deepEqual(runs.find(r=>r.id==='run-b').latencyEntries.map(e=>e.id),['b-early','b-bind']);
assert.equal(runs.filter(r=>r.id.startsWith('latency:event:')).length,2);
assert(runs.every(r=>r.rows.length===0));
""")


def test_popup_activation_cutoff_preserves_only_exact_bound_earlier_timings():
    projection_check(FACTORY + r"""
let entries=trace.applyTraceFrame([],snapshot([
 latency('old-unrelated',10,'input_final',10,{turn_id:'old'}),
 latency('input',90,'input_final',90,{turn_id:'current'}),
 latency('preparation',91,'preparation',91,{turn_id:'current',duration_ms:1}),
 task('run',100),
]),100);
assert.deepEqual(trace.traceEntriesSince(entries,100).map(e=>e.id),['run-start']);
// The popup can open at query_started before compilation supplies the bridge.
entries=trace.applyTraceFrame(entries,frame(latency('binding',102,'activation',102,
 {turn_id:'current',run_id:'run',duration_ms:2})),100);
const visible=trace.traceEntriesSince(entries,100);
assert.deepEqual(visible.map(e=>e.id),['input','preparation','run-start','binding']);
assert.equal(trace.traceRuns(visible).length,1);
assert.equal(trace.traceRuns(visible)[0].latencyEntries.length,3);
assert(entries.length<=trace.TRACE_ENTRY_LIMIT);
""")


def test_latency_validation_preserves_absent_duration_and_rejects_malformed_identity():
    projection_check(FACTORY + r"""
const good=latency('good',100,'first_pcm',10,{turn_id:'turn',run_id:'run',speech_sequence:0,generation:0});
const badPayloads=[
 {stage:'invented'}, {stage:'__proto__'}, {monotonic_ms:-1}, {monotonic_ms:null}, {monotonic_ms:'10'},
 {monotonic_ms:Infinity}, {duration_ms:-1}, {duration_ms:null}, {duration_ms:'3'}, {duration_ms:true},
 {speech_sequence:0.5}, {speech_sequence:Number.MAX_SAFE_INTEGER+1}, {generation:-1},
 {turn_id:''}, {turn_id:'x'.repeat(161)}, {turn_id:'bad\nturn'}, {run_id:'x'.repeat(161)},
];
for(const changes of badPayloads){
 const bad={...good,payload:{...good.payload,...changes}};
 assert.deepEqual(trace.applyTraceFrame([],frame(bad),100),[],JSON.stringify(changes));
}
assert.deepEqual(trace.applyTraceFrame([],frame({...good,run_id:'different'}),100),[]);
assert.deepEqual(trace.applyTraceFrame([],frame({...good,channel:'latency',payload:{kind:'tool'}}),100),[]);
assert.deepEqual(trace.applyTraceFrame([],frame({...good,channel:'measurement',payload:{kind:'tool'}}),100),[]);
let entries=trace.applyTraceFrame([],frame(good),100);
assert.equal(entries[0].latency.durationMs,undefined);
entries=trace.applyTraceFrame([],frame({...good,payload:{...good.payload,duration_ms:0}}),100);
assert.equal(entries[0].latency.durationMs,0); // A reported zero is distinct from absence.
assert.equal(trace.traceRuns(entries)[0].rows.length,0);
""")


def test_late_measurements_and_replay_preserve_packet_actions_and_early_timing():
    projection_check(FACTORY + r"""
let entries=trace.applyTraceFrame([],snapshot([
 latency('input',100,'input_final',100,{turn_id:'turn'}),task('run',101),
 {id:'packet',at:102,run_id:'run',channel:'activation',line:'Packet',payload:{kind:'packet',sections:[]}},
 latency('bridge',103,'activation',103,{turn_id:'turn',run_id:'run',duration_ms:3}),
]),100);
for(let i=0;i<300;i++)entries=trace.applyTraceFrame(entries,frame({id:'action-'+i,run_id:'run',at:104+i,
 channel:'status',line:'Recorded event',payload:{kind:'context',projection:{}}}),100);
const late=latency('audio',500,'first_output_write',500,{turn_id:'turn',run_id:'run',speech_sequence:0});
entries=trace.applyTraceFrame(entries,frame(late),100);
entries=trace.applyTraceFrame(entries,JSON.stringify({type:'replay',entries:[late]}),100);
assert(entries.length<=trace.TRACE_ENTRY_LIMIT);
assert(entries.some(e=>e.id==='packet'));assert(entries.some(e=>e.id==='run-start'));
assert(entries.some(e=>e.id==='input'));assert(entries.some(e=>e.id==='bridge'));
const run=trace.traceRuns(entries).find(r=>r.id==='run');
assert.deepEqual(run.latencyEntries.map(e=>e.id),['input','bridge','audio']);
assert(!run.rows.some(row=>row.entry.latency));
""")


def test_rendered_timeline_is_unnumbered_readable_and_keeps_model_wait_visible():
    node_check(f"""
import fs from 'node:fs';import vm from 'node:vm';import {{strict as assert}} from 'node:assert';
import ts from {json.dumps((UI / 'node_modules/typescript/lib/typescript.js').as_uri())};
import * as trace from {json.dumps((PANES / 'action-trace.ts').as_uri())};
const source=fs.readFileSync({json.dumps(str(PANES / 'action-trace-popup.tsx'))},'utf8');
const compiled=ts.transpileModule(source,{{compilerOptions:{{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}}}).outputText;
const state=[],effects=[],sockets=[];let cursor=0;
const react={{useState(initial){{const i=cursor++;if(!(i in state))state[i]=initial;return[state[i],next=>state[i]=typeof next==='function'?next(state[i]):next];}},
 useRef(initial){{const i=cursor++;if(!(i in state))state[i]={{current:initial}};return state[i];}},useEffect(fn){{effects.push(fn);}}}};
const jsx=(type,props,key)=>typeof type==='function'?{{...type(props),key}}:{{type,props,key}};
class Socket{{constructor(url){{sockets.push(this);}}close(){{}}}}
const module={{exports:{{}}}};
vm.runInNewContext(compiled,{{module,exports:module.exports,WebSocket:Socket,setTimeout:()=>1,clearTimeout:()=>{{}},
 require:name=>name==='react'?react:name==='react/jsx-runtime'?{{jsx,jsxs:jsx}}:name==='@/lib/api'?{{WS_BASE:'ws://isolated'}}:trace}});
const render=()=>{{cursor=0;return module.exports.ActionTracePopup({{since:100}});}};
const nodes=value=>Array.isArray(value)?value.flatMap(nodes):value&&typeof value==='object'?[value,...nodes(value.props?.children)]:[];
const words=value=>Array.isArray(value)?value.map(words).join(' '):value&&typeof value==='object'?words(value.props?.children):value==null?'':String(value);
render();const cleanup=effects[0]();
sockets[0].onmessage({{data:JSON.stringify({{type:'snapshot',entries:[
 {{id:'start',at:100,run_id:'r',channel:'run',line:'Task started',payload:{{kind:'run',task_title:'Query',status:'running'}}}},
 {{id:'model',at:102,run_id:'r',call_id:'model-1',step:1,channel:'model',line:'Waiting',payload:{{kind:'model',phase:'waiting'}}}},
 {{id:'speech',at:99,channel:'measurement',line:'Input',payload:{{kind:'latency',stage:'input_final',monotonic_ms:99,turn_id:'t'}}}},
 {{id:'binding',at:104,run_id:'r',channel:'context',line:'Bound',payload:{{kind:'latency',stage:'activation',monotonic_ms:100,turn_id:'t',run_id:'r',duration_ms:12.5}}}},
 {{id:'last-latency',at:105,run_id:'r',channel:'model',line:'Wait measured',payload:{{kind:'latency',stage:'model_wait',monotonic_ms:101,turn_id:'t',duration_ms:0}}}},
]}})}});
const view=render();const text=words(view);
assert(text.includes('Latency timeline'));assert(text.includes('Elapsed from first recorded stage; durations may overlap'));
assert(text.includes('Input accepted'));assert(text.includes('12.5 ms'));assert(text.includes('0 ms'));assert(text.includes('Not reported'));
const waiting=nodes(view).find(node=>node.props?.role==='status'&&node.props['data-trace-event']==='model');
assert(waiting);assert(words(waiting).includes('Waiting for model availability'));
assert.equal(nodes(view).filter(node=>node.type==='table'&&node.props['aria-label']==='Latency timeline').length,1);
assert.deepEqual(nodes(view).filter(node=>node.props?.['data-latency-stage']).map(node=>node.props['data-latency-stage']),['input_final','activation','model_wait']);
const cells=row=>nodes(row).filter(node=>node.type==='td').map(words);
const timingRows=nodes(view).filter(node=>node.props?.['data-latency-stage']);
assert.deepEqual(timingRows.map(row=>cells(row).slice(1)),[['Not reported','0 ms'],['12.5 ms','1 ms'],['0 ms','2 ms']]);
assert(nodes(view).some(node=>node.type==='th'&&words(node)==='Elapsed'));
assert(!nodes(view).some(node=>node.type==='details'&&['speech','binding','last-latency'].includes(node.key)));
const timeline=nodes(view).find(node=>node.type==='details'&&node.props['data-trace-event']==='last-latency');
assert(timeline);assert.equal(timeline.props.open,undefined);
const followed=[];
nodes(view).find(node=>node.props?.['aria-label']==='Task steps').props.ref.current={{querySelectorAll:()=>nodes(view)
 .filter(node=>node.props?.['data-trace-event']).map(node=>({{dataset:{{traceEvent:node.props['data-trace-event']}},scrollIntoView:()=>followed.push(node.props['data-trace-event'])}}))}};
effects.at(-1)();assert.deepEqual(followed,['last-latency']);
// Separate unbound turns have independent origins; anonymous events have none.
sockets[0].onmessage({{data:JSON.stringify({{type:'snapshot',entries:[
 {{id:'a-final',at:120,channel:'measurement',line:'Final',payload:{{kind:'latency',stage:'speech_final',monotonic_ms:1025,turn_id:'a'}}}},
 {{id:'b-first',at:121,channel:'measurement',line:'Partial',payload:{{kind:'latency',stage:'first_partial',monotonic_ms:2000,turn_id:'b'}}}},
 {{id:'a-first',at:122,channel:'measurement',line:'Partial',payload:{{kind:'latency',stage:'first_partial',monotonic_ms:1000,turn_id:'a'}}}},
 {{id:'anonymous',at:123,channel:'measurement',line:'Unbound',payload:{{kind:'latency',stage:'input_final',monotonic_ms:3000}}}},
]}})}});
const unboundView=render();
assert(words(unboundView).includes('no unique Task binding'));
const tables=nodes(unboundView).filter(node=>node.type==='table');
assert.equal(tables.length,3);
assert.deepEqual(tables.map(table=>nodes(table).filter(node=>node.props?.['data-latency-stage']).map(row=>cells(row).at(-1))),
 [['0 ms','25 ms'],['0 ms'],['Not reported']]);
cleanup();
""")
