"""Exercise the actual backdrop model and Three.js cross-link geometry."""

import json
import importlib
import subprocess
from pathlib import Path

from obsidience.harness.config import CONFIG
from obsidience.harness.knowledge.vault import write_note


RENDER_PROBE = r"""
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { createRequire } = require('node:module');
const ui = path.resolve('obsidience/ui');
const nativeRequire = createRequire(path.join(ui, 'package.json'));
const ts = nativeRequire('typescript');
const THREE = nativeRequire('three');
const graph = JSON.parse(fs.readFileSync(0, 'utf8'));
const cache = new Map();
let stateIndex = 0;
let sceneProps;
const sceneMarker = () => {};
const react = {
  useEffect() {},
  useMemo: fn => fn(),
  useRef: value => ({current:value}),
  useState: initial => [stateIndex++ === 0 ? graph :
    typeof initial === 'function' ? initial() : initial, () => {}],
};
function load(filename) {
  if (cache.has(filename)) return cache.get(filename).exports;
  const mod = {exports:{}};
  cache.set(filename, mod);
  const localRequire = id => {
    if (id === 'react') return react;
    if (id === 'react/jsx-runtime') return {
      jsx: (type, props) => { if (type === sceneMarker) sceneProps = props; return {type,props}; },
      jsxs: (type, props) => ({type,props}),
    };
    if (id.endsWith('/knowledge-3d-scene')) return {Knowledge3dScene:sceneMarker};
    if (id === '@/lib/api') return {};
    if (id === '@/lib/graph-tuning') return {
      MAIN_GRAPH_ID:'main',
      loadGraphTuning: () => load(path.join(ui,
        'src/renderer/src/components/themes/obsidience/knowledge-3d.ts')).DEFAULT_KNOWLEDGE_3D_TUNING,
    };
    if (!id.startsWith('.') && !id.startsWith('@/')) return nativeRequire(id);
    const base = id.startsWith('@/') ? path.join(ui,'src/renderer/src',id.slice(2))
      : path.resolve(path.dirname(filename),id);
    const target = [base,base+'.ts',base+'.tsx'].find(candidate => fs.existsSync(candidate)
      && fs.statSync(candidate).isFile());
    if (!target) throw new Error('Cannot resolve '+id+' from '+filename);
    return load(target);
  };
  const source = ts.transpileModule(fs.readFileSync(filename,'utf8'), {compilerOptions:{
    module:ts.ModuleKind.CommonJS, target:ts.ScriptTarget.ES2022, jsx:ts.JsxEmit.ReactJSX,
    esModuleInterop:true,
  }}).outputText;
  vm.runInThisContext('(function(require,module,exports){'+source+'\n})', {filename})(
    localRequire,mod,mod.exports);
  return mod.exports;
}
global.window = {innerWidth:1920,innerHeight:1200};
load(path.join(ui,'src/renderer/src/panes/graph-backdrop.tsx')).GraphBackdrop();
const {createKnowledge3dCloud} = load(path.join(ui,
  'src/renderer/src/components/themes/obsidience/knowledge-3d-cloud.ts'));
const {KNOWLEDGE_CROSS_SEGMENTS} = load(path.join(ui,
  'src/renderer/src/components/themes/obsidience/knowledge-3d-links.ts'));
const deps = {
  pointVertexShader:'point', pointFragmentShader:'point', pointDepthFragmentShader:'depth',
  beamVertexShader:'beam', taxonomyFragmentShader:'taxonomy', crossFragmentShader:'cross',
  particleVertexShader:'particle', particleFragmentShader:'particle', particleTime:{value:0},
  parseColor: () => ({r:1,g:1,b:1,a:1}),
  sharedUniforms:{uPerspective:{value:1},uPulse:{value:0},uTime:{value:0}},
  viewportUniform:{value:new THREE.Vector2(1920,1200)},
};
const inputs = [{agentId:'main', main:true, nodes:sceneProps.nodes, edges:sceneProps.edges,
  tuning:sceneProps.tuning, hub:sceneProps.hub}, ...sceneProps.satellites];
const output = {};
for (const input of inputs) {
  const cloud = createKnowledge3dCloud(input,deps,1200,1);
  const mesh = cloud.group.children.find(child => child.material?.fragmentShader === 'cross');
  const starts = mesh.geometry.getAttribute('aStart');
  const ends = mesh.geometry.getAttribute('aEnd');
  const simulation = cloud.captureSimNodes();
  const crossEdges = input.edges.filter(edge => !edge.taxonomy
    && simulation.has(edge.source) && simulation.has(edge.target));
  const segments = starts.count / (crossEdges.length * 4);
  const rendered = crossEdges.map((edge,index) => {
    for (const [id,attribute,vertex] of [[edge.source,starts,index*segments*4],
      [edge.target,ends,(index*segments+segments-1)*4]]) {
      const node = simulation.get(id);
      const actual = [attribute.getX(vertex),attribute.getY(vertex),attribute.getZ(vertex)];
      if (![node.x,node.y,node.z].every((value,axis) => Math.abs(value-actual[axis]) < 0.0001))
        throw new Error('Geometry endpoint mismatch: '+JSON.stringify({edge,id,actual,node}));
    }
    return {source:edge.source,target:edge.target};
  });
  output[input.agentId] = {nodes:input.nodes.map(node=>node.id), links:rendered,
    taxonomy:input.edges.filter(edge=>edge.taxonomy).map(({source,target})=>({source,target})),
    geometry_vertices:starts.count, segments_per_link:KNOWLEDGE_CROSS_SEGMENTS};
  cloud.dispose(new THREE.Scene());
}
process.stdout.write(JSON.stringify(output));
"""


