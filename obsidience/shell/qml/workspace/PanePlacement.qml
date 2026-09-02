pragma ComponentBehavior: Bound

import QtCore
import QtQml
import Quickshell.Io

QtObject {
    id: root

    readonly property string schema: "obsidience.surface-placement.v1"
    property string paneId: "displays"
    property string stateFileName: paneId === "displays"
        ? "pane-placement.json" : paneId + "-placement.json"
    readonly property string statePath: StandardPaths.writableLocation(
        StandardPaths.RuntimeLocation
    ) + "/obsidience-shell/" + stateFileName

    property string defaultSurfaceId: "samsung"
    property int defaultX: 2180
    property int defaultY: 260
    property int defaultWidth: 720
    property int defaultHeight: 420
    property bool defaultOpen: true
    property int defaultZOrder: 10

    property string surfaceId: defaultSurfaceId
    property int x: defaultX
    property int y: defaultY
    property int width: defaultWidth
    property int height: defaultHeight
    property bool open: defaultOpen
    property int zOrder: defaultZOrder
    property var tileBounds: null
    property int revision: 0
    property bool authoritative: false

    function isNumber(value) {
        return typeof value === "number" && isFinite(value)
    }

    function normalizeTileBounds(value) {
        if (!value) {
            return null
        }
        if ((value.surface_id !== "samsung" && value.surface_id !== "usb-c"
                && value.surface_id !== "dp-4")
                || !Number.isInteger(value.columns)
                || !Number.isInteger(value.rows)
                || !Number.isInteger(value.left)
                || !Number.isInteger(value.top)
                || !Number.isInteger(value.right)
                || !Number.isInteger(value.bottom)
                || value.columns < 1 || value.rows < 1
                || value.left < 0 || value.top < 0
                || value.right <= value.left || value.bottom <= value.top
                || value.right > value.columns || value.bottom > value.rows) {
            return null
        }
        return {
            "surface_id": value.surface_id,
            "columns": value.columns,
            "rows": value.rows,
            "left": value.left,
            "top": value.top,
            "right": value.right,
            "bottom": value.bottom
        }
    }

    function applyRecord(record) {
        if (!record || record.schema !== schema || record.pane_id !== paneId) {
            return
        }
        if (record.surface_id !== "samsung" && record.surface_id !== "usb-c"
                && record.surface_id !== "dp-4") {
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
        // tile_home was an immutable minimum footprint and is intentionally
        // not migrated. The next Meta+Arrow establishes current tile bounds.
        tileBounds = normalizeTileBounds(record.tile_bounds)
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
            "tile_bounds": tileBounds,
            "revision": revision
        }
    }

    function writeState() {
        placementFile.setText(JSON.stringify(record(), null, 2) + "\n")
    }

    function commitGeometry(expectedRevision, nextSurfaceId, nextX, nextY,
                            nextWidth, nextHeight, nextZOrder, nextTileBounds) {
        if (!authoritative || revision !== expectedRevision
                || (nextSurfaceId !== "samsung" && nextSurfaceId !== "usb-c"
                    && nextSurfaceId !== "dp-4")
                || !isNumber(nextX) || !isNumber(nextY)
                || !isNumber(nextWidth) || !isNumber(nextHeight)
                || nextWidth <= 0 || nextHeight <= 0) {
            return false
        }
        surfaceId = nextSurfaceId
        x = Math.round(nextX)
        y = Math.round(nextY)
        width = Math.round(nextWidth)
        height = Math.round(nextHeight)
        open = true
        zOrder = isNumber(nextZOrder) ? Math.round(nextZOrder) : zOrder
        tileBounds = normalizeTileBounds(nextTileBounds)
        revision += 1
        writeState()
        return true
    }

    function previewResize(nextWidth, nextHeight) {
        width = Math.max(360, Math.round(nextWidth))
        height = Math.max(240, Math.round(nextHeight))
    }

    function commitResize() {
        tileBounds = null
        revision += 1
        writeState()
    }

    function present() {
        open = true
        zOrder += 1
        revision += 1
        writeState()
    }

    function presentOn(nextSurfaceId, nextX, nextY, nextZOrder) {
        if (surfaceId !== nextSurfaceId) {
            tileBounds = null
        }
        surfaceId = nextSurfaceId
        x = Math.round(nextX)
        y = Math.round(nextY)
        open = true
        zOrder = isNumber(nextZOrder) ? Math.round(nextZOrder) : zOrder + 1
        revision += 1
        writeState()
    }

    function dismiss() {
        if (!open) {
            return
        }
        open = false
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
