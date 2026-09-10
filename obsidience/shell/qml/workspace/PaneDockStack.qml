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
            if (definition.placement.paneId === paneId) return definition
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

    Repeater {
        // Slots keep their physical half even when a sibling is empty or
        // collapsed. A hidden module still owns its chosen slot.
        model: [0, 1]

        delegate: Item {
            id: moduleSlot

            required property int modelData
            readonly property var slot: {
                const currentRevision = root.stateRevision
                return root.dockLayout.slotState(root.hostPaneId, root.side, modelData)
            }
            readonly property var definition: slot ? root.definitionFor(slot.pane_id) : null
            readonly property color tint: definition ? definition.accent : "#64748b"
            x: 0
            y: modelData * root.height / 2
            width: root.width
            height: root.height / 2
            clip: true

            Rectangle {
                anchors.fill: parent
                color: root.side === "left" ? "#bf020a12" : "#c708050f"
            }

            Rectangle {
                visible: moduleSlot.modelData === 1
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: 1
                color: "#2467e8f9"
                z: 3
            }

            Text {
                visible: !moduleSlot.slot && root.width > 28
                anchors.centerIn: parent
                text: "Empty dock"
                color: "#526174"
                font.family: "JetBrains Mono"
                font.pixelSize: 10
            }

            Loader {
                anchors.fill: parent
                active: !!moduleSlot.definition && !moduleSlot.slot.collapsed
                sourceComponent: active ? moduleSlot.definition.component : null
            }

            Rectangle {
                visible: !!moduleSlot.slot && moduleSlot.slot.collapsed
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: 28
                color: expandMouse.containsMouse ? "#203448" : "#111e2c"

                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.side === "left" ? "›" : "‹"
                    color: moduleSlot.tint
                    font.pixelSize: 15
                }
                Text {
                    visible: root.width > 28
                    anchors.left: parent.left
                    anchors.leftMargin: 28
                    anchors.right: parent.right
                    anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    text: moduleSlot.definition ? moduleSlot.definition.title : ""
                    textFormat: Text.PlainText
                    color: moduleSlot.tint
                    elide: Text.ElideRight
                    font.pixelSize: 11
                }
                MouseArea {
                    id: expandMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.expand(moduleSlot.slot.pane_id)
                    ToolTip.visible: containsMouse
                    ToolTip.delay: 400
                    ToolTip.text: "Expand " + (moduleSlot.definition ? moduleSlot.definition.title : "pane")
                }
            }
        }
    }

    Rectangle {
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.right: root.side === "left" ? parent.right : undefined
        anchors.left: root.side === "right" ? parent.left : undefined
        width: 1
        color: root.side === "left" ? "#1f67e8f9" : "#1fc4b5fd"
        z: 2
    }
}
