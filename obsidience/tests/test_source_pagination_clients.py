"""The native Source pane assembles pages before replacing a listing."""
import json
from pathlib import Path
import re
import subprocess

import pytest


ROOT = Path(__file__).parents[1]


def node_check(script):
    result = subprocess.run(
        ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


FIXTURES = r"""
const file=(key,version=1)=>({key,path:key,name:key.split('/').at(-1),media_type:'text/plain',
 size:version,modified_at:version,storage:'code',read_only:true,articles:[]});
const issue={path:'obsidience/missing',status:'missing',detail:'Missing file'};
const page=(files,next=null,issues=[])=>({files,issues,coverage:{scope:null,limit:2000,
 returned:files.length,complete:next===null,next_cursor:next,consistency:'live'}});
"""


def native_check(script):
    source = (ROOT / "shell/qml/panes/source/SourcePane.qml").read_text()
    functions = "\n".join(
        re.search(rf"^    function {name}\([^\n]*\) \{{.*?^    \}}", source, re.M | re.S)[0]
        for name in ("refresh", "checkoutKey")
    )
    node_check(
        "import {strict as assert} from 'node:assert';\nimport vm from 'node:vm';\n"
        + FIXTURES + r"""
const requests=[];
class Request {
 static DONE=4;
 open(method,url){this.url=url;}
 send(){requests.push(this);}
 respond(payload,status=200){this.status=status;this.readyState=4;
  this.responseText=typeof payload==='string'?payload:JSON.stringify(payload);this.onreadystatechange();}
}
const previous=[file('obsidience/previous')];
const state={XMLHttpRequest:Request,requestGeneration:0,files:previous,issues:[issue],storage:null,
 checkouts:{},articleRefs:{},loading:false,errorMessage:'',rebuilds:0,rebuildRows(){this.rebuilds++;}};
state.root=state;
vm.createContext(state);
"""
        + f"vm.runInContext({json.dumps(functions)},state);\n"
        + r"""
const request=(path)=>requests.findLast(r=>r.url.endsWith(path));
const sourceRequests=()=>requests.filter(r=>r.url.includes('/api/source-files'));
const finishOther=()=>{
 request('/api/source-checkouts').respond({assignments:[]});request('/api/graph').respond({});};
const plain=value=>JSON.parse(JSON.stringify(value));
""" + script
    )


def test_native_commits_only_complete_page_assembly_and_exact_key_deduplication():
    native_check(r"""
state.refresh();finishOther();
const cursor='obsidience/Source folder/Stage.qml';
sourceRequests()[0].respond(page([file(cursor)],cursor,[issue]));
assert.equal(state.files,previous);assert.equal(state.loading,true);assert.equal(state.rebuilds,0);
assert(sourceRequests()[1].url.endsWith('?after='+encodeURIComponent(cursor)));
sourceRequests()[1].respond(page([file(cursor,2),file('obsidience/Source folder/stage.qml')],null,[issue]));
assert.deepEqual(plain(state.files).map(f=>[f.key,f.size]),[[cursor,2],['obsidience/Source folder/stage.qml',1]]);
assert.deepEqual(plain(state.issues),[issue]);assert.equal(state.loading,false);assert.equal(state.errorMessage,'');
assert.equal(state.rebuilds,1);
""")


@pytest.mark.parametrize("failure", [
    "continuation.respond('Source temporarily unavailable',503)",
    "continuation.respond('invalid JSON')",
    "continuation.respond(page([file('obsidience/a')],'obsidience/a'))",
    "continuation.respond(page([], 'obsidience/b'))",
    "const invalid=page([file('obsidience/b')]);invalid.coverage.returned=5;continuation.respond(invalid)",
    "continuation.respond({files:[file('obsidience/b')],issues:[]})",
])
def test_native_failed_page_preserves_prior_listing_and_shows_error(failure):
    native_check(r"""
state.refresh();
sourceRequests()[0].respond(page([file('obsidience/a')],'obsidience/a'));
const continuation=sourceRequests()[1];
""" + failure + r""";
finishOther();
assert.equal(state.files,previous);assert.equal(state.loading,false);
assert(state.errorMessage);assert.equal(state.rebuilds,0);
assert.equal(sourceRequests().length,2);
""")


def test_native_superseded_generation_stops_pagination_and_cannot_overwrite_new_listing():
    native_check(r"""
state.refresh();
const staleInitial=sourceRequests()[0];
state.refresh();
const currentInitial=sourceRequests()[1];
staleInitial.respond(page([file('obsidience/stale')],'obsidience/stale'));
assert.equal(sourceRequests().length,2);assert.equal(state.files,previous);
currentInitial.respond(page([file('obsidience/a')],'obsidience/a'));
const staleContinuation=sourceRequests()[2];
state.refresh();finishOther();
sourceRequests()[3].respond(page([file('obsidience/current')]));
assert.deepEqual(plain(state.files).map(f=>f.key),['obsidience/current']);
const before=state.rebuilds;
staleContinuation.respond(page([file('obsidience/late')],'obsidience/late'));
assert.equal(sourceRequests().length,4);assert.equal(state.rebuilds,before);
assert.deepEqual(plain(state.files).map(f=>f.key),['obsidience/current']);
assert.equal(state.loading,false);assert.equal(state.errorMessage,'');
""")
