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

    property bool realtimeEnabled: false
    property bool realtimeReady: false
    property bool realtimeProactive: false
    property string realtimePhase: "off"
    property string realtimeAction: ""
    property string realtimeError: ""
    property bool captureActive: false
    property bool userSpeaking: false
    property string liveTranscriptText: ""
    property bool liveTranscriptFinal: false
    readonly property bool realtimeBusy: realtimeAction !== "" || !shellApi.realtime.connected
    readonly property bool inputCapturing: realtimeEnabled && (captureActive || userSpeaking)
    readonly property bool recognitionVisible: inputCapturing || recognitionLinger.running
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
        if (!launcherOpen && !shelfHover.hovered && !recognitionVisible) {
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

    onRecognitionVisibleChanged: {
        if (recognitionVisible) {
            shelfHideTimer.stop()
            shelfOpen = true
        } else {
            scheduleShelfHide()
        }
    }

    onRealtimeEnabledChanged: {
        if (!realtimeEnabled) recognitionLinger.stop()
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

    function applyRealtime(payload) {
        if (!payload) {
            return
        }
        realtimeEnabled = payload.enabled === true
        realtimeReady = payload.ready === true
        realtimeProactive = payload.proactive === true
        realtimePhase = typeof payload.phase === "string"
            ? payload.phase : (realtimeEnabled ? "running" : "off")
        realtimeError = typeof payload.last_error === "string"
            ? payload.last_error : ""
        captureActive = payload.capture_active === true
        userSpeaking = payload.user_speaking === true
        const transcript = payload.live_transcript
        liveTranscriptText = transcript
                && typeof transcript.text === "string"
            ? transcript.text : ""
        liveTranscriptFinal = !!transcript && transcript.final === true
        if (realtimePhase === "disconnected") recognitionLinger.stop()
    }

    function realtimeRequest(method, path, action, body) {
        const xhr = new XMLHttpRequest()
        xhr.open(method, "http://127.0.0.1:8765" + path)
        if (body !== undefined && body !== null) {
            xhr.setRequestHeader("content-type", "application/json")
        }
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE) {
                return
            }
            if (action && root.realtimeAction === action) {
                root.realtimeAction = ""
            }
            if (xhr.status < 200 || xhr.status >= 300) {
                root.realtimeError = xhr.responseText
                    || "Realtime request failed (" + xhr.status + ")"
                return
            }
            try {
                // The shared stream owns live state; HTTP only acknowledges
                // this explicit control request and cannot overwrite newer events.
                JSON.parse(xhr.responseText)
            } catch (error) {
                root.realtimeError = "Realtime returned invalid state."
            }
        }
        xhr.send(body === undefined || body === null ? null : JSON.stringify(body))
    }

    function toggleRealtime() {
        if (realtimeBusy || realtimePhase === "starting"
                || realtimePhase === "stopping") {
            return
        }
        realtimeAction = "power"
        realtimeError = ""
        realtimeRequest(
            "POST",
            realtimeEnabled ? "/api/realtime/stop" : "/api/realtime/start",
            "power",
            null
        )
    }

    function toggleCamera() {
        togglePane(cameraEntry())
    }

    function toggleProactive() {
        if (!realtimeReady || realtimeBusy) {
            return
        }
        realtimeAction = "mode"
        realtimeError = ""
        realtimeRequest("PATCH", "/api/realtime/mode", "mode", {
            "proactive": !realtimeProactive
        })
    }

    Component.onCompleted: applyRealtime(shellApi.realtime.state)

    Connections {
        target: root.shellApi.realtime
        function onStateChanged() { root.applyRealtime(root.shellApi.realtime.state) }
        function onTranscriptUpdated() { recognitionLinger.restart() }
    }

    WebSocket {
        id: shellSocket

        url: "ws://127.0.0.1:8768"
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
            if (!root.launcherOpen && !shelfHover.hovered && !root.recognitionVisible) {
                root.shelfOpen = false
            }
        }
    }

    Timer {
        id: recognitionLinger
        interval: 2000
        repeat: false
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

        Rectangle {
            id: realtimeContainer

            Layout.preferredWidth: 352
            Layout.preferredHeight: height
            Layout.alignment: Qt.AlignTop
            width: 352
            height: realtimeColumn.implicitHeight + 8
            radius: 4
            color: "#cc020b14"
            border.width: 1
            border.color: "#2667e8f9"

            Column {
                id: realtimeColumn

                x: 4
                y: 4
                width: parent.width - 8
                spacing: 4

                Row {
                    id: realtimeControls

                    width: parent.width
                    height: 28
                    spacing: 4

                    GlowButton {
                        id: realtimeButton

                        width: 32
                        height: 28
                        text: ""
                        padding: 1
                        contentHorizontalPadding: 0
                        selected: root.realtimeEnabled
                        emphasized: !root.realtimeEnabled
                            && root.realtimePhase === "error"
                        enabled: !root.realtimeBusy
                            && root.realtimePhase !== "starting"
                            && root.realtimePhase !== "stopping"
                        accent: emphasized ? "#f87171" : "#67e8f9"
                        foreground: emphasized ? "#fecaca" : "#cffafe"
                        idleBorderOpacity: emphasized ? 0.45 : 0.15
                        selectedBorderOpacity: 0.55
                        selectedFillOpacity: 0.15
                        idleTextOpacity: emphasized ? 1.0 : 0.55
                        disabledOpacity: 0.60
                        onClicked: root.toggleRealtime()

                        contentItem: ControlIcon {
                            glyph: root.realtimeAction === "power"
                                    || root.realtimePhase === "starting"
                                    || root.realtimePhase === "stopping"
                                ? "loader"
                                : (root.realtimeEnabled ? "mic" : "mic-off")
                            iconColor: realtimeButton.selected
                                    || realtimeButton.hovered
                                    || realtimeButton.emphasized
                                ? realtimeButton.foreground : realtimeButton.accent
                            strokeOpacity: realtimeButton.selected
                                    || realtimeButton.hovered
                                    || realtimeButton.emphasized ? 1.0 : 0.55
                            width: 25
                            height: 25
                        }

                        ToolTip.visible: false
                        ToolTip.delay: 400
                        ToolTip.text: root.realtimeReady ? "Realtime mode active"
                            : root.realtimeEnabled
                                ? "Realtime " + root.realtimePhase
                                : "Enable realtime mode"
                    }

                    GlowButton {
                        id: cameraButton

                        readonly property var entry: root.cameraEntry()
                        width: 32
                        height: 28
                        text: ""
                        padding: 1
                        contentHorizontalPadding: 0
                        selected: root.paneIsLocal(entry)
                        emphasized: !selected && root.realtimeEnabled
                        accent: !selected && root.realtimeEnabled
                            ? "#fcd34d" : "#67e8f9"
                        foreground: !selected && root.realtimeEnabled
                            ? "#fef3c7" : "#cffafe"
                        idleBorderOpacity: !selected && root.realtimeEnabled
                            ? 0.40 : 0.15
                        idleTextOpacity: !selected && root.realtimeEnabled
                            ? 0.80 : 0.55
                        selectedBorderOpacity: 0.55
                        selectedFillOpacity: 0.15
                        enabled: entry !== null
                        disabledOpacity: 0.60
                        onClicked: root.toggleCamera()

                        contentItem: ControlIcon {
                            glyph: cameraButton.selected ? "eye" : "eye-off"
                            iconColor: cameraButton.selected
                                    || cameraButton.hovered
                                    || root.realtimeEnabled
                                ? cameraButton.foreground : cameraButton.accent
                            strokeOpacity: cameraButton.selected
                                    || cameraButton.hovered
                                    || root.realtimeEnabled ? 1.0 : 0.55
                            width: 25
                            height: 25
                        }

                        ToolTip.visible: false
                        ToolTip.delay: 400
                        ToolTip.text: selected ? "Close camera video"
                            : root.realtimeEnabled
                                ? "Camera active for Realtime; open video view"
                                : "Open camera video"
                    }

                    GlowButton {
                        id: proactiveButton

                        width: 32
                        height: 28
                        text: ""
                        padding: 1
                        contentHorizontalPadding: 0
                        selected: root.realtimeProactive
                        enabled: root.realtimeReady && !root.realtimeBusy
                        accent: selected ? "#fcd34d" : "#67e8f9"
                        foreground: selected ? "#fef3c7" : "#cffafe"
                        selectedBorderOpacity: 0.60
                        selectedFillOpacity: 0.15
                        idleTextOpacity: 0.55
                        disabledOpacity: 0.25
                        onClicked: root.toggleProactive()

                        contentItem: ControlIcon {
                            glyph: root.realtimeAction === "mode" ? "loader"
                                : (root.realtimeProactive ? "pause" : "play")
                            iconColor: proactiveButton.selected
                                    || proactiveButton.hovered
                                ? proactiveButton.foreground
                                : proactiveButton.accent
                            strokeOpacity: proactiveButton.selected
                                    || proactiveButton.hovered ? 1.0 : 0.55
                            width: 24
                            height: 24
                        }

                        ToolTip.visible: false
                        ToolTip.delay: 400
                        ToolTip.text: root.realtimeReady
                            ? root.realtimeProactive
                                ? "Return to command-only mode"
                                : "Enable proactive observation"
                            : "Realtime mode must finish loading first"
                    }

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        leftPadding: 4
                        rightPadding: 4
                        text: root.realtimeProactive ? "PROACTIVE"
                            : root.realtimeReady ? "REALTIME"
                            : root.realtimePhase.toUpperCase()
                        color: root.realtimeProactive ? "#ccfde68a"
                            : root.realtimeReady ? "#b3a5f3fc" : "#5967e8f9"
                        font.family: "JetBrains Mono"
                        font.pixelSize: 9
                        font.capitalization: Font.AllUppercase
                        font.letterSpacing: 1.62
                    }
                }

                Item {
                    id: realtimeLive

                    visible: root.realtimeEnabled
                    width: parent.width
                    height: visible ? liveColumn.implicitHeight + 2 : 0

                    Column {
                        id: liveColumn

                        x: 2
                        width: parent.width - 4
                        spacing: 4

                        Row {
                            id: inputMeter

                            width: parent.width
                            height: 24
                            spacing: 4

                            Text {
                                id: inputLabel

                                anchors.verticalCenter: parent.verticalCenter
                                text: "INPUT"
                                color: "#7367e8f9"
                                font.family: "JetBrains Mono"
                                font.pixelSize: 7
                                font.capitalization: Font.AllUppercase
                                font.letterSpacing: 1.12
                            }

                            InputWaveform {
                                anchors.verticalCenter: parent.verticalCenter
                                width: parent.width - inputLabel.implicitWidth - parent.spacing
                                height: 24
                                levels: root.shellApi.realtime.levels
                                capturing: root.inputCapturing
                            }
                        }

                        Item {
                            id: transcriptRow

                            width: parent.width
                            height: Math.max(
                                transcriptPrefix.implicitHeight,
                                transcriptViewport.height
                            )

                            Text {
                                id: transcriptPrefix

                                anchors.left: parent.left
                                anchors.top: parent.top
                                text: root.inputCapturing ? "HEARING"
                                    : root.liveTranscriptFinal
                                        ? "HEARD" : "LISTENING"
                                color: "#7367e8f9"
                                font.family: "JetBrains Mono"
                                font.pixelSize: 9
                                font.capitalization: Font.AllUppercase
                                font.letterSpacing: 1.26
                                lineHeightMode: Text.FixedHeight
                                lineHeight: 16
                            }

                            Flickable {
                                id: transcriptViewport
                                anchors.left: transcriptPrefix.right
                                anchors.leftMargin: 4
                                anchors.right: parent.right
                                anchors.top: parent.top
                                height: Math.min(48, contentHeight)
                                contentHeight: transcriptText.implicitHeight
                                contentWidth: width
                                contentY: Math.max(0, contentHeight - height)
                                interactive: false
                                clip: true

                                Text {
                                    id: transcriptText
                                    width: transcriptViewport.width
                                    text: root.liveTranscriptText !== ""
                                        ? root.liveTranscriptText : "Listening…"
                                    color: "#d9cffafe"
                                    wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                                    font.family: "JetBrains Mono"
                                    font.pixelSize: 11
                                    lineHeightMode: Text.FixedHeight
                                    lineHeight: 16
                                }
                            }
                        }
                    }
                }
            }
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
