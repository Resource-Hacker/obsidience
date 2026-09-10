pragma ComponentBehavior: Bound

import QtQml
import QtWebSockets
import "../workspace"

QtObject {
    id: root

    required property PanePlacement readerPlacement
    required property PaneWorkspace paneWorkspace
    required property PaneDockLayout dockLayout
    required property var surfaceLayout
    required property bool knowledgeVisible
    required property bool sessionLocked

    readonly property string commandSchema: "obsidience.shell.command.v1"
    readonly property string eventSchema: "obsidience.shell.event.v1"
    readonly property string subprotocol: "obsidience.shell.v1"
    property var readerSelection: null
    property var settingsSelection: ({kind: "settings", section: "graph"})
    property int settingsSelectionRevision: 0
    property var clients: []
    property var graphStates: ({})
    property var windowStates: ({})
    property var moduleWindowBindings: ({})
    property var moduleRestorePending: null
    property int moduleRestoreSequence: 0
    property var windowAdapterSocket: null
    property int lockGeneration: 0
    property var clickTokens: []
    property var clickRequests: []
    readonly property int clickTokenLimit: 4096
    readonly property int clickRequestLifetimeMs: 6000
    property string selectedGraphId: "main"
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

    function cleanReaderSelection(selection) {
        if (!selection || typeof selection !== "object") return null
        if (selection.kind === "feed_preview") {
            const item = selection.item
            if (!item || typeof item !== "object" || Array.isArray(item)) return null
            const limits = {title: 300, summary: 4000, reporting_url: 2048,
                published: 100, feed_title: 300, feed_url: 2048}
            const preview = {}
            for (const field of Object.keys(limits)) {
                if (typeof item[field] !== "string" || Array.from(item[field]).length > limits[field]
                        || /[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(item[field])) return null
                preview[field] = item[field]
            }
            return {kind: "feed_preview", item: preview}
        }
        if (selection.kind !== "article" && selection.kind !== "source") return null
        const field = selection.kind === "article" ? "ref" : "key"
        if (typeof selection[field] !== "string") return null
        const value = selection[field].trim()
        if (!value || value.length > 2048 || /[\u0000-\u001f]/.test(value)) return null
        const result = {kind: selection.kind, [field]: value,
            graph_id: selection.kind === "article" && typeof selection.graph_id === "string"
                && /^[A-Za-z0-9_-]{0,128}$/.test(selection.graph_id) ? selection.graph_id : ""}
        if (selection.kind === "source" && selection.feed_item_id !== undefined) {
            if (typeof selection.feed_item_id !== "string"
                    || !/^[A-Za-z0-9_-]{1,128}$/.test(selection.feed_item_id)) return null
            result.feed_item_id = selection.feed_item_id
        }
        return result
    }

    function knowledgeState() {
        return {
            "schema": eventSchema,
            "type": "surface.state",
            "surface": {
                "surface_id": surfaceLayout.graphSurfaceId,
                "visible": knowledgeVisible
            }
        }
    }

    function graphDisplayState() {
        const options = []
        for (const surface of surfaceLayout.surfaces) {
            options.push({"id": surface.id, "label": surface.label})
        }
        return {
            "schema": eventSchema,
            "type": "graph.display.state",
            "revision": surfaceLayout.revision,
            "selected_surface_id": surfaceLayout.graphSurfaceId,
            "surfaces": options
        }
    }

    function workspaceState() {
        return {
            "schema": eventSchema,
            "type": "workspace.state",
            "revision": surfaceLayout.revision,
            "pane_grid_size": surfaceLayout.paneGridSize,
            "minimum_pane_grid_size": surfaceLayout.minimumPaneGridSize,
            "maximum_pane_grid_size": surfaceLayout.maximumPaneGridSize,
            "minimum_tile_count": surfaceLayout.minimumTileCount,
            "maximum_tile_count": surfaceLayout.maximumTileCount,
            "workspace_tile_gap": surfaceLayout.workspaceTileGap,
            "tile_resize_limit_percent": surfaceLayout.tileResizeLimitPercent,
            "minimum_tile_resize_limit_percent": surfaceLayout.minimumTileResizeLimitPercent,
            "maximum_tile_resize_limit_percent": surfaceLayout.maximumTileResizeLimitPercent,
            "oled_mode_enabled": surfaceLayout.oledModeEnabled,
            "oled_shift_distance_px": surfaceLayout.oledShiftDistancePx,
            "minimum_oled_shift_distance_px": surfaceLayout.minimumOledShiftDistancePx,
            "maximum_oled_shift_distance_px": surfaceLayout.maximumOledShiftDistancePx,
            "oled_travel_duration_seconds": surfaceLayout.oledTravelDurationSeconds,
            "minimum_oled_travel_duration_seconds": surfaceLayout.minimumOledTravelDurationSeconds,
            "maximum_oled_travel_duration_seconds": surfaceLayout.maximumOledTravelDurationSeconds,
            "oled_glow_rotation_hours": surfaceLayout.oledGlowRotationHours,
            "session_locked": sessionLocked,
            "lock_generation": lockGeneration,
            "minimum_oled_glow_rotation_hours": surfaceLayout.minimumOledGlowRotationHours,
            "maximum_oled_glow_rotation_hours": surfaceLayout.maximumOledGlowRotationHours,
            "workspace_tiling": surfaceLayout.workspaceTilingState()
        }
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

    function clamp(value, minimum, maximum) {
        return Math.max(minimum, Math.min(maximum, value))
    }

    function cleanDragToken(value) {
        return typeof value === "string"
            && /^[A-Za-z0-9._:-]{1,96}$/.test(value) ? value : ""
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
        broadcast(dockState())
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
        broadcast(dockState())
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
        broadcast(dockState())
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
        broadcast(dockDragState(pane.paneId, command.surface_id))
    }

    function clearDockDrag() {
        activeDockDrag = null
        broadcast(dockDragState("", ""))
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
        send(socket, {
            "schema": eventSchema,
            "type": type,
            "token": typeof token === "string" ? token : "",
            "reason": reason
        })
    }

    function handlePaneCommand(socket, command) {
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

    function send(socket, message) {
        if (socket && socket.status === WebSocket.Open) {
            socket.sendTextMessage(JSON.stringify(message))
        }
    }

    function broadcast(message) {
        for (const socket of clients) {
            send(socket, message)
        }
    }

    function removeClient(socket) {
        clients = clients.filter(candidate => candidate !== socket)
        for (const pending of clickRequests) {
            if (pending.adapter === socket && pending.socket !== socket) {
                windowClickResult(pending.socket, pending.command, false,
                    "shell_scene_command_unavailable", "uncertain")
            }
        }
        clickRequests = clickRequests.filter(pending =>
            pending.socket !== socket && pending.adapter !== socket)
        if (windowAdapterSocket === socket) {
            windowAdapterSocket = null
        }
    }

    function cleanWindowText(value, maximum) {
        if (typeof value !== "string") {
            return ""
        }
        const text = value.replace(/[\u0000-\u001f]/g, " ")
            .replace(/\s+/g, " ").trim()
        return text.slice(0, maximum)
    }

    function cleanPaneId(value) {
        return typeof value === "string"
            && /^[a-z][a-z0-9-]{0,47}$/.test(value) ? value : ""
    }

    function cleanWindowRect(value) {
        if (!value || typeof value !== "object"
                || !Number.isInteger(value.x) || !Number.isInteger(value.y)
                || !Number.isInteger(value.width) || value.width < 1
                || !Number.isInteger(value.height) || value.height < 1
                || Math.abs(value.x) > 32768 || Math.abs(value.y) > 32768
                || value.width > 32768 || value.height > 32768) {
            return null
        }
        return {
            "x": value.x,
            "y": value.y,
            "width": value.width,
            "height": value.height
        }
    }

    function cleanTileBounds(value, surfaceId) {
        if (!value || typeof value !== "object"
                || value.surface_id !== surfaceId
                || !Number.isInteger(value.columns)
                || !Number.isInteger(value.rows)
                || !Number.isInteger(value.left)
                || !Number.isInteger(value.top)
                || !Number.isInteger(value.right)
                || !Number.isInteger(value.bottom)) {
            return null
        }
        const bounds = {
            "surface_id": surfaceId,
            "columns": value.columns,
            "rows": value.rows,
            "left": value.left,
            "top": value.top,
            "right": value.right,
            "bottom": value.bottom
        }
        return surfaceLayout.validTileBounds(surfaceId, bounds) ? bounds : null
    }

    function cleanWindowState(command) {
        const surfaceId = typeof command.surface_id === "string"
            && surfaceLayout.surface(command.surface_id) ? command.surface_id : ""
        if (!surfaceId || !Number.isInteger(command.revision)
                || command.revision < 1 || !Array.isArray(command.windows)
                || command.windows.length > 256
                || typeof command.surface_awake !== "boolean") {
            return null
        }
        const windows = []
        const ids = {}
        for (const candidate of command.windows) {
            if (!candidate || typeof candidate !== "object") {
                continue
            }
            const windowId = cleanWindowText(candidate.window_id, 128)
            const appId = cleanWindowText(candidate.app_id, 256)
            const windowKind = candidate.window_kind === "module"
                ? "module" : candidate.window_kind === "application"
                    ? "application" : ""
            const paneId = windowKind === "module"
                ? cleanPaneId(candidate.pane_id) : ""
            const stableId = cleanWindowText(candidate.stable_id, 128)
            const localRect = cleanWindowRect(candidate.local_rect)
            if (!windowId || !appId || !windowKind || !localRect
                    || (windowKind === "module"
                        && (appId !== "io.obsidience.shell" || !paneId))
                    || ids[windowId]) {
                continue
            }
            ids[windowId] = true
            windows.push({
                "window_id": windowId,
                "app_id": appId,
                "title": cleanWindowText(candidate.title, 512) || appId,
                "pid": Number.isInteger(candidate.pid) && candidate.pid > 0
                    ? candidate.pid : 0,
                "minimized": candidate.minimized === true,
                "visible_on_workspace": candidate.visible_on_workspace === true,
                "window_kind": windowKind,
                "pane_id": paneId,
                "stable_id": stableId,
                "local_rect": localRect
            })
        }
        let activeWindowId = cleanWindowText(command.active_window_id, 128)
        if (!ids[activeWindowId]) {
            activeWindowId = ""
        }
        return {
            "schema": eventSchema,
            "type": "application.state",
            "surface_id": surfaceId,
            "revision": command.revision,
            "active_window_id": activeWindowId,
            "surface_awake": command.surface_awake,
            "windows": windows
        }
    }

    function moduleCandidateMatchesIntent(placement, binding, state, window) {
        if (!placement || !state || !window) {
            return false
        }
        // A unique remapped address may need the existing cross-Surface restore.
        if (!binding || binding.window_id !== window.window_id) {
            return true
        }
        // A Surface selected by the shell is pending until this exact native
        // window reaches it. With no pending intent, a native Surface move is
        // authoritative and may be observed normally.
        return placement.surfaceId === binding.surface_id
            || state.surface_id === placement.surfaceId
    }

    function requestModuleRestore(paneId, placement, state, window) {
        const bounds = placement.tileBounds
        if (!windowAdapterSocket
                || windowAdapterSocket.status !== WebSocket.Open
                || moduleRestorePending
                || !bounds
                || bounds.surface_id !== placement.surfaceId
                || !surfaceLayout.validTileBounds(bounds.surface_id, bounds)) {
            return false
        }
        moduleRestoreSequence += 1
        const token = "restore." + paneId + "."
            + String(moduleRestoreSequence)
        moduleWindowBindings = Object.assign({}, moduleWindowBindings, {
            [paneId]: {
                "window_id": window.window_id,
                "surface_id": bounds.surface_id,
                "restoring": true,
                "restore_failed": false,
                "restore_token": token
            }
        })
        moduleRestorePending = {
            "token": token,
            "pane_id": paneId,
            "window_id": window.window_id,
            "source_surface_id": state.surface_id,
            "source_revision": state.revision,
            "destination_surface_id": bounds.surface_id,
            "cross_surface": state.surface_id !== bounds.surface_id,
            "result_received": false,
            "post_revision": 0,
            "tile_bounds": bounds
        }
        const request = {
            "schema": eventSchema,
            "type": state.surface_id === bounds.surface_id
                ? "window.layout.restore.request" : "window.place.request",
            "token": token,
            "surface_id": state.surface_id,
            "window_id": window.window_id,
            "expected_revision": state.revision,
            "tile_bounds": bounds,
            "pane_id": paneId
        }
        if (request.type === "window.place.request") {
            request.destination_surface_id = bounds.surface_id
            request.workspace_tiling = surfaceLayout.workspaceTilingState()
        }
        send(windowAdapterSocket, request)
        return true
    }

    function finishModuleRestore(token, success) {
        const pending = moduleRestorePending
        if (!pending || pending.token !== token) {
            return false
        }
        const paneId = pending.pane_id
        const binding = moduleWindowBindings[paneId]
        if (!binding || binding.restore_token !== token) {
            return false
        }
        moduleWindowBindings = Object.assign(
            {}, moduleWindowBindings, {
                [paneId]: {
                    "window_id": binding.window_id,
                    "surface_id": binding.surface_id,
                    "restoring": false,
                    "restore_failed": success !== true,
                    "restore_token": ""
                }
            }
        )
        moduleRestorePending = null
        return true
    }

    function stateWindow(state, windowId) {
        if (!state) {
            return null
        }
        for (const window of state.windows) {
            if (window.window_id === windowId) {
                return window
            }
        }
        return null
    }

    function settlePendingModuleRestore() {
        const pending = moduleRestorePending
        if (!pending || pending.result_received !== true) {
            return false
        }
        const source = windowStates[pending.source_surface_id]
        const destination = windowStates[pending.destination_surface_id]
        const destinationWindow = stateWindow(
            destination, pending.window_id)
        const settled = destinationWindow
            ? surfaceLayout.nearestTiledPaneRect(
                pending.destination_surface_id,
                destinationWindow.local_rect
            ) : null
        const placement = placementFor(pending.pane_id)
        if (!destination
                || destination.revision < pending.post_revision
                || !destinationWindow || !settled || !placement
                || !placement.sameTileBounds(
                    pending.tile_bounds, settled.tile_bounds)
                || (pending.cross_surface === true
                    && (!source
                        || source.revision <= pending.source_revision
                        || stateWindow(source, pending.window_id)))) {
            return false
        }
        return finishModuleRestore(pending.token, true)
    }

    function observeModuleWindows() {
        if (sessionLocked || moduleRestorePending) {
            return
        }
        const candidates = {}
        const duplicates = {}
        for (const surfaceId of Object.keys(windowStates)) {
            const state = windowStates[surfaceId]
            for (const window of state.windows) {
                if (window.window_kind !== "module") {
                    continue
                }
                if (candidates[window.pane_id]) {
                    duplicates[window.pane_id] = true
                } else {
                    candidates[window.pane_id] = {
                        "state": state,
                        "window": window
                    }
                }
            }
        }

        for (const paneId of Object.keys(candidates)) {
            if (duplicates[paneId]) {
                continue
            }
            const placement = placementFor(paneId)
            if (!placement || !placement.open || dockLayout.isDocked(paneId)) {
                continue
            }
            const candidate = candidates[paneId]
            const state = candidate.state
            const window = candidate.window
            const binding = moduleWindowBindings[paneId]
            if (!moduleCandidateMatchesIntent(
                    placement, binding, state, window)) {
                continue
            }
            if ((!binding || binding.window_id !== window.window_id)
                    && requestModuleRestore(
                        paneId, placement, state, window)) {
                // A restore publishes a new adapter revision. Serialize open
                // panes so the next request binds that fresh exact revision.
                return
            }
            if (binding && binding.window_id === window.window_id
                    && (binding.restoring === true
                        || binding.restore_failed === true)) {
                continue
            }
            const settled = surfaceLayout.nearestTiledPaneRect(
                state.surface_id, window.local_rect
            )
            if (!settled) {
                continue
            }
            placement.observeNative(
                state.surface_id, settled, settled.tile_bounds
            )
            if (!binding || binding.window_id !== window.window_id
                    || binding.surface_id !== state.surface_id) {
                moduleWindowBindings = Object.assign(
                    {}, moduleWindowBindings, {
                        [paneId]: {
                            "window_id": window.window_id,
                            "surface_id": state.surface_id,
                            "restoring": false,
                            "restore_failed": false,
                            "restore_token": ""
                        }
                    }
                )
            }
        }
    }

    function windowResult(socket, command, success, reason) {
        const event = {
            "schema": eventSchema,
            "type": "window.activation.result",
            "token": cleanDragToken(command.token),
            "surface_id": cleanWindowText(command.surface_id, 32),
            "window_id": cleanWindowText(command.window_id, 128),
            "success": success === true,
            "reason": cleanWindowText(reason, 96),
            "post_revision": Number.isInteger(command.post_revision)
                && command.post_revision > 0 ? command.post_revision : 0
        }
        if (socket) {
            send(socket, event)
        } else {
            broadcast(event)
        }
    }

    function windowPlaceResult(socket, command, success, reason) {
        const event = {
            "schema": eventSchema,
            "type": "window.place.result",
            "token": cleanDragToken(command.token),
            "surface_id": cleanWindowText(command.surface_id, 32),
            "window_id": cleanWindowText(command.window_id, 128),
            "destination_surface_id": cleanWindowText(
                command.destination_surface_id, 32),
            "success": success === true,
            "reason": cleanWindowText(reason, 96),
            "post_revision": Number.isInteger(command.post_revision)
                && command.post_revision > 0 ? command.post_revision : 0,
            "verified_tile_bounds": success === true
                ? cleanTileBounds(command.verified_tile_bounds,
                    command.destination_surface_id) : null
        }
        if (socket) {
            send(socket, event)
        } else {
            broadcast(event)
        }
    }

    function windowLayoutResult(socket, command, success, reason) {
        const event = {
            "schema": eventSchema,
            "type": "window.layout.result",
            "token": cleanDragToken(command.token),
            "surface_id": cleanWindowText(command.surface_id, 32),
            "window_id": cleanWindowText(command.window_id, 128),
            "success": success === true,
            "reason": cleanWindowText(reason, 96)
        }
        if (socket) {
            send(socket, event)
        } else {
            broadcast(event)
        }
    }

    function windowCloseResult(socket, command, success, reason) {
        const event = {
            "schema": eventSchema,
            "type": "window.close.result",
            "token": cleanDragToken(command.token),
            "surface_id": cleanWindowText(command.surface_id, 32),
            "window_id": cleanWindowText(command.window_id, 128),
            "success": success === true,
            "reason": cleanWindowText(reason, 96)
        }
        if (socket) {
            send(socket, event)
        } else {
            broadcast(event)
        }
    }

    function hasExactFields(value, fields) {
        return value !== null && typeof value === "object" && !Array.isArray(value)
            && Object.keys(value).length === fields.length
            && fields.every(key => Object.prototype.hasOwnProperty.call(value, key))
    }

    function cleanClickWitness(value) {
        const fields = ["stable_id", "pid", "process_start_time", "local_rect",
            "image_width", "image_height", "x", "y", "captured_at_unix_ns",
            "label"]
        if (!hasExactFields(value, fields)
                || typeof value.stable_id !== "string"
                || !/^[0-9a-f]{1,32}$/.test(value.stable_id)
                || /[^0-9a-f]/.test(value.stable_id)
                || typeof value.label !== "string"
                || value.label.length < 1 || value.label.length > 128
                || !value.label.trim() || /[\u0000-\u001f]/.test(value.label)
                || !["pid", "process_start_time", "captured_at_unix_ns"].every(key =>
                    Number.isInteger(value[key]) && value[key] > 0
                        && value[key] < Math.pow(2, 63))
                || !["image_width", "image_height"].every(key =>
                    Number.isInteger(value[key]) && value[key] > 0
                        && value[key] <= 16000000)
                || value.image_width * value.image_height > 16000000
                || !Number.isFinite(value.x) || !Number.isFinite(value.y)
                || value.x < 0 || value.x >= value.image_width
                || value.y < 0 || value.y >= value.image_height) {
            return null
        }
        const rect = value.local_rect
        const rectFields = ["x", "y", "width", "height"]
        if (!hasExactFields(rect, rectFields)
                || !rectFields.every(key => Number.isInteger(rect[key]))
                || Math.abs(rect.x) > 131072 || Math.abs(rect.y) > 131072
                || rect.width < 1 || rect.width > 65536
                || rect.height < 1 || rect.height > 65536) {
            return null
        }
        return value
    }

    function cleanClickToken(value) {
        const token = cleanDragToken(value)
        return token && !/[^A-Za-z0-9._:-]/.test(token) ? token : ""
    }

    function windowClickResult(socket, command, success, reason, delivery) {
        send(socket, {
            "schema": eventSchema, "type": "window.click.result",
            "token": cleanClickToken(command.token),
            "surface_id": cleanWindowText(command.surface_id, 32),
            "window_id": cleanWindowText(command.window_id, 128),
            "success": success === true,
            "reason": cleanWindowText(reason, 96),
            "delivery": delivery
        })
    }

    function clickRequestOwned(pending) {
        if (!pending || sessionLocked || pending.generation !== lockGeneration
                || Date.now() < pending.createdAt
                || Date.now() - pending.createdAt >= clickRequestLifetimeMs
                || pending.socket.status !== WebSocket.Open
                || clients.indexOf(pending.socket) < 0
                || pending.adapter !== windowAdapterSocket
                || !windowAdapterSocket || windowAdapterSocket.status !== WebSocket.Open) {
            return false
        }
        return true
    }

    function clickRequestCurrent(pending) {
        if (!clickRequestOwned(pending)) {
            return false
        }
        const command = pending.command
        const state = windowStates[command.surface_id]
        const window = state && state.windows.find(candidate =>
            candidate.window_id === command.window_id)
        return !!window && state.revision === command.expected_revision
            && state.surface_awake === true && window.window_kind === "application"
            && window.minimized !== true && window.visible_on_workspace === true
    }

    function invalidateClickRequests(reason) {
        for (const pending of clickRequests) {
            windowClickResult(pending.socket, pending.command, false, reason, "uncertain")
        }
        clickRequests = []
    }

    function handleClickCommand(socket, command) {
        const type = command.type
        if (["window.click", "window.click.guard", "window.click.cancel",
                "window.click.result"].indexOf(type) < 0) {
            return false
        }
        const token = cleanClickToken(command.token)
        const pending = clickRequests.find(item => item.command.token === token)
        if (type === "window.click.guard") {
            const allowed = command.token === token && !!token
                && hasExactFields(command, ["schema", "type", "token", "surface_id",
                    "window_id", "expected_revision", "lock_generation"])
                && clickRequestCurrent(pending)
                && command.surface_id === pending.command.surface_id
                && command.window_id === pending.command.window_id
                && command.expected_revision === pending.command.expected_revision
                && command.lock_generation === pending.generation
            send(socket, {"schema": eventSchema, "type": "window.click.guard.result",
                "token": token, "allowed": allowed === true})
            return true
        }
        if (type === "window.click.cancel") {
            if (pending && pending.socket === socket) {
                clickRequests = clickRequests.filter(item => item !== pending)
                windowClickResult(socket, pending.command, false, "cancelled", "uncertain")
            }
            return true
        }
        if (type === "window.click.result") {
            if (!pending || socket !== windowAdapterSocket || socket !== pending.adapter
                    || command.token !== token
                    || command.surface_id !== pending.command.surface_id
                    || command.window_id !== pending.command.window_id) {
                return true
            }
            clickRequests = clickRequests.filter(item => item !== pending)
            const validResult = typeof command.success === "boolean"
                && typeof command.reason === "string"
                && ["acknowledged", "not_dispatched", "uncertain"].indexOf(command.delivery) >= 0
                && (!command.success || command.delivery === "acknowledged")
            // A click can change the scene before its receipt arrives. Preserve
            // the adapter's acknowledgement; only the fresh post-image can
            // establish what the application did. Ownership loss stays uncertain.
            if (!validResult || (!clickRequestOwned(pending)
                    && command.delivery !== "not_dispatched")) {
                windowClickResult(pending.socket, pending.command, false,
                    "click_outcome_uncertain", "uncertain")
            } else {
                windowClickResult(pending.socket, pending.command,
                    command.success, command.reason, command.delivery)
            }
            return true
        }
        if (!token || command.token !== token) {
            windowClickResult(socket, command, false, "invalid_click_request", "not_dispatched")
            return true
        }
        if (clickTokens.indexOf(token) >= 0) {
            windowClickResult(socket, command, false, "duplicate_token", "uncertain")
            return true
        }
        if (clickTokens.length >= clickTokenLimit) {
            windowClickResult(socket, command, false, "click_token_capacity", "not_dispatched")
            return true
        }
        clickTokens = clickTokens.concat([token])
        const witness = cleanClickWitness(command.witness)
        if (!hasExactFields(command, ["schema", "type", "token", "surface_id",
                    "window_id", "expected_revision", "witness"])
                || !witness || typeof command.surface_id !== "string"
                || !surfaceLayout.surface(command.surface_id)
                || typeof command.window_id !== "string" || !command.window_id
                || command.window_id.length > 128 || /[\u0000-\u001f]/.test(command.window_id)
                || !Number.isSafeInteger(command.expected_revision)
                || command.expected_revision < 1) {
            windowClickResult(socket, command, false, "invalid_click_request", "not_dispatched")
            return true
        }
        const candidate = {"socket": socket, "adapter": windowAdapterSocket,
            "command": command, "generation": lockGeneration, "createdAt": Date.now()}
        if (!clickRequestCurrent(candidate)) {
            windowClickResult(socket, command, false,
                sessionLocked ? "scene_unavailable" : "stale_or_unavailable", "not_dispatched")
            return true
        }
        // Expiry is checked on demand; no polling or timer owns input delivery.
        clickRequests = clickRequests.filter(item => {
            if (Date.now() - item.createdAt < clickRequestLifetimeMs) {
                return true
            }
            windowClickResult(item.socket, item.command, false, "click_expired", "uncertain")
            return false
        })
        if (clickRequests.length >= 32) {
            windowClickResult(socket, command, false, "click_busy", "not_dispatched")
            return true
        }
        clickRequests = clickRequests.concat([candidate])
        send(windowAdapterSocket, {
            "schema": eventSchema, "type": "window.click.request", "token": token,
            "surface_id": command.surface_id, "window_id": command.window_id,
            "expected_revision": command.expected_revision, "witness": witness,
            "lock_generation": lockGeneration
        })
        return true
    }

    function handleWindowCommand(socket, command) {
        if (handleClickCommand(socket, command)) {
            return true
        }
        if (command.type === "window.adapter.subscribe") {
            if (windowAdapterSocket && windowAdapterSocket !== socket) {
                invalidateClickRequests("shell_scene_command_unavailable")
                windowAdapterSocket.active = false
            }
            windowAdapterSocket = socket
            windowStates = ({})
            return true
        }
        if (command.type === "window.state.publish") {
            if (socket !== windowAdapterSocket) {
                return true
            }
            const state = cleanWindowState(command)
            if (!state) {
                return true
            }
            windowStates = Object.assign(
                {}, windowStates, {[state.surface_id]: state}
            )
            settlePendingModuleRestore()
            observeModuleWindows()
            broadcast(state)
            return true
        }
        if (command.type === "window.activation.result") {
            if (socket !== windowAdapterSocket || !cleanDragToken(command.token)) {
                return true
            }
            windowResult(
                null, command, command.success === true,
                command.success === true ? "" : command.reason
            )
            return true
        }
        if (command.type === "window.layout.result") {
            if (socket !== windowAdapterSocket || !cleanDragToken(command.token)) {
                return true
            }
            windowLayoutResult(
                null, command, command.success === true,
                command.success === true ? "" : command.reason
            )
            return true
        }
        if (command.type === "window.place.result") {
            if (socket !== windowAdapterSocket || !cleanDragToken(command.token)) {
                return true
            }
            const pending = moduleRestorePending
            if (pending && pending.token === command.token
                    && pending.cross_surface === true) {
                if (command.success === true) {
                    moduleRestorePending = Object.assign({}, pending, {
                        "result_received": true,
                        "post_revision": Number.isInteger(command.post_revision)
                            && command.post_revision > 0
                            ? command.post_revision : 0
                    })
                    if (settlePendingModuleRestore()) {
                        observeModuleWindows()
                    }
                } else if (finishModuleRestore(command.token, false)) {
                    observeModuleWindows()
                }
            }
            windowPlaceResult(
                null, command, command.success === true,
                command.success === true ? "" : command.reason
            )
            return true
        }
        if (command.type === "window.layout.restore.result") {
            if (socket !== windowAdapterSocket
                    || !cleanDragToken(command.token)) {
                return true
            }
            const pending = moduleRestorePending
            if (pending && pending.token === command.token
                    && pending.cross_surface !== true) {
                if (command.success === true) {
                    moduleRestorePending = Object.assign({}, pending, {
                        "result_received": true
                    })
                    if (settlePendingModuleRestore()) {
                        observeModuleWindows()
                    }
                } else if (finishModuleRestore(command.token, false)) {
                    observeModuleWindows()
                }
            }
            return true
        }
        if (command.type === "window.close.result") {
            if (socket !== windowAdapterSocket || !cleanDragToken(command.token)) {
                return true
            }
            windowCloseResult(
                null, command, command.success === true,
                command.success === true ? "" : command.reason
            )
            return true
        }
        if (command.type === "window.close_active") {
            const token = cleanDragToken(command.token)
            const surfaceId = cleanWindowText(command.source_surface_id, 32)
            const state = windowStates[surfaceId]
            const windowId = state ? state.active_window_id : ""
            if (!token || !surfaceLayout.surface(surfaceId)) {
                windowCloseResult(socket, command, false, "invalid")
                return true
            }
            const current = state && windowId
                && state.windows.find(window => window.window_id === windowId)
            if (!current || !windowAdapterSocket
                    || windowAdapterSocket.status !== WebSocket.Open) {
                windowCloseResult(socket, command, false, "stale_or_unavailable")
                return true
            }
            if (current.window_kind === "module") {
                const placement = placementFor(current.pane_id)
                if (!placement || !placement.open) {
                    windowCloseResult(
                        socket, command, false, "stale_or_unavailable")
                    return true
                }
                placement.dismiss()
                windowCloseResult(socket, {
                    "token": token,
                    "surface_id": surfaceId,
                    "window_id": windowId
                }, true, "")
                return true
            }
            send(windowAdapterSocket, {
                "schema": eventSchema,
                "type": "window.close.request",
                "token": token,
                "surface_id": surfaceId,
                "window_id": windowId,
                "expected_revision": state.revision
            })
            return true
        }
        if (command.type === "window.layout_active") {
            const token = cleanDragToken(command.token)
            const surfaceId = cleanWindowText(command.source_surface_id, 32)
            const action = cleanWindowText(command.action, 16)
            const direction = cleanWindowText(command.direction, 16)
            const state = windowStates[surfaceId]
            const windowId = state ? state.active_window_id : ""
            const validAction = ["resize", "tile", "surface"].indexOf(action) >= 0
            const validDirection = ["left", "right", "top", "bottom"]
                .indexOf(direction) >= 0
            if (!token || !surfaceLayout.surface(surfaceId)
                    || !validAction || !validDirection) {
                windowLayoutResult(socket, command, false, "invalid")
                return true
            }
            const current = state && windowId
                && state.windows.some(window => window.window_id === windowId)
            if (!current || !windowAdapterSocket
                    || windowAdapterSocket.status !== WebSocket.Open) {
                windowLayoutResult(socket, command, false, "stale_or_unavailable")
                return true
            }
            send(windowAdapterSocket, {
                "schema": eventSchema,
                "type": "window.layout.request",
                "token": token,
                "surface_id": surfaceId,
                "window_id": windowId,
                "expected_revision": state.revision,
                "action": action,
                "direction": direction,
                "workspace_tiling": surfaceLayout.workspaceTilingState()
            })
            return true
        }
        if (command.type === "window.place") {
            const token = cleanDragToken(command.token)
            const surfaceId = cleanWindowText(command.surface_id, 32)
            const windowId = cleanWindowText(command.window_id, 128)
            const destinationSurfaceId = cleanWindowText(
                command.destination_surface_id, 32)
            const state = windowStates[surfaceId]
            const current = state && state.revision === command.expected_revision
                && state.windows.some(window => window.window_id === windowId)
            const suppliedBounds = command.tile_bounds !== undefined
                && command.tile_bounds !== null
            const tileBounds = suppliedBounds
                ? cleanTileBounds(command.tile_bounds, destinationSurfaceId)
                : null
            if (!token || !surfaceLayout.surface(destinationSurfaceId)
                    || (suppliedBounds && !tileBounds)) {
                windowPlaceResult(socket, command, false, "invalid_destination")
                return true
            }
            if (sessionLocked) {
                windowPlaceResult(socket, command, false, "scene_unavailable")
                return true
            }
            if (!current) {
                windowPlaceResult(socket, command, false, "stale_scene")
                return true
            }
            if (!windowAdapterSocket
                    || windowAdapterSocket.status !== WebSocket.Open) {
                windowPlaceResult(
                    socket, command, false, "shell_scene_command_unavailable")
                return true
            }
            send(windowAdapterSocket, {
                "schema": eventSchema,
                "type": "window.place.request",
                "token": token,
                "surface_id": surfaceId,
                "window_id": windowId,
                "expected_revision": command.expected_revision,
                "destination_surface_id": destinationSurfaceId,
                "tile_bounds": tileBounds,
                "workspace_tiling": surfaceLayout.workspaceTilingState()
            })
            return true
        }
        if (command.type !== "window.activate") {
            return false
        }
        const token = cleanDragToken(command.token)
        const surfaceId = cleanWindowText(command.surface_id, 32)
        const windowId = cleanWindowText(command.window_id, 128)
        const state = windowStates[surfaceId]
        const current = state && state.revision === command.expected_revision
            && state.windows.some(window => window.window_id === windowId)
        if (!token) {
            windowResult(socket, command, false, "stale_scene")
            return true
        }
        if (sessionLocked) {
            windowResult(socket, command, false, "scene_unavailable")
            return true
        }
        if (!current) {
            windowResult(socket, command, false, "stale_scene")
            return true
        }
        if (!windowAdapterSocket
                || windowAdapterSocket.status !== WebSocket.Open) {
            windowResult(
                socket, command, false, "shell_scene_command_unavailable")
            return true
        }
        send(windowAdapterSocket, {
            "schema": eventSchema,
            "type": "window.activation.request",
            "token": token,
            "surface_id": surfaceId,
            "window_id": windowId,
            "expected_revision": command.expected_revision
        })
        return true
    }

    function cleanGraphId(value) {
        if (typeof value !== "string") {
            return ""
        }
        const graphId = value.trim()
        return graphId && graphId.length <= 64
            && !/[\u0000-\u001f]/.test(graphId) ? graphId : ""
    }

    function cleanTuning(value) {
        if (!value || typeof value !== "object" || Array.isArray(value)) {
            return null
        }
        const result = {}
        let count = 0
        for (const key of Object.keys(value)) {
            if (count >= 64 || !/^[A-Za-z][A-Za-z0-9_]{0,47}$/.test(key)) {
                continue
            }
            const number = value[key]
            if (typeof number === "number" && Number.isFinite(number)) {
                result[key] = number
                count += 1
            }
        }
        return count ? result : null
    }

    function cleanProfile(value) {
        if (typeof value !== "string") {
            return ""
        }
        const profile = value.trim().slice(0, 24)
        return profile && profile !== "__new__"
            && !/[\u0000-\u001f]/.test(profile) ? profile : ""
    }

    function cleanProfiles(value) {
        if (!Array.isArray(value)) {
            return []
        }
        const profiles = []
        const limit = Math.min(value.length, 32)
        for (let index = 0; index < limit; index += 1) {
            const profile = cleanProfile(value[index])
            if (profile && profiles.indexOf(profile) < 0) {
                profiles.push(profile)
            }
        }
        return profiles
    }

    function handleGraphCommand(command) {
        if (command.type === "graph.display.request") {
            broadcast(graphDisplayState())
            return true
        }
        if (command.type === "graph.display.select") {
            if (typeof command.surface_id === "string") {
                surfaceLayout.commitGraphSurface(command.surface_id)
            }
            return true
        }
        const graphId = cleanGraphId(command.graph_id)
        if (!graphId) {
            return true
        }
        if (command.type === "graph.selection.publish") {
            selectedGraphId = graphId
            broadcast({
                "schema": eventSchema,
                "type": "graph.selection",
                "graph_id": graphId
            })
            return true
        }
        if (command.type === "graph.state.request"
                || command.type === "graph.thinking.test") {
            broadcast({
                "schema": eventSchema,
                "type": "graph.command",
                "action": command.type === "graph.state.request"
                    ? "state.request" : "thinking.test",
                "graph_id": graphId
            })
            return true
        }
        if (command.type === "graph.profile.select") {
            const profile = cleanProfile(command.profile)
            if (profile) {
                broadcast({
                    "schema": eventSchema,
                    "type": "graph.command",
                    "action": "profile.select",
                    "graph_id": graphId,
                    "profile": profile
                })
            }
            return true
        }
        if (command.type === "graph.profile.create") {
            const profile = cleanProfile(command.profile)
            const tuning = cleanTuning(command.tuning)
            if (profile && tuning) {
                broadcast({
                    "schema": eventSchema,
                    "type": "graph.command",
                    "action": "profile.create",
                    "graph_id": graphId,
                    "profile": profile,
                    "tuning": tuning
                })
            }
            return true
        }
        if (command.type === "graph.tuning.preview"
                || command.type === "graph.tuning.save") {
            const tuning = cleanTuning(command.tuning)
            if (!tuning) {
                return true
            }
            broadcast({
                "schema": eventSchema,
                "type": "graph.command",
                "action": command.type === "graph.tuning.preview"
                    ? "tuning.preview" : "tuning.save",
                "graph_id": graphId,
                "tuning": tuning
            })
            return true
        }
        if (command.type !== "graph.state.publish") {
            return false
        }
        const tuning = cleanTuning(command.tuning)
        const defaultTuning = cleanTuning(command.default_tuning)
        const profile = cleanProfile(command.profile)
        const profiles = cleanProfiles(command.profiles)
        if (!tuning || !defaultTuning || !Array.isArray(command.fields)
                || command.fields.length > 64 || !profile
                || profiles.indexOf(profile) < 0) {
            return true
        }
        const state = {
            "schema": eventSchema,
            "type": "graph.state",
            "graph_id": graphId,
            "tuning": tuning,
            "default_tuning": defaultTuning,
            "fields": command.fields,
            "profile": profile,
            "profiles": profiles
        }
        graphStates = Object.assign({}, graphStates, {[graphId]: state})
        broadcast(state)
        return true
    }

    function handleWorkspaceCommand(command) {
        if (command.type === "workspace.state.request") {
            broadcast(workspaceState())
            return true
        }
        if (command.type === "workspace.grid.set") {
            if (surfaceLayout.commitPaneGridSize(command.pane_grid_size)) {
                broadcast(workspaceState())
            }
            return true
        }
        if (command.type === "workspace.tile.limit.set") {
            if (surfaceLayout.commitTileResizeLimitPercent(
                    command.tile_resize_limit_percent
            )) {
                broadcast(workspaceState())
            }
            return true
        }
        if (command.type === "workspace.oled.set") {
            if (surfaceLayout.commitOledSettings(
                    command.oled_mode_enabled,
                    command.oled_shift_distance_px,
                    command.oled_travel_duration_seconds,
                    command.oled_glow_rotation_hours
            )) {
                broadcast(workspaceState())
            }
            return true
        }
        if (command.type === "workspace.tiling.set") {
            if (surfaceLayout.commitWorkspaceTiling(
                    command.surface_id,
                    command.columns,
                    command.rows
            )) {
                broadcast(workspaceState())
            }
            return true
        }
        return false
    }

    function handleCommand(socket, text) {
        if (typeof text !== "string" || text.length < 2 || text.length > 65536) {
            return
        }
        let command
        try {
            command = JSON.parse(text)
        } catch (error) {
            return
        }
        if (!command || command.schema !== commandSchema) {
            return
        }
        if (typeof command.type === "string"
                && command.type.startsWith("window.")
                && handleWindowCommand(socket, command)) {
            return
        }
        if (typeof command.type === "string"
                && command.type.startsWith("workspace.")
                && handleWorkspaceCommand(command)) {
            return
        }
        if (typeof command.type === "string" && command.type.startsWith("graph.")
                && handleGraphCommand(command)) {
            return
        }
        if (typeof command.type === "string"
                && command.type.startsWith("pane.")
                && handlePaneCommand(socket, command)) {
            return
        }
        if (command.pane_id === "settings" && command.type === "pane.present"
                && command.selection && command.selection.kind === "settings"
                && ["graph", "input", "workspace", "connections", "ai-voice"].includes(command.selection.section)) {
            const placement = placementFor("settings")
            if (placement && presentPlacementOnSurface(placement, placement.surfaceId)) {
                settingsSelection = {kind: "settings", section: command.selection.section}
                settingsSelectionRevision += 1
                broadcast(settingsState())
            }
            return
        }
        if (command.pane_id !== "reader") {
            return
        }
        if (command.type === "pane.dismiss") {
            readerPlacement.dismiss()
            broadcast(readerState())
            return
        }
        if (command.type !== "pane.present") return
        const selection = cleanReaderSelection(command.selection)
        if (!selection) return
        readerSelection = selection
        presentPlacementOnSurface(readerPlacement, readerPlacement.surfaceId)
        broadcast(readerState())
    }

    function acceptClient(socket) {
        if (!socket || clients.length >= 32
                || socket.negotiatedSubprotocol !== subprotocol) {
            if (socket) {
                socket.active = false
            }
            return
        }
        clients = clients.concat([socket])
        socket.textMessageReceived.connect(message => handleCommand(socket, message))
        socket.statusChanged.connect(status => {
            if (status === WebSocket.Closed || status === WebSocket.Error) {
                removeClient(socket)
            }
        })
        send(socket, readerState())
        send(socket, settingsState())
        send(socket, knowledgeState())
        send(socket, graphDisplayState())
        send(socket, workspaceState())
        send(socket, dockState())
        send(socket, {
            "schema": eventSchema,
            "type": "graph.selection",
            "graph_id": selectedGraphId
        })
        for (const graphId of Object.keys(graphStates)) {
            send(socket, graphStates[graphId])
        }
        for (const surfaceId of Object.keys(windowStates)) {
            send(socket, windowStates[surfaceId])
        }
    }

    onKnowledgeVisibleChanged: broadcast(knowledgeState())
    onSessionLockedChanged: {
        lockGeneration += 1
        invalidateClickRequests("scene_unavailable")
        broadcast(workspaceState())
        if (sessionLocked) {
            moduleWindowBindings = ({})
            moduleRestorePending = null
        } else {
            observeModuleWindows()
        }
    }

    property Connections graphDisplayConnections: Connections {
        target: root.surfaceLayout
        function onGraphSurfaceIdChanged() {
            root.broadcast(root.graphDisplayState())
        }
        function onPaneGridSizeChanged() {
            root.broadcast(root.workspaceState())
        }
    }

    property WebSocketServer server: WebSocketServer {
        host: "127.0.0.1"
        port: 8768
        name: "Obsidience Shell"
        supportedSubprotocols: [root.subprotocol]
        listen: true
        accept: true

        onClientConnected: socket => root.acceptClient(socket)
        onErrorStringChanged: function() {
            if (root.server.errorString) {
                console.warn("Shell command server:", root.server.errorString)
            }
        }
    }
}
