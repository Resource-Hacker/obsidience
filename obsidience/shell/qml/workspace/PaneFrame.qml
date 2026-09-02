pragma ComponentBehavior: Bound

import QtQuick
import Quickshell.Widgets
import "../api"

Item {
    id: root

    required property string title
    required property ShellTheme theme
    default property alias contentData: content.data

    signal dragStarted()
    signal dragMoved(real deltaX, real deltaY, real pointerX, real pointerY)
    signal dragFinished(bool moved)
    signal resizeStarted()
    signal resizeMoved(real deltaX, real deltaY)
    signal resizeFinished(bool moved)
    signal closeRequested()

    ClippingRectangle {
        id: frame

        anchors.fill: parent
        radius: root.theme.cornerRadius
        color: root.theme.surface
        border.width: root.theme.borderWidth
        border.color: root.theme.accent
        contentUnderBorder: true

        Rectangle {
            id: titleBar

            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: root.theme.titleHeight
            color: "transparent"

            property bool moved: false

            Rectangle {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                height: 1
                color: root.theme.separator
            }

            Text {
                anchors.left: parent.left
                anchors.leftMargin: 13
                anchors.verticalCenter: parent.verticalCenter
                text: root.title
                color: root.theme.text
                font.family: root.theme.titleFont
                font.pixelSize: root.theme.titleFontSize
                font.capitalization: Font.AllUppercase
                font.letterSpacing: root.theme.titleLetterSpacing
            }

            Rectangle {
                id: closeButton

                anchors.right: parent.right
                anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                width: 24
                height: 17
                radius: 4
                color: closeMouse.containsMouse ? root.theme.hover : "transparent"
                border.width: root.theme.borderWidth
                border.color: root.theme.accent

                Text {
                    anchors.centerIn: parent
                    text: "×"
                    color: closeMouse.containsMouse ? root.theme.text : root.theme.muted
                    font.family: root.theme.titleFont
                    font.pixelSize: root.theme.titleFontSize
                }

                MouseArea {
                    id: closeMouse

                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.closeRequested()
                }
            }

            MouseArea {
                id: dragArea

                anchors.left: parent.left
                anchors.right: closeButton.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
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
            id: content

            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: titleBar.bottom
            anchors.bottom: parent.bottom
        }

        Item {
            id: resizeHandle

            anchors.right: parent.right
            anchors.bottom: parent.bottom
            width: 22
            height: 22

            Rectangle {
                anchors.right: parent.right
                anchors.bottom: parent.bottom
                anchors.rightMargin: 4
                anchors.bottomMargin: 4
                width: 8
                height: 8
                color: "transparent"
                border.width: 0

                Rectangle {
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    width: 2
                    height: parent.height
                    color: root.theme.strongAccent
                }

                Rectangle {
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    width: parent.width
                    height: 2
                    color: root.theme.strongAccent
                }
            }

            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton
                preventStealing: true
                cursorShape: Qt.SizeFDiagCursor

                property point pressGlobal: Qt.point(0, 0)
                property bool moved: false

                onPressed: mouse => {
                    moved = false
                    pressGlobal = resizeHandle.mapToGlobal(mouse.x, mouse.y)
                    root.resizeStarted()
                }
                onPositionChanged: mouse => {
                    if (!pressed) {
                        return
                    }
                    const pointer = resizeHandle.mapToGlobal(mouse.x, mouse.y)
                    const deltaX = pointer.x - pressGlobal.x
                    const deltaY = pointer.y - pressGlobal.y
                    if (Math.abs(deltaX) > 0 || Math.abs(deltaY) > 0) {
                        moved = true
                    }
                    root.resizeMoved(deltaX, deltaY)
                }
                onReleased: root.resizeFinished(moved)
                onCanceled: root.resizeFinished(moved)
            }
        }
    }

    // Keep the five-pixel outline in the pane's ordinary scene subtree so the
    // complete chrome follows PaneItem.z as one stacking unit.
    Rectangle {
        anchors.fill: frame
        anchors.margins: -5
        z: 1
        color: "transparent"
        radius: root.theme.cornerRadius + 5
        border.width: 5
        border.color: Qt.rgba(
            root.theme.shadow.r,
            root.theme.shadow.g,
            root.theme.shadow.b,
            0.08
        )
    }
}
