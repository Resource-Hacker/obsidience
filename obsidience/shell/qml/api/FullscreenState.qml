pragma ComponentBehavior: Bound

import QtQml
import Quickshell
import Quickshell.Io

QtObject {
    id: root

    readonly property string statePath: Quickshell.env("XDG_RUNTIME_DIR")
        + "/obsidience-shell-fullscreen.state"
    property bool active: false

    function reloadState() {
        active = stateFile.text().trim() === "1"
    }

    property FileView stateFile: FileView {
        id: stateFile

        path: root.statePath
        preload: true
        watchChanges: true

        onFileChanged: stateFile.reload()
        onLoaded: root.reloadState()
    }

    Component.onCompleted: reloadState()
}
