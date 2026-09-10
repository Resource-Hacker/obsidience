"""Settings navigation has one Shell owner and replay-safe section revisions."""

import json
from pathlib import Path
import re
import subprocess


QML = Path(__file__).parents[1] / "shell/qml"
SETTINGS = QML / "panes/settings/SettingsPane.qml"
SERVER = QML / "api/ShellCommandServer.qml"


def run_navigation(body):
    pane_source = SETTINGS.read_text()
    server_source = SERVER.read_text()

    def functions(source):
        return "\n".join(re.findall(r"^    function \w+\([^\n]*\) \{.*?^    \}", source, re.M | re.S))

    sections = re.search(r"readonly property var sections: (\[[\s\S]*?^    \])", pane_source, re.M)[1]
    initial_selection = re.search(r"property var settingsSelection: ([^\n]+)", server_source)[1]
    tab_click = re.search(r"onClicked: ([^\n]*sectionButton[^\n]*)", pane_source)[1]
    program = r"""
import {strict as assert} from 'node:assert';
import vm from 'node:vm';
const commands=[],events=[],presentations=[];
const copy=value=>JSON.parse(JSON.stringify(value));
const pane={activeSection:'graph',selectionRevision:-1,WebSocket:{Open:1},
    settingsSocket:{status:1,sendTextMessage(text){commands.push(text)}}};
pane.root=pane;vm.createContext(pane);
const placement={paneId:'settings',surfaceId:'usb-c'};
const host={commandSchema:'obsidience.shell.command.v1',eventSchema:'obsidience.shell.event.v1',
    subprotocol:'obsidience.shell.v1',WebSocket:{Open:1,Closed:0,Error:3},
    settingsSelectionRevision:0,placementAllowed:true,clients:[],graphStates:{},windowStates:{},selectedGraphId:'main'};
host.root=host;vm.createContext(host);
""" + f"""
pane.sections=vm.runInContext({json.dumps(sections)},pane);
host.settingsSelection=vm.runInContext({json.dumps(initial_selection)},host);
vm.runInContext({json.dumps(functions(pane_source))},pane);
vm.runInContext({json.dumps(functions(server_source))},host);
const tabClick={json.dumps(tab_click)};
""" + r"""
host.placementFor=id=>id==='settings'?placement:null;
host.presentPlacementOnSurface=(target,surface)=>{presentations.push([target.paneId,surface]);return host.placementAllowed};
host.broadcast=event=>events.push(copy(event));
for(const name of ['readerState','knowledgeState','graphDisplayState','workspaceState','dockState'])host[name]=()=>({type:name});
function command(section,selectionExtra={}) {
    return {schema:host.commandSchema,type:'pane.present',pane_id:'settings',
        selection:{kind:'settings',section,...selectionExtra}};
}
function present(section,extra={}) {host.handleCommand(null,JSON.stringify(command(section,extra)))}
function deliver(event) {pane.applyShellEvent(JSON.stringify(event))}
function clickTab(section) {
    pane.sectionButton={modelData:{id:section}};
    vm.runInContext(tabClick,pane);
}
""" + body
    result = subprocess.run(["node", "--input-type=module", "-e", program], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr


def test_manual_navigation_survives_replay_and_fresh_external_navigation_still_works():
    run_navigation(r"""
deliver(host.settingsState());assert.equal(pane.activeSection,'graph');assert.equal(pane.selectionRevision,0);
present('connections');const oldConnections=events.at(-1);deliver(oldConnections);
assert.equal(pane.activeSection,'connections');assert.equal(pane.selectionRevision,1);
clickTab('ai-voice');
assert.equal(commands.length,1);
assert.deepEqual(JSON.parse(commands[0]),command('ai-voice'));
assert.equal(pane.activeSection,'connections'); // Only the owner commits navigation.
deliver(oldConnections);host.handleCommand(null,commands.shift());deliver(events.at(-1));
assert.equal(pane.activeSection,'ai-voice');assert.equal(pane.selectionRevision,2);
deliver(oldConnections);deliver({...oldConnections,revision:2});
assert.equal(pane.activeSection,'ai-voice');assert.equal(pane.selectionRevision,2);
const replay=[];
host.acceptClient({status:1,negotiatedSubprotocol:host.subprotocol,
    textMessageReceived:{connect(){}},statusChanged:{connect(){}},sendTextMessage(text){replay.push(JSON.parse(text))}});
const settingsReplay=replay.find(event=>event.type==='pane.selection');
assert.deepEqual(settingsReplay,copy(host.settingsState()));deliver(settingsReplay);
assert.equal(pane.activeSection,'ai-voice');assert.equal(commands.length,0); // No echo loop.
present('connections');deliver(events.at(-1));assert.equal(pane.activeSection,'connections');
assert.equal(pane.selectionRevision,3);
present('connections');deliver(events.at(-1));assert.equal(pane.selectionRevision,4);
assert.equal(presentations.length,4);
assert(presentations.every(([id,surface])=>id==='settings'&&surface==='usb-c'));
""")


def test_owner_accepts_only_known_sections_and_projects_only_selection_fields():
    run_navigation(r"""
for(const section of ['graph','input','workspace','connections','ai-voice']) {
    present(section,{extra:'must not be relayed'});
    assert.deepEqual(copy(host.settingsSelection),{kind:'settings',section});
    deliver(events.at(-1));assert.equal(pane.activeSection,section);
}
assert.equal(host.settingsSelectionRevision,5);
for(const section of [null,undefined,{},[],true,42,'','AI & Voice','ai_voice',' connections','graph\u0000','x'.repeat(10000)])present(section);
host.handleCommand(null,JSON.stringify({...command('graph'),schema:'wrong'}));
host.handleCommand(null,JSON.stringify(command('graph',{kind:'source'})));
assert.equal(host.settingsSelectionRevision,5);assert.equal(events.length,5);
assert.equal(presentations.length,5);assert.equal(pane.activeSection,'ai-voice');
assert.equal(commands.length,0);
""")


def test_client_rejects_invalid_or_stale_snapshots_without_consuming_a_revision():
    run_navigation(r"""
present('ai-voice');deliver(events.at(-1));const valid=copy(host.settingsState());
for(const event of [null,{},[],{...valid,schema:'wrong'},{...valid,type:'pane.state'},
    {...valid,pane_id:'reader'},{...valid,revision:undefined},{...valid,revision:null},
    {...valid,revision:true},{...valid,revision:-1},{...valid,revision:1.5},
    {...valid,revision:1e20},{...valid,revision:2,selection:null},
    {...valid,revision:2,selection:{kind:'settings',section:'unknown'}},
    {...valid,revision:2,selection:{kind:'article',section:'graph'}}])deliver(event);
pane.applyShellEvent('{invalid');pane.applyShellEvent('x'.repeat(65537));
assert.equal(pane.activeSection,'ai-voice');assert.equal(pane.selectionRevision,1);
present('workspace');deliver(events.at(-1));assert.equal(pane.activeSection,'workspace');
assert.equal(pane.selectionRevision,2);assert.equal(commands.length,0);
""")


def test_unavailable_transport_or_placement_does_not_commit_navigation():
    run_navigation(r"""
deliver(host.settingsState());pane.settingsSocket.status=0;clickTab('ai-voice');
assert.equal(commands.length,0);assert.equal(pane.activeSection,'graph');
pane.settingsSocket.status=1;clickTab('unknown');assert.equal(commands.length,0);
clickTab('ai-voice');assert.equal(commands.length,1);host.placementAllowed=false;
host.handleCommand(null,commands.shift());
assert.equal(host.settingsSelection.section,'graph');assert.equal(host.settingsSelectionRevision,0);
assert.equal(events.length,0);assert.equal(pane.activeSection,'graph');
""")


def test_native_settings_navigation_round_trips_through_the_owner(tmp_path):
    import asyncio
    import os
    import shutil

    import pytest
    import websockets

    qml = shutil.which("qml6")
    if qml is None:
        pytest.skip("qml6 is not installed")
    for directory, component in (
        ("graph", "GraphSettings"), ("input", "InputSettings"),
        ("workspace", "WorkspaceSettings"), ("connections", "ConnectionsSettings"),
        ("ai_voice", "AiVoiceSettings"),
    ):
        target = tmp_path / directory
        target.mkdir()
        (target / (component + ".qml")).write_text("import QtQuick\nItem {}\n")
    (tmp_path / "fixture.qml").write_text("""
import QtQuick
import QtQuick.Window
Window {
    width: 720; height: 520; visible: true
    property int stage: 0
    SettingsPane { id: pane; anchors.fill: parent }
    Timer {
        interval: 20; repeat: true; running: true
        onTriggered: {
            if (pane.selectionRevision < 0) return
            if (stage === 0) {
                if (pane.activeSection !== "graph") { Qt.exit(20); return }
                pane.selectSection("ai-voice")
                stage = 1
            } else if (stage === 1 && pane.selectionRevision === 1) {
                if (pane.activeSection !== "ai-voice") { Qt.exit(21); return }
                pane.selectSection("connections")
                stage = 2
            } else if (stage === 2 && pane.selectionRevision === 2) {
                if (pane.activeSection !== "connections") { Qt.exit(22); return }
                Qt.quit()
            }
        }
    }
    Timer { interval: 5000; running: true; onTriggered: Qt.exit(23) }
}
""")

    async def exercise():
        commands = []
        failures = []

        def snapshot(section, revision):
            return json.dumps({
                "schema": "obsidience.shell.event.v1", "type": "pane.selection",
                "pane_id": "settings", "revision": revision,
                "selection": {"kind": "settings", "section": section},
            })

        async def handle(socket):
            try:
                await socket.send(snapshot("graph", 0))
                async for message in socket:
                    command = json.loads(message)
                    commands.append(command)
                    assert command["schema"] == "obsidience.shell.command.v1"
                    assert command["type"] == "pane.present"
                    assert command["pane_id"] == "settings"
                    assert command["selection"]["kind"] == "settings"
                    await socket.send(snapshot(command["selection"]["section"], len(commands)))
                    await socket.send(snapshot("graph", 0))
            except Exception as error:
                failures.append(repr(error))

        async with websockets.serve(
            handle, "127.0.0.1", 0, subprotocols=["obsidience.shell.v1"]
        ) as server:
            port = server.sockets[0].getsockname()[1]
            (tmp_path / "SettingsPane.qml").write_text(
                SETTINGS.read_text().replace("ws://127.0.0.1:8768", f"ws://127.0.0.1:{port}")
            )
            environment = os.environ.copy()
            environment.update(
                QT_QPA_PLATFORM="offscreen", QT_QUICK_BACKEND="software",
                QT_QUICK_CONTROLS_STYLE="Basic",
            )
            process = await asyncio.create_subprocess_exec(
                qml, str(tmp_path / "fixture.qml"), env=environment,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=8)
            except TimeoutError:
                process.kill()
                await process.communicate()
                raise
            output = stdout.decode() + stderr.decode()
            assert process.returncode == 0, output
            assert not any(error in output for error in ("ReferenceError", "TypeError", "Binding loop")), output
            assert failures == []
            assert [command["selection"]["section"] for command in commands] == ["ai-voice", "connections"]

    asyncio.run(exercise())
