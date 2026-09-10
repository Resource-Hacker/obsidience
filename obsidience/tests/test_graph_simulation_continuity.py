"""Run the real shared Three.js/d3 cloud without a browser or live graph writes."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


SIMULATION_PROBE = r"""
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {strict: assert} = require('node:assert');
const {createRequire} = require('node:module');
const ui = path.resolve('obsidience/ui');
const nativeRequire = createRequire(path.join(ui, 'package.json'));
const ts = nativeRequire('typescript');
const THREE = nativeRequire('three');
const options = JSON.parse(fs.readFileSync(0, 'utf8'));
const component = path.join(ui, 'src/renderer/src/components/themes/obsidience');
const cloudFile = path.join(component, 'knowledge-3d-cloud.ts');
const cache = new Map();
function load(filename) {
  if (cache.has(filename)) return cache.get(filename).exports;
  const mod = {exports:{}};
  cache.set(filename, mod);
  const localRequire = id => {
    if (!id.startsWith('.')) return nativeRequire(id);
    const base = path.resolve(path.dirname(filename), id);
    const target = [base, base+'.ts', base+'.tsx'].find(candidate =>
      fs.existsSync(candidate) && fs.statSync(candidate).isFile());
    assert(target, 'unresolved real dependency: '+id);
    return load(target);
  };
  // Diagnostic replay reads the exact preimage; production files stay untouched.
  const selected = filename === cloudFile && options.legacy_source
    ? options.legacy_source : filename;
  const source = ts.transpileModule(fs.readFileSync(selected, 'utf8'), {
    compilerOptions:{module:ts.ModuleKind.CommonJS, target:ts.ScriptTarget.ES2022,
      esModuleInterop:true},
  }).outputText;
  vm.runInThisContext('(function(require,module,exports){'+source+'\n})', {filename})(
    localRequire, mod, mod.exports);
  return mod.exports;
}
const physics = load(path.join(component, 'knowledge-3d.ts'));
const {createKnowledge3dCloud} = load(cloudFile);
const deps = {
  pointVertexShader:'point', pointFragmentShader:'point', pointDepthFragmentShader:'depth',
  beamVertexShader:'beam', taxonomyFragmentShader:'taxonomy', crossFragmentShader:'cross',
  particleVertexShader:'particle', particleFragmentShader:'particle', particleTime:{value:0},
  parseColor: css => {
    const color = new THREE.Color(css);
    return {r:color.r, g:color.g, b:color.b, a:1};
  },
  sharedUniforms:{uPerspective:{value:1}, uPulse:{value:0}, uTime:{value:0}},
  viewportUniform:{value:new THREE.Vector2(1920,1200)},
};
function fixture(agentId='main') {
  const node = (id, depth, parentId, x, y) => ({
    id, depth, parentId, x, y, role:depth===0?'root':depth===1?'section':'claim',
    radius:depth===0?12:depth===1?7:4, subject:depth<2,
    core:'#22ccff', dark:'#02060c', ring:'#44ddff', glow:'#115577',
    ringScale:1.2, ringWidth:1, glowScale:1.5, alpha:0.8, autoCurated:false,
  });
  return {
    agentId, main:agentId==='main', hub:{x:0.5,y:0.5},
    nodes:[node('root',0,null,0.5,0.5), node('branch-a',1,'root',0.2,0.4),
      node('branch-b',1,'root',0.8,0.6), node('leaf-a',2,'branch-a',0.1,0.2),
      node('leaf-b',2,'branch-b',0.9,0.8)],
    edges:[['root','branch-a'],['root','branch-b'],['branch-a','leaf-a'],
      ['branch-b','leaf-b']].map(([source,target])=>({source,target,taxonomy:true,color:'#22ccff'})),
    tuning:{...physics.DEFAULT_KNOWLEDGE_3D_TUNING},
  };
}
const clone = input => JSON.parse(JSON.stringify(input));
const build = (input, previous, height=1200, pixelRatio=1) =>
  createKnowledge3dCloud(input,deps,height,pixelRatio,previous);
