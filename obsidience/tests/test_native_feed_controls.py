"""Standalone native Feed controls preserve the existing owner boundaries."""

import json
from pathlib import Path
import re
import subprocess


PANES = Path(__file__).parents[1] / "shell/qml/panes"
SOURCE = PANES / "feeds/FeedsPane.qml"


def run_control(path, setup, body):
    """Run real handlers, readonly bindings and simple change handlers in JS."""
    qml = path.read_text()
    functions = "\n".join(re.findall(r"^    function \w+\([^\n]*\) \{.*?^    \}", qml, re.M | re.S))
    bindings = dict(re.findall(r"^    readonly property [\w.]+ (\w+): ([\s\S]*?)(?=^    (?:readonly property |property |signal |color:|clip:|function ))", qml, re.M))
    bindings.pop("apiBase", None)
    handlers = dict(re.findall(r"^    on(\w+)Changed: ([^\n]+)$", qml, re.M))
    code = r"""
import {strict as assert} from 'node:assert';
import vm from 'node:vm';
const requests=[];
class Request {
 static DONE=4;
 open(method,url){this.method=method;this.url=url;}
 setRequestHeader(){}
 send(body){this.body=body?JSON.parse(body):null;requests.push(this);}
 respond(status,payload){this.status=status;this.readyState=4;this.responseText=typeof payload==='string'?payload:JSON.stringify(payload);this.onreadystatechange();}
}
const state={XMLHttpRequest:Request,URL,apiBase:'http://isolated',connections:[],feeds:[],providers:[],destinationNodes:[],
 revision:-1,selectedFeedId:'',loading:false,busy:false,busyLabel:'',errorMessage:'',notice:'',requestGeneration:0,
 draftName:'',draftUrl:'',draftEnabled:true,draftConnectionId:'',draftDestinationRef:'',draftInterval:30,draftItemLimit:10,
 draftMaxActiveArticles:10,draftDistillInstructions:'',manageMode:false,feedDetailTab:'preview',sourceExpanded:true,
 previewData:null,previewLoading:false,previewError:'',previewGeneration:0,WebSocket:{Open:1},
 shellSocket:{status:1,sent:[],sendTextMessage(text){this.sent.push(JSON.parse(text));}},
 browser:{refreshCalls:0,refresh(){this.refreshCalls++}},openCapturedItem(){},openPreviewItem(){},
 dockLayout:{applyRecord(){}}};
""" + setup + "\nstate.root=state;vm.createContext(state);\n" + f"vm.runInContext({json.dumps(functions)},state);\n" + f"const bindings={json.dumps(bindings)}, handlers={json.dumps(handlers)};\n" + r"""
for (const [key,expression] of Object.entries(bindings)) {
 Object.defineProperty(state,key,{get(){return vm.runInContext('('+expression+')',state)}});
}
for (const [name,handler] of Object.entries(handlers)) {
 const key=name[0].toLowerCase()+name.slice(1);
 if (!(key in state)) continue;
 let value=state[key];
 Object.defineProperty(state,key,{get(){return value},set(next){if(next!==value){value=next;vm.runInContext(handler,state)}}});
}
const connection={id:'bbc',name:'BBC',kind:'rss',url:'https://feeds.bbci.co.uk',enabled:true,auth_mode:'none',credential_set:false};
const feed={id:'top',connection_id:'bbc',name:'Top stories',url:'https://feeds.bbci.co.uk/news/rss.xml',enabled:false,
 interval_minutes:30,item_limit:10,max_active_articles:10,distill_instructions:'',destination_ref:'News & Research/News & Research',
 destination_title:'News & Research',auto_curate:true,auto_curate_supported:true};
const snapshot=(revision=1)=>({revision,connections:[connection],feeds:[feed],providers:[],
 destination_nodes:[{ref:feed.destination_ref,title:'News & Research',auto_curate:true,available:true}]});
const plain=value=>JSON.parse(JSON.stringify(value));
""" + body
    result = subprocess.run(["node", "--input-type=module", "-e", code], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


def run_js(body):
    run_control(SOURCE, "", body)


def test_opening_and_draft_navigation_only_read_metadata():
    run_js(r"""
state.refresh();state.refresh();
assert(requests.every(r=>r.method==='GET'&&r.url==='http://isolated/api/connections'));
requests[1].respond(200,snapshot(2));state.openFeed('top','settings');
requests[0].respond(200,{...snapshot(),feeds:[]});
assert.equal(state.revision,2);assert.equal(state.selectedFeedId,'top');assert.equal(state.feedDetailTab,'settings');
assert.equal(requests.length,2);assert.equal(state.draftName,'Top stories');
state.newRecord();assert.equal(state.draftEnabled,true);assert.equal(state.draftUrl,connection.url);
assert.equal(state.draftItemLimit,10);assert.equal(state.draftMaxActiveArticles,10);assert.equal(state.draftInterval,30);
assert.equal(state.draftDestinationRef,'');assert.equal(state.canSave,false);
state.refresh();requests.at(-1).respond(502,{detail:'Unavailable'});
assert.equal(state.errorMessage,'Unavailable');assert.equal(state.feeds.length,1);
state.refresh();requests.at(-1).respond(200,'not-json');
assert.match(state.errorMessage,/invalid feed metadata/);assert.equal(state.feeds.length,1);
""")


def test_feed_crud_uses_exact_id_revision_and_only_feed_fields():
    run_js(r"""
state.applySnapshot(snapshot(5));state.newRecord();state.draftName='World';state.draftDestinationRef=feed.destination_ref;
state.saveRecord();state.saveRecord();assert.equal(requests.length,1);
assert.equal(requests[0].method,'POST');assert.equal(requests[0].url,'http://isolated/api/feeds');
assert.deepEqual(requests[0].body,{revision:5,name:'World',url:connection.url,enabled:true,connection_id:'bbc',
 interval_minutes:30,item_limit:10,destination_ref:feed.destination_ref,max_active_articles:10,distill_instructions:''});
const created={...feed,id:'created',name:'World',url:connection.url,enabled:true};
requests[0].respond(200,{...snapshot(6),feeds:[feed,created],created_id:'created'});
assert.equal(state.selectedFeedId,'created');assert.equal(state.revision,6);assert.equal(requests.length,1);
state.draftName='Edited';state.saveRecord();assert.equal(requests.at(-1).method,'PATCH');
assert.equal(requests.at(-1).url,'http://isolated/api/feeds/created');assert.equal(requests.at(-1).body.revision,6);
requests.at(-1).respond(409,{detail:'Configuration changed'});
assert.equal(state.draftName,'Edited');assert.equal(state.errorMessage,'Configuration changed');assert.equal(state.busy,false);
state.removeRecord();assert.equal(requests.at(-1).method,'DELETE');assert.equal(requests.at(-1).url,'http://isolated/api/feeds/created?revision=6');
requests.at(-1).respond(200,snapshot(7));assert.equal(state.selectedFeedId,'');assert.equal(state.draftName,'');
""")


def test_collection_is_explicit_and_requires_saved_settings():
    run_js(r"""
state.applySnapshot(snapshot());state.openFeed('top','preview');assert.equal(requests.length,0);
state.draftItemLimit=2;state.checkNow();assert.equal(requests.length,0);
state.loadDraft(feed);state.checkNow();state.checkNow();state.removeRecord();
assert.equal(requests.length,1);assert.equal(requests[0].method,'POST');assert.equal(requests[0].url,'http://isolated/api/feeds/top/check');
assert.equal(requests[0].body,null);requests[0].respond(200,{...snapshot(2),feeds:[{...feed,last_error:'Feed unavailable'}]});
assert.equal(state.notice,'');assert.equal(state.selectedFeed.last_error,'Feed unavailable');assert.equal(state.browser.refreshCalls,1);
""")


def test_destination_permission_is_bound_to_saved_node_and_preserves_other_drafts():
    run_js(r"""
state.applySnapshot(snapshot());state.openFeed('top','settings');
state.destinationNodes.push({ref:'Projects/Science/Science',title:'Science',auto_curate:false,available:true});
state.draftDestinationRef='Projects/Science/Science';state.setDestinationAutoCurate(false);assert.equal(requests.length,0);
state.draftDestinationRef=feed.destination_ref;state.draftName='Unsaved name';
state.setDestinationAutoCurate(false);state.setDestinationAutoCurate(false);state.openFeed('other','preview');
assert.equal(requests.length,1);assert.equal(state.selectedFeedId,'top');
assert.equal(requests[0].method,'PUT');
assert.equal(requests[0].url,'http://isolated/api/articles/News%20%26%20Research/News%20%26%20Research/auto-curate');
assert.deepEqual(requests[0].body,{enabled:false});assert.equal(state.destinationAutoCurate,true);
requests[0].respond(200,{article:feed.destination_ref,enabled:false});assert.equal(requests[1].method,'GET');
requests[1].respond(200,{...snapshot(2),feeds:[{...feed,auto_curate:false}]});
assert.equal(state.destinationAutoCurate,false);assert.equal(state.draftName,'Unsaved name');
state.setDestinationAutoCurate(true);requests.at(-1).respond(409,{detail:'Destination changed'});
assert.equal(state.destinationAutoCurate,false);assert.equal(state.errorMessage,'Destination changed');
state.setDestinationAutoCurate(true);requests.at(-1).respond(200,{article:'Unrelated/Node',enabled:true});
assert.match(state.errorMessage,/invalid Auto-curate response/);assert.equal(state.destinationAutoCurate,false);
state.newRecord();state.setDestinationAutoCurate(true);assert.equal(requests.length,4);
""")


def test_feed_destination_requires_existing_available_node_and_preserves_shared_permission():
    run_js(r"""
state.applySnapshot({...snapshot(),feeds:[feed,{...feed,id:'second'}],destination_nodes:[
 {...snapshot().destination_nodes[0],auto_curate:false},
 {ref:'Projects/Unavailable',title:'Unavailable',available:false,auto_curate:true}
]});
state.newRecord();state.draftName='Shared target';
for(const ref of ['', 'Invented/Node', 'Projects/Unavailable']) {
 state.draftDestinationRef=ref;assert.equal(state.canSave,false);state.saveRecord();
}
assert.equal(requests.length,0);state.draftDestinationRef=feed.destination_ref;
assert.equal(state.canSave,true);assert.equal(state.destinationAutoCurate,false);
state.saveRecord();assert.equal(requests[0].body.destination_ref,feed.destination_ref);
assert(!('auto_curate' in requests[0].body));assert.equal(requests.length,1);
assert(!requests.some(r=>r.url.includes('/auto-curate')||r.url.includes('/destinations')));
""")


def test_retention_instructions_and_saved_feedback_remain_distinct_from_capture_count():
    run_js(r"""
state.applySnapshot(snapshot());state.openFeed('top','settings');
state.draftItemLimit=3;state.draftMaxActiveArticles=17;state.draftDistillInstructions='Focus on findings.\nPreserve caveats.';
state.saveRecord();assert.equal(requests[0].body.item_limit,3);assert.equal(requests[0].body.max_active_articles,17);
assert.equal(requests[0].body.distill_instructions,state.draftDistillInstructions);assert(!('auto_curate' in requests[0].body));
requests[0].respond(200,{...snapshot(2),retention_result:{retention_status:'blocked',blocked_reason:'Protected Article.'}});
assert.equal(state.notice,'Settings saved. Article retirement is blocked. Protected Article.');
for (const [field,value] of [['draftItemLimit',0],['draftItemLimit',31],['draftMaxActiveArticles',0],
 ['draftMaxActiveArticles',1001],['draftInterval',4],['draftInterval',1441],['draftDistillInstructions','a'.repeat(501)]]) {
 state.loadDraft(feed);state[field]=value;assert.equal(state.canSave,false);state.saveRecord();
}
assert.equal(requests.length,1);state.loadDraft(feed);state.draftDistillInstructions='😀'.repeat(500);
assert.equal(state.instructionLength,500);assert.equal(state.canSave,true);
""")


def test_preview_is_explicit_and_drops_old_url_selection_and_revision_responses():
    run_js(r"""
const response=(context,title='Preview')=>({...context,feed_title:title,feed_description:'Provider text',feed_format:'rss20',
 available_count:2,count_limited:false,entries:[{position:1,title:'First',summary:'One',published:'',reporting_url:'https://report.example/1'},
 {position:2,title:'Second',summary:'Two',published:'',reporting_url:'https://report.example/2'}]});
state.applySnapshot(snapshot(4));state.openFeed('top','preview');assert.equal(requests.length,0);
state.requestPreview();state.requestPreview();assert.equal(requests.length,1);const old=requests[0];
assert.deepEqual(old.body,{revision:4,connection_id:'bbc',url:feed.url,item_limit:10});
state.draftUrl='https://feeds.bbci.co.uk/other';assert.equal(state.previewLoading,false);
state.requestPreview();const current=requests[1];current.respond(200,response(current.body));
old.respond(200,response(old.body,'Old'));assert.equal(state.previewData.feed_title,'Preview');
state.draftItemLimit=1;assert.equal(requests.length,2);assert.equal(state.previewData.entries.length,2);
state.requestPreview();const stale=requests.at(-1);state.applySnapshot(snapshot(5),true);
stale.respond(200,response(stale.body));assert.equal(state.previewData,null);
state.requestPreview();requests.at(-1).respond(400,{detail:'Invalid provider feed'});assert.equal(state.previewError,'Invalid provider feed');
assert(requests.every(r=>r.url==='http://isolated/api/feeds/preview'));
""")


def test_preview_attests_returned_resource_and_accepts_equivalent_normalized_url():
    run_js(r"""
state.applySnapshot(snapshot(4));state.openFeed('top','preview');
const response=context=>({...context,feed_title:'Provider',available_count:0,entries:[]});
state.requestPreview();const wrong=requests.at(-1);
wrong.respond(200,{...response(wrong.body),url:'https://feeds.bbci.co.uk/other'});
assert.equal(state.previewData,null);assert.match(state.previewError,/could not be read/);
state.draftUrl='https://feeds.bbci.co.uk:443#fragment';state.requestPreview();
const normalized=requests.at(-1);normalized.respond(200,{...response(normalized.body),url:'https://feeds.bbci.co.uk/'});
assert.equal(state.previewData.feed_title,'Provider');
state.requestPreview();const wrongConnection=requests.at(-1);
wrongConnection.respond(200,{...response(wrongConnection.body),connection_id:'other'});
assert.equal(state.previewData,null);
state.requestPreview();const oversized=requests.at(-1);
oversized.respond(200,{...response(oversized.body),entries:Array.from({length:31},()=>({title:'Item',summary:''}))});
assert.equal(state.previewData,null);assert.equal(state.previewLoading,false);
""")


def test_presets_are_same_origin_and_do_not_fetch_or_overwrite_custom_endpoint():
    run_js(r"""
state.applySnapshot({...snapshot(),connections:[connection,{...connection,id:'other',url:'https://other.example/rss'}],providers:[
 {name:'BBC',feeds:[{name:'World',url:'https://feeds.bbci.co.uk:443/world',description:'World stories'},
 {name:'HTTP',url:'http://feeds.bbci.co.uk/rss'},{name:'Wrong',url:'https://feeds.bbci.co.uk.fake.example/rss'}]}]});
state.newRecord();assert.equal(state.presets.length,2);state.usePreset(1);
assert.equal(state.draftName,'World');assert.equal(state.offeringDescription(),'World stories');
state.chooseFeedConnection('other');assert.equal(state.draftUrl,'https://feeds.bbci.co.uk:443/world');
assert.equal(state.presets.length,1);state.draftUrl='https://other.example/rss';state.chooseFeedConnection('bbc');
assert.equal(state.draftUrl,connection.url);assert.equal(requests.length,0);
""")


def test_items_route_to_reader_and_access_setup_routes_to_settings_without_acquisition():
    run_js(r"""
state.presentCapturedItem({source_id:'exact-id',source_path:'obsidience/evidence/raw/exact.md'});
assert.deepEqual(state.shellSocket.sent[0],{schema:'obsidience.shell.command.v1',type:'pane.present',pane_id:'reader',
 selection:{kind:'source',key:'obsidience/evidence/raw/exact.md',feed_item_id:'exact-id'}});
state.presentPreviewItem({title:'Provider item',summary:'Untrusted <b>publisher</b> text',reporting_url:'https://report.example/1',feed_title:'News'});
assert.equal(state.shellSocket.sent[1].selection.kind,'feed_preview');
assert.equal(state.shellSocket.sent[1].selection.item.summary,'Untrusted <b>publisher</b> text');
state.openConnectionSettings();assert.deepEqual(state.shellSocket.sent[2],{schema:'obsidience.shell.command.v1',
 type:'pane.present',pane_id:'settings',selection:{kind:'settings',section:'connections'}});
assert.equal(requests.length,0);
""")
