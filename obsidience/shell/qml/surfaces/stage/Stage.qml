import QtQuick
import Quickshell
import Quickshell.Wayland
import "../../api"
import "../../components/identity"

PanelWindow {
    required property ShellApi shellApi

    color: "#02060c"
    focusable: false
    exclusiveZone: 0

    anchors {
        top: true
        right: true
        bottom: true
        left: true
    }

    WlrLayershell.layer: WlrLayer.Background
    WlrLayershell.namespace: "obsidience-shell-stage"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    mask: Region {}

    Identity {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.leftMargin: 20
        anchors.topMargin: 12
    }
}