const dispose = cloud => cloud.dispose(new THREE.Scene());
function settle(cloud) {
  let ticks = 0;
  while (cloud.tickIfHot()) assert(++ticks < 1000, 'real simulation did not cool');
  assert(ticks > 0);
  assert.equal(cloud.isHot(),false);
  return ticks;
}
function coordinates(nodes) {
  return [...nodes].sort(([a],[b])=>a.localeCompare(b)).map(([id,n])=>{
    const values = [n.x,n.y,n.z,n.vx,n.vy,n.vz];
    assert(values.every(Number.isFinite), 'nonfinite simulation state for '+id);
    return [id,...values];
  });
}
function displacement(before, after) {
  const positions = new Map(before.map(([id,...values])=>[id,values]));
  return Math.max(0,...after.filter(([id])=>positions.has(id)).map(([id,...values])=>
    Math.hypot(...values.slice(0,3).map((value,axis)=>value-positions.get(id)[axis]))));
}
function points(cloud) {
  const mesh = cloud.group.children.find(child=>child.material?.fragmentShader==='point');
  assert(mesh?.geometry.getAttribute('position'), 'real point geometry was not built');
  return mesh;
}
function geometryMatches(cloud,input) {
  const geometry = points(cloud).geometry;
  const position = geometry.getAttribute('position');
  const radius = geometry.getAttribute('aRadius');
  const nodes = cloud.captureSimNodes();
  assert.equal(position.count,input.nodes.length);
  input.nodes.forEach((node,index)=>{
    const actual = nodes.get(node.id);
    [actual.x,actual.y,actual.z].forEach((value,axis)=>{
      assert(Math.abs(position.array[index*3+axis]-value)<0.0001,'painted position mismatch');
    });
    assert(radius.getX(index)>0, 'node has no readable positive radius');
  });
}
function paint(input,variant) {
  if (variant==='paint') {
    input.nodes.forEach(node=>{node.core='#ff4400';node.alpha=0.6;});
    input.edges.forEach(edge=>{edge.color='#ff4400';});
  } else if (variant==='auto_curate') input.nodes[3].autoCurated=true;
  else if (variant==='visual_tuning') {
    input.tuning.lineArticles=0;
    input.tuning.lineBranches=0;
    input.tuning.nodeGlow*=1.4;
    input.tuning.graphScale*=1.2;
    input.tuning.streakCount+=1;
  } else if (variant==='order') {
    input.nodes.reverse();input.edges.reverse();
  } else if (variant==='seed_layout') {
    input.nodes.forEach(node=>{node.x=1-node.x;node.y=1-node.y;});
  } else throw new Error('unknown presentation change '+variant);
}
function assertPaint(cloud,input,variant) {
  geometryMatches(cloud,input);
  const mesh = points(cloud);
  if (variant==='paint') {
    const color = new THREE.Color('#ff4400');
    const cores = mesh.geometry.getAttribute('aCore');
    assert(Math.abs(cores.getX(0)-color.r)<0.000001);
    assert(Math.abs(cores.getY(0)-color.g)<0.000001);
    assert(Math.abs(mesh.geometry.getAttribute('aStyle').getW(0)-0.6)<0.000001);
  } else if (variant==='auto_curate') {
    assert.equal(mesh.geometry.getAttribute('aCurate').getX(3),1);
  } else if (variant==='visual_tuning') {
    assert.equal(mesh.material.uniforms.uGlowScale.value,input.tuning.nodeGlow);
  }
}
const results = {};
function check(name,run) {
  try {results[name]={ok:true,...(run()??{})};}
  catch(error) {results[name]={ok:false,error:error.stack};}
}
if (options.legacy_source) {
  check('legacy_paint',()=>{
    const input=fixture();const original=build(input);settle(original);
    const previous=original.captureSimNodes();const before=coordinates(previous);
    const next=clone(input);paint(next,'paint');dispose(original);
    const refreshed=build(next,previous);
    const reheated=refreshed.isHot();
    for(let n=0;n<12;n++)refreshed.tickIfHot();
    const moved=displacement(before,coordinates(refreshed.captureSimNodes()));
    dispose(refreshed);
    assert(reheated && moved>0, 'legacy defect did not reproduce');
    return {reheated,max_displacement_world_units:moved,ticks_after_refresh:12};
  });
} else {
  for(const phase of ['cooled','hot']) for(const variant of
      ['paint','auto_curate','visual_tuning','order','seed_layout']) {
    check(phase+'_'+variant,()=>{
      const input=fixture();const original=build(input);
      if(phase==='cooled')settle(original);else for(let n=0;n<12;n++)original.tickIfHot();
      const previous=original.captureSimulation();const before=coordinates(previous.nodes);
      const next=clone(input);paint(next,variant);const refreshed=build(next,previous);
      const state=refreshed.captureSimulation();
      assert.equal(state.signature,previous.signature);
      assert.equal(state.alpha,previous.alpha,'presentation restarted the cooldown');
      assert.deepEqual(coordinates(state.nodes),before,'presentation moved a node or reset velocity');
      assert.equal(refreshed.isHot(),phase==='hot');
      assertPaint(refreshed,next,variant);
      for(let n=0;n<12;n++) {
        assert.equal(refreshed.tickIfHot(),original.tickIfHot());
      }
      assert.equal(refreshed.captureSimulation().alpha,original.captureSimulation().alpha);
      if(phase==='cooled') {
        assert.deepEqual(coordinates(refreshed.captureSimNodes()),before);
      } else if(variant!=='order') {
        assert.deepEqual(coordinates(refreshed.captureSimNodes()),coordinates(original.captureSimNodes()),
          'unchanged forces no longer follow the uninterrupted trajectory');
      }
      const moved=displacement(before,coordinates(refreshed.captureSimNodes()));
      dispose(refreshed);dispose(original);
      return {max_displacement_world_units:moved,alpha:state.alpha};
    });
  }
  const physical=['node','edge','edge_kind','parent','depth','role','radius',
    'charge','velocity','link_distance','node_size','viewport'];
  for(const change of physical)check('physical_'+change,()=>{
    const input=fixture();const original=build(input);settle(original);
    const previous=original.captureSimulation();const next=clone(input);let height=1200;
    if(change==='node') {
      next.nodes.push({...next.nodes[3],id:'new-leaf',x:0.35,y:0.15});
      next.edges.push({source:'branch-a',target:'new-leaf',taxonomy:true,color:'#22ccff'});
    } else if(change==='edge')next.edges.push({source:'leaf-a',target:'leaf-b',taxonomy:false,color:'#22ccff'});
    else if(change==='edge_kind')next.edges[2].taxonomy=false;
    else if(change==='parent')next.nodes[3].parentId='branch-b';
    else if(change==='depth') {
      // Physical depth changes through ancestry, not the 2D Article paint tier.
      next.nodes[1].parentId='branch-b';
      next.edges.find(edge=>edge.target==='branch-a').source='branch-b';
    }
    else if(change==='role')next.nodes[3].role='section';
    else if(change==='radius')next.nodes[3].radius*=1.5;
    else if(change==='charge')next.tuning.chargeStrength*=1.2;
    else if(change==='velocity')next.tuning.velocityDecay*=0.8;
    else if(change==='link_distance')next.tuning.linkDistance*=1.2;
    else if(change==='node_size')next.tuning.sizeArticle*=1.3;
    else if(change==='viewport')height=900;
    const refreshed=build(next,previous,height);const state=refreshed.captureSimulation();
    assert.notEqual(state.signature,previous.signature);
    assert(refreshed.isHot(),'changed physical constraint was left cold');
    assert(state.alpha>previous.alpha);
    assert(refreshed.tickIfHot());geometryMatches(refreshed,next);
    if(change==='node')assert(refreshed.captureSimNodes().has('new-leaf'));
    dispose(refreshed);dispose(original);
  });
  check('unaffected_cloud',()=>{
    const aInput=fixture();const bInput=fixture('Darwin');
    const a=build(aInput);const b=build(bInput);settle(a);settle(b);
    const aState=a.captureSimulation();const bState=b.captureSimulation();
    const bBefore=coordinates(bState.nodes);const changed=clone(aInput);
    changed.tuning.chargeStrength*=1.2;
    const nextA=build(changed,aState);const nextB=build(clone(bInput),bState);
    assert(nextA.isHot());assert.equal(nextB.isHot(),false);
    assert.equal(nextB.tickIfHot(),false);
    assert.deepEqual(coordinates(nextB.captureSimNodes()),bBefore);
    [a,b,nextA,nextB].forEach(dispose);
  });
  check('pixel_ratio_paint',()=>{
    const input=fixture();const original=build(input);settle(original);
    const state=original.captureSimulation();const before=coordinates(state.nodes);
    const refreshed=build(clone(input),state,1200,2);
    assert.equal(refreshed.captureSimulation().signature,state.signature);
    assert.equal(refreshed.isHot(),false);
    assert.equal(refreshed.tickIfHot(),false);
    assert.deepEqual(coordinates(refreshed.captureSimNodes()),before);
    assert.equal(points(refreshed).geometry.getAttribute('aStyle').getZ(0),
      points(original).geometry.getAttribute('aStyle').getZ(0)*2);
    dispose(refreshed);dispose(original);
  });
}
process.stdout.write(JSON.stringify(results));
"""


def run_probe(*, legacy_source: Path | None = None) -> dict:
    options = {"legacy_source": str(legacy_source)} if legacy_source else {}
    result = subprocess.run(
        ["node", "-e", SIMULATION_PROBE], input=json.dumps(options),
        cwd=Path(__file__).parents[2], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.fixture(scope="module")
def simulation_results():
    return run_probe()


@pytest.mark.parametrize("phase", ["cooled", "hot"])
@pytest.mark.parametrize("change", ["paint", "auto_curate", "visual_tuning", "order", "seed_layout"])
def test_presentation_refresh_preserves_real_simulation(simulation_results, phase, change):
    result = simulation_results[f"{phase}_{change}"]
    assert result["ok"], result.get("error")
    if phase == "cooled":
        assert result["max_displacement_world_units"] == 0


@pytest.mark.parametrize("change", [
    "node", "edge", "edge_kind", "parent", "depth", "role", "radius",
    "charge", "velocity", "link_distance", "node_size", "viewport",
])
def test_actual_physical_changes_reheat_the_cloud(simulation_results, change):
    result = simulation_results[f"physical_{change}"]
    assert result["ok"], result.get("error")


def test_unaffected_agent_cloud_stays_settled(simulation_results):
    result = simulation_results["unaffected_cloud"]
    assert result["ok"], result.get("error")


def test_pixel_ratio_updates_ring_geometry_without_reheating(simulation_results):
    result = simulation_results["pixel_ratio_paint"]
    assert result["ok"], result.get("error")
