pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtWebSockets
import QMLTermWidget 2.0

Rectangle {
    id: root

    property int activeTab: 0
    property bool terminalConnected: true
    property bool traceConnected: false
    property bool followTrace: true
    property var traceEntries: []

    color: "#020609"
    clip: true

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
                model: ["LOCAL CONSOLE", "ACTION TRACE"]

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
                        onClicked: root.activeTab = parent.index
                    }
                }
            }
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
