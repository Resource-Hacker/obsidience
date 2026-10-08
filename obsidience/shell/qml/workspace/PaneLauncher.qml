pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtWebSockets
import Quickshell
import Quickshell.Widgets
import "../api"
import "../components/visual"

PanelWindow {
    id: root

    required property ShellApi shellApi
    required property PaneDockLayout dockLayout
    required property string surfaceId
    required property var surfaceScreen
    required property var panes
    required property bool launcherOpen

    signal presentRequested(var placement, string surfaceId, real x, real y)
    signal launcherRequested()

    property var runningApplications: []
    property string activeWindowId: ""
    property int windowRevision: 0
    property int activationSequence: 0
    property string applicationError: ""
    property bool shelfOpen: false

    readonly property int shelfMaximumWidth: 1200
    readonly property int edgeTriggerHeight: 12

    readonly property var currentSurface: shellApi.surfaceLayout.surface(surfaceId)

    screen: surfaceScreen
    visible: true
    implicitWidth: Math.min(
        surfaceScreen ? Math.max(1, surfaceScreen.width - 40)
                      : shelfMaximumWidth,
        shelfMaximumWidth
    )
    implicitHeight: launcherRow.implicitHeight + 4
    color: "transparent"
    focusable: false
    aboveWindows: true
    exclusiveZone: 0
    mask: Region { item: shelfSurface }

    anchors {
        bottom: true
    }

    margins {
        bottom: 0
    }

    function scheduleShelfHide() {
        if (!launcherOpen && !shelfHover.hovered) {
            shelfHideTimer.restart()
        }
    }

    onLauncherOpenChanged: {
        if (launcherOpen) {
            shelfHideTimer.stop()
            shelfOpen = true
        } else {
            scheduleShelfHide()
        }
    }

    ApplicationLauncher {
        anchorItem: applicationLauncherButton
        surfaceScreen: root.surfaceScreen
        requestedVisible: root.launcherOpen
        shelfWidth: root.width
        shelfHeight: root.height
        onDismissRequested: {
            if (root.launcherOpen) {
                root.launcherRequested()
            }
        }
    }

    function openPane(entry) {
        if (!entry || !entry.placement || !currentSurface) {
            return
        }
        const placement = entry.placement
        const x = placement.surfaceId === surfaceId
            ? placement.x
            : Math.round(
                (currentSurface.logical_width - placement.width) / 2
            )
        const y = placement.surfaceId === surfaceId
            ? placement.y
            : Math.round(
                (currentSurface.logical_height - placement.height) / 2
            )
        presentRequested(
            placement,
            surfaceId,
            shellApi.surfaceLayout.clampPaneX(
                currentSurface, placement.width, x
            ),
            shellApi.surfaceLayout.clampPaneY(
                currentSurface, placement.height, y
            )
        )
    }

    function paneIsLocal(entry) {
        if (entry && entry.placement
                && dockLayout.isDocked(entry.placement.paneId)) {
            const state = dockLayout.moduleState(entry.placement.paneId)
            const host = paneEntry(state.host_pane_id)
            return state.collapsed !== true && host && host.placement.open
                && host.placement.surfaceId === surfaceId
        }
        return entry && entry.placement && entry.placement.open
            && entry.placement.surfaceId === surfaceId
    }

    function paneEntry(paneId) {
        for (const entry of panes) {
            if (entry && entry.placement && entry.placement.paneId === paneId) {
                return entry
            }
        }
        return null
    }

    function sendDockCommand(command) {
        if (shellSocket.status === WebSocket.Open) {
            shellSocket.sendTextMessage(JSON.stringify(command))
        }
    }

    function activateWindow(entry) {
        if (!entry || !entry.window_id || windowRevision < 1
                || shellSocket.status !== WebSocket.Open) {
            return
        }
        activationSequence += 1
        applicationError = ""
        shellSocket.sendTextMessage(JSON.stringify({
            "schema": "obsidience.shell.command.v1",
            "type": "window.activate",
            "token": surfaceId + ":activate:" + activationSequence,
            "surface_id": surfaceId,
            "window_id": entry.window_id,
            "expected_revision": windowRevision
        }))
    }

    function togglePane(entry) {
        if (!entry || !entry.placement) {
            return
        }
        if (dockLayout.isDocked(entry.placement.paneId)) {
            const state = dockLayout.moduleState(entry.placement.paneId)
            const host = paneEntry(state.host_pane_id)
            const localAndExpanded = state.collapsed !== true && host
                && host.placement.open && host.placement.surfaceId === surfaceId
            sendDockCommand({
                "schema": "obsidience.shell.command.v1",
                "type": localAndExpanded ? "pane.collapse" : "pane.expand",
                "pane_id": entry.placement.paneId,
                "host_pane_id": state.host_pane_id,
                "surface_id": surfaceId,
                "expected_revision": dockLayout.revision
            })
            return
        }
        if (paneIsLocal(entry)) {
            entry.placement.dismiss()
        } else {
            openPane(entry)
        }
    }

    function cameraEntry() {
        for (const entry of panes) {
            if (entry && entry.placement && entry.placement.paneId === "camera") {
                return entry
            }
        }
        return null
    }

    function toggleCamera() {
        togglePane(cameraEntry())
    }

    WebSocket {
        id: shellSocket

        url: "ws://127.0.0.1:8768" + ShellCommandToken.query
        requestedSubprotocols: ["obsidience.shell.v1"]
        active: true

        onTextMessageReceived: message => {
            if (typeof message !== "string" || message.length > 65536) {
                return
            }
            try {
                const event = JSON.parse(message)
                if (event && event.schema === "obsidience.shell.event.v1"
                        && event.type === "pane.dock.state" && event.layout) {
                    root.dockLayout.applyRecord(event.layout)
                } else if (event
                        && event.schema === "obsidience.shell.event.v1"
                        && event.type === "application.state"
                        && event.surface_id === root.surfaceId
                        && Array.isArray(event.windows)) {
                    root.runningApplications = event.windows.filter(
                        window => window.window_kind !== "module"
                    )
                    root.activeWindowId = typeof event.active_window_id === "string"
                        ? event.active_window_id : ""
                    root.windowRevision = Number.isInteger(event.revision)
                        ? event.revision : 0
                } else if (event
                        && event.schema === "obsidience.shell.event.v1"
                        && event.type === "window.activation.result"
                        && event.surface_id === root.surfaceId
                        && event.success !== true) {
                    root.applicationError = typeof event.reason === "string"
                        ? event.reason : "activation_failed"
                    applicationErrorTimer.restart()
                }
            } catch (error) {
                return
            }
        }
        onStatusChanged: status => {
            if (status === WebSocket.Closed || status === WebSocket.Error) {
                dockReconnectTimer.restart()
            }
        }
    }

    Timer {
        id: dockReconnectTimer

        interval: 500
        repeat: false
        onTriggered: {
            shellSocket.active = false
            shellSocket.active = true
        }
    }

    Timer {
        id: applicationErrorTimer

        interval: 3000
        repeat: false
        onTriggered: root.applicationError = ""
    }

    Timer {
        id: shelfHideTimer

        interval: 250
        repeat: false
        onTriggered: {
            if (!root.launcherOpen && !shelfHover.hovered) {
                root.shelfOpen = false
            }
        }
    }



    SystemClock {
        id: shellClock

        precision: SystemClock.Minutes
    }

    Item {
        id: shelfSurface

        x: 0
        y: root.shelfOpen ? 0 : root.height - root.edgeTriggerHeight
        width: root.width
        height: root.shelfOpen ? root.height : root.edgeTriggerHeight

        HoverHandler {
            id: shelfHover

            onHoveredChanged: {
                if (hovered) {
                    shelfHideTimer.stop()
                    root.shelfOpen = true
                } else {
                    root.scheduleShelfHide()
                }
            }
        }
    }

    Rectangle {
        parent: shelfSurface
        anchors.fill: parent
        radius: 5
        color: "#cc020b14"
        border.width: 1
        border.color: "#2667e8f9"
        visible: root.shelfOpen
        z: 0
    }

    RowLayout {
        id: launcherRow

        parent: shelfSurface
        anchors.fill: parent
        anchors.margins: 2
        spacing: 8
        enabled: root.shelfOpen
        opacity: root.shelfOpen ? 1 : 0
        z: 1

        GlowButton {
            id: applicationLauncherButton

            Layout.preferredWidth: 32
            Layout.preferredHeight: 28
            Layout.alignment: Qt.AlignTop
            Layout.topMargin: 4
            text: ""
            padding: 1
            contentHorizontalPadding: 0
            selected: root.launcherOpen
            accent: "#67e8f9"
            foreground: "#cffafe"
            selectedBorderOpacity: 0.60
            selectedFillOpacity: 0.15
            onClicked: root.launcherRequested()

            contentItem: ShellIcon {
                glyph: "launcher"
                iconColor: applicationLauncherButton.selected
                        || applicationLauncherButton.hovered
                    ? applicationLauncherButton.foreground
                    : applicationLauncherButton.accent
                iconOpacity: applicationLauncherButton.selected
                        || applicationLauncherButton.hovered ? 1.0 : 0.62
                width: 27
                height: 27
            }

            ToolTip.visible: false
            ToolTip.delay: 400
            ToolTip.text: root.launcherOpen
                ? "Close application launcher" : "Open application launcher"
            Accessible.name: ToolTip.text
        }

        GlowButton {
            id: cameraButton
            readonly property var entry: root.cameraEntry()
            Layout.preferredWidth: 32
            Layout.preferredHeight: 28
            Layout.alignment: Qt.AlignTop
            Layout.topMargin: 4
            text: ""
            selected: root.paneIsLocal(entry)
            enabled: entry !== null
            foreground: "#cffafe"
            idleBorderOpacity: 0.15
            idleTextOpacity: 0.55
            onClicked: root.toggleCamera()
            contentItem: ControlIcon {
                glyph: cameraButton.selected ? "eye" : "eye-off"
                iconColor: cameraButton.foreground
                strokeOpacity: cameraButton.selected || cameraButton.hovered ? 1.0 : 0.55
                width: 25
                height: 25
            }
            Accessible.name: selected ? "Close camera video" : "Open camera video"
        }

        Item {
            id: runningApplicationRegion

            Layout.fillWidth: true
            Layout.minimumWidth: 120
            Layout.preferredHeight: 28
            Layout.alignment: Qt.AlignTop
            Layout.topMargin: 4
            height: 28
            clip: true

            Flickable {
                anchors.fill: parent
                contentWidth: runningApplicationRow.implicitWidth
                contentHeight: height
                clip: true
                boundsBehavior: Flickable.StopAtBounds

                Row {
                    id: runningApplicationRow

                    height: parent.height
                    spacing: 4

                    Row {
                        visible: root.runningApplications.length === 0
                        height: parent.height
                        spacing: 5

                        ShellIcon {
                            anchors.verticalCenter: parent.verticalCenter
                            width: 15
                            height: 15
                            glyph: "application"
                            iconColor: root.applicationError
                                ? "#f87171" : "#67e8f9"
                            iconOpacity: 0.44
                        }

                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: root.applicationError
                                ? root.applicationError : "NO APPLICATIONS"
                            color: root.applicationError
                                ? "#bffca5a5" : "#5967e8f9"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                            font.capitalization: Font.AllUppercase
                            font.letterSpacing: 1.4
                        }
                    }

                    Repeater {
                        model: root.runningApplications

                        delegate: GlowButton {
                            id: applicationButton

                            required property var modelData
                            readonly property var desktopEntry:
                                DesktopEntries.heuristicLookup(
                                    String(modelData.app_id || "")
                                )

                            width: 32
                            height: 28
                            padding: 1
                            text: ""
                            contentHorizontalPadding: 0
                            selected: String(modelData.window_id || "")
                                === root.activeWindowId
                            accent: "#67e8f9"
                            foreground: "#e6faff"
                            selectedBorderOpacity: 0.65
                            selectedFillOpacity: 0.18
                            onClicked: root.activateWindow(modelData)

                            contentItem: IconImage {
                                source: Quickshell.iconPath(
                                    applicationButton.desktopEntry
                                            ? applicationButton.desktopEntry.icon : "",
                                    "application-x-executable"
                                )
                                asynchronous: true
                                mipmap: true
                                opacity: applicationButton.selected
                                        || applicationButton.hovered ? 1.0 : 0.72
                            }

                            ToolTip.visible: false
                            ToolTip.delay: 400
                            ToolTip.text: String(
                                modelData.title || modelData.app_id || "Application"
                            )
                            Accessible.name: ToolTip.text
                        }
                    }
                }
            }
        }

        Row {
            id: paneRow

            Layout.preferredWidth: implicitWidth
            Layout.preferredHeight: 28
            Layout.alignment: Qt.AlignTop
            Layout.topMargin: 4
            height: 28
            spacing: 4

            Repeater {
                model: root.panes

                delegate: GlowButton {
                    id: paneButton

                    required property var modelData
                    width: 32
                    height: 28
                    text: ""
                    padding: 1
                    contentHorizontalPadding: 0
                    selected: root.paneIsLocal(modelData)
                    accent: String(modelData.accent || "#67e8f9")
                    foreground: "#e6faff"
                    idleForeground: accent
                    selectedBorderOpacity: 0.60
                    selectedFillOpacity: 0.15
                    onClicked: root.togglePane(modelData)

                    contentItem: ShellIcon {
                        glyph: String(paneButton.modelData.icon || "application")
                        iconColor: paneButton.selected || paneButton.hovered
                            ? paneButton.foreground : paneButton.accent
                        iconOpacity: paneButton.selected || paneButton.hovered
                            ? 1.0 : 0.62
                        width: 27
                        height: 27
                    }

                    ToolTip.visible: false
                    ToolTip.delay: 400
                    ToolTip.text: String(modelData.title)
                    Accessible.name: ToolTip.text
                }
            }
        }

        Rectangle {
            id: clockRegion

            Layout.preferredWidth: 82
            Layout.preferredHeight: 28
            Layout.alignment: Qt.AlignTop
            Layout.topMargin: 4
            height: 28
            radius: 4
            color: "#8f020b14"
            border.width: 1
            border.color: "#2667e8f9"

            Row {
                anchors.centerIn: parent
                spacing: 6

                ShellIcon {
                    anchors.verticalCenter: parent.verticalCenter
                    width: 14
                    height: 14
                    glyph: "clock"
                    iconColor: "#67e8f9"
                    iconOpacity: 0.58
                }

                Text {
                    id: clockLabel

                    anchors.verticalCenter: parent.verticalCenter
                    text: Qt.formatTime(shellClock.date, "h:mm AP")
                    color: "#c7cffafe"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 9
                    font.weight: Font.Medium
                }
            }
        }
    }
}
