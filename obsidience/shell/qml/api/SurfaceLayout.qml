pragma ComponentBehavior: Bound

import QtCore
import QtQml
import Quickshell.Io

QtObject {
    id: root

    readonly property string schema: "obsidience.surface-layout.v1"
    readonly property string statePath: StandardPaths.writableLocation(
        StandardPaths.ConfigLocation
    ) + "/obsidience-shell/surface-layout.json"
    readonly property int minimumPaneGridSize: 1
    readonly property int maximumPaneGridSize: 100
    readonly property int minimumTileCount: 1
    readonly property int maximumTileCount: 16
    readonly property int workspaceTileGap: 5
    readonly property int minimumTileResizeLimitPercent: 0
    readonly property int maximumTileResizeLimitPercent: 25
    readonly property int minimumOledShiftDistancePx: 1
    readonly property int maximumOledShiftDistancePx: 50
    readonly property int minimumOledTravelDurationSeconds: 60
    readonly property int maximumOledTravelDurationSeconds: 86400
    readonly property int minimumOledGlowRotationHours: 1
    readonly property int maximumOledGlowRotationHours: 24
    // The auto-hidden shelf reserves no pane workspace.
    readonly property int paneTopInset: 0

    property int revision: 0
    property var surfaces: []
    property string graphSurfaceId: "samsung"
    property int paneGridSize: 10
    property int tileResizeLimitPercent: 25
    property bool oledModeEnabled: false
    property int oledShiftDistancePx: 32
    property int oledTravelDurationSeconds: 3600
    property int oledGlowRotationHours: 3
    property var workspaceTiling: ({
        "samsung": {"columns": 8, "rows": 2},
        "usb-c": {"columns": 3, "rows": 2},
        "dp-4": {"columns": 4, "rows": 1}
    })
    readonly property WorkspaceTiler workspaceTiler: WorkspaceTiler {
        gap: root.workspaceTileGap
    }

    function isNumber(value) {
        return typeof value === "number" && isFinite(value)
    }

    function normalizeSurface(value) {
        if (!value || typeof value.id !== "string"
                || typeof value.label !== "string"
                || typeof value.output !== "string"
                || !isNumber(value.logical_width) || value.logical_width <= 0
                || !isNumber(value.logical_height) || value.logical_height <= 0) {
            return null
        }
        const result = {
            "id": value.id,
            "label": value.label,
            "output": value.output,
            "logical_width": Math.round(value.logical_width),
            "logical_height": Math.round(value.logical_height)
        }
        // Stable monitor identity: Hyprland's EDID description, matched as a
        // prefix like `desc:`. `output` is the connector it last resolved to.
        if (typeof value.description === "string" && value.description.length > 0
                && value.description.length <= 256) {
            result.description = value.description
        }
        return result
    }

    function normalizePaneGridSize(value) {
        return Number.isInteger(value)
                && value >= minimumPaneGridSize
                && value <= maximumPaneGridSize ? value : 10
    }

    function normalizeTileResizeLimitPercent(value) {
        return Number.isInteger(value)
                && value >= minimumTileResizeLimitPercent
                && value <= maximumTileResizeLimitPercent ? value : 25
    }

    function normalizeOledShiftDistancePx(value) {
        return Number.isInteger(value)
                && value >= minimumOledShiftDistancePx
                && value <= maximumOledShiftDistancePx ? value : 32
    }

    function normalizeOledTravelDurationSeconds(value) {
        return Number.isInteger(value)
                && value >= minimumOledTravelDurationSeconds
                && value <= maximumOledTravelDurationSeconds ? value : 3600
    }

    function normalizeOledGlowRotationHours(value) {
        return Number.isInteger(value)
                && value >= minimumOledGlowRotationHours
                && value <= maximumOledGlowRotationHours ? value : 3
    }

    function defaultTiling() {
        return {
            "samsung": {"columns": 8, "rows": 2},
            "usb-c": {"columns": 3, "rows": 2},
            "dp-4": {"columns": 4, "rows": 1}
        }
    }

    function normalizeWorkspaceTiling(value) {
        const defaults = defaultTiling()
        const result = {}
        for (const surfaceId of ["samsung", "usb-c", "dp-4"]) {
            const candidate = value && value[surfaceId]
            const columns = candidate && Number.isInteger(candidate.columns)
                    && candidate.columns >= minimumTileCount
                    && candidate.columns <= maximumTileCount
                ? candidate.columns : defaults[surfaceId].columns
            const rows = candidate && Number.isInteger(candidate.rows)
                    && candidate.rows >= minimumTileCount
                    && candidate.rows <= maximumTileCount
                ? candidate.rows : defaults[surfaceId].rows
            result[surfaceId] = {"columns": columns, "rows": rows}
        }
        return result
    }

    function applyRecord(record) {
        if (!record || record.schema !== schema
                || !isNumber(record.revision)
                || record.revision < revision
                || !Array.isArray(record.surfaces)
                || record.surfaces.length !== 3) {
            return
        }
        const next = []
        const ids = {}
        for (const value of record.surfaces) {
            const surface = normalizeSurface(value)
            if (!surface || ids[surface.id]) {
                return
            }
            ids[surface.id] = true
            next.push(surface)
        }
        if (!ids.samsung || !ids["usb-c"] || !ids["dp-4"]) {
            return
        }
        revision = Math.round(record.revision)
        surfaces = next
        graphSurfaceId = ids[record.graph_surface_id]
            ? record.graph_surface_id : "samsung"
        paneGridSize = normalizePaneGridSize(record.pane_grid_size)
        tileResizeLimitPercent = normalizeTileResizeLimitPercent(
            record.tile_resize_limit_percent
        )
        oledModeEnabled = typeof record.oled_mode_enabled === "boolean"
            ? record.oled_mode_enabled : false
        oledShiftDistancePx = normalizeOledShiftDistancePx(
            record.oled_shift_distance_px
        )
        oledTravelDurationSeconds = normalizeOledTravelDurationSeconds(
            record.oled_travel_duration_seconds
        )
        oledGlowRotationHours = normalizeOledGlowRotationHours(
            record.oled_glow_rotation_hours
        )
        workspaceTiling = normalizeWorkspaceTiling(record.workspace_tiling)
    }

    function reloadState() {
        const text = layoutFile.text()
        if (!text) {
            return
        }
        try {
            applyRecord(JSON.parse(text))
        } catch (error) {
            console.warn("Ignored invalid Surface layout:", error)
        }
    }

    function surface(surfaceId) {
        for (const candidate of surfaces) {
            if (candidate.id === surfaceId) {
                return candidate
            }
        }
        return null
    }

    function surfaceIdForOutput(output) {
        if (typeof output !== "string" || output.length === 0) {
            return ""
        }
        for (const candidate of surfaces) {
            if (candidate.output === output) {
                return candidate.id
            }
        }
        return ""
    }

    // The window adapter resolves each Surface's monitor description to its
    // current connector ("" while absent). Record those connectors so every
    // reader matching screens by `output` follows a renumbered monitor. An
    // absent Surface keeps its last connector unless a present one now owns it.
    function commitSurfaceOutputs(outputs) {
        const owners = {}
        for (const candidate of surfaces) {
            const output = outputs ? outputs[candidate.id] : undefined
            if (typeof output !== "string"
                    || (output && !/^[A-Za-z0-9._-]{1,64}$/.test(output))) {
                return false
            }
            if (output) {
                if (owners[output]) {
                    return false
                }
                owners[output] = candidate.id
            }
        }
        let changed = false
        const next = []
        for (const candidate of surfaces) {
            const resolved = outputs[candidate.id]
            const output = resolved
                || (owners[candidate.output] ? "" : candidate.output)
            changed = changed || output !== candidate.output
            next.push(output === candidate.output ? candidate
                : Object.assign({}, candidate, {"output": output}))
        }
        if (changed) {
            surfaces = next
            revision += 1
            writeState()
        }
        return true
    }

    function snapPaneValue(value) {
        if (!isNumber(value)) {
            return 0
        }
        return Math.round(value / paneGridSize) * paneGridSize
    }

    function tilingFor(surfaceId) {
        const tiling = workspaceTiling[surfaceId]
        return tiling || defaultTiling()[surfaceId] || null
    }

    function tileRect(surfaceId, bounds) {
        const surfaceRecord = surface(surfaceId)
        const tiling = tilingFor(surfaceId)
        if (!surfaceRecord || !tiling
                || !workspaceTiler.validBounds(
                    bounds, tiling.columns, tiling.rows, surfaceId
                )) {
            return null
        }
        return workspaceTiler.rectForBounds(
            surfaceRecord.logical_width,
            surfaceRecord.logical_height,
            paneTopInset,
            bounds
        )
    }

    function validTileBounds(surfaceId, bounds) {
        const tiling = tilingFor(surfaceId)
        return !!tiling && workspaceTiler.validBounds(
            bounds, tiling.columns, tiling.rows, surfaceId
        )
    }

    function nearestTiledPaneRect(surfaceId, rect) {
        const surfaceRecord = surface(surfaceId)
        const tiling = tilingFor(surfaceId)
        if (!surfaceRecord || !tiling) {
            return null
        }
        const bounds = workspaceTiler.boundsForRect(
            surfaceRecord.logical_width,
            surfaceRecord.logical_height,
            paneTopInset,
            surfaceId,
            tiling.columns,
            tiling.rows,
            rect
        )
        const tiled = tileRect(surfaceId, bounds)
        if (!tiled) {
            return null
        }
        tiled.tile_bounds = bounds
        return tiled
    }

    function clampPaneX(surfaceRecord, paneWidth, value) {
        if (!surfaceRecord || !isNumber(paneWidth) || !isNumber(value)) {
            return 0
        }
        return Math.max(0, Math.min(
            snapPaneValue(value),
            Math.max(0, surfaceRecord.logical_width - Math.round(paneWidth))
        ))
    }

    function clampPaneY(surfaceRecord, paneHeight, value) {
        if (!surfaceRecord || !isNumber(paneHeight) || !isNumber(value)) {
            return paneTopInset
        }
        return Math.max(paneTopInset, Math.min(
            snapPaneValue(value),
            Math.max(
                paneTopInset,
                surfaceRecord.logical_height - Math.round(paneHeight)
            )
        ))
    }

    function commitGraphSurface(surfaceId) {
        if (!surface(surfaceId)) {
            return false
        }
        if (graphSurfaceId === surfaceId) {
            return true
        }
        revision += 1
        graphSurfaceId = surfaceId
        writeState()
        return true
    }

    function commitPaneGridSize(value) {
        if (!Number.isInteger(value)
                || value < minimumPaneGridSize
                || value > maximumPaneGridSize) {
            return false
        }
        if (paneGridSize === value) {
            return true
        }
        revision += 1
        paneGridSize = value
        writeState()
        return true
    }

    function commitTileResizeLimitPercent(value) {
        if (!Number.isInteger(value)
                || value < minimumTileResizeLimitPercent
                || value > maximumTileResizeLimitPercent) {
            return false
        }
        if (tileResizeLimitPercent === value) {
            return true
        }
        tileResizeLimitPercent = value
        revision += 1
        writeState()
        return true
    }

    function commitOledSettings(
            enabled, shiftDistancePx, travelDurationSeconds, glowRotationHours) {
        if (typeof enabled !== "boolean"
                || !Number.isInteger(shiftDistancePx)
                || shiftDistancePx < minimumOledShiftDistancePx
                || shiftDistancePx > maximumOledShiftDistancePx
                || !Number.isInteger(travelDurationSeconds)
                || travelDurationSeconds < minimumOledTravelDurationSeconds
                || travelDurationSeconds > maximumOledTravelDurationSeconds
                || !Number.isInteger(glowRotationHours)
                || glowRotationHours < minimumOledGlowRotationHours
                || glowRotationHours > maximumOledGlowRotationHours) {
            return false
        }
        if (oledModeEnabled === enabled
                && oledShiftDistancePx === shiftDistancePx
                && oledTravelDurationSeconds === travelDurationSeconds
                && oledGlowRotationHours === glowRotationHours) {
            return true
        }
        oledModeEnabled = enabled
        oledShiftDistancePx = shiftDistancePx
        oledTravelDurationSeconds = travelDurationSeconds
        oledGlowRotationHours = glowRotationHours
        revision += 1
        writeState()
        return true
    }

    function commitWorkspaceTiling(surfaceId, columns, rows) {
        if (!surface(surfaceId) || !Number.isInteger(columns)
                || !Number.isInteger(rows)
                || columns < minimumTileCount || columns > maximumTileCount
                || rows < minimumTileCount || rows > maximumTileCount) {
            return false
        }
        const current = tilingFor(surfaceId)
        if (current.columns === columns && current.rows === rows) {
            return true
        }
        const next = Object.assign({}, workspaceTiling)
        next[surfaceId] = {"columns": columns, "rows": rows}
        workspaceTiling = next
        revision += 1
        writeState()
        return true
    }

    function workspaceTilingState() {
        const result = []
        for (const surfaceId of ["samsung", "usb-c", "dp-4"]) {
            const surfaceRecord = surface(surfaceId)
            const tiling = tilingFor(surfaceId)
            if (surfaceRecord && tiling) {
                result.push({
                    "surface_id": surfaceId,
                    "label": surfaceRecord.label,
                    "columns": tiling.columns,
                    "rows": tiling.rows,
                    "zones": tiling.columns * tiling.rows
                })
            }
        }
        return result
    }

    function record() {
        return {
            "schema": schema,
            "revision": revision,
            "graph_surface_id": graphSurfaceId,
            "pane_grid_size": paneGridSize,
            "tile_resize_limit_percent": tileResizeLimitPercent,
            "oled_mode_enabled": oledModeEnabled,
            "oled_shift_distance_px": oledShiftDistancePx,
            "oled_travel_duration_seconds": oledTravelDurationSeconds,
            "oled_glow_rotation_hours": oledGlowRotationHours,
            "workspace_tiling": workspaceTiling,
            "surfaces": surfaces
        }
    }

    function writeState() {
        layoutFile.setText(JSON.stringify(record(), null, 2) + "\n")
    }

    property FileView layoutFile: FileView {
        id: layoutFile

        path: root.statePath
        preload: true
        blockLoading: true
        watchChanges: true
        atomicWrites: true

        onLoaded: root.reloadState()
        onTextChanged: root.reloadState()
        onFileChanged: layoutFile.reload()
    }
}
