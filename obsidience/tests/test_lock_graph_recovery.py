"""Lock graph recovery uses actual QML callbacks with no desktop or network."""

import json
from pathlib import Path
import re
import subprocess

import pytest


QML = Path(__file__).parents[1] / "shell/qml/lock/LockSurface.qml"


def _recovery_script() -> str:
    source = QML.read_text()
    function = re.search(
        r"^                function recoverFailedPage\(\) \{.*?^                \}",
        source, re.S | re.M,
    ).group(0)
    connected = re.search(
        r"^                onBackendConnectedChanged: \{(.*?)^                \}",
        source, re.S | re.M,
    ).group(1)
    loading = re.search(
        r"^                onLoadingChanged: info => \{(.*?)^                \}",
        source, re.S | re.M,
    ).group(1)
    binding = re.search(
        r"readonly property bool backendConnected:\s*([^\n]+)", source,
    ).group(1)
    defaults = {
        name: value == "true"
        for name, value in re.findall(
            r"property bool (loadFailed|recoveryAttempted): (true|false)", source,
        )
    }
    assert set(defaults) == {"loadFailed", "recoveryAttempted"}
    callbacks = (
        function + "\nfunction connectionChanged() {" + connected + "}\n"
        + "function loadingChanged(info) {" + loading + "}\n"
    )
    return r"""
const assert = require('node:assert/strict'), vm = require('node:vm');
const pending = [], reloads = [];
const realtime = {connected: false, state: {enabled: false, ready: false}};
const controller = {
    shellApi: {realtime}, secure: true, password: 'untouched',
    tryUnlock: () => {throw new Error('Graph recovery must not unlock');}
};
const lockBefore = JSON.stringify({secure: controller.secure, password: controller.password});
const context = {
    ...DEFAULTS, root: {controller}, loading: false,
    WebEngineView: {LoadStartedStatus: 0, LoadStoppedStatus: 1,
        LoadSucceededStatus: 2, LoadFailedStatus: 3},
    // Do not coalesce callbacks: duplicate deferred events must remain safe.
    Qt: {callLater: callback => pending.push(callback)},
    // Deliberately do not set loading immediately; test the pre-reload guard.
    reload: () => reloads.push({failed: context.loadFailed, connected: context.backendConnected})
};
vm.createContext(context);
Object.defineProperty(context, 'backendConnected', {
    get: () => vm.runInContext(BINDING, context)
});
vm.runInContext(CALLBACKS, context);
const connect = value => {
    assert.notEqual(realtime.connected, value, 'Simulate actual property transitions');
    realtime.connected = value;
    context.connectionChanged();
};
const status = name => context.loadingChanged({status: context.WebEngineView[name]});
const flush = () => {
    let count = 0;
    while (pending.length) {
        assert(++count <= 16, 'Deferred recovery must not create a retry loop');
        pending.shift()();
    }
};
""".replace("DEFAULTS", json.dumps(defaults)).replace(
        "BINDING", json.dumps(binding),
    ).replace("CALLBACKS", json.dumps(callbacks))


