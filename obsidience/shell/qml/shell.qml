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
    readonly property var targetScreens: Quickshell.screens.filter(
        screen => screen.name === shellApi.primaryOutputName
    )
    readonly property bool knowledgeVisible: !lockState.active && !fullscreenState.active

    PaneWorkspace {
        id: paneWorkspace

        shellApi: root.shellApi
        surfaceId: "samsung"
        targetScreens: root.targetScreens
        authoritative: true
        locked: root.lockState.active
    }

    ShellCommandServer {
        readerPlacement: paneWorkspace.readerPlacement
        paneWorkspace: paneWorkspace
        dockLayout: paneWorkspace.dockLayout
        surfaceLayout: root.shellApi.surfaceLayout
        knowledgeVisible: root.knowledgeVisible
    }

    Variants {
        model: root.targetScreens

        Stage {
            required property var modelData

            screen: modelData
            surfaceId: "samsung"
            shellApi: root.shellApi
            locked: root.lockState.active
        }
    }

}
