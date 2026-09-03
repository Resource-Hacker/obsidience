pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import "../api"

FocusScope {
    id: root

    required property ShellApi shellApi
    required property PaneDragSession dragSession
    required property PaneDockLayout dockLayout
    required property string surfaceId
    required property var paneDefinition
    required property var panes
    property bool activeInCanvas: false

    readonly property PanePlacement placement: paneDefinition.placement
    readonly property var currentSurface: shellApi.surfaceLayout.surface(surfaceId)
    readonly property bool dragOwnsPane: dragSession.active
        && dragSession.paneId === placement.paneId
    readonly property bool moduleDocked: dockLayout.isDocked(placement.paneId)
    readonly property int dockRevision: dockLayout.revision
    readonly property bool paneVisible: !moduleDocked && placement.open
        && placement.surfaceId === surfaceId
    readonly property bool tiled: shellApi.surfaceLayout.validTileBounds(
        surfaceId, placement.tileBounds
    )
    readonly property int renderWidth: tiled ? placement.width : currentSurface
        ? shellApi.surfaceLayout.clampPaneSize(
            placement.width,
            paneDefinition.minWidth,
            currentSurface.logical_width
        ) : placement.width
    readonly property int renderHeight: tiled ? placement.height : currentSurface
        ? shellApi.surfaceLayout.clampPaneSize(
            placement.height,
            paneDefinition.minHeight,
            currentSurface.logical_height
        ) : placement.height
    readonly property int renderX: dragOwnsPane ? dragSession.x
        : tiled ? placement.x : shellApi.surfaceLayout.clampPaneX(
            currentSurface, renderWidth, placement.x
        )
    readonly property int renderY: dragOwnsPane ? dragSession.y
        : tiled ? placement.y : shellApi.surfaceLayout.clampPaneY(
            currentSurface, renderHeight, placement.y
        )
    property Region inputRegion: Region { item: root }

    property real dragStartX: 0
    property real dragStartY: 0
    property real resizeStartWidth: 0
    property real resizeStartHeight: 0
    property bool dragReady: false

    signal activated(string paneId)
    signal deactivated(string paneId)
    signal inputRegionReady(var region)

    x: renderX
    y: renderY
    width: paneVisible ? renderWidth : 0
    height: paneVisible ? renderHeight : 0
    visible: paneVisible
    z: activeInCanvas ? 1000000 : placement.zOrder

    Component.onCompleted: inputRegionReady(inputRegion)
    onActiveFocusChanged: {
        if (activeFocus) {
            activated(placement.paneId)
        } else {
            deactivated(placement.paneId)
        }
    }

    // Observe the first press without consuming it from the pane content.
    PointHandler {
        acceptedButtons: Qt.LeftButton
        onActiveChanged: if (active) {
            root.forceActiveFocus(Qt.MouseFocusReason)
        }
    }

    function beginDrag() {
        forceActiveFocus(Qt.MouseFocusReason)
        activated(placement.paneId)
        dragStartX = renderX
        dragStartY = renderY
        dragReady = dragSession.begin(
            placement.paneId, placement, renderX, renderY
        )
    }

    function moveDrag(deltaX, deltaY, pointerX, pointerY) {
        if (!dragReady || dragSession.phase !== "local"
                || placement.surfaceId !== surfaceId || !currentSurface) {
            return
        }
        const unboundedX = dragStartX + deltaX
        const unboundedY = dragStartY + deltaY
        const sourceX = shellApi.surfaceLayout.clampPaneX(
            currentSurface, renderWidth, unboundedX
        )
        const sourceY = shellApi.surfaceLayout.clampPaneY(
            currentSurface, renderHeight, unboundedY
        )
        dragSession.previewLocal(sourceX, sourceY)
    }

    function finishDrag(moved) {
        if (!dragReady) {
            return
        }
        dragReady = false
        dragSession.finish(moved)
        activated(placement.paneId)
    }

    function beginResize() {
        forceActiveFocus(Qt.MouseFocusReason)
        activated(placement.paneId)
        resizeStartWidth = renderWidth
        resizeStartHeight = renderHeight
    }

    function moveResize(deltaX, deltaY) {
        if (placement.surfaceId !== surfaceId || !currentSurface) {
            return
        }
        const maximumWidth = Math.max(
            paneDefinition.minWidth,
            currentSurface.logical_width - renderX
        )
        const maximumHeight = Math.max(
            paneDefinition.minHeight,
            currentSurface.logical_height - renderY
        )
        placement.previewResize(
            shellApi.surfaceLayout.clampPaneSize(
                resizeStartWidth + deltaX,
                paneDefinition.minWidth,
                maximumWidth
            ),
            shellApi.surfaceLayout.clampPaneSize(
                resizeStartHeight + deltaY,
                paneDefinition.minHeight,
                maximumHeight
            )
        )
    }

    function finishResize(moved) {
        if (!moved || placement.surfaceId !== surfaceId) {
            return
        }
        placement.commitResize()
        activated(placement.paneId)
    }

    PaneFrame {
        anchors.fill: parent
        title: root.paneDefinition.title
        theme: root.shellApi.theme
        active: root.activeInCanvas && root.activeFocus

        onDragStarted: root.beginDrag()
        onDragMoved: (deltaX, deltaY, pointerX, pointerY) => root.moveDrag(
            deltaX,
            deltaY,
            pointerX,
            pointerY
        )
        onDragFinished: moved => root.finishDrag(moved)
        onResizeStarted: root.beginResize()
        onResizeMoved: (deltaX, deltaY) => root.moveResize(deltaX, deltaY)
        onResizeFinished: moved => root.finishResize(moved)
        onCloseRequested: root.placement.dismiss()

        Loader {
            anchors.fill: parent
            active: root.paneVisible
            sourceComponent: root.placement.paneId === "reader"
                ? dockHostComponent : root.paneDefinition.component
        }
    }

    Component {
        id: dockHostComponent

        PaneDockHost {
            hostDefinition: root.paneDefinition
            paneDefinitions: root.panes
            dockLayout: root.dockLayout
            surfaceId: root.surfaceId
        }
    }
}
