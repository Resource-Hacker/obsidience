import QtQuick
import Quickshell
import Quickshell.Wayland
import "../../api"

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
    WlrLayershell.namespace: "obsidience-shell-background"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    mask: Region {}
}
