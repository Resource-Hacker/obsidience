pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtWebSockets
import "../../components/visual"

Rectangle {
    id: root

    required property var realtime
    property bool voiceRequestPending: false
    property string voiceError: ""
    readonly property var voice: realtime.state
    readonly property string wakeWord: voice.wake_word || "Computer"
    readonly property string voiceMode: voice.mode || "off"
    readonly property bool voiceReady: voice.ready === true && realtime.connected
    readonly property bool recognizing: voiceReady && voice.command_open === true
        && (voice.capture_active === true || voice.user_speaking === true
            || (voice.live_transcript && voice.live_transcript.final !== true))
    readonly property string recognizedText: voice.live_transcript && voice.live_transcript.final !== true
        ? String(voice.live_transcript.text || "") : ""
    property var turns: []
    property string draft: ""
    property string conversationId: ""
    property var contextUsage: null
    property int compactAt: 80
    property bool busy: false
    property string activeTurnId: ""
    property bool acceptingClarification: false
    property bool connected: false
    property bool resetting: false
    property string socketError: ""

    color: "#b302080e"
    clip: true

    function changeVoice(payload) {
        if (voiceRequestPending || !realtime.connected) return
        voiceRequestPending = true
        voiceError = ""
        const xhr = new XMLHttpRequest()
        xhr.open("PATCH", "http://127.0.0.1:8765/api/realtime/mode")
        xhr.setRequestHeader("Content-Type", "application/json")
        xhr.onreadystatechange = function() {
            if (!root || xhr.readyState !== XMLHttpRequest.DONE) return
            root.voiceRequestPending = false
            if (xhr.status < 200 || xhr.status >= 300) {
                root.voiceError = "Voice could not change mode."
                try { root.voiceError = JSON.parse(xhr.responseText).detail || root.voiceError } catch (error) {}
            }
        }
        xhr.send(JSON.stringify(payload))
    }

    function voiceStatus() {
        if (voiceError || voice.last_error) return voiceError || voice.last_error
        if (!realtime.connected) return "Voice reconnecting…"
        if (voiceMode === "off") return "Microphone off"
        if (voice.phase === "suspended") return "Voice paused while another agent finishes"
        if (!voiceReady) return "Preparing voice…"
        if (recognizing) return "Listening to your command"
        if (busy) return "Executive is working"
        if (voice.executive && voice.executive.state === "busy") return "An agent is working · voice available"
        if (voice.executive && voice.executive.state === "unavailable")
            return "Listening · Executive will prepare on your next command"
        if (!voice.executive || !voice.executive.warm) return "Warming Executive…"
        return voiceMode === "wake" ? "Ready · say " + wakeWord + ", then your command" : "Ready · speak naturally"
    }

    function mergeTurn(turn) {
        if (!turn || typeof turn.id !== "string") {
            return
        }
        const merged = []
        let replaced = false
        for (const current of turns) {
            if (current.id === turn.id) {
                merged.push(turn)
                replaced = true
            } else {
                merged.push(current)
            }
        }
        if (!replaced) {
            merged.push(turn)
        }
        merged.sort((left, right) => Number(left.sequence) - Number(right.sequence))
        turns = merged
    }

    function applyMessage(text) {
        if (typeof text !== "string" || text.length > 1048576) {
            return
        }
        let message
        try {
            message = JSON.parse(text)
        } catch (error) {
            return
        }
        if (!message || typeof message.type !== "string") {
            return
        }
        if (message.type === "history"
                && typeof message.conversation_id === "string"
                && Array.isArray(message.turns)) {
            conversationId = message.conversation_id
            const history = []
            for (const turn of message.turns) {
                if (turn && typeof turn.id === "string") {
                    const existing = history.findIndex(item => item.id === turn.id)
                    if (existing >= 0) {
                        history[existing] = turn
                    } else {
                        history.push(turn)
                    }
                }
            }
            history.sort((left, right) => Number(left.sequence) - Number(right.sequence))
            turns = history
            resetting = false
        } else if (message.type === "turn" && message.turn
                && message.turn.conversation_id === conversationId) {
            mergeTurn(message.turn)
        } else if (message.type === "context"
                && message.conversation_id === conversationId) {
            contextUsage = {
                "conversation_id": message.conversation_id,
                "used_tokens": Number(message.used_tokens ?? 0),
                "count_method": String(message.count_method || "unavailable"),
                "measurement_scope": String(message.measurement_scope || ""),
                "capacity_tokens": Number(message.capacity_tokens ?? 0),
                "percent": Number(message.percent ?? 0),
                "compact_at": Number(message.compact_at ?? 80),
                "compacting": Boolean(message.compacting ?? false)
            }
            compactAt = contextUsage.compact_at
        } else if (message.type === "start") {
            busy = true
        } else if (message.type === "end") {
            busy = false
            acceptingClarification = false
            activeTurnId = ""
        } else if (message.type === "active_turn" && message.conversation_id === conversationId) {
            activeTurnId = typeof message.turn_id === "string" ? message.turn_id : ""
            acceptingClarification = Boolean(message.accepting_clarification) && activeTurnId.length > 0
            busy = activeTurnId.length > 0
        } else if (message.type === "error") {
            socketError = String(message.text || "Request failed")
        } else if (message.type === "steering") {
            socketError = ""
        }
    }

    function canMutate() {
        return connected && !busy && !resetting
            && chatSocket.status === WebSocket.Open
    }

    function sendDraft() {
        const clean = draft.trim()
        const clarify = busy && acceptingClarification && connected && !resetting
            && chatSocket.status === WebSocket.Open
        if (!clean || (!canMutate() && !clarify)) {
            return
        }
        chatSocket.sendTextMessage(JSON.stringify({
            "type": clarify ? "steer" : "message",
            "expected_turn_id": clarify ? activeTurnId : "",
            "text": clean,
            "source": "text"
        }))
        socketError = ""
        draft = ""
        busy = true
    }

    function newConversation() {
        if (!canMutate()) {
            return
        }
        chatSocket.sendTextMessage(JSON.stringify({
            "type": "new_conversation"
        }))
        resetting = true
    }

    function setCompactThreshold(percent) {
        if (!canMutate() || (contextUsage && contextUsage.compacting)) {
            return
        }
        chatSocket.sendTextMessage(JSON.stringify({
            "type": "set_compact_threshold",
            "percent": percent
        }))
        compactAt = percent
    }

    function compactNow() {
        if (!canMutate() || (contextUsage && contextUsage.compacting)) {
            return
        }
        chatSocket.sendTextMessage(JSON.stringify({"type": "compact"}))
        if (contextUsage) {
            const next = Object.assign({}, contextUsage)
            next.compacting = true
            contextUsage = next
        }
    }

    Rectangle {
        id: header

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 42
        color: "#33071119"

        Text {
            anchors.left: parent.left
            anchors.leftMargin: 16
            anchors.verticalCenter: parent.verticalCenter
            text: root.connected ? "EXECUTIVE · VOICE & CHAT" : "CHAT RECONNECTING"
            color: root.connected ? "#8067e8f9" : "#99fcd34d"
            font.family: "JetBrains Mono"
            font.pixelSize: 9
            font.letterSpacing: 1.5
        }

        GlowButton {
            id: newConversationButton

            anchors.right: parent.right
            anchors.rightMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            width: 154
            height: 28
            enabled: root.canMutate()
            text: "+  NEW CONVERSATION"
            foreground: "#a5f3fc"
            idleBorderOpacity: 0.20
            idleTextOpacity: 0.60
            disabledOpacity: 0.35
            textPixelSize: 10
            textLetterSpacing: 1.2
            onClicked: root.newConversation()
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: "#2467e8f9"
        }
    }

    Rectangle {
        id: voicePanel
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: header.bottom
        height: 86
        color: "#4d071119"

        Row {
            id: voiceModes
            x: 12
            y: 10
            width: parent.width - 24
            height: 30
            spacing: 6

            Repeater {
                model: [{mode: "wake", label: "WAKE WORD"},
                        {mode: "realtime", label: "REALTIME"}, {mode: "off", label: "MUTE"}]
                delegate: GlowButton {
                    required property var modelData
                    width: (voiceModes.width - 12) / 3
                    height: 30
                    text: modelData.label
                    selected: root.voiceMode === modelData.mode
                    enabled: root.realtime.connected && !root.voiceRequestPending
                        && root.voice.phase !== "stopping" && root.voice.phase !== "starting"
                    foreground: modelData.mode === "off" ? "#fcd34d" : "#a5f3fc"
                    textPixelSize: 10
                    textLetterSpacing: 1
                    idleBorderOpacity: 0.22
                    idleTextOpacity: 0.60
                    selectedFillOpacity: 0.16
                    onClicked: root.changeVoice({mode: modelData.mode})
                }
            }
        }

        Text {
            anchors.left: parent.left
            anchors.leftMargin: 14
            anchors.right: proactive.visible ? proactive.left : parent.right
            anchors.rightMargin: 12
            y: 49
            text: root.voiceStatus()
            color: root.voiceError || root.voice.last_error ? "#fcd34d" : "#99a5f3fc"
            font.family: "JetBrains Mono"
            font.pixelSize: 10
            wrapMode: Text.Wrap
        }

        GlowButton {
            id: proactive
            anchors.right: parent.right
            anchors.rightMargin: 12
            y: 46
            width: 100
            height: 25
            visible: root.voiceMode === "realtime"
            text: "PROACTIVE"
            selected: root.voice.proactive === true
            enabled: root.voiceReady && !root.voiceRequestPending
            textPixelSize: 8
            foreground: "#fcd34d"
            idleTextOpacity: 0.5
            onClicked: root.changeVoice({proactive: !root.voice.proactive})
        }
    }

    ListView {
        id: transcript

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: voicePanel.bottom
        anchors.bottom: composer.top
        anchors.margins: 8
        clip: true
        spacing: 3
        model: root.turns
        boundsBehavior: Flickable.StopAtBounds
        onCountChanged: Qt.callLater(positionViewAtEnd)

        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
        }

        delegate: Item {
            id: turnRow

            required property var modelData
            width: transcript.width
            height: turnBubble.height + 8

            Rectangle {
                id: turnBubble

                width: Math.max(150, turnRow.width * 0.92)
                height: turnText.implicitHeight + 20
                x: turnRow.modelData.role === "user"
                    ? turnRow.width - width : 0
                radius: 8
                color: turnRow.modelData.role === "user"
                    ? "#1c22d3ee" : "#c4051018"
                border.width: 1
                border.color: turnRow.modelData.role === "user"
                    ? "#5267e8f9" : "#2467e8f9"

                Text {
                    id: turnText

                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 10
                    text: String(turnRow.modelData.text || "…")
                    textFormat: Text.MarkdownText
                    wrapMode: Text.Wrap
                    color: turnRow.modelData.role === "user" ? "#e6faff" : "#d2edf2"
                    linkColor: "#67e8f9"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 12
                    lineHeight: 1.35
                    lineHeightMode: Text.ProportionalHeight
                }
            }
        }

        Text {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 10
            visible: root.turns.length === 0
            text: root.connected
                ? "Say " + root.wakeWord + " followed by your command, or type below. Realtime keeps the conversation open without repeating the name."
                : (root.socketError || "Connecting to Executive chat…")
            color: "#667dd3fc"
            wrapMode: Text.Wrap
            font.family: "JetBrains Mono"
            font.pixelSize: 11
            lineHeight: 1.4
            lineHeightMode: Text.ProportionalHeight
        }

        footer: Item {
            width: transcript.width
            height: root.recognizing ? liveCommand.implicitHeight + 18 : 0
            visible: root.recognizing
            Column {
                id: liveCommand
                x: 12
                width: parent.width - 24
                spacing: 8
                InputWaveform {
                    width: parent.width
                    height: 22
                    levels: root.realtime.levels
                    capturing: root.recognizing
                }
                Text {
                    width: parent.width
                    text: root.recognizedText || "Listening…"
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    color: "#e6faff"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 12
                }
            }
        }
    }

    Connections {
        target: root.realtime
        function onTranscriptUpdated() { transcript.positionViewAtEnd() }
    }

    Text {
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: composer.top
        anchors.margins: 10
        visible: root.socketError.length > 0
        text: root.socketError
        color: "#fcd34d"
        font.pixelSize: 11
        wrapMode: Text.Wrap
        z: 2
    }

    Rectangle {
        id: composer

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        height: 112
        color: "#66030a10"
        border.width: 1
        border.color: "#2467e8f9"

        Text {
            id: immediateLabel

            anchors.left: parent.left
            anchors.leftMargin: 10
            anchors.top: parent.top
            anchors.topMargin: 9
            text: "CONTEXT"
            color: "#667dd3fc"
            font.family: "JetBrains Mono"
            font.pixelSize: 8
            font.letterSpacing: 1.0
        }

        Rectangle {
            id: contextTrack

            anchors.left: immediateLabel.right
            anchors.right: contextPercent.left
            anchors.leftMargin: 10
            anchors.rightMargin: 8
            anchors.verticalCenter: immediateLabel.verticalCenter
            height: 4
            radius: 2
            color: "#b0032230"

            Rectangle {
                width: parent.width * Math.max(0, Math.min(
                    100,
                    root.contextUsage && root.contextUsage.count_method === "runtime"
                        ? Number(root.contextUsage.percent) : 0
                )) / 100
                height: parent.height
                radius: 2
                color: "#9967e8f9"
            }
        }

        Text {
            id: contextPercent

            anchors.right: compactLabel.left
            anchors.rightMargin: 12
            anchors.verticalCenter: immediateLabel.verticalCenter
            width: 34
            text: !root.contextUsage || root.contextUsage.count_method !== "runtime" ? "—"
                : (root.contextUsage.measurement_scope === "native_session" ? "" : "~")
                    + Math.round(Number(root.contextUsage.percent)) + "%"
            color: "#667dd3fc"
            font.family: "JetBrains Mono"
            font.pixelSize: 8
        }

        Text {
            id: compactLabel

            anchors.right: thresholdBox.left
            anchors.rightMargin: 6
            anchors.verticalCenter: immediateLabel.verticalCenter
            text: "COMPACT AT"
            color: "#4d7dd3fc"
            font.family: "JetBrains Mono"
            font.pixelSize: 8
        }

        GlowComboBox {
            id: thresholdBox

            anchors.right: parent.right
            anchors.rightMargin: 10
            anchors.top: parent.top
            anchors.topMargin: 4
            width: 65
            height: 25
            model: [60, 70, 80, 90]
            currentIndex: model.indexOf(root.compactAt)
            enabled: root.canMutate() && !(root.contextUsage && root.contextUsage.compacting)
            fieldColor: "#03101a"
            foreground: "#cffafe"
            idleBorderOpacity: 0.15
            textOpacity: 0.65
            disabledOpacity: 0.35
            textPixelSize: 9
            displayText: currentIndex >= 0 ? String(model[currentIndex]) + "%" : ""
            onActivated: index => root.setCompactThreshold(model[index])
        }

        TextArea {
            id: draftInput

            anchors.left: parent.left
            anchors.right: compactButton.left
            anchors.top: immediateLabel.bottom
            anchors.bottom: parent.bottom
            anchors.leftMargin: 10
            anchors.rightMargin: 8
            anchors.topMargin: 9
            anchors.bottomMargin: 10
            text: root.draft
            placeholderText: root.acceptingClarification ? "Clarify the current request" : root.busy || root.resetting ? "…" : "Type a message…"
            color: "#e6faff"
            placeholderTextColor: "#4d7dd3fc"
            wrapMode: TextEdit.Wrap
            selectByMouse: true
            font.family: "JetBrains Mono"
            font.pixelSize: 12
            onTextChanged: root.draft = text
            Keys.onPressed: event => {
                if ((event.key === Qt.Key_Return || event.key === Qt.Key_Enter)
                        && !(event.modifiers & Qt.ShiftModifier)) {
                    event.accepted = true
                    root.sendDraft()
                }
            }

            background: Rectangle {
                radius: 6
                color: "#d903101a"
                border.width: 1
                border.color: draftInput.activeFocus ? "#7367e8f9" : "#3367e8f9"
            }
        }

        GlowButton {
            id: compactButton

            anchors.right: sendButton.left
            anchors.rightMargin: 7
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 10
            width: 86
            height: 54
            enabled: root.canMutate() && !(root.contextUsage && root.contextUsage.compacting)
            text: root.contextUsage && root.contextUsage.compacting ? "COMPACTING…" : "COMPACT"
            foreground: "#a5f3fc"
            idleBorderOpacity: 0.20
            idleTextOpacity: 0.55
            disabledOpacity: 0.35
            textPixelSize: 9
            textLetterSpacing: 1.0
            onClicked: root.compactNow()
        }

        GlowButton {
            id: sendButton

            anchors.right: parent.right
            anchors.rightMargin: 10
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 10
            width: root.acceptingClarification ? 76 : 50
            height: 54
            enabled: (root.canMutate() || (root.connected && root.acceptingClarification && !root.resetting)) && root.draft.trim().length > 0
            text: root.acceptingClarification ? "CLARIFY" : "SEND"
            foreground: "#67e8f9"
            idleBorderOpacity: 0.25
            idleTextOpacity: 0.70
            disabledOpacity: 0.40
            textPixelSize: 9
            textLetterSpacing: 1.0
            onClicked: root.sendDraft()
        }
    }

    WebSocket {
        id: chatSocket

        url: "ws://127.0.0.1:8765/ws/chat"
        active: true
        onTextMessageReceived: message => root.applyMessage(message)
        onStatusChanged: status => {
            root.connected = status === WebSocket.Open
            if (status === WebSocket.Open) {
                root.socketError = ""
            } else if (status === WebSocket.Closed || status === WebSocket.Error) {
                root.acceptingClarification = false
                root.busy = false
                root.resetting = false
                if (status === WebSocket.Error) {
                    root.socketError = chatSocket.errorString
                }
                chatReconnect.restart()
            }
        }
    }

    Timer {
        id: chatReconnect

        interval: 1000
        repeat: false
        onTriggered: {
            chatSocket.active = false
            chatSocket.active = true
        }
    }
}
