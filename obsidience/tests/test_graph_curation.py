"""Exercise the graph's pure TypeScript projection with installed Node, no UI."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest


def test_canonical_markers_project_only_backend_resolved_permissions():
    helper = Path(__file__).parents[1] / "ui/src/renderer/src/panes/graph-curation.ts"
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", f"""
import {{ strict as assert }} from 'node:assert';
import {{ projectedAutoCuratedRefs }} from {json.dumps(helper.as_uri())};
const branch = '@branch/News & Research';
const article = 'News & Research/index';
const executive = 'Agents/Executive/Executive';
const world = branch+'/World';
const leaf = 'News & Research/World/Story';
const subjects = [
  {{id:branch, article_ref:article}},
  {{id:world, article_ref:'News & Research/World/index'}},
  {{id:'@vault', article_ref:executive}},
];
// The backend has resolved inheritance for this exact parent/subnode/leaf set.
const selected = projectedAutoCuratedRefs(
  [executive, article, 'News & Research/World/index', leaf], [], subjects);
for (const id of ['@vault', branch, world, leaf]) assert(selected.has(id));
// Physical index selections still mark their absorbed navigation node.
assert(projectedAutoCuratedRefs([article],
  [{{id:article, navigation_ref:branch}}], []).has(branch));
// Owner override can refer to a physical index absent from graph.nodes.
assert(projectedAutoCuratedRefs([article], [], subjects).has(branch));
// Existing direct navigation selections keep working.
assert.deepEqual([...projectedAutoCuratedRefs([branch], [], [])], [branch]);
// A similarly named Article never marks a different branch by title/path guess.
assert(!projectedAutoCuratedRefs(['Other/index'], [], subjects).has(branch));
// Do not restore a child the backend omitted because of explicit false.
assert(!projectedAutoCuratedRefs([executive, article], [], subjects).has(world));
assert(!projectedAutoCuratedRefs([executive, article], [], subjects).has(leaf));
// Brain permission cannot spill into shared executable capability checkouts.
for (const id of ['Tools/vault.read', 'Skills/vault.read', 'Tasks/ingest',
                 'Runbooks/ingest-sources', '@branch/Tools', '@library',
                 '@branch/Projects', 'Projects/News & Research']) {{
  assert(!selected.has(id), id);
}}
assert.deepEqual([...projectedAutoCuratedRefs([leaf], [], subjects)], [leaf]);
assert.deepEqual([...projectedAutoCuratedRefs([], [], subjects)], []);
"""],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr


def test_shared_node_ring_shader_compiles():
    validator = shutil.which("glslangValidator")
    if not validator:
        pytest.skip("GLSL validator is not installed")
    scene = Path(__file__).parents[1] / (
        "ui/src/renderer/src/components/themes/obsidience/knowledge-3d-scene.tsx"
    )
    shader = scene.read_text().split("const POINT_FRAGMENT_SHADER = `", 1)[1].split("`;", 1)[0]
    result = subprocess.run(
        [validator, "--stdin", "-S", "frag"],
        input="precision highp float;\n" + shader,
        text=True, capture_output=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr
