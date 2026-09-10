pragma ComponentBehavior: Bound

import QtQuick
import QtWebSockets

Item {
    id: root

    required property var hostDefinition
    required property var paneDefinitions
    required property PaneDockLayout dockLayout
    required property string surfaceId

    property string draggingModule: ""
    property string draggingSurface: ""

    clip: true

    function sendCommand(command) {
        if (shellSocket.status === WebSocket.Open) {
            shellSocket.sendTextMessage(JSON.stringify(command))
        }
    }

    function applyShellEvent(message) {
        if (typeof message !== "string" || message.length > 65536) {
            return
        }
        let event
        try {
            event = JSON.parse(message)
        } catch (error) {
            return
        }
        if (!event || event.schema !== "obsidience.shell.event.v1") {
            return
        }
        if (event.type === "pane.dock.state" && event.layout) {
            dockLayout.applyRecord(event.layout)
            return
        }
        if (event.type === "pane.dock.drag") {
            draggingModule = typeof event.pane_id === "string"
                ? event.pane_id : ""
            draggingSurface = typeof event.surface_id === "string"
                ? event.surface_id : ""
        }
    }

    WebSocket {
        id: shellSocket

        url: "ws://127.0.0.1:8768"
        requestedSubprotocols: ["obsidience.shell.v1"]
        active: true

        onTextMessageReceived: message => root.applyShellEvent(message)
        onStatusChanged: status => {
            if (status === WebSocket.Closed || status === WebSocket.Error) {
                reconnectTimer.restart()
            }
        }
    }

    Timer {
        id: reconnectTimer

        interval: 500
        repeat: false
        onTriggered: {
            shellSocket.active = false
            shellSocket.active = true
        }
    }

    PaneDockStack {
        id: leftStack

        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        side: "left"
        hostPaneId: root.hostDefinition.placement.paneId
        surfaceId: root.surfaceId
        dockLayout: root.dockLayout
        paneDefinitions: root.paneDefinitions
        availableWidth: root.width
        onCommandRequested: command => root.sendCommand(command)
    }

    Loader {
        id: hostContent

        anchors.left: leftStack.right
        anchors.right: rightStack.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        active: true
        sourceComponent: root.hostDefinition.component
    }

    PaneDockStack {
        id: rightStack

        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        side: "right"
        hostPaneId: root.hostDefinition.placement.paneId
        surfaceId: root.surfaceId
        dockLayout: root.dockLayout
        paneDefinitions: root.paneDefinitions
        availableWidth: root.width
        onCommandRequested: command => root.sendCommand(command)
    }

    Item {
        id: dockTargets

        anchors.fill: parent
        visible: root.draggingModule !== ""
            && root.draggingSurface === root.surfaceId
        z: 70

        Repeater {
            model: [
                {"side": "left", "position": "top", "label": "Dock left · top"},
                {"side": "left", "position": "bottom", "label": "Dock left · bottom"},
                {"side": "right", "position": "top", "label": "Dock right · top"},
                {"side": "right", "position": "bottom", "label": "Dock right · bottom"}
            ]

            delegate: Rectangle {
                id: target

                required property var modelData
                readonly property var occupant: {
                    const currentRevision = root.dockLayout.revision
                    return root.dockLayout.slotState(
                        root.hostDefinition.placement.paneId, modelData.side,
                        modelData.position === "top" ? 0 : 1
                    )
                }
                width: dockTargets.width * 0.28
                height: dockTargets.height / 2 - 12
                x: modelData.side === "left"
                    ? 8 : dockTargets.width - width - 8
                y: modelData.position === "top"
                    ? 8 : dockTargets.height - height - 8
                radius: 8
                color: "#1767e8f9"
                border.width: 1
                border.color: "#73a5f3fc"

                Text {
                    anchors.centerIn: parent
                    width: parent.width - 16
                    text: target.modelData.label + (target.occupant
                        && target.occupant.pane_id !== root.draggingModule
                        ? "\n" + (root.dockLayout.isDocked(root.draggingModule)
                            ? "Swap with " : "Move to empty dock: ")
                            + target.occupant.pane_id : "")
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                    color: "#ccecff"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 9
                    font.capitalization: Font.AllUppercase
                    font.letterSpacing: 1.62
                }
            }
        }
    }
}
