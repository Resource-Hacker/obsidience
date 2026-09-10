"""Graph inventory responses respect the Settings Loader's page lifetime."""

from obsidience.tests.test_native_feed_browser import PANES, run_qml_functions


SOURCE = PANES / "settings/graph/GraphSettings.qml"
FIELDS = "apiBase:'http://isolated',selectedGraphId:'library',graphOptions:[],selectedIndex:0,"


def test_graph_inventory_ignores_responses_after_settings_page_is_destroyed():
    run_qml_functions(SOURCE, FIELDS, r"""
let stateRequests=0;state.requestState=()=>{stateRequests+=1;};
state.refreshGraphs();state.refreshGraphs();state.refreshGraphs();
assert.equal(requests.length,3);
assert(requests.every(request=>request.method==='GET'&&request.url==='http://isolated/api/graph'));
// Switching the Settings Loader to Connections destroys the old GraphSettings root.
state.root=null;
assert.doesNotThrow(()=>requests[0].respond(200,{navigation:{groups:[{id:'library',title:'Library'}]}}));
assert.doesNotThrow(()=>requests[1].respond(503,{detail:'Unavailable'}));
requests[2].status=200;requests[2].readyState=Request.DONE;requests[2].responseText='{"navigation":';
assert.doesNotThrow(()=>requests[2].onreadystatechange());
assert.equal(state.graphOptions.length,0);assert.equal(state.errorMessage,'');
assert.equal(stateRequests,0);
""")


def test_live_graph_settings_preserves_selection_and_reports_inventory_errors():
    run_qml_functions(SOURCE, FIELDS, r"""
let stateRequests=0;state.requestState=()=>{stateRequests+=1;};
state.refreshGraphs();
requests[0].respond(200,{navigation:{groups:[
    {id:'library',title:'Library'},{id:'executive',title:'Executive'}]}});
assert.equal(state.graphOptions[0].graphId,'main');
assert.equal(state.graphOptions[1].graphId,'library');
assert.equal(state.selectedIndex,1);assert.equal(stateRequests,1);
state.refreshGraphs();requests[1].respond(503,{detail:'Graph temporarily unavailable'});
assert.equal(state.errorMessage,'Graph temporarily unavailable');
assert.equal(state.graphOptions.length,2);assert.equal(stateRequests,1);
state.refreshGraphs();
requests[2].status=200;requests[2].readyState=Request.DONE;requests[2].responseText='{"navigation":';
requests[2].onreadystatechange();
assert.equal(state.errorMessage,'Obsidience returned invalid graph navigation.');
assert.equal(state.graphOptions.length,2);assert.equal(stateRequests,1);
""")
