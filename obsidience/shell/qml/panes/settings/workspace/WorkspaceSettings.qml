pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtWebSockets

Item {
    id: root

    readonly property string commandSchema: "obsidience.shell.command.v1"
    property string activeSection: "grid"
    readonly property var sections: [
        {"id": "grid", "label": "Grid"},
        {"id": "tiling", "label": "Workspace tiling"},
        {"id": "behavior", "label": "Tile behavior"}
    ]
    property int paneGridSize: 10
    property int minimumPaneGridSize: 1
    property int maximumPaneGridSize: 100
    property int minimumTileCount: 1
    property int maximumTileCount: 16
    property int workspaceTileGap: 5
    property int tileResizeLimitPercent: 25
    property int minimumTileResizeLimitPercent: 0
    property int maximumTileResizeLimitPercent: 25
    property bool oledModeEnabled: false
    property int oledShiftDistancePx: 32
    property int minimumOledShiftDistancePx: 1
    property int maximumOledShiftDistancePx: 50
    property int oledTravelDurationSeconds: 3600
    property int minimumOledTravelDurationSeconds: 60
    property int maximumOledTravelDurationSeconds: 86400
    property int oledGlowRotationHours: 3
    property int minimumOledGlowRotationHours: 1
    property int maximumOledGlowRotationHours: 24
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
                || !Number.isInteger(message.workspace_tile_gap)
                || !Number.isInteger(message.tile_resize_limit_percent)
                || !Number.isInteger(message.minimum_tile_resize_limit_percent)
                || !Number.isInteger(message.maximum_tile_resize_limit_percent)
                || typeof message.oled_mode_enabled !== "boolean"
                || !Number.isInteger(message.oled_shift_distance_px)
                || !Number.isInteger(message.minimum_oled_shift_distance_px)
                || !Number.isInteger(message.maximum_oled_shift_distance_px)
                || !Number.isInteger(message.oled_travel_duration_seconds)
                || !Number.isInteger(message.minimum_oled_travel_duration_seconds)
                || !Number.isInteger(message.maximum_oled_travel_duration_seconds)
                || !Number.isInteger(message.oled_glow_rotation_hours)
                || !Number.isInteger(message.minimum_oled_glow_rotation_hours)
                || !Number.isInteger(message.maximum_oled_glow_rotation_hours)
                || !Array.isArray(message.workspace_tiling)
                || message.workspace_tiling.length !== 3) {
            return
        }
        minimumPaneGridSize = message.minimum_pane_grid_size
        maximumPaneGridSize = message.maximum_pane_grid_size
        paneGridSize = message.pane_grid_size
        minimumTileCount = message.minimum_tile_count
        maximumTileCount = message.maximum_tile_count
        workspaceTileGap = message.workspace_tile_gap
        tileResizeLimitPercent = message.tile_resize_limit_percent
        minimumTileResizeLimitPercent = message.minimum_tile_resize_limit_percent
        maximumTileResizeLimitPercent = message.maximum_tile_resize_limit_percent
        oledModeEnabled = message.oled_mode_enabled
        oledShiftDistancePx = message.oled_shift_distance_px
        minimumOledShiftDistancePx = message.minimum_oled_shift_distance_px
        maximumOledShiftDistancePx = message.maximum_oled_shift_distance_px
        oledTravelDurationSeconds = message.oled_travel_duration_seconds
        minimumOledTravelDurationSeconds = message.minimum_oled_travel_duration_seconds
        maximumOledTravelDurationSeconds = message.maximum_oled_travel_duration_seconds
        oledGlowRotationHours = message.oled_glow_rotation_hours
        minimumOledGlowRotationHours = message.minimum_oled_glow_rotation_hours
        maximumOledGlowRotationHours = message.maximum_oled_glow_rotation_hours
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

    function setTileResizeLimitPercent(value) {
        const next = Math.max(minimumTileResizeLimitPercent, Math.min(
            maximumTileResizeLimitPercent, Math.round(value)
        ))
        if (next === tileResizeLimitPercent) {
            return
        }
        send("workspace.tile.limit.set", {
            "tile_resize_limit_percent": next
        })
    }

    function setOledSettings(
            enabled, shiftDistancePx, travelDurationSeconds, glowRotationHours) {
        const nextEnabled = enabled === true
        const nextDistance = Math.max(minimumOledShiftDistancePx, Math.min(
            maximumOledShiftDistancePx, Math.round(shiftDistancePx)
        ))
        const nextDuration = Math.max(
            minimumOledTravelDurationSeconds,
            Math.min(
                maximumOledTravelDurationSeconds,
                Math.round(travelDurationSeconds)
            )
        )
        const nextGlowHours = Math.max(
            minimumOledGlowRotationHours,
            Math.min(
                maximumOledGlowRotationHours,
                Math.round(glowRotationHours)
            )
        )
        if (nextEnabled === oledModeEnabled
                && nextDistance === oledShiftDistancePx
                && nextDuration === oledTravelDurationSeconds
                && nextGlowHours === oledGlowRotationHours) {
            return
        }
        send("workspace.oled.set", {
            "oled_mode_enabled": nextEnabled,
            "oled_shift_distance_px": nextDistance,
            "oled_travel_duration_seconds": nextDuration,
            "oled_glow_rotation_hours": nextGlowHours
        })
    }

    function formatOledDuration(seconds) {
        if (seconds % 3600 === 0) {
            return (seconds / 3600) + " hr"
        }
        if (seconds % 60 === 0) {
            return (seconds / 60) + " min"
        }
        return seconds + " sec"
    }

    function parseOledDuration(text, fallbackSeconds) {
        const normalized = String(text).trim().toLowerCase()
        const parsed = parseFloat(normalized)
        if (!Number.isFinite(parsed)) {
            return fallbackSeconds
        }
        if (normalized.indexOf("hr") >= 0
                || normalized.indexOf("hour") >= 0) {
            return Math.round(parsed * 3600)
        }
        if (normalized.indexOf("sec") >= 0) {
            return Math.round(parsed)
        }
        return Math.round(parsed * 60)
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
        id: header
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 18
        spacing: 5

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

    }

    Item {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: header.bottom
        anchors.bottom: parent.bottom
        anchors.leftMargin: 18
        anchors.rightMargin: 18
        anchors.topMargin: 14
        anchors.bottomMargin: 18

        Rectangle {
            id: sectionRail
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: 144
            radius: 5
            color: "#4d02070c"
            border.width: 1
            border.color: "#1867e8f9"

            Flickable {
                anchors.fill: parent
                anchors.margins: 4
                contentWidth: width
                contentHeight: sectionButtons.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds

                Column {
                    id: sectionButtons
                    width: parent.width
                    spacing: 2

                    Repeater {
                        model: root.sections

                        delegate: Rectangle {
                            id: sectionButton

                            required property var modelData
                            width: sectionButtons.width
                            height: 28
                            radius: 4
                            color: root.activeSection === modelData.id
                                ? "#2667e8f9"
                                : sectionMouse.containsMouse ? "#1467e8f9" : "transparent"

                            Text {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.leftMargin: 8
                                anchors.rightMargin: 6
                                text: String(sectionButton.modelData.label).toUpperCase()
                                color: root.activeSection === sectionButton.modelData.id
                                    ? "#cffafe" : "#9967e8f9"
                                elide: Text.ElideRight
                                font.family: "JetBrains Mono"
                                font.pixelSize: 8
                                font.letterSpacing: 1.35
                            }

                            MouseArea {
                                id: sectionMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.activeSection = sectionButton.modelData.id
                            }
                        }
                    }
                }
            }
        }

        Flickable {
            id: settingsScroll
            anchors.left: sectionRail.right
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.leftMargin: 12
            clip: true
            contentWidth: width
            contentHeight: settings.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}

            Column {
                id: settings
                width: settingsScroll.width - 5
                spacing: 10

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
                    text: "Each Surface has its own proportional tile grid · "
                        + root.workspaceTileGap + " px gaps."
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

        Rectangle {
            visible: root.activeSection === "behavior"
            width: parent.width
            height: visible ? 433 : 0
            radius: 6
            color: "#a8061019"
            border.width: 1
            border.color: "#3467e8f9"

            Column {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 9

                Text {
                    text: "TILE BEHAVIOR"
                    color: "#d1f7fe"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 9
                    font.bold: true
                    font.letterSpacing: 1.2
                }

                Text {
                    width: parent.width
                    text: "Tune pane expansion and slow OLED-safe tile movement."
                    color: "#758db8c7"
                    wrapMode: Text.WordWrap
                    font.family: "JetBrains Mono"
                    font.pixelSize: 8
                }

                Row {
                    width: parent.width
                    height: 42
                    spacing: 12

                    Column {
                        width: parent.width - tileResizeLimit.width - parent.spacing
                        spacing: 3

                        Text {
                            text: "EXPAND / CONTRACT LIMIT"
                            color: "#cffafe"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 9
                            font.bold: true
                        }

                        Text {
                            text: "Maximum tile-border change for pane expansion."
                            color: "#758db8c7"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                        }
                    }

                    SpinBox {
                        id: tileResizeLimit

                        width: 112
                        height: 32
                        from: root.minimumTileResizeLimitPercent
                        to: root.maximumTileResizeLimitPercent
                        stepSize: 1
                        editable: true
                        enabled: root.stateReady
                        value: root.tileResizeLimitPercent
                        textFromValue: value => value + " %"
                        valueFromText: text => parseInt(text, 10)
                        onValueModified: root.setTileResizeLimitPercent(value)
                        font.family: "JetBrains Mono"
                        font.pixelSize: 9
                    }
                }

                Rectangle {
                    width: parent.width
                    height: 1
                    color: "#2267e8f9"
                }

                Row {
                    width: parent.width
                    height: 36
                    spacing: 8

                    CheckBox {
                        id: oledMode

                        width: 26
                        height: 26
                        anchors.verticalCenter: parent.verticalCenter
                        checked: root.oledModeEnabled
                        enabled: root.stateReady
                        onToggled: root.setOledSettings(
                            checked,
                            oledShiftDistance.value,
                            oledTravelDuration.value,
                            oledGlowRotation.value
                        )
                    }

                    Column {
                        width: parent.width - oledMode.width - parent.spacing
                        spacing: 2

                        Text {
                            text: "OLED MODE"
                            color: "#cffafe"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 9
                            font.bold: true
                        }

                        Text {
                            text: "Drift shared seams independently while panes stay joined."
                            color: "#758db8c7"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                        }
                    }
                }

                Row {
                    width: parent.width
                    height: 52
                    spacing: 12

                    Column {
                        width: (parent.width - parent.spacing) / 2
                        spacing: 4

                        Text {
                            text: "MAXIMUM DRIFT"
                            color: root.oledModeEnabled ? "#cffafe" : "#657a9cab"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                            font.bold: true
                        }

                        SpinBox {
                            id: oledShiftDistance

                            width: parent.width
                            height: 32
                            from: root.minimumOledShiftDistancePx
                            to: root.maximumOledShiftDistancePx
                            stepSize: 1
                            editable: true
                            enabled: root.stateReady && root.oledModeEnabled
                            value: root.oledShiftDistancePx
                            textFromValue: value => value + " px"
                            valueFromText: text => parseInt(text, 10)
                            onValueModified: root.setOledSettings(
                                oledMode.checked,
                                value,
                                oledTravelDuration.value,
                                oledGlowRotation.value
                            )
                            font.family: "JetBrains Mono"
                            font.pixelSize: 9
                        }
                    }

                    Column {
                        width: (parent.width - parent.spacing) / 2
                        spacing: 4

                        Text {
                            text: "NOMINAL TRAVEL"
                            color: root.oledModeEnabled ? "#cffafe" : "#657a9cab"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                            font.bold: true
                        }

                        SpinBox {
                            id: oledTravelDuration

                            width: parent.width
                            height: 32
                            from: root.minimumOledTravelDurationSeconds
                            to: root.maximumOledTravelDurationSeconds
                            stepSize: 60
                            editable: true
                            enabled: root.stateReady && root.oledModeEnabled
                            value: root.oledTravelDurationSeconds
                            textFromValue: value => root.formatOledDuration(value)
                            valueFromText: text => root.parseOledDuration(
                                text, root.oledTravelDurationSeconds
                            )
                            onValueModified: root.setOledSettings(
                                oledMode.checked,
                                oledShiftDistance.value,
                                value,
                                oledGlowRotation.value
                            )
                            font.family: "JetBrains Mono"
                            font.pixelSize: 9
                        }
                    }
                }

                Row {
                    width: parent.width
                    height: 52
                    spacing: 12

                    Column {
                        width: parent.width - oledGlowRotation.width - parent.spacing
                        spacing: 3

                        Text {
                            text: "BORDER GLOW ROTATION"
                            color: root.oledModeEnabled ? "#cffafe" : "#657a9cab"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                            font.bold: true
                        }

                        Text {
                            text: "Time for one complete neon rotation."
                            color: "#758db8c7"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                        }
                    }

                    SpinBox {
                        id: oledGlowRotation

                        width: 142
                        height: 32
                        from: root.minimumOledGlowRotationHours
                        to: root.maximumOledGlowRotationHours
                        stepSize: 1
                        editable: true
                        enabled: root.stateReady && root.oledModeEnabled
                        value: root.oledGlowRotationHours
                        textFromValue: value => value + " hr / rotation"
                        valueFromText: text => parseInt(text, 10)
                        onValueModified: root.setOledSettings(
                            oledMode.checked,
                            oledShiftDistance.value,
                            oledTravelDuration.value,
                            value
                        )
                        font.family: "JetBrains Mono"
                        font.pixelSize: 9
                    }
                }

                Text {
                    width: parent.width
                    text: "Per-seam drift can change a pane by up to twice its value and may be safety-limited by the grid. Travel is nominal active time with ±10% seam pacing; motion starts at center. Geometry moves only on Samsung; chrome stays consistent on every Surface. Defaults: ±32 px · 1 hr travel · 3 hr border glow."
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
    }
}
