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
    // The auto-hidden shelf reserves no pane workspace.
    readonly property int paneTopInset: 0

    property int revision: 0
    property var surfaces: []
    property string graphSurfaceId: "samsung"
    property int paneGridSize: 10

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
