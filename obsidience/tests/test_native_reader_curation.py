"""Native Reader request lifecycle without a window, socket, or real API write."""
import json
import re
import subprocess
from pathlib import Path


def test_native_reader_permission_refresh_and_stale_selection_guard():
    reader = Path(__file__).parents[1] / "shell/qml/panes/reader/ReaderPane.qml"
    source = reader.read_text()
    functions = "\n".join(
        re.search(rf"^    function {name}\([^\n]*\) \{{.*?^    \}}", source, re.M | re.S)[0]
        for name in ("resetDocument", "loadDocument", "setAutoCurate")
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", f"""
import {{ strict as assert }} from 'node:assert';
import vm from 'node:vm';
const requests = [];
class Request {{
  static DONE = 4;
  open(method, url) {{ this.method = method; this.url = url; }}
  setRequestHeader() {{}}
  send(body) {{ this.body = body; requests.push(this); }}
  respond(status, data) {{
    this.status = status; this.responseText = JSON.stringify(data);
    this.readyState = Request.DONE; this.onreadystatechange();
  }}
}}
const state = {{XMLHttpRequest:Request, feedItemMode:false, feedItemId:'', sourceMode:false, sourceKey:'',
  previewMode:false, previewItem:{{}}, selectionKind:'article',
  articleRef:'@sat/Alexandria/observations', requestGeneration:0,
  loadArticleTitles() {{}}}};
state.root = state;
vm.createContext(state);
vm.runInContext({json.dumps(functions)}, state);
const document = {{title:'Observations', kind:'knowledge', body:'Summary',
  auto_curate_supported:true, auto_curate:true}};
state.loadDocument();
requests.at(-1).respond(200, document);
assert.equal(state.autoCurateSupported, true);
assert.equal(state.autoCurateEnabled, true);
state.setAutoCurate(false);
const put = requests.at(-1);
assert.equal(put.method, 'PUT');
assert.equal(put.url, 'http://127.0.0.1:8765/api/articles/@sat/Alexandria/observations/auto-curate');
assert.equal(put.body, '{{"enabled":false}}');
assert.equal(state.curationBusy, true);
state.setAutoCurate(false);
assert.equal(requests.at(-1), put); // No duplicate request while busy.
put.respond(200, {{enabled:false}});
assert.equal(requests.at(-1).method, 'GET'); // Read effective canonical state.
requests.at(-1).respond(200, {{...document, auto_curate:false}});
assert.equal(state.autoCurateEnabled, false);
assert.equal(state.curationBusy, false);
state.setAutoCurate(true);
const rejected = requests.at(-1);
rejected.respond(409, {{detail:'Permission unavailable'}});
assert.equal(state.autoCurateEnabled, false); // No optimistic permission.
assert.match(state.errorMessage, /Permission unavailable/);
state.setAutoCurate(true);
const stale = requests.at(-1);
state.articleRef = 'Tools/vault.read';
state.loadDocument();
requests.at(-1).respond(200, {{title:'vault.read', kind:'tool', body:'Tool',
  auto_curate_supported:false, auto_curate:false}});
const count = requests.length;
stale.respond(200, {{enabled:true}});
assert.equal(requests.length, count); // No refresh of a different selection.
assert.equal(state.articleTitle, 'vault.read');
assert.equal(state.autoCurateSupported, false);
assert.equal(state.autoCurateEnabled, false);
assert.equal(state.noticeMessage, '');
state.setAutoCurate(true);
assert.equal(requests.length, count); // Unsupported Articles cannot submit.
"""],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert "checked: root.autoCurateEnabled" in source
    assert "onClicked: root.setAutoCurate(!root.autoCurateEnabled)" in source
    assert "visible: !root.sourceMode && !root.articleReadOnly && root.autoCurateSupported && !root.editing" in source
