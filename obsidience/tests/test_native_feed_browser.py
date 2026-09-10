"""Standalone captured Feed list preserves selection across refreshes."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

PANES = Path(__file__).parents[1] / 'shell/qml/panes'


def run_qml_functions(path, fields, body):
    functions = '\n'.join(re.findall(r'^    function \w+\([^\n]*\) \{.*?^    \}', path.read_text(), re.M | re.S))
    code = r'''
import {strict as assert} from 'node:assert';
import vm from 'node:vm';
const requests=[];
class Request {
 static DONE=4;
 open(method,url){this.method=method;this.url=url;}
 send(){requests.push(this);}
 respond(status,payload){this.status=status;this.readyState=4;this.responseText=JSON.stringify(payload);this.onreadystatechange();}
}
const state={XMLHttpRequest:Request,requestGeneration:0,loading:false,errorMessage:'',
''' + fields + '};\nstate.root=state;vm.createContext(state);\n' + f'vm.runInContext({json.dumps(functions)},state);\n' + body
    result = subprocess.run(['node','--input-type=module','-e',code],capture_output=True,text=True,timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


def test_capture_list_preserves_selection_and_discards_old_feed_responses():
    run_qml_functions(PANES / 'feeds/FeedBrowser.qml', r'''
 apiBase:'http://isolated',selectedFeedId:'',selectedItemId:'',items:[],truncated:false,
 connections:[{id:'bbc',name:'BBC'},{id:'other',name:'Other'}],
 feeds:[{id:'top',connection_id:'bbc',name:'Top'},{id:'second',connection_id:'other',name:'Second'}],
''', r'''
const item=(id)=>({source_id:id,source_path:'obsidience/evidence/raw/'+id+'.json',title:'Captured '+id});
state.refresh();assert.equal(requests[0].method,'GET');assert.equal(requests[0].url,'http://isolated/api/feeds/items?limit=100');
requests[0].respond(200,{items:[item('a'),item('b')]});assert.equal(state.selectedItemId,'a');
state.selectedItemId='b';state.refresh();requests.at(-1).respond(200,{items:[item('c'),item('b'),item('a')]});
assert.equal(state.selectedItemId,'b'); // A new first item must not interrupt reading.
state.selectFeed('top');const old=requests.at(-1);assert.equal(state.selectedItemId,'');
state.selectFeed('second');const current=requests.at(-1);
assert.equal(current.url,'http://isolated/api/feeds/items?limit=100&feed_id=second');
current.respond(200,{items:[item('d')]});old.respond(200,{items:[item('stale')]});
assert.equal(state.selectedItemId,'d');assert.equal(state.items[0].source_id,'d');
state.refresh();requests.at(-1).respond(502,{detail:'Unavailable'});
assert.match(state.errorMessage,/HTTP 502/);assert.equal(state.selectedItemId,'d');
state.refresh();requests.at(-1).respond(200,{items:[]});assert.equal(state.selectedItemId,'');
assert.equal(state.itemDate({captured_at:1788966000}),'2026-09-09');
assert.equal(state.destinationLabel({destination_ref:'Projects/Science/Science',destination_title:'Science',auto_curate:true,auto_curate_supported:true}),'Science · Automatic');
assert.equal(state.destinationLabel({destination_ref:'Projects/Science/Science',auto_curate:false,auto_curate_supported:true}),'Projects/Science/Science · Review');
assert.equal(state.destinationLabel({destination_ref:'Projects/Science/Science'}),'Projects/Science/Science · Permission unavailable');
assert.equal(state.destinationLabel({destination_error:'Missing node'}),'Destination unavailable · Missing node');
assert.equal(state.destinationLabel({}),'Select a Knowledge destination');
assert.equal(state.activeArticleLabel({active_article_count:14,max_active_articles:10}),'Active articles: 14 / 10');
assert.equal(state.activeArticleLabel({}),'Active articles: Not reported / Not reported');
assert.equal(state.retentionLabel({retention_status:'review_required'}),'Retirement needs review');
assert.equal(state.retentionLabel({retention_status:'blocked'}),'Retirement blocked');
assert.equal(state.retentionLabel({retention_status:'over_limit'}),'Over article limit');
assert.equal(state.retentionLabel({retention_status:'within_limit'}),'Within limit');
assert.equal(state.retentionLabel({}),'Retention not reported');
assert(requests.every(request=>request.method==='GET'));
''')

