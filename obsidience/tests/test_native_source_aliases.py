"""Source filters consume the same canonical Article identity as the Reader."""
import json
import re
import subprocess
from pathlib import Path


def test_source_navigation_aliases_match_exact_physical_files():
    source = (Path(__file__).parents[1] / "shell/qml/panes/source/SourcePane.qml").read_text()
    functions = "\n".join(
        re.search(rf"^    function {name}\([^\n]*\) \{{.*?^    \}}", source, re.M | re.S)[0]
        for name in ("refresh", "sourceMatchesArticle", "checkoutKey")
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", f"""
import {{ strict as assert }} from 'node:assert';
import vm from 'node:vm';
const requests = [];
class Request {{
  static DONE = 4;
  open(method, url) {{ this.url = url; }}
  send() {{ requests.push(this); }}
  respond(data) {{ this.status = 200; this.readyState = 4;
    this.responseText = JSON.stringify(data); this.onreadystatechange(); }}
}}
const state = {{XMLHttpRequest:Request, requestGeneration:0, articleRefs:{{}},
  rebuildRows() {{}}}};
state.root = state;
vm.createContext(state);
vm.runInContext({json.dumps(functions)}, state);
const ref = 'Agents/Darwin/Observations/index';
const graph = {{navigation:{{groups:[
  {{id:'researcher', root_ref:'Agents/Darwin/Darwin', subjects:[
    {{id:'@sat/Darwin/observations', article_ref:ref}}]}},
  {{id:'executive', root_ref:'Agents/Executive/Executive', subjects:[]}}
]}}}};
function respond(path, payload) {{
  requests.findLast(request => request.url.endsWith(path)).respond(payload);
}}
function completeRefresh() {{
  respond('/api/source-files', {{files:[], issues:[]}});
  respond('/api/source-checkouts', {{assignments:[]}});
}}
state.refresh();
completeRefresh();
assert.equal(state.loading, false); // The real filesystem does not wait for aliases.
respond('/api/graph', graph);
assert.equal(state.loading, false);
const file = {{storage:'knowledge', articles:[ref]}};
assert(state.sourceMatchesArticle(file, '@sat/Darwin/observations'));
assert(state.sourceMatchesArticle(file, ref));
assert(!state.sourceMatchesArticle(file, '@sat/Heimdall/observations'));
assert(state.sourceMatchesArticle({{articles:['Agents/Executive/Executive']}}, '@vault'));
// Keep the existing subtree and System-scope matching behavior.
assert(state.sourceMatchesArticle({{articles:['Games/TFT/Guide']}}, '@branch/Games'));
assert(state.sourceMatchesArticle({{articles:[], storage:'system'}}, '@branch/ADMECH Workstation'));
assert(!state.sourceMatchesArticle({{articles:['Games/TFT/Guide']}}, '@branch/Personal'));
state.refresh();
const stale = requests.at(-1);
state.refresh();
completeRefresh();
respond('/api/graph', {{navigation:{{groups:[]}}}});
stale.respond(graph);
assert(!state.sourceMatchesArticle(file, '@sat/Darwin/observations'));
assert(state.sourceMatchesArticle(file, ref));
for (const reply of [{{}}, null]) {{
  state.refresh();
  completeRefresh();
  respond('/api/graph', reply);
  assert.equal(state.loading, false);
  assert.equal(state.errorMessage, '');
  assert(state.sourceMatchesArticle(file, ref));
}}
for (const [status, body] of [[503, 'unavailable'], [200, 'invalid JSON']]) {{
  state.refresh();
  completeRefresh();
  const request = requests.at(-1);
  request.status = status;
  request.readyState = Request.DONE;
  request.responseText = body;
  request.onreadystatechange();
  assert.equal(state.loading, false);
  assert.equal(state.errorMessage, '');
  assert(state.sourceMatchesArticle(file, ref));
}}
"""],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
