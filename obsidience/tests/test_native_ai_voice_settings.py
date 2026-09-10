"""AI & Voice keeps the existing settings owners and sends no default writes."""

import json
from pathlib import Path
import re
import subprocess

import pytest


SOURCE = Path(__file__).parents[1] / "shell/qml/panes/settings/ai_voice/AiVoiceSettings.qml"


def catalog():
    return {
        "switching": False,
        "slots": [
            {"id": "cpu", "kind": "cpu", "label": "CPU", "selected": "none", "options": []},
            {"id": "rtx4080", "kind": "gpu", "label": "RTX 4080 SUPER", "selected": "omniparser",
             "options": [{"id": "omniparser", "label": "OmniParser", "available": True},
                         {"id": "none", "label": "None", "available": True},
                         {"id": "unavailable", "label": "Unavailable model", "available": False}]},
            {"id": "rtx4000", "kind": "gpu", "label": "RTX 4000 Ada", "selected": "gemma",
             "options": [{"id": "gemma", "label": "Gemma", "available": True}]},
        ],
        "interfaces": [
            {"id": kind, "label": label, "selected": kind + "-saved",
             "options": [{"id": kind + "-saved", "label": "Saved " + label, "available": True},
                         {"id": kind + "-next", "label": "Other " + label, "available": True},
                         {"id": "missing", "label": "Disconnected device", "available": False}]}
            for kind, label in [("microphone", "Microphone input"), ("speaker", "Speaker output"), ("camera", "Preferred camera")]
        ],
        "speech": {"voice": "hal", "voices": [{"id": "hal", "label": "HAL"}, {"id": "starfleet", "label": "Star Trek Computer"}]},
    }


