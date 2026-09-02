pragma ComponentBehavior: Bound

import QtQuick
import "graph"
import "input"
import "workspace"

Item {
    id: root

    property string activeSection: "graph"
    readonly property var sections: [
        {"id": "graph", "label": "Graph", "accent": "#fb923c"},
        {"id": "input", "label": "Input", "accent": "#a3e635"},
        {"id": "workspace", "label": "Workspace", "accent": "#67e8f9"}
    ]

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

            Text {
                text: "SETTINGS"
                color: "#8ba5f3fc"
                font.family: "JetBrains Mono"
                font.pixelSize: 8
                font.letterSpacing: 1.7
            }

            Repeater {
                model: root.sections

                delegate: Rectangle {
                    id: sectionButton

                    required property var modelData
                    width: parent.width
                    height: 34
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
                        text: String(sectionButton.modelData.label).toUpperCase()
                        color: root.activeSection === sectionButton.modelData.id
                            ? "#e6f9fe" : "#9bbae6ee"
                        elide: Text.ElideRight
                        font.family: "JetBrains Mono"
                        font.pixelSize: 9
                        font.letterSpacing: 1.2
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

    Loader {
        anchors.left: sectionRail.right
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.leftMargin: 8
        sourceComponent: root.activeSection === "workspace"
            ? workspaceSettingsComponent
            : root.activeSection === "input"
                ? inputSettingsComponent : graphSettingsComponent
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
