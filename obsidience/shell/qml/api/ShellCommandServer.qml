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

    readonly property string commandSchema: "obsidience.shell.command.v1"
    readonly property string eventSchema: "obsidience.shell.event.v1"
    readonly property string subprotocol: "obsidience.shell.v1"
    property var readerSelection: null
    property var clients: []
    property var paneClients: []
    property var activePaneBySurface: ({})
    property var graphStates: ({})
    property var windowStates: ({})
    property var windowAdapterSocket: null
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

    function broadcastToPaneClients(message) {
        for (const socket of paneClients) {
            send(socket, message)
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

    function commitLocalDrag(socket, command) {
        const token = cleanDragToken(command.token)
        const placement = placementFor(command.pane_id)
        const surface = surfaceLayout.surface(command.source_surface_id)
        const rect = command.local_rect
        if (!token || !placement || !surface || !rect
                || placement.surfaceId !== command.source_surface_id
                || placement.revision !== command.expected_revision
                || !isNumber(rect.x) || !isNumber(rect.y)) {
            failPaneCommand(socket, "pane.drag.failed", token, "stale_commit")
            return
        }
        const x = surfaceLayout.clampPaneX(
            surface, placement.width, rect.x
        )
        const y = surfaceLayout.clampPaneY(
            surface, placement.height, rect.y
        )
        if (!placement.commitDrag(
                command.expected_revision, surface.id, x, y)) {
            failPaneCommand(socket, "pane.drag.failed", token, "stale_commit")
            return
        }
        broadcastToPaneClients({
            "schema": eventSchema,
            "type": "pane.drag.committed",
            "token": token,
            "pane": placement.record()
        })
    }

    function activatePane(command) {
        const placement = placementFor(command.pane_id)
        if (!placement || placement.open !== true
                || placement.surfaceId !== command.surface_id
                || placement.revision !== command.expected_revision) {
            return
        }
        const next = Object.assign({}, activePaneBySurface)
        next[placement.surfaceId] = placement.paneId
        activePaneBySurface = next
    }

    function deactivatePane(command) {
        const placement = placementFor(command.pane_id)
        if (!placement || placement.surfaceId !== command.surface_id
                || placement.revision !== command.expected_revision
                || activePaneBySurface[command.surface_id] !== placement.paneId) {
            return
        }
        const next = Object.assign({}, activePaneBySurface)
        delete next[command.surface_id]
        activePaneBySurface = next
    }

    function activePlacement(surfaceId) {
        const paneId = activePaneBySurface[surfaceId]
        const placement = placementFor(paneId)
        if (placement && placement.open === true
                && placement.surfaceId === surfaceId) {
            return placement
        }
        return null
    }

    function movePane(socket, placement, direction) {
        const source = placement
            ? surfaceLayout.surface(placement.surfaceId) : null
        if (!placement || !source || placement.open !== true
                || ["left", "right", "top", "bottom"].indexOf(direction) < 0) {
            failPaneCommand(socket, "pane.move.failed", "", "invalid")
            return
        }
        const route = surfaceLayout.moveRoute(
            source.id,
            direction,
            placement.x + placement.width / 2,
            placement.y + placement.height / 2,
            12
        )
        const destination = route
            ? surfaceLayout.surface(route.destination_id) : null
        if (!destination || destination.id === source.id) {
            failPaneCommand(socket, "pane.move.failed", "", "boundary")
            return
        }
        const width = Math.min(placement.width, destination.logical_width)
        const height = Math.min(
            placement.height,
            destination.logical_height - surfaceLayout.paneTopInset
        )
        let x = route.x - width / 2
        let y = route.y - height / 2
        if (route.destination_edge === "left") {
            x = 12
        } else if (route.destination_edge === "right") {
            x = destination.logical_width - width - 12
        } else if (route.destination_edge === "top") {
            y = surfaceLayout.paneTopInset
        } else {
            y = destination.logical_height - height - 12
        }
        x = surfaceLayout.clampPaneX(destination, width, x)
        y = surfaceLayout.clampPaneY(destination, height, y)
        if (!placement.commitGeometry(
                placement.revision,
                destination.id,
                x,
                y,
                width,
                height,
                paneWorkspace.nextZOrder(destination.id),
                null
        )) {
            failPaneCommand(socket, "pane.move.failed", "", "stale_commit")
            return
        }
        const next = Object.assign({}, activePaneBySurface)
        if (next[source.id] === placement.paneId) {
            delete next[source.id]
        }
        next[destination.id] = placement.paneId
        activePaneBySurface = next
        const event = {
            "schema": eventSchema,
            "type": "pane.moved",
            "pane": placement.record()
        }
        broadcastToPaneClients(event)
        if (paneClients.indexOf(socket) < 0) {
            send(socket, event)
        }
    }

    function tilePane(socket, placement, direction, translate) {
        const surface = placement
            ? surfaceLayout.surface(placement.surfaceId) : null
        if (!placement || !surface || placement.open !== true
                || ["left", "right", "top", "bottom"].indexOf(direction) < 0) {
            failPaneCommand(socket, "pane.tile.failed", "", "invalid")
            return
        }
        const result = surfaceLayout.tiledPaneRect(
            surface.id,
            {
                "x": placement.x,
                "y": placement.y,
                "width": placement.width,
                "height": placement.height
            },
            direction,
            placement.tileBounds,
            translate === true
        )
        if (!result) {
            failPaneCommand(socket, "pane.tile.failed", "", "invalid_geometry")
            return
        }
        if (result.changed && !placement.commitGeometry(
                placement.revision,
                surface.id,
                result.x,
                result.y,
                result.width,
                result.height,
                placement.zOrder,
                result.tile_bounds
        )) {
            failPaneCommand(socket, "pane.tile.failed", "", "stale_commit")
            return
        }
        const event = {
            "schema": eventSchema,
            "type": "pane.tiled",
            "pane": placement.record()
        }
        broadcastToPaneClients(event)
        if (paneClients.indexOf(socket) < 0) {
            send(socket, event)
        }
    }

    function handlePaneCommand(socket, command) {
        if (command.type === "pane.subscribe") {
            if (surfaceLayout.surface(command.surface_id)
                    && paneClients.indexOf(socket) < 0) {
                paneClients = paneClients.concat([socket])
            }
            return true
        }
        if (command.type === "pane.drag.commit") {
            commitLocalDrag(socket, command)
            return true
        }
        if (command.type === "pane.activate") {
            activatePane(command)
            return true
        }
        if (command.type === "pane.deactivate") {
            deactivatePane(command)
            return true
        }
        if (command.type === "pane.move_active") {
            const source = surfaceLayout.surface(command.source_surface_id)
            const direction = command.direction
            const placement = source ? activePlacement(source.id) : null
            if (!placement) {
                failPaneCommand(socket, "pane.move.failed", "", "no_active_pane")
                return true
            }
            movePane(socket, placement, direction)
            return true
        }
        if (command.type === "pane.tile_active"
                || command.type === "pane.tile_move_active") {
            const source = surfaceLayout.surface(command.source_surface_id)
            const direction = command.direction
            const placement = source ? activePlacement(source.id) : null
            if (!placement) {
                failPaneCommand(socket, "pane.tile.failed", "", "no_active_pane")
                return true
            }
            tilePane(
                socket,
                placement,
                direction,
                command.type === "pane.tile_move_active"
            )
            return true
        }
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
        paneClients = paneClients.filter(candidate => candidate !== socket)
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

    function cleanWindowState(command) {
        const surfaceId = typeof command.surface_id === "string"
            && surfaceLayout.surface(command.surface_id) ? command.surface_id : ""
        if (!surfaceId || !Number.isInteger(command.revision)
                || command.revision < 1 || !Array.isArray(command.windows)
                || command.windows.length > 256) {
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
            if (!windowId || !appId || ids[windowId]) {
                continue
            }
            ids[windowId] = true
            windows.push({
                "window_id": windowId,
                "app_id": appId,
                "title": cleanWindowText(candidate.title, 512) || appId,
                "pid": Number.isInteger(candidate.pid) && candidate.pid > 0
                    ? candidate.pid : 0,
                "minimized": candidate.minimized === true
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
            "windows": windows
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
            "reason": cleanWindowText(reason, 96)
        }
        if (socket) {
            send(socket, event)
        } else {
            broadcast(event)
        }
    }

    function handleWindowCommand(socket, command) {
        if (command.type === "window.adapter.subscribe") {
            if (windowAdapterSocket && windowAdapterSocket !== socket) {
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
        if (command.type !== "window.activate") {
            return false
        }
        const token = cleanDragToken(command.token)
        const surfaceId = cleanWindowText(command.surface_id, 32)
        const windowId = cleanWindowText(command.window_id, 128)
        const state = windowStates[surfaceId]
        const current = state && state.revision === command.expected_revision
            && state.windows.some(window => window.window_id === windowId)
        if (!token || !current || !windowAdapterSocket
                || windowAdapterSocket.status !== WebSocket.Open) {
            windowResult(socket, command, false, "stale_or_unavailable")
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
        if (command.pane_id !== "reader") {
            return
        }
        if (command.type === "pane.dismiss") {
            readerPlacement.dismiss()
            broadcast(readerState())
            return
        }
        const selection = command.selection
        if (command.type !== "pane.present" || !selection
                || (selection.kind !== "article" && selection.kind !== "source")) {
            return
        }
        const field = selection.kind === "article" ? "ref" : "key"
        if (typeof selection[field] !== "string") {
            return
        }
        const value = selection[field].trim()
        if (!value || value.length > 2048 || /[\u0000-\u001f]/.test(value)) {
            return
        }
        readerSelection = {
            "kind": selection.kind,
            [field]: value
        }
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
