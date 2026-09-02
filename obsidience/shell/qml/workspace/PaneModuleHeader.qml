pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls

Item {
    id: root

    required property string moduleId
    required property string title
    required property color tint
    required property PaneDockLayout dockLayout
    required property string surfaceId
    property string countText: ""

    signal commandRequested(var command)

    readonly property var dockState: dockLayout.moduleState(moduleId)
    readonly property bool docked: dockLayout.isDocked(moduleId)
    readonly property string placement: docked ? dockState.side : "floating"
    readonly property var controlModel: docked ? [
        {
            "action": "float",
            "glyph": "↗",
            "label": "Detach " + moduleId + " pane"
        },
        {
            "action": "collapse",
            "glyph": placement === "left" ? "‹" : "›",
            "label": "Collapse " + moduleId
        }
    ] : [
        {
            "action": "dock-left",
            "glyph": "◧",
            "label": "Dock " + moduleId + " left"
        },
        {
            "action": "dock-right",
            "glyph": "◨",
            "label": "Dock " + moduleId + " right"
        }
    ]

    implicitHeight: 22

    function baseCommand(type) {
        return {
            "schema": "obsidience.shell.command.v1",
            "type": type,
            "pane_id": moduleId,
            "host_pane_id": "reader",
            "surface_id": surfaceId,
            "expected_revision": dockLayout.revision
        }
    }

    function invoke(action) {
        if (action === "float") {
            commandRequested(baseCommand("pane.float"))
            return
        }
        if (action === "collapse") {
            commandRequested(baseCommand("pane.collapse"))
            return
        }
        const command = baseCommand("pane.dock")
        command.side = action === "dock-left" ? "left" : "right"
        command.position = "bottom"
        commandRequested(command)
    }

    Row {
        id: dragLabel

        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        spacing: 4

        Text {
            visible: root.docked
            text: "⋮"
            color: Qt.rgba(root.tint.r, root.tint.g, root.tint.b, 0.40)
            font.family: "JetBrains Mono"
            font.pixelSize: 10
        }

        Text {
            text: root.title
            color: Qt.rgba(root.tint.r, root.tint.g, root.tint.b, 0.55)
            font.family: "JetBrains Mono"
            font.pixelSize: 8
            font.capitalization: Font.AllUppercase
            font.letterSpacing: 1.44
        }
    }

    MouseArea {
        id: dragArea

        anchors.left: parent.left
        anchors.right: controls.left
        anchors.top: parent.top
        anchors.bottom: parent.bottom
        anchors.rightMargin: 4
        enabled: root.docked
        hoverEnabled: root.docked
        acceptedButtons: Qt.LeftButton
        preventStealing: true
        cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor

        property point pressGlobal: Qt.point(0, 0)
        property bool dragAnnounced: false

        onPressed: mouse => {
            pressGlobal = dragArea.mapToGlobal(mouse.x, mouse.y)
            dragAnnounced = false
        }
        onPositionChanged: mouse => {
            if (!pressed) {
                return
            }
            const point = dragArea.mapToGlobal(mouse.x, mouse.y)
            if (!dragAnnounced && (Math.abs(point.x - pressGlobal.x) > 4
                    || Math.abs(point.y - pressGlobal.y) > 4)) {
                dragAnnounced = true
                const command = root.baseCommand("pane.dock.drag.start")
                root.commandRequested(command)
            }
        }
        onReleased: mouse => {
            if (!dragAnnounced) {
                return
            }
            const point = dragArea.mapToGlobal(mouse.x, mouse.y)
            const command = root.baseCommand("pane.dock.drag.finish")
            command.pointer = {"x": point.x, "y": point.y}
            root.commandRequested(command)
            dragAnnounced = false
        }
        onCanceled: {
            if (dragAnnounced) {
                root.commandRequested(root.baseCommand("pane.dock.drag.cancel"))
            }
            dragAnnounced = false
        }

        ToolTip.visible: containsMouse && !pressed
        ToolTip.delay: 500
        ToolTip.text: "Drag to dock, stack, or detach"
    }

    Row {
        id: controls

        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: 4

        Text {
            anchors.verticalCenter: parent.verticalCenter
            visible: root.countText !== ""
            text: root.countText
            color: Qt.rgba(root.tint.r, root.tint.g, root.tint.b, 0.48)
            font.family: "JetBrains Mono"
            font.pixelSize: 8
            font.letterSpacing: 0.8
        }

        Repeater {
            model: root.controlModel

            delegate: Rectangle {
                id: controlButton

                required property var modelData
                width: 16
                height: 16
                radius: 4
                color: controlMouse.containsMouse
                    ? Qt.rgba(root.tint.r, root.tint.g, root.tint.b, 0.10)
                    : "transparent"
                border.width: 1
                border.color: Qt.rgba(
                    root.tint.r,
                    root.tint.g,
                    root.tint.b,
                    controlMouse.containsMouse ? 0.40 : 0.15
                )

                Text {
                    anchors.centerIn: parent
                    text: controlButton.modelData.glyph
                    color: Qt.rgba(
                        root.tint.r,
                        root.tint.g,
                        root.tint.b,
                        controlMouse.containsMouse ? 0.95 : 0.48
                    )
                    font.family: "JetBrains Mono"
                    font.pixelSize: 10
                }

                MouseArea {
                    id: controlMouse

                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.invoke(controlButton.modelData.action)

                    ToolTip.visible: containsMouse
                    ToolTip.delay: 400
                    ToolTip.text: controlButton.modelData.label
                }
            }
        }
    }
}
