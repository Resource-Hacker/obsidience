pragma ComponentBehavior: Bound

import Quickshell
import "api"
import "surfaces/stage"

ShellRoot {
    id: root

    property ShellApi shellApi: ShellApi {}
    readonly property var targetScreens: Quickshell.screens.filter(
        screen => screen.name === shellApi.primaryOutputName
    )

    Variants {
        model: root.targetScreens

        Stage {
            required property var modelData

            screen: modelData
            shellApi: root.shellApi
        }
    }
}
