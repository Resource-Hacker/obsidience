pragma ComponentBehavior: Bound

import QtQml
import Quickshell
import Quickshell.Io
import Quickshell.Services.Pam
import Quickshell.Wayland

Scope {
    id: root

    required property var shellApi
    readonly property bool active: sessionLock.locked
    readonly property bool secure: sessionLock.secure
    property string password: ""
    property bool authenticating: false
    property bool authenticationFailed: false

    function surfaceIdForScreen(screenName) {
        if (screenName === shellApi.primaryOutputName) {
            return "samsung"
        }
        if (screenName === shellApi.usbOutputName) {
            return "usb-c"
        }
        if (screenName === shellApi.dp4OutputName) {
            return "dp-4"
        }
        return ""
    }

    function requestLock() {
        if (sessionLock.locked) {
            return "locked"
        }
        password = ""
        authenticationFailed = false
        sessionLock.locked = true
        return "locking"
    }

    function tryUnlock() {
        if (!sessionLock.locked || !sessionLock.secure
                || authenticating || password.length === 0) {
            return
        }
        authenticationFailed = false
        authenticating = pam.start()
        if (!authenticating) {
            authenticationFailed = true
        }
    }

    function ownerUnlock() {
        if (!sessionLock.locked) {
            return "unlocked"
        }
        if (!sessionLock.secure || authenticating) {
            return "busy"
        }
        // Owner-authorized local IPC, also used by the Executive's session.unlock.
        // The web graph has no unlock command and never receives credentials.
        password = ""
        authenticationFailed = false
        sessionLock.locked = false
        return "unlocking"
    }

    onPasswordChanged: authenticationFailed = false

    PamContext {
        id: pam

        configDirectory: "/etc/pam.d"
        config: "obsidience"

        onPamMessage: {
            if (responseRequired) {
                respond(root.password)
            }
        }

        onCompleted: result => {
            root.authenticating = false
            if (result === PamResult.Success && sessionLock.secure) {
                root.password = ""
                root.authenticationFailed = false
                sessionLock.locked = false
                return
            }
            root.password = ""
            root.authenticationFailed = true
        }
    }

    WlSessionLock {
        id: sessionLock

        locked: false

        WlSessionLockSurface {
            id: lockSurface

            color: "#02060c"

            LockSurface {
                anchors.fill: parent
                controller: root
                surfaceId: root.surfaceIdForScreen(
                    lockSurface.screen ? lockSurface.screen.name : ""
                )
                graphSurfaceId: root.shellApi.surfaceLayout.graphSurfaceId
            }
        }
    }

    IpcHandler {
        target: "lock"

        function lock(): string {
            return root.requestLock()
        }

        function status(): string {
            return root.secure ? "secure"
                : root.active ? "locking" : "unlocked"
        }

        function unlock(): string {
            return root.ownerUnlock()
        }
    }
}
