pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Shapes

Item {
    id: root

    property string glyph: ""
    property color iconColor: "#67e8f9"
    property real iconOpacity: 1.0
    readonly property bool customArtwork: ["reader", "source", "models"]
        .indexOf(glyph) >= 0
    readonly property bool canvasVector: ["reader", "source"]
        .indexOf(glyph) >= 0

    readonly property string primaryGlyphText: {
        switch (glyph) {
        case "launcher": return "\uf0c9"
        case "chat": return "\uf075"
        case "tasks": return "\uf0ae"
        case "reviews": return "\uf164"
        case "knowledge": return "\uf19d"
        case "source": return "\uf0c7"
        case "models": return "\uf5dc"
        case "hardware": return "\uf2db"
        case "camera": return "\uf06e"
        case "settings": return "\uf013"
        case "connections": return "\uf0c1"
        case "feeds": return "\uf09e"
        case "applications": return "\uf1b3"
        case "terminal": return "\uf120"
        case "displays": return "\uf108"
        case "clock": return "\uf017"
        case "application": return "\uf135"
        default: return "\uf111"
        }
    }

    readonly property string secondaryGlyphText: {
        switch (glyph) {
        case "hardware": return "\uf0e7"
        default: return ""
        }
    }

    implicitWidth: 24
    implicitHeight: 24

    RoleIcon {
        anchors.centerIn: parent
        width: Math.min(parent.width, parent.height) * 1.46
        height: width
        role: "library"
        visible: root.glyph === "library"
        opacity: root.iconOpacity
    }

    Text {
        anchors.fill: parent
        visible: root.glyph !== "library" && !root.customArtwork
        text: root.primaryGlyphText
        color: root.iconColor
        opacity: root.iconOpacity
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        font.family: "JetBrainsMono Nerd Font Mono"
        font.pixelSize: Math.round(Math.min(width, height) * 1.08)
        font.weight: Font.Medium
        renderType: Text.NativeRendering
    }

    Text {
        visible: root.glyph !== "library" && !root.customArtwork
            && root.secondaryGlyphText !== ""
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        width: parent.width * 0.58
        height: parent.height * 0.58
        text: root.secondaryGlyphText
        color: "#effcff"
        opacity: root.iconOpacity
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        font.family: "JetBrainsMono Nerd Font Mono"
        font.pixelSize: Math.round(Math.min(width, height) * 0.94)
        font.weight: Font.Bold
        renderType: Text.NativeRendering
    }

    Canvas {
        id: vectorIcon

        anchors.fill: parent
        visible: root.canvasVector
        contextType: "2d"

        function begin(context) {
            context.clearRect(0, 0, width, height)
            context.save()
            context.strokeStyle = root.iconColor
            context.fillStyle = root.iconColor
            context.globalAlpha = root.iconOpacity
            context.lineWidth = Math.max(1.4, Math.min(width, height) * 0.075)
            context.lineCap = "round"
            context.lineJoin = "round"
            context.shadowColor = root.iconColor
            context.shadowBlur = Math.min(width, height) * 0.11
        }

        function ellipse(context, x, y, radiusX, radiusY) {
            context.save()
            context.translate(x, y)
            context.scale(radiusX, radiusY)
            context.beginPath()
            context.arc(0, 0, 1, 0, Math.PI * 2)
            context.restore()
        }

        function paintSource(context) {
            const w = width
            const h = height
            ellipse(context, w * 0.5, h * 0.22, w * 0.34, h * 0.12)
            context.stroke()
            context.globalAlpha = root.iconOpacity * 0.16
            context.fill()
            context.globalAlpha = root.iconOpacity
            context.beginPath()
            context.moveTo(w * 0.16, h * 0.22)
            context.lineTo(w * 0.16, h * 0.76)
            context.bezierCurveTo(
                w * 0.16, h * 0.91, w * 0.84, h * 0.91, w * 0.84, h * 0.76
            )
            context.lineTo(w * 0.84, h * 0.22)
            context.stroke()
            for (const y of [0.43, 0.64]) {
                context.beginPath()
                context.moveTo(w * 0.16, h * y)
                context.bezierCurveTo(
                    w * 0.16, h * (y + 0.14),
                    w * 0.84, h * (y + 0.14),
                    w * 0.84, h * y
                )
                context.stroke()
            }
        }

        function paintReader(context) {
            const w = width
            const h = height

            // Wiki page and compact article marks.
            context.beginPath()
            context.moveTo(w * 0.13, h * 0.10)
            context.lineTo(w * 0.80, h * 0.10)
            context.lineTo(w * 0.80, h * 0.78)
            context.lineTo(w * 0.67, h * 0.88)
            context.lineTo(w * 0.13, h * 0.88)
            context.closePath()
            context.stroke()
            context.globalAlpha = root.iconOpacity * 0.68
            for (const line of [[0.24, 0.24, 0.67], [0.24, 0.34, 0.58]]) {
                context.beginPath()
                context.moveTo(w * line[0], h * line[1])
                context.lineTo(w * line[2], h * line[1])
                context.stroke()
            }

            // The reference icon's boxed W, simplified for micro-menu scale.
            context.globalAlpha = root.iconOpacity
            context.strokeRect(w * 0.21, h * 0.43, w * 0.34, h * 0.28)
            context.beginPath()
            context.moveTo(w * 0.26, h * 0.49)
            context.lineTo(w * 0.31, h * 0.64)
            context.lineTo(w * 0.38, h * 0.54)
            context.lineTo(w * 0.44, h * 0.64)
            context.lineTo(w * 0.50, h * 0.49)
            context.stroke()

            // One clean edit pencil, matching the downloaded reference.
            context.beginPath()
            context.moveTo(w * 0.55, h * 0.82)
            context.lineTo(w * 0.84, h * 0.53)
            context.lineTo(w * 0.93, h * 0.62)
            context.lineTo(w * 0.64, h * 0.91)
            context.closePath()
            context.globalAlpha = root.iconOpacity * 0.16
            context.fill()
            context.globalAlpha = root.iconOpacity
            context.stroke()
            context.beginPath()
            context.moveTo(w * 0.55, h * 0.82)
            context.lineTo(w * 0.51, h * 0.95)
            context.lineTo(w * 0.64, h * 0.91)
            context.moveTo(w * 0.80, h * 0.57)
            context.lineTo(w * 0.89, h * 0.66)
            context.stroke()
        }

        onPaint: {
            const context = getContext("2d")
            begin(context)
            if (root.glyph === "source") {
                paintSource(context)
            } else if (root.glyph === "reader") {
                paintReader(context)
            }
            context.restore()
        }

        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onVisibleChanged: if (visible) requestPaint()

        Connections {
            target: root
            function onGlyphChanged() { vectorIcon.requestPaint() }
            function onIconColorChanged() { vectorIcon.requestPaint() }
            function onIconOpacityChanged() { vectorIcon.requestPaint() }
        }
    }

    // Match the Electron Models pane's Lucide BrainCircuit icon natively.
    Shape {
        anchors.centerIn: parent
        width: 24
        height: 24
        scale: Math.min(root.width, root.height) / 24
        visible: root.glyph === "models"
        opacity: root.iconOpacity
        preferredRendererType: Shape.CurveRenderer

        ShapePath {
            fillColor: "transparent"
            strokeColor: root.iconColor
            strokeWidth: 2.2
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin

            PathSvg {
                path: "M12 5a3 3 0 1 0-5.997.125a4 4 0 0 0-2.526 5.77a4 4 0 0 0 .556 6.588A4 4 0 1 0 12 18Z M9 13a4.5 4.5 0 0 0 3-4 M6.003 5.125A3 3 0 0 0 6.401 6.5 M3.477 10.896a4 4 0 0 1 .585-.396 M6 18a4 4 0 0 1-1.967-.516 M12 13h4 M12 18h6a2 2 0 0 1 2 2v1 M12 8h8 M16 8V5a2 2 0 0 1 2-2 M16 12.5a.5.5 0 1 0 0 1a.5.5 0 1 0 0-1 M18 2.5a.5.5 0 1 0 0 1a.5.5 0 1 0 0-1 M20 20.5a.5.5 0 1 0 0 1a.5.5 0 1 0 0-1 M20 7.5a.5.5 0 1 0 0 1a.5.5 0 1 0 0-1"
            }
        }
    }
}
