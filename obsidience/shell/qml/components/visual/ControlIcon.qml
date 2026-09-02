pragma ComponentBehavior: Bound

import QtQuick

Canvas {
    id: root

    property string glyph: "play"
    property color iconColor: "#cffafe"
    property real strokeOpacity: 1.0

    implicitWidth: 15
    implicitHeight: 15
    contextType: "2d"

    function beginStroke(context, scale, opacity) {
        context.strokeStyle = Qt.rgba(
            iconColor.r, iconColor.g, iconColor.b,
            strokeOpacity * (opacity === undefined ? 1.0 : opacity)
        )
        context.fillStyle = "transparent"
        context.lineWidth = 2 * scale
        context.lineCap = "round"
        context.lineJoin = "round"
    }

    function microphone(context, scale, muted) {
        beginStroke(context, scale, muted ? 0.62 : 1.0)
        context.beginPath()
        context.moveTo(9 * scale, 5 * scale)
        context.bezierCurveTo(9 * scale, 3.34 * scale,
            10.34 * scale, 2 * scale, 12 * scale, 2 * scale)
        context.bezierCurveTo(13.66 * scale, 2 * scale,
            15 * scale, 3.34 * scale, 15 * scale, 5 * scale)
        context.lineTo(15 * scale, 12 * scale)
        context.bezierCurveTo(15 * scale, 13.66 * scale,
            13.66 * scale, 15 * scale, 12 * scale, 15 * scale)
        context.bezierCurveTo(10.34 * scale, 15 * scale,
            9 * scale, 13.66 * scale, 9 * scale, 12 * scale)
        context.closePath()
        context.stroke()

        context.beginPath()
        context.moveTo(5 * scale, 10 * scale)
        context.lineTo(5 * scale, 12 * scale)
        context.bezierCurveTo(5 * scale, 15.87 * scale,
            8.13 * scale, 19 * scale, 12 * scale, 19 * scale)
        context.bezierCurveTo(15.87 * scale, 19 * scale,
            19 * scale, 15.87 * scale, 19 * scale, 12 * scale)
        context.lineTo(19 * scale, 10 * scale)
        context.stroke()
        context.beginPath()
        context.moveTo(12 * scale, 19 * scale)
        context.lineTo(12 * scale, 22 * scale)
        context.moveTo(8 * scale, 22 * scale)
        context.lineTo(16 * scale, 22 * scale)
        context.stroke()

        if (muted) {
            beginStroke(context, scale, 1.0)
            context.beginPath()
            context.moveTo(2 * scale, 2 * scale)
            context.lineTo(22 * scale, 22 * scale)
            context.stroke()
        }
    }

    function eye(context, scale, hidden) {
        beginStroke(context, scale, hidden ? 0.62 : 1.0)
        context.beginPath()
        context.moveTo(2 * scale, 12 * scale)
        context.bezierCurveTo(4.8 * scale, 7.1 * scale,
            8.1 * scale, 5 * scale, 12 * scale, 5 * scale)
        context.bezierCurveTo(15.9 * scale, 5 * scale,
            19.2 * scale, 7.1 * scale, 22 * scale, 12 * scale)
        context.bezierCurveTo(19.2 * scale, 16.9 * scale,
            15.9 * scale, 19 * scale, 12 * scale, 19 * scale)
        context.bezierCurveTo(8.1 * scale, 19 * scale,
            4.8 * scale, 16.9 * scale, 2 * scale, 12 * scale)
        context.closePath()
        context.stroke()
        context.beginPath()
        context.arc(12 * scale, 12 * scale, 3 * scale, 0, Math.PI * 2)
        context.stroke()

        if (hidden) {
            beginStroke(context, scale, 1.0)
            context.beginPath()
            context.moveTo(3 * scale, 3 * scale)
            context.lineTo(21 * scale, 21 * scale)
            context.stroke()
        }
    }

    function play(context, scale) {
        beginStroke(context, scale, 1.0)
        context.beginPath()
        context.moveTo(6 * scale, 3 * scale)
        context.lineTo(20 * scale, 12 * scale)
        context.lineTo(6 * scale, 21 * scale)
        context.closePath()
        context.stroke()
    }

    function pause(context, scale) {
        beginStroke(context, scale, 1.0)
        context.beginPath()
        context.moveTo(8 * scale, 5 * scale)
        context.lineTo(8 * scale, 19 * scale)
        context.moveTo(16 * scale, 5 * scale)
        context.lineTo(16 * scale, 19 * scale)
        context.stroke()
    }

    function loader(context, scale) {
        beginStroke(context, scale, 1.0)
        context.beginPath()
        context.arc(12 * scale, 12 * scale, 9 * scale,
            -Math.PI * 0.15, Math.PI * 1.35)
        context.stroke()
    }

    function renderControlIcon() {
        const context = getContext("2d")
        context.clearRect(0, 0, width, height)
        const scale = Math.min(width, height) / 24
        context.save()
        context.translate((width - 24 * scale) / 2, (height - 24 * scale) / 2)
        switch (glyph) {
        case "mic": microphone(context, scale, false); break
        case "mic-off": microphone(context, scale, true); break
        case "eye": eye(context, scale, false); break
        case "eye-off": eye(context, scale, true); break
        case "pause": pause(context, scale); break
        case "loader": loader(context, scale); break
        default: play(context, scale); break
        }
        context.restore()
    }

    onGlyphChanged: requestPaint()
    onIconColorChanged: requestPaint()
    onStrokeOpacityChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onPaint: renderControlIcon()

    NumberAnimation on rotation {
        from: 0
        to: 360
        duration: 900
        loops: Animation.Infinite
        running: root.glyph === "loader" && root.visible
    }
}
