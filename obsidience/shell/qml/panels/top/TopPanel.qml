import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Wayland
import "../../api"

PanelWindow {
    id: panel

    required property ShellApi shellApi

    color: "transparent"
    focusable: false
    implicitHeight: 38
    exclusiveZone: 38

    anchors {
        top: true
        right: true
        left: true
    }

    WlrLayershell.layer: WlrLayer.Top
    WlrLayershell.namespace: "obsidience-shell-panel"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    SystemClock {
        id: clock
        precision: SystemClock.Seconds
    }

    Rectangle {
        anchors.fill: parent
        color: "#f5020810"

        Rectangle {
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.left: parent.left
            height: 1
            color: "#b82addff"
        }

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 16
            anchors.rightMargin: 16
            spacing: 18

            Text {
                text: "OBSIDIENCE"
                color: "#55e5ff"
                font.family: "JetBrains Mono"
                font.pixelSize: 12
                font.bold: true
                font.letterSpacing: 1
            }

            Item {
                Layout.fillWidth: true
            }

            Text {
                text: Qt.formatDateTime(clock.date, "HH:mm:ss")
                color: "#c5d8e6"
                font.family: "JetBrains Mono"
                font.pixelSize: 12
            }
        }
    }
}
