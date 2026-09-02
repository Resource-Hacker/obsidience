pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import "../../api"

PanelWindow {
    id: stage

    required property ShellApi shellApi
    required property string surfaceId
    required property bool locked

    color: "#02060c"
    visible: locked || shellApi.surfaceLayout.graphSurfaceId !== surfaceId
    focusable: false
    exclusiveZone: 0
    aboveWindows: locked
    implicitWidth: screen ? screen.width : 0
    implicitHeight: screen ? screen.height : 0

    anchors {
        top: true
        right: true
        bottom: true
        left: true
    }

    mask: Region {}

    StageContent {
        width: stage.screen ? stage.screen.width : 0
        height: stage.screen ? stage.screen.height : 0
        surfaceId: stage.surfaceId
        locked: stage.locked
    }
}
