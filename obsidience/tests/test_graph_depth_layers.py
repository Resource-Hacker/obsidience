"""Uneven real 3D clouds keep semantic depths on shared, readable layers."""

import json
import subprocess
from pathlib import Path

import pytest

from test_graph_simulation_continuity import SIMULATION_PROBE


PROBE = SIMULATION_PROBE.split("if (options.legacy_source) {", 1)[0] + r"""
function unevenFixture(agentId, heterogeneous) {
  const input=fixture(agentId),root=clone(input.nodes[0]);
  const branch=clone(input.nodes[1]),article=clone(input.nodes[3]);
  input.nodes=[root];input.edges=[];
  const add=(node,parentId)=>{
    input.nodes.push({...node,parentId});
    input.edges.push({source:parentId,target:node.id,taxonomy:true,color:'#22ccff'});
  };
  // Runbooks and Architecture are exact direct Brain children. Uneven
  // descendant density and different glyph radii may expand a whole layer,
  // but must not push one branch onto a different semantic layer.
  [1,2,4,8,16,32].forEach((count,b)=>{
    const id=b===4?'Architecture':b===5?'Runbooks':'branch-'+b;
    add({...branch,id,depth:1,radius:heterogeneous?7+b*4:7,
      x:0.5+Math.cos(b)*0.3,y:0.5+Math.sin(b)*0.3},'root');
    for(let c=0;c<count;c++) {
      const child=id+'-child-'+c;
      add({...article,id:child,depth:2,subject:true,role:'section',
        radius:heterogeneous?5+(c%4)*3:4},id);
      if(c%4===0)for(let d=0;d<3;d++)
        add({...article,id:child+'-article-'+d,depth:3,
          radius:heterogeneous?4+d*2:4},child);
    }
  });
  const byId=new Map(input.nodes.map(n=>[n.id,n]));
  assert.equal(input.nodes.length,121);
  assert.equal(input.nodes.filter(n=>n.parentId==='root').length,6);
  for(const node of input.nodes)if(node.id!=='root')
    assert.equal(byId.get(node.parentId).depth+1,node.depth,'invalid fixture ancestry');
  return input;
}
function measureLayers(cloud) {
  const nodes=[...cloud.captureSimNodes().values()],layers=new Map();
  coordinates(cloud.captureSimNodes()); // Every position and velocity is finite.
  for(const node of nodes) {
    if(node.id==='root') {
      assert.deepEqual([node.x,node.y,node.z],[0,0,0]);
    } else {
      assert(node.fx==null&&node.fy==null&&node.fz==null,
        'nonroot coordinate was pinned: '+node.id);
    }
    const radius=Math.hypot(node.x,node.y,node.z);
    assert(Number.isFinite(node.radius)&&node.radius>0,'invalid visible node size');
    if(!layers.has(node.depth))layers.set(node.depth,[]);
    layers.get(node.depth).push({radius,core:node.radius});
  }
  let spread=0,envelopeGap=Infinity,previousOuter=null;
  const radii=[];
  for(const [depth,layer] of [...layers].sort(([a],[b])=>a-b)) {
    const inner=Math.min(...layer.map(n=>n.radius-n.core));
    const outer=Math.max(...layer.map(n=>n.radius+n.core));
    const minimum=Math.min(...layer.map(n=>n.radius));
    const maximum=Math.max(...layer.map(n=>n.radius));
    spread=Math.max(spread,maximum-minimum);
    if(previousOuter!==null)envelopeGap=Math.min(envelopeGap,inner-previousOuter);
    previousOuter=outer;
    radii.push({depth,minimum,maximum,inner,outer,count:layer.length});
  }
  return {spread,envelopeGap,radii};
}
function coreGap(cloud) {
  const nodes=[...cloud.captureSimNodes().values()];let gap=Infinity;
  for(let a=0;a<nodes.length;a++)for(let b=a+1;b<nodes.length;b++) {
    const x=nodes[a],y=nodes[b];
    gap=Math.min(gap,Math.hypot(x.x-y.x,x.y-y.y,x.z-y.z)-x.radius-y.radius);
  }
  return gap;
}
function projectedFixture(agentId) {
  const {layoutKnowledgeGraph}=load(path.join(component,'knowledge-layout.ts'));
  const rows=[['root',null,'root'],['Architecture','root','section'],
    ['Runbooks','root','section'],['nested','Runbooks','section'],
    ['deep-parent','nested','section'],['shallow-article','Architecture','claim'],
    ['middle-article','nested','claim'],['deep-article','deep-parent','claim']];
  const graph={nodes:rows.map(([id,parentId,role],order)=>({
    id,parentId,role,order,label:id,degree:1,kind:role==='claim'?'article':'subject',
  })),edges:rows.filter(([,parent])=>parent!==null).map(([id,parent])=>({
    id:parent+'->'+id,source:parent,target:id,type:'taxonomy',
  }))};
  const graphBefore=clone(graph),layout=layoutKnowledgeGraph(graph);
  assert.deepEqual(graph,graphBefore,'layout changed the input graph metadata');
  const byId=new Map(layout.nodes.map(n=>[n.id,n]));
  // Reproduce the real rendering contract: Articles share the deepest paint
  // tier even when their exact parents are at different semantic depths.
  assert.equal(byId.get('shallow-article').depth,byId.get('deep-article').depth);
  assert.equal(byId.get('Architecture').depth,1);
  assert.equal(byId.get('deep-parent').depth,3);
  assert.notEqual(byId.get('shallow-article').depth,2);
  const input=fixture(agentId),style=clone(input.nodes[3]);
  input.nodes=layout.nodes.map(n=>({...style,...n,
    subject:n.role!=='claim',radius:n.role==='root'?12:n.role==='section'?9:5}));
  input.edges=graph.edges.map(e=>({source:e.source,target:e.target,
    taxonomy:true,color:'#22ccff'}));
  return {input,graph,layout};
}
for(const agentId of ['main','Alexandria'])for(const profile of ['default','projected'])
  check(agentId+'_close_first_layer_'+profile,()=>{
    const input=profile==='default'?fixture(agentId):projectedFixture(agentId).input;
    const cloud=build(input);
    const inspect=()=>{
      const layers=measureLayers(cloud),first=layers.radii.find(layer=>layer.depth===1);
      // The accepted normal first tier was near 19–20 world units. Adding
      // semantic shells must not move its peers out to the old 35–41 range.
      assert(first.minimum>=18&&first.maximum<=22,
        'default first tier left its close scale: '+JSON.stringify(first));
      assert(layers.spread<=1e-7);
      assert(layers.envelopeGap>=-1e-7);
      return first;
    };
    try {
      inspect();
      let ticks=0;
      while(cloud.tickIfHot()) {assert(++ticks<1000);inspect();}
      geometryMatches(cloud,input);
      return {first_layer:inspect()};
    } finally {dispose(cloud);}
  });
for(const agentId of ['main','Alexandria'])for(const growth of ['deeper','crowded'])
  check(agentId+'_local_layer_growth_'+growth,()=>{
    const {input}=projectedFixture(agentId);
    // An existing section gains descendants without changing its own role,
    // size or parent. All original layers retain exactly the same members.
    Object.assign(input.nodes.find(node=>node.id==='deep-article'),
      {role:'section',subject:true});
    const original=build(input);let enlarged;
    try {
      settle(original);
      const before=measureLayers(original),expanded=clone(input);
      const template=clone(input.nodes.find(node=>node.id==='deep-article'));
      const append=(id,parentId,depth,radius)=>{
        expanded.nodes.push({...template,id,parentId,depth,radius});
        expanded.edges.push({source:parentId,target:id,taxonomy:true,color:'#22ccff'});
      };
      if(growth==='deeper') {
        let parent='deep-article';
        for(let depth=5;depth<=8;depth++) {
          const id='new-depth-'+depth;
          append(id,parent,depth,5);parent=id;
        }
      } else {
        for(let index=0;index<40;index++)append('new-peer-'+index,'deep-article',5,12);
      }
      assert.deepEqual(expanded.nodes.slice(0,input.nodes.length),input.nodes);
      enlarged=build(expanded,original.captureSimulation());
      const inspect=()=>{
        const current=measureLayers(enlarged);
        assert(current.spread<=1e-7,'descendants broke shared semantic shells');
        assert(current.envelopeGap>=-1e-7,'descendant layers overlap');
        for(const layer of before.radii) {
          const after=current.radii.find(row=>row.depth===layer.depth);
          assert.equal(after.count,layer.count);
          assert(Math.abs(after.minimum-layer.minimum)<=1e-7
            &&Math.abs(after.maximum-layer.maximum)<=1e-7,
            'new descendants displaced unchanged layer '+layer.depth+': '
              +layer.minimum+' -> '+after.minimum);
        }
      };
      inspect();geometryMatches(enlarged,expanded);
      let ticks=0;
      while(enlarged.tickIfHot()) {assert(++ticks<1000);inspect();}
      assert(ticks>0);geometryMatches(enlarged,expanded);
    } finally {if(enlarged)dispose(enlarged);dispose(original);}
  });
for(const agentId of ['main','Alexandria'])check(agentId+'_projected_parentage',()=>{
  const {input,graph,layout}=projectedFixture(agentId);
  const inputBefore=clone(input),graphBefore=clone(graph),layoutBefore=clone(layout);
  const cloud=build(input);let refreshed;
  const inspect=()=>{
    const nodes=cloud.captureSimNodes();
    for(const node of nodes.values())if(node.parentId)
      assert.equal(node.depth,nodes.get(node.parentId).depth+1,
        'private 3D depth did not follow exact parent: '+node.id);
    assert.equal(nodes.get('shallow-article').depth,2);
    assert.equal(nodes.get('middle-article').depth,3);
    assert.equal(nodes.get('deep-article').depth,4);
    const layers=measureLayers(cloud);
    assert(layers.spread<=1e-7,'semantic peers left their shared shell');
    assert(layers.envelopeGap>=-1e-7,'semantic layer envelopes overlap');
    assert.deepEqual(input,inputBefore,'private depth rewrote renderer inputs');
    assert.deepEqual(layout,layoutBefore,'private depth rewrote display tiers');
    assert.deepEqual(graph,graphBefore,'private depth rewrote graph metadata');
  };
  try {
    inspect();geometryMatches(cloud,input);
    let ticks=0;
    while(cloud.tickIfHot()) {assert(++ticks<1000);inspect();}
    assert(ticks>0);assert(coreGap(cloud)>=-1e-6);
    const state=cloud.captureSimulation(),before=coordinates(state.nodes);
    const painted=clone(input);paint(painted,'paint');painted.nodes.reverse();
    refreshed=build(painted,state);
    assert.equal(refreshed.captureSimulation().signature,state.signature);
    assert.equal(refreshed.captureSimulation().alpha,state.alpha);
    assert.equal(refreshed.tickIfHot(),false);
    assert.deepEqual(coordinates(refreshed.captureSimNodes()),before,
      'display-tier metadata reheated or displaced a normalized simulation');
  } finally {if(refreshed)dispose(refreshed);dispose(cloud);}
});
for(const agentId of ['main','Alexandria'])check(agentId+'_branch_outer_reach',()=>{
  const {input}=projectedFixture(agentId),cloud=build(input);
  try {
    settle(cloud);
    const nodes=cloud.captureSimNodes(),reaches=new Map();
    for(const node of nodes.values()) {
      if(node.role==='root')continue;
      let branch=node;
      while(nodes.get(branch.parentId)?.role!=='root')branch=nodes.get(branch.parentId);
      const radius=Math.hypot(node.x,node.y,node.z);
      reaches.set(branch.id,Math.max(reaches.get(branch.id)??0,radius));
    }
    assert.equal(reaches.size,2);
    const values=[...reaches.values()];
    // Equal semantic layers must not make the shallow Article branch end
    // halfway inside the deep branch's outer extent, as linear spacing did.
    const ratio=Math.max(...values)/Math.min(...values);
    assert(ratio<=1.7,'uneven semantic depths stretched the whole cloud: '+ratio);
    return {outer_reach_ratio:ratio};
  } finally {dispose(cloud);}
});
check('two_dimensions_keep_display_tiers',()=>{
  const {input}=projectedFixture('main');
  const nodes=input.nodes.map(n=>({...n,vx:0,vy:0,vz:0}));
  const before=nodes.map(n=>[n.id,n.depth,n.parentId]);
  const simulation=physics.createKnowledgeForceSimulation(nodes,[],input.tuning,2);
  try {
    assert.equal(simulation.force('depthLayers'),undefined);
    simulation.tick(20);
    assert.deepEqual(nodes.map(n=>[n.id,n.depth,n.parentId]),before);
    coordinates(new Map(nodes.map(n=>[n.id,n])));
  } finally {simulation.stop();}
});
check('incomplete_parentage_uses_bounded_fallback',()=>{
  const input=[['root',null,0,'root'],['valid','root',99,'section'],
    ['valid-child','valid',99,'claim'],['missing','absent',7,'claim'],
    ['cycle-a','cycle-b',8,'section'],['cycle-b','cycle-a',9,'section'],
    ['self','self',6,'claim']].map(([id,parentId,depth,role],index)=>({
      id,parentId,depth,role,radius:2,x:index,y:index,z:index,vx:0,vy:0,vz:0,
    }));
  const expected=new Map([['root',0],['valid',1],['valid-child',2],['missing',7],
    ['cycle-a',8],['cycle-b',9],['self',6]]);
  for(const reverse of [false,true]) {
    const nodes=clone(input);if(reverse)nodes.reverse();
    const simulation=physics.createKnowledgeForceSimulation(nodes,[]);
    try {
      for(const node of nodes)assert.equal(node.depth,expected.get(node.id));
      simulation.tick(20);
      coordinates(new Map(nodes.map(n=>[n.id,n])));
    } finally {simulation.stop();}
  }
});
for(const agentId of ['main','Alexandria']) {
  for(const profile of ['uniform','varied','compact','compact_large','wide'])
    check(agentId+'_'+profile,()=>{
    const input=unevenFixture(agentId,profile!=='uniform');
    // Exercise the public Layout/Nodes controls at their supported extremes.
    if(profile==='compact'||profile==='compact_large') {
      input.tuning.linkDistance=0.4;
      if(profile==='compact_large')
        for(const key of ['sizeCore','sizeBranch','sizeSubnode','sizeChild','sizeArticle'])
          input.tuning[key]=2.2;
    } else if(profile==='wide')input.tuning.linkDistance=2;
    const cloud=build(input);
    try {
      const initial=measureLayers(cloud);
      geometryMatches(cloud,input);
      let ticks=0,maximumSpread=0,minimumEnvelopeGap=initial.envelopeGap;
      while(cloud.tickIfHot()) {
        assert(++ticks<1000,'shared layers prevented bounded cooling');
        const current=measureLayers(cloud);
        maximumSpread=Math.max(maximumSpread,current.spread);
        minimumEnvelopeGap=Math.min(minimumEnvelopeGap,current.envelopeGap);
      }
      assert(ticks>0);assert.equal(cloud.isHot(),false);
      geometryMatches(cloud,input);
      const final=measureLayers(cloud);
      return {ticks,initial_spread:initial.spread,
        maximum_spread:maximumSpread,settled_spread:final.spread,
        minimum_envelope_gap:minimumEnvelopeGap,minimum_core_gap:coreGap(cloud),
        layers:final.radii};
    } finally {dispose(cloud);}
  });
  for(const phase of ['hot','cooled'])for(const change of ['paint','approval'])
    check(agentId+'_'+phase+'_'+change,()=>{
      const input=unevenFixture(agentId,true);
      input.edges.push({source:'Architecture-child-0-article-0',
        target:'Runbooks-child-0-article-0',taxonomy:false,preview:true,color:'#22ccff'});
      const original=build(input);let refreshed;
      try {
        if(phase==='cooled')settle(original);
        else for(let tick=0;tick<20;tick++)original.tickIfHot();
        const before=original.captureSimulation(),positions=coordinates(before.nodes);
        const next=clone(input);
        if(change==='paint')paint(next,'paint');
        else {
          delete next.edges.at(-1).preview;
          next.nodes.reverse();next.edges.reverse();
        }
        refreshed=build(next,before);
        const after=refreshed.captureSimulation();
        assert.equal(after.signature,before.signature);
        assert.equal(after.alpha,before.alpha,'presentation restarted layer cooling');
        assert.equal(refreshed.isHot(),phase==='hot');
        assert.deepEqual(coordinates(after.nodes),positions,'presentation disturbed shared layers');
        geometryMatches(refreshed,next);
        for(let tick=0;tick<20;tick++) {
          assert.equal(refreshed.tickIfHot(),original.tickIfHot());
          assert.deepEqual(coordinates(refreshed.captureSimNodes()),
            coordinates(original.captureSimNodes()),'presentation changed the real trajectory');
        }
        if(phase==='cooled')assert.deepEqual(coordinates(refreshed.captureSimNodes()),positions);
      } finally {
        if(refreshed)dispose(refreshed);
        dispose(original);
      }
    });
}
for(const decay of [0.35,1])check('zero_vectors_'+decay,()=>{
  const input=unevenFixture('main',true).nodes.slice(0,2).map(n=>({
    id:n.id,parentId:n.parentId,depth:n.depth,role:n.role,radius:n.radius,
    x:0,y:0,z:0,vx:0,vy:0,vz:0,
  }));
  input.push({...input[1],id:'peer'});
  const run=()=>{
    const nodes=clone(input),tuning={...physics.DEFAULT_KNOWLEDGE_3D_TUNING,
      velocityDecay:decay};
    const simulation=physics.createKnowledgeForceSimulation(nodes,[],tuning);
    assert.equal(typeof simulation.force('depthLayers'),'function');
    // Isolate the actual layer force while retaining d3's real integration.
    for(const name of ['link','charge','collide','dagRadial','outwardHemisphere','branchTerritory'])
      simulation.force(name,null);
    for(const node of nodes)Object.assign(node,{x:0,y:0,z:0,vx:0,vy:0,vz:0});
    for(let tick=0;tick<20;tick++) {
      simulation.tick();
      const state=new Map(nodes.map(n=>[n.id,n]));
      coordinates(state);
      assert.deepEqual([nodes[0].x,nodes[0].y,nodes[0].z],[0,0,0]);
      const radii=nodes.slice(1).map(n=>Math.hypot(n.x,n.y,n.z));
      assert(radii.every(r=>r>0));
      assert(Math.max(...radii)-Math.min(...radii)<=1e-7);
      assert(nodes.slice(1).every(n=>n.fx==null&&n.fy==null&&n.fz==null));
    }
    simulation.stop();
    return coordinates(new Map(nodes.map(n=>[n.id,n])));
  };
  assert.deepEqual(run(),run(),'zero-vector fallback is not deterministic');
});
process.stdout.write(JSON.stringify(results));
"""


