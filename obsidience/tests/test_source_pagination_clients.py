"""The existing Source consumers assemble pages before replacing a listing."""
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


def api_check(script):
    node_check(
        "import {strict as assert} from 'node:assert';\n"
        f"import {{api}} from {json.dumps((ROOT / 'ui/src/renderer/src/lib/api.ts').as_uri())};\n"
        + FIXTURES + script
    )


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


def test_api_follows_exact_cursors_deduplicates_and_retains_case_distinctions():
    api_check(r"""
const cursor='obsidience/Source folder/Stage.qml';
const calls=[];
const pages=[page([file(cursor)],cursor,[issue]),
 page([file(cursor,2),file('obsidience/Source folder/stage.qml')],null,[issue])];
globalThis.fetch=async(url,options)=>{calls.push([url,options]);return {ok:true,json:async()=>pages.shift()};};
const result=await api.sourceFiles();
assert.deepEqual(result.files.map(f=>[f.key,f.size]),[[cursor,2],['obsidience/Source folder/stage.qml',1]]);
assert.deepEqual(result.issues,[issue]);
assert.equal(calls.length,2);
assert(calls[1][0].endsWith('?after='+encodeURIComponent(cursor)));
assert(calls.every(c=>c[1].cache==='no-store'));
// The existing consumer DTO is still a complete assembled files/issues pair.
assert.deepEqual(Object.keys(result),['files','issues']);
""")


def test_api_failure_on_later_page_never_resolves_partial_listing():
    api_check(r"""
let calls=0;
globalThis.fetch=async()=>++calls===1?{ok:true,json:async()=>page([file('obsidience/a')],'obsidience/a')}
 :{ok:false,status:503,text:async()=>JSON.stringify({detail:'Source refresh failed'})};
await assert.rejects(api.sourceFiles(),/Source refresh failed/);
assert.equal(calls,2);
""")


@pytest.mark.parametrize("mutation", [
    "reply.coverage.returned=2",
    "reply.coverage.limit=0",
    "reply.coverage.consistency='snapshot'",
    "reply.coverage.scope='obsidience/another'",
    "reply.coverage.next_cursor='obsidience/not-last'",
    "reply.coverage.complete='yes'",
    "delete reply.coverage",
])
def test_api_rejects_inconsistent_continuation_metadata(mutation):
    api_check(r"""
const reply=page([file('obsidience/b')],'obsidience/b');
""" + mutation + r""";
let calls=0;
globalThis.fetch=async()=>({ok:true,json:async()=>++calls===1
 ?page([file('obsidience/a')],'obsidience/a'):reply});
await assert.rejects(api.sourceFiles(),/Source hierarchy/);
assert.equal(calls,2);
""")


def test_api_rejects_cyclic_cursors_and_preserves_legacy_single_response():
    api_check(r"""
let calls=0;
globalThis.fetch=async()=>({ok:true,json:async()=>{
 const key=++calls%2?'obsidience/b':'obsidience/a';return page([file(key)],key);
}});
await assert.rejects(api.sourceFiles(),/did not advance/);
assert.equal(calls,3);
globalThis.fetch=async()=>({ok:true,json:async()=>({files:[file('obsidience/legacy')],issues:[]})});
assert.deepEqual((await api.sourceFiles()).files.map(f=>f.key),['obsidience/legacy']);
""")


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
