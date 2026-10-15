pragma ComponentBehavior: Bound

import QtQml

// Pane selection and Reader docking for the obsidience.shell.v1 command server:
// pane.present/pane.select for the Reader, Settings and the graph viewer, and
// pane.dock/float/collapse/expand with the dock drag gesture.
QtObject {
    id: root

    required property var server
    readonly property string eventSchema: server.eventSchema
    readonly property var readerPlacement: server.readerPlacement
    readonly property var paneWorkspace: server.paneWorkspace
    readonly property var dockLayout: server.dockLayout
    readonly property var surfaceLayout: server.surfaceLayout

    property var readerSelection: null
    property var settingsSelection: ({kind: "settings", section: "graph"})
    property int settingsSelectionRevision: 0
    property string graphViewerView: "knowledge"
    property var activeDockDrag: null

    function readerState() {
        return {
            "schema": eventSchema,
            "type": "pane.state",
            "pane": readerPlacement.record(),
            "selection": readerSelection
        }
    }

    function settingsState() {
        return {"schema": eventSchema, "type": "pane.selection", "pane_id": "settings",
            "revision": settingsSelectionRevision, "selection": settingsSelection}
    }

    function graphViewerState() {
        return {schema: eventSchema, type: "pane.selection", pane_id: "knowledge-graph",
            selection: {kind: "graph", view: graphViewerView}}
    }

    function cleanReaderSelection(selection) {
        if (!selection || typeof selection !== "object") return null
        if (selection.kind !== "article" && selection.kind !== "source") return null
        const field = selection.kind === "article" ? "ref" : "key"
        if (typeof selection[field] !== "string") return null
        const value = selection[field].trim()
        if (!value || value.length > 2048 || /[\u0000-\u001f]/.test(value)) return null
        const result = {kind: selection.kind, [field]: value,
            graph_id: selection.kind === "article" && typeof selection.graph_id === "string"
                && /^[A-Za-z0-9_-]{0,128}$/.test(selection.graph_id) ? selection.graph_id : ""}
        return result
    }

    function dockState() {
        return {
            "schema": eventSchema,
            "type": "pane.dock.state",
            "layout": dockLayout.record()
        }
    }

    function dockDragState(paneId, surfaceId) {
        return {
            "schema": eventSchema,
            "type": "pane.dock.drag",
            "pane_id": paneId || "",
            "surface_id": surfaceId || ""
        }
    }

    function isNumber(value) {
        return typeof value === "number" && Number.isFinite(value)
    }

    function placementFor(paneId) {
        return typeof paneId === "string"
            ? paneWorkspace.placementFor(paneId) : null
    }

    function presentPlacementOnSurface(placement, surfaceId) {
        const surface = surfaceLayout.surface(surfaceId)
        if (!placement || !surface) {
            return false
        }
        const x = placement.surfaceId === surfaceId ? placement.x
            : Math.round((surface.logical_width - placement.width) / 2)
        const y = placement.surfaceId === surfaceId ? placement.y
            : Math.round((surface.logical_height - placement.height) / 2)
        paneWorkspace.presentPaneOn(
            placement,
            surfaceId,
            surfaceLayout.clampPaneX(surface, placement.width, x),
            surfaceLayout.clampPaneY(surface, placement.height, y)
        )
        return true
    }

    function performDock(socket, command) {
        const pane = placementFor(command.pane_id)
        const host = placementFor(command.host_pane_id)
        const surfaceId = surfaceLayout.surface(command.surface_id)
            ? command.surface_id : (host ? host.surfaceId : "")
        if (!pane || !host || pane === host
                || !dockLayout.commitDock(
                    command.expected_revision,
                    pane.paneId,
                    host.paneId,
                    command.side,
                    command.position
                )) {
            failPaneCommand(socket, "pane.dock.failed", "", "stale_or_invalid")
            return false
        }
        pane.dismiss()
        presentPlacementOnSurface(host, surfaceId)
        server.broadcast(dockState())
        return true
    }

    function performFloat(socket, command) {
        const pane = placementFor(command.pane_id)
        const state = dockLayout.moduleState(command.pane_id)
        const host = placementFor(state.host_pane_id)
        if (!pane || !host || !dockLayout.commitFloat(
                command.expected_revision, command.pane_id)) {
            failPaneCommand(socket, "pane.dock.failed", "", "stale_or_invalid")
            return false
        }
        const targetSurfaceId = surfaceLayout.surface(command.surface_id)
            ? command.surface_id : host.surfaceId
        const surface = surfaceLayout.surface(targetSurfaceId)
        let x = pane.x
        let y = pane.y
        if (pane.surfaceId !== targetSurfaceId && surface) {
            x = Math.round((surface.logical_width - pane.width) / 2)
            y = Math.round((surface.logical_height - pane.height) / 2)
        }
        if (surface) {
            x = surfaceLayout.clampPaneX(surface, pane.width, x)
            y = surfaceLayout.clampPaneY(surface, pane.height, y)
        }
        paneWorkspace.presentPaneOn(pane, targetSurfaceId, x, y)
        server.broadcast(dockState())
        return true
    }

    function performCollapsed(socket, command, collapsed) {
        const state = dockLayout.moduleState(command.pane_id)
        const host = placementFor(state.host_pane_id)
        if (!host || state.host_pane_id !== command.host_pane_id
                || !dockLayout.commitCollapsed(
                    command.expected_revision,
                    command.pane_id,
                    collapsed
                )) {
            failPaneCommand(socket, "pane.dock.failed", "", "stale_or_invalid")
            return false
        }
        if (!collapsed) {
            const surfaceId = surfaceLayout.surface(command.surface_id)
                ? command.surface_id : host.surfaceId
            presentPlacementOnSurface(host, surfaceId)
        }
        server.broadcast(dockState())
        return true
    }

    function beginDockDrag(socket, command) {
        const pane = placementFor(command.pane_id)
        if (!pane || !surfaceLayout.surface(command.surface_id)
                || !dockLayout.canDock(command.pane_id, "reader")
                || command.expected_revision !== dockLayout.revision) {
            failPaneCommand(socket, "pane.dock.failed", "", "stale_or_invalid")
            return
        }
        activeDockDrag = {
            "pane_id": pane.paneId,
            "surface_id": command.surface_id,
            "was_docked": dockLayout.isDocked(pane.paneId)
        }
        server.broadcast(dockDragState(pane.paneId, command.surface_id))
    }

    function clearDockDrag() {
        activeDockDrag = null
        server.broadcast(dockDragState("", ""))
    }

    function finishDockDrag(socket, command) {
        const drag = activeDockDrag
        const pointer = command.pointer
        if (!drag || drag.pane_id !== command.pane_id
                || drag.surface_id !== command.surface_id
                || command.expected_revision !== dockLayout.revision
                || !pointer || !isNumber(pointer.x) || !isNumber(pointer.y)) {
            clearDockDrag()
            failPaneCommand(socket, "pane.dock.failed", "", "stale_or_invalid")
            return
        }
        clearDockDrag()

        const host = readerPlacement
        const contentX = host.x
        const contentY = host.y + 32
        const contentWidth = host.width
        const contentHeight = Math.max(0, host.height - 32)
        const localX = pointer.x - contentX
        const localY = pointer.y - contentY
        const inHost = host.open && host.surfaceId === drag.surface_id
            && localX >= 0 && localY >= 0
            && localX <= contentWidth && localY <= contentHeight
        const inLeft = inHost && localX <= contentWidth * 0.28
        const inRight = inHost && localX >= contentWidth * 0.72
        if (inLeft || inRight) {
            performDock(socket, {
                "pane_id": drag.pane_id,
                "host_pane_id": "reader",
                "surface_id": drag.surface_id,
                "expected_revision": dockLayout.revision,
                "side": inLeft ? "left" : "right",
                "position": localY < contentHeight / 2 ? "top" : "bottom"
            })
            return
        }
        if (drag.was_docked && dockLayout.isDocked(drag.pane_id)) {
            performFloat(socket, {
                "pane_id": drag.pane_id,
                "surface_id": drag.surface_id,
                "expected_revision": dockLayout.revision
            })
        }
    }

    function failPaneCommand(socket, type, token, reason) {
        server.send(socket, {
            "schema": eventSchema,
            "type": type,
            "token": typeof token === "string" ? token : "",
            "reason": reason
        })
    }

    function handleDockCommand(socket, command) {
        if (command.type === "pane.dock") {
            performDock(socket, command)
            return true
        }
        if (command.type === "pane.float") {
            performFloat(socket, command)
            return true
        }
        if (command.type === "pane.collapse") {
            performCollapsed(socket, command, true)
            return true
        }
        if (command.type === "pane.expand") {
            performCollapsed(socket, command, false)
            return true
        }
        if (command.type === "pane.dock.drag.start") {
            beginDockDrag(socket, command)
            return true
        }
        if (command.type === "pane.dock.drag.finish") {
            finishDockDrag(socket, command)
            return true
        }
        if (command.type === "pane.dock.drag.cancel") {
            clearDockDrag()
            return true
        }
        return false
    }

    // Selection commands for the Reader, Settings and the graph viewer.
    // Returns false for a command no domain owns.
    function handleSelection(socket, command) {
        if (["pane.present", "pane.select"].includes(command.type)
                && ["graph", "knowledge-graph", "memory", "code"].includes(command.pane_id)) {
            const selection = command.selection
            const view = selection ? (selection.kind === "graph" ? selection.view : "")
                : command.pane_id === "memory" || command.pane_id === "code" ? command.pane_id : graphViewerView
            if (!["knowledge", "memory", "code"].includes(view)) {
                server.commandError(socket, command, "invalid_selection")
                return true
            }
            const placement = placementFor("knowledge-graph")
            if (!placement || (command.type === "pane.present"
                    && !presentPlacementOnSurface(placement, placement.surfaceId))) {
                server.commandError(socket, command, "pane_unavailable")
                return true
            }
            // Header selection changes only the existing viewer, not placement
            // or native focus. Old pane IDs remain aliases, never extra windows.
            graphViewerView = view
            server.broadcast(graphViewerState())
            return true
        }
        if (command.pane_id === "settings" && command.type === "pane.present"
                && command.selection && command.selection.kind === "settings"
                && ["graph", "input", "workspace", "ai-voice"].includes(command.selection.section)) {
            const placement = placementFor("settings")
            if (placement && presentPlacementOnSurface(placement, placement.surfaceId)) {
                settingsSelection = {kind: "settings", section: command.selection.section}
                settingsSelectionRevision += 1
                server.broadcast(settingsState())
            } else {
                server.commandError(socket, command, "pane_unavailable")
            }
            return true
        }
        if (command.pane_id !== "reader" || command.type !== "pane.present") {
            return false
        }
        const selection = cleanReaderSelection(command.selection)
        if (!selection) {
            server.commandError(socket, command, "invalid_selection")
            return true
        }
        readerSelection = selection
        presentPlacementOnSurface(readerPlacement, readerPlacement.surfaceId)
        server.broadcast(readerState())
        return true
    }
}
