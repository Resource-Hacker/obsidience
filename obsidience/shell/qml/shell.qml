pragma ComponentBehavior: Bound

import Quickshell
import "api"
import "panels/top"
import "surfaces/background"

ShellRoot {
    id: root

    property ShellApi shellApi: ShellApi {}
    readonly property var targetScreens: Quickshell.screens.filter(
        screen => screen.name === shellApi.primaryOutputName
    )

    Variants {
        model: root.targetScreens

        Background {
            required property var modelData

            screen: modelData
            shellApi: root.shellApi
        }
    }

    Variants {
        model: root.targetScreens

        TopPanel {
            required property var modelData

            screen: modelData
            shellApi: root.shellApi
        }
    }
}
