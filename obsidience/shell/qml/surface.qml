pragma ComponentBehavior: Bound

import Quickshell
import "api"
import "workspace"

ShellRoot {
    id: root

    property ShellApi shellApi: ShellApi {}
    property PanePlacement panePlacement: PanePlacement {}
    readonly property var targetScreens: Quickshell.screens.filter(
        screen => screen.name === shellApi.usbOutputName
    )

    Variants {
        model: root.targetScreens

        PaneWindow {
            required property var modelData

            surfaceScreen: modelData
            surfaceId: "usb-c"
            placement: root.panePlacement
        }
    }
}