@pytest.fixture(scope="module")
def layer_results():
    result = subprocess.run(
        ["node", "-e", PROBE], input="{}", cwd=Path(__file__).parents[2],
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.fixture(params=[
    f"{agent}_{profile}"
    for agent in ("main", "Alexandria")
    for profile in ("uniform", "varied", "compact", "compact_large", "wide")
])
def settled_layers(layer_results, request):
    result = layer_results[request.param]
    assert result["ok"], result.get("error")
    return result


def test_equal_semantic_depth_shares_one_radius_after_every_tick(settled_layers):
    assert settled_layers["maximum_spread"] <= 1e-7, settled_layers
    assert settled_layers["settled_spread"] <= 1e-7, settled_layers


def test_first_visible_frame_already_uses_shared_semantic_layers(settled_layers):
    assert settled_layers["initial_spread"] <= 1e-7, settled_layers


@pytest.mark.parametrize("agent_id", ["main", "Alexandria"])
@pytest.mark.parametrize("profile", ["default", "projected"])
def test_default_first_layer_stays_at_the_accepted_close_scale(
    layer_results, agent_id, profile,
):
    result = layer_results[f"{agent_id}_close_first_layer_{profile}"]
    assert result["ok"], result.get("error")


@pytest.mark.parametrize("agent_id", ["main", "Alexandria"])
@pytest.mark.parametrize("growth", ["deeper", "crowded"])
def test_new_descendants_preserve_every_unchanged_shallower_layer(
    layer_results, agent_id, growth,
):
    result = layer_results[f"{agent_id}_local_layer_growth_{growth}"]
    assert result["ok"], result.get("error")


def test_semantic_layers_keep_ordered_nonoverlapping_core_envelopes(settled_layers):
    assert settled_layers["minimum_envelope_gap"] >= -1e-7, settled_layers


def test_uneven_shared_layers_settle_without_overlapping_node_cores(settled_layers):
    assert settled_layers["minimum_core_gap"] >= -1e-6, settled_layers


@pytest.mark.parametrize("agent_id", ["main", "Alexandria"])
@pytest.mark.parametrize("phase", ["hot", "cooled"])
@pytest.mark.parametrize("change", ["paint", "approval"])
def test_dense_layer_presentation_preserves_positions_velocity_and_cooling(
    layer_results, agent_id, phase, change,
):
    result = layer_results[f"{agent_id}_{phase}_{change}"]
    assert result["ok"], result.get("error")


@pytest.mark.parametrize("agent_id", ["main", "Alexandria"])
@pytest.mark.parametrize("profile", ["compact_large", "wide"])
def test_larger_glyphs_or_spacing_expand_whole_layers(layer_results, agent_id, profile):
    base_profile = "compact" if profile == "compact_large" else "varied"
    base = layer_results[f"{agent_id}_{base_profile}"]
    enlarged = layer_results[f"{agent_id}_{profile}"]
    assert base["ok"], base.get("error")
    assert enlarged["ok"], enlarged.get("error")
    for before, after in zip(base["layers"][1:], enlarged["layers"][1:], strict=True):
        assert before["depth"] == after["depth"]
        assert after["minimum"] > before["maximum"] + 1e-7
        assert after["maximum"] - after["minimum"] <= 1e-7


@pytest.mark.parametrize("decay", [0.35, 1])
def test_zero_vector_recovery_is_finite_unpinned_and_deterministic(layer_results, decay):
    result = layer_results[f"zero_vectors_{decay}"]
    assert result["ok"], result.get("error")


@pytest.mark.parametrize("agent_id", ["main", "Alexandria"])
def test_real_layout_articles_use_private_semantic_parent_depth(layer_results, agent_id):
    result = layer_results[f"{agent_id}_projected_parentage"]
    assert result["ok"], result.get("error")


@pytest.mark.parametrize("agent_id", ["main", "Alexandria"])
def test_shallow_and_deep_branches_keep_comparable_outer_reach(layer_results, agent_id):
    result = layer_results[f"{agent_id}_branch_outer_reach"]
    assert result["ok"], result.get("error")


@pytest.mark.parametrize("case", [
    "two_dimensions_keep_display_tiers", "incomplete_parentage_uses_bounded_fallback",
])
def test_depth_normalization_preserves_projection_and_handles_incomplete_trees(layer_results, case):
    result = layer_results[case]
    assert result["ok"], result.get("error")
