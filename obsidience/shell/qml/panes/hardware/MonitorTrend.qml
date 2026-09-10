pragma ComponentBehavior: Bound

import QtQuick

Item {
    id: root
    property var values: []
    property color lineColor: "#67e8f9"
    property color gridColor: "#2667e8f9"
    property real maximum: 100
    implicitHeight: 72

    function segments() {
        const parts = []
        let part = []
        const rows = Array.from(values || [])
        const ceiling = maximum > 0 ? maximum : Math.max(1, ...rows.filter(value => typeof value === "number" && Number.isFinite(value)))
        for (let index = 0; index < rows.length; index++) {
            const value = rows[index]
            if (typeof value !== "number" || !Number.isFinite(value)) {
                if (part.length) parts.push(part)
                part = []
                continue
            }
            part.push({"x": (120 - rows.length + index) / 119,
                "y": 1 - Math.max(0, Math.min(1, value / ceiling))})
        }
        if (part.length) parts.push(part)
        return parts
    }

    onValuesChanged: { if (visible) plot.requestPaint() }
    onMaximumChanged: { if (visible) plot.requestPaint() }
    onLineColorChanged: { if (visible) plot.requestPaint() }
    onVisibleChanged: { if (visible) plot.requestPaint() }
    Canvas {
        id: plot
        anchors.fill: parent
        contextType: "2d"
        onWidthChanged: { if (visible) requestPaint() }
        onHeightChanged: { if (visible) requestPaint() }
        onPaint: {
            const context = getContext("2d")
            context.clearRect(0, 0, width, height)
            if (!root.visible) return
            context.strokeStyle = root.gridColor
            context.lineWidth = 1
            for (let column = 0; column <= 12; column++) {
                const x = Math.round((width - 1) * column / 12) + 0.5
                context.beginPath(); context.moveTo(x, 0); context.lineTo(x, height); context.stroke()
            }
            for (let row = 1; row <= 3; row++) {
                const y = Math.round((height - 4) * row / 3) + 0.5
                context.beginPath(); context.moveTo(0, y); context.lineTo(width, y); context.stroke()
            }
            context.strokeStyle = root.lineColor
            context.fillStyle = root.lineColor
            context.lineWidth = 1.8
            context.lineJoin = "round"
            for (const part of root.segments()) {
                context.beginPath()
                for (let index = 0; index < part.length; index++) {
                    const x = 2 + part[index].x * (width - 4)
                    const y = 2 + part[index].y * (height - 4)
                    if (index === 0) context.moveTo(x, y)
                    else context.lineTo(x, y)
                }
                context.stroke()
                if (part.length === 1) {
                    context.beginPath()
                    context.arc(2 + part[0].x * (width - 4), 2 + part[0].y * (height - 4), 2, 0, Math.PI * 2)
                    context.fill()
                }
            }
        }
    }
}
