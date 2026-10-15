pragma ComponentBehavior: Bound

import QtQml
import QtWebSockets

// The window adapter's side of obsidience.shell.v1: the published Scene
// (application.state), module window restore, place/close/layout/activation
// relays, state refresh and the token-bound click/drag guard. Only the socket
// that subscribed with the adapter credential may publish or answer.
QtObject {
    id: root

    required property var server
    readonly property string eventSchema: server.eventSchema
    readonly property var surfaceLayout: server.surfaceLayout
    readonly property var dockLayout: server.dockLayout
    readonly property var panes: server.panes

    property var windowStates: ({})
    // Surface -> connector its monitor currently uses, as the adapter resolved it.
    property var resolvedOutputs: ({})
    property var moduleWindowBindings: ({})
    property var moduleRestorePending: null
    property int moduleRestoreSequence: 0
    property var windowAdapterSocket: null
    property var clickTokens: []
    property var clickRequests: []
    property var windowRefreshRequests: []
    readonly property int clickTokenLimit: 4096
    readonly property int clickRequestLifetimeMs: 6000

    function windowRefreshResult(socket, command, success, reason, revisions) {
        server.send(socket, {"schema": eventSchema, "type": "window.state.refresh.result",
            "token": command.token, "surface_id": "", "window_id": "",
            "success": success, "reason": reason, "revisions": revisions || {}})
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
            const windowId = server.cleanWindowText(candidate.window_id, 128)
            const appId = server.cleanWindowText(candidate.app_id, 256)
            const windowKind = candidate.window_kind === "module"
                ? "module" : candidate.window_kind === "application"
                    ? "application" : ""
            const paneId = windowKind === "module"
                ? cleanPaneId(candidate.pane_id) : ""
            const stableId = server.cleanWindowText(candidate.stable_id, 128)
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
                "title": server.cleanWindowText(candidate.title, 512) || appId,
                "pid": Number.isInteger(candidate.pid) && candidate.pid > 0
                    ? candidate.pid : 0,
                "minimized": candidate.minimized === true,
                "visible_on_workspace": candidate.visible_on_workspace === true,
                "window_kind": windowKind,
                "pane_id": paneId,
                "stable_id": stableId,
                "focus_rank": windowKind === "application"
                    && Number.isInteger(candidate.focus_rank)
                    && candidate.focus_rank >= 0 && candidate.focus_rank < 256
                    ? candidate.focus_rank : -1,
                "local_rect": localRect
            })
        }
        let activeWindowId = server.cleanWindowText(command.active_window_id, 128)
        if (!ids[activeWindowId]) {
            activeWindowId = ""
        }
        const surfaceRecord = surfaceLayout.surface(surfaceId)
        return {
            "schema": eventSchema,
            "type": "application.state",
            "surface_id": surfaceId,
            "revision": command.revision,
            "active_window_id": activeWindowId,
            "surface_awake": command.surface_awake,
            "logical_width": surfaceRecord.logical_width,
            "logical_height": surfaceRecord.logical_height,
            "windows": windows
        }
    }

    // Commit once every Surface has reported, so a renumbering is one record.
    function recordResolvedOutput(surfaceId, output) {
        resolvedOutputs = Object.assign({}, resolvedOutputs, {
            [surfaceId]: typeof output === "string" ? output : ""
        })
        if (surfaceLayout.surfaces.every(surface => surface.id in resolvedOutputs)) {
            surfaceLayout.commitSurfaceOutputs(resolvedOutputs)
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
        server.send(windowAdapterSocket, request)
        return true
    }

    // Only the adapter connection that received a restore can return its
    // receipt. Without that connection, retry once against fresh revisions
    // instead of leaving every later pane observation blocked.
    function abandonModuleRestore() {
        const pending = moduleRestorePending
        if (!pending) {
            return
        }
        const bindings = Object.assign({}, moduleWindowBindings)
        delete bindings[pending.pane_id]
        moduleWindowBindings = bindings
        moduleRestorePending = null
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
        const placement = panes.placementFor(pending.pane_id)
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
        if (server.sessionLocked || moduleRestorePending) {
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
            const placement = panes.placementFor(paneId)
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
            "token": server.cleanDragToken(command.token),
            "surface_id": server.cleanWindowText(command.surface_id, 32),
            "window_id": server.cleanWindowText(command.window_id, 128),
            "success": success === true,
            "reason": server.cleanWindowText(reason, 96),
            "post_revision": Number.isInteger(command.post_revision)
                && command.post_revision > 0 ? command.post_revision : 0
        }
        if (socket) {
            server.send(socket, event)
        } else {
            server.broadcast(event)
        }
    }

    function windowPlaceResult(socket, command, success, reason) {
        const event = {
            "schema": eventSchema,
            "type": "window.place.result",
            "token": server.cleanDragToken(command.token),
            "surface_id": server.cleanWindowText(command.surface_id, 32),
            "window_id": server.cleanWindowText(command.window_id, 128),
            "destination_surface_id": server.cleanWindowText(
                command.destination_surface_id, 32),
            "success": success === true,
            "reason": server.cleanWindowText(reason, 96),
            "post_revision": Number.isInteger(command.post_revision)
                && command.post_revision > 0 ? command.post_revision : 0,
            "verified_tile_bounds": success === true
                ? cleanTileBounds(command.verified_tile_bounds,
                    command.destination_surface_id) : null
        }
        if (socket) {
            server.send(socket, event)
        } else {
            server.broadcast(event)
        }
    }

    function windowLayoutResult(socket, command, success, reason) {
        const event = {
            "schema": eventSchema,
            "type": "window.layout.result",
            "token": server.cleanDragToken(command.token),
            "surface_id": server.cleanWindowText(command.surface_id, 32),
            "window_id": server.cleanWindowText(command.window_id, 128),
            "success": success === true,
            "reason": server.cleanWindowText(reason, 96)
        }
        if (socket) {
            server.send(socket, event)
        } else {
            server.broadcast(event)
        }
    }

    function windowCloseResult(socket, command, success, reason) {
        const event = {
            "schema": eventSchema,
            "type": "window.close.result",
            "token": server.cleanDragToken(command.token),
            "surface_id": server.cleanWindowText(command.surface_id, 32),
            "window_id": server.cleanWindowText(command.window_id, 128),
            "success": success === true,
            "reason": server.cleanWindowText(reason, 96)
        }
        if (socket) {
            server.send(socket, event)
        } else {
            server.broadcast(event)
        }
    }

    function hasExactFields(value, fields) {
        return value !== null && typeof value === "object" && !Array.isArray(value)
            && Object.keys(value).length === fields.length
            && fields.every(key => Object.prototype.hasOwnProperty.call(value, key))
    }

    function cleanClickWitness(value, drag) {
        const fields = ["stable_id", "pid", "process_start_time", "local_rect",
            "image_width", "image_height", "x", "y", "captured_at_unix_ns",
            "label"]
        if (drag) fields.push("drag")
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
        if (drag && (!hasExactFields(value.drag, ["x", "y", "duration_ms"])
                || !Number.isFinite(value.drag.x) || !Number.isFinite(value.drag.y)
                || value.drag.x < 0 || value.drag.x >= value.image_width
                || value.drag.y < 0 || value.drag.y >= value.image_height
                || !Number.isInteger(value.drag.duration_ms)
                || value.drag.duration_ms < 200 || value.drag.duration_ms > 1000)) {
            return null
        }
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
        const token = server.cleanDragToken(value)
        return token && !/[^A-Za-z0-9._:-]/.test(token) ? token : ""
    }

    function windowClickResult(socket, command, success, reason, delivery) {
        server.send(socket, {
            "schema": eventSchema, "type": command.type === "window.drag"
                ? "window.drag.result" : "window.click.result",
            "token": cleanClickToken(command.token),
            "surface_id": server.cleanWindowText(command.surface_id, 32),
            "window_id": server.cleanWindowText(command.window_id, 128),
            "success": success === true,
            "reason": server.cleanWindowText(reason, 96),
            "delivery": delivery
        })
    }

    function clickRequestOwned(pending) {
        if (!pending || server.sessionLocked || pending.generation !== server.lockGeneration
                || Date.now() < pending.createdAt
                || Date.now() - pending.createdAt >= clickRequestLifetimeMs
                || pending.socket.status !== WebSocket.Open
                || server.clients.indexOf(pending.socket) < 0
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
        if (["window.click", "window.drag", "window.click.guard",
                "window.click.result", "window.drag.result"].indexOf(type) < 0) {
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
            server.send(socket, {"schema": eventSchema, "type": "window.click.guard.result",
                "token": token, "allowed": allowed === true})
            return true
        }
        if (type === "window.click.result" || type === "window.drag.result") {
            if (!pending || socket !== windowAdapterSocket || socket !== pending.adapter
                    || command.token !== token || type !== pending.command.type + ".result"
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
        const witness = cleanClickWitness(command.witness, type === "window.drag")
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
            "command": command, "generation": server.lockGeneration, "createdAt": Date.now()}
        if (!clickRequestCurrent(candidate)) {
            windowClickResult(socket, command, false,
                server.sessionLocked ? "scene_unavailable" : "stale_or_unavailable", "not_dispatched")
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
        if (clickRequests.length >= 1) {
            windowClickResult(socket, command, false, "click_busy", "not_dispatched")
            return true
        }
        clickRequests = clickRequests.concat([candidate])
        server.send(windowAdapterSocket, {
            "schema": eventSchema, "type": "window.click.request", "token": token,
            "surface_id": command.surface_id, "window_id": command.window_id,
            "expected_revision": command.expected_revision, "witness": witness,
            "lock_generation": server.lockGeneration
        })
        return true
    }

    function handleWindowRefresh(socket, command) {
        if (command.type !== "window.state.refresh" && command.type !== "window.state.refresh.result")
            return false
        if (command.type === "window.state.refresh.result") {
            const pending = windowRefreshRequests.find(item => item.command.token === command.token)
            if (!pending || socket !== windowAdapterSocket || pending.adapter !== socket)
                return true
            windowRefreshRequests = windowRefreshRequests.filter(item => item !== pending)
            const revisions = command.revisions
            const surfaces = ["samsung", "usb-c", "dp-4"]
            const valid = hasExactFields(command, ["schema", "type", "token", "surface_id", "window_id",
                    "success", "reason", "revisions"])
                && command.surface_id === "" && command.window_id === ""
                && command.success === true && typeof command.reason === "string"
                && revisions && typeof revisions === "object" && !Array.isArray(revisions)
                && hasExactFields(revisions, surfaces)
                && surfaces.every(id => Number.isSafeInteger(revisions[id]) && revisions[id] > 0
                    && windowStates[id] && windowStates[id].revision >= revisions[id])
                && Date.now() >= pending.createdAt && Date.now() - pending.createdAt <= 5000
                && pending.generation === server.lockGeneration && !server.sessionLocked
            windowRefreshResult(pending.socket, pending.command, valid,
                valid ? "" : "refresh_unavailable", valid ? revisions : {})
            return true
        }
        const token = server.cleanDragToken(command.token)
        if (!token || !hasExactFields(command, ["schema", "type", "token", "surface_id", "window_id"])
                || command.surface_id !== "" || command.window_id !== "") {
            windowRefreshResult(socket, command, false, "invalid_refresh", {})
            return true
        }
        windowRefreshRequests = windowRefreshRequests.filter(item =>
            Date.now() - item.createdAt <= 5000)
        if (server.sessionLocked || !windowAdapterSocket || windowAdapterSocket.status !== WebSocket.Open
                || windowRefreshRequests.length >= 32
                || windowRefreshRequests.some(item => item.command.token === token)) {
            windowRefreshResult(socket, command, false, "refresh_unavailable", {})
            return true
        }
        windowRefreshRequests = windowRefreshRequests.concat([{
            "socket": socket, "adapter": windowAdapterSocket, "command": command,
            "generation": server.lockGeneration, "createdAt": Date.now()}])
        server.send(windowAdapterSocket, {"schema": eventSchema, "type": "window.state.refresh.request",
            "token": token, "surface_id": "", "window_id": ""})
        return true
    }

    function handleWindowCommand(socket, command) {
        if (handleWindowRefresh(socket, command)) return true
        if (handleClickCommand(socket, command)) {
            return true
        }
        if (command.type === "window.adapter.subscribe") {
            if (server.adapterClients.indexOf(socket) < 0) {
                server.commandError(socket, command, "adapter_credential_required")
                return true
            }
            if (windowAdapterSocket && windowAdapterSocket !== socket) {
                invalidateClickRequests("shell_scene_command_unavailable")
                windowAdapterSocket.active = false
                abandonModuleRestore()
            }
            windowAdapterSocket = socket
            windowStates = ({})
            resolvedOutputs = ({})
            return true
        }
        if (command.type === "window.state.publish") {
            if (socket !== windowAdapterSocket) {
                server.commandError(socket, command, "not_window_adapter")
                return true
            }
            const state = cleanWindowState(command)
            if (!state) {
                server.commandError(socket, command, "invalid_window_state")
                return true
            }
            windowStates = Object.assign(
                {}, windowStates, {[state.surface_id]: state}
            )
            recordResolvedOutput(state.surface_id, command.output)
            settlePendingModuleRestore()
            observeModuleWindows()
            server.broadcast(state)
            return true
        }
        if (command.type === "window.activation.result") {
            if (socket !== windowAdapterSocket || !server.cleanDragToken(command.token)) {
                return true
            }
            windowResult(
                null, command, command.success === true,
                command.success === true ? "" : command.reason
            )
            return true
        }
        if (command.type === "window.layout.result") {
            if (socket !== windowAdapterSocket || !server.cleanDragToken(command.token)) {
                return true
            }
            windowLayoutResult(
                null, command, command.success === true,
                command.success === true ? "" : command.reason
            )
            return true
        }
        if (command.type === "window.place.result") {
            if (socket !== windowAdapterSocket || !server.cleanDragToken(command.token)) {
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
                    || !server.cleanDragToken(command.token)) {
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
            if (socket !== windowAdapterSocket || !server.cleanDragToken(command.token)) {
                return true
            }
            windowCloseResult(
                null, command, command.success === true,
                command.success === true ? "" : command.reason
            )
            return true
        }
        if (command.type === "window.close_active") {
            const token = server.cleanDragToken(command.token)
            const surfaceId = server.cleanWindowText(command.source_surface_id, 32)
            const state = windowStates[surfaceId]
            const windowId = state ? state.active_window_id : ""
            if (!token || !surfaceLayout.surface(surfaceId)) {
                windowCloseResult(socket, command, false, "invalid")
                return true
            }
            if (server.sessionLocked) {
                windowCloseResult(socket, command, false, "scene_unavailable")
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
                const placement = panes.placementFor(current.pane_id)
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
            server.send(windowAdapterSocket, {
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
            const token = server.cleanDragToken(command.token)
            const surfaceId = server.cleanWindowText(command.source_surface_id, 32)
            const action = server.cleanWindowText(command.action, 16)
            const direction = server.cleanWindowText(command.direction, 16)
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
            if (server.sessionLocked) {
                windowLayoutResult(socket, command, false, "scene_unavailable")
                return true
            }
            const current = state && windowId
                && state.windows.some(window => window.window_id === windowId)
            if (!current || !windowAdapterSocket
                    || windowAdapterSocket.status !== WebSocket.Open) {
                windowLayoutResult(socket, command, false, "stale_or_unavailable")
                return true
            }
            server.send(windowAdapterSocket, {
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
            const token = server.cleanDragToken(command.token)
            const surfaceId = server.cleanWindowText(command.surface_id, 32)
            const windowId = server.cleanWindowText(command.window_id, 128)
            const destinationSurfaceId = server.cleanWindowText(
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
            if (server.sessionLocked) {
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
            server.send(windowAdapterSocket, {
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
        const token = server.cleanDragToken(command.token)
        const surfaceId = server.cleanWindowText(command.surface_id, 32)
        const windowId = server.cleanWindowText(command.window_id, 128)
        const state = windowStates[surfaceId]
        const current = state && state.revision === command.expected_revision
            && state.windows.some(window => window.window_id === windowId)
        if (!token) {
            windowResult(socket, command, false, "stale_scene")
            return true
        }
        if (server.sessionLocked) {
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
        server.send(windowAdapterSocket, {
            "schema": eventSchema,
            "type": "window.activation.request",
            "token": token,
            "surface_id": surfaceId,
            "window_id": windowId,
            "expected_revision": command.expected_revision
        })
        return true
    }

    // Requests relayed through a departing socket get an explicit refusal.
    function removeClient(socket) {
        for (const pending of windowRefreshRequests) {
            if (pending.adapter === socket && pending.socket !== socket)
                windowRefreshResult(pending.socket, pending.command, false, "refresh_unavailable", {})
        }
        windowRefreshRequests = windowRefreshRequests.filter(pending =>
            pending.socket !== socket && pending.adapter !== socket)
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
            abandonModuleRestore()
        }
    }

    // Called by the server after a lock change has invalidated pending clicks
    // and published the new workspace state.
    function sessionLockChanged() {
        if (server.sessionLocked) {
            moduleWindowBindings = ({})
            moduleRestorePending = null
        } else {
            observeModuleWindows()
        }
    }
}
