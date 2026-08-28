pragma ComponentBehavior: Bound

import QtCore
import QtQml
import Quickshell.Io

QtObject {
    id: root

    readonly property string schema: "obsidience.surface-placement.v1"
    readonly property string paneId: "surface-probe"
    readonly property string statePath: StandardPaths.writableLocation(
        StandardPaths.RuntimeLocation
    ) + "/obsidience-shell/pane-placement.json"

    property string surfaceId: "samsung"
    property int x: 2180
    property int y: 260
    property int width: 720
    property int height: 420
    property bool open: true
    property int zOrder: 10
    property int revision: 0

    function isNumber(value) {
        return typeof value === "number" && isFinite(value)
    }

    function applyRecord(record) {
        if (!record || record.schema !== schema || record.pane_id !== paneId) {
            return
        }
        if (record.surface_id !== "samsung" && record.surface_id !== "usb-c") {
            return
        }
        const rect = record.local_rect
        if (!rect || !isNumber(rect.x) || !isNumber(rect.y)
                || !isNumber(rect.width) || !isNumber(rect.height)
                || !isNumber(record.revision) || record.revision < revision) {
            return
        }
        surfaceId = record.surface_id
        x = Math.round(rect.x)
        y = Math.round(rect.y)
        width = Math.max(360, Math.round(rect.width))
        height = Math.max(240, Math.round(rect.height))
        open = record.open === true
        zOrder = isNumber(record.z_order) ? Math.round(record.z_order) : 10
        revision = Math.round(record.revision)
    }

    function reloadState() {
        const text = placementFile.text()
        if (!text) {
            return
        }
        try {
            applyRecord(JSON.parse(text))
        } catch (error) {
            console.warn("Ignored invalid pane placement:", error)
        }
    }

    function record() {
        return {
            "schema": schema,
            "pane_id": paneId,
            "surface_id": surfaceId,
            "local_rect": {
                "x": x,
                "y": y,
                "width": width,
                "height": height
            },
            "open": open,
            "z_order": zOrder,
            "revision": revision
        }
    }

    function writeState() {
        placementFile.setText(JSON.stringify(record(), null, 2) + "\n")
    }

    function previewMove(nextX, nextY) {
        x = Math.round(nextX)
        y = Math.round(nextY)
    }

    function commitMove() {
        revision += 1
        writeState()
    }

    function transfer(nextSurfaceId, nextX, nextY) {
        surfaceId = nextSurfaceId
        x = Math.round(nextX)
        y = Math.round(nextY)
        revision += 1
        writeState()
    }

    property FileView placementFile: FileView {
        id: placementFile

        path: root.statePath
        preload: true
        blockLoading: true
        watchChanges: true
        atomicWrites: true

        onLoaded: root.reloadState()
        onTextChanged: root.reloadState()
        onFileChanged: placementFile.reload()
    }
}
