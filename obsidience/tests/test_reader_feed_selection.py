"""Shared Reader Feed selections retain evidence and reject late responses."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess


SHELL = Path(__file__).parents[1] / "shell/qml"
READER = SHELL / "panes/reader/ReaderPane.qml"
SERVER = SHELL / "api/ShellCommandServer.qml"


def run_functions(path: Path, body: str, *, reader: bool = True) -> None:
    functions = "\n".join(re.findall(
        r"^    function \w+\([^\n]*\) \{.*?^    \}", path.read_text(), re.M | re.S))
    fixture = r"""
import {strict as assert} from 'node:assert';
import vm from 'node:vm';
const requests = [], later = new Set();
class Request {
    static DONE = 4;
    open(method, url) { this.method = method; this.url = url; }
    setRequestHeader() {}
    send(body) { this.body = body; requests.push(this); }
    respond(status, body) {
        this.status = status; this.responseText = JSON.stringify(body);
        this.readyState = 4; this.onreadystatechange();
    }
}
const sourceA = '11111111-1111-4111-8111-111111111111';
const sourceB = '22222222-2222-4222-8222-222222222222';
const sourcePath = id => 'obsidience/evidence/raw/' + id + '.md';
const sourceSelection = id => ({kind:'source', key:sourcePath(id), feed_item_id:id});
const captured = id => ({source_id:id, source_path:sourcePath(id), title:'Captured provider title',
    content_text:'Complete provider text', feed_name:'World', published:'2026-09-09T18:00:00Z',
    reporting_url:'https://publisher.example/story'});
const preview = title => ({kind:'feed_preview', item:{title,
    summary:'Uncollected <img src="https://tracker.example/pixel"> publisher text',
    reporting_url:'https://publisher.example/story', published:'2026-09-09T18:00:00Z',
    feed_title:'World news', feed_url:'https://publisher.example/rss'}});
const state = {XMLHttpRequest:Request, Qt:{callLater:fn=>later.add(fn)},
    followShellSelection:true, selectionKind:'article', articleRef:'', sourceKey:'', feedItemId:'',
    previewItem:null, graphId:'', requestGeneration:0, loading:false, saving:false,
    editing:false, curationBusy:false, draftTitle:'', draftBody:'', feedProvenance:{},
    documentPath:'', sourceStorage:'', articleTitle:'', articleBody:'', errorMessage:'', noticeMessage:''};
state.root = state;
function flush() {
    for (let remaining = 10; later.size; --remaining) {
        assert(remaining > 0, 'callLater did not settle');
        const batch = [...later]; later.clear();
        for (const fn of batch) fn.call(state);
    }
}
function select(selection) {
    state.applyShellEvent(JSON.stringify({schema:'obsidience.shell.event.v1',
        type:'pane.state',pane:{pane_id:'reader'}, selection}));
}
vm.createContext(state);
"""
    if reader:
        fixture += r"""
Object.defineProperties(state, {
    previewMode:{get(){return this.selectionKind === 'feed_preview';}},
    sourceMode:{get(){return this.selectionKind === 'source' || this.previewMode;}},
    feedItemMode:{get(){return this.selectionKind === 'source' && this.feedItemId.length > 0;}}
});
"""
    script = fixture + f"\nvm.runInContext({json.dumps(functions)}, state);\n" + body
    result = subprocess.run(["node", "--input-type=module", "-e", script],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


def test_shared_reader_attests_captured_source_id_and_path():
    run_functions(READER, r"""
select(sourceSelection(sourceA)); flush();
assert.equal(state.selectionKind,'source');
assert.equal(state.feedItemId,sourceA);
assert.equal(state.sourceKey,sourcePath(sourceA));
assert.equal(requests.length,1);
assert.equal(requests[0].url,'http://127.0.0.1:8765/api/feeds/items/' + sourceA);
requests[0].respond(200,{...captured(sourceA),source_path:sourcePath(sourceB)});
assert.equal(state.articleBody,'');
assert.equal(state.documentPath,'');
assert.equal(state.errorMessage,'Document response was invalid.');
select(sourceSelection(sourceB)); flush();
requests.at(-1).respond(200,{...captured(sourceB),source_id:sourceA});
assert.equal(state.articleBody,'');
assert.equal(state.errorMessage,'Document response was invalid.');
select(sourceSelection(sourceA)); flush();
requests.at(-1).respond(200,captured(sourceA));
assert.equal(state.articleBody,'Complete provider text');
assert.equal(state.documentPath,sourcePath(sourceA));
assert.equal(state.feedProvenance.source_id,sourceA);
assert.equal(state.articleRef,'');
assert.equal(state.autoCurateSupported,false);
assert(requests.every(request=>request.method === 'GET' && request.url.includes('/api/feeds/items/')));
""")


def test_uncollected_preview_never_fetches_or_edits_an_article():
    run_functions(READER, r"""
