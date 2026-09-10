"""Native monitor samples only while visible and renders real gaps and unavailable data."""

import json
from pathlib import Path
import re
import subprocess

import pytest


FOLDER = Path(__file__).parents[1] / "shell/qml/panes/hardware"
SOURCE = FOLDER / "HardwarePane.qml"


def sample(sample_id="first"):
    return {
        "schema": "obsidience.hardware-monitor.v1", "sample_id": sample_id,
        "captured_at": "2026-09-09T20:00:00Z", "interval_seconds": 2,
        "cpu": {"utilization_percent": 18.5, "threads": 32, "physical_cores": 16,
                "temperature_c": 47, "clock_core_mhz": 3600, "load_1m": 2.1, "load_5m": 2.4, "load_15m": 2.7,
                "per_core_percent": [0, 10, 20, None] * 8},
        "memory": {"used_percent": 42, "used_bytes": 28_000_000_000, "total_bytes": 64_000_000_000,
                   "available_bytes": 36_000_000_000, "cached_bytes": 4_000_000_000,
                   "swap_total_bytes": 0, "swap_used_bytes": 0},
        "gpus": [{"device": "gpu-a", "name": "Example GPU", "status": "online", "utilization_percent": 33,
                  "memory_used_mib": 8000, "memory_total_mib": 24000, "temperature_c": 42,
                  "power_w": 63, "clock_core_mhz": 1000, "fan_percent": 0,
                  "memory_controller_percent": 20, "encoder_percent": 0, "decoder_percent": 2},
                 {"device": "gpu-b", "name": "Unavailable GPU", "status": "unavailable"}],
        "storage": {"devices": [{"id": "disk:example", "name": "Example device", "read_bytes_per_second": 102400,
                                  "write_bytes_per_second": 4096, "io_busy_percent": 2}],
                    "filesystems": [{"id": "fs:example", "source": "/dev/example", "mount_points": ["/home", "/var/lib/ai"],
                                     "filesystem": "btrfs", "used_percent": 55, "used_bytes": 550_000_000_000,
                                     "total_bytes": 1_000_000_000_000, "available_bytes": 450_000_000_000}], "locations": []},
        "network": [{"id": "ethernet0", "is_physical": True, "state": "up", "speed_mbps": 1000,
                     "received_bytes_per_second": None, "sent_bytes_per_second": 10240,
                     "total_received_bytes": 4096000, "total_sent_bytes": 1024000}],
        "processes": [{"pid": 100, "started_at": 1700000000, "name": "example-process", "cpu_percent": 12.5, "memory_bytes": 1_000_000},
                      {"pid": 200, "started_at": 1700000050, "name": "new-process", "cpu_percent": None, "memory_bytes": 128000}],
        "problems": [],
    }


