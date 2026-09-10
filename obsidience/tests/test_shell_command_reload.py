"""Development file edits cannot bypass the guarded host restart."""

import json
from pathlib import Path
import re
import subprocess


def test_shell_disables_automatic_generation_replacement_on_startup():
    qml = Path(__file__).parents[1] / "shell/qml"
    source = (qml / "shell.qml").read_text()
    callback = re.search(r"    Component\.onCompleted: ([^\n]+)", source).group(1)
    script = (
        "const vm=require('node:vm'),assert=require('node:assert/strict');"
        "const settings={Quickshell:{watchFiles:true}};vm.createContext(settings);"
        "vm.runInContext(" + json.dumps(callback) + ",settings);"
        "assert.equal(settings.Quickshell.watchFiles,false);"
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    command_server = (qml / "api/ShellCommandServer.qml").read_text()
    assert "rebindCommandServer" not in command_server
    assert "onReloadCompleted" not in command_server
