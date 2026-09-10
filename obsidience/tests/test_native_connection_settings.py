"""Connection Settings preserves revision and credential boundaries without feeds."""

from obsidience.tests.test_native_feed_controls import PANES, run_control


SOURCE = PANES / "settings/connections/ConnectionsSettings.qml"


def run_js(body):
    run_control(
        SOURCE,
        "Object.assign(state,{selectedConnectionId:'',draftKind:'rss',draftAuthMode:'none',credentialSecret:'',visible:true});",
        body,
    )


def test_opening_settings_only_reads_metadata_and_rejects_stale_or_invalid_refresh():
    run_js(r"""
state.refresh();state.refresh();
assert(requests.every(r=>r.method==='GET'&&r.url==='http://isolated/api/connections'));
requests[1].respond(200,snapshot(2));assert.equal(state.selectedConnectionId,'bbc');
assert.equal(state.draftName,'BBC');assert.equal(state.credentialSecret,'');
requests[0].respond(200,{...snapshot(),connections:[]});
assert.equal(state.revision,2);assert.equal(state.connections.length,1);
state.refresh();requests.at(-1).respond(503,{detail:'Provider unavailable'});
assert.equal(state.errorMessage,'Provider unavailable');assert.equal(state.connections.length,1);
state.refresh();requests.at(-1).respond(200,'not json');
assert.match(state.errorMessage,/invalid connection metadata/);assert.equal(state.connections.length,1);
state.newRecord();state.selectRow('bbc');assert.equal(requests.length,4);
""")


def test_connection_crud_has_exact_ids_revisions_and_no_feed_side_effect():
    run_js(r"""
state.applySnapshot(snapshot(5));state.newRecord();
assert.equal(state.draftKind,'rss');assert.equal(state.draftAuthMode,'none');assert.equal(state.draftEnabled,true);
state.draftName=' New API ';state.draftUrl=' https://api.example.test/v1 ';state.draftKind='http_api';state.draftAuthMode='bearer';
state.saveRecord();state.saveRecord();assert.equal(requests.length,1);
assert.equal(requests[0].method,'POST');assert.equal(requests[0].url,'http://isolated/api/connections');
assert.deepEqual(requests[0].body,{revision:5,name:'New API',url:'https://api.example.test/v1',kind:'http_api',auth_mode:'bearer',enabled:true});
const created={...connection,id:'created-api',name:'New API',url:'https://api.example.test/v1',kind:'http_api',auth_mode:'bearer'};
requests[0].respond(200,{...snapshot(6),connections:[connection,created],created_id:created.id});
assert.equal(state.selectedConnectionId,'created-api');assert.equal(state.revision,6);assert.equal(requests.length,1);
state.draftName='Edited API';state.draftEnabled=false;state.saveRecord();
assert.equal(requests[1].method,'PATCH');assert.equal(requests[1].url,'http://isolated/api/connections/created-api');
assert.equal(requests[1].body.revision,6);assert.equal(requests[1].body.enabled,false);
requests[1].respond(409,{detail:'Configuration changed; refresh'});
assert.equal(state.errorMessage,'Configuration changed; refresh');assert.equal(state.draftName,'Edited API');assert.equal(state.busy,false);
state.removeRecord();assert.equal(requests[2].method,'DELETE');
assert.equal(requests[2].url,'http://isolated/api/connections/created-api?revision=6');
requests[2].respond(200,snapshot(7));assert.equal(state.selectedConnectionId,'');assert.equal(state.draftName,'');
assert(!requests.some(r=>r.url.includes('/feeds')||r.url.includes('/credential')));
""")


def test_connection_check_is_explicit_single_flight_and_requires_saved_settings():
    run_js(r"""
state.applySnapshot(snapshot());state.draftUrl='https://unsaved.example/';state.checkNow();assert.equal(requests.length,0);
state.selectRow('bbc');state.checkNow();state.checkNow();state.removeRecord();state.selectRow('other');
assert.equal(requests.length,1);assert.equal(state.selectedConnectionId,'bbc');
assert.equal(requests[0].method,'POST');assert.equal(requests[0].url,'http://isolated/api/connections/bbc/check');
assert.equal(requests[0].body,null);requests[0].respond(502,{detail:'Endpoint did not respond'});
assert.equal(state.busy,false);assert.equal(state.errorMessage,'Endpoint did not respond');
state.checkNow();requests[1].respond(200,{...snapshot(2),connections:[{...connection,last_error:'HTTP 403'}]});
assert.equal(state.notice,'');assert.equal(state.selectedConnection.last_error,'HTTP 403');
assert.equal(state.rowStatus(state.selectedConnection),'Check failed');
assert.equal(requests.length,2);assert.equal(state.browser.refreshCalls,0);
""")


