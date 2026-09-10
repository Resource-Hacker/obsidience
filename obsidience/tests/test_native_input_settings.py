"""Input responses respect the Settings Loader's page lifetime."""

from obsidience.tests.test_native_feed_browser import PANES, run_qml_functions


SOURCE = PANES / "settings/input/InputSettings.qml"
FIELDS = "apiBase:'http://isolated',inputState:{},"


def test_input_ignores_delayed_responses_after_settings_page_is_destroyed():
    run_qml_functions(SOURCE, FIELDS, r"""
state.refresh();state.refresh();state.refresh();
assert.equal(requests.length,3);
assert(requests.every(request=>request.method==='GET'&&request.url==='http://isolated/api/input'));
// Selecting another section destroys this InputSettings instance before replies arrive.
state.root=null;
assert.doesNotThrow(()=>requests[0].respond(200,{mouse:{name:'Mouse'},keyboard:{name:'Keyboard'}}));
assert.doesNotThrow(()=>requests[1].respond(503,{detail:'Unavailable'}));
requests[2].status=200;requests[2].readyState=Request.DONE;requests[2].responseText='{"mouse":';
assert.doesNotThrow(()=>requests[2].onreadystatechange());
assert.equal(Object.keys(state.inputState).length,0);assert.equal(state.errorMessage,'');
""")


def test_live_input_settings_accepts_readings_and_preserves_them_on_error():
    run_qml_functions(SOURCE, FIELDS, r"""
state.refresh();requests[0].respond(200,{mouse:{name:'Mouse'},keyboard:{name:'Keyboard'}});
assert.equal(state.inputState.mouse.name,'Mouse');assert.equal(state.errorMessage,'');
state.refresh();requests[1].respond(503,{detail:'Unavailable'});
assert.equal(state.errorMessage,'Input state unavailable (503)');
assert.equal(state.inputState.keyboard.name,'Keyboard');
state.refresh();requests[2].status=200;requests[2].readyState=Request.DONE;requests[2].responseText='{"mouse":';
requests[2].onreadystatechange();
assert.equal(state.errorMessage,'Input state was invalid');assert.equal(state.inputState.mouse.name,'Mouse');
""")
