pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import "../api"

FloatingWindow {
    id: root

    required property ShellApi shellApi
    required property var paneWorkspace
    required property PaneDockLayout dockLayout
    required property var paneDefinition
    required property var panes

    readonly property PanePlacement placement: paneDefinition.placement
    readonly property bool moduleDocked: dockLayout.isDocked(placement.paneId)
    readonly property bool paneVisible: placement.hydrated
        && placement.open && !moduleDocked
        && surfaceScreen !== null
    readonly property var surfaceScreen: paneWorkspace.screenForSurface(
        placement.surfaceId
    )
    readonly property var defaultTileRect: shellApi.surfaceLayout.tileRect(
        placement.surfaceId, placement.tileBounds
    )
    readonly property int defaultGuideTolerance: 5
    readonly property bool tiled: defaultTileRect !== null
    readonly property bool tiledResizeEnabled: tiled
        && shellApi.surfaceLayout.tileResizeLimitPercent > 0
    readonly property bool resizeControlsEnabled: !tiled || tiledResizeEnabled
    readonly property bool defaultSizeFeedbackEnabled:
        placement.surfaceId !== "samsung"
        || !shellApi.surfaceLayout.oledModeEnabled
    readonly property bool defaultWidthReached: defaultTileRect !== null
        && Math.abs(width - defaultTileRect.width) <= defaultGuideTolerance
    readonly property bool defaultHeightReached: defaultTileRect !== null
        && Math.abs(height - defaultTileRect.height) <= defaultGuideTolerance
    readonly property string verticalDefaultGuideEdge: {
        const bounds = placement.tileBounds
        if (!resizeControlsEnabled) {
            return ""
        }
        if (!tiled) {
            return "right"
        }
        if (!shellApi.surfaceLayout.validTileBounds(
                placement.surfaceId, bounds)) {
            return ""
        }
        if (bounds.right < bounds.columns) {
            return "right"
        }
        return bounds.left > 0 ? "left" : ""
    }
    readonly property string horizontalDefaultGuideEdge: {
        const bounds = placement.tileBounds
        if (!resizeControlsEnabled) {
            return ""
        }
        if (!tiled) {
            return "bottom"
        }
        if (!shellApi.surfaceLayout.validTileBounds(
                placement.surfaceId, bounds)) {
            return ""
        }
        if (bounds.bottom < bounds.rows) {
            return "bottom"
        }
        return bounds.top > 0 ? "top" : ""
    }
    // Quickshell 0.3.1 consumes its internal close latch when a visible
    // FloatingWindow changes screen. Keep the window hidden for that one
    // public-property transition so later compositor closes still work.
    property var activeScreen: null
    property bool screenTransitionPending: true
    property int screenTransitionGeneration: 0

    title: "obsidience-pane:" + placement.paneId
    screen: activeScreen
    visible: paneVisible && activeScreen !== null && !screenTransitionPending
    implicitWidth: Math.max(paneDefinition.minWidth, placement.width)
    implicitHeight: Math.max(paneDefinition.minHeight, placement.height)
    minimumSize: Qt.size(paneDefinition.minWidth, paneDefinition.minHeight)
    color: "transparent"

    function selectSurfaceScreen() {
        screenTransitionGeneration += 1
        const generation = screenTransitionGeneration
        const target = surfaceScreen
        if (target === null || screen === target) {
            activeScreen = target
            screenTransitionPending = false
            return
        }
        screenTransitionPending = true
        Qt.callLater(() => {
            if (generation !== screenTransitionGeneration) {
                return
            }
            activeScreen = target
            Qt.callLater(() => {
                if (generation === screenTransitionGeneration) {
                    screenTransitionPending = false
                }
            })
        })
    }

    Component.onCompleted: selectSurfaceScreen()
    onSurfaceScreenChanged: selectSurfaceScreen()

    PaneFrame {
        anchors.fill: parent
        title: root.paneDefinition.title
        theme: root.shellApi.theme
        defaultWidthReached: root.defaultWidthReached
        defaultHeightReached: root.defaultHeightReached
        verticalDefaultGuideEdge: root.verticalDefaultGuideEdge
        horizontalDefaultGuideEdge: root.horizontalDefaultGuideEdge
        defaultSizeFeedbackEnabled: root.defaultSizeFeedbackEnabled

        onMoveRequested: root.startSystemMove()
        onResizeRequested: edges => root.startSystemResize(edges)
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
            surfaceId: root.placement.surfaceId
        }
    }
}
