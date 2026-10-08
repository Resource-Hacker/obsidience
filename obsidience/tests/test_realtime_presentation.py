"""Exercise the native read-only speech projection and actual waveform geometry."""
import json
import os
from pathlib import Path
import re
import subprocess


QML = Path(__file__).parents[1] / "shell/qml"


def test_realtime_projection_uses_actual_samples_and_immediate_transcripts():
    source = (QML / "api/RealtimeState.qml").read_text()
    functions = re.findall(r"    function \w+\([^\n]*\) \{.*?\n    \}", source, re.S)
    assert len(functions) == 3
    script = f"""
const assert=require('node:assert/strict'),vm=require('node:vm');
let captions=0;
const context={{state:{{}},levels:[],connected:true,levelLimit:32,transcriptUpdated:()=>captions++}};
vm.createContext(context);vm.runInContext({json.dumps(chr(10).join(functions))},context);
const state={{enabled:true,ready:true,command_open:true,phase:'command',input_level:0.25,capture_active:false,user_speaking:false,live_transcript:null}};
const event=(payload,reason,type='runtime')=>context.applyMessage(JSON.stringify({{type,reason,state:payload}}));
event(state,undefined,'state');assert.equal(context.levels.length,0);
for(let i=0;i<40;i++)event({{...state,input_level:i/40}},'input_level');
assert.equal(context.levels.length,32);assert.equal(context.levels[0],8/40);
const sampled=JSON.stringify(context.levels);
event({{...state,capture_active:true}},'capture_active');
assert.equal(context.state.capture_active,true);assert.equal(context.state.user_speaking,false);
assert.equal(JSON.stringify(context.levels),sampled);
// Real partials appear on the very first event, before finalization or HTTP.
event({{...state,capture_active:true,live_transcript:{{text:'recognize these',final:false}}}});
assert.equal(context.state.live_transcript.text,'recognize these');assert.equal(captions,1);
event({{...state,live_transcript:{{text:'recognize these',final:false}}}});
assert.equal(captions,1);
event({{...state,live_transcript:{{text:'recognize these words',final:true}}}});
assert.equal(captions,2);assert.equal(context.state.live_transcript.final,true);
assert.equal(context.levels.length,32); // Transcript events are not amplitude samples.
context.disconnected();assert.equal(context.connected,false);assert.equal(context.state.ready,false);
assert.equal(context.levels.length,0);assert.equal(context.state.live_transcript,null);
event({{...state,live_transcript:{{text:'old final',final:true}}}},undefined,'state');
assert.equal(context.levels.length,0);assert.equal(captions,2); // Snapshot cannot reopen the shelf.
event({{...state,input_level:2}},'input_level');assert.equal(context.levels[0],1);
event({{...state,input_level:-1}},'input_level');assert.equal(context.levels[1],0);
event({{...state,input_level:'bad'}},'input_level');assert.equal(context.levels[2],0);
event({{...state,live_transcript:{{text:'a'.repeat(5000)+' latest',final:false}}}});
assert.equal(context.state.live_transcript.text.length,4096);
assert(context.state.live_transcript.text.endsWith(' latest'));
event({{...state,enabled:false,capture_active:true,live_transcript:{{text:'stale',final:true}}}});
assert.equal(context.levels.length,0);assert.equal(context.state.live_transcript,null);
assert.equal(context.state.capture_active,false);
const before=JSON.stringify(context.state);
for(const invalid of ['{{','null','[]','x'.repeat(1048577)])context.applyMessage(invalid);
assert.equal(JSON.stringify(context.state),before);
"""
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


def test_waveform_real_qml_geometry_and_quiet_reset(tmp_path):
    # The launcher's recognition caption was retired; the waveform remains.
    fixture = tmp_path / "tst_waveform.qml"
    fixture.write_text(f"""
import QtQuick
import QtTest
import {json.dumps((QML / 'components/visual').as_uri())} as Visual

TestCase {{
    id: root
    name: "InputWaveform"
    when: windowShown
    width: 352; height: 100
    Visual.InputWaveform {{ id: waveform; width: 280; height: 24 }}
    function test_samples_and_reset() {{
        compare(findChild(waveform, "inputBar0").height, 2)
        waveform.levels = [0, 0.5, 1]
        waveform.capturing = true
        tryCompare(findChild(waveform, "inputBar31"), "height", 24)
        compare(findChild(waveform, "inputBar30").height, 13)
        compare(findChild(waveform, "inputBar28").height, 2)
        const last = findChild(waveform, "inputBar31")
        compare(last.y + last.height / 2, 12)
        waveform.width = 160
        verify(last.width > 0)
        tryVerify(() => last.x + last.width <= waveform.width + 0.1)
        waveform.levels = []
        tryCompare(last, "height", 2)
    }}
}}
""")
    result = subprocess.run(
        ["/usr/lib/qt6/bin/qmltestrunner", "-platform", "offscreen", "-input", str(fixture)],
        capture_output=True, text=True, timeout=15,
        env={**os.environ, "QT_QUICK_BACKEND": "software", "QSG_RHI_BACKEND": "software"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