def render_graph(document):
    result = subprocess.run(
        ["node", "-e", RENDER_PROBE], input=json.dumps(document),
        cwd=Path(__file__).parents[2], capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_cloud_membership_uses_only_exact_api_refs_and_display_aliases():
    module = Path(__file__).parents[1] / "ui/src/renderer/src/panes/graph-links.ts"
    result = subprocess.run([
        "node", "--experimental-strip-types", "--input-type=module", "-e", f"""
import {{strict as assert}} from 'node:assert';
import {{graphArticleIds}} from {json.dumps(module.as_uri())};
const aliases = new Map([['Skills/vault.read','@library/Skills/vault/read']]);
assert.deepEqual([...graphArticleIds({{article_refs:[
  'Skills/vault.read','@library/Skills/vault/read','Tools/vault.read','Other/vault.read',
]}},aliases)], ['@library/Skills/vault/read','Tools/vault.read','Other/vault.read']);
assert.equal(graphArticleIds(undefined,aliases).size,0);
assert.equal(graphArticleIds({{}},aliases).size,0);
"""], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_actual_geometry_retains_parent_and_absorbed_article_relationships():
    """The API has already selected scope; rendering must not discard its Articles."""
    executive = "Agents/Executive/Executive"
    darwin = "Agents/Darwin/Darwin"
    skill = "Skills/vault.read"
    mirror = "@library/Skills/vault/read"
    tool = "Tools/vault.read"
    runbook = "Runbooks/research"
    task = "Tasks/research"
    hub = "World/World"
    child_hub = "World/Topic/Topic"
    observations = "Agents/Darwin/Observations/Temporary Observations/Temporary Observations"

    def node(ref, kind="knowledge", **meta):
        return {"id": ref, "title": ref.rsplit("/", 1)[-1], "kind": kind, **meta}

    shared = [node(tool, "tool"), node(skill, "skill"),
              node(mirror, "skill", synthetic=True, article_ref=skill),
              node(runbook, "runbook", children=[runbook + "/question"]),
              node(runbook + "/question", "runbook"),
              node(task, "task", children=[task + "/question"]),
              node(task + "/question", "task")]
    main_subjects = [{"id": "@branch/" + name, "title": name}
                     for name in ("Tools", "Skills", "Runbooks", "Tasks")]
    main_subjects += [
        {"id": "@branch/World", "title": "World", "path": "World", "article_ref": hub},
        {"id": "@branch/World/Topic", "title": "Topic", "path": "World/Topic",
         "article_ref": child_hub, "parent_id": "@branch/World"},
        {"id": "@agent/Subagents", "title": "Other Agents"},
    ]
    darwin_subjects = [{"id": "@agent/Darwin/" + name.lower(), "title": name}
                       for name in ("Tools", "Skills", "Runbooks", "Tasks", "Observations")]
    darwin_subjects += [{"id": "@agent/Darwin/temporary-observations", "title": "Temporary",
                        "article_ref": observations, "parent_id": "@agent/Darwin/observations"},
                       {"id": "@agent/Darwin/other-agents", "title": "Other Agents"}]
    library_subjects = [{"id": "@library/" + name, "title": name} for name in ("Tools", "Tasks")]

    def group(identifier, root, subjects, refs):
        return {"id": identifier, "root_ref": root, "title": identifier, "subjects": subjects,
                "article_refs": [root, *refs, *(s["id"] for s in subjects)]}

    shared_refs = [n["id"] for n in shared]
    graph = {
        "nodes": [node(executive, "agent"), node(darwin, "agent"), *shared,
                  node(hub, navigation_ref="@branch/World"),
                  node(child_hub, navigation_ref="@branch/World/Topic"),
                  # Specialists publish the physical ref on the navigation subject,
                  # not a navigation_ref on the underlying Article DTO.
                  node(observations)],
        "links": [
            {"source": skill, "target": tool},
            {"source": runbook, "target": skill},
            {"source": runbook, "target": tool, "derived": True, "via": [skill]},
            {"source": task, "target": tool, "derived": True, "via": [runbook, skill]},
            {"source": runbook, "target": runbook + "/question"},
            {"source": runbook + "/question", "target": runbook},
            {"source": task, "target": task + "/question"},
            {"source": task + "/question", "target": task},
            {"source": hub, "target": tool},
            {"source": hub, "target": child_hub},
            {"source": child_hub, "target": hub},
            {"source": observations, "target": tool},
        ],
        "auto_curated": [], "auto_curate_resolved": True,
        "navigation": {"groups": [
            group("executive", executive, main_subjects, [*shared_refs, hub, child_hub]),
            group("researcher", darwin, darwin_subjects, [*shared_refs, observations]),
            group("library", "@library", library_subjects, shared_refs),
        ]},
    }
    before = json.dumps(graph, sort_keys=True)
    rendered = render_graph(graph)
    assert json.dumps(graph, sort_keys=True) == before
    for name in ("main", "Darwin"):
        links = rendered[name]["links"]
        assert {"source": runbook, "target": mirror} in links
        assert {"source": runbook, "target": tool} in links
        assert {"source": task, "target": tool} in links
    assert {"source": "@branch/World", "target": tool} in rendered["main"]["links"]
    assert {"source": "@agent/Darwin/temporary-observations", "target": tool} in rendered["Darwin"]["links"]
    assert observations not in rendered["Darwin"]["nodes"]
    assert hub not in rendered["main"]["nodes"]
    assert {"source": task, "target": tool} in rendered["library"]["links"]
    assert mirror not in rendered["library"]["nodes"]  # Existing Tool+Skill pair display.
    for cloud in rendered.values():
        assert len(cloud["nodes"]) == len(set(cloud["nodes"]))
        pairs = [tuple(sorted(edge.values())) for edge in cloud["links"] + cloud["taxonomy"]]
        assert len(pairs) == len(set(pairs))
        assert all(edge["source"] != edge["target"] for edge in cloud["links"])
        assert cloud["geometry_vertices"] == len(cloud["links"]) * cloud["segments_per_link"] * 4
    # Removing a real relationship retracts its beam without changing membership.
    graph["links"] = [link for link in graph["links"]
                      if (link["source"], link["target"]) != (observations, tool)]
    assert {"source": "@agent/Darwin/temporary-observations", "target": tool} not in render_graph(graph)["Darwin"]["links"]


def test_actual_executive_geometry_keeps_local_bindings_and_excludes_foreign_variants(
    tmp_path, monkeypatch, isolated_task_ledger,
):
    monkeypatch.setattr(CONFIG, "vault_dir", tmp_path / "vault")
    from obsidience.harness.capabilities.registry import binding, source

    def article(ref, kind, body="Article.", **meta):
        write_note(ref + ".md", {"kind": kind, "title": ref.rsplit("/", 1)[-1], **meta}, body)

    for tool in ("vault.propose", "computer.observe", "task.create", "task.complete"):
        article("Tools/" + tool, "tool", binding=binding(tool), source=source(tool))
        article("Skills/" + tool, "skill", tool="[[Tools/" + tool + "]]")
    article("Runbooks/observations/executive", "runbook", skills=["[[Skills/vault.propose]]"],
            for_agent="[[Agents/Executive/Executive]]")
    article("Runbooks/operate", "runbook",
            skills=["[[Skills/computer.observe]]", "[[Skills/task.create]]"])
    article("Runbooks/answer-the-user", "runbook", skills=["[[Skills/task.create]]"])
    article("Agents/Executive/Architecture/scene", "knowledge",
            body="Read [the observation Tool](/Tools/computer.observe.md).")
    article("Tasks/operate", "task", runbook="[[Runbooks/operate]]",
            assignee="[[Agents/Executive/Executive]]")
    article("Tasks/query", "task", assignee="[[Agents/Executive/Executive]]",
            runbook="[[Runbooks/answer-the-user]]")
    article("Tasks/observe", "task", assignee="[[Agents/Executive/Executive]]",
            runbook="[[Runbooks/observations/executive]]")
    # Both Task and Tool are Executive members, but this applicable variant
    # belongs only to Darwin. Endpoints alone are not enough.
    article("Runbooks/Generated/researcher/query", "runbook", task="[[Tasks/query]]",
            for_agent="[[Agents/Darwin/Darwin]]", skills=["[[Skills/vault.propose]]"])
    # An unscoped, unselected route cannot acquire authority from its endpoints.
    article("Runbooks/foreign-route", "runbook", task="[[Tasks/query]]",
            skills=["[[Skills/vault.propose]]"])
    article("Agents/Executive/Executive", "agent",
            tasks=["Tasks/query", "Tasks/operate", "Tasks/observe"])
    article("Agents/Darwin/Darwin", "agent", tasks=["Tasks/query"])
    article("Agents/Darwin/private", "knowledge",
            body="Use [the proposal Tool](/Tools/vault.propose.md).")
    isolated_task_ledger.sync(embed=False)
    api = importlib.import_module("obsidience.harness.interfaces.api.app")
    rendered = render_graph(api.graph())
    main = rendered["main"]

    def neighbors(cloud, ref):
        return {edge["target"] if edge["source"] == ref else edge["source"]
                for edge in cloud["links"] if ref in (edge["source"], edge["target"])}

    assert neighbors(main, "Tools/vault.propose") == {
        "@library/Skills/vault/propose", "Runbooks/observations/executive", "Tasks/observe",
    }
    assert neighbors(main, "Tools/computer.observe") == {
        "@library/Skills/computer/observe", "Runbooks/operate", "Tasks/operate",
        "Agents/Executive/Architecture/scene",
    }
    assert neighbors(main, "Tools/task.create") == {
        "@library/Skills/task/create", "Runbooks/operate", "Runbooks/answer-the-user",
        "Tasks/operate", "Tasks/query",
    }
    assert neighbors(rendered["Darwin"], "Tools/vault.propose") == {
        "@library/Skills/vault/propose", "Runbooks/Generated/researcher/query", "Tasks/query",
        "Agents/Darwin/private",
    }
    # Other-Agent Brains are navigation peers, not admission of their Knowledge.
    assert "Agents/Darwin/Darwin" in main["nodes"]
    assert "Agents/Executive/Executive" in rendered["Darwin"]["nodes"]
    assert "Agents/Darwin/private" not in main["nodes"]
    assert "Agents/Darwin/private" in rendered["Darwin"]["nodes"]
    assert not neighbors(main, "Agents/Darwin/Darwin")
    # Library intentionally has no Runbooks and keeps the global relationship.
    assert "Tasks/query" in neighbors(rendered["library"], "Tools/vault.propose")
    assert main["geometry_vertices"] == len(main["links"]) * main["segments_per_link"] * 4
    # A removed authored requirement retracts the actual beam, not just its DTO.
    article("Runbooks/operate", "runbook", skills=["[[Skills/task.create]]"])
    isolated_task_ledger.sync(embed=False)
    refreshed = render_graph(api.graph())["main"]
    assert neighbors(refreshed, "Tools/computer.observe") == set()
    assert "Tools/computer.observe" not in refreshed["nodes"]
    assert "Agents/Executive/Architecture/scene" in refreshed["nodes"]
