"""Frozen trials remain visible inside one real Audit without claiming effects."""

import asyncio
from collections import deque
from contextvars import ContextVar
import json

import pytest

from obsidience.harness.execution import trace
from obsidience.tests.test_action_trace_popup import PANES, UI, node_check, projection_check
from obsidience.tests.test_evaluation_session import action, trial_runtime  # noqa: F401

REAL_EMIT, REAL_LATENCY = trace.emit, trace.latency


@pytest.fixture
def public_stream(monkeypatch):
    monkeypatch.setattr(trace, "_HISTORY", deque())
    monkeypatch.setattr(trace, "_HISTORY_CHARS", 0)
    monkeypatch.setattr(trace, "_SUBSCRIBERS", set())
    monkeypatch.setattr(trace, "_LEDGER", None)
    monkeypatch.setattr(trace, "_LOOP", None)
    monkeypatch.setattr(trace, "_CONTEXT", ContextVar("isolated_trial_trace", default={}))


def bind_trial(variant="baseline"):
    return trace.bind_trial("audit:degraded:" + variant + ":1", case_id="degraded",
                            split="train", variant=variant, repetition=1)


def test_trial_metadata_survives_public_projection_and_unicode_roundtrip(public_stream):
    owner = trace.bind("audit", "Tasks/audit", "Agents/Heimdall/Heimdall")
    trial = bind_trial()
    try:
        trace.emit("tool", "Simulation · Heimdall → harness.status", [], {
            "step": 1, "payload": {"kind": "tool", "name": "harness.status",
                                    "phase": "start", "arguments": {}, "simulated": True}})
        trace.emit("result", "Frozen result", [], {
            "step": 1, "payload": {"kind": "tool", "name": "harness.status",
                                    "phase": "result", "status": "returned", "result": {"status": "degraded"}}})
        trace.latency("model_first_public", duration_ms=61.4)
    finally:
        trace.reset(trial)
        trace.emit("status", "Audit continues")
        trace.reset(owner)
    start, result, latency, outside = json.loads(json.dumps(trace.history(), ensure_ascii=True))
    for entry in (start, result, latency):
        assert entry["run_id"] == "audit" and entry["task_ref"] == "Tasks/audit"
        assert entry["trial"] == {"id": "audit:degraded:baseline:1", "case_id": "degraded",
                                  "split": "train", "variant": "baseline", "repetition": 1}
        assert entry["payload"]["simulated"] is True
        assert entry["truncated"] is False
        assert entry["line"].count("Simulation") == 1 and "\\u" not in entry["line"]
    assert "Heimdall → harness.status" in start["line"]
    assert start["call_id"] == result["call_id"] == "audit:degraded:baseline:1:tool:1"
    assert "call_id" not in latency
    assert "trial" not in outside and outside["run_id"] == "audit"


@pytest.mark.parametrize("field,value", [
    ("trial_id", "x" * 161), ("trial_id", "bad\nidentity"),
    ("case_id", "x" * 65), ("case_id", "sk-" + "a" * 24),
    ("split", ["train"]), ("variant", "unknown"),
    ("repetition", True), ("repetition", 0), ("repetition", 4),
])
def test_trial_identity_is_bounded_and_invalid_binding_does_not_leak(public_stream, field, value):
    args = {"trial_id": "audit:case:baseline:1", "case_id": "case", "split": "train",
            "variant": "baseline", "repetition": 1, field: value}
    with pytest.raises(ValueError, match="trace identity"):
        trace.bind_trial(**args)
    trace.emit("status", "Outside rejected binding")
    assert "trial" not in trace.history()[0]


def test_trial_public_bounds_and_private_filter_remain_in_force(public_stream):
    token = bind_trial()
    try:
        trace.emit("result", "Result", [], {"step": 1, "payload": {
            "kind": "tool", "name": "vault.read", "phase": "result", "result": {
                "password": "PRIVATE-PASSWORD", "reasoning": "PRIVATE-REASONING",
                "_private_image_png": b"PRIVATE-PIXELS", "body": "日本語" * 30_000}}})
    finally:
        trace.reset(token)
    entry = trace.history()[0]
    encoded = json.dumps(entry, ensure_ascii=True, separators=(",", ":"))
    assert len(encoded) <= trace.MAX_EVENT_CHARS
    assert entry["truncated"] is True
    assert entry["trial"]["variant"] == "baseline"
    assert all(private not in encoded for private in ("PRIVATE-PASSWORD", "PRIVATE-REASONING", "PRIVATE-PIXELS"))


