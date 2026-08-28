pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import Quickshell.Io

PanelWindow {
    id: root

    required property PanePlacement placement
    required property string surfaceId
    required property var surfaceScreen

    property real dragStartX: 0
    property real dragStartY: 0

    readonly property int samsungUsbStart: 1706
    readonly property int samsungUsbEnd: 3413
    readonly property int samsungWidth: 5120
    readonly property int samsungHeight: 1440
    readonly property int usbWidth: 1920
    readonly property int usbHeight: 1200
    readonly property int usbScale: 2

    screen: surfaceScreen
    visible: placement.open && placement.surfaceId === surfaceId
    implicitWidth: placement.width
    implicitHeight: placement.height
    color: "transparent"
    focusable: false
    aboveWindows: true
    exclusiveZone: 0

    anchors {
        left: true
        top: true
    }

    margins {
        left: placement.x
        top: placement.y
    }

    function clamp(value, minimum, maximum) {
        return Math.max(minimum, Math.min(maximum, value))
    }

    function beginDrag() {
        dragStartX = placement.x
        dragStartY = placement.y
    }

    function routePointer(command) {
        pointerCommand.exec([
            "/usr/bin/sh",
            "-c",
            "printf '%s\\n' \"$1\" > /run/user/1000/usb-monitor-edge-bridge.cmd",
            "obsidience-surface",
            command
        ])
    }

    function moveDrag(deltaX, deltaY, pointerX, pointerY) {
        if (placement.surfaceId !== surfaceId) {
            return
        }

        const unboundedX = dragStartX + deltaX
        const unboundedY = dragStartY + deltaY
        const contactX = unboundedX + pointerX

        if (surfaceId === "samsung"
                && deltaY > 0
                && unboundedY + placement.height >= samsungHeight
                && contactX >= samsungUsbStart
                && contactX < samsungUsbEnd) {
            const sourceSpan = samsungUsbEnd - samsungUsbStart - 1
            const mappedPointerX = Math.round(
                ((contactX - samsungUsbStart) / sourceSpan) * (usbWidth - 1)
            )
            const destinationX = clamp(
                mappedPointerX - pointerX,
                0,
                usbWidth - placement.width
            )
            const destinationPointerX = destinationX + pointerX
            const destinationPointerY = pointerY
            placement.transfer("usb-c", destinationX, 0)
            routePointer(
                "enterxy "
                    + Math.round(destinationPointerX * usbScale)
                    + " "
                    + Math.round(destinationPointerY * usbScale)
            )
            return
        }

        if (surfaceId === "usb-c"
                && deltaY < 0
                && unboundedY <= 0
                && contactX >= 0
                && contactX < usbWidth) {
            const mappedPointerX = samsungUsbStart + Math.round(
                (contactX / Math.max(1, usbWidth - 1))
                    * (samsungUsbEnd - samsungUsbStart - 1)
            )
            const destinationX = clamp(
                mappedPointerX - pointerX,
                0,
                samsungWidth - placement.width
            )
            const destinationY = samsungHeight - placement.height
            const destinationPointerX = destinationX + pointerX
            const destinationPointerY = destinationY + pointerY
            placement.transfer("samsung", destinationX, destinationY)
            routePointer(
                "exitxy "
                    + Math.round(destinationPointerX)
                    + " "
                    + Math.round(destinationPointerY)
            )
            return
        }

        const nextX = clamp(
            unboundedX,
            0,
            surfaceScreen.width - placement.width
        )
        const nextY = clamp(
            unboundedY,
            0,
            surfaceScreen.height - placement.height
        )
        placement.previewMove(nextX, nextY)
    }

    function finishDrag(moved) {
        if (!moved || placement.surfaceId !== surfaceId) {
            return
        }

        placement.commitMove()
    }

    Process {
        id: pointerCommand
    }

    PaneFrame {
        anchors.fill: parent
        title: "Surface Pane"
        surfaceLabel: root.surfaceId
        revision: root.placement.revision

        onDragStarted: root.beginDrag()
        onDragMoved: (deltaX, deltaY, pointerX, pointerY) => root.moveDrag(
            deltaX,
            deltaY,
            pointerX,
            pointerY
        )
        onDragFinished: moved => root.finishDrag(moved)
    }
}