def test_credentials_are_write_only_cleared_on_submit_and_never_echoed_from_errors():
    run_js(r"""
connection.auth_mode='bearer';state.applySnapshot(snapshot(4));state.credentialSecret='private-example';state.saveCredential();
assert.equal(state.credentialSecret,'');assert.equal(requests[0].method,'PUT');
assert.equal(requests[0].url,'http://isolated/api/connections/bbc/credential');
assert.deepEqual(requests[0].body,{revision:4,secret:'private-example'});
requests[0].respond(400,{detail:'Do not echo private-example'});
assert(!state.errorMessage.includes('private-example'));assert.match(state.errorMessage,/Credential change failed/);
state.credentialSecret='replacement';state.saveCredential();
requests[1].respond(200,{...snapshot(5),connections:[{...connection,credential_set:true}]});
assert.equal(state.credentialSecret,'');assert.equal(state.credentialReady,true);
state.credentialSecret='unused';state.removeCredential();assert.equal(state.credentialSecret,'');
assert.equal(requests[2].method,'DELETE');assert.equal(requests[2].url,'http://isolated/api/connections/bbc/credential?revision=5');
assert.equal(requests[2].body,null);requests[2].respond(200,snapshot(6));assert.equal(state.credentialReady,false);
""")
    assert "echoMode: TextInput.Password" in SOURCE.read_text()


def test_credentials_require_saved_auth_context_and_clear_on_context_or_visibility_change():
    run_js(r"""
connection.auth_mode='bearer';state.applySnapshot(snapshot(4));
state.credentialSecret='pending';state.draftAuthMode='bot';assert.equal(state.credentialSecret,'');
state.credentialSecret='unsaved-mode';state.saveCredential();state.removeCredential();assert.equal(requests.length,0);
state.draftAuthMode='bearer';state.credentialSecret='pending';state.draftUrl='https://changed.example/';
assert.equal(state.credentialSecret,'');state.credentialSecret='unsaved-url';state.saveCredential();assert.equal(requests.length,0);
state.selectRow('bbc');assert.equal(state.credentialSecret,'');state.credentialSecret='pending';state.newRecord();assert.equal(state.credentialSecret,'');
state.draftName='New';state.draftUrl='https://new.example/';state.draftAuthMode='bearer';state.credentialSecret='unsaved-record';
state.saveCredential();state.removeCredential();assert.equal(requests.length,0);
state.selectRow('bbc');state.credentialSecret='hidden';state.visible=false;assert.equal(state.credentialSecret,'');
""")
    assert 'Component.onDestruction: credentialSecret = ""' in SOURCE.read_text()


def test_provider_presets_have_clean_defaults_and_no_discovery_or_collection_requests():
    run_js(r"""
state.applySnapshot({...snapshot(),providers:[
 {name:'Example RSS',url:'https://publisher.example/rss',kind:'rss',description:'Current RSS stories'},
 {name:'Example API',url:'https://api.example/v1',kind:'http_api',description:'API connectivity'}]});
state.newRecord();assert.equal(state.presets.length,3);state.usePreset(1);
assert.equal(state.draftName,'Example RSS');assert.equal(state.draftUrl,'https://publisher.example/rss');
assert.equal(state.draftKind,'rss');assert.equal(state.draftAuthMode,'none');assert.equal(state.draftEnabled,true);
assert.equal(state.offeringDescription(),'Current RSS stories');
state.usePreset(2);assert.equal(state.draftKind,'http_api');assert.equal(state.draftAuthMode,'none');
assert.equal(state.offeringDescription(),'API connectivity');state.draftUrl='https://different.example/';
assert.match(state.offeringDescription(),/read-only access/);
assert.equal(state.sameOrigin('https://api.example:443/path','https://api.example/other'),true);
assert.equal(state.sameOrigin('https://api.example/path','https://api.example.other/other'),false);
assert.equal(state.sameOrigin('invalid','https://api.example'),false);
assert.equal(requests.length,0);
""")
