pragma ComponentBehavior: Bound

import QtQml
import Quickshell
import Quickshell.Io

QtObject {
    id: root

    readonly property string statePath: Quickshell.env("XDG_RUNTIME_DIR")
        + "/obsidience-shell/lock-state"
    property bool active: true

    function reloadState() {
        // Missing or incomplete state fails closed until KScreenLocker is known.
        active = stateFile.text().trim() !== "0"
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
