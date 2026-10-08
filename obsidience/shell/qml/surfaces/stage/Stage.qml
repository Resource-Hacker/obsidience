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
    property var windowState: null
    property bool motionAllowed: false
    readonly property bool stageExposed: !!windowState && windowState.surface_awake !== false
        && !(windowState.windows || []).some(window => !window.minimized
            && window.visible_on_workspace !== false
            && window.local_rect && window.local_rect.width >= stage.width - 12
            && window.local_rect.height >= stage.height - 12)

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
        locked: stage.locked
        oledEnabled: stage.surfaceId === "samsung" && stage.shellApi.surfaceLayout.oledModeEnabled
        motionActive: stage.motionAllowed && stage.stageExposed && !stage.locked
        driftDistance: stage.shellApi.surfaceLayout.oledShiftDistancePx
        travelSeconds: stage.shellApi.surfaceLayout.oledTravelDurationSeconds
    }
}
