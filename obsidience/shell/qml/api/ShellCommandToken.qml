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
// A second token, adapter.token, is read only by the window adapter and is never
// served over HTTP; only its holder may publish the Scene.
Singleton {
    id: root

    readonly property string path: Quickshell.env("XDG_RUNTIME_DIR")
        + "/obsidience-shell/command.token"
    readonly property string adapterPath: Quickshell.env("XDG_RUNTIME_DIR")
        + "/obsidience-shell/adapter.token"
    property string value: ""
    property string adapterValue: ""
    // Appended to "ws://127.0.0.1:8768"; empty when no valid token was read.
    readonly property string query: value ? "/?token=" + value : ""

    function read(file, path) {
        const token = file.text().trim()
        if (/^[0-9a-f]{64}$/.test(token)) return token
        console.warn("Shell token is missing or invalid:", path)
        return ""
    }

    function reload() {
        value = read(tokenFile, path)
    }

    function reloadAdapter() {
        adapterValue = read(adapterFile, adapterPath)
    }

    property FileView tokenFile: FileView {
        id: tokenFile

        path: root.path
        preload: true
        blockLoading: true

        onLoaded: root.reload()
        onLoadFailed: root.reload()
    }

    property FileView adapterFile: FileView {
        path: root.adapterPath
        preload: true
        blockLoading: true

        onLoaded: root.reloadAdapter()
        onLoadFailed: root.reloadAdapter()
    }

    Component.onCompleted: {
        reload()
        reloadAdapter()
    }
}
