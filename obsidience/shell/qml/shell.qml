//@ pragma NativeTextRendering
pragma ComponentBehavior: Bound

import Quickshell
import QtQml
import "api"
import "surfaces/stage"
import "workspace"

ShellRoot {
    id: root

    property ShellApi shellApi: ShellApi {}
    property FullscreenState fullscreenState: FullscreenState {}
    property LockState lockState: LockState {}
    readonly property var samsungScreens: Quickshell.screens.filter(
        screen => screen.name === shellApi.primaryOutputName
    )
    readonly property var usbScreens: Quickshell.screens.filter(
        screen => screen.name === shellApi.usbOutputName
    )
    readonly property var dp4Screens: Quickshell.screens.filter(
        screen => screen.name === shellApi.dp4OutputName
    )
    readonly property bool knowledgeVisible: !lockState.active && !fullscreenState.active

    PaneWorkspace {
        id: samsungWorkspace

        shellApi: root.shellApi
        surfaceId: "samsung"
        targetScreens: root.samsungScreens
        authoritative: true
        locked: root.lockState.active
    }

    PaneWorkspace {
        id: usbWorkspace

        shellApi: root.shellApi
        surfaceId: "usb-c"
        targetScreens: root.usbScreens
        locked: root.lockState.active
    }

    PaneWorkspace {
        id: dp4Workspace

        shellApi: root.shellApi
        surfaceId: "dp-4"
        targetScreens: root.dp4Screens
        locked: root.lockState.active
    }

    ShellCommandServer {
        readerPlacement: samsungWorkspace.readerPlacement
        paneWorkspace: samsungWorkspace
        dockLayout: samsungWorkspace.dockLayout
        surfaceLayout: root.shellApi.surfaceLayout
        knowledgeVisible: root.knowledgeVisible
    }

    Variants {
        model: root.samsungScreens

        Stage {
            required property var modelData

            screen: modelData
            surfaceId: "samsung"
            shellApi: root.shellApi
            locked: root.lockState.active
        }
    }

    Variants {
        model: root.usbScreens

        Stage {
            required property var modelData

            screen: modelData
            surfaceId: "usb-c"
            shellApi: root.shellApi
            locked: root.lockState.active
        }
    }

    Variants {
        model: root.dp4Screens

        Stage {
            required property var modelData

            screen: modelData
            surfaceId: "dp-4"
            shellApi: root.shellApi
            locked: root.lockState.active
        }
    }

}
