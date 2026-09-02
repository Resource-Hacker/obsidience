pragma ComponentBehavior: Bound

import QtQuick
import "../../api"

Item {
    id: root

    required property SurfaceLayout surfaceLayout

    readonly property real mapWidth: 5120
    readonly property real mapHeight: 3000
    readonly property real mapScale: Math.max(0.01, Math.min(
        (canvas.width - 40) / mapWidth,
        (canvas.height - 40) / mapHeight
    ))
    readonly property real mapOriginX: (canvas.width - mapWidth * mapScale) / 2
    readonly property real mapOriginY: (canvas.height - mapHeight * mapScale) / 2

    Text {
        id: introduction

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.leftMargin: 22
        anchors.rightMargin: 22
        anchors.topMargin: 16
        text: "DRAG SURFACES TO DEFINE TOUCHING EDGES"
        color: "#a6cffafe"
        font.family: "JetBrains Mono"
        font.pixelSize: 10
        font.letterSpacing: 1.3
        horizontalAlignment: Text.AlignHCenter
    }

    Item {
        id: canvas

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: introduction.bottom
        anchors.bottom: footer.top
        anchors.margins: 12
        clip: true

        Repeater {
            model: root.surfaceLayout.surfaces

            delegate: Rectangle {
                id: surfaceBox

                required property var modelData
                property real dragOffsetX: 0
                property real dragOffsetY: 0

                x: root.mapOriginX + modelData.map_rect.x * root.mapScale
                    + dragOffsetX
                y: root.mapOriginY + modelData.map_rect.y * root.mapScale
                    + dragOffsetY
                width: Math.max(90, modelData.map_rect.width * root.mapScale)
                height: Math.max(48, modelData.map_rect.height * root.mapScale)
                z: dragArea.pressed ? 10 : 0
                radius: 8
                color: dragArea.pressed ? "#2634d399" : "#1722d3ee"
                border.width: 1
                border.color: dragArea.pressed ? "#a6cffafe" : "#7367e8f9"

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    height: 2
                    color: "#67e8f9"
                    visible: root.surfaceLayout.touching(
                        surfaceBox.modelData.id,
                        "top"
                    )
                }

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: 2
                    color: "#67e8f9"
                    visible: root.surfaceLayout.touching(
                        surfaceBox.modelData.id,
                        "bottom"
                    )
                }

                Rectangle {
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    width: 2
                    color: "#67e8f9"
                    visible: root.surfaceLayout.touching(
                        surfaceBox.modelData.id,
                        "left"
                    )
                }

                Rectangle {
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    width: 2
                    color: "#67e8f9"
                    visible: root.surfaceLayout.touching(
                        surfaceBox.modelData.id,
                        "right"
                    )
                }

                Column {
                    anchors.centerIn: parent
                    width: parent.width - 14
                    spacing: 3

                    Text {
                        width: parent.width
                        text: surfaceBox.modelData.label
                        color: "#cffafe"
                        elide: Text.ElideRight
                        horizontalAlignment: Text.AlignHCenter
                        font.family: "JetBrains Mono"
                        font.pixelSize: 11
                        font.weight: Font.Medium
                        font.capitalization: Font.AllUppercase
                        font.letterSpacing: 1.0
                    }

                    Text {
                        width: parent.width
                        text: surfaceBox.modelData.pixel_width + " × "
                            + surfaceBox.modelData.pixel_height
                        color: "#9967e8f9"
                        horizontalAlignment: Text.AlignHCenter
                        font.family: "JetBrains Mono"
                        font.pixelSize: 9
                    }

                    Text {
                        width: parent.width
                        text: surfaceBox.modelData.id + " · "
                            + surfaceBox.modelData.backend
                        color: "#7367e8f9"
                        elide: Text.ElideRight
                        horizontalAlignment: Text.AlignHCenter
                        font.family: "JetBrains Mono"
                        font.pixelSize: 8
                        font.capitalization: Font.AllUppercase
                    }
                }

                MouseArea {
                    id: dragArea

                    anchors.fill: parent
                    acceptedButtons: Qt.LeftButton
                    preventStealing: true
                    cursorShape: pressed ? Qt.ClosedHandCursor : Qt.OpenHandCursor

                    property point pressCanvas: Qt.point(0, 0)
                    property real startX: 0
                    property real startY: 0

                    onPressed: mouse => {
                        surfaceBox.dragOffsetX = 0
                        surfaceBox.dragOffsetY = 0
                        pressCanvas = mapToItem(canvas, mouse.x, mouse.y)
                        startX = surfaceBox.modelData.map_rect.x
                        startY = surfaceBox.modelData.map_rect.y
                    }
                    onPositionChanged: mouse => {
                        if (!pressed) {
                            return
                        }
                        const pointer = mapToItem(canvas, mouse.x, mouse.y)
                        surfaceBox.dragOffsetX = pointer.x - pressCanvas.x
                        surfaceBox.dragOffsetY = pointer.y - pressCanvas.y
                    }
                    onReleased: {
                        const targetX = startX
                            + surfaceBox.dragOffsetX / root.mapScale
                        const targetY = startY
                            + surfaceBox.dragOffsetY / root.mapScale
                        surfaceBox.dragOffsetX = 0
                        surfaceBox.dragOffsetY = 0
                        root.surfaceLayout.commitSurfaceAt(
                            surfaceBox.modelData.id,
                            targetX,
                            targetY
                        )
                    }
                    onCanceled: {
                        surfaceBox.dragOffsetX = 0
                        surfaceBox.dragOffsetY = 0
                    }
                }
            }
        }
    }

    Text {
        id: footer

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.leftMargin: 18
        anchors.rightMargin: 18
        anchors.bottomMargin: 14
        text: "CYAN EDGES ARE ACTIVE · REVISION "
            + String(root.surfaceLayout.revision).padStart(3, "0")
        color: "#7367e8f9"
        font.family: "JetBrains Mono"
        font.pixelSize: 9
        font.letterSpacing: 1.0
        horizontalAlignment: Text.AlignHCenter
    }
}
