pragma ComponentBehavior: Bound

import QtQuick

Canvas {
    id: root

    property string role: "executive"
    readonly property string normalizedRole: resolveRole(role)
    readonly property color tint: roleTint(normalizedRole)

    implicitWidth: 24
    implicitHeight: 24
    contextType: "2d"

    function resolveRole(value) {
        const parts = String(value || "").trim().split("/").filter(Boolean)
        const identity = parts.length > 0
            ? String(parts[parts.length - 1]).toLowerCase() : ""
        if (identity === "alexandria" || identity === "curator") {
            return "curator"
        }
        if (identity === "darwin" || identity === "researcher") {
            return "researcher"
        }
        if (identity === "heimdall" || identity === "guardian") {
            return "guardian"
        }
        if (identity === "library") {
            return "library"
        }
        return "executive"
    }

    function roleTint(value) {
        switch (value) {
        case "curator": return "#fbbf24"
        case "researcher": return "#c084fc"
        case "guardian": return "#60a5fa"
        case "library": return "#34d399"
        default: return "#67e8f9"
        }
    }

    function neonStroke(context, color, lineWidth) {
        context.strokeStyle = color
        context.lineWidth = lineWidth
        context.lineJoin = "round"
        context.lineCap = "round"
        context.shadowColor = color
        context.shadowBlur = lineWidth * 3
    }

    function roundedRect(context, x, y, width, height, radius) {
        context.moveTo(x + radius, y)
        context.lineTo(x + width - radius, y)
        context.quadraticCurveTo(x + width, y, x + width, y + radius)
        context.lineTo(x + width, y + height - radius)
        context.quadraticCurveTo(x + width, y + height,
            x + width - radius, y + height)
        context.lineTo(x + radius, y + height)
        context.quadraticCurveTo(x, y + height, x, y + height - radius)
        context.lineTo(x, y + radius)
        context.quadraticCurveTo(x, y, x + radius, y)
        context.closePath()
    }

    function paintExecutive(context, size) {
        const color = roleTint("executive")
        neonStroke(context, color, size * 0.035)
        const headWidth = size * 0.5
        const headHeight = size * 0.44
        const x = (size - headWidth) / 2
        const y = size * 0.3
        context.beginPath()
        roundedRect(context, x, y, headWidth, headHeight, size * 0.08)
        context.stroke()
        context.globalAlpha = 0.16
        context.fillStyle = color
        context.fill()
        context.globalAlpha = 0.9
        for (const eyeX of [x + headWidth * 0.28, x + headWidth * 0.72]) {
            context.beginPath()
            context.arc(eyeX, y + headHeight * 0.42, size * 0.045,
                0, Math.PI * 2)
            context.fillStyle = "#ffffff"
            context.fill()
        }
        context.globalAlpha = 1
        context.beginPath()
        context.moveTo(x + headWidth * 0.3, y + headHeight * 0.74)
        context.lineTo(x + headWidth * 0.7, y + headHeight * 0.74)
        context.stroke()
        context.beginPath()
        context.moveTo(size / 2, y)
        context.lineTo(size / 2, y - size * 0.12)
        context.stroke()
        context.beginPath()
        context.arc(size / 2, y - size * 0.15, size * 0.03,
            0, Math.PI * 2)
        context.stroke()
    }

    function paintCuratorGear(context, size, centerX, centerY, radius,
            teeth, phase, alpha) {
        const color = roleTint("curator")
        context.save()
        context.globalAlpha = alpha
        neonStroke(context, color, radius * 0.16)
        for (let index = 0; index < teeth; index += 1) {
            const angle = phase + index / teeth * Math.PI * 2
            context.beginPath()
            context.moveTo(
                centerX + Math.cos(angle) * radius,
                centerY + Math.sin(angle) * radius
            )
            context.lineTo(
                centerX + Math.cos(angle) * radius * 1.32,
                centerY + Math.sin(angle) * radius * 1.32
            )
            context.stroke()
        }
        context.beginPath()
        context.arc(centerX, centerY, radius, 0, Math.PI * 2)
        context.stroke()
        context.globalAlpha = alpha * 0.16
        context.fillStyle = color
        context.fill()
        context.globalAlpha = alpha
        context.beginPath()
        context.arc(centerX, centerY, radius * 0.32, 0, Math.PI * 2)
        context.stroke()
        context.restore()
    }

    function paintCurator(context, size) {
        paintCuratorGear(context, size, size * 0.63, size * 0.3,
            size * 0.1, 8, 0.2, 0.4)
        paintCuratorGear(context, size, size * 0.42, size * 0.44,
            size * 0.17, 9, 0, 0.95)
        paintCuratorGear(context, size, size * 0.66, size * 0.66,
            size * 0.11, 7, 0.35, 0.85)
    }

    function paintResearcher(context, size) {
        const color = roleTint("researcher")
        neonStroke(context, color, size * 0.035)
        const topY = size * 0.24
        const neckHalf = size * 0.06
        const baseY = size * 0.76
        const baseHalf = size * 0.24
        context.beginPath()
        context.moveTo(size / 2 - neckHalf, topY)
        context.lineTo(size / 2 - neckHalf, size * 0.42)
        context.lineTo(size / 2 - baseHalf, baseY)
        context.quadraticCurveTo(size / 2, baseY + size * 0.1,
            size / 2 + baseHalf, baseY)
        context.lineTo(size / 2 + neckHalf, size * 0.42)
        context.lineTo(size / 2 + neckHalf, topY)
        context.stroke()
        context.globalAlpha = 0.35
        context.fillStyle = color
        context.beginPath()
        context.moveTo(size / 2 - baseHalf * 0.82, baseY - size * 0.045)
        context.lineTo(size / 2 + baseHalf * 0.82, baseY - size * 0.045)
        context.quadraticCurveTo(size / 2, baseY + size * 0.08,
            size / 2 - baseHalf * 0.82, baseY - size * 0.045)
        context.fill()
        context.globalAlpha = 0.85
        const bubbles = [
            [0.46, 0.6, 0.02],
            [0.55, 0.52, 0.025],
            [0.5, 0.34, 0.02],
            [0.56, 0.2, 0.028],
            [0.44, 0.14, 0.02]
        ]
        for (const bubble of bubbles) {
            context.beginPath()
            context.arc(size * bubble[0], size * bubble[1], size * bubble[2],
                0, Math.PI * 2)
            context.stroke()
        }
        context.globalAlpha = 1
    }

    function paintGuardian(context, size) {
        const color = roleTint("guardian")
        neonStroke(context, color, size * 0.04)
        const top = size * 0.2
        const left = size * 0.26
        const right = size * 0.74
        context.beginPath()
        context.moveTo(left, top)
        context.lineTo(right, top)
        context.lineTo(right, size * 0.52)
        context.quadraticCurveTo(right, size * 0.72, size / 2, size * 0.84)
        context.quadraticCurveTo(left, size * 0.72, left, size * 0.52)
        context.closePath()
        context.stroke()
        context.globalAlpha = 0.18
        context.fillStyle = color
        context.fill()
        context.globalAlpha = 0.8
        context.beginPath()
        context.moveTo(size / 2, top + size * 0.08)
        context.lineTo(size / 2, size * 0.72)
        context.stroke()
        context.globalAlpha = 1
    }

    function paintLibrary(context, size) {
        const color = roleTint("library")
        neonStroke(context, color, size * 0.035)
        const top = size * 0.3
        const bottom = size * 0.72
        const middle = size / 2
        const edge = size * 0.2
        context.beginPath()
        context.moveTo(middle, top + size * 0.05)
        context.quadraticCurveTo(middle - size * 0.16, top - size * 0.03,
            edge, top + size * 0.04)
        context.lineTo(edge, bottom)
        context.quadraticCurveTo(middle - size * 0.16, bottom - size * 0.07,
            middle, bottom + size * 0.02)
        context.quadraticCurveTo(middle + size * 0.16, bottom - size * 0.07,
            size - edge, bottom)
        context.lineTo(size - edge, top + size * 0.04)
        context.quadraticCurveTo(middle + size * 0.16, top - size * 0.03,
            middle, top + size * 0.05)
        context.stroke()
        context.globalAlpha = 0.16
        context.fillStyle = color
        context.fill()
        context.globalAlpha = 0.8
        context.beginPath()
        context.moveTo(middle, top + size * 0.05)
        context.lineTo(middle, bottom + size * 0.02)
        context.stroke()
        context.globalAlpha = 0.6
        for (const range of [
            [edge + size * 0.045, middle - size * 0.075],
            [middle + size * 0.075, size - edge - size * 0.045]
        ]) {
            for (const lineY of [0.42, 0.51, 0.6]) {
                context.beginPath()
                context.moveTo(range[0], size * lineY)
                context.lineTo(range[1], size * lineY)
                context.stroke()
            }
        }
        context.globalAlpha = 1
    }

    function renderRoleIcon() {
        const context = getContext("2d")
        context.clearRect(0, 0, width, height)
        const size = Math.min(width, height)
        context.save()
        context.translate((width - size) / 2, (height - size) / 2)
        switch (normalizedRole) {
        case "curator": paintCurator(context, size); break
        case "researcher": paintResearcher(context, size); break
        case "guardian": paintGuardian(context, size); break
        case "library": paintLibrary(context, size); break
        default: paintExecutive(context, size); break
        }
        context.restore()
    }

    onRoleChanged: requestPaint()
    onNormalizedRoleChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onPaint: renderRoleIcon()
}
