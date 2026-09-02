pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Wayland
import "../../api"

PanelWindow {
    id: stage

    required property ShellApi shellApi
    required property string surfaceId
    required property bool locked

    color: "transparent"
    focusable: false
    exclusiveZone: 0
    aboveWindows: false
    implicitWidth: screen ? screen.width : 0
    implicitHeight: screen ? screen.height : 0

    anchors {
        top: true
        right: true
        bottom: true
        left: true
    }

    mask: Region {}

    WlrLayershell.layer: WlrLayer.Bottom
    WlrLayershell.namespace: "obsidience-shell-stage"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    StageContent {
        width: stage.screen ? stage.screen.width : 0
        height: stage.screen ? stage.screen.height : 0
        surfaceId: stage.surfaceId
        locked: stage.locked
    }
}
