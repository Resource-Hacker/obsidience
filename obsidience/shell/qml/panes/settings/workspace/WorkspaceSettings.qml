pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtWebSockets

Item {
    id: root

    readonly property string commandSchema: "obsidience.shell.command.v1"
    property string activeSection: "grid"
    property int paneGridSize: 10
    property int minimumPaneGridSize: 1
    property int maximumPaneGridSize: 100
    property int minimumTileCount: 1
    property int maximumTileCount: 16
    property var workspaceTiling: []
    property bool stateReady: false
    property string errorMessage: ""

    function send(type, extra) {
        if (shellSocket.status !== WebSocket.Open) {
            return false
        }
        shellSocket.sendTextMessage(JSON.stringify(Object.assign({
            "schema": commandSchema,
            "type": type
        }, extra || {})))
        return true
    }

    function requestState() {
        if (!send("workspace.state.request")) {
            errorMessage = "Waiting for the workspace…"
        }
    }

    function applyState(message) {
        if (!message || message.type !== "workspace.state"
                || !Number.isInteger(message.pane_grid_size)
                || !Number.isInteger(message.minimum_pane_grid_size)
                || !Number.isInteger(message.maximum_pane_grid_size)
                || !Number.isInteger(message.minimum_tile_count)
                || !Number.isInteger(message.maximum_tile_count)
                || !Array.isArray(message.workspace_tiling)
                || message.workspace_tiling.length !== 3) {
            return
        }
        minimumPaneGridSize = message.minimum_pane_grid_size
        maximumPaneGridSize = message.maximum_pane_grid_size
        paneGridSize = message.pane_grid_size
        minimumTileCount = message.minimum_tile_count
        maximumTileCount = message.maximum_tile_count
        workspaceTiling = message.workspace_tiling
        stateReady = true
        errorMessage = ""
    }

    function setPaneGridSize(value) {
        const next = Math.max(minimumPaneGridSize, Math.min(
            maximumPaneGridSize, Math.round(value)
        ))
        if (next === paneGridSize) {
            return
        }
        send("workspace.grid.set", {"pane_grid_size": next})
    }

    function setWorkspaceTiling(surfaceId, columns, rows) {
        send("workspace.tiling.set", {
            "surface_id": surfaceId,
            "columns": Math.max(minimumTileCount, Math.min(
                maximumTileCount, Math.round(columns)
            )),
            "rows": Math.max(minimumTileCount, Math.min(
                maximumTileCount, Math.round(rows)
            ))
        })
    }

    Component.onCompleted: requestState()
    onVisibleChanged: if (visible) requestState()

    WebSocket {
        id: shellSocket

        url: "ws://127.0.0.1:8768"
        requestedSubprotocols: ["obsidience.shell.v1"]
        active: true

        onStatusChanged: status => {
            if (status === WebSocket.Open) {
                root.requestState()
            } else if (status === WebSocket.Closed || status === WebSocket.Error) {
                reconnectTimer.restart()
            }
        }
        onTextMessageReceived: message => {
            if (typeof message !== "string" || message.length > 16384) {
                return
            }
            try {
                const event = JSON.parse(message)
                if (event.schema === "obsidience.shell.event.v1") {
                    root.applyState(event)
                }
            } catch (error) {
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

    Column {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 18
        spacing: 14

        Text {
            text: "WORKSPACE"
            color: "#d9f9fe"
            font.family: "JetBrains Mono"
            font.pixelSize: 11
            font.bold: true
            font.letterSpacing: 1.8
        }

        Text {
            width: parent.width
            text: "Shared behavior for every movable pane on every Surface."
            color: "#7899b8c5"
            wrapMode: Text.WordWrap
            font.family: "JetBrains Mono"
            font.pixelSize: 9
        }

        Row {
            spacing: 8

            Repeater {
                model: [
                    {"id": "grid", "label": "Grid"},
                    {"id": "tiling", "label": "Workspace tiling"}
                ]

                delegate: Rectangle {
                    id: tab

                    required property var modelData
                    width: modelData.id === "tiling" ? 156 : 112
                    height: 30
                    radius: 4
                    color: root.activeSection === modelData.id
                        ? "#202f4a18" : tabMouse.containsMouse ? "#141b3214" : "transparent"
                    border.width: 1
                    border.color: root.activeSection === modelData.id
                        ? "#8067e8f9" : "#3067e8f9"

                    Text {
                        anchors.centerIn: parent
                        text: String(tab.modelData.label).toUpperCase()
                        color: root.activeSection === tab.modelData.id
                            ? "#e6f9fe" : "#91a9bfd3"
                        font.family: "JetBrains Mono"
                        font.pixelSize: 9
                        font.bold: true
                        font.letterSpacing: 1.2
                    }

                    MouseArea {
                        id: tabMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.activeSection = tab.modelData.id
                    }
                }
            }
        }

        Rectangle {
            visible: root.activeSection === "grid"
            width: parent.width
            height: visible ? 104 : 0
            radius: 6
            color: "#a8061019"
            border.width: 1
            border.color: "#3467e8f9"

            Column {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 7

                Row {
                    width: parent.width
                    height: 32
                    spacing: 12

                    Column {
                        width: parent.width - gridSize.width - parent.spacing
                        spacing: 3

                        Text {
                            text: "PANE GRID"
                            color: "#d1f7fe"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 9
                            font.bold: true
                            font.letterSpacing: 1.2
                        }

                        Text {
                            text: "Snap pane position and size to this spacing."
                            color: "#758db8c7"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                        }
                    }

                    SpinBox {
                        id: gridSize

                        width: 112
                        height: 32
                        from: root.minimumPaneGridSize
                        to: root.maximumPaneGridSize
                        stepSize: 1
                        editable: true
                        enabled: root.stateReady
                        value: root.paneGridSize
                        font.family: "JetBrains Mono"
                        font.pixelSize: 10
                        textFromValue: (value, locale) => value + " px"
                        valueFromText: (text, locale) => {
                            const parsed = parseInt(text, 10)
                            return Number.isFinite(parsed) ? parsed : root.paneGridSize
                        }
                        onValueModified: root.setPaneGridSize(value)

                        background: Rectangle {
                            radius: 4
                            color: "#061019"
                            border.width: 1
                            border.color: gridSize.activeFocus
                                ? "#8067e8f9" : "#4067e8f9"
                        }
                        contentItem: TextInput {
                            text: gridSize.displayText.toUpperCase()
                            color: "#cffafe"
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            readOnly: !gridSize.editable
                            validator: gridSize.validator
                            inputMethodHints: Qt.ImhDigitsOnly
                            selectByMouse: true
                            font: gridSize.font
                        }
                    }
                }

                Text {
                    text: "Default: 10 px · applies while moving and resizing"
                    color: "#657a9cab"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 8
                }

                Text {
                    visible: root.errorMessage !== ""
                    text: root.errorMessage
                    color: "#fda4af"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 8
                }
            }
        }

        Rectangle {
            visible: root.activeSection === "tiling"
            width: parent.width
            height: visible ? 238 : 0
            radius: 6
            color: "#a8061019"
            border.width: 1
            border.color: "#3467e8f9"

            Column {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 7

                Text {
                    text: "WORKSPACE TILING"
                    color: "#d1f7fe"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 9
                    font.bold: true
                    font.letterSpacing: 1.2
                }

                Text {
                    width: parent.width
                    text: "Each Surface has its own proportional tile grid."
                    color: "#758db8c7"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 8
                }

                Repeater {
                    model: root.workspaceTiling

                    delegate: Row {
                        id: tilingRow

                        required property var modelData
                        width: parent.width
                        height: 34
                        spacing: 8

                        Text {
                            width: 130
                            anchors.verticalCenter: parent.verticalCenter
                            text: String(tilingRow.modelData.label).toUpperCase()
                            color: "#cffafe"
                            elide: Text.ElideRight
                            font.family: "JetBrains Mono"
                            font.pixelSize: 9
                            font.bold: true
                        }

                        SpinBox {
                            id: columns

                            width: 72
                            height: 30
                            from: root.minimumTileCount
                            to: root.maximumTileCount
                            editable: true
                            enabled: root.stateReady
                            value: tilingRow.modelData.columns
                            onValueModified: root.setWorkspaceTiling(
                                tilingRow.modelData.surface_id,
                                value,
                                tilingRow.modelData.rows
                            )
                            textFromValue: value => value + " COL"
                            valueFromText: text => parseInt(text, 10)
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                        }

                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: "×"
                            color: "#7899b8c5"
                            font.pixelSize: 10
                        }

                        SpinBox {
                            id: rows

                            width: 72
                            height: 30
                            from: root.minimumTileCount
                            to: root.maximumTileCount
                            editable: true
                            enabled: root.stateReady
                            value: tilingRow.modelData.rows
                            onValueModified: root.setWorkspaceTiling(
                                tilingRow.modelData.surface_id,
                                tilingRow.modelData.columns,
                                value
                            )
                            textFromValue: value => value + " ROW"
                            valueFromText: text => parseInt(text, 10)
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                        }

                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: (tilingRow.modelData.columns
                                * tilingRow.modelData.rows) + " ZONES"
                            color: "#7899b8c5"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                        }
                    }
                }

                Text {
                    width: parent.width
                    text: "META + ARROW RESIZES  ·  CTRL + META + ARROW MOVES  ·  SHIFT + META + ARROW CHANGES SURFACE"
                    color: "#657a9cab"
                    wrapMode: Text.WordWrap
                    font.family: "JetBrains Mono"
                    font.pixelSize: 8
                }

                Text {
                    visible: root.errorMessage !== ""
                    text: root.errorMessage
                    color: "#fda4af"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 8
                }
            }
        }
    }
}
