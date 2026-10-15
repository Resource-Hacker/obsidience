pragma ComponentBehavior: Bound

import QtQml
import QtWebSockets
import ".."
import "../../workspace"

// The obsidience.shell.v1 command endpoint on 127.0.0.1:8768: transport,
// client authentication, dispatch and broadcast. Each command domain has one
// owner: PaneCommands (pane selection and Reader docking), WindowSceneRelay
// (the window adapter's Scene), GraphRelay (graph state and stream signalling)
// and WorkspaceCommands (workspace settings).
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
    property var clients: []
    // Sockets that presented the adapter credential; only these may subscribe.
    property var adapterClients: []
    property int lockGeneration: 0

    readonly property PaneCommands panes: PaneCommands { server: root }
    readonly property WindowSceneRelay scene: WindowSceneRelay { server: root }
    readonly property GraphRelay graph: GraphRelay { server: root }
    readonly property WorkspaceCommands workspace: WorkspaceCommands { server: root }

    function cleanDragToken(value) {
        return typeof value === "string"
            && /^[A-Za-z0-9._:-]{1,96}$/.test(value) ? value : ""
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

    // Callers get an explicit refusal instead of waiting out a timeout.
    function commandError(socket, command, reason) {
        const valid = command && typeof command === "object"
        send(socket, {"schema": eventSchema, "type": "error",
            "token": valid ? cleanDragToken(command.token) : "",
            "command_type": valid ? cleanWindowText(command.type, 64) : "",
            "reason": reason})
    }

    function removeClient(socket) {
        scene.removeClient(socket)
        graph.removeClient(socket)
        clients = clients.filter(candidate => candidate !== socket)
        adapterClients = adapterClients.filter(candidate => candidate !== socket)
    }

    function cleanWindowText(value, maximum) {
        if (typeof value !== "string") {
            return ""
        }
        const text = value.replace(/[\u0000-\u001f]/g, " ")
            .replace(/\s+/g, " ").trim()
        return text.slice(0, maximum)
    }

    function handleCommand(socket, text) {
        if (typeof text !== "string" || text.length < 2 || text.length > 65536) {
            commandError(socket, null, "malformed_command")
            return
        }
        let command
        try {
            command = JSON.parse(text)
        } catch (error) {
            commandError(socket, null, "malformed_command")
            return
        }
        if (!command || typeof command !== "object" || Array.isArray(command)
                || typeof command.type !== "string") {
            commandError(socket, null, "malformed_command")
            return
        }
        if (command.schema !== commandSchema) {
            commandError(socket, command, "unsupported_schema")
            return
        }
        if (command.type === "graph.stream") { graph.handleGraphStream(socket, command); return }
        if (typeof command.type === "string"
                && command.type.startsWith("window.")
                && scene.handleWindowCommand(socket, command)) {
            return
        }
        if (typeof command.type === "string"
                && command.type.startsWith("workspace.")
                && workspace.handleWorkspaceCommand(command)) {
            return
        }
        if (typeof command.type === "string" && command.type.startsWith("graph.")
                && graph.handleGraphCommand(socket, command)) {
            return
        }
        if (typeof command.type === "string"
                && command.type.startsWith("pane.")
                && panes.handleDockCommand(socket, command)) {
            return
        }
        if (!panes.handleSelection(socket, command)) {
            commandError(socket, command, "unknown_command")
        }
    }

    // Browsers can open this loopback socket with any subprotocol; only a
    // client that read a user-only runtime token may observe or command. The
    // separate adapter token (never served over HTTP) adds the adapter role.
    function clientRole(socket) {
        const match = /[?&]token=([0-9a-f]{64})(?:&|$)/.exec(String(socket.url))
        const token = match ? match[1] : ""
        if (token && token === ShellCommandToken.adapterValue) {
            return "adapter"
        }
        if (token && token === ShellCommandToken.value) {
            return "command"
        }
        console.warn("Shell command server: refused a client without the current token")
        return ""
    }

    function acceptClient(socket) {
        const role = socket && clients.length < 32
            && socket.negotiatedSubprotocol === subprotocol ? clientRole(socket) : ""
        if (!role) {
            if (socket) {
                socket.active = false
            }
            return
        }
        clients = clients.concat([socket])
        if (role === "adapter") {
            adapterClients = adapterClients.concat([socket])
        }
        socket.textMessageReceived.connect(message => handleCommand(socket, message))
        socket.statusChanged.connect(status => {
            if (status === WebSocket.Closed || status === WebSocket.Error) {
                removeClient(socket)
            }
        })
        send(socket, panes.readerState())
        send(socket, panes.settingsState())
        send(socket, panes.graphViewerState())
        send(socket, graph.knowledgeState())
        send(socket, graph.graphDisplayState())
        for (const view of ["memory", "code"])
            send(socket, {schema: eventSchema, type: "graph.viewer.state", view: view, settings: graph.providerGraphViews[view]})
        send(socket, workspace.workspaceState())
        send(socket, panes.dockState())
        send(socket, {
            "schema": eventSchema,
            "type": "graph.selection",
            "graph_id": graph.selectedGraphId
        })
        for (const graphId of Object.keys(graph.graphStates)) {
            send(socket, graph.graphStates[graphId])
        }
        for (const surfaceId of Object.keys(scene.windowStates)) {
            send(socket, scene.windowStates[surfaceId])
        }
    }

    onKnowledgeVisibleChanged: broadcast(graph.knowledgeState())
    onSessionLockedChanged: {
        lockGeneration += 1
        scene.invalidateClickRequests("scene_unavailable")
        broadcast(workspace.workspaceState())
        scene.sessionLockChanged()
    }

    property WebSocketServer listener: WebSocketServer {
        host: "127.0.0.1"
        port: 8768
        name: "Obsidience Shell"
        supportedSubprotocols: [root.subprotocol]
        listen: true
        accept: true

        onClientConnected: socket => root.acceptClient(socket)
        onErrorStringChanged: function() {
            if (root.listener.errorString) {
                console.warn("Shell command server:", root.listener.errorString)
            }
        }
    }
}
