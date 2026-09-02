pragma ComponentBehavior: Bound

import QtQml

// Gap-aware zone geometry follows the small pure-geometry pattern in
// Omarchy Windows' MIT-licensed Aero Snap helper. Obsidience generalizes that
// pattern to an arbitrary integer grid and owns its directional state machine.
QtObject {
    id: root

    property int gap: 5

    function validBounds(bounds, columns, rows, surfaceId) {
        return !!bounds
            && (!surfaceId || bounds.surface_id === surfaceId)
            && bounds.columns === columns && bounds.rows === rows
            && Number.isInteger(bounds.left)
            && Number.isInteger(bounds.top)
            && Number.isInteger(bounds.right)
            && Number.isInteger(bounds.bottom)
            && bounds.left >= 0 && bounds.top >= 0
            && bounds.right > bounds.left && bounds.bottom > bounds.top
            && bounds.right <= columns && bounds.bottom <= rows
    }

    function initialBounds(surfaceId, columns, rows, direction) {
        if (columns < 1 || rows < 1) {
            return null
        }
        if (direction === "left") {
            return makeBounds(surfaceId, columns, rows, 0, 0, 1, rows)
        }
        if (direction === "right") {
            return makeBounds(
                surfaceId, columns, rows, columns - 1, 0, columns, rows
            )
        }
        if (direction === "top") {
            return makeBounds(surfaceId, columns, rows, 0, 0, columns, 1)
        }
        if (direction === "bottom") {
            return makeBounds(
                surfaceId, columns, rows, 0, rows - 1, columns, rows
            )
        }
        return null
    }

    function entryBounds(surfaceId, columns, rows, edge, axisRatio) {
        if (columns < 1 || rows < 1 || typeof axisRatio !== "number"
                || !isFinite(axisRatio)) {
            return null
        }
        const ratio = Math.max(0, Math.min(1, axisRatio))
        if (edge === "top" || edge === "bottom") {
            const column = Math.min(columns - 1, Math.floor(ratio * columns))
            const row = edge === "top" ? 0 : rows - 1
            return makeBounds(
                surfaceId, columns, rows, column, row, column + 1, row + 1
            )
        }
        if (edge === "left" || edge === "right") {
            const column = edge === "left" ? 0 : columns - 1
            const row = Math.min(rows - 1, Math.floor(ratio * rows))
            return makeBounds(
                surfaceId, columns, rows, column, row, column + 1, row + 1
            )
        }
        return null
    }

    function makeBounds(surfaceId, columns, rows, left, top, right, bottom) {
        return {
            "surface_id": surfaceId,
            "columns": columns,
            "rows": rows,
            "left": left,
            "top": top,
            "right": right,
            "bottom": bottom
        }
    }

    function copyBounds(bounds) {
        return makeBounds(
            bounds.surface_id,
            bounds.columns,
            bounds.rows,
            bounds.left,
            bounds.top,
            bounds.right,
            bounds.bottom
        )
    }

    function resizeBounds(bounds, direction) {
        if (!bounds) {
            return null
        }
        const next = copyBounds(bounds)
        if (direction === "left") {
            if (next.left > 0) next.left -= 1
            else if (next.right - next.left > 1) next.right -= 1
        } else if (direction === "right") {
            if (next.right < next.columns) next.right += 1
            else if (next.right - next.left > 1) next.left += 1
        } else if (direction === "top") {
            if (next.top > 0) next.top -= 1
            else if (next.bottom - next.top > 1) next.bottom -= 1
        } else if (direction === "bottom") {
            if (next.bottom < next.rows) next.bottom += 1
            else if (next.bottom - next.top > 1) next.top += 1
        } else {
            return null
        }
        return next
    }

    function translateBounds(bounds, direction) {
        if (!bounds) {
            return null
        }
        const next = copyBounds(bounds)
        const dx = direction === "left" ? -1 : direction === "right" ? 1 : 0
        const dy = direction === "top" ? -1 : direction === "bottom" ? 1 : 0
        if ((dx === 0 && dy === 0)
                || next.left + dx < 0 || next.right + dx > next.columns
                || next.top + dy < 0 || next.bottom + dy > next.rows) {
            return next
        }
        next.left += dx
        next.right += dx
        next.top += dy
        next.bottom += dy
        return next
    }

    function cellStart(extent, count, index, offset) {
        const usable = extent - gap * (count + 1)
        return offset + gap + Math.round(index * usable / count) + index * gap
    }

    function cellEnd(extent, count, index, offset) {
        const usable = extent - gap * (count + 1)
        return offset + gap + Math.round(
            (index + 1) * usable / count
        ) + index * gap
    }

    function rectForBounds(width, height, topInset, bounds) {
        if (!bounds || width <= 0 || height <= topInset
                || gap < 0
                || width - gap * (bounds.columns + 1) <= 0
                || height - topInset - gap * (bounds.rows + 1) <= 0
                || !validBounds(
                    bounds, bounds.columns, bounds.rows, bounds.surface_id
                )) {
            return null
        }
        const x = cellStart(width, bounds.columns, bounds.left, 0)
        const y = cellStart(
            height - topInset, bounds.rows, bounds.top, topInset
        )
        const right = cellEnd(
            width, bounds.columns, bounds.right - 1, 0
        )
        const bottom = cellEnd(
            height - topInset, bounds.rows, bounds.bottom - 1, topInset
        )
        return {
            "x": x,
            "y": y,
            "width": right - x,
            "height": bottom - y
        }
    }

    function sameBounds(first, second) {
        return !!first && !!second
            && first.surface_id === second.surface_id
            && first.columns === second.columns && first.rows === second.rows
            && first.left === second.left && first.top === second.top
            && first.right === second.right && first.bottom === second.bottom
    }
}