def test_trial_scope_is_task_local_and_cancellation_restores_outer_identity(public_stream):
    async def exercise():
        reached = asyncio.Event()

        async def worker():
            token = bind_trial()
            try:
                trace.latency("model_wait", duration_ms=1)
                reached.set()
                await asyncio.Future()
            finally:
                trace.reset(token)
                trace.emit("status", "Cancelled trial released")

        owner = trace.bind("audit", "Tasks/audit", "Agents/Heimdall/Heimdall")
        try:
            running = asyncio.create_task(worker())
            await reached.wait()
            trace.emit("status", "Concurrent outer owner event")
            running.cancel()
            with pytest.raises(asyncio.CancelledError):
                await running
        finally:
            trace.reset(owner)
        trace.emit("status", "Outside owner")

    asyncio.run(exercise())
    trial, parallel, released, outside = trace.history()
    assert trial["trial"]["variant"] == "baseline"
    assert "trial" not in parallel and "trial" not in released
    assert parallel["run_id"] == released["run_id"] == "audit"
    assert "run_id" not in outside


def test_actual_frozen_executor_gets_display_correlation_without_live_receipts(
        trial_runtime, public_stream, monkeypatch):
    monkeypatch.setattr(trace, "emit", REAL_EMIT)
    monkeypatch.setattr(trace, "latency", REAL_LATENCY)
    owner = trace.bind("audit", "Tasks/audit", "Agents/Heimdall/Heimdall")
    try:
        for variant in ("baseline", "candidate"):
            token = bind_trial(variant)
            try:
                asyncio.run(trial_runtime.run([
                    action("harness.status"), action("task.complete", status="completed", summary="Fixture finished")]))
            finally:
                trace.reset(token)
    finally:
        trace.reset(owner)
    events = trace.history()
    assert all(entry["run_id"] == "audit" and entry["task_ref"] == "Tasks/audit" for entry in events)
    assert not any(entry.get("payload", {}).get("kind") == "run" for entry in events)
    assert "run_id" not in trial_runtime.context and "_receipt_covered" not in trial_runtime.context
    for variant in ("baseline", "candidate"):
        tools = [entry for entry in events if entry["trial"]["variant"] == variant
                 and entry.get("payload", {}).get("kind") == "tool"]
        assert len(tools) == 4
        for start, returned in (tools[:2], tools[2:]):
            assert start["call_id"] == returned["call_id"]
            assert f":{variant}:1:tool:" in start["call_id"]
        models = [entry for entry in events if entry["trial"]["variant"] == variant
                  and entry.get("payload", {}).get("kind") == "model"]
        assert models and all(f":{variant}:1:model:" in entry["call_id"] for entry in models)
    assert trial_runtime.leases == trial_runtime.releases == 2


def test_popup_keeps_trial_pairing_timings_and_simulation_labels_inside_one_audit():
    projection_check(r"""
const trial=variant=>({id:`audit:degraded:${variant}:1`,case_id:'degraded',split:'train',variant,repetition:1});
const event=(id,kind,phase,scope)=>({id,at:100,run_id:'audit',task_ref:'Tasks/audit',channel:kind==='tool'?(phase==='result'?'result':'tool'):'model',
  line:'Simulation · Heimdall → harness.status',call_id:kind==='tool'?'same-tool':'same-model',step:1,
  ...(scope?{trial:trial(scope)}:{}),payload:{kind,phase,...(scope?{simulated:true}:{}),name:'harness.status',status:'returned',result:{status:'degraded'}}});
const rows=[{id:'owner',at:90,run_id:'audit',task_ref:'Tasks/audit',channel:'run',line:'Audit started',payload:{kind:'run',task_title:'Audit',status:'running'}}];
for(const variant of [undefined,'baseline','candidate']) rows.push(event(`${variant}-model-start`,'model','started',variant),event(`${variant}-model-result`,'model','result',variant),event(`${variant}-start`,'tool','start',variant));
for(const variant of ['candidate',undefined,'baseline']) rows.push(event(`${variant}-result`,'tool','result',variant));
for(const variant of [undefined,'baseline','candidate']) rows.push({id:`${variant}-latency`,at:101,run_id:'audit',channel:'measurement',line:'Latency',...(variant?{trial:trial(variant)}:{}),payload:{kind:'latency',stage:'model_first_public',monotonic_ms:100,duration_ms:61.4,...(variant?{simulated:true}:{})}});
rows.push({id:'simulated-outcome',at:102,run_id:'audit',channel:'status',line:'Trial finished',trial:trial('candidate'),payload:{kind:'run',status:'completed',task_title:'Check',simulated:true}});
const entries=trace.applyTraceFrame([],JSON.stringify({type:'snapshot',entries:rows}),0);
const runs=trace.traceRuns(entries);assert.equal(runs.length,1);
const run=runs[0];assert.equal(run.id,'audit');assert.equal(run.title,'Audit');assert.equal(run.status,'running');
for(const variant of [undefined,'baseline','candidate']) {
 const row=run.rows.find(row=>row.id===`${variant}-start`);
 assert.equal(row.result.id,`${variant}-result`);
 assert.deepEqual(row.model.entries.map(entry=>entry.id),[`${variant}-model-start`,`${variant}-model-result`]);
 if(variant) assert(trace.traceActionTitle(row.entry).includes(`Simulation · ${variant==='baseline'?'Baseline':'Candidate'} · degraded · Training · repetition 1 · Check system health`));
}
assert.equal(run.modelRequests.length,0);
assert.deepEqual(run.latencyEntries.map(entry=>entry.id),['undefined-latency']);
assert.equal(run.entries.filter(entry=>entry.latency&&entry.trial).length,2);
const legacy=entries.find(entry=>entry.id==='baseline-start');
assert.equal(trace.traceActionTitle({...legacy,trial:undefined,payload:{...legacy.payload,simulated:undefined}}),'Simulation · Check system health');
for(const invalid of [{...trial('baseline'),repetition:true},{...trial('baseline'),split:['train']},{...trial('baseline'),id:'x'.repeat(161)}]) {
 const frame=JSON.stringify({type:'entry',entry:{...rows[1],id:'invalid',trial:invalid}});
 assert.deepEqual(trace.applyTraceFrame(entries,frame,0),entries);
}
""")


