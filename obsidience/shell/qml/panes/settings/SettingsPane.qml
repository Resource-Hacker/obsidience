pragma ComponentBehavior: Bound

import QtQuick
import QtWebSockets
import "graph"
import "input"
import "workspace"
import "connections"
import "ai_voice"

Item {
    id: root

    property string activeSection: "graph"
    property int selectionRevision: -1
    readonly property var sections: [
        {"id": "graph", "label": "Graph", "accent": "#fb923c"},
        {"id": "input", "label": "Input", "accent": "#a3e635"},
        {"id": "workspace", "label": "Workspace", "accent": "#67e8f9"},
        {"id": "connections", "label": "Connections", "accent": "#38bdf8"},
        {"id": "ai-voice", "label": "AI & Voice", "accent": "#c4b5fd"}
    ]

    function selectSection(section) {
        if (!sections.some(item => item.id === section)
                || settingsSocket.status !== WebSocket.Open) return
        settingsSocket.sendTextMessage(JSON.stringify({
            "schema": "obsidience.shell.command.v1", "type": "pane.present",
            "pane_id": "settings", "selection": {"kind": "settings", "section": section}
        }))
    }

    function applyShellEvent(message) {
        if (typeof message !== "string" || message.length > 65536) return
        let event
        try { event = JSON.parse(message) } catch (error) { return }
        if (!event || event.schema !== "obsidience.shell.event.v1"
                || event.type !== "pane.selection" || event.pane_id !== "settings"
                || !Number.isSafeInteger(event.revision) || event.revision < 0
                || event.revision <= selectionRevision
                || !event.selection || event.selection.kind !== "settings"
                || !sections.some(item => item.id === event.selection.section)) return
        selectionRevision = event.revision
        activeSection = event.selection.section
    }

    WebSocket {
        id: settingsSocket
        url: "ws://127.0.0.1:8768"
        requestedSubprotocols: ["obsidience.shell.v1"]
        active: true
        onTextMessageReceived: message => root.applyShellEvent(message)
        onStatusChanged: status => {
            if (status === WebSocket.Closed || status === WebSocket.Error) reconnect.restart()
        }
    }
    Timer {
        id: reconnect
        interval: 500
        repeat: false
        onTriggered: { settingsSocket.active = false; settingsSocket.active = true }
    }

    Rectangle {
        id: sectionRail

        anchors.left: parent.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        width: 148
        color: "#d903080e"
        border.width: 1
        border.color: "#2638bdf8"

        Column {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 10
            spacing: 8

            Repeater {
                model: root.sections

                delegate: Rectangle {
                    id: sectionButton

                    required property var modelData
                    width: parent.width
                    height: 38
                    radius: 4
                    color: root.activeSection === modelData.id
                        ? "#2422d3ee"
                        : sectionMouse.containsMouse ? "#12167c96" : "transparent"
                    border.width: 1
                    border.color: root.activeSection === modelData.id
                        ? modelData.accent : "#1f67e8f9"

                    Rectangle {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        width: 2
                        color: sectionButton.modelData.accent
                        visible: root.activeSection === sectionButton.modelData.id
                    }

                    Text {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.leftMargin: 10
                        anchors.rightMargin: 8
                        text: sectionButton.modelData.label
                        color: root.activeSection === sectionButton.modelData.id
                            ? "#e6f9fe" : "#9bbae6ee"
                        elide: Text.ElideRight
                        font.pixelSize: 14
                    }

                    MouseArea {
                        id: sectionMouse
                        anchors.fill: parent
                        enabled: settingsSocket.status === WebSocket.Open
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.selectSection(sectionButton.modelData.id)
                    }
                }
            }
        }
    }

    Loader {
        anchors.left: sectionRail.right
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.leftMargin: 8
        sourceComponent: root.activeSection === "ai-voice"
            ? aiVoiceSettingsComponent
            : root.activeSection === "connections" ? connectionsSettingsComponent
            : root.activeSection === "workspace" ? workspaceSettingsComponent
            : root.activeSection === "input"
                ? inputSettingsComponent : graphSettingsComponent
    }

    Component {
        id: aiVoiceSettingsComponent

        AiVoiceSettings {}
    }

    Component {
        id: connectionsSettingsComponent

        ConnectionsSettings {}
    }

    Component {
        id: graphSettingsComponent

        GraphSettings {}
    }

    Component {
        id: inputSettingsComponent

        InputSettings {}
    }

    Component {
        id: workspaceSettingsComponent

        WorkspaceSettings {}
    }
}
