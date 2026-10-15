pragma ComponentBehavior: Bound

import QtQml

// Graph traffic on obsidience.shell.v1: the graph Surface and its visibility,
// the selected graph, published graph state, profile/tuning commands for the
// graph stages, provider viewer settings and graph.stream WebRTC signalling.
QtObject {
    id: root

    required property var server
    readonly property string eventSchema: server.eventSchema
    readonly property var surfaceLayout: server.surfaceLayout

    property var graphStates: ({})
    property string selectedGraphId: "main"
    property var providerGraphViews: ({memory: {}, code: {}})
    property var graphStreams: []

    function knowledgeState() {
        return {
            "schema": eventSchema,
            "type": "surface.state",
            "surface": {
                "surface_id": surfaceLayout.graphSurfaceId,
                "visible": server.knowledgeVisible
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

    // Only signaling crosses the Shell. Canvas video and presentation controls
    // travel directly between a stage and its viewers; no desktop capture/input.
    function removeGraphStream(id) {
        const removed = graphStreams.find(peer => peer.id === id)
        if (!removed) return
        graphStreams = graphStreams.filter(peer => peer.id !== id)
        for (const peer of graphStreams.filter(peer => peer.view === removed.view && peer.role !== removed.role))
            server.send(peer.socket, {schema: eventSchema, type: "graph.stream", action: "left", to: peer.id, id: id})
    }

    function handleGraphStream(socket, command) {
        if (typeof command.id !== "string" || !/^[a-f0-9-]{36}$/.test(command.id)
                || !["join", "leave", "signal"].includes(command.action)) {
            server.commandError(socket, command, "malformed_command")
            return
        }
        const current = graphStreams.find(peer => peer.id === command.id && peer.socket === socket)
        if (command.action === "leave") { if (current) removeGraphStream(current.id); return }
        if (command.action === "join") {
            if (current || graphStreams.length >= 24 || !["knowledge", "library", "memory", "code", "knowledge:Darwin", "knowledge:Alexandria", "knowledge:Heimdall"].includes(command.view)
                    || !["stage", "viewer"].includes(command.role)) return
            if (graphStreams.some(peer => peer.id === command.id)) return
            if (command.role === "stage" && graphStreams.some(peer => peer.view === command.view && peer.role === "stage")) {
                server.send(socket, {schema: eventSchema, type: "graph.stream", action: "rejected", to: command.id, reason: "A stage already owns this graph"})
                return
            }
            const joined = {id: command.id, view: command.view, role: command.role, socket: socket}
            graphStreams = graphStreams.concat([joined])
            for (const peer of graphStreams.filter(peer => peer.view === joined.view && peer.role !== joined.role)) {
                server.send(peer.socket, {schema: eventSchema, type: "graph.stream", action: "peer", to: peer.id, id: joined.id, role: joined.role})
                server.send(socket, {schema: eventSchema, type: "graph.stream", action: "peer", to: joined.id, id: peer.id, role: peer.role})
            }
            return
        }
        if (command.action !== "signal" || !current) return
        const target = graphStreams.find(peer => peer.id === command.to && peer.view === current.view && peer.role !== current.role)
        const signal = command.signal
        if (!target || !signal || typeof signal !== "object" || Array.isArray(signal)) return
        const sdp = ["offer", "answer"].includes(signal.type) && typeof signal.sdp === "string" && signal.sdp.length <= 48000
        const ice = typeof signal.candidate === "string" && signal.candidate.length <= 4096
        if (!sdp && !ice) return
        server.send(target.socket, {schema: eventSchema, type: "graph.stream", action: "signal", to: target.id, id: current.id,
            signal: sdp ? {type: signal.type, sdp: signal.sdp}
                : {candidate: signal.candidate, sdpMid: signal.sdpMid, sdpMLineIndex: signal.sdpMLineIndex}})
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
            if (count >= 96 || !/^[A-Za-z][A-Za-z0-9_]{0,47}$/.test(key)) {
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

    function handleGraphCommand(socket, command) {
        if (command.type === "graph.viewer.configure" && ["memory", "code"].includes(command.view)) {
            const supplied = command.settings || {}
            const settings = Object.assign({}, providerGraphViews[command.view])
            if (typeof supplied.follow === "boolean") settings.follow = supplied.follow
            if (command.view === "code" && typeof supplied.allSymbols === "boolean")
                settings.allSymbols = supplied.allSymbols
            if (command.view === "memory") {
                if (typeof supplied.bank === "string" && /^obsidience-[a-f0-9]{32}$/.test(supplied.bank))
                    settings.bank = supplied.bank
                if (["all", "world", "experience", "observation"].includes(supplied.memoryType))
                    settings.memoryType = supplied.memoryType
            }
            const next = Object.assign({}, providerGraphViews)
            next[command.view] = settings
            providerGraphViews = next
            const eventSettings = Object.assign({}, settings)
            if (supplied.refresh === true) eventSettings.refresh = true
            if (supplied.fit === true) eventSettings.fit = true
            server.broadcast({schema: eventSchema, type: "graph.viewer.state", view: command.view, settings: eventSettings})
            return true
        }
        if (command.type === "graph.display.request") {
            server.broadcast(graphDisplayState())
            return true
        }
        if (command.type === "graph.display.select") {
            if (typeof command.surface_id === "string") {
                surfaceLayout.commitGraphSurface(command.surface_id)
            }
            return true
        }
        if (["graph.selection.publish", "graph.state.request", "graph.thinking.test",
                "graph.profile.select", "graph.profile.create", "graph.tuning.preview",
                "graph.tuning.save", "graph.state.publish"].indexOf(command.type) < 0) {
            return false
        }
        const graphId = cleanGraphId(command.graph_id)
        if (!graphId) {
            server.commandError(socket, command, "invalid_graph_id")
            return true
        }
        if (command.type === "graph.selection.publish") {
            selectedGraphId = graphId
            server.broadcast({
                "schema": eventSchema,
                "type": "graph.selection",
                "graph_id": graphId
            })
            return true
        }
        if (command.type === "graph.state.request"
                || command.type === "graph.thinking.test") {
            server.broadcast({
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
                server.broadcast({
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
                server.broadcast({
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
            server.broadcast({
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
                || command.fields.length > 96 || !profile
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
        server.broadcast(state)
        return true
    }

    function removeClient(socket) {
        for (const peer of graphStreams.filter(peer => peer.socket === socket)) removeGraphStream(peer.id)
    }

    property Connections graphDisplayConnections: Connections {
        target: root.surfaceLayout
        function onGraphSurfaceIdChanged() {
            root.server.broadcast(root.graphDisplayState())
        }
    }
}
