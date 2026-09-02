pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls

Button {
    id: control

    property bool selected: false
    property bool emphasized: false
    property bool uppercase: true
    property color accent: "#67e8f9"
    property color foreground: "#cffafe"
    property color idleForeground: foreground
    property real idleBorderOpacity: 0.15
    property real hoverBorderOpacity: 0.40
    property real selectedBorderOpacity: 0.50
    property real hoverFillOpacity: 0.10
    property real selectedFillOpacity: 0.10
    property real emphasizedFillOpacity: 0.10
    property real idleTextOpacity: 0.50
    property real hoverTextOpacity: 1.0
    property real selectedTextOpacity: 1.0
    property real disabledOpacity: 0.35
    property int textPixelSize: 10
    property real textLetterSpacing: 1.8
    property int contentHorizontalPadding: 10

    implicitWidth: Math.max(28,
        implicitContentWidth + contentHorizontalPadding * 2)
    implicitHeight: 28
    opacity: enabled ? 1.0 : disabledOpacity

    background: Rectangle {
        radius: 4
        color: control.selected
            ? Qt.rgba(control.accent.r, control.accent.g, control.accent.b,
                control.selectedFillOpacity)
            : control.emphasized
                ? Qt.rgba(control.accent.r, control.accent.g, control.accent.b,
                    control.emphasizedFillOpacity)
            : (control.hovered || control.down)
                ? Qt.rgba(control.accent.r, control.accent.g, control.accent.b,
                    control.hoverFillOpacity)
                : "transparent"
        border.width: 1
        border.color: Qt.rgba(
            control.accent.r,
            control.accent.g,
            control.accent.b,
            control.selected ? control.selectedBorderOpacity
                : (control.hovered || control.down)
                    ? control.hoverBorderOpacity : control.idleBorderOpacity
        )
    }

    contentItem: Text {
        text: control.uppercase ? control.text.toUpperCase() : control.text
        color: {
            const activeColor = control.selected || control.hovered || control.down
                ? control.foreground : control.idleForeground
            const activeOpacity = control.selected ? control.selectedTextOpacity
                : (control.hovered || control.down)
                    ? control.hoverTextOpacity : control.idleTextOpacity
            return Qt.rgba(
                activeColor.r, activeColor.g, activeColor.b, activeOpacity
            )
        }
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        font.family: "JetBrains Mono"
        font.pixelSize: control.textPixelSize
        font.weight: Font.Medium
        font.letterSpacing: control.textLetterSpacing
    }
}
