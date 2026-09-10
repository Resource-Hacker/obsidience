"""Review lifecycle and exact endpoint projection in the actual renderer helper."""
import json
import subprocess
from pathlib import Path

import pytest


PROBE = r"""
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {strict:assert}=require('node:assert');
const {createRequire}=require('node:module');
const ui=path.resolve('obsidience/ui');
const native=createRequire(path.join(ui,'package.json')),ts=native('typescript');
const cache=new Map();
function load(file){
  if(cache.has(file))return cache.get(file).exports;
  const mod={exports:{}};cache.set(file,mod);
  const local=id=>id.startsWith('.')?load(path.resolve(path.dirname(file),id)+'.ts'):native(id);
  const source=ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{
    module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,esModuleInterop:true,
  }}).outputText;
  vm.runInThisContext('(function(require,module,exports){'+source+'\n})',{filename:file})(local,mod,mod.exports);
  return mod.exports;
}
const {recordLinkApproval:record,projectLinkReviewEffects:project,previewLinkReviewCloud:preview}=load(path.join(ui,'src/renderer/src/panes/graph-link-review.ts'));
const proposal={proposal_id:'review-1',run_id:'run-1',source:'A',target:'B'};
const edge={source:'A',target:'B'};
const decision={...proposal,state:'approved',decided_at:10000,links:[edge],truncated:false};
const nodes=['A','B'].map(id=>({id}));
const clouds=[{agentId:'main',nodes,edges:[edge]},{agentId:'Alexandria',nodes:[{id:'A'}],edges:[]}];
const aliases=new Map();
const approval=record([],decision,10000,1000);
const check={};
function test(name,fn){try{fn();check[name]={ok:true};}catch(e){check[name]={ok:false,error:e.stack};}}
test('pending_is_presentation_only',()=>{
  const accepted=[];const before=JSON.stringify([accepted,clouds,proposal]);
  const result=project([proposal],[],accepted,aliases,clouds,1000);
  assert.equal(result.length,1);assert.equal(result[0].phase,'pending');assert.equal(result[0].graphId,'main');
  assert.equal(JSON.stringify([accepted,clouds,proposal]),before);
});
test('approval_waits_for_accepted_snapshot',()=>{
  assert.equal(project([],approval,[],aliases,clouds,1000).length,0);
  const result=project([],approval,[edge],aliases,clouds,1000);
  assert.equal(result.length,1);assert.equal(result[0].phase,'approved');
});
test('approval_requires_exact_direction_and_direct_edge',()=>{
  for(const links of [[{source:'B',target:'A'}],[{...edge,derived:true}]])
    assert.equal(project([],approval,links,aliases,clouds,1000).length,0);
});
test('approved_edge_must_belong_to_rendered_cloud',()=>{
  assert.equal(project([],approval,[edge],aliases,[{agentId:'main',nodes,edges:[]}],1000).length,0);
});
test('pending_requires_the_eventual_cross_link',()=>{
  for(const edges of [[],[{...edge,taxonomy:true}]])
    assert.equal(project([proposal],[],[],aliases,[{agentId:'main',nodes,edges}],1000).length,0);
});
test('pending_disappears_without_inferred_approval',()=>{
  assert.equal(project([],[],[],aliases,clouds,1000).length,0);
  assert.equal(project([],[],[edge],aliases,clouds,1000).length,0);
});
test('rejection_does_not_glow',()=>{
  assert.deepEqual(record([],{...decision,state:'rejected'},10000,1000),[]);
  assert.deepEqual(record([],{...decision,state:'pending'},10000,1000),[]);
});
test('replay_does_not_restart_approval',()=>{
  const again=record(approval,decision,11000,2000);
  assert.deepEqual(again,approval);
  assert.equal(project([],again,[edge],aliases,clouds,4999).length,1);
  assert.equal(project([],again,[edge],aliases,clouds,5000).length,0);
});
test('reconnect_preserves_original_decision_age',()=>{
  const afterReconnect=record([],decision,12000,90000);
  assert.equal(afterReconnect[0].startedAt,88000);
  assert.equal(project([],afterReconnect,[edge],aliases,clouds,92000).length,0);
  assert.deepEqual(record([],decision,14000,92000),[]);
});
test('invalid_or_stale_decision_cannot_glow',()=>{
  for(const decided_at of [undefined,NaN,Infinity,6000,12000])
    assert.deepEqual(record([],{...decision,decided_at},10000,1000),[]);
});
test('accepted_pair_supersedes_stale_pending',()=>{
  const result=project([proposal],approval,[edge],aliases,clouds,1000);
  assert.equal(result.length,1);assert.equal(result[0].phase,'approved');
});
test('exact_aliases_and_missing_endpoints',()=>{
  const renamed=[{agentId:'main',nodes:[{id:'@A'},{id:'@B'}],edges:[{source:'@A',target:'@B'}]}];
  const result=project([proposal],[],[],new Map([['A','@A'],['B','@B']]),renamed,1000);
  assert.equal(result.length,1);assert.equal(result[0].source,'@A');
  assert.equal(project([proposal],[],[],aliases,renamed,1000).length,0);
  assert.equal(project([proposal],[],[],new Map([['A','@A'],['B','@A']]),renamed,1000).length,0);
});
test('duplicate_visual_pairs_render_once',()=>{
  assert.equal(project([proposal,{...proposal,source:'B',target:'A',proposal_id:'review-2'}],[],[],aliases,clouds,1000).length,1);
});
test('pending_and_approval_payloads_are_bounded',()=>{
  const many=Array.from({length:200},(_,i)=>({...edge,target:'B'+i}));
  assert.equal(record([],{...decision,links:many},10000,1000)[0].links.length,64);
  const largeCloud=[{agentId:'main',nodes:[{id:'A'},...many.map(x=>({id:x.target}))],edges:many}];
  assert.equal(project(many.map((x,i)=>({...proposal,...x,proposal_id:String(i)})),[],[],aliases,largeCloud,1000).length,128);
});

const {knowledgeNodeRadius:radius}=load(path.join(ui,'src/renderer/src/components/themes/obsidience/knowledge-paint.ts'));
const {visibleArticleLinks}=load(path.join(ui,'src/renderer/src/panes/graph-links.ts'));
const node=(id,degree=0)=>({id,x:0.5,y:0.5,role:'claim',depth:3,parentId:'root',
  radius:radius('claim',degree,false,3),core:'#00ffff',subject:false});
const baseCloud={nodes:[{...node('root'),role:'root',parentId:null,radius:21},node('A'),node('B'),node('C')],
  edges:['A','B','C'].map(target=>({source:'root',target,taxonomy:true,color:'#00ffff'}))};
const edgeColorEnd=()=>"#00ffff";
const union=links=>visibleArticleLinks(links,new Set(['root','A','B','C']));
test('preview_adds_only_scene_spring_and_future_radii',()=>{
  const original=JSON.stringify(baseCloud),accepted=[];
  const result=preview(baseCloud,accepted,union([edge]),true,edgeColorEnd);
  assert.equal(result.edges.length,baseCloud.edges.length+1);
  assert.equal(result.edges.at(-1).preview,true);
  assert.equal(result.edges.at(-1).colorEnd,edgeColorEnd());
  assert.equal(result.nodes.find(n=>n.id==='A').radius,radius('claim',1,false,3));
  assert.equal(result.nodes.find(n=>n.id==='B').radius,radius('claim',1,false,3));
  assert.equal(result.nodes.find(n=>n.id==='C').radius,node('C').radius);
  assert.equal(JSON.stringify(baseCloud),original);assert.equal(accepted.length,0);
});
test('approval_has_identical_spring_and_radius_inputs',()=>{
  const pending=preview(baseCloud,[],union([edge]),true,edgeColorEnd);
  const accepted={...baseCloud,nodes:baseCloud.nodes.map(n=>['A','B'].includes(n.id)?{...n,radius:radius('claim',1,false,3)}:n),
    edges:[...baseCloud.edges,{...edge,taxonomy:false,color:'#00ffff'}]};
  const after=preview(accepted,[edge],union([edge]),true,edgeColorEnd);
  assert.deepEqual(pending.nodes.map(n=>[n.id,n.radius]),after.nodes.map(n=>[n.id,n.radius]));
  assert.deepEqual(pending.edges.map(e=>[e.source,e.target,e.taxonomy]),after.edges.map(e=>[e.source,e.target,e.taxonomy]));
  assert.equal(after,accepted,'accepted graph unnecessarily duplicated');
});
test('one_spring_per_visual_pair_and_partial_approval',()=>{
  const second={source:'B',target:'C'};
  const pending=preview(baseCloud,[],union([edge,{source:'B',target:'A'},second]),true,edgeColorEnd);
  assert.equal(pending.edges.length,baseCloud.edges.length+2);
  const accepted={...baseCloud,nodes:baseCloud.nodes.map(n=>['A','B'].includes(n.id)?{...n,radius:radius('claim',1,false,3)}:n),
    edges:[...baseCloud.edges,{...edge,taxonomy:false,color:'#00ffff'}]};
  const partial=preview(accepted,[edge],union([edge,edge,second]),true,edgeColorEnd);
  assert.deepEqual(partial.nodes.map(n=>[n.id,n.radius]),pending.nodes.map(n=>[n.id,n.radius]));
  assert.equal(partial.edges.length,pending.edges.length);
});
test('rejection_restores_remaining_constraints_without_mutating_accepted',()=>{
  const original=JSON.stringify(baseCloud);
  preview(baseCloud,[],union([edge]),true,edgeColorEnd);
  assert.equal(preview(baseCloud,[],[],true,edgeColorEnd),baseCloud);
  assert.equal(JSON.stringify(baseCloud),original);
});
test('satellite_preview_keeps_its_existing_radius_policy',()=>{
  const result=preview(baseCloud,[],union([edge]),false,edgeColorEnd);
  assert.equal(result.nodes,baseCloud.nodes);
  assert.equal(result.edges.length,baseCloud.edges.length+1);
});
test('pending_start_survives_projection_refresh',()=>{
  const starts=new Map([['review-1',777]]);
  assert.equal(project([proposal],[],[],aliases,clouds,1000,starts)[0].startedAt,777);
  assert.equal(project([proposal],[],[],aliases,clouds,9000,starts)[0].startedAt,777);
});

process.stdout.write(JSON.stringify(check));
"""


@pytest.fixture(scope="module")
def results():
    result = subprocess.run(["node", "-e", PROBE], cwd=Path(__file__).parents[2],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("case", [
    "pending_is_presentation_only", "approval_waits_for_accepted_snapshot",
    "approval_requires_exact_direction_and_direct_edge", "approved_edge_must_belong_to_rendered_cloud",
    "pending_requires_the_eventual_cross_link", "pending_disappears_without_inferred_approval", "rejection_does_not_glow",
    "replay_does_not_restart_approval", "reconnect_preserves_original_decision_age",
    "invalid_or_stale_decision_cannot_glow", "accepted_pair_supersedes_stale_pending",
    "exact_aliases_and_missing_endpoints", "duplicate_visual_pairs_render_once",
    "pending_and_approval_payloads_are_bounded",
    "preview_adds_only_scene_spring_and_future_radii",
    "approval_has_identical_spring_and_radius_inputs",
    "one_spring_per_visual_pair_and_partial_approval",
    "rejection_restores_remaining_constraints_without_mutating_accepted",
    "satellite_preview_keeps_its_existing_radius_policy",
    "pending_start_survives_projection_refresh",
])
def test_link_review_lifecycle(results, case):
    assert results[case]["ok"], results[case].get("error")
