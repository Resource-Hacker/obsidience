pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls

ComboBox {
    id: control

    property color accent: "#67e8f9"
    property color foreground: "#a5f3fc"
    property color fieldColor: "#020a12"
    property int textPixelSize: 9
    property real textLetterSpacing: 0
    property real idleBorderOpacity: 0.20
    property real hoverBorderOpacity: 0.40
    property real focusBorderOpacity: 0.50
    property real textOpacity: 0.70
    property real disabledOpacity: 0.45

    implicitWidth: Math.max(72, implicitContentWidth + 30)
    implicitHeight: 28
    opacity: enabled ? 1.0 : disabledOpacity
    leftPadding: 8
    rightPadding: 22

    background: Rectangle {
        radius: 4
        color: control.fieldColor
        border.width: 1
        border.color: Qt.rgba(
            control.accent.r,
            control.accent.g,
            control.accent.b,
            control.activeFocus ? control.focusBorderOpacity
                : control.hovered ? control.hoverBorderOpacity
                    : control.idleBorderOpacity
        )
    }

    contentItem: Text {
        leftPadding: control.leftPadding
        rightPadding: control.rightPadding
        text: control.displayText
        color: Qt.rgba(
            control.foreground.r,
            control.foreground.g,
            control.foreground.b,
            control.textOpacity
        )
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        font.family: "JetBrains Mono"
        font.pixelSize: control.textPixelSize
        font.letterSpacing: control.textLetterSpacing
    }

    indicator: Canvas {
        x: control.width - width - 8
        y: (control.height - height) / 2
        width: 9
        height: 6
        contextType: "2d"
        onPaint: {
            const context = getContext("2d")
            context.clearRect(0, 0, width, height)
            context.strokeStyle = Qt.rgba(
                control.foreground.r,
                control.foreground.g,
                control.foreground.b,
                control.enabled ? 0.65 : 0.30
            )
            context.lineWidth = 1.25
            context.lineCap = "round"
            context.lineJoin = "round"
            context.beginPath()
            context.moveTo(0.75, 1)
            context.lineTo(width / 2, height - 0.75)
            context.lineTo(width - 0.75, 1)
            context.stroke()
        }
    }

    delegate: ItemDelegate {
        id: option

        required property var modelData
        required property int index
        width: control.popup.width - 2
        height: 28
        highlighted: control.highlightedIndex === index

        contentItem: Text {
            leftPadding: 8
            rightPadding: 8
            text: control.textRole && option.modelData
                    && typeof option.modelData === "object"
                ? String(option.modelData[control.textRole] ?? "")
                : String(option.modelData ?? "")
            color: option.highlighted ? "#cffafe" : "#b37dd3e8"
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
            font.family: "JetBrains Mono"
            font.pixelSize: control.textPixelSize
            font.letterSpacing: control.textLetterSpacing
        }

        background: Rectangle {
            color: option.highlighted ? "#0e3a47" : "transparent"
        }
    }

    popup: Popup {
        y: control.height + 2
        width: control.width
        implicitHeight: Math.min(contentItem.implicitHeight + 2, 320)
        padding: 1

        contentItem: ListView {
            clip: true
            implicitHeight: contentHeight
            model: control.popup.visible ? control.delegateModel : null
            currentIndex: control.highlightedIndex

            ScrollIndicator.vertical: ScrollIndicator {}
        }

        background: Rectangle {
            radius: 4
            color: "#07131b"
            border.width: 1
            border.color: "#164e5b"
        }
    }
}