select(preview('First live title')); flush();
assert.equal(state.previewMode,true);
assert.equal(state.sourceMode,true);
assert.equal(state.articleTitle,'First live title');
assert.equal(state.articleBody,preview('').item.summary);
assert.equal(state.feedItemId,'');
assert.equal(state.sourceKey,'');
assert.equal(state.articleRef,'');
assert.equal(state.documentPath,'');
assert.equal(state.autoCurateSupported,false);
assert.equal(state.editing,false);
state.startEdit(); state.saveArticle(); state.setAutoCurate(true);
assert.equal(state.editing,false);
assert.equal(requests.length,0);
const generation=state.requestGeneration;
select(preview('Second live title')); flush();
assert(state.requestGeneration > generation);
assert.equal(state.articleTitle,'Second live title');
assert.equal(requests.length,0);
""")


def test_preview_uses_visible_plain_prose_and_hides_source_code_panel():
    source = READER.read_text()
    prose = re.search(r"id: articleText\n(.*?)onLinkActivated:", source, re.S)[1]
    prose_visible = re.search(r"visible: ([^\n]*!root.sourceMode[^\n]*root.articleTitle[^\n]*)", source)[1]
    code_visible = re.search(r"visible: (root.sourceMode && [^\n]*root.articleTitle[^\n]*)", source)[1]
    format_expression = re.search(r"textFormat: ([^\n]*)", prose)[1]
    text_expression = re.search(r"\n\s+text: ([^\n]*)", prose)[1]
    run_functions(READER, r"""
state.Text={PlainText:'plain',MarkdownText:'markdown'};
select(preview('Plain <b>title</b>')); flush();
""" + f"""
assert.equal(vm.runInContext({json.dumps(prose_visible)},state),true);
assert.equal(vm.runInContext({json.dumps(code_visible)},state),false);
assert.equal(vm.runInContext({json.dumps(format_expression)},state),'plain');
assert.equal(vm.runInContext({json.dumps(text_expression)},state),preview('').item.summary);
""")


def test_new_preview_invalidates_pending_source_before_queued_load():
    run_functions(READER, r"""
select(sourceSelection(sourceA)); flush();
const pending=requests.at(-1), generation=state.requestGeneration;
select(preview('Latest preview'));
assert(state.requestGeneration > generation);
pending.respond(200,captured(sourceA));
assert.notEqual(state.articleTitle,'Captured provider title');
flush();
assert.equal(state.articleTitle,'Latest preview');
assert.equal(state.documentPath,'');
assert.equal(state.feedItemId,'');
assert.equal(state.feedProvenance.source_id,undefined);
assert.equal(requests.length,1);
""")


def test_leaving_feed_selection_clears_provenance_and_fetches_normal_source():
    run_functions(READER, r"""
select(sourceSelection(sourceA)); flush(); requests.at(-1).respond(200,captured(sourceA));
select({kind:'source',key:'obsidience/ordinary.txt'}); flush();
assert.equal(state.feedItemId,'');
assert.equal(state.previewMode,false);
assert.equal(state.feedProvenance.source_id,undefined);
const ordinary=requests.findLast(request=>request.url.endsWith('/api/source-files/obsidience/ordinary.txt'));
assert(ordinary);
ordinary.respond(200,{name:'ordinary.txt',path:'obsidience/ordinary.txt',storage:'code',
    content:'Ordinary source text',media_type:'text/plain',size:20});
assert.equal(state.articleBody,'Ordinary source text');
assert.equal(state.documentPath,'obsidience/ordinary.txt');
select(preview('Preview before article')); flush();
select({kind:'article',ref:'Knowledge/World/World',graph_id:'main'}); flush();
const article=requests.findLast(request=>request.url.endsWith('/api/articles/Knowledge/World/World'));
assert(article);
article.respond(200,{title:'World',body:'Accepted article',kind:'knowledge',ref:'Knowledge/World/World',
    auto_curate_supported:true,auto_curate:true});
assert.equal(state.sourceMode,false);
assert.equal(state.articleTitle,'World');
assert.equal(state.articleBody,'Accepted article');
assert.equal(state.feedItemId,'');
assert.equal(state.sourceKey,'');
assert.equal(state.feedProvenance.source_id,undefined);
assert(!state.previewItem || Object.keys(state.previewItem).length === 0);
""")


def test_late_article_save_cannot_replace_new_preview_or_its_notice():
    run_functions(READER, r"""