def run_js(body):
    text = SOURCE.read_text()
    functions = "\n".join(re.findall(r"^    function \w+\([^\n]*\) \{.*?^    \}", text, re.M | re.S))
    bindings = dict(re.findall(r"^    readonly property \w+ (\w+): (.+)$", text, re.M))
    bindings.pop("apiBase")
    program = r"""
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
const state={XMLHttpRequest:Request,apiBase:'http://isolated',hardware:null,loading:false,changing:'',errorMessage:'',notice:''};
state.root=state;vm.createContext(state);
""" + f"vm.runInContext({json.dumps(functions)},state);\nconst bindings={json.dumps(bindings)};\nconst initial={json.dumps(catalog())};\n" + r"""
for(const [key,expression] of Object.entries(bindings)) Object.defineProperty(state,key,{get(){return vm.runInContext('('+expression+')',state)}});
const copy=value=>JSON.parse(JSON.stringify(value));
""" + body
    result = subprocess.run(["node", "--input-type=module", "-e", program], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


def test_opening_and_reload_only_read_saved_settings_and_preserve_failed_reads():
    run_js(r"""
state.refresh();state.refresh();assert.equal(requests.length,1);
assert.equal(requests[0].method,'GET');assert.equal(requests[0].url,'http://isolated/api/hardware');
requests[0].respond(200,initial);assert.deepEqual(copy(state.hardware),initial);assert.equal(state.gpuSlots.length,2);
state.refresh();requests[1].respond(200,{slots:[]});assert.deepEqual(copy(state.hardware),initial);assert.match(state.errorMessage,/Reload/);
state.refresh();requests[2].respond(503,{detail:'Runtime unavailable'});assert.deepEqual(copy(state.hardware),initial);
assert.equal(state.errorMessage,'Runtime unavailable');assert.equal(state.busy,false);
assert(requests.every(request=>request.method==='GET'));
""")


def test_residency_changes_are_exact_explicit_available_and_single_flight():
    run_js(r"""
state.applySnapshot(initial);
for(const [device,value] of [['cpu','none'],['rtx4080','omniparser'],['rtx4080','unavailable'],['missing','none']]) state.assignSlot(device,value);
assert.equal(requests.length,0);
state.hardware.switching=true;state.assignSlot('rtx4080','none');assert.equal(requests.length,0);state.hardware.switching=false;
state.assignSlot('rtx4080','none');state.assignVoice('starfleet');state.refresh();assert.equal(requests.length,1);
assert.equal(requests[0].method,'PATCH');assert.equal(requests[0].url,'http://isolated/api/hardware');
assert.deepEqual(requests[0].body,{device:'rtx4080',component:'none'});
requests[0].respond(400,{detail:'Device is reserved'});assert.equal(state.hardware.slots[1].selected,'omniparser');
assert.equal(state.errorMessage,'Device is reserved');assert.equal(state.busy,false);
state.assignSlot('rtx4080','none');const updated=copy(initial);updated.slots[1].selected='none';
requests[1].respond(200,updated);assert.equal(state.hardware.slots[1].selected,'none');assert.equal(state.notice,'Model residency saved.');
""")


def test_media_and_voice_keep_existing_payloads_and_never_write_on_binding():
    run_js(r"""
state.applySnapshot(initial);
state.assignInterface('microphone','microphone-saved');state.assignInterface('speaker','missing');
state.assignVoice('hal');state.assignVoice('unknown');assert.equal(requests.length,0);
for(const kind of ['microphone','speaker','camera']) {
 state.assignInterface(kind,kind+'-next');const request=requests.at(-1);
 assert.equal(request.method,'PATCH');assert.equal(request.url,'http://isolated/api/hardware/interfaces');
 assert.deepEqual(request.body,{interface:kind,selection:kind+'-next'});
 const updated=copy(state.hardware);updated.interfaces.find(row=>row.id===kind).selected=kind+'-next';request.respond(200,updated);
}
state.assignVoice('starfleet');const voice=requests.at(-1);
assert.equal(voice.url,'http://isolated/api/hardware/voice');assert.deepEqual(voice.body,{voice:'starfleet'});
voice.respond(200,{voice:'starfleet'});assert.equal(requests.at(-1).method,'GET');
const updated=copy(state.hardware);updated.speech.voice='starfleet';requests.at(-1).respond(200,updated);
assert.equal(state.hardware.speech.voice,'starfleet');assert.equal(state.busy,false);
""")


@pytest.mark.parametrize("width", [440, 840])
def test_native_settings_load_without_writes_and_restore_selection_after_rejection(tmp_path, width):
    import http.server
    import os
    import shutil
    import threading

    qml = shutil.which("qml6")
    if qml is None:
        pytest.skip("qml6 is not installed")
    requests = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(("GET", self.path, None))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(catalog()).encode())

        def do_PATCH(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(("PATCH", self.path, body))
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"detail":"Device is reserved"}')

        def log_message(self, *_args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    visual = json.dumps((SOURCE.parents[3] / "components/visual").resolve().as_uri())
    text = SOURCE.read_text().replace("http://127.0.0.1:8765", f"http://127.0.0.1:{server.server_port}")
    (tmp_path / SOURCE.name).write_text(text.replace('import "../../../components/visual"', "import " + visual))
    (tmp_path / "fixture.qml").write_text(r"""
import QtQuick
import QtQuick.Window
Window {
 id: win
 width: WIDTH; height: 712; visible:true; color:'#040c12'
 property int stage:0
 AiVoiceSettings { id:pane; anchors.fill:parent }
 function findObject(parent,name) {
  if(parent.objectName===name)return parent
  const children=parent.children||[]
  for(let i=0;i<children.length;i++){const found=findObject(children[i],name);if(found)return found}
  return null
 }
 Timer {
  interval:100;repeat:true;running:true
  onTriggered: {
   if(pane.busy||!pane.hardware)return
   const slot=findObject(pane,'ai-slot-rtx4080')
   if(stage===0){
    for(const name of ['ai-slot-rtx4080','ai-slot-rtx4000','ai-interface-microphone','ai-interface-speaker','ai-interface-camera','ai-voice-selection']){
     const control=findObject(pane,name)
     if(!control||control.currentIndex!==0||control.width<100||control.mapToItem(pane,control.width,0).x>pane.width){console.log('Invalid control',name,control,control?control.currentIndex:-5,control?control.count:0,control?JSON.stringify(control.model):'',JSON.stringify(control.parent.modelData),JSON.stringify(pane.optionRows(pane.gpuSlots[0].options)));Qt.exit(20);return}
    }
    stage=1;slot.currentIndex=1;slot.activated(1)
   }else if(stage===1){
    if(!pane.errorMessage)return
    if(slot.currentIndex!==0||pane.hardware.slots[1].selected!=='omniparser'){Qt.exit(21);return}
    stage=2
    pane.grabToImage(result=>{result.saveToFile(IMAGE);Qt.quit()})
   }
  }
 }
 Timer { interval:5000;running:true;onTriggered:Qt.exit(22) }
}
""".replace("WIDTH", str(width)).replace("IMAGE", json.dumps(str(tmp_path / "ai-voice.png"))))
    environment = os.environ.copy()
    environment.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", QT_QUICK_CONTROLS_STYLE="Basic", QT_FORCE_STDERR_LOGGING="1")
    try:
        result = subprocess.run([qml, str(tmp_path / "fixture.qml")], env=environment, capture_output=True, text=True, timeout=8)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert result.returncode == 0, result.stdout + result.stderr + repr(requests)
    assert not any(error in result.stderr for error in ("ReferenceError", "TypeError", "Binding loop")), result.stderr
    assert requests == [("GET", "/api/hardware", None), ("PATCH", "/api/hardware", {"device": "rtx4080", "component": "none"})]
    evidence = os.environ.get("OBSIDIENCE_AI_VOICE_EVIDENCE")
    if evidence:
        destination = Path(evidence) / str(width)
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(tmp_path / "ai-voice.png", destination / "ai-voice.png")
        (destination / "native-load.log").write_text(result.stdout + result.stderr)
