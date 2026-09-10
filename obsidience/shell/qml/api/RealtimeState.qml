import QtQml
import QtWebSockets

QtObject {
    id: root

    // One read-only projection of the existing speech owner, shared by Surfaces.
    property bool connected: false
    property var state: ({})
    property var levels: []
    readonly property int levelLimit: 32
    signal transcriptUpdated()

    function applyState(payload, levelSample) {
        if (!payload || typeof payload !== "object") return
        const enabled = payload.enabled === true
        const level = typeof payload.input_level === "number"
            && isFinite(payload.input_level)
            ? Math.max(0, Math.min(1, payload.input_level)) : 0
        const transcript = payload.live_transcript
        state = {
            enabled: enabled,
            ready: payload.ready === true,
            proactive: payload.proactive === true,
            phase: typeof payload.phase === "string" ? payload.phase : "off",
            last_error: typeof payload.last_error === "string" ? payload.last_error : "",
            input_level: enabled ? level : 0,
            capture_active: enabled && payload.capture_active === true,
            user_speaking: enabled && payload.user_speaking === true,
            live_transcript: enabled && transcript && typeof transcript.text === "string"
                ? {text: transcript.text.slice(-4096), final: transcript.final === true} : null
        }
        if (!enabled || !state.ready) levels = []
        else if (levelSample) levels = levels.concat([level]).slice(-levelLimit)
    }

    function applyMessage(text) {
        if (typeof text !== "string" || text.length > 1048576) return
        let event
        try { event = JSON.parse(text) } catch (error) { return }
        if (!event || typeof event !== "object" || !event.state) return
        const previous = JSON.stringify(state.live_transcript)
        if (event.type === "state") levels = []
        applyState(event.state, event.type === "runtime" && event.reason === "input_level")
        if (event.type === "runtime" && !event.reason && state.live_transcript
                && state.live_transcript.text !== ""
                && JSON.stringify(state.live_transcript) !== previous) transcriptUpdated()
    }

    function disconnected() {
        connected = false
        levels = []
        state = Object.assign({}, state, {
            ready: false, phase: "disconnected", input_level: 0,
            capture_active: false, user_speaking: false, live_transcript: null,
            last_error: "Realtime connection unavailable."
        })
    }

    readonly property WebSocket socket: WebSocket {
        url: "ws://127.0.0.1:8765/ws/realtime"
        active: true
        onTextMessageReceived: message => root.applyMessage(message)
        onStatusChanged: status => {
            if (status === WebSocket.Open) {
                root.reconnect.stop()
                root.connected = true
            } else if (status === WebSocket.Closed || status === WebSocket.Error) {
                root.disconnected()
                root.reconnect.restart()
            }
        }
    }

    readonly property Timer reconnect: Timer {
        interval: 1000
        repeat: false
        onTriggered: {
            root.socket.active = false
            root.socket.active = true
        }
    }
}