select({kind:'article',ref:'Knowledge/World/World'}); flush();
requests.at(-1).respond(200,{title:'World',body:'Before',kind:'knowledge',ref:'Knowledge/World/World'});
state.startEdit(); state.draftTitle='Edited World'; state.draftBody='Saved old Article'; state.saveArticle();
const save=requests.at(-1);
assert.equal(save.method,'PATCH');
assert.equal(save.url,'http://127.0.0.1:8765/api/articles/Knowledge/World/World');
assert.deepEqual(JSON.parse(save.body),{title:'Edited World',body:'Saved old Article'});
select(preview('Keep this preview')); flush();
save.respond(200,{ok:true});
assert.equal(state.articleTitle,'Keep this preview');
assert.equal(state.articleBody,preview('').item.summary);
assert.equal(state.noticeMessage,'');
assert.equal(state.editing,false);
assert.equal(state.saving,false);
save.respond(409,{detail:'An old conflict'});
assert.equal(state.errorMessage,'');
""")


def test_reconnect_selection_replay_preserves_article_edit_and_pending_save():
    run_functions(READER, r"""
const selection={kind:'article',ref:'Knowledge/World/World',graph_id:'main'};
select(selection); flush();
requests.findLast(request=>request.url.includes('/api/articles/')).respond(200,
    {title:'World',body:'Before',kind:'knowledge',ref:selection.ref});
state.startEdit(); state.draftTitle='Edited World'; state.draftBody='Unsent changes';
const generation=state.requestGeneration, requestCount=requests.length;
// acceptClient replays this same current pane.state after a WebSocket reconnect.
select(selection); flush();
assert.equal(state.requestGeneration,generation);
assert.equal(requests.length,requestCount);
assert.equal(state.editing,true);
assert.equal(state.draftTitle,'Edited World');
assert.equal(state.draftBody,'Unsent changes');
assert.equal(state.articleBody,'Before');
state.saveArticle();
const pendingSave=requests.at(-1);
assert.equal(pendingSave.method,'PATCH');
assert.equal(state.saving,true);
select(selection); flush();
assert.equal(state.requestGeneration,generation);
assert.equal(requests.length,requestCount+1);
assert.equal(state.saving,true);
assert.equal(state.editing,true);
pendingSave.respond(200,{ok:true});
assert.equal(state.saving,false);
assert.equal(state.editing,false);
assert.equal(state.articleTitle,'Edited World');
assert.equal(state.articleBody,'Unsent changes');
assert.equal(state.noticeMessage,'Article saved.');
""")


def test_shell_reader_projection_limits_preview_and_captured_metadata():
    run_functions(SERVER, r"""
const clean=value=>JSON.parse(JSON.stringify(state.cleanReaderSelection(value)));
const uncollected=preview('Live headline');
assert.deepEqual(clean({...uncollected,secret:'do not forward',item:{...uncollected.item,body:'not a full article',token:'do not forward'}}),uncollected);
// The Python preview contract counts Unicode characters, including supplementary ones.
assert.equal(clean({...uncollected,item:{...uncollected.item,title:'\u{1f30d}'.repeat(300)}}).item.title,
    '\u{1f30d}'.repeat(300));
const selection=sourceSelection(sourceA);
assert.deepEqual(clean({...selection,secret:'do not forward'}),{...selection,graph_id:''});
for (const invalid of [null,{},[],{kind:'other'},
    {kind:'feed_preview'}, {kind:'feed_preview',item:'invalid'},
    {...uncollected,item:{...uncollected.item,title:'x'.repeat(301)}},
    {...uncollected,item:{...uncollected.item,summary:'x'.repeat(4001)}},
    {...uncollected,item:{...uncollected.item,reporting_url:'x'.repeat(2049)}},
    {...uncollected,item:{...uncollected.item,feed_title:'x'.repeat(301)}},
    {...uncollected,item:{...uncollected.item,feed_url:'x'.repeat(2049)}},
    {...uncollected,item:{...uncollected.item,published:'x'.repeat(101)}},
    {...uncollected,item:{...uncollected.item,title:'Hidden\u0000text'}},
    {...selection,feed_item_id:'../wrong-resource'},
    {...selection,key:''}]) {
    assert.equal(state.cleanReaderSelection(invalid),null,JSON.stringify(invalid));
}
assert.equal(clean({kind:'article',ref:'Knowledge/World/World',graph_id:'main'}).ref,'Knowledge/World/World');
assert.equal(clean({kind:'source',key:'obsidience/ordinary.txt'}).key,'obsidience/ordinary.txt');
assert(!('feed_item_id' in clean({kind:'source',key:'obsidience/ordinary.txt'})));
""", reader=False)
