"""Coupled spherical contacts and recursive moving crowns, through the real cloud."""

import json
import subprocess
from pathlib import Path

import pytest

from test_graph_simulation_continuity import SIMULATION_PROBE


PROBE = SIMULATION_PROBE.split("if (options.legacy_source) {", 1)[0] + r"""
const spherical=load(path.join(component,'knowledge-spherical.ts'));
const xyz=n=>[n.x,n.y,n.z];
const norm=a=>Math.hypot(...a);
const dot=(a,b)=>a.reduce((sum,x,i)=>sum+x*b[i],0);
const sub=(a,b)=>a.map((x,i)=>x-b[i]);
const unit=n=>{const p=xyz(n),r=norm(p);return r?p.map(x=>x/r):[0,0,0];};
const kernelNode=(id,parentId,depth,x,y,z,radius=1)=>({
  id,parentId,depth,role:depth===0?'root':'section',radius,x,y,z,vx:0,vy:0,vz:0,
});
function kernel(nodes,radii=new Map([[0,0],[1,20],[2,40],[3,60]]),previous) {
  return spherical.createSphericalConstraint(nodes,{
    velocityDecay:0.35,alphaMin:0.006,radii,avoidance:n=>n.radius,
    signature:JSON.stringify(nodes.map(n=>[n.id,n.parentId,n.depth,n.radius]).sort()),previous,
  });
}
function integrate(nodes,force,alpha=0.001) {
  force(alpha);
  for(const node of nodes)for(const [p,v] of [['x','vx'],['y','vy'],['z','vz']])
    node[p]+=node[v]*=0.65;
}
function verifyCloud(cloud) {
  const nodes=cloud.captureSimNodes(),layers=new Map();
  for(const node of nodes.values()) {
    const radius=norm(xyz(node));
    assert([...xyz(node),node.vx,node.vy,node.vz].every(Number.isFinite));
    if(layers.has(node.depth))assert(Math.abs(radius-layers.get(node.depth))<1e-7);
    else layers.set(node.depth,radius);
    if(node.depth===0)assert.deepEqual(xyz(node),[0,0,0]);
    else assert(node.fx==null&&node.fy==null&&node.fz==null);
    const parent=nodes.get(node.parentId);
    if(parent&&parent.depth>0)
      assert(dot(sub(xyz(node),xyz(parent)),unit(parent))>=-0.001,'inward edge: '+node.id);
  }
  const all=[...nodes.values()];let gap=Infinity;
  for(let i=0;i<all.length;i++)for(let j=0;j<i;j++) {
    const clearance=physics.knowledge3dAvoidanceRadius(all[i])+physics.knowledge3dAvoidanceRadius(all[j]);
    gap=Math.min(gap,norm(sub(xyz(all[i]),xyz(all[j])))-clearance);
  }
  assert(gap>=-0.001,'avoidance spheres overlap: '+gap);
  const state=cloud.layoutDiagnostics();
  assert.equal(state.status,'settled',JSON.stringify(state.residuals));
  assert(state.residuals.maxTerritoryViolation<=0.001,'recursive crown violation');
  return {minimum_avoidance_gap:gap,ticks:state.ticks,residuals:state.residuals};
}
function hardwareFixture(agentId='main') {
  const input=fixture(agentId),base=clone(input.nodes[1]),leaf=clone(input.nodes[3]);
  input.nodes=[input.nodes[0]];input.edges=[];
  function add(id,parentId,section=true,radius=section?7:4) {
    const parent=input.nodes.find(n=>n.id===parentId);
    input.nodes.push({...clone(section?base:leaf),id,parentId,depth:parent.depth+1,
      role:section?'section':'claim',subject:section,radius});
    input.edges.push({source:parentId,target:id,taxonomy:true,color:'#22ccff'});
  }
  add('ADMECH','root');add('Research','root');add('Projects','root');
  add('Hardware','ADMECH');add('Applications','ADMECH');add('Observations','ADMECH');
  add('Compute','Hardware');add('Devices','Hardware');add('Drives','Hardware');
  add('Network','Hardware',false);
  for(const [group,count] of [['Compute',4],['Devices',3],['Drives',4],
    ['Applications',3],['Observations',8],['Research',5],['Projects',2]])
    for(let i=0;i<count;i++)add(group+'-'+i,group,false,4+i%3);
  return input;
}
check('exact_angular_clearance',()=>{
  const angle=spherical.sphericalClearanceAngle;
  assert.equal(angle(10,20,9),0);
  assert.equal(angle(0,10,10),0);
  assert.equal(angle(10,10,21),Infinity);
  assert.equal(angle(0,10,11),Infinity);
  assert.throws(()=>angle(-1,2,1),RangeError);
  for(const [a,b,gap] of [[10,10,6],[10,12,7],[30,50,23],[2,3,5]]) {
    const theta=angle(a,b,gap);
    assert(Math.abs(Math.sqrt(a*a+b*b-2*a*b*Math.cos(theta))-gap)<1e-7);
  }
});
check('contacts_stay_on_shells',()=>{
  const nodes=[kernelNode('root',null,0,0,0,0),
    kernelNode('a','root',1,20,0,0,3),kernelNode('b','root',1,20,0,0,3),
    kernelNode('c','root',1,19,1,0,3)];
  const force=kernel(nodes);
  for(let tick=0;tick<100;tick++) {
    integrate(nodes,force);
    assert(nodes.slice(1).every(n=>Math.abs(norm(xyz(n))-20)<1e-7));
  }
  for(let i=1;i<nodes.length;i++)for(let j=1;j<i;j++)
    assert(norm(sub(xyz(nodes[i]),xyz(nodes[j])))>=6-0.001);
});
check('coupled_registration_and_2d_isolation',()=>{
  const input=[kernelNode('root',null,0,0,0,0),kernelNode('a','root',1,20,0,0)];
  const three=physics.createKnowledgeForceSimulation(clone(input),[],undefined,3);
  const two=physics.createKnowledgeForceSimulation(clone(input),[],undefined,2);
  assert.equal(typeof three.force('depthLayers'),'function');
  for(const name of ['collide','outwardHemisphere','branchTerritory'])
    assert.equal(three.force(name),undefined,'competing 3D correction still active: '+name);
  assert.equal(two.force('depthLayers'),undefined);
  assert.equal(typeof two.force('collide'),'function');
  assert.equal(typeof two.force('outwardHemisphere'),'function');
  three.stop();two.stop();
});
check('rotation_and_permutation',()=>{
  const input=[kernelNode('root',null,0,0,0,0),kernelNode('a','root',1,20,3,4),
    kernelNode('b','root',1,-4,20,7),kernelNode('c','a',2,-3,35,8),
    kernelNode('d','b',2,32,8,4)];
  const q=new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1,2,3).normalize(),0.71);
  const rotate=v=>new THREE.Vector3(...v).applyQuaternion(q).toArray();
  const forward=clone(input),reverse=clone(input).reverse(),rotated=clone(input);
  for(const n of rotated)[n.x,n.y,n.z]=rotate(xyz(n));
  const forces=[kernel(forward),kernel(reverse),kernel(rotated)];
  [forward,reverse,rotated].forEach((nodes,i)=>integrate(nodes,forces[i],0.1));
  for(const node of forward) {
    assert(norm(sub(xyz(node),xyz(reverse.find(n=>n.id===node.id))))<1e-8);
    assert(norm(sub(rotate(xyz(node)),xyz(rotated.find(n=>n.id===node.id))))<1e-7);
  }
});
for(const agentId of ['main','Alexandria']) {
  check(agentId+'_hardware_crown',()=>{
    const cloud=build(hardwareFixture(agentId));
    try {settle(cloud);return verifyCloud(cloud);}finally{dispose(cloud);}
  });
  check(agentId+'_cold_nested_recovery',()=>{
    const input=hardwareFixture(agentId),initial=build(input),state=initial.captureSimulation();
    // Cross Compute and Drives articles inside the SAME Hardware/ADMECH tree.
    // A Brain-level-only territory cannot detect this ownership error.
    const a=state.nodes.get('Compute-0'),b=state.nodes.get('Drives-0'),position=xyz(a);
    [a.x,a.y,a.z]=xyz(b);[b.x,b.y,b.z]=position;
    state.alpha=0.000001;
    const cloud=build(input,state);
    try {
      assert(cloud.isHot(),'cooling hid an unresolved nested crown');
      const ticks=settle(cloud);assert(ticks>8);
      return verifyCloud(cloud);
    }finally{dispose(initial);dispose(cloud);}
  });
  check(agentId+'_capacity_refresh_continuity',()=>{
    const input=hardwareFixture(agentId),original=build(input);let refresh;
    try {
      settle(original);const state=original.captureSimulation();
      const next=clone(input);next.nodes.reverse();next.edges.reverse();paint(next,'paint');
      refresh=build(next,state);
      assert.deepEqual(refresh.captureSimulation().layout,state.layout);
      assert.deepEqual(coordinates(refresh.captureSimNodes()),coordinates(original.captureSimNodes()));
      assert.equal(refresh.tickIfHot(),false);verifyCloud(refresh);
    }finally{dispose(original);if(refresh)dispose(refresh);}
  });
}
check('impossible_capacity_is_not_reported_as_settled',()=>{
  // Twenty nonoverlapping exclusion caps need more area than this shell has,
  // even after the documented bounded expansion budget. Never fake success.
  const nodes=Array.from({length:20},(_,i)=>kernelNode('n'+i,null,1,20,i,1,20));
  const force=kernel(nodes,new Map([[1,20]]));let ticks=0;
  while(force.needsTick()) {integrate(nodes,force,0);assert(++ticks<=900);}
  const state=force.capture();
  assert.equal(state.status,'needs-capacity');
  assert(state.residuals.maxOverlap>0.001);
  const radii=nodes.map(n=>norm(xyz(n)));
  assert(Math.max(...radii)-Math.min(...radii)<1e-7);
  return {ticks,status:state.status};
});
process.stdout.write(JSON.stringify(results));
"""


@pytest.fixture(scope="module")
def territory_results():
    result = subprocess.run(
        ["node", "-e", PROBE], input="{}", cwd=Path(__file__).parents[2],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("case", [
    "exact_angular_clearance", "contacts_stay_on_shells",
    "coupled_registration_and_2d_isolation", "rotation_and_permutation",
    "main_hardware_crown", "Alexandria_hardware_crown",
    "main_cold_nested_recovery", "Alexandria_cold_nested_recovery",
    "main_capacity_refresh_continuity", "Alexandria_capacity_refresh_continuity",
    "impossible_capacity_is_not_reported_as_settled",
])
def test_recursive_crowns_and_shell_constraints(territory_results, case):
    result = territory_results[case]
    assert result["ok"], result.get("error")
