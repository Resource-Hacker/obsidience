pragma ComponentBehavior: Bound

import QtQml

// Gap-aware zone geometry follows the small pure-geometry pattern in
// Omarchy Windows' MIT-licensed Aero Snap helper. Obsidience generalizes that
// pattern to an arbitrary integer grid; Hyprland's layout.lua owns resizing.
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

    function boundsForRect(width, height, topInset, surfaceId, columns, rows,
                           rect) {
        if (!rect || width <= 0 || height <= topInset
                || !Number.isInteger(columns) || columns < 1
                || !Number.isInteger(rows) || rows < 1
                || typeof rect.x !== "number" || !isFinite(rect.x)
                || typeof rect.y !== "number" || !isFinite(rect.y)
                || typeof rect.width !== "number" || !isFinite(rect.width)
                || typeof rect.height !== "number" || !isFinite(rect.height)
                || rect.width <= 0 || rect.height <= 0) {
            return null
        }
        const workspaceHeight = height - topInset
        const left = Math.max(0, Math.min(
            columns - 1, Math.round(rect.x * columns / width)
        ))
        const top = Math.max(0, Math.min(
            rows - 1,
            Math.round((rect.y - topInset) * rows / workspaceHeight)
        ))
        const right = Math.max(left + 1, Math.min(
            columns, Math.round((rect.x + rect.width) * columns / width)
        ))
        const bottom = Math.max(top + 1, Math.min(
            rows,
            Math.round(
                (rect.y + rect.height - topInset) * rows / workspaceHeight
            )
        ))
        return makeBounds(
            surfaceId, columns, rows, left, top, right, bottom
        )
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
}