def run_js(body, source=SOURCE, setup=""):
    functions = "\n".join(re.findall(r"^    function \w+\([^\n]*\) \{.*?^    \}", source.read_text(), re.M | re.S))
    code = r"""
import {strict as assert} from 'node:assert';
import vm from 'node:vm';
const requests=[];
class Request {
 static DONE=4;
 open(method,url){this.method=method;this.url=url;}
 send(body){this.body=body;requests.push(this);}
 abort(){this.aborted=true;}
 respond(status,payload){this.readyState=4;this.status=status;this.responseText=JSON.stringify(payload);this.onreadystatechange();}
}
const state={apiBase:'http://isolated',XMLHttpRequest:Request,visible:true,disposing:false,monitorActive:true,
 snapshot:null,history:[],historyGap:false,loading:false,errorMessage:'',requestGeneration:0,activeRequest:null,
 WebSocket:{Open:1},shellSocket:{status:1,sent:[],sendTextMessage(value){this.sent.push(JSON.parse(value))}}};
state.root=state;vm.createContext(state);
""" + f"vm.runInContext({json.dumps(functions)},state);\nconst original={json.dumps(sample())};\n" + setup + "\n" + body
    result = subprocess.run(["node", "--input-type=module", "-e", code], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


def test_monitor_reads_are_single_flight_abortable_and_never_mutate_hardware():
    run_js(r"""
state.monitorActive=false;state.refresh();assert.equal(requests.length,0);
state.monitorActive=true;state.refresh();state.refresh();assert.equal(requests.length,1);
assert.equal(requests[0].method,'GET');assert.equal(requests[0].url,'http://isolated/api/hardware/monitor');
state.stopRequest();assert(requests[0].aborted);requests[0].respond(200,original);assert.equal(state.snapshot,null);
state.refresh();requests[1].respond(200,original);assert.equal(state.loading,false);assert.equal(state.snapshot.sample_id,'first');
state.refresh();requests[2].respond(503,{});assert.equal(state.snapshot.sample_id,'first');assert(state.historyGap);
assert.match(state.errorMessage,/Last reading retained/);assert(requests.every(r=>r.method==='GET'&&!r.body));
state.showSettings();assert.deepEqual(state.shellSocket.sent[0].selection,{kind:'settings',section:'ai-voice'});
""")


def test_history_is_bounded_distinct_samples_preserve_nulls_and_break_after_gaps():
    run_js(r"""
state.applySnapshot(original);state.applySnapshot(original);assert.equal(state.history.length,1);
assert.equal(state.series('receive:ethernet0')[0],null);assert.equal(state.series('gpu:gpu-b')[0],null);
state.historyGap=true;state.applySnapshot({...original,sample_id:'second'});
assert.equal(state.history.length,3);assert.equal(state.history[1].values,null);
for(let i=0;i<150;i++) state.applySnapshot({...original,sample_id:'sample-'+i,captured_at:new Date(Date.parse(original.captured_at)+i*2000).toISOString()});
assert.equal(state.history.length,120);
state.applySnapshot({...original,sample_id:'after-sleep',captured_at:'2026-09-09T20:10:00Z'});
assert.equal(state.history.length,120);assert.equal(state.history.at(-2).values,null);
assert.equal(state.percent(null),'Unavailable');assert.equal(state.rate(null),'Awaiting rate');assert.equal(state.bytes(0),'0 B');
assert.throws(()=>state.applySnapshot({...original,processes:null}));assert.equal(state.snapshot.sample_id,'after-sleep');
""")


def test_aggregate_rates_preserve_gaps_until_every_device_has_a_reading():
    run_js(r"""
for(const unavailable of [null,undefined,NaN]) {
 const reading=JSON.parse(JSON.stringify(original));reading.sample_id='incomplete-'+String(unavailable);
 reading.storage.devices=[{read_bytes_per_second:100,write_bytes_per_second:50},{read_bytes_per_second:unavailable,write_bytes_per_second:0}];
 reading.network=[{id:'a',is_physical:true,received_bytes_per_second:100,sent_bytes_per_second:50},{id:'b',is_physical:true,received_bytes_per_second:0,sent_bytes_per_second:unavailable}];
 state.applySnapshot(reading);
 assert.equal(state.series('disk-read').at(-1),null);assert.equal(state.series('disk-write').at(-1),50);
 assert.equal(state.series('net-receive').at(-1),100);assert.equal(state.series('net-send').at(-1),null);
 assert.equal(state.rate(state.sum(reading.storage.devices,'read_bytes_per_second')),'Awaiting rate');
}
assert.equal(state.sum([],'rate'),null);
assert.equal(state.sum([{rate:0},{rate:0}],'rate'),0);
assert.equal(state.sum([{rate:100},{rate:200}],'rate'),300);
""")


def test_trend_does_not_connect_null_samples_or_invent_missing_points():
    run_js(r"""
state.values=[null,10,20,null,40,null];state.maximum=100;
let segments=state.segments();assert.equal(segments.length,2);assert.equal(segments[0].length,2);assert.equal(segments[1].length,1);
assert.equal(segments[0][0].y,.9);assert.equal(segments[1][0].y,.6);
state.values=[null,null];assert.equal(state.segments().length,0);
state.values=[0,2048];state.maximum=0;segments=state.segments();assert.equal(segments[0][0].y,1);assert.equal(segments[0][1].y,0);
""", source=FOLDER / "MonitorTrend.qml")


def test_summary_counts_only_physical_network_and_gpu_details_show_supported_metrics():
    run_js(r"""
const reading=JSON.parse(JSON.stringify(original));
reading.network=[{id:'eth0',is_physical:true,received_bytes_per_second:100,sent_bytes_per_second:50},
 {id:'lo',is_physical:false,received_bytes_per_second:900,sent_bytes_per_second:900},
 {id:'virtual',is_physical:false,received_bytes_per_second:null,sent_bytes_per_second:null}];
state.applySnapshot(reading);
assert.equal(state.series('net-receive').at(-1),100);assert.equal(state.series('net-send').at(-1),50);
assert.equal(state.series('receive:lo').at(-1),900);assert.equal(state.series('receive:virtual').at(-1),null);
assert.equal(state.series('disk-read:disk:example').at(-1),102400);
const rows=state.gpuReadings({status:'online',clock_core_mhz:1000,power_w:0,fan_percent:null});
assert(rows.some(row=>row.label==='Power'&&row.value==='0 W'));
assert(rows.some(row=>row.label==='Core clock'&&row.value==='1000 MHz'));
assert(!rows.some(row=>row.label==='Fan'||row.label==='Video encode'||row.value==='Unavailable'));
assert.equal(state.rateScale([null,1024,0]),'1.0 KiB/s');
""")


@pytest.mark.parametrize("width", [586, 634, 1160])
def test_native_monitor_sections_nulls_and_hidden_window_stop_sampling(tmp_path, width):
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
            requests.append(self.path)
            self.send_response(200)
            self.end_headers()
            payload = sample("cached-sample")
            payload["gpus"].append({"device": "gpu-c", "name": "Integrated GPU", "status": "online", "utilization_percent": 5})
            payload["storage"]["devices"].extend({"id": f"disk:extra{index}", "name": f"Extra disk {index}", "read_bytes_per_second": 0, "write_bytes_per_second": 0} for index in range(3))
            payload["network"].extend({"id": f"virtual{index}", "state": "up", "is_physical": False, "received_bytes_per_second": 0, "sent_bytes_per_second": 0} for index in range(16))
            self.wfile.write(json.dumps(payload).encode())

        def log_message(self, *_args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    visual = json.dumps((FOLDER.parents[1] / "components/visual").resolve().as_uri())
    for source in FOLDER.glob("*.qml"):
        text = source.read_text().replace('import "../../components/visual"', "import " + visual)
        text = text.replace('active: root.visible', 'active: false')
        (tmp_path / source.name).write_text(text)
    fixture = r"""
import QtQuick
import QtQuick.Window
Window {
 id: win
 width: WIDTH; height: 702; visible:true; color:'#030a10'
 property int stage:0
 property int lastCapture:-1
 property bool capturing:false
 property bool seededHistory:false
 property int initialGeneration:0
 property var names:['overview','cpu','memory','gpus','storage','network','processes']
 QtObject {
  id: theme
  property color surface:'#eb030a10'
  property color inactiveSurface:'#f002080e'
  property color separator:'#2667e8f9'
  property color strongAccent:'#6667e8f9'
  property color text:'#cffafe'
  property color muted:'#9967e8f9'
  property color selection:'#102a36'
  property color hover:'#1a67e8f9'
 }
 HardwarePane { id:pane; anchors.fill:parent; shellTheme:theme; apiBase:API_BASE }
 function findObject(parent,name) {
  if(parent.objectName===name)return parent
  for(const child of parent.children||[]){const found=findObject(child,name);if(found)return found}
  return null
 }
 Timer {
  interval:160;repeat:true;running:true
  onTriggered:{
   if(capturing||pane.loading||!pane.snapshot)return
   if(!seededHistory){
    const original=JSON.parse(JSON.stringify(pane.snapshot))
    for(let index=0;index<80;index++){
     const reading=JSON.parse(JSON.stringify(original));reading.sample_id=index===79?original.sample_id:'fixture-'+index
     reading.captured_at=new Date(Date.parse(original.captured_at)+(index-79)*2000).toISOString()
     reading.cpu.utilization_percent=index>37&&index<42?null:10+(index%18)
     reading.memory.used_percent=35+index/12
     pane.applySnapshot(reading)
    }
    seededHistory=true;return
   }
   if(stage<names.length){
    if(lastCapture!==stage){
     findObject(pane,'hardware-nav-'+names[stage]).clicked();lastCapture=stage;return
    }
    const heading=findObject(pane,'hardware-section-title')
    const link=findObject(pane,'hardware-ai-voice-settings')
    if(!heading||heading.width<80||link.mapToItem(pane,link.width,link.height).x>pane.width||link.mapToItem(pane,0,link.height).y>pane.height){Qt.exit(20);return}
    if(names[stage]==='processes'&&!findObject(pane,'hardware-process-100-1700000000')){Qt.exit(21);return}
    if(names[stage]==='overview'){
     const cpu=findObject(pane,'hardware-summary-cpu-plot'),memory=findObject(pane,'hardware-summary-memory-plot')
     if(win.width<1000&&!findObject(pane,'hardware-summary-top-processes').visible){Qt.exit(31);return}
     if(cpu.width<180||memory.mapToItem(pane,0,memory.height).y>link.mapToItem(pane,0,0).y){Qt.exit(25);return}
    }
    if(names[stage]==='gpus'){
     findObject(pane,'hardware-device-gpu-b').clicked()
     if(pane.selectedGpu.device!=='gpu-b'||pane.sectionTitle!=='Unavailable GPU'){Qt.exit(26);return}
     findObject(pane,'hardware-device-gpu-a').clicked()
    }
    if(names[stage]==='storage'){
     findObject(pane,'hardware-device-disk:example').clicked()
     if(!pane.selectedDisk||pane.selectedDisk.id!=='disk:example'){Qt.exit(27);return}
    }
    if(names[stage]==='network'){
     findObject(pane,'hardware-device-ethernet0').clicked()
     if(pane.selectedNetwork.id!=='ethernet0'){Qt.exit(28);return}
     const navigation=findObject(pane,'hardware-navigation')
     if(navigation.contentItem.contentHeight<=navigation.height){Qt.exit(29);return}
     navigation.contentItem.contentY=navigation.contentItem.contentHeight-navigation.height
     findObject(pane,'hardware-device-virtual15').clicked()
     if(pane.selectedNetwork.id!=='virtual15'){Qt.exit(30);return}
     navigation.contentItem.contentY=0
     findObject(pane,'hardware-device-ethernet0').clicked()
    }
    capturing=true
    pane.grabToImage(result=>{result.saveToFile(IMAGE_ROOT+'/'+names[stage]+'.png');capturing=false;stage++})
   }else if(stage===7){
    const empty=JSON.parse(JSON.stringify(pane.snapshot));empty.sample_id='empty';empty.cpu={per_core_percent:[]};empty.memory={};empty.gpus=[];empty.storage={};empty.network=[];empty.processes=[];empty.problems=[{component:'gpu',message:'Sensors unavailable'}]
    pane.applySnapshot(empty);pane.activeSection='overview';stage++;return
   }else if(stage===8){
    capturing=true
    pane.grabToImage(result=>{result.saveToFile(IMAGE_ROOT+'/empty.png');capturing=false;win.visible=false;initialGeneration=pane.requestGeneration;hiddenWait.start();stage++})
   }
  }
 }
 Timer {
  id:hiddenWait;interval:2400
  onTriggered:{
   if(pane.monitorActive||pane.loading||pane.requestGeneration!==initialGeneration){Qt.exit(22);return}
   pane.monitoringAllowed=false;win.visible=true;blockedWait.start()
  }
 }
 Timer { id:blockedWait;interval:300;onTriggered:{if(pane.monitorActive||pane.requestGeneration!==initialGeneration){Qt.exit(23);return}Qt.quit()} }
 Timer { interval:9000;running:true;onTriggered:{console.log('Monitor fixture timeout',stage);Qt.exit(24)} }
}
""".replace("WIDTH", str(width)).replace("API_BASE", json.dumps(f"http://127.0.0.1:{server.server_port}"))
    fixture = fixture.replace("IMAGE_ROOT", json.dumps(str(tmp_path)))
    (tmp_path / "fixture.qml").write_text(fixture)
    environment = os.environ.copy()
    environment.update(QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software", QT_QUICK_CONTROLS_STYLE="Basic", QT_FORCE_STDERR_LOGGING="1")
    try:
        result = subprocess.run([qml, str(tmp_path / "fixture.qml")], env=environment, capture_output=True, text=True, timeout=12)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    assert result.returncode == 0, result.stdout + result.stderr + repr(requests)
    assert not any(error in result.stderr for error in ("ReferenceError", "TypeError", "Binding loop")), result.stderr
    assert requests and all(path == "/api/hardware/monitor" for path in requests)
    assert len(requests) <= 3, requests
    evidence = os.environ.get("OBSIDIENCE_HARDWARE_EVIDENCE")
    if evidence:
        destination = Path(evidence) / str(width)
        destination.mkdir(parents=True, exist_ok=True)
        for picture in tmp_path.glob("*.png"):
            shutil.copy2(picture, destination / picture.name)
        (destination / "native-load.log").write_text(result.stdout + result.stderr)
