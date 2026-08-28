pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Effects

Item {
    id: root

    required property string title
    required property string surfaceLabel
    required property int revision

    signal dragStarted()
    signal dragMoved(real deltaX, real deltaY)
    signal dragFinished(bool moved)

    Rectangle {
        id: frame

        anchors.fill: parent
        anchors.margins: 18
        radius: 12
        color: "#eb030a10"
        border.width: 1
        border.color: "#4037d7ee"
        clip: true

        layer.enabled: true
        layer.effect: MultiEffect {
            shadowEnabled: true
            shadowColor: "#2822d3ee"
            shadowBlur: 0.75
            shadowScale: 1.015
        }

        Rectangle {
            id: titleBar

            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: 38
            color: "#120ea5b7"

            property bool moved: false

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 1
                color: "#2637d7ee"
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

            Row {
                anchors.right: parent.right
                anchors.rightMargin: 12
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8

                Text {
                    text: root.surfaceLabel
                    color: "#8ba5f3fc"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 9
                    font.capitalization: Font.AllUppercase
                    font.letterSpacing: 1.4
                }

                Rectangle {
                    width: 7
                    height: 7
                    radius: 4
                    color: "#22d3ee"
                    opacity: 0.8
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
                    root.dragMoved(deltaX, deltaY)
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
                    color: "#e2e8f0"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 16
                    font.weight: Font.Medium
                    font.letterSpacing: 1.1
                }

                Text {
                    width: parent.width
                    wrapMode: Text.WordWrap
                    text: "This is one logical Obsidience pane rendered by the active Surface. Drag its title bar through the Samsung bottom-middle edge or the USB-C top edge to transfer ownership."
                    color: "#a9cbd5df"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 11
                    lineHeight: 1.55
                }

                Rectangle {
                    width: parent.width
                    height: 1
                    color: "#1937d7ee"
                }

                Row {
                    spacing: 26

                    Column {
                        spacing: 5

                        Text {
                            text: "ACTIVE SURFACE"
                            color: "#708ba5b7"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 9
                            font.letterSpacing: 1.3
                        }
                        Text {
                            text: root.surfaceLabel
                            color: "#67e8f9"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 12
                            font.capitalization: Font.AllUppercase
                        }
                    }

                    Column {
                        spacing: 5

                        Text {
                            text: "PLACEMENT REVISION"
                            color: "#708ba5b7"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 9
                            font.letterSpacing: 1.3
                        }
                        Text {
                            text: String(root.revision).padStart(3, "0")
                            color: "#d8f7fb"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 12
                        }
                    }
                }
            }
        }
    }
}
