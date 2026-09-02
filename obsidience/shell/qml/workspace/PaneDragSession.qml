pragma ComponentBehavior: Bound

import QtQml
import QtWebSockets

QtObject {
    id: root

    required property string surfaceId

    readonly property string commandSchema: "obsidience.shell.command.v1"
    readonly property string eventSchema: "obsidience.shell.event.v1"
    readonly property bool active: token !== ""
    property string token: ""
    property string paneId: ""
    property string phase: "idle"
    property string sourceSurfaceId: ""
    property int expectedRevision: -1
    property int x: 0
    property int y: 0
    property int width: 0
    property int height: 0
    property int tokenCounter: 0

    signal placementAccepted(var record)

    function nextToken(pane) {
        tokenCounter += 1
        return surfaceId + "." + pane + "." + Date.now() + "." + tokenCounter
    }

    function send(command) {
        if (shellSocket.status !== WebSocket.Open) {
            return false
        }
        shellSocket.sendTextMessage(JSON.stringify(Object.assign({
            "schema": commandSchema
        }, command)))
        return true
    }

    function reset() {
        token = ""
        paneId = ""
        phase = "idle"
        sourceSurfaceId = ""
        expectedRevision = -1
        x = 0
        y = 0
        width = 0
        height = 0
    }

    function begin(pane, placement, startX, startY) {
        if (active || !placement || shellSocket.status !== WebSocket.Open) {
            return false
        }
        const next = nextToken(pane)
        paneId = pane
        phase = "local"
        sourceSurfaceId = placement.surfaceId
        expectedRevision = placement.revision
        x = typeof startX === "number" && isFinite(startX)
            ? Math.round(startX) : placement.x
        y = typeof startY === "number" && isFinite(startY)
            ? Math.round(startY) : placement.y
        width = placement.width
        height = placement.height
        token = next
        return true
    }

    function previewLocal(nextX, nextY) {
        if (phase !== "local") {
            return
        }
        x = Math.round(nextX)
        y = Math.round(nextY)
    }

    function finish(moved) {
        if (!active) {
            return
        }
        if (phase !== "local") {
            return
        }
        if (!moved) {
            reset()
            return
        }
        if (phase === "local") {
            if (send({
                "type": "pane.drag.commit",
                "token": token,
                "pane_id": paneId,
                "source_surface_id": sourceSurfaceId,
                "expected_revision": expectedRevision,
                "local_rect": {
                    "x": x,
                    "y": y,
                    "width": width,
                    "height": height
                }
            })) {
                phase = "committing"
            } else {
                reset()
            }
        }
    }

    function cancel() {
        reset()
    }

    function activatePane(placement) {
        if (!placement || placement.surfaceId !== surfaceId) {
            return false
        }
        return send({
            "type": "pane.activate",
            "pane_id": placement.paneId,
            "surface_id": placement.surfaceId,
            "expected_revision": placement.revision
        })
    }

    function deactivatePane(placement) {
        if (!placement || placement.surfaceId !== surfaceId) {
            return false
        }
        return send({
            "type": "pane.deactivate",
            "pane_id": placement.paneId,
            "surface_id": placement.surfaceId,
            "expected_revision": placement.revision
        })
    }

    function applyDragEvent(event) {
        if (!event || event.schema !== eventSchema
                || typeof event.type !== "string") {
            return
        }
        if ((event.type === "pane.drag.committed"
                || event.type === "pane.moved"
                || event.type === "pane.tiled") && event.pane) {
            placementAccepted(event.pane)
            if (event.token === token) {
                reset()
            }
            return
        }
        if (event.token !== token && active) {
            return
        }
        if (event.type === "pane.drag.failed") {
            if (event.token === token) {
                reset()
            }
            return
        }
    }

    function receiveMessage(message) {
        if (typeof message !== "string" || message.length > 16384) {
            return
        }
        try {
            applyDragEvent(JSON.parse(message))
        } catch (error) {
            // The existing shell socket carries unrelated bounded event types.
        }
    }

    property WebSocket shellSocket: WebSocket {
        id: shellSocket

        url: "ws://127.0.0.1:8768"
        requestedSubprotocols: ["obsidience.shell.v1"]
        active: true

        onTextMessageReceived: message => root.receiveMessage(message)
        onStatusChanged: status => {
            if (status === WebSocket.Open) {
                root.send({
                    "type": "pane.subscribe",
                    "surface_id": root.surfaceId
                })
            } else if (status === WebSocket.Closed || status === WebSocket.Error) {
                if (root.active) {
                    root.reset()
                }
                reconnectTimer.restart()
            }
        }
    }

    property Timer reconnectTimer: Timer {
        id: reconnectTimer

        interval: 500
        repeat: false
        onTriggered: {
            shellSocket.active = false
            shellSocket.active = true
        }
    }
}
