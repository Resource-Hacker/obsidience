"""Hardware shares the ordinary module lifecycle and canonical shell theme."""

import json
from pathlib import Path
import re
import subprocess


WORKSPACE = Path(__file__).parents[1] / 'shell/qml/workspace'


def test_hardware_button_uses_the_existing_pane_lifecycle_and_saved_placement():
    workspace = (WORKSPACE / 'PaneWorkspace.qml').read_text()
    launcher = (WORKSPACE / 'PaneLauncher.qml').read_text()
    functions = '\n'.join(re.findall(r'^    function \w+\([^\n]*\) \{.*?^    \}', launcher, re.M | re.S))
    program = r'''
import {strict as assert} from 'node:assert';
import vm from 'node:vm';
const opened=[],closed=[];
const placement={paneId:'hardware',surfaceId:'usb-c',open:false,x:180,y:100,width:1120,height:860,dismiss(){closed.push(this.paneId)}};
const state={surfaceId:'usb-c',currentSurface:{logical_width:1920,logical_height:1200},
 dockLayout:{isDocked(){return false}},presentRequested(...args){opened.push(args)},
 shellApi:{surfaceLayout:{clampPaneX(surface,width,x){return x},clampPaneY(surface,height,y){return y}}}};
state.root=state;vm.createContext(state);
''' + f'vm.runInContext({json.dumps(functions)},state);\n' + r'''
state.togglePane({placement});assert.equal(opened.length,1);assert.equal(opened[0][0],placement);
placement.open=true;state.togglePane({placement});assert.deepEqual(closed,['hardware']);
assert.equal(state.paneIsLocal({placement}),true);
placement.surfaceId='samsung';assert.equal(state.paneIsLocal({placement}),false);
'''
    result = subprocess.run(['node', '--input-type=module', '-e', program], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'shellTheme: root.shellApi.theme' in workspace
    assert 'monitoringAllowed: root.monitoringAllowed' in workspace
    assert 'monitoringAllowed: !root.lockController.active' in (WORKSPACE.parent / 'shell.qml').read_text()
    assert 'paneId: "hardware"' in workspace
    assert '"label": "Hardware", "title": "Hardware", "icon": "hardware", "accent": "#fbbf24"' in workspace
    assert 'com.tmog.taskmanager' not in workspace + launcher
