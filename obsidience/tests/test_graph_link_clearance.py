"""Links follow their endpoint shells without stems, bows or force changes."""

import json
import subprocess
from pathlib import Path

import pytest

from test_graph_simulation_continuity import SIMULATION_PROBE


# Reuse the real TypeScript/Three.js/d3 loader and cloud fixture. These assertions
# measure the whole rendered segment against its interpolated radial level.
PROBE = SIMULATION_PROBE.split("if (options.legacy_source) {", 1)[0] + r"""
const {KNOWLEDGE_CROSS_SEGMENTS:segments,writeKnowledgeCrossRoute:writeRoute} =
  load(path.join(component,'knowledge-3d-links.ts'));
const norm=p=>Math.hypot(...p);
const dot=(a,b)=>a.reduce((sum,value,axis)=>sum+value*b[axis],0);
const sub=(a,b)=>a.map((value,axis)=>value-b[axis]);
const point=(buffer,index)=>Array.from(buffer.slice(index*3,index*3+3));
const samePoint=(a,b)=>assert(norm(sub(a,b))<1e-4,`${a} != ${b}`);
function segmentMargin(a,b,levelA,levelB) {
  // |a+t(b-a)|² - (levelA+t(levelB-levelA))² is quadratic. Its exact
  // minimum attests the entire drawn chord, including its endpoint intervals.
  const delta=sub(b,a),levelDelta=levelB-levelA;
  const quadratic=dot(delta,delta)-levelDelta*levelDelta;
  const linear=2*(dot(a,delta)-levelA*levelDelta);
  const value=t=>dot(a,a)-levelA*levelA+linear*t+quadratic*t*t;
  const candidates=[value(0),value(1)];
  if(quadratic>0)candidates.push(value(Math.max(0,Math.min(1,-linear/(2*quadratic)))));
  return Math.min(...candidates);
}
function checkRoute(route,a,b) {
  assert.equal(route.length,(segments+1)*3);
  assert.equal(segments,32,'endpoint stems added extra route segments');
  assert([...route].every(Number.isFinite),'nonfinite route');
  samePoint(point(route,0),a);samePoint(point(route,segments),b);
  const ra=norm(a),rb=norm(b);
  const cosine=ra>1e-8&&rb>1e-8?Math.max(-1,Math.min(1,dot(a,b)/(ra*rb))):1;
  const angle=Math.acos(cosine);
  const envelope=(1+2e-6)/Math.cos(angle/segments);
  const level=index=>ra+(rb-ra)*index/segments;
  let minimum=Infinity;
  for(let index=1;index<segments;index++) {
    const p=point(route,index),radius=norm(p),expected=level(index);
    assert(radius>=expected-1e-5,'sample dipped below its interpolated level');
    assert(radius<=expected*envelope+1e-5,
      `extra bow or endpoint lift: radius ${radius}, allowed ${expected*envelope}`);
    if(ra>1e-8&&rb>1e-8&&angle>1e-5) {
      const measured=Math.acos(Math.max(-1,Math.min(1,dot(a,p)/(ra*radius))));
      assert(Math.abs(measured-angle*index/segments)<1e-5,
        'angular progress paused for a radial stem or eased away from the endpoint');
    }
  }
  for(let segment=0;segment<segments;segment++) {
    const margin=segmentMargin(point(route,segment),point(route,segment+1),
      level(segment),level(segment+1));
    minimum=Math.min(minimum,margin);
    assert(margin>=-1e-6*Math.max(1,ra*ra,rb*rb),
      `segment ${segment} dipped below the interpolated shell: squared margin ${margin}`);
  }
  return minimum;
}
const routeCases={
  ordinary:[[30,0,0],[0,30,0]],
  unequal:[[12,0,0],[0,45,0]],
  antipodal_x:[[30,0,0],[-30,0,0]],
  antipodal_y:[[0,30,0],[0,-30,0]],
  antipodal_z:[[0,0,30],[0,0,-30]],
  antipodal_oblique:[[20,30,40],[-20,-30,-40]],
  near_antipodal:[[0,25,0],[1e-7,-25,2e-7]],
  near_antipodal_unequal:[[27,13,-6],[-54+2e-7,-26,12-2e-7]],
  near_parallel:[[20,0,0],[40,1e-7,0]],
  same_ray:[[10,0,0],[50,0,0]],
  coincident:[[10,20,30],[10,20,30]],
  one_at_origin:[[0,0,0],[0,30,0]],
  both_at_origin:[[0,0,0],[0,0,0]],
};
for(const [name,args] of Object.entries(routeCases))check(name,()=>{
  const route=new Float32Array((segments+1)*3).fill(NaN);
  writeRoute(route,...args);
  const margin=checkRoute(route,...args);
  const repeated=new Float32Array(route.length);writeRoute(repeated,...args);
  assert.deepEqual(route,repeated,'same endpoints changed their route');
  return {minimum_squared_shell_margin:margin};
});
check('angle_depth_matrix',()=>{
  let minimum=Infinity;
  for(const angle of [1e-8,0.01,0.3,1,Math.PI/2,Math.PI-0.01,Math.PI-1e-8])
    for(const ratio of [0.1,0.9,1,4]) {
      const a=[25,0,0],b=[25*ratio*Math.cos(angle),25*ratio*Math.sin(angle),0];
      const route=new Float32Array((segments+1)*3);writeRoute(route,a,b);
      minimum=Math.min(minimum,checkRoute(route,a,b));
    }
  return {minimum_squared_shell_margin:minimum};
});
function crossGeometry(cloud) {
  const mesh=cloud.group.children.find(child=>child.material?.fragmentShader==='cross'
    && !child.material.defines.KNOWLEDGE_REVIEW_EFFECT);
  assert(mesh);return mesh.geometry;
}
function routeFromGeometry(geometry) {
  const start=geometry.getAttribute('aStart'),end=geometry.getAttribute('aEnd');
  assert.equal(start.count,segments*4);
  const route=new Float32Array((segments+1)*3);
  for(let segment=0;segment<segments;segment++) {
    const a=[start.getX(segment*4),start.getY(segment*4),start.getZ(segment*4)];
    const b=[end.getX(segment*4),end.getY(segment*4),end.getZ(segment*4)];
    if(segment)samePoint(point(route,segment),a);
    route.set(a,segment*3);route.set(b,(segment+1)*3);
    for(let vertex=1;vertex<4;vertex++) {
      const index=segment*4+vertex;
      samePoint([start.getX(index),start.getY(index),start.getZ(index)],a);
      samePoint([end.getX(index),end.getY(index),end.getZ(index)],b);
    }
  }
  return route;
}
function checkStreakBinding(cloud,route) {
  const streak=cloud.group.children.find(child=>child.material?.fragmentShader==='particle');
  assert(streak?.isLineSegments,'streaks must draw individual route segments');
  const geometry=streak.geometry;
  const start=geometry.getAttribute('aStart'),end=geometry.getAttribute('aEnd');
  const range=geometry.getAttribute('aRange'),tip=geometry.getAttribute('aTip');
  const phase=geometry.getAttribute('aPhase'),speed=geometry.getAttribute('aSpeed');
  assert.equal(start.count,2*segments*2,'one long head/tail chord replaced segmented streaks');
  assert.equal(end.count,start.count);assert.equal(range.count,start.count);
  for(let particle=0;particle<2;particle++)for(let segment=0;segment<segments;segment++)
    for(let vertex=0;vertex<2;vertex++) {
      const index=(particle*segments+segment)*2+vertex;
      samePoint([start.getX(index),start.getY(index),start.getZ(index)],point(route,segment));
      samePoint([end.getX(index),end.getY(index),end.getZ(index)],point(route,segment+1));
      assert(Math.abs(range.getX(index)-segment/segments)<1e-7);
      assert(Math.abs(range.getY(index)-(segment+1)/segments)<1e-7);
      assert.equal(tip.getX(index),vertex);
      assert.equal(phase.getX(index),phase.getX(particle*segments*2));
      assert.equal(speed.getX(index),speed.getX(particle*segments*2));
    }
}
for(const agentId of ['main','Alexandria'])check(agentId+'_cloud',()=>{
  const input=fixture(agentId);
  input.tuning.streakCount=2;
  input.edges.push({source:'leaf-a',target:'leaf-b',taxonomy:false,
    color:'#22ccff',colorEnd:'#ff8844',preview:true});
  const original=build(input);settle(original);
  const state=original.captureSimulation();
  // Keep the near-antipodal endpoint case on this real cloud's semantic
  // layer. Unequal radii are covered by the pure route cases above.
  const leaf=state.nodes.get('leaf-a'),radius=Math.hypot(leaf.x,leaf.y,leaf.z);
  const start=[0,radius,0],end=[1e-7,-Math.sqrt(radius*radius-1e-14),0];
  Object.assign(state.nodes.get('leaf-a'),{x:start[0],y:start[1],z:0,vx:0,vy:0,vz:0});
  Object.assign(state.nodes.get('leaf-b'),{x:end[0],y:end[1],z:0,vx:0,vy:0,vz:0});
  const cloud=build(input,state),before=coordinates(cloud.captureSimNodes());
  const curve=routeFromGeometry(crossGeometry(cloud));
  checkRoute(curve,start,end);
  checkStreakBinding(cloud,curve);
  const proposal={id:'review',graphId:agentId,source:'leaf-a',target:'leaf-b',
    phase:'pending',startedAt:1000};
  cloud.applyRelationEffects([proposal],1500);
  const review=cloud.group.getObjectByName('knowledge-review-links');assert(review);
  assert.deepEqual(routeFromGeometry(review.geometry),curve,'review used another route');
  cloud.applyTuning({...input.tuning,crossCurve:0.8},1);
  assert.deepEqual(routeFromGeometry(crossGeometry(cloud)),curve,
    'retired crossCurve preference restored an outward bow');
  checkRoute(routeFromGeometry(crossGeometry(cloud)),start,end);
  checkStreakBinding(cloud,routeFromGeometry(crossGeometry(cloud)));
  assert.equal(cloud.captureSimulation().signature,state.signature);
  assert.equal(cloud.captureSimulation().alpha,state.alpha);
  assert.equal(cloud.tickIfHot(),false);
  assert.deepEqual(coordinates(cloud.captureSimNodes()),before,'routing moved nodes');
  const acceptedInput=clone(input);delete acceptedInput.edges.at(-1).preview;
  acceptedInput.nodes.reverse();acceptedInput.edges.reverse();
  const accepted=build(acceptedInput,state);
  assert.deepEqual(routeFromGeometry(crossGeometry(accepted)),curve,
    'approval or render-array order changed the route');
  assert.deepEqual(coordinates(accepted.captureSimNodes()),before);
  assert.equal(accepted.captureSimulation().alpha,state.alpha);
  const reciprocalInput=clone(input),reciprocalEdge=reciprocalInput.edges.at(-1);
  [reciprocalEdge.source,reciprocalEdge.target]=[reciprocalEdge.target,reciprocalEdge.source];
  [reciprocalEdge.color,reciprocalEdge.colorEnd]=[reciprocalEdge.colorEnd,reciprocalEdge.color];
  const reciprocal=build(reciprocalInput,state),reversed=new Float32Array(curve.length);
  for(let index=0;index<=segments;index++)reversed.set(point(curve,segments-index),index*3);
  assert.deepEqual(routeFromGeometry(crossGeometry(reciprocal)),reversed,
    'reciprocal edge took another side around the layer');
  checkStreakBinding(reciprocal,reversed);
  assert.equal(reciprocal.captureSimulation().signature,state.signature);
  assert.equal(reciprocal.captureSimulation().alpha,state.alpha);
  const unrelatedState={...state,nodes:new Map([...state.nodes].map(([id,node])=>[id,{...node}]))};
  Object.assign(unrelatedState.nodes.get('branch-b'),{x:10000,y:5000,z:0});
  const unrelated=build(input,unrelatedState);
  assert.deepEqual(routeFromGeometry(crossGeometry(unrelated)),curve,
    'an unrelated distant node changed this endpoint pair route');
  [original,cloud,accepted,reciprocal,unrelated].forEach(dispose);
});
process.stdout.write(JSON.stringify(results));
"""


@pytest.fixture(scope="module")
def clearance_results():
    result = subprocess.run(
        ["node", "-e", PROBE], input="{}", cwd=Path(__file__).parents[2],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize("case", [
    "ordinary", "unequal", "antipodal_x", "antipodal_y", "antipodal_z",
    "antipodal_oblique", "near_antipodal", "near_antipodal_unequal",
    "near_parallel", "same_ray", "coincident", "one_at_origin", "both_at_origin",
    "angle_depth_matrix", "main_cloud", "Alexandria_cloud",
])
def test_links_follow_the_live_endpoint_shells(clearance_results, case):
    result = clearance_results[case]
    assert result["ok"], result.get("error")
