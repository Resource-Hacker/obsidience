pragma ComponentBehavior: Bound

import QtQuick
import Quickshell
import "../api"

PanelWindow {
    id: root

    required property ShellApi shellApi
    required property PaneDragSession dragSession
    required property PaneDockLayout dockLayout
    required property string surfaceId
    required property var surfaceScreen
    required property var panes
    required property bool locked

    property string activePaneId: ""

    readonly property bool hasLocalPane: {
        for (const definition of panes) {
            const placement = definition.placement
            if (placement.open && placement.surfaceId === surfaceId) {
                return true
            }
        }
        return false
    }

    screen: surfaceScreen
    visible: hasLocalPane && !locked
    color: "transparent"
    focusable: hasLocalPane && !locked
    aboveWindows: true
    exclusiveZone: 0

    anchors {
        left: true
        right: true
        top: true
        bottom: true
    }

    // One native canvas per Surface; its input is only the union of live panes.
    mask: Region { id: inputMask }

    function activatePane(paneId) {
        activePaneId = paneId
        for (const definition of panes) {
            const placement = definition.placement
            if (placement.paneId === paneId) {
                dragSession.activatePane(placement)
                return
            }
        }
    }

    Item {
        anchors.fill: parent

        Repeater {
            model: root.panes

            PaneItem {
                required property var modelData

                shellApi: root.shellApi
                dragSession: root.dragSession
                dockLayout: root.dockLayout
                surfaceId: root.surfaceId
                paneDefinition: modelData
                panes: root.panes
                activeInCanvas: root.activePaneId === placement.paneId
                onInputRegionReady: region => inputMask.regions.push(region)
                onActivated: paneId => root.activatePane(paneId)
            }
        }
    }
}
