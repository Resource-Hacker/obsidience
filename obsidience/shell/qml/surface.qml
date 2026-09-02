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
    property LockState lockState: LockState {}
    readonly property string surfaceId: String(
        Quickshell.env("OBSIDIENCE_SURFACE_ID") ?? ""
    )
    readonly property var targetSurface: shellApi.surfaceLayout.surface(surfaceId)
    readonly property var targetScreens: Quickshell.screens.filter(
        screen => targetSurface && screen.name === targetSurface.output
    )

    PaneWorkspace {
        shellApi: root.shellApi
        surfaceId: root.surfaceId
        targetScreens: root.targetScreens
        authoritative: false
        locked: root.lockState.active
    }

    Variants {
        model: root.targetScreens

        X11Stage {
            required property var modelData

            screen: modelData
            surfaceId: root.surfaceId
            shellApi: root.shellApi
            locked: root.lockState.active
        }
    }

}
