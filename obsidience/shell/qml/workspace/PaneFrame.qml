pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Effects

Item {
    id: root

    required property string title
    required property string surfaceLabel
    required property int revision

    signal dragStarted()
    signal dragMoved(real deltaX, real deltaY, real pointerX, real pointerY)
    signal dragFinished(bool moved)

    Rectangle {
        id: frame

        anchors.fill: parent
        radius: 12
        color: "#eb030a10"
        border.width: 1
        border.color: "#4067e8f9"
        clip: true

        layer.enabled: true
        layer.effect: MultiEffect {
            shadowEnabled: true
            shadowColor: "#22d3ee"
            shadowOpacity: 0.08
            shadowBlur: 0.75
            shadowScale: 1.0
        }

        Rectangle {
            id: titleBar

            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 32
            color: "transparent"

            property bool moved: false

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 1
                color: "#2667e8f9"
            }

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 13
                anchors.verticalCenter: parent.verticalCenter
                text: root.title
                color: "#cffafe"
                font.family: "JetBrains Mono"
                font.pixelSize: 10
                font.capitalization: Font.AllUppercase
                font.letterSpacing: 2.2
            }

            Rectangle {
                anchors.right: parent.right
                anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                width: 24
                height: 17
                radius: 4
                color: "transparent"
                border.width: 1
                border.color: "#4067e8f9"

                Text {
                    anchors.centerIn: parent
                    text: "×"
                    color: "#9967e8f9"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 10
                }
            }

            MouseArea {
                id: dragArea

                anchors.fill: parent
                acceptedButtons: Qt.LeftButton
                preventStealing: true
                cursorShape: Qt.OpenHandCursor

                property point pressGlobal: Qt.point(0, 0)

                onPressed: mouse => {
                    titleBar.moved = false
                    pressGlobal = titleBar.mapToGlobal(mouse.x, mouse.y)
                    cursorShape = Qt.ClosedHandCursor
                    root.dragStarted()
                }
                onPositionChanged: mouse => {
                    if (!dragArea.pressed) {
                        return
                    }
                    const pointer = titleBar.mapToGlobal(mouse.x, mouse.y)
                    const deltaX = pointer.x - pressGlobal.x
                    const deltaY = pointer.y - pressGlobal.y
                    if (Math.abs(deltaX) > 0 || Math.abs(deltaY) > 0) {
                        titleBar.moved = true
                    }
                    const localPointer = dragArea.mapToItem(
                        root,
                        mouse.x,
                        mouse.y
                    )
                    root.dragMoved(
                        deltaX,
                        deltaY,
                        localPointer.x,
                        localPointer.y
                    )
                }
                onReleased: {
                    cursorShape = Qt.OpenHandCursor
                    root.dragFinished(titleBar.moved)
                }
                onCanceled: {
                    cursorShape = Qt.OpenHandCursor
                    root.dragFinished(titleBar.moved)
                }
            }
        }

        Item {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: titleBar.bottom
            anchors.bottom: parent.bottom

            Column {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 24
                spacing: 15

                Text {
                    text: "ONE PANE · ONE OWNER"
                    color: "#cffafe"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 16
                    font.weight: Font.Medium
                    font.letterSpacing: 1.1
                }

                Text {
                    width: parent.width
                    wrapMode: Text.WordWrap
                    text: "This is one logical Obsidience pane rendered by the active Surface. Drag its title bar through the Samsung bottom-middle edge or the USB-C top edge to transfer ownership."
                    color: "#8c67e8f9"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 11
                    lineHeight: 1.55
                }

                Rectangle {
                    width: parent.width
                    height: 1
                    color: "#1a67e8f9"
                }

                Row {
                    spacing: 26

                    Column {
                        spacing: 5

                        Text {
                            text: "ACTIVE SURFACE"
                            color: "#7367e8f9"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 9
                            font.letterSpacing: 1.3
                        }
                        Text {
                            text: root.surfaceLabel
                            color: "#9967e8f9"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 12
                            font.capitalization: Font.AllUppercase
                        }
                    }

                    Column {
                        spacing: 5

                        Text {
                            text: "PLACEMENT REVISION"
                            color: "#7367e8f9"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 9
                            font.letterSpacing: 1.3
                        }
                        Text {
                            text: String(root.revision).padStart(3, "0")
                            color: "#a6cffafe"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 12
                        }
                    }
                }
            }
        }
    }
}
