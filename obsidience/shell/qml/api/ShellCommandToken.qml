pragma Singleton
pragma ComponentBehavior: Bound

import QtQml
import Quickshell
import Quickshell.Io

// Any web page can open a loopback WebSocket and name obsidience.shell.v1, so
// the command server admits only clients presenting this user-only runtime
// token. The host unit writes a fresh one before every start; this process reads
// it once. Python clients read the same file per connection, and pages served
// by the Harness fetch it from its same-origin /api/shell/command-token.
Singleton {
    id: root

    readonly property string path: Quickshell.env("XDG_RUNTIME_DIR")
        + "/obsidience-shell/command.token"
    property string value: ""
    // Appended to "ws://127.0.0.1:8768"; empty when no valid token was read.
    readonly property string query: value ? "/?token=" + value : ""

    function reload() {
        const token = tokenFile.text().trim()
        value = /^[0-9a-f]{64}$/.test(token) ? token : ""
        if (!value) {
            console.warn("Shell command token is missing or invalid:", path)
        }
    }

    property FileView tokenFile: FileView {
        id: tokenFile

        path: root.path
        preload: true
        blockLoading: true

        onLoaded: root.reload()
        onLoadFailed: root.reload()
    }

    Component.onCompleted: reload()
}
