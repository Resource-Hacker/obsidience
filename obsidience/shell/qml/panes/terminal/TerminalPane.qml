pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtWebEngine
import QtWebSockets
import QMLTermWidget 2.0
import Quickshell.Io

Rectangle {
    id: root

    property int activeTab: 0
    property bool terminalConnected: true
    property bool traceConnected: false
    property bool followTrace: true
    // The agent canvas is created on first use and then kept, so switching
    // tabs never reloads it. nodeterm owns the canvas and its tmux sessions.
    property bool canvasOpened: false
    readonly property string canvasOrigin: "http://127.0.0.1:8770"
    property var traceEntries: []

    color: "#020609"
    clip: true

    Action {
        id: copyAction

        text: "Copy"
        shortcut: "Ctrl+Shift+C"
        enabled: root.visible && root.activeTab === 0 && root.terminalConnected
        onTriggered: terminal.copyClipboard()
    }

    Action {
        id: pasteAction

        text: "Paste"
        shortcut: "Ctrl+Shift+V"
        enabled: copyAction.enabled
        onTriggered: {
            terminal.forceActiveFocus(Qt.ShortcutFocusReason)
            terminal.pasteClipboard()
        }
    }

    Shortcut {
        sequences: ["Ctrl+V", "Shift+Insert"]
        context: Qt.WindowShortcut
        enabled: pasteAction.enabled
        onActivated: pasteAction.trigger()
    }

    Menu {
        id: clipboardMenu

        parent: terminal
        font.family: "JetBrains Mono"
        font.pixelSize: 12
        palette.window: "#07151d"
        palette.base: "#07151d"
        palette.button: "#07151d"
        palette.text: "#b8f7ff"
        palette.buttonText: "#b8f7ff"
        palette.highlight: "#102a36"
        palette.highlightedText: "#cffafe"
        background: Rectangle {
            color: clipboardMenu.palette.window
            border.color: "#3367e8f9"
            radius: 4
        }
        onClosed: {
            if (terminal.visible) {
                terminal.forceActiveFocus(Qt.PopupFocusReason)
            }
        }
        MenuItem { action: copyAction }
        MenuItem { action: pasteAction }
    }

    function applyTrace(message) {
        if (typeof message !== "string" || message.length > 262144) {
            return
        }
        try {
            const payload = JSON.parse(message)
            if (payload.type === "snapshot" && Array.isArray(payload.entries)) {
                traceEntries = payload.entries.slice(-500)
            } else if (payload.type === "entry" && payload.entry) {
                traceEntries = traceEntries.concat([payload.entry]).slice(-500)
            }
        } catch (error) {
            console.warn("Ignored invalid action trace frame:", error)
        }
    }

    function traceColor(channel) {
        switch (channel) {
        case "tool": return "#fcd34d"
        case "result": return "#5eead4"
        case "error": return "#fb7185"
        case "status": return "#d8b4fe"
        default: return "#7dd3fc"
        }
    }

    Rectangle {
        id: tabBar

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 34
        color: "#59030a10"

        Row {
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom

            Repeater {
                model: ["LOCAL CONSOLE", "ACTION TRACE", "AGENT CANVAS"]

                delegate: Rectangle {
                    required property string modelData
                    required property int index

                    width: 132
                    height: tabBar.height
                    color: root.activeTab === index ? "#1822d3ee" : "transparent"

                    Rectangle {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.bottom: parent.bottom
                        height: 1
                        color: root.activeTab === parent.index
                            ? "#67e8f9" : "transparent"
                    }

                    Text {
                        anchors.centerIn: parent
                        text: parent.modelData
                        color: root.activeTab === parent.index
                            ? "#cffafe" : "#667dd3fc"
                        font.family: "JetBrainsMono Nerd Font Mono"
                        font.pixelSize: 9
                        font.letterSpacing: 1.2
                    }

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            root.activeTab = parent.index
                            if (root.activeTab === 0) {
                                terminal.forceActiveFocus(Qt.MouseFocusReason)
                            } else if (root.activeTab === 2) {
                                root.canvasOpened = true
                                if (canvasLoader.item)
                                    canvasLoader.item.forceActiveFocus(Qt.MouseFocusReason)
                            }
                        }
                    }
                }
            }
        }

        ToolButton {
            anchors.right: parent.right
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            visible: root.activeTab === 0
            enabled: pasteAction.enabled
            text: "CLIPBOARD"
            font.family: "JetBrains Mono"
            font.pixelSize: 9
            palette.buttonText: "#b8f7ff"
            background: Rectangle {
                color: parent.hovered ? "#1822d3ee" : "transparent"
            }
            onClicked: clipboardMenu.popup()
        }

        Text {
            anchors.right: parent.right
            anchors.rightMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            visible: root.activeTab === 1
            text: (root.traceConnected ? "LIVE" : "RECONNECTING")
                + "  ·  " + root.traceEntries.length + " ACTIONS"
            color: root.traceConnected ? "#805eead4" : "#80fcd34d"
            font.family: "JetBrainsMono Nerd Font Mono"
            font.pixelSize: 8
            font.letterSpacing: 1
        }

        Text {
            anchors.right: parent.right
            anchors.rightMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            visible: root.activeTab === 2
            text: "NODETERM  ·  TMUX -L NODE-TERMINAL"
            color: "#667dd3fc"
            font.family: "JetBrainsMono Nerd Font Mono"
            font.pixelSize: 8
            font.letterSpacing: 1
        }
    }

    Item {
        id: terminalArea

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: tabBar.bottom
        anchors.bottom: parent.bottom

        QMLTermWidget {
            id: terminal

            // Obsidience owns tmux sizing, so the viewport and grid follow
            // the pane together like a normal terminal.
            anchors.fill: parent
            anchors.margins: 4
            visible: root.activeTab === 0
            focus: visible
            colorScheme: "DarkPastels"
            font: Qt.font({
                // Installed fixed-pitch JetBrains Mono face. QMLTermWidget
                // cannot express the browser's CSS fallback-family list.
                family: "JetBrains Mono",
                pixelSize: 14,
                weight: Font.Normal
            })
            antialiasText: true
            useFBORendering: false
            blinkingCursor: true
            fullCursorHeight: true
            lineSpacing: 0
            onConfigureRequest: position => clipboardMenu.popup(position.x, position.y)

            // A terminal widget handles mouse selection itself; give keyboard
            // focus on press without consuming its selection or tmux mouse input.
            TapHandler {
                acceptedButtons: Qt.LeftButton
                gesturePolicy: TapHandler.DragThreshold
                onPressedChanged: {
                    if (pressed) {
                        terminal.forceActiveFocus(Qt.MouseFocusReason)
                    }
                }
            }

            session: QMLTermSession {
                id: terminalSession

                initialWorkingDirectory: "/home/wissenschafter"
                shellProgram: "/home/wissenschafter/Projects/obsidience/obsidience/shell/qml/panes/terminal/attach-shared-tmux"
                onFinished: root.terminalConnected = false
            }

            Component.onCompleted: {
                setBackgroundColor("#020609")
                setForegroundColor("#b8f7ff")
                terminalSession.startShellProgram()
                forceActiveFocus()
            }
        }

        Text {
            anchors.centerIn: parent
            visible: root.activeTab === 0 && !root.terminalConnected
            text: "TMUX SESSION CLOSED"
            color: "#9967e8f9"
            font.family: "JetBrainsMono Nerd Font Mono"
            font.pixelSize: 11
            font.letterSpacing: 2
        }

        Loader {
            id: canvasLoader

            // Optional provider: obsidience-shell-agent-canvas.service serves
            // nodeterm on loopback. Its login stays on (it rejects DNS-rebinding
            // pages); the pane answers it itself, and the named profile keeps
            // the session cookie across pane and Shell reloads.
            anchors.fill: parent
            active: root.canvasOpened
            visible: root.activeTab === 2
            onLoaded: item.forceActiveFocus(Qt.OtherFocusReason)

            sourceComponent: WebEngineView {
                id: canvasView

                property bool loadFailed: false

                url: root.canvasOrigin + "/"
                backgroundColor: "#020609"
                settings.errorPageEnabled: false
                settings.javascriptCanAccessClipboard: true
                settings.javascriptCanPaste: true
                profile: WebEngineProfile {
                    storageName: "obsidience-agent-canvas"
                    offTheRecord: false
                    persistentCookiesPolicy: WebEngineProfile.ForcePersistentCookies
                }

                onLoadingChanged: info => {
                    loadFailed = info.status === WebEngineView.LoadFailedStatus
                    // A rejected secret lands on /login?error=1 and is never retried.
                    if (info.status === WebEngineView.LoadSucceededStatus
                            && info.url.toString() === root.canvasOrigin + "/login"
                            && !canvasSignIn.running) {
                        canvasSignIn.view = canvasView
                        canvasSignIn.running = true
                    }
                }
                onNavigationRequested: request => {
                    if (!request.url.toString().startsWith(root.canvasOrigin + "/"))
                        request.action = WebEngineNavigationRequest.IgnoreRequest
                }
                onNewWindowRequested: request => {}
                onPermissionRequested: permission => {
                    // xterm.js copy/paste only; every other permission stays denied.
                    if (permission.origin.toString().startsWith(root.canvasOrigin)
                            && permission.permissionType === WebEnginePermission.PermissionType.ClipboardReadWrite)
                        permission.grant()
                    else
                        permission.deny()
                }
            }
        }

        Process {
            id: canvasSignIn

            // Machine secret seeded into nodeterm at install; never shown to the owner.
            property var view: null
            command: ["/usr/bin/systemd-creds", "decrypt", "--user", "--name=password",
                "/home/wissenschafter/.config/credentials/obsidience-agent-canvas-password.cred", "-"]
            stdout: StdioCollector {
                onStreamFinished: {
                    if (canvasSignIn.view && text.length > 0)
                        canvasSignIn.view.runJavaScript("(function(s){var f=document.querySelector('form[action=\"/auth/login\"]');"
                            + "var i=f&&f.querySelector('input[name=password]');if(i){i.value=s;f.submit();}})("
                            + JSON.stringify(text) + ")")
                    canvasSignIn.view = null
                }
            }
        }

        Button {
            anchors.centerIn: parent
            visible: root.activeTab === 2 && canvasLoader.item !== null && canvasLoader.item.loadFailed
            text: "Reconnect agent canvas"
            onClicked: canvasLoader.item.reload()
        }

        Rectangle {
            id: traceView

            anchors.fill: parent
            visible: root.activeTab === 1
            color: "#78020609"

            Row {
                id: traceControls

                anchors.right: parent.right
                anchors.rightMargin: 10
                anchors.top: parent.top
                anchors.topMargin: 8
                spacing: 8

                Text {
                    text: root.followTrace ? "FOLLOW ON" : "FOLLOW OFF"
                    color: root.followTrace ? "#995eead4" : "#667dd3fc"
                    font.family: "JetBrainsMono Nerd Font Mono"
                    font.pixelSize: 8

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.followTrace = !root.followTrace
                    }
                }

                Text {
                    text: "CLEAR"
                    color: "#667dd3fc"
                    font.family: "JetBrainsMono Nerd Font Mono"
                    font.pixelSize: 8

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.traceEntries = []
                    }
                }
            }

            ListView {
                id: traceList

                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: traceControls.bottom
                anchors.bottom: parent.bottom
                anchors.margins: 10
                clip: true
                spacing: 5
                model: root.traceEntries
                onCountChanged: {
                    if (root.followTrace) {
                        positionViewAtEnd()
                    }
                }

                delegate: Item {
                    id: traceEntry

                    required property var modelData
                    width: traceList.width
                    height: traceLine.implicitHeight
                        + (details.visible ? details.implicitHeight + 3 : 0)

                    Text {
                        id: traceLine

                        anchors.left: parent.left
                        anchors.right: parent.right
                        text: new Date(traceEntry.modelData.at).toLocaleTimeString()
                            + "  [" + String(traceEntry.modelData.channel).toUpperCase()
                            + "]  " + String(traceEntry.modelData.line)
                        color: root.traceColor(traceEntry.modelData.channel)
                        font.family: "JetBrainsMono Nerd Font Mono"
                        font.pixelSize: 10
                        wrapMode: Text.Wrap
                    }

                    Text {
                        id: details

                        anchors.left: parent.left
                        anchors.leftMargin: 88
                        anchors.right: parent.right
                        anchors.top: traceLine.bottom
                        anchors.topMargin: 3
                        visible: Array.isArray(traceEntry.modelData.detail)
                            && traceEntry.modelData.detail.length > 0
                        text: visible ? traceEntry.modelData.detail.join("\n") : ""
                        color: "#737dd3fc"
                        font.family: "JetBrainsMono Nerd Font Mono"
                        font.pixelSize: 9
                        wrapMode: Text.Wrap
                    }
                }

                ScrollBar.vertical: ScrollBar {}
            }
        }
    }

    WebSocket {
        id: traceSocket

        url: "ws://127.0.0.1:8765/ws/trace"
        active: true
        onTextMessageReceived: message => root.applyTrace(message)
        onStatusChanged: status => {
            root.traceConnected = status === WebSocket.Open
            if (status === WebSocket.Closed || status === WebSocket.Error) {
                traceReconnect.restart()
            }
        }
    }

    Timer {
        id: traceReconnect

        interval: 1500
        repeat: false
        onTriggered: {
            traceSocket.active = false
            traceSocket.active = true
        }
    }
}