def test_rendered_popup_shows_simulation_and_separate_trial_timelines():
    node_check(rf"""
import {{ strict as assert }} from 'node:assert';
import fs from 'node:fs';
import vm from 'node:vm';
import {{ createRequire }} from 'node:module';
import * as trace from {json.dumps((PANES / 'action-trace.ts').as_uri())};
const require=createRequire({json.dumps((UI / 'package.json').as_uri())});
const ts=require('typescript');
const source=fs.readFileSync({json.dumps(str(PANES / 'action-trace-popup.tsx'))},'utf8');
const compiled=ts.transpileModule(source+'\nmodule.exports.TestRow = ActionRow; module.exports.TestLatency = LatencyTimeline; module.exports.TestSimulations = SimulationTimelines;',{{compilerOptions:{{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}}}).outputText;
const jsx=(type,props,key)=>typeof type==='function'?type(props):({{type,props,key}});
const module={{exports:{{}}}};
vm.runInNewContext(compiled,{{module,exports:module.exports,require:name=>
 name==='react'?{{}}:name==='react/jsx-runtime'?{{jsx,jsxs:jsx}}:name==='@/lib/api'?{{}}:
 name==='./action-trace'?trace:(()=>{{throw Error(name);}})(),
}});
const nodes=value=>Array.isArray(value)?value.flatMap(nodes):value&&typeof value==='object'?[value,...nodes(value.props?.children)]:[];
const words=value=>Array.isArray(value)?value.map(words).join(''):value&&typeof value==='object'?words(value.props?.children):value==null?'':String(value);
const trial=variant=>({{id:`audit:case:${{variant}}:1`,case_id:'degraded-inspection',split:'train',variant,repetition:1}});
const wire=[{{id:'owner',at:90,run_id:'audit',channel:'run',line:'Audit started',payload:{{kind:'run',status:'running',task_title:'Audit'}}}}];
for(const variant of [undefined,'baseline','candidate']) wire.push({{id:`${{variant}}-latency`,at:100,run_id:'audit',channel:'measurement',line:'Latency',...(variant?{{trial:trial(variant)}}:{{}}),payload:{{kind:'latency',stage:'model_first_public',monotonic_ms:100,duration_ms:variant==='baseline'?61.4:variant==='candidate'?82.3:901.2,...(variant?{{simulated:true}}:{{}})}}}});
wire.push({{id:'simulated-action',at:101,run_id:'audit',channel:'tool',line:'Simulation · Candidate · degraded-inspection · repetition 1 · Heimdall → harness.status',trial:trial('candidate'),call_id:'trial:tool:1',step:1,payload:{{kind:'tool',phase:'start',name:'harness.status',arguments:{{}},simulated:true}}}});
const run=trace.traceRuns(trace.applyTraceFrame([],JSON.stringify({{type:'snapshot',entries:wire}}),0))[0];
const row=module.exports.TestRow({{row:run.rows.find(row=>row.id==='simulated-action'),index:1,startedAt:90}});
assert(words(row).includes('Simulation · Candidate · degraded-inspection · Training · repetition 1 · Check system health'));
assert(!words(row).includes('shortened'));
const ordinary=module.exports.TestLatency({{run}}),simulated=module.exports.TestSimulations({{run}});
assert(words(ordinary).includes('901.2 ms'));assert(!words(ordinary).includes('61.4 ms'));assert(!words(ordinary).includes('82.3 ms'));
const tables=nodes(simulated).filter(node=>node.type==='table');assert.equal(tables.length,2);
assert(tables[0].props['aria-label'].includes('Baseline'));assert(words(tables[0]).includes('61.4 ms'));assert(!words(tables[0]).includes('82.3 ms'));
assert(tables[1].props['aria-label'].includes('Candidate'));assert(words(tables[1]).includes('82.3 ms'));assert(!words(tables[1]).includes('61.4 ms'));
assert(!words(simulated).includes('901.2 ms'));assert.equal(run.status,'running');
""")
