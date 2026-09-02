pragma ComponentBehavior: Bound

import QtQuick

Rectangle {
    id: root

    property string fieldKey: ""
    property int optionIndex: 0

    width: 22
    height: 22
    radius: 3
    color: "#02070c"

    onFieldKeyChanged: portrait.requestPaint()
    onOptionIndexChanged: portrait.requestPaint()

    Canvas {
        id: portrait

        anchors.fill: parent
        antialiasing: true

        function glow(context, radius, color, alpha) {
            const center = width / 2
            const gradient = context.createRadialGradient(
                center, center, 0, center, center, radius
            )
            gradient.addColorStop(0, color)
            gradient.addColorStop(1, "rgba(0,0,0,0)")
            context.save()
            context.globalAlpha = alpha
            context.fillStyle = gradient
            context.fillRect(0, 0, width, height)
            context.restore()
        }

        function disc(context, alpha) {
            const center = width / 2
            const radius = width * 0.34
            const gradient = context.createRadialGradient(
                center - radius * 0.3, center - radius * 0.34,
                radius * 0.1, center, center, radius
            )
            gradient.addColorStop(0, "#f0f9ff")
            gradient.addColorStop(0.35, "#67e8f9")
            gradient.addColorStop(1, "#155e75")
            context.save()
            context.globalAlpha = alpha === undefined ? 1 : alpha
            context.fillStyle = gradient
            context.beginPath()
            context.arc(center, center, radius, 0, Math.PI * 2)
            context.fill()
            context.restore()
        }

        function ring(context, radius, dashed) {
            context.save()
            context.strokeStyle = "#67e8f9"
            context.lineWidth = 1.4
            context.setLineDash(dashed ? [3, 2] : [])
            context.beginPath()
            context.arc(width / 2, height / 2, radius, 0, Math.PI * 2)
            context.stroke()
            context.restore()
        }

        function flare(context, span) {
            context.save()
            context.strokeStyle = "rgba(255,255,255,0.85)"
            context.lineWidth = 1
            context.beginPath()
            context.moveTo(width / 2 - span, height / 2)
            context.lineTo(width / 2 + span, height / 2)
            context.moveTo(width / 2, height / 2 - span)
            context.lineTo(width / 2, height / 2 + span)
            context.stroke()
            context.restore()
        }

        function roundedPath(context, x, y, side, radius) {
            const right = x + side
            const bottom = y + side
            context.beginPath()
            context.moveTo(x + radius, y)
            context.lineTo(right - radius, y)
            context.quadraticCurveTo(right, y, right, y + radius)
            context.lineTo(right, bottom - radius)
            context.quadraticCurveTo(right, bottom, right - radius, bottom)
            context.lineTo(x + radius, bottom)
            context.quadraticCurveTo(x, bottom, x, bottom - radius)
            context.lineTo(x, y + radius)
            context.quadraticCurveTo(x, y, x + radius, y)
            context.closePath()
        }

        function tile(context, rounded, hollow) {
            const inset = width * 0.18
            const side = width - inset * 2
            const radius = rounded ? width * 0.13 : width * 0.025
            const gradient = context.createLinearGradient(
                inset, inset, width - inset, height - inset
            )
            gradient.addColorStop(0, "#ecfeff")
            gradient.addColorStop(0.35, "#67e8f9")
            gradient.addColorStop(1, "#155e75")
            roundedPath(context, inset, inset, side, radius)
            context.save()
            context.globalAlpha = hollow ? 0.16 : 0.9
            context.fillStyle = gradient
            context.fill()
            context.restore()
            context.strokeStyle = "#67e8f9"
            context.lineWidth = 1.35
            context.stroke()
        }

        function dataMarks(context) {
            context.save()
            context.strokeStyle = "rgba(207,250,254,0.78)"
            context.lineWidth = 0.8
            for (const offset of [-0.13, 0.13]) {
                context.beginPath()
                context.moveTo(width * 0.3, height * (0.5 + offset))
                context.lineTo(width * 0.7, height * (0.5 + offset))
                context.stroke()
            }
            context.restore()
        }

        function paintSubject(context, index) {
            if (index === 0) {
                disc(context)
                ring(context, width * 0.44, false)
            } else if (index === 1) {
                glow(context, width * 0.48, "#67e8f9", 0.9)
                glow(context, width * 0.2, "#ffffff", 0.9)
            } else if (index === 2) {
                disc(context)
                glow(context, width * 0.16, "#ffffff", 1)
                flare(context, width * 0.3)
            } else if (index === 3) {
                disc(context, 0.18)
                ring(context, width * 0.4, false)
            } else if (index === 4) {
                glow(context, width * 0.48, "#67e8f9", 0.45)
                tile(context, true, false)
            } else {
                tile(context, false, true)
                dataMarks(context)
            }
        }

        function paintArticle(context, index) {
            if (index === 0) {
                glow(context, width * 0.46, "#67e8f9", 0.8)
                glow(context, width * 0.14, "#ffffff", 1)
                flare(context, width * 0.42)
            } else if (index === 1) {
                glow(context, width * 0.46, "#67e8f9", 0.8)
                glow(context, width * 0.14, "#ffffff", 1)
            } else if (index === 2) {
                disc(context)
            } else if (index === 3) {
                glow(context, width * 0.34, "#fcd34d", 0.85)
                glow(context, width * 0.12, "#fff7ed", 1)
            } else if (index === 4) {
                glow(context, width * 0.46, "#67e8f9", 0.65)
                tile(context, true, false)
                flare(context, width * 0.26)
            } else {
                tile(context, false, false)
                dataMarks(context)
            }
        }

        function paintRing(context, index) {
            disc(context, index === 3 ? 0.55 : 0.35)
            if (index === 0) ring(context, width * 0.42, false)
            else if (index === 1) ring(context, width * 0.42, true)
            else if (index === 2) {
                ring(context, width * 0.44, false)
                ring(context, width * 0.32, false)
            }
        }

        function paintCore(context, index) {
            if (index === 4) {
                const center = width / 2
                const radius = width * 0.4
                context.save()
                context.strokeStyle = "rgba(110,231,183,0.9)"
                context.fillStyle = "rgba(52,211,153,0.28)"
                context.lineWidth = 1.1
                context.beginPath()
                for (let vertex = 0; vertex < 6; vertex += 1) {
                    const angle = (30 + vertex * 60) * Math.PI / 180
                    const x = center + Math.cos(angle) * radius
                    const y = center - Math.sin(angle) * radius
                    if (vertex === 0) context.moveTo(x, y)
                    else context.lineTo(x, y)
                }
                context.closePath()
                context.fill()
                context.stroke()
                context.restore()
                return
            }
            glow(context, width * 0.44, "#67e8f9", 0.72)
            if (index === 1) {
                glow(context, width * 0.18, "#ffffff", 0.9)
            } else if (index === 3) {
                glow(context, width * 0.2, "#ffffff", 0.95)
                for (const radius of [0.18, 0.3, 0.42]) {
                    ring(context, width * radius, false)
                }
            } else {
                context.save()
                context.strokeStyle = "rgba(255,255,255,0.78)"
                context.lineWidth = 1
                for (let arm = 0; arm < (index === 2 ? 2 : 3); arm += 1) {
                    context.beginPath()
                    for (let step = 0; step <= 12; step += 1) {
                        const progress = step / 12
                        const angle = arm * Math.PI + progress * (index === 2 ? 3.4 : 2.4)
                        const radius = progress * width * 0.4
                        const x = width / 2 + Math.cos(angle) * radius
                        const y = height / 2 + Math.sin(angle) * radius
                        if (step === 0) context.moveTo(x, y)
                        else context.lineTo(x, y)
                    }
                    context.stroke()
                }
                context.restore()
            }
        }

        onPaint: {
            const context = getContext("2d")
            context.clearRect(0, 0, width, height)
            if (root.fieldKey === "articleStyle") {
                paintArticle(context, root.optionIndex)
            } else if (root.fieldKey === "ringStyle") {
                paintRing(context, root.optionIndex)
            } else if (root.fieldKey === "coreStyle") {
                paintCore(context, root.optionIndex)
            } else {
                paintSubject(context, root.optionIndex)
            }
        }
    }
}
