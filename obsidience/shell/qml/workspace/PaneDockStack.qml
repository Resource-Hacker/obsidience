pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls

Item {
    id: root

    required property string side
    required property string hostPaneId
    required property string surfaceId
    required property PaneDockLayout dockLayout
    required property var paneDefinitions
    required property real availableWidth

    signal commandRequested(var command)

    readonly property int stateRevision: dockLayout.revision
    readonly property var activeModules: {
        const currentRevision = stateRevision
        return dockLayout.modulesFor(hostPaneId, side, false)
    }
    readonly property var collapsedModules: {
        const currentRevision = stateRevision
        return dockLayout.modulesFor(hostPaneId, side, true)
    }
    readonly property bool hasModules: activeModules.length > 0
        || collapsedModules.length > 0

    visible: hasModules
    width: !hasModules ? 0 : activeModules.length > 0
        ? Math.min(380, Math.max(240, availableWidth * 0.30)) : 28

    function definitionFor(paneId) {
        for (const definition of paneDefinitions) {
            if (definition.placement.paneId === paneId) {
                return definition
            }
        }
        return null
    }

    function expand(paneId) {
        commandRequested({
            "schema": "obsidience.shell.command.v1",
            "type": "pane.expand",
            "pane_id": paneId,
            "host_pane_id": hostPaneId,
            "surface_id": surfaceId,
            "expected_revision": dockLayout.revision
        })
    }

    Row {
        anchors.fill: parent
        layoutDirection: root.side === "left"
            ? Qt.LeftToRight : Qt.RightToLeft

        Rectangle {
            id: collapsedRail

            visible: root.collapsedModules.length > 0
            width: visible ? 28 : 0
            height: parent.height
            color: root.side === "left" ? "#bf020a12" : "#c708050f"

            Rectangle {
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.right: root.side === "left" ? parent.right : undefined
                anchors.left: root.side === "right" ? parent.left : undefined
                width: 1
                color: root.side === "left" ? "#1f67e8f9" : "#1fc4b5fd"
            }

            Column {
                anchors.top: parent.top
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.topMargin: 8
                spacing: 4

                Repeater {
                    model: root.collapsedModules

                    delegate: Rectangle {
                        id: railButton

                        required property var modelData
                        readonly property color tint: modelData.pane_id === "knowledge"
                            ? "#67e8f9" : "#c4b5fd"
                        width: 20
                        height: 20
                        radius: 4
                        color: railMouse.containsMouse
                            ? Qt.rgba(tint.r, tint.g, tint.b, 0.10)
                            : "transparent"
                        border.width: 1
                        border.color: Qt.rgba(
                            tint.r, tint.g, tint.b,
                            railMouse.containsMouse ? 0.40 : 0.15
                        )

                        Text {
                            anchors.centerIn: parent
                            text: railButton.modelData.pane_id === "knowledge"
                                ? "▤" : "◫"
                            color: Qt.rgba(
                                railButton.tint.r,
                                railButton.tint.g,
                                railButton.tint.b,
                                railMouse.containsMouse ? 0.95 : 0.48
                            )
                            font.family: "JetBrains Mono"
                            font.pixelSize: 10
                        }

                        MouseArea {
                            id: railMouse

                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.expand(railButton.modelData.pane_id)

                            ToolTip.visible: containsMouse
                            ToolTip.delay: 400
                            ToolTip.text: "Open " + railButton.modelData.pane_id
                        }
                    }
                }
            }
        }

        Item {
            id: activeArea

            visible: root.activeModules.length > 0
            width: visible ? root.width - collapsedRail.width : 0
            height: parent.height

            Rectangle {
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.right: root.side === "left" ? parent.right : undefined
                anchors.left: root.side === "right" ? parent.left : undefined
                width: 1
                color: root.side === "left" ? "#1f67e8f9" : "#1fc4b5fd"
                z: 2
            }

            Column {
                anchors.fill: parent

                Repeater {
                    model: root.activeModules

                    delegate: Item {
                        id: moduleSlot

                        required property int index
                        required property var modelData
                        readonly property var definition: root.definitionFor(
                            modelData.pane_id
                        )
                        width: activeArea.width
                        height: activeArea.height / Math.max(
                            1, root.activeModules.length
                        )

                        Rectangle {
                            visible: moduleSlot.index > 0
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            height: 1
                            color: "#1a67e8f9"
                            z: 3
                        }

                        Loader {
                            anchors.fill: parent
                            active: moduleSlot.definition !== null
                            sourceComponent: moduleSlot.definition
                                ? moduleSlot.definition.component : null
                        }
                    }
                }
            }
        }
    }
}
