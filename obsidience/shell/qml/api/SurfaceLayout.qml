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
    readonly property int snapThreshold: 120
    readonly property int minimumPaneGridSize: 1
    readonly property int maximumPaneGridSize: 100
    readonly property int minimumTileCount: 1
    readonly property int maximumTileCount: 16
    // The auto-hidden shelf reserves no pane workspace.
    readonly property int paneTopInset: 0

    property int revision: 0
    property var surfaces: []
    property string graphSurfaceId: "samsung"
    property int paneGridSize: 10
    property var workspaceTiling: ({
        "samsung": {"columns": 8, "rows": 2},
        "usb-c": {"columns": 3, "rows": 2},
        "dp-4": {"columns": 4, "rows": 1}
    })

    function isNumber(value) {
        return typeof value === "number" && isFinite(value)
    }

    function normalizeSurface(value) {
        if (!value || typeof value.id !== "string"
                || typeof value.label !== "string"
                || typeof value.backend !== "string"
                || typeof value.display !== "string"
                || typeof value.output !== "string"
                || !isNumber(value.pixel_width) || value.pixel_width <= 0
                || !isNumber(value.pixel_height) || value.pixel_height <= 0
                || !isNumber(value.logical_width) || value.logical_width <= 0
                || !isNumber(value.logical_height) || value.logical_height <= 0
                || !isNumber(value.device_scale) || value.device_scale <= 0) {
            return null
        }
        const rect = value.map_rect
        if (!rect || !isNumber(rect.x) || !isNumber(rect.y)
                || !isNumber(rect.width) || rect.width <= 0
                || !isNumber(rect.height) || rect.height <= 0) {
            return null
        }
        return {
            "id": value.id,
            "label": value.label,
            "backend": value.backend,
            "display": value.display,
            "output": value.output,
            "x_screen": value.x_screen ?? null,
            "pixel_width": Math.round(value.pixel_width),
            "pixel_height": Math.round(value.pixel_height),
            "logical_width": Math.round(value.logical_width),
            "logical_height": Math.round(value.logical_height),
            "device_scale": value.device_scale,
            "map_rect": {
                "x": Math.round(rect.x),
                "y": Math.round(rect.y),
                "width": Math.round(rect.width),
                "height": Math.round(rect.height)
            }
        }
    }

    function normalizePaneGridSize(value) {
        return Number.isInteger(value)
                && value >= minimumPaneGridSize
                && value <= maximumPaneGridSize ? value : 10
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

    function tileBoundary(surfaceId, axis, index) {
        const surfaceRecord = surface(surfaceId)
        const tiling = tilingFor(surfaceId)
        if (!surfaceRecord || !tiling || (axis !== "x" && axis !== "y")) {
            return 0
        }
        const count = axis === "x" ? tiling.columns : tiling.rows
        const extent = axis === "x" ? surfaceRecord.logical_width
            : surfaceRecord.logical_height - paneTopInset
        const offset = axis === "x" ? 0 : paneTopInset
        const safeIndex = Math.max(0, Math.min(count, Math.round(index)))
        return offset + Math.round(safeIndex * extent / count)
    }

    function tileRect(surfaceId, bounds) {
        const tiling = tilingFor(surfaceId)
        if (!tiling || !bounds
                || !Number.isInteger(bounds.left)
                || !Number.isInteger(bounds.top)
                || !Number.isInteger(bounds.right)
                || !Number.isInteger(bounds.bottom)
                || bounds.left < 0 || bounds.top < 0
                || bounds.right <= bounds.left || bounds.bottom <= bounds.top
                || bounds.right > tiling.columns || bounds.bottom > tiling.rows) {
            return null
        }
        const x = tileBoundary(surfaceId, "x", bounds.left)
        const y = tileBoundary(surfaceId, "y", bounds.top)
        const right = tileBoundary(surfaceId, "x", bounds.right)
        const bottom = tileBoundary(surfaceId, "y", bounds.bottom)
        return {"x": x, "y": y, "width": right - x, "height": bottom - y}
    }

    function minimumTileSpan(surfaceId, axis, minimumSize) {
        const tiling = tilingFor(surfaceId)
        const count = axis === "x" ? tiling.columns : tiling.rows
        for (let span = 1; span <= count; span += 1) {
            let everyPositionFits = true
            for (let start = 0; start + span <= count; start += 1) {
                const first = tileBoundary(surfaceId, axis, start)
                const last = tileBoundary(surfaceId, axis, start + span)
                if (last - first < minimumSize) {
                    everyPositionFits = false
                    break
                }
            }
            if (everyPositionFits) return span
        }
        return count
    }

    function tileHomeForRect(surfaceId, rect, minimumWidth, minimumHeight) {
        const surfaceRecord = surface(surfaceId)
        const tiling = tilingFor(surfaceId)
        if (!surfaceRecord || !tiling || !rect) {
            return null
        }
        const columnSpan = minimumTileSpan(surfaceId, "x", minimumWidth)
        const rowSpan = minimumTileSpan(surfaceId, "y", minimumHeight)
        let left = 0
        let top = 0
        let right = tiling.columns
        let bottom = tiling.rows
        for (let index = 0; index < tiling.columns; index += 1) {
            if (tileBoundary(surfaceId, "x", index) <= rect.x) left = index
        }
        for (let index = 1; index <= tiling.columns; index += 1) {
            if (tileBoundary(surfaceId, "x", index) >= rect.x + rect.width) {
                right = index
                break
            }
        }
        for (let index = 0; index < tiling.rows; index += 1) {
            if (tileBoundary(surfaceId, "y", index) <= rect.y) top = index
        }
        for (let index = 1; index <= tiling.rows; index += 1) {
            if (tileBoundary(surfaceId, "y", index) >= rect.y + rect.height) {
                bottom = index
                break
            }
        }
        while (right - left < columnSpan) {
            if (right < tiling.columns) right += 1
            else if (left > 0) left -= 1
            else break
        }
        while (bottom - top < rowSpan) {
            if (bottom < tiling.rows) bottom += 1
            else if (top > 0) top -= 1
            else break
        }
        return {
            "surface_id": surfaceId,
            "columns": tiling.columns,
            "rows": tiling.rows,
            "left": left,
            "top": top,
            "right": right,
            "bottom": bottom
        }
    }

    function validTileHome(surfaceId, home) {
        const tiling = tilingFor(surfaceId)
        return !!tiling && !!home && home.surface_id === surfaceId
            && home.columns === tiling.columns && home.rows === tiling.rows
            && Number.isInteger(home.left) && Number.isInteger(home.top)
            && Number.isInteger(home.right) && Number.isInteger(home.bottom)
            && home.left >= 0 && home.top >= 0
            && home.right > home.left && home.bottom > home.top
            && home.right <= tiling.columns && home.bottom <= tiling.rows
    }

    function nearestTileIndex(surfaceId, axis, value) {
        const tiling = tilingFor(surfaceId)
        const count = axis === "x" ? tiling.columns : tiling.rows
        let bestIndex = 0
        let bestDistance = Number.MAX_VALUE
        for (let index = 0; index <= count; index += 1) {
            const distance = Math.abs(tileBoundary(surfaceId, axis, index) - value)
            if (distance < bestDistance) {
                bestDistance = distance
                bestIndex = index
            }
        }
        return bestIndex
    }

    function tileBoundsForRect(surfaceId, rect) {
        const bounds = {
            "left": nearestTileIndex(surfaceId, "x", rect.x),
            "top": nearestTileIndex(surfaceId, "y", rect.y),
            "right": nearestTileIndex(surfaceId, "x", rect.x + rect.width),
            "bottom": nearestTileIndex(surfaceId, "y", rect.y + rect.height)
        }
        const tiled = tileRect(surfaceId, bounds)
        if (!tiled || Math.abs(tiled.x - rect.x) > 1
                || Math.abs(tiled.y - rect.y) > 1
                || Math.abs(tiled.width - rect.width) > 1
                || Math.abs(tiled.height - rect.height) > 1) {
            return null
        }
        return bounds
    }

    function tiledPaneRect(surfaceId, rect, minimumWidth, minimumHeight,
                            direction, tileHome, translate) {
        const tiling = tilingFor(surfaceId)
        if (!tiling || ["left", "right", "top", "bottom"].indexOf(direction) < 0) {
            return null
        }
        let home = validTileHome(surfaceId, tileHome) ? Object.assign({}, tileHome)
            : tileHomeForRect(surfaceId, rect, minimumWidth, minimumHeight)
        let bounds = validTileHome(surfaceId, tileHome)
            ? tileBoundsForRect(surfaceId, rect) : null
        if (!bounds || bounds.left > home.left || bounds.top > home.top
                || bounds.right < home.right || bounds.bottom < home.bottom) {
            bounds = {
                "left": home.left,
                "top": home.top,
                "right": home.right,
                "bottom": home.bottom
            }
        }

        if (translate === true) {
            const dx = direction === "left" ? -1 : direction === "right" ? 1 : 0
            const dy = direction === "top" ? -1 : direction === "bottom" ? 1 : 0
            if (bounds.left + dx >= 0 && bounds.right + dx <= tiling.columns
                    && bounds.top + dy >= 0 && bounds.bottom + dy <= tiling.rows) {
                bounds.left += dx
                bounds.right += dx
                bounds.top += dy
                bounds.bottom += dy
                home.left += dx
                home.right += dx
                home.top += dy
                home.bottom += dy
            }
        } else if (direction === "right") {
            if (bounds.left < home.left) bounds.left += 1
            else if (bounds.right < tiling.columns) bounds.right += 1
        } else if (direction === "left") {
            if (bounds.right > home.right) bounds.right -= 1
            else if (bounds.left > 0) bounds.left -= 1
        } else if (direction === "bottom") {
            if (bounds.top < home.top) bounds.top += 1
            else if (bounds.bottom < tiling.rows) bounds.bottom += 1
        } else if (direction === "top") {
            if (bounds.bottom > home.bottom) bounds.bottom -= 1
            else if (bounds.top > 0) bounds.top -= 1
        }

        const tiled = tileRect(surfaceId, bounds)
        if (!tiled) {
            return null
        }
        tiled.tile_home = home
        tiled.changed = tiled.x !== Math.round(rect.x)
            || tiled.y !== Math.round(rect.y)
            || tiled.width !== Math.round(rect.width)
            || tiled.height !== Math.round(rect.height)
            || !validTileHome(surfaceId, tileHome)
        return tiled
    }

    function clampPaneSize(value, minimum, maximum) {
        if (!isNumber(value) || !isNumber(minimum) || !isNumber(maximum)) {
            return 0
        }
        const safeMinimum = Math.max(0, Math.round(minimum))
        const safeMaximum = Math.max(safeMinimum, Math.round(maximum))
        return Math.max(safeMinimum, Math.min(
            snapPaneValue(value), safeMaximum
        ))
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

    function replaceRect(surfaceId, rect) {
        const next = []
        for (const candidate of surfaces) {
            if (candidate.id === surfaceId) {
                next.push(Object.assign({}, candidate, {
                    "map_rect": {
                        "x": Math.round(rect.x),
                        "y": Math.round(rect.y),
                        "width": candidate.map_rect.width,
                        "height": candidate.map_rect.height
                    }
                }))
            } else {
                next.push(candidate)
            }
        }
        surfaces = next
    }

    function rangesOverlap(startA, lengthA, startB, lengthB) {
        return Math.min(startA + lengthA, startB + lengthB)
            > Math.max(startA, startB)
    }

    function snappedRectAt(surfaceId, x, y) {
        const candidate = surface(surfaceId)
        if (!candidate || !isNumber(x) || !isNumber(y)) {
            return null
        }
        const rect = {
            "x": Math.round(x),
            "y": Math.round(y),
            "width": candidate.map_rect.width,
            "height": candidate.map_rect.height
        }
        let best = {
            "x": rect.x,
            "y": rect.y,
            "distance": snapThreshold + 1
        }
        function consider(distance, x, y, overlaps) {
            if (overlaps && distance <= root.snapThreshold
                    && distance < best.distance) {
                best = {"x": x, "y": y, "distance": distance}
            }
        }
        for (const other of surfaces) {
            if (other.id === surfaceId) {
                continue
            }
            const target = other.map_rect
            const verticalOverlap = rangesOverlap(
                rect.y, rect.height, target.y, target.height
            )
            const horizontalOverlap = rangesOverlap(
                rect.x, rect.width, target.x, target.width
            )
            consider(
                Math.abs(rect.x - (target.x + target.width)),
                target.x + target.width,
                rect.y,
                verticalOverlap
            )
            consider(
                Math.abs((rect.x + rect.width) - target.x),
                target.x - rect.width,
                rect.y,
                verticalOverlap
            )
            consider(
                Math.abs(rect.y - (target.y + target.height)),
                rect.x,
                target.y + target.height,
                horizontalOverlap
            )
            consider(
                Math.abs((rect.y + rect.height) - target.y),
                rect.x,
                target.y - rect.height,
                horizontalOverlap
            )
        }
        return {
            "x": best.x,
            "y": best.y,
            "width": rect.width,
            "height": rect.height
        }
    }

    function commitSurfaceAt(surfaceId, x, y) {
        const snapped = snappedRectAt(surfaceId, x, y)
        if (!snapped) {
            return
        }
        replaceRect(surfaceId, snapped)
        revision += 1
        writeState()
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

    function touching(surfaceId, edge) {
        const source = surface(surfaceId)
        if (!source) {
            return false
        }
        const rect = source.map_rect
        const horizontal = edge === "top" || edge === "bottom"
        const boundary = edge === "left" ? rect.x
            : edge === "right" ? rect.x + rect.width
            : edge === "top" ? rect.y
            : rect.y + rect.height
        for (const destination of surfaces) {
            if (destination.id === surfaceId) {
                continue
            }
            const target = destination.map_rect
            const opposite = edge === "left" ? target.x + target.width
                : edge === "right" ? target.x
                : edge === "top" ? target.y + target.height
                : target.y
            const overlaps = horizontal
                ? rangesOverlap(rect.x, rect.width, target.x, target.width)
                : rangesOverlap(rect.y, rect.height, target.y, target.height)
            if (Math.abs(boundary - opposite) < 0.5 && overlaps) {
                return true
            }
        }
        return false
    }

    function route(sourceId, edge, localX, localY, inset) {
        const source = surface(sourceId)
        if (!source || ["left", "right", "top", "bottom"].indexOf(edge) < 0) {
            return null
        }
        const safeInset = isNumber(inset) ? Math.max(0, Math.round(inset)) : 12
        const rect = source.map_rect
        const horizontal = edge === "top" || edge === "bottom"
        const localAxis = horizontal
            ? Math.max(0, Math.min(localX, source.logical_width - 1))
            : Math.max(0, Math.min(localY, source.logical_height - 1))
        const sourceLength = horizontal ? source.logical_width : source.logical_height
        const globalAxis = (horizontal ? rect.x : rect.y)
            + (localAxis / Math.max(1, sourceLength))
                * (horizontal ? rect.width : rect.height)
        const boundary = edge === "left" ? rect.x
            : edge === "right" ? rect.x + rect.width
            : edge === "top" ? rect.y
            : rect.y + rect.height
        const destinationEdge = edge === "left" ? "right"
            : edge === "right" ? "left"
            : edge === "top" ? "bottom"
            : "top"

        for (const destination of surfaces) {
            if (destination.id === sourceId) {
                continue
            }
            const target = destination.map_rect
            const targetBoundary = destinationEdge === "left" ? target.x
                : destinationEdge === "right" ? target.x + target.width
                : destinationEdge === "top" ? target.y
                : target.y + target.height
            if (Math.abs(boundary - targetBoundary) >= 0.5) {
                continue
            }
            const sourceStart = horizontal ? rect.x : rect.y
            const sourceExtent = horizontal ? rect.width : rect.height
            const targetStart = horizontal ? target.x : target.y
            const targetExtent = horizontal ? target.width : target.height
            const overlapStart = Math.max(sourceStart, targetStart)
            const overlapEnd = Math.min(
                sourceStart + sourceExtent, targetStart + targetExtent
            )
            if (overlapEnd <= overlapStart
                    || globalAxis < overlapStart || globalAxis >= overlapEnd) {
                continue
            }
            const ratio = Math.max(0, Math.min(
                1, (globalAxis - targetStart) / targetExtent
            ))
            let x = horizontal
                ? Math.round(ratio * (destination.logical_width - 1)) : 0
            let y = horizontal
                ? 0 : Math.round(ratio * (destination.logical_height - 1))
            if (destinationEdge === "left") {
                x = Math.min(safeInset, destination.logical_width - 1)
            } else if (destinationEdge === "right") {
                x = Math.max(0, destination.logical_width - 1 - safeInset)
            } else if (destinationEdge === "top") {
                y = Math.min(safeInset, destination.logical_height - 1)
            } else {
                y = Math.max(0, destination.logical_height - 1 - safeInset)
            }
            return {
                "destination_id": destination.id,
                "destination_edge": destinationEdge,
                "x": x,
                "y": y,
                "device_scale": destination.device_scale
            }
        }
        return null
    }

    // Pane shortcuts use the nearest mapped neighbour in the requested
    // direction. Pointer traversal remains exact and continues to use route().
    function moveRoute(sourceId, edge, localX, localY, inset) {
        const exact = route(sourceId, edge, localX, localY, inset)
        if (exact) {
            return exact
        }
        const source = surface(sourceId)
        if (!source || ["left", "right", "top", "bottom"].indexOf(edge) < 0) {
            return null
        }
        const safeInset = isNumber(inset) ? Math.max(0, Math.round(inset)) : 12
        const rect = source.map_rect
        const horizontal = edge === "top" || edge === "bottom"
        const localAxis = horizontal
            ? Math.max(0, Math.min(localX, source.logical_width - 1))
            : Math.max(0, Math.min(localY, source.logical_height - 1))
        const sourceLength = horizontal ? source.logical_width : source.logical_height
        const globalAxis = (horizontal ? rect.x : rect.y)
            + (localAxis / Math.max(1, sourceLength))
                * (horizontal ? rect.width : rect.height)
        const boundary = edge === "left" ? rect.x
            : edge === "right" ? rect.x + rect.width
            : edge === "top" ? rect.y
            : rect.y + rect.height
        const destinationEdge = edge === "left" ? "right"
            : edge === "right" ? "left"
            : edge === "top" ? "bottom"
            : "top"
        let best = null

        for (const destination of surfaces) {
            if (destination.id === sourceId) {
                continue
            }
            const target = destination.map_rect
            const targetBoundary = destinationEdge === "left" ? target.x
                : destinationEdge === "right" ? target.x + target.width
                : destinationEdge === "top" ? target.y
                : target.y + target.height
            if (Math.abs(boundary - targetBoundary) >= 0.5) {
                continue
            }
            const sourceStart = horizontal ? rect.x : rect.y
            const sourceExtent = horizontal ? rect.width : rect.height
            const targetStart = horizontal ? target.x : target.y
            const targetExtent = horizontal ? target.width : target.height
            const overlapStart = Math.max(sourceStart, targetStart)
            const overlapEnd = Math.min(
                sourceStart + sourceExtent, targetStart + targetExtent
            )
            if (overlapEnd <= overlapStart) {
                continue
            }
            const mappedAxis = Math.max(
                overlapStart,
                Math.min(globalAxis, overlapEnd - 0.001)
            )
            const distance = Math.abs(globalAxis - mappedAxis)
            if (best && distance >= best.distance) {
                continue
            }
            const ratio = Math.max(0, Math.min(
                1, (mappedAxis - targetStart) / targetExtent
            ))
            let x = horizontal
                ? Math.round(ratio * (destination.logical_width - 1)) : 0
            let y = horizontal
                ? 0 : Math.round(ratio * (destination.logical_height - 1))
            if (destinationEdge === "left") {
                x = Math.min(safeInset, destination.logical_width - 1)
            } else if (destinationEdge === "right") {
                x = Math.max(0, destination.logical_width - 1 - safeInset)
            } else if (destinationEdge === "top") {
                y = Math.min(safeInset, destination.logical_height - 1)
            } else {
                y = Math.max(0, destination.logical_height - 1 - safeInset)
            }
            best = {
                "distance": distance,
                "route": {
                    "destination_id": destination.id,
                    "destination_edge": destinationEdge,
                    "x": x,
                    "y": y,
                    "device_scale": destination.device_scale
                }
            }
        }
        return best ? best.route : null
    }

    function record() {
        return {
            "schema": schema,
            "revision": revision,
            "graph_surface_id": graphSurfaceId,
            "pane_grid_size": paneGridSize,
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