@pytest.mark.parametrize("scenario", [
    pytest.param(r"""
        context.loading = true;
        status('LoadFailedStatus');
        assert.equal(context.loadFailed, true);
        context.loading = false;
        flush();
        assert.equal(reloads.length, 0);
        connect(true);
        assert.equal(reloads.length, 0); // Recovery is deferred.
        flush();
        assert.equal(reloads.length, 1);
    """, id="failed-offline-then-reconnected"),
    pytest.param(r"""
        context.loading = true;
        connect(true);
        flush(); // The connection edge arrived before the failure.
        assert.equal(reloads.length, 0);
        status('LoadFailedStatus');
        context.loading = false; // Qt may update this after the status callback.
        flush();
        assert.equal(reloads.length, 1);
    """, id="reconnected-before-inflight-failure"),
    pytest.param(r"""
        connect(true);
        status('LoadFailedStatus');
        assert.equal(pending.length, 2);
        flush();
        assert.equal(reloads.length, 1);
        assert.equal(context.recoveryAttempted, true);
        status('LoadStartedStatus');
        for (let i = 0; i < 3; i++) status('LoadFailedStatus');
        flush();
        assert.equal(reloads.length, 1); // Failure cannot rearm itself.
    """, id="coincident-edges-and-failed-retry-do-not-loop"),
    pytest.param(r"""
        connect(true); status('LoadFailedStatus'); flush();
        assert.equal(reloads.length, 1);
        context.loading = true;
        connect(false);
        assert.equal(context.recoveryAttempted, false);
        connect(true); flush();
        assert.equal(reloads.length, 1);
        status('LoadStartedStatus'); // Must not consume the new connected interval.
        status('LoadFailedStatus'); context.loading = false; flush();
        assert.equal(reloads.length, 2);
        status('LoadFailedStatus'); flush();
        assert.equal(reloads.length, 2);
    """, id="new-connection-rearms-while-prior-retry-is-inflight"),
    pytest.param(r"""
        connect(true); status('LoadSucceededStatus'); flush();
        connect(false); connect(true); flush();
        assert.equal(reloads.length, 0);
        assert.equal(context.loadFailed, false);
    """, id="working-page-kept-across-backend-reconnect"),
    pytest.param(r"""
        connect(true); status('LoadFailedStatus');
        status('LoadSucceededStatus'); // Success wins before deferred dispatch.
        flush();
        assert.equal(reloads.length, 0);
        assert.equal(context.loadFailed, false);
        assert.equal(context.recoveryAttempted, false);
    """, id="deferred-callback-rechecks-success"),
    pytest.param(r"""
        connect(true); status('LoadFailedStatus'); connect(false); flush();
        assert.equal(reloads.length, 0);
        assert.equal(context.recoveryAttempted, false);
        connect(true); flush();
        assert.equal(reloads.length, 1);
    """, id="deferred-callback-rechecks-disconnection"),
    pytest.param(r"""
        connect(true); status('LoadFailedStatus');
        context.loading = true; status('LoadStartedStatus'); flush();
        assert.equal(reloads.length, 0);
        assert.equal(context.recoveryAttempted, false);
        context.loading = false; status('LoadFailedStatus'); flush();
        assert.equal(reloads.length, 1);
    """, id="deferred-callback-rechecks-inflight-navigation"),
    pytest.param(r"""
        connect(true); status('LoadFailedStatus'); flush();
        status('LoadSucceededStatus'); flush();
        assert.equal(context.loadFailed, false);
        // Success restores the graph but does not permit another same-interval retry.
        status('LoadStartedStatus'); status('LoadFailedStatus'); flush();
        assert.equal(reloads.length, 1);
        connect(false); connect(true); flush();
        assert.equal(reloads.length, 2);
    """, id="success-restores-visibility-without-rearming"),
    pytest.param(r"""
        connect(true); status('LoadStoppedStatus'); flush();
        assert.equal(reloads.length, 0);
        assert.equal(context.loadFailed, false);
    """, id="stopped-navigation-is-not-network-failure"),
])
def test_lock_graph_recovery_event_order(scenario):
    script = _recovery_script() + scenario + r"""
assert.equal(JSON.stringify({secure: controller.secure, password: controller.password}), lockBefore);
assert.equal(realtime.state.enabled, false); // Recovery does not require/start speech.
assert.equal(realtime.state.ready, false);
for (const attempt of reloads) assert(attempt.failed && attempt.connected);
"""
    result = subprocess.run(
        ["node", "-e", script], capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_lock_graph_failure_keeps_native_lock_and_existing_transport():
    source = QML.read_text()
    graph = re.search(
        r"^            WebEngineView \{.*?^            \}", source, re.S | re.M,
    ).group(0)
    assert "settings.errorPageEnabled: false" in graph
    assert "visible: !loadFailed" in graph
    assert "enabled: false" in graph and "focus: false" in graph
    assert "root.controller.shellApi.realtime.connected" in graph
    assert "Timer {" not in source and "WebSocket {" not in source
    assert "WlSessionLock {" not in source and "PamContext {" not in source
    assert 'color: "#02060c"' in source
    assert source.index("id: unlockPanel") > source.index("id: graphView")
    assert "echoMode: TextInput.Password" in source
    assert "inputMethodHints: Qt.ImhSensitiveData" in source
    assert "onAccepted: root.controller.tryUnlock()" in source
    assert "onClicked: root.controller.tryUnlock()" in source
