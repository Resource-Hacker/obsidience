"""Review paint exercises the real shared cloud; its geometry cannot change forces."""

import json
import subprocess
from pathlib import Path

import pytest

from test_graph_simulation_continuity import SIMULATION_PROBE


# Reuse the actual TypeScript loader, Three.js/d3 fixture and assertions without
# executing the separate continuity matrix again.
PROBE = SIMULATION_PROBE.split("if (options.legacy_source) {", 1)[0] + r"""
const overlay = cloud => cloud.group.getObjectByName('knowledge-review-links');
const {KNOWLEDGE_LINK_APPROVAL_DURATION_MS:duration} = load(cloudFile);
assert.equal(duration,4000);
const layersMatch=(cloud,tuning)=>{
  const nodes=[...cloud.captureSimNodes().values()],radii=physics.knowledge3dDepthRadii(nodes,tuning);
  for(const node of nodes)assert(Math.abs(Math.hypot(node.x,node.y,node.z)-radii.get(node.depth))<1e-8,
    'node left its current semantic shell: '+node.id);
  coordinates(cloud.captureSimNodes());
};
for(const agentId of ['main','Alexandria']) {
  const input=fixture(agentId);
  input.edges.push({source:'leaf-a',target:'leaf-b',taxonomy:false,color:'#22ccff',colorEnd:'#ff8844'});
  const proposal={id:'review-1',graphId:agentId,source:'leaf-a',target:'leaf-b',
    phase:'pending',startedAt:1000};
  check(agentId+'_lifecycle',()=>{
    const cloud=build(input);settle(cloud);
    const state=cloud.captureSimulation(),before=coordinates(state.nodes);
    const forceInputs=JSON.stringify(input);
    const unchanged=()=>{
      assert.equal(cloud.captureSimulation().signature,state.signature);
      assert.equal(cloud.captureSimulation().alpha,state.alpha);
      assert.equal(cloud.tickIfHot(),false);
      assert.deepEqual(coordinates(cloud.captureSimNodes()),before);
      assert.equal(JSON.stringify(input),forceInputs);
    };
    cloud.applyRelationEffects([proposal],1500);
    const pending=overlay(cloud);assert(pending);unchanged();
    const actual=cloud.group.children.find(child=>child.material?.fragmentShader==='cross'
      && !child.material.defines.KNOWLEDGE_REVIEW_EFFECT);
    assert(actual);
    for(const name of ['aStart','aEnd','aArc','aColor'])
      assert.deepEqual(pending.geometry.getAttribute(name).array,actual.geometry.getAttribute(name).array);
    assert.equal(pending.material.uniforms.uWidthPx.value,actual.material.uniforms.uWidthPx.value);
    assert.equal(pending.material.defines.KNOWLEDGE_REVIEW_EFFECT,1);
    assert.equal(pending.geometry.getAttribute('aReview').getX(0),0);
    assert.equal(pending.geometry.getAttribute('aReview').getY(0),0.5);
    // The visible curve binds the exact current endpoint coordinates.
    const start=pending.geometry.getAttribute('aStart');
    const end=pending.geometry.getAttribute('aEnd');
    const a=state.nodes.get('leaf-a'),b=state.nodes.get('leaf-b');
    assert(start.count>0);
    for(const [axis,get] of [['x','getX'],['y','getY'],['z','getZ']]) {
      assert(Math.abs(start[get](0)-a[axis])<0.0001);
      assert(Math.abs(end[get](end.count-1)-b[axis])<0.0001);
    }
    cloud.applyRelationEffects([{...proposal}],2000);
    assert.equal(overlay(cloud),pending,'unchanged poll rebuilt overlay geometry');
    assert.equal(pending.geometry.getAttribute('aReview').getY(0),1);
    unchanged();
    cloud.applyRelationEffects([{...proposal,phase:'approved',startedAt:2100}],2600);
    const approved=overlay(cloud);assert(approved);unchanged();
    assert.equal(approved.geometry.getAttribute('aReview').getX(0),1);
    cloud.drivePathTimeline(3,2,0.9,1);
    assert.equal(approved.material.uniforms.uGlow.value,0,'thinking altered approval timing');
    let geometryDisposals=0,materialDisposals=0;
    approved.geometry.addEventListener('dispose',()=>geometryDisposals++);
    approved.material.addEventListener('dispose',()=>materialDisposals++);
    cloud.applyRelationEffects([],2700);
    assert.equal(overlay(cloud),undefined);unchanged();
    assert.equal(geometryDisposals,1);assert.equal(materialDisposals,1);
    dispose(cloud);
  });
  check(agentId+'_scope',()=>{
    const cloud=build(input);settle(cloud);
    for(const invalid of [
      {...proposal,graphId:agentId==='main'?'Alexandria':'main'},
      {...proposal,source:'Leaf-a'}, {...proposal,target:'missing'},
      {...proposal,source:'branch-a',target:'branch-b'},
      {...proposal,target:'leaf-a'}, {...proposal,phase:'rejected'},
      {...proposal,startedAt:NaN}, {...proposal,startedAt:Infinity},
      {...proposal,startedAt:3000},
    ]) {
      cloud.applyRelationEffects([invalid],2000);
      assert.equal(overlay(cloud),undefined,'invalid endpoint/state produced review paint');
    }
    dispose(cloud);
  });
  check(agentId+'_approval_rebuild_and_expiry',()=>{
    const cloud=build(input);settle(cloud);
    const approved={...proposal,phase:'approved',startedAt:2000};
    cloud.applyRelationEffects([approved],2500);
    const state=cloud.captureSimulation(),before=coordinates(state.nodes);
    const rebuilt=build(clone(input),state);
    rebuilt.applyRelationEffects([{...approved}],3000);
    assert.equal(overlay(rebuilt).geometry.getAttribute('aReview').getY(0),1,
      'cloud rebuild restarted the approval');
    assert.deepEqual(coordinates(rebuilt.captureSimNodes()),before);
    assert.equal(rebuilt.captureSimulation().alpha,state.alpha);
    let disposedGeometry=0,disposedMaterial=0;
    overlay(rebuilt).geometry.addEventListener('dispose',()=>disposedGeometry++);
    overlay(rebuilt).material.addEventListener('dispose',()=>disposedMaterial++);
    rebuilt.applyRelationEffects([approved],approved.startedAt+duration-1);
    assert(overlay(rebuilt));
    rebuilt.applyRelationEffects([approved],approved.startedAt+duration);
    assert.equal(overlay(rebuilt),undefined);
    assert.equal(disposedGeometry,1);assert.equal(disposedMaterial,1);
    const replay=build(clone(input),rebuilt.captureSimulation());
    replay.applyRelationEffects([{...approved}],approved.startedAt+duration+1);
    assert.equal(overlay(replay),undefined,'expired approval replayed after rebuild');
    [cloud,rebuilt,replay].forEach(dispose);
  });
  check(agentId+'_spring_promotion',()=>{
    const baseInput=fixture(agentId);
    const base=build(baseInput);settle(base);
    const baseState=base.captureSimulation(),before=coordinates(baseState.nodes);
    const previewInput=clone(baseInput);
    previewInput.edges.push({...input.edges.at(-1),preview:true});
    if(agentId==='main')previewInput.nodes.filter(n=>n.role==='claim').forEach(n=>n.radius+=0.55);
    const pending=build(previewInput,baseState);
    assert(pending.isHot(),'proposal did not introduce its physical spring');
    assert.deepEqual(coordinates(pending.captureSimNodes()),before,'proposal teleported nodes');
    for(let n=0;n<12;n++){pending.tickIfHot();layersMatch(pending,previewInput.tuning);}
    const state=pending.captureSimulation(),atApproval=coordinates(state.nodes);
    const acceptedInput=clone(previewInput);delete acceptedInput.edges.at(-1).preview;
    acceptedInput.nodes.reverse();acceptedInput.edges.reverse();
    const accepted=build(acceptedInput,state);
    assert.equal(accepted.captureSimulation().signature,state.signature);
    assert.equal(accepted.captureSimulation().alpha,state.alpha,'approval reheated the same spring');
    assert.deepEqual(coordinates(accepted.captureSimNodes()),atApproval);
    const curve=cloud=>cloud.group.children.find(child=>child.material?.fragmentShader==='cross'
      && !child.material.defines.KNOWLEDGE_REVIEW_EFFECT).geometry;
    for(const name of ['aStart','aEnd','aArc','aColor'])
      assert.deepEqual(curve(accepted).getAttribute(name).array,curve(pending).getAttribute(name).array);
    for(let n=0;n<12;n++){pending.tickIfHot();accepted.tickIfHot();}
    assert.deepEqual(coordinates(accepted.captureSimNodes()),coordinates(pending.captureSimNodes()),
      'input ordering changed the ongoing trajectory at approval');
    const atRejection=coordinates(pending.captureSimNodes());
    const rejected=build(baseInput,pending.captureSimulation());
    assert.notEqual(rejected.captureSimulation().signature,state.signature);
    assert(rejected.isHot());
    assert.deepEqual(coordinates(rejected.captureSimNodes()),atRejection,
      'rejection restored an obsolete position snapshot');
    rejected.tickIfHot();layersMatch(rejected,baseInput.tuning);
    [base,pending,accepted,rejected].forEach(dispose);
  });
  check(agentId+'_constructor_projection',()=>{
    const originalInput=fixture(agentId),original=build(originalInput);
    layersMatch(original,originalInput.tuning);settle(original);
    const before=original.captureSimulation();
    for(const change of ['new_node','reparent','spacing']) {
      const next=clone(originalInput);
      if(change==='new_node') {
        next.nodes.push({...next.nodes[3],id:'new-leaf',radius:30});
        next.edges.push({source:'branch-a',target:'new-leaf',taxonomy:true,color:'#22ccff'});
      } else if(change==='reparent') {
        next.nodes.find(node=>node.id==='branch-a').parentId='branch-b';
        next.edges.find(edge=>edge.target==='branch-a').source='branch-b';
      } else next.tuning.linkDistance*=1.2;
      const rebuilt=build(next,before);
      layersMatch(rebuilt,next.tuning);
      if(change==='reparent')assert.equal(rebuilt.captureSimNodes().get('leaf-a').depth,3);
      assert.notDeepEqual(coordinates(rebuilt.captureSimNodes()),coordinates(before.nodes),
        'changed semantic layout retained obsolete positions: '+change);
      geometryMatches(rebuilt,next);
      dispose(rebuilt);
    }
    dispose(original);
  });
}
process.stdout.write(JSON.stringify(results));
"""


@pytest.fixture(scope="module")
def overlay_results():
    result = subprocess.run(
        ["node", "-e", PROBE], input="{}", cwd=Path(__file__).parents[2],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("agent_id", ["main", "Alexandria"])
@pytest.mark.parametrize("case", ["lifecycle", "scope", "approval_rebuild_and_expiry", "spring_promotion", "constructor_projection"])
def test_review_overlay_preserves_the_real_cloud(overlay_results, agent_id, case):
    result = overlay_results[f"{agent_id}_{case}"]
    assert result["ok"], result.get("error")
