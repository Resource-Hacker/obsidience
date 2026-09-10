//@ pragma AppId io.obsidience.shell
//@ pragma NativeTextRendering
pragma ComponentBehavior: Bound

import Quickshell
import QtQml
import "api"
import "lock"
import "surfaces/stage"
import "workspace"

ShellRoot {
    id: root

    // Apply changes through the guarded restart; concurrent QML generations
    // cannot share the command listener or the secure session-lock lifecycle.
    Component.onCompleted: Quickshell.watchFiles = false

    property ShellApi shellApi: ShellApi {}
    property FullscreenState fullscreenState: FullscreenState {}
    property LockController lockController: LockController {
        shellApi: root.shellApi
    }
    readonly property var samsungScreens: Quickshell.screens.filter(
        screen => screen.name === shellApi.primaryOutputName
    )
    readonly property var usbScreens: Quickshell.screens.filter(
        screen => screen.name === shellApi.usbOutputName
    )
    readonly property var dp4Screens: Quickshell.screens.filter(
        screen => screen.name === shellApi.dp4OutputName
    )
    readonly property var workspaceScreens: samsungScreens.concat(
        usbScreens
    ).concat(dp4Screens)
    readonly property bool knowledgeVisible: !lockController.active
        && !fullscreenState.active

    PaneWorkspace {
        id: paneWorkspace

        shellApi: root.shellApi
        targetScreens: root.workspaceScreens
        monitoringAllowed: !root.lockController.active
    }

    ShellCommandServer {
        id: commandServer

        readerPlacement: paneWorkspace.readerPlacement
        paneWorkspace: paneWorkspace
        dockLayout: paneWorkspace.dockLayout
        surfaceLayout: root.shellApi.surfaceLayout
        knowledgeVisible: root.knowledgeVisible
        sessionLocked: root.lockController.active
    }

    Variants {
        model: root.samsungScreens

        Stage {
            required property var modelData

            screen: modelData
            surfaceId: "samsung"
            shellApi: root.shellApi
            locked: root.lockController.active
        }
    }

    Variants {
        model: root.usbScreens

        Stage {
            required property var modelData

            screen: modelData
            surfaceId: "usb-c"
            shellApi: root.shellApi
            locked: root.lockController.active
        }
    }

    Variants {
        model: root.dp4Screens

        Stage {
            required property var modelData

            screen: modelData
            surfaceId: "dp-4"
            shellApi: root.shellApi
            locked: root.lockController.active
        }
    }

}
