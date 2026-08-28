pragma ComponentBehavior: Bound

import QtQuick
import Quickshell

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

    function moveDrag(deltaX, deltaY) {
        if (placement.surfaceId !== surfaceId) {
            return
        }

        const nextX = clamp(
            dragStartX + deltaX,
            0,
            surfaceScreen.width - placement.width
        )
        const nextY = clamp(
            dragStartY + deltaY,
            0,
            surfaceScreen.height - placement.height
        )
        placement.previewMove(nextX, nextY)
    }

    function finishDrag(moved) {
        if (!moved || placement.surfaceId !== surfaceId) {
            return
        }

        const paneCenterX = placement.x + placement.width / 2
        if (surfaceId === "samsung"
                && placement.y >= surfaceScreen.height - placement.height
                && paneCenterX >= samsungUsbStart
                && paneCenterX < samsungUsbEnd) {
            const span = samsungUsbEnd - samsungUsbStart - 1
            const mappedCenterX = Math.round(
                ((paneCenterX - samsungUsbStart) / span) * (usbWidth - 1)
            )
            const destinationX = clamp(
                mappedCenterX - placement.width / 2,
                0,
                usbWidth - placement.width
            )
            placement.transfer("usb-c", destinationX, 0)
            return
        }

        if (surfaceId === "usb-c" && placement.y <= 0) {
            const mappedCenterX = samsungUsbStart + Math.round(
                (paneCenterX / Math.max(1, usbWidth - 1))
                    * (samsungUsbEnd - samsungUsbStart - 1)
            )
            const destinationX = clamp(
                mappedCenterX - placement.width / 2,
                0,
                samsungWidth - placement.width
            )
            const destinationY = samsungHeight - placement.height - 12
            placement.transfer("samsung", destinationX, destinationY)
            return
        }

        placement.commitMove()
    }

    PaneFrame {
        anchors.fill: parent
        title: "Surface Pane"
        surfaceLabel: root.surfaceId
        revision: root.placement.revision

        onDragStarted: root.beginDrag()
        onDragMoved: (deltaX, deltaY) => root.moveDrag(deltaX, deltaY)
        onDragFinished: moved => root.finishDrag(moved)
    }
}
