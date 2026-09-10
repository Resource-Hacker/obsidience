"""Moving 3D branch territories preserve dynamics and exact parent ownership."""

import json
import subprocess
from pathlib import Path

import pytest

from test_graph_simulation_continuity import SIMULATION_PROBE


PROBE = SIMULATION_PROBE.split("if (options.legacy_source) {", 1)[0] + r"""
const territory=physics.forceKnowledgeBranchTerritory;
assert.equal(typeof territory,'function');
const position=n=>[n.x,n.y,n.z];
const velocity=n=>[n.vx??0,n.vy??0,n.vz??0];
const dot=(a,b)=>a.reduce((total,value,axis)=>total+value*b[axis],0);
const norm=a=>Math.hypot(...a);
const minus=(a,b)=>a.map((value,axis)=>value-b[axis]);
const unit=n=>{const p=position(n),r=norm(p);return r?p.map(value=>value/r):[0,0,0];};
const near=(a,b)=>assert(norm(minus(a,b))<1e-8,`${a} != ${b}`);
function forceFixture() {
  const node=(id,parentId,depth,x,y,z,radius=1)=>({
    id,parentId,depth,role:depth===0?'root':depth===1?'section':'claim',
    radius,x,y,z,vx:0,vy:0,vz:0});
  return [node('root',null,0,0,0,0,2),node('a','root',1,20,0,0,2),
    node('b','root',1,0,20,0,2),node('c','root',1,-10,0,20,2),
    node('inside','a',2,32,3,4),node('crossing','a',2,5,30,4),
    node('nested','a',2,28,2,0),node('deep','nested',3,4,29,5),
    node('margin','a',2,21,20,0,2)];
}
function corrected(nodes,alpha=1) {
  const before=new Map(nodes.map(n=>[n.id,{position:position(n),velocity:velocity(n)}]));
  territory(nodes)(alpha);
  for(const node of nodes) {
    near(position(node),before.get(node.id).position);
    const delta=minus(velocity(node),before.get(node.id).velocity);
    assert(delta.every(Number.isFinite),'nonfinite force for '+node.id);
    assert(Math.abs(dot(position(node),delta))<1e-7,'radial correction for '+node.id);
  }
  return new Map(nodes.map(n=>[n.id,velocity(n)]));
}
check('tangential_and_scoped',()=>{
  const nodes=forceFixture(),out=corrected(nodes);
  for(const id of ['root','a','b','c','inside','nested'])near(out.get(id),[0,0,0]);
  for(const id of ['crossing','deep','margin']) {
    assert(norm(out.get(id))>0,'territory did not correct '+id);
    assert(dot(out.get(id),[1,-1,0])>0,'correction points toward the competing branch');
  }
  assert(nodes.every(n=>n.fx==null&&n.fy==null&&n.fz==null),'force introduced coordinate pins');
});
check('independent_of_cooling',()=>{
  const hot=corrected(forceFixture(),1),cold=corrected(forceFixture(),0.000001);
  for(const [id,value] of hot)near(value,cold.get(id));
});
check('rotation_and_permutation',()=>{
  const original=forceFixture(),expected=corrected(clone(original));
  const reversed=corrected(clone(original).reverse());
  for(const [id,value] of expected)near(value,reversed.get(id));
  const rotation=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1,2,3).normalize(),0.73);
  const rotate=value=>new THREE.Vector3(...value).applyQuaternion(rotation).toArray();
  const rotated=clone(original);
  rotated.forEach(node=>{[node.x,node.y,node.z]=rotate(position(node));});
  const actual=corrected(rotated);
  for(const [id,value] of expected)near(actual.get(id),rotate(value));
  const tied=forceFixture();
  Object.assign(tied.find(n=>n.id==='c'),{x:0,y:0,z:20});
  Object.assign(tied.find(n=>n.id==='crossing'),{x:-5,y:20,z:20});
  const tiedForward=corrected(clone(tied)),tiedReverse=corrected(clone(tied).reverse());
  for(const [id,value] of tiedForward)near(value,tiedReverse.get(id));
});
check('three_dimensional_registration',()=>{
  const three=physics.createKnowledgeForceSimulation(forceFixture(),[],undefined,3);
  const two=physics.createKnowledgeForceSimulation(forceFixture(),[],undefined,2);
  assert.equal(three.numDimensions(),3);
  assert.equal(typeof three.force('branchTerritory'),'function');
  assert.equal(two.numDimensions(),2);
  assert.equal(two.force('branchTerritory'),undefined,'3D territory leaked into the 2D layout');
  three.stop();two.stop();
});
check('invalid_ancestry',()=>{
  const nodes=forceFixture();
  for(const [id,parentId] of [['missing','absent'],['cycle-a','cycle-b'],
    ['cycle-b','cycle-a'],['self','self'],['unparented',null]])
    nodes.push({...nodes[5],id,parentId});
  const output=corrected(nodes);
  for(const id of ['missing','cycle-a','cycle-b','self','unparented'])
    near(output.get(id),[0,0,0]);
});
check('moving_boundaries',()=>{
  const nodes=forceFixture(),force=territory(nodes);
  const own=nodes.find(n=>n.id==='a'),competitor=nodes.find(n=>n.id==='b');
  // Reusing the same force must use the roots' new positions, not seed rays.
  [own.x,own.y,own.z]=[0,20,0];[competitor.x,competitor.y,competitor.z]=[20,0,0];
  force(1);
  near(velocity(nodes.find(n=>n.id==='crossing')),[0,0,0]);
  assert(norm(velocity(nodes.find(n=>n.id==='inside')))>0);
});
check('degenerate_directions',()=>{
  const same=forceFixture().filter(n=>['root','a','b','crossing'].includes(n.id));
  const sameA=same.find(n=>n.id==='a'),sameB=same.find(n=>n.id==='b');
  [sameB.x,sameB.y,sameB.z]=position(sameA);
  const unchanged=corrected(same);for(const value of unchanged.values())near(value,[0,0,0]);
  const opposite=forceFixture().filter(n=>['root','a','b','crossing'].includes(n.id));
  const other=opposite.find(n=>n.id==='b'),leaf=opposite.find(n=>n.id==='crossing');
  [other.x,other.y,other.z]=[-20,0,0];[leaf.x,leaf.y,leaf.z]=[-30,0,0];
  const force=territory(opposite);force(1);
  assert(norm(velocity(leaf))>0,'antipodal violation has a zero-gradient trap');
  for(let tick=0;tick<160;tick++) {
    force(0.001);
    for(const node of opposite)for(const [p,v] of [['x','vx'],['y','vy'],['z','vz']])
      node[p]+=node[v]*=0.6;
    assert(opposite.every(n=>[...position(n),...velocity(n)].every(Number.isFinite)));
  }
  assert(leaf.x>0,'antipodal descendant never returned to its own hemisphere');
  const origin=forceFixture();Object.assign(origin.find(n=>n.id==='crossing'),{x:0,y:0,z:0});
  corrected(origin);
});
function branchViolations(cloud) {
  const nodes=cloud.captureSimNodes(),a=unit(nodes.get('branch-a')),b=unit(nodes.get('branch-b'));
  return ['leaf-a','leaf-b'].filter(id=>{
    const node=nodes.get(id),own=id==='leaf-a'?a:b,other=id==='leaf-a'?b:a;
    return dot(unit(node),own)<dot(unit(node),other)-1e-8;
  });
}
for(const agentId of ['main','Alexandria']) {
  check(agentId+'_settlement',()=>{
    const input=fixture(agentId),initial=build(input),state=initial.captureSimulation();
    const set=(id,r,angle)=>Object.assign(state.nodes.get(id),{
      x:r*Math.cos(angle*Math.PI/180),y:r*Math.sin(angle*Math.PI/180),z:0,vx:0,vy:0,vz:0});
    set('branch-a',20,0);set('branch-b',20,42);set('leaf-a',40,34);set('leaf-b',40,8);
    state.alpha=0.4;
    const cloud=build(input,state);assert.equal(branchViolations(cloud).length,2);
    const ticks=settle(cloud);assert.deepEqual(branchViolations(cloud),[]);
    const nodes=[...cloud.captureSimNodes().values()];let minimumGap=Infinity;
    for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++) {
      const gap=norm(minus(position(nodes[i]),position(nodes[j])))-nodes[i].radius-nodes[j].radius;
      minimumGap=Math.min(minimumGap,gap);
    }
    assert(minimumGap>=-1e-6,'recovery overlapped node bodies');
    [initial,cloud].forEach(dispose);return {ticks,minimum_core_gap:minimumGap};
  });
  check(agentId+'_approval_continuity',()=>{
    const input=fixture(agentId);
    input.edges.push({source:'leaf-a',target:'leaf-b',taxonomy:false,preview:true,color:'#22ccff'});
    const pending=build(input);for(let tick=0;tick<20;tick++)pending.tickIfHot();
    const state=pending.captureSimulation(),before=coordinates(state.nodes);
    const next=clone(input);delete next.edges.at(-1).preview;next.nodes.reverse();next.edges.reverse();
    const accepted=build(next,state);
    assert.equal(accepted.captureSimulation().signature,state.signature);
    assert.equal(accepted.captureSimulation().alpha,state.alpha);
    assert.deepEqual(coordinates(accepted.captureSimNodes()),before);
    for(let tick=0;tick<20;tick++){pending.tickIfHot();accepted.tickIfHot();}
    assert.deepEqual(coordinates(accepted.captureSimNodes()),coordinates(pending.captureSimNodes()),
      'territory changed the hot trajectory at approval');
    [pending,accepted].forEach(dispose);
  });
}
process.stdout.write(JSON.stringify(results));
"""


@pytest.fixture(scope="module")
def territory_results():
    result = subprocess.run(
        ["node", "-e", PROBE], input="{}", cwd=Path(__file__).parents[2],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("case", [
    "tangential_and_scoped", "independent_of_cooling", "rotation_and_permutation",
    "three_dimensional_registration",
    "invalid_ancestry", "moving_boundaries", "degenerate_directions",
    "main_settlement", "Alexandria_settlement",
    "main_approval_continuity", "Alexandria_approval_continuity",
])
def test_branch_territories_follow_the_live_root_fork(territory_results, case):
    result = territory_results[case]
    assert result["ok"], result.get("error")
