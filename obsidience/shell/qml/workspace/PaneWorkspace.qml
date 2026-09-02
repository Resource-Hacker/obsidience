pragma ComponentBehavior: Bound

import QtQml
import Quickshell
import "../api"
import "../panes/applications"
import "../panes/camera"
import "../panes/chat"
import "../panes/displays"
import "../panes/hardware"
import "../panes/knowledge"
import "../panes/library"
import "../panes/reader"
import "../panes/reviews"
import "../panes/source"
import "../panes/status"
import "../panes/tasks"
import "../panes/terminal"
import "../panes/settings"

Scope {
    id: root

    required property ShellApi shellApi
    required property string surfaceId
    required property var targetScreens
    required property bool locked
    property bool authoritative: false
    property bool launcherOpen: false

    property PaneDockLayout dockLayout: PaneDockLayout {
        authoritative: root.authoritative
    }

    property PanePlacement displaysPlacement: PanePlacement {
        paneId: "displays"
        authoritative: root.authoritative
    }
    property PanePlacement chatPlacement: PanePlacement {
        paneId: "chat"
        authoritative: root.authoritative
        defaultSurfaceId: "usb-c"
        defaultX: 20
        defaultY: 58
        defaultWidth: 600
        defaultHeight: 680
        defaultOpen: true
        defaultZOrder: 20
    }
    property PanePlacement libraryPlacement: PanePlacement {
        paneId: "library"
        authoritative: root.authoritative
        defaultSurfaceId: "usb-c"
        defaultX: 640
        defaultY: 58
        defaultWidth: 620
        defaultHeight: 520
        defaultOpen: true
        defaultZOrder: 21
    }
    property PanePlacement tasksPlacement: PanePlacement {
        paneId: "tasks"
        authoritative: root.authoritative
        defaultSurfaceId: "usb-c"
        defaultX: 1280
        defaultY: 58
        defaultWidth: 620
        defaultHeight: 660
        defaultOpen: true
        defaultZOrder: 22
    }
    property PanePlacement reviewsPlacement: PanePlacement {
        paneId: "reviews"
        authoritative: root.authoritative
        defaultSurfaceId: "usb-c"
        defaultX: 640
        defaultY: 598
        defaultWidth: 620
        defaultHeight: 580
        defaultOpen: true
        defaultZOrder: 23
    }
    property PanePlacement readerPlacement: PanePlacement {
        paneId: "reader"
        authoritative: root.authoritative
        defaultX: 3400
        defaultY: 90
        defaultWidth: 1600
        defaultHeight: 980
        defaultOpen: false
        defaultZOrder: 30
    }
    property PanePlacement knowledgePlacement: PanePlacement {
        paneId: "knowledge"
        authoritative: root.authoritative
        defaultSurfaceId: "usb-c"
        defaultX: 24
        defaultY: 100
        defaultWidth: 520
        defaultHeight: 780
        defaultOpen: false
        defaultZOrder: 31
    }
    property PanePlacement sourcePlacement: PanePlacement {
        paneId: "source"
        authoritative: root.authoritative
        defaultSurfaceId: "usb-c"
        defaultX: 560
        defaultY: 100
        defaultWidth: 560
        defaultHeight: 780
        defaultOpen: false
        defaultZOrder: 32
    }
    property PanePlacement statusPlacement: PanePlacement {
        paneId: "status"
        authoritative: root.authoritative
        defaultSurfaceId: "usb-c"
        defaultX: 160
        defaultY: 100
        defaultWidth: 1040
        defaultHeight: 820
        defaultOpen: false
        defaultZOrder: 33
    }
    property PanePlacement hardwarePlacement: PanePlacement {
        paneId: "hardware"
        authoritative: root.authoritative
        defaultSurfaceId: "usb-c"
        defaultX: 180
        defaultY: 100
        defaultWidth: 1120
        defaultHeight: 860
        defaultOpen: false
        defaultZOrder: 34
    }
    property PanePlacement cameraPlacement: PanePlacement {
        paneId: "camera"
        authoritative: root.authoritative
        defaultSurfaceId: "usb-c"
        defaultX: 260
        defaultY: 120
        defaultWidth: 960
        defaultHeight: 700
        defaultOpen: false
        defaultZOrder: 35
    }
    property PanePlacement settingsPlacement: PanePlacement {
        paneId: "settings"
        authoritative: root.authoritative
        defaultSurfaceId: "usb-c"
        defaultX: 1080
        defaultY: 80
        defaultWidth: 800
        defaultHeight: 680
        defaultOpen: false
        defaultZOrder: 36
    }
    property PanePlacement applicationsPlacement: PanePlacement {
        paneId: "applications"
        authoritative: root.authoritative
        defaultSurfaceId: "usb-c"
        defaultX: 420
        defaultY: 100
        defaultWidth: 1040
        defaultHeight: 760
        defaultOpen: false
        defaultZOrder: 37
    }
    property PanePlacement terminalPlacement: PanePlacement {
        paneId: "terminal"
        authoritative: root.authoritative
        defaultX: 100
        defaultY: 430
        defaultWidth: 1900
        defaultHeight: 900
        defaultOpen: true
        defaultZOrder: 40
    }

    property Component displaysComponent: Component {
        DisplaysPane { surfaceLayout: root.shellApi.surfaceLayout }
    }
    property Component chatComponent: Component { ChatPane {} }
    property Component libraryComponent: Component { LibraryPane {} }
    property Component tasksComponent: Component { TasksPane {} }
    property Component reviewsComponent: Component { ReviewsPane {} }
    property Component readerComponent: Component { ReaderPane {} }
    property Component knowledgeComponent: Component {
        KnowledgePane {
            dockLayout: root.dockLayout
            surfaceId: root.surfaceId
        }
    }
    property Component sourceComponent: Component {
        SourcePane {
            dockLayout: root.dockLayout
            surfaceId: root.surfaceId
        }
    }
    property Component statusComponent: Component { StatusPane {} }
    property Component hardwareComponent: Component { HardwarePane {} }
    property Component cameraComponent: Component { CameraPane {} }
    property Component settingsComponent: Component { SettingsPane {} }
    property Component applicationsComponent: Component { ApplicationsPane {} }
    property Component terminalComponent: Component { TerminalPane {} }

    function placementFor(paneId) {
        for (const definition of paneDefinitions) {
            if (definition.placement.paneId === paneId) {
                return definition.placement
            }
        }
        return null
    }

    function topPlacement(surface) {
        let top = null
        for (const definition of paneDefinitions) {
            const placement = definition.placement
            if (placement.open && placement.surfaceId === surface
                    && (!top || placement.zOrder > top.zOrder)) {
                top = placement
            }
        }
        return top
    }

    function nextZOrder(surface) {
        const top = topPlacement(surface)
        return top ? top.zOrder + 1 : 10
    }

    function presentPane(placement) {
        if (!placement) {
            return
        }
        placement.presentOn(
            placement.surfaceId,
            placement.x,
            placement.y,
            nextZOrder(placement.surfaceId)
        )
    }

    function presentPaneOn(placement, targetSurfaceId, x, y) {
        if (!placement) {
            return
        }
        const surface = shellApi.surfaceLayout.surface(targetSurfaceId)
        const nextX = surface ? shellApi.surfaceLayout.clampPaneX(
            surface, placement.width, x
        ) : x
        const nextY = surface ? shellApi.surfaceLayout.clampPaneY(
            surface, placement.height, y
        ) : y
        placement.presentOn(
            targetSurfaceId,
            nextX,
            nextY,
            nextZOrder(targetSurfaceId)
        )
    }

    property PaneDragSession dragSession: PaneDragSession {
        surfaceId: root.surfaceId
        onPlacementAccepted: record => {
            const placement = root.placementFor(record.pane_id)
            if (placement) {
                placement.applyRecord(record)
            }
        }
    }

    // The registry is Surface state, not screen-discovery state. In particular,
    // X11 may populate targetScreens after this Scope is created.
    readonly property var paneDefinitions: [
        {"label": "Chat", "title": "Chat", "icon": "chat", "accent": "#67e8f9",
            "placement": chatPlacement,
            "component": chatComponent, "minWidth": 460, "minHeight": 360},
        {"label": "Library", "title": "Library", "icon": "library", "accent": "#6ee7b7",
            "placement": libraryPlacement,
            "component": libraryComponent, "minWidth": 500, "minHeight": 360},
        {"label": "Tasks", "title": "Tasks", "icon": "tasks", "accent": "#fcd34d",
            "placement": tasksPlacement,
            "component": tasksComponent, "minWidth": 540, "minHeight": 380},
        {"label": "Reviews", "title": "Review Queue", "icon": "reviews", "accent": "#86efac",
            "placement": reviewsPlacement,
            "component": reviewsComponent, "minWidth": 500, "minHeight": 340},
        {"label": "Reader", "title": "Reader", "icon": "reader", "accent": "#a5f3fc",
            "placement": readerPlacement,
            "component": readerComponent, "minWidth": 520, "minHeight": 360},
        {"label": "Knowledge", "title": "Knowledge", "icon": "knowledge", "accent": "#93c5fd",
            "placement": knowledgePlacement,
            "component": knowledgeComponent, "minWidth": 320, "minHeight": 320},
        {"label": "Source", "title": "Source", "icon": "source", "accent": "#c4b5fd",
            "placement": sourcePlacement,
            "component": sourceComponent, "minWidth": 340, "minHeight": 280},
        {"label": "Models", "title": "Models", "icon": "models", "accent": "#f0abfc",
            "placement": statusPlacement,
            "component": statusComponent, "minWidth": 640, "minHeight": 420},
        {"label": "Hardware", "title": "Hardware", "icon": "hardware", "accent": "#fbbf24",
            "placement": hardwarePlacement,
            "component": hardwareComponent, "minWidth": 680, "minHeight": 440},
        {"label": "Camera", "title": "Camera", "icon": "camera", "accent": "#22d3ee",
            "placement": cameraPlacement,
            "component": cameraComponent, "minWidth": 520, "minHeight": 380},
        {"label": "Settings", "title": "Settings", "icon": "settings", "accent": "#fb923c",
            "placement": settingsPlacement,
            "component": settingsComponent, "minWidth": 680, "minHeight": 440},
        {"label": "Applications", "title": "Applications", "icon": "applications", "accent": "#2dd4bf",
            "placement": applicationsPlacement,
            "component": applicationsComponent, "minWidth": 620, "minHeight": 420},
        {"label": "Terminal", "title": "Terminal", "icon": "terminal", "accent": "#4ade80",
            "placement": terminalPlacement,
            "component": terminalComponent, "minWidth": 660, "minHeight": 400},
        {"label": "Displays", "title": "Displays", "icon": "displays", "accent": "#60a5fa",
            "placement": displaysPlacement,
            "component": displaysComponent, "minWidth": 520, "minHeight": 340}
    ]

    Variants {
        model: root.targetScreens

        PaneCanvas {
            required property var modelData

            surfaceScreen: modelData
            surfaceId: root.surfaceId
            shellApi: root.shellApi
            dragSession: root.dragSession
            dockLayout: root.dockLayout
            panes: root.paneDefinitions
            locked: root.locked
        }
    }

    Variants {
        model: root.targetScreens

        PaneLauncher {
            required property var modelData

            surfaceScreen: modelData
            surfaceId: root.surfaceId
            shellApi: root.shellApi
            dockLayout: root.dockLayout
            panes: root.paneDefinitions
            locked: root.locked
            launcherOpen: root.launcherOpen
            onLauncherRequested: root.launcherOpen = !root.launcherOpen
            onPresentRequested: (placement, targetSurfaceId, x, y) =>
                root.presentPaneOn(placement, targetSurfaceId, x, y)
        }
    }
}
