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
    readonly property bool stageExposed: !!windowState && !!screen
        && windowState.surface_awake !== false
        && !(windowState.windows || []).some(window => !window.minimized
            && window.visible_on_workspace !== false
            && window.local_rect && window.local_rect.width >= stage.screen.width - 12
            && window.local_rect.height >= stage.screen.height - 12)

    color: "transparent"
    focusable: false
    exclusiveZone: 0
    aboveWindows: false
    // Only the wordmark draws here. A layer sized to it and its OLED drift
    // keeps the compositor from blending a full-output buffer every frame.
    implicitWidth: content.extentWidth
    implicitHeight: content.extentHeight

    anchors {
        top: true
        left: true
    }

    mask: Region {}

    WlrLayershell.layer: WlrLayer.Bottom
    WlrLayershell.namespace: "obsidience-shell-stage"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None

    StageContent {
        id: content
        anchors.fill: parent
        locked: stage.locked
        oledEnabled: stage.surfaceId === "samsung" && stage.shellApi.surfaceLayout.oledModeEnabled
        motionActive: stage.motionAllowed && stage.stageExposed && !stage.locked
        driftDistance: stage.shellApi.surfaceLayout.oledShiftDistancePx
        travelSeconds: stage.shellApi.surfaceLayout.oledTravelDurationSeconds
    }
}
