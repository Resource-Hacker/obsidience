pragma ComponentBehavior: Bound

import QtQuick
import Quickshell.Widgets
import "../api"

Item {
    id: root

    required property string title
    required property ShellTheme theme
    property bool defaultWidthReached: false
    property bool defaultHeightReached: false
    property string verticalDefaultGuideEdge: ""
    property string horizontalDefaultGuideEdge: ""
    property bool defaultSizeFeedbackEnabled: true
    property bool resizeFeedbackActive: false
    property int resizeFeedbackEdges: 0
    readonly property int verticalResizeEdge:
        verticalDefaultGuideEdge === "left" ? Qt.LeftEdge : Qt.RightEdge
    readonly property int horizontalResizeEdge:
        horizontalDefaultGuideEdge === "top" ? Qt.TopEdge : Qt.BottomEdge
    readonly property bool widthResizeFeedback:
        (resizeFeedbackEdges & (Qt.LeftEdge | Qt.RightEdge)) !== 0
    readonly property bool heightResizeFeedback:
        (resizeFeedbackEdges & (Qt.TopEdge | Qt.BottomEdge)) !== 0
    default property alias contentData: content.data

    signal moveRequested()
    signal resizeRequested(int edges)
    signal closeRequested()

    function keepResizeFeedback() {
        if (resizeFeedbackActive) {
            resizeFeedbackTimer.restart()
        }
    }

    function beginResize(edges) {
        resizeFeedbackEdges = edges
        resizeFeedbackActive = true
        resizeFeedbackTimer.restart()
        resizeRequested(edges)
    }

    function keepWidthResizeFeedback() {
        if (widthResizeFeedback) {
            resizeFeedbackActive = true
            resizeFeedbackTimer.restart()
        }
    }

    function keepHeightResizeFeedback() {
        if (heightResizeFeedback) {
            resizeFeedbackActive = true
            resizeFeedbackTimer.restart()
        }
    }

    onWidthChanged: keepWidthResizeFeedback()
    onHeightChanged: keepHeightResizeFeedback()

    Timer {
        id: resizeFeedbackTimer

        interval: 900
        repeat: false
        onTriggered: root.resizeFeedbackActive = false
    }

    ClippingRectangle {
        id: frame

        anchors.fill: parent
        radius: root.theme.cornerRadius
        color: root.theme.surface
        border.width: 0
        contentUnderBorder: true

        Rectangle {
            id: titleBar

            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            height: root.theme.titleHeight
            color: "transparent"

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
                cursorShape: Qt.OpenHandCursor

                onPressed: {
                    cursorShape = Qt.ClosedHandCursor
                    root.moveRequested()
                }
                onReleased: cursorShape = Qt.OpenHandCursor
                onCanceled: cursorShape = Qt.OpenHandCursor
            }
        }

        Item {
            id: content

            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: titleBar.bottom
            anchors.bottom: parent.bottom
        }

        Rectangle {
            id: verticalDefaultGuide

            x: root.verticalDefaultGuideEdge === "left"
                ? 3 : parent.width - width - 3
            y: 3
            width: 2
            height: Math.max(0, parent.height - 6)
            radius: 1
            color: root.theme.text
            opacity: root.defaultSizeFeedbackEnabled
                    && root.resizeFeedbackActive
                    && root.widthResizeFeedback
                    && root.defaultWidthReached
                    && root.verticalDefaultGuideEdge !== "" ? 0.9 : 0

            Behavior on opacity {
                NumberAnimation { duration: 80 }
            }
        }

        Rectangle {
            id: horizontalDefaultGuide

            x: 3
            y: root.horizontalDefaultGuideEdge === "top"
                ? 3 : parent.height - height - 3
            width: Math.max(0, parent.width - 6)
            height: 2
            radius: 1
            color: root.theme.text
            opacity: root.defaultSizeFeedbackEnabled
                    && root.resizeFeedbackActive
                    && root.heightResizeFeedback
                    && root.defaultHeightReached
                    && root.horizontalDefaultGuideEdge !== "" ? 0.9 : 0

            Behavior on opacity {
                NumberAnimation { duration: 80 }
            }
        }

        Item {
            id: widthResizeHandle

            visible: root.verticalDefaultGuideEdge !== ""
            x: root.verticalDefaultGuideEdge === "left"
                ? 0 : parent.width - width
            y: Math.round((parent.height - height) / 2)
            width: 18
            height: 56

            Rectangle {
                anchors.fill: parent
                anchors.margins: 2
                radius: 6
                color: widthResizeMouse.containsMouse
                    || widthResizeMouse.pressed
                    ? root.theme.hover : "transparent"
            }

            Rectangle {
                anchors.centerIn: parent
                width: 2
                height: 24
                radius: 1
                color: widthResizeMouse.containsMouse
                    || widthResizeMouse.pressed
                    ? root.theme.text : root.theme.strongAccent
            }

            MouseArea {
                id: widthResizeMouse

                anchors.fill: parent
                acceptedButtons: Qt.LeftButton
                hoverEnabled: true
                cursorShape: Qt.SizeHorCursor
                onPressed: root.beginResize(root.verticalResizeEdge)
                onReleased: root.keepResizeFeedback()
                onCanceled: root.keepResizeFeedback()
            }
        }

        Item {
            id: heightResizeHandle

            visible: root.horizontalDefaultGuideEdge !== ""
            x: Math.round((parent.width - width) / 2)
            y: root.horizontalDefaultGuideEdge === "top"
                ? 0 : parent.height - height
            width: 56
            height: 18

            Rectangle {
                anchors.fill: parent
                anchors.margins: 2
                radius: 6
                color: heightResizeMouse.containsMouse
                    || heightResizeMouse.pressed
                    ? root.theme.hover : "transparent"
            }

            Rectangle {
                anchors.centerIn: parent
                width: 24
                height: 2
                radius: 1
                color: heightResizeMouse.containsMouse
                    || heightResizeMouse.pressed
                    ? root.theme.text : root.theme.strongAccent
            }

            MouseArea {
                id: heightResizeMouse

                anchors.fill: parent
                acceptedButtons: Qt.LeftButton
                hoverEnabled: true
                cursorShape: Qt.SizeVerCursor
                onPressed: root.beginResize(root.horizontalResizeEdge)
                onReleased: root.keepResizeFeedback()
                onCanceled: root.keepResizeFeedback()
            }
        }

        Item {
            id: resizeHandle

            visible: root.verticalDefaultGuideEdge !== ""
                && root.horizontalDefaultGuideEdge !== ""
            x: root.verticalDefaultGuideEdge === "left"
                ? 0 : parent.width - width
            y: root.horizontalDefaultGuideEdge === "top"
                ? 0 : parent.height - height
            width: 30
            height: 30

            Rectangle {
                anchors.fill: parent
                anchors.margins: 2
                radius: 6
                color: resizeMouse.containsMouse || resizeMouse.pressed
                    ? root.theme.hover : "transparent"
            }

            Item {
                id: cornerGlyph

                x: 5
                y: 5
                width: 15
                height: 15
                transform: Scale {
                    origin.x: cornerGlyph.width / 2
                    origin.y: cornerGlyph.height / 2
                    xScale: root.verticalDefaultGuideEdge === "left" ? -1 : 1
                    yScale: root.horizontalDefaultGuideEdge === "top" ? -1 : 1
                }

                Rectangle {
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    width: 2
                    height: parent.height
                    color: resizeMouse.containsMouse || resizeMouse.pressed
                        ? root.theme.text : root.theme.strongAccent
                }

                Rectangle {
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    width: parent.width
                    height: 2
                    color: resizeMouse.containsMouse || resizeMouse.pressed
                        ? root.theme.text : root.theme.strongAccent
                }

                Rectangle {
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.rightMargin: 6
                    anchors.bottomMargin: 6
                    width: 2
                    height: 6
                    color: resizeMouse.containsMouse || resizeMouse.pressed
                        ? root.theme.text : root.theme.strongAccent
                }

                Rectangle {
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.rightMargin: 6
                    anchors.bottomMargin: 6
                    width: 6
                    height: 2
                    color: resizeMouse.containsMouse || resizeMouse.pressed
                        ? root.theme.text : root.theme.strongAccent
                }
            }

            MouseArea {
                id: resizeMouse

                anchors.fill: parent
                acceptedButtons: Qt.LeftButton
                hoverEnabled: true
                cursorShape: (root.verticalDefaultGuideEdge === "left")
                        === (root.horizontalDefaultGuideEdge === "top")
                    ? Qt.SizeFDiagCursor : Qt.SizeBDiagCursor
                onPressed: root.beginResize(
                    root.verticalResizeEdge | root.horizontalResizeEdge
                )
                onReleased: root.keepResizeFeedback()
                onCanceled: root.keepResizeFeedback()
            }
        }
    }
}
