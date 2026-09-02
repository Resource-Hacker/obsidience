pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtWebSockets
import "../../components/visual"

Rectangle {
    id: root

    property var proposals: []
    property string expandedFile: ""
    property string loadError: ""
    property string actionError: ""
    property string decidingFile: ""
    property bool loading: true

    color: "#b302080e"
    clip: true

    function cleanLeaf(value) {
        const leaf = String(value ?? "").replace(/\.md$/i, "").split("/").pop()
        return leaf.replace(/-/g, " ").replace(/\b\w/g,
            letter => letter.toUpperCase())
    }

    function requestError(request, fallback) {
        const raw = String(request.responseText || "").trim()
        if (!raw) {
            return fallback
        }
        try {
            const parsed = JSON.parse(raw)
            return typeof parsed.detail === "string" ? parsed.detail : raw
        } catch (error) {
            return raw
        }
    }

    function requestJson(method, path, callback) {
        const request = new XMLHttpRequest()
        request.open(method, "http://127.0.0.1:8765" + path)
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE) {
                return
            }
            if (request.status < 200 || request.status >= 300) {
                callback(false, null, root.requestError(request,
                    "Request failed (" + request.status + ")"))
                return
            }
            try {
                callback(true, request.responseText ? JSON.parse(request.responseText) : {}, "")
            } catch (error) {
                callback(false, null, "The harness returned invalid JSON.")
            }
        }
        request.send()
    }

    function refresh() {
        requestJson("GET", "/api/reviews", (ok, payload, error) => {
            if (!root) {
                return
            }
            root.loading = false
            if (!ok || !Array.isArray(payload)) {
                root.loadError = "Review service unavailable: " + error
                return
            }
            root.proposals = payload
            root.loadError = ""
            if (root.expandedFile
                    && !payload.some(proposal => proposal.file === root.expandedFile)) {
                root.expandedFile = ""
            }
        })
    }

    function decide(proposal, approve) {
        if (!proposal || decidingFile) {
            return
        }
        actionError = ""
        decidingFile = proposal.file
        const action = approve ? "approve" : "reject?reason="
            + encodeURIComponent("rejected from review pane")
        requestJson("POST", "/api/reviews/" + encodeURIComponent(proposal.file)
            + "/" + action, (ok, payload, error) => {
            if (!root) {
                return
            }
            root.decidingFile = ""
            if (!ok) {
                root.actionError = error
                return
            }
            root.refresh()
        })
    }

    function presentArticle(ref) {
        if (!ref || shellSocket.status !== WebSocket.Open) {
            return
        }
        shellSocket.sendTextMessage(JSON.stringify({
            "schema": "obsidience.shell.command.v1",
            "type": "pane.present",
            "pane_id": "reader",
            "selection": {"kind": "article", "ref": ref}
        }))
    }

    Component.onCompleted: refresh()

    Timer {
        interval: 2000
        repeat: true
        running: true
        onTriggered: root.refresh()
    }

    Rectangle {
        id: header

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 42
        color: "#3d071119"

        Text {
            anchors.left: parent.left
            anchors.leftMargin: 13
            anchors.verticalCenter: parent.verticalCenter
            text: root.loading ? "LOADING REVIEW QUEUE"
                : root.proposals.length + " AWAITING REVIEW"
            color: "#667dd3fc"
            font.family: "JetBrains Mono"
            font.pixelSize: 9
            font.letterSpacing: 1.5
        }

        GlowButton {
            id: refreshButton

            anchors.right: parent.right
            anchors.rightMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            width: 28
            height: 28
            text: "↻"
            enabled: !root.loading
            idleBorderOpacity: 0
            hoverBorderOpacity: 0
            idleTextOpacity: 0.60
            hoverFillOpacity: 0.10
            textPixelSize: 14
            textLetterSpacing: 0
            contentHorizontalPadding: 0
            disabledOpacity: 0.30
            onClicked: {
                root.actionError = ""
                root.loading = true
                root.refresh()
            }
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
        id: errorStrip

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: header.bottom
        height: (root.loadError || root.actionError) ? 38 : 0
        visible: height > 0
        color: "#39190a12"
        border.width: 1
        border.color: "#36fb7185"

        Text {
            anchors.left: parent.left
            anchors.right: retryButton.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.leftMargin: 12
            anchors.rightMargin: 8
            text: root.actionError || root.loadError
            color: "#fda4af"
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
            font.family: "JetBrains Mono"
            font.pixelSize: 9
        }

        GlowButton {
            id: retryButton

            anchors.right: parent.right
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            visible: root.loadError !== ""
            width: visible ? 56 : 0
            height: 24
            text: "RETRY"
            idleBorderOpacity: 0
            hoverBorderOpacity: 0
            idleTextOpacity: 0.80
            hoverFillOpacity: 0
            textPixelSize: 8
            textLetterSpacing: 0
            contentHorizontalPadding: 4
            onClicked: root.refresh()
        }
    }

    Flickable {
        id: reviewScroll

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: errorStrip.bottom
        anchors.bottom: parent.bottom
        anchors.margins: 8
        clip: true
        contentWidth: width
        contentHeight: cards.implicitHeight + 2
        boundsBehavior: Flickable.StopAtBounds

        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
        }

        Column {
            id: cards

            width: reviewScroll.width
            spacing: 8

            Repeater {
                model: root.proposals

                delegate: Rectangle {
                    id: card

                    required property var modelData
                    readonly property bool isLink: modelData.review_class === "link"
                    readonly property bool expanded: root.expandedFile === modelData.file
                    width: cards.width
                    height: cardColumn.implicitHeight
                    radius: 8
                    color: "#c4020a12"
                    border.width: 1
                    border.color: isLink ? "#45c4b5fd" : "#2867e8f9"

                    Column {
                        id: cardColumn

                        width: parent.width

                        Item {
                            id: summary

                            width: parent.width
                            height: Math.max(104, summaryText.implicitHeight + 28)

                            Rectangle {
                                id: expandButton

                                anchors.left: parent.left
                                anchors.leftMargin: 10
                                anchors.top: parent.top
                                anchors.topMargin: 12
                                width: 24
                                height: 24
                                radius: 4
                                color: expandMouse.containsMouse ? "#2034d399" : "transparent"

                                Text {
                                    anchors.centerIn: parent
                                    text: card.expanded ? "⌄" : "›"
                                    color: "#9967e8f9"
                                    font.family: "JetBrains Mono"
                                    font.pixelSize: 14
                                }

                                MouseArea {
                                    id: expandMouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.expandedFile = card.expanded ? "" : card.modelData.file
                                }
                            }

                            Column {
                                id: summaryText

                                anchors.left: expandButton.right
                                anchors.right: decisions.left
                                anchors.top: parent.top
                                anchors.leftMargin: 4
                                anchors.rightMargin: 10
                                anchors.topMargin: 13
                                spacing: 4

                                Text {
                                    width: parent.width
                                    text: card.isLink ? "LINK PROPOSAL"
                                        : String(card.modelData.action).toUpperCase() + " ARTICLE PROPOSAL"
                                    color: card.isLink ? "#c4b5fd" : "#d7b96f"
                                    elide: Text.ElideRight
                                    font.family: "JetBrains Mono"
                                    font.pixelSize: 8
                                    font.letterSpacing: 1.3
                                }

                                Text {
                                    width: parent.width
                                    text: card.modelData.title || root.cleanLeaf(card.modelData.target)
                                    color: "#e6faff"
                                    elide: Text.ElideRight
                                    font.family: "JetBrains Mono"
                                    font.pixelSize: 13
                                    font.weight: Font.DemiBold

                                    MouseArea {
                                        anchors.fill: parent
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: root.presentArticle(card.modelData.target)
                                    }
                                }

                                Text {
                                    width: parent.width
                                    visible: String(card.modelData.reason || "") !== ""
                                    text: String(card.modelData.reason || "")
                                    color: "#8bb6c3"
                                    wrapMode: Text.Wrap
                                    maximumLineCount: 2
                                    elide: Text.ElideRight
                                    font.family: "JetBrains Mono"
                                    font.pixelSize: 9
                                    lineHeight: 1.25
                                    lineHeightMode: Text.ProportionalHeight
                                }

                                Text {
                                    width: parent.width
                                    text: root.cleanLeaf(card.modelData.target) + "   ·   "
                                        + String(card.modelData.agent || "")
                                        + (card.modelData.task
                                            ? "   ·   " + root.cleanLeaf(card.modelData.task) : "")
                                    color: "#4d7dd3fc"
                                    elide: Text.ElideRight
                                    font.family: "JetBrains Mono"
                                    font.pixelSize: 8
                                }
                            }

                            Row {
                                id: decisions

                                anchors.right: parent.right
                                anchors.rightMargin: 10
                                anchors.top: parent.top
                                anchors.topMargin: 12
                                spacing: 6

                                GlowButton {
                                    id: approveButton

                                    width: 30
                                    height: 30
                                    text: "✓"
                                    accent: "#5eead4"
                                    foreground: "#5eead4"
                                    idleBorderOpacity: 0.35
                                    idleTextOpacity: 1.0
                                    hoverFillOpacity: 0.10
                                    textPixelSize: 13
                                    textLetterSpacing: 0
                                    contentHorizontalPadding: 0
                                    disabledOpacity: 0.30
                                    enabled: !root.decidingFile && card.modelData.approvable
                                    onClicked: root.decide(card.modelData, true)
                                }

                                GlowButton {
                                    id: rejectButton

                                    width: 30
                                    height: 30
                                    text: "×"
                                    accent: "#fb7185"
                                    foreground: "#fb7185"
                                    idleBorderOpacity: 0.35
                                    idleTextOpacity: 1.0
                                    hoverFillOpacity: 0.10
                                    textPixelSize: 15
                                    textLetterSpacing: 0
                                    contentHorizontalPadding: 0
                                    disabledOpacity: 0.30
                                    enabled: !root.decidingFile
                                    onClicked: root.decide(card.modelData, false)
                                }
                            }
                        }

                        Rectangle {
                            width: parent.width
                            height: blockedText.implicitHeight + 18
                            visible: String(card.modelData.blocked_reason || "") !== ""
                            color: "#14fbbf24"
                            border.width: 1
                            border.color: "#44fbbf24"

                            Text {
                                id: blockedText
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.top: parent.top
                                anchors.margins: 9
                                text: String(card.modelData.blocked_reason || "")
                                color: "#fcd34d"
                                wrapMode: Text.Wrap
                                font.family: "JetBrains Mono"
                                font.pixelSize: 9
                            }
                        }

                        Rectangle {
                            width: parent.width
                            height: linkColumn.implicitHeight + 18
                            visible: card.isLink && card.modelData.link_changes
                                && ((Array.isArray(card.modelData.link_changes.added)
                                        && card.modelData.link_changes.added.length > 0)
                                    || (Array.isArray(card.modelData.link_changes.removed)
                                        && card.modelData.link_changes.removed.length > 0))
                            color: "#12c4b5fd"
                            border.width: 1
                            border.color: "#35c4b5fd"

                            Column {
                                id: linkColumn

                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.top: parent.top
                                anchors.margins: 9
                                spacing: 3

                                Text {
                                    width: parent.width
                                    text: "RELATIONSHIP CHANGE"
                                    color: "#99c4b5fd"
                                    font.family: "JetBrains Mono"
                                    font.pixelSize: 8
                                    font.letterSpacing: 1.2
                                }

                                Repeater {
                                    model: card.modelData.link_changes
                                        && Array.isArray(card.modelData.link_changes.added)
                                        ? card.modelData.link_changes.added : []
                                    delegate: Text {
                                        required property string modelData
                                        width: linkColumn.width
                                        text: "+ " + root.cleanLeaf(modelData)
                                        color: "#86efac"
                                        elide: Text.ElideRight
                                        font.family: "JetBrains Mono"
                                        font.pixelSize: 9
                                    }
                                }

                                Repeater {
                                    model: card.modelData.link_changes
                                        && Array.isArray(card.modelData.link_changes.removed)
                                        ? card.modelData.link_changes.removed : []
                                    delegate: Text {
                                        required property string modelData
                                        width: linkColumn.width
                                        text: "− " + root.cleanLeaf(modelData)
                                        color: "#fda4af"
                                        elide: Text.ElideRight
                                        font.family: "JetBrains Mono"
                                        font.pixelSize: 9
                                    }
                                }
                            }
                        }

                        Rectangle {
                            id: preview

                            width: parent.width
                            height: card.expanded ? Math.min(380,
                                Math.max(90, previewText.implicitHeight + 52)) : 0
                            visible: card.expanded
                            color: "#b801070d"
                            border.width: 1
                            border.color: card.isLink ? "#30c4b5fd" : "#2067e8f9"

                            Text {
                                anchors.left: parent.left
                                anchors.top: parent.top
                                anchors.leftMargin: 12
                                anchors.topMargin: 10
                                text: card.isLink ? "ARTICLE AFTER LINK" : "PROPOSED ARTICLE"
                                color: card.isLink ? "#80c4b5fd" : "#6667e8f9"
                                font.family: "JetBrains Mono"
                                font.pixelSize: 8
                                font.letterSpacing: 1.4
                            }

                            Flickable {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.top: parent.top
                                anchors.bottom: parent.bottom
                                anchors.leftMargin: 12
                                anchors.rightMargin: 8
                                anchors.topMargin: 32
                                anchors.bottomMargin: 10
                                clip: true
                                contentWidth: width
                                contentHeight: previewText.implicitHeight
                                boundsBehavior: Flickable.StopAtBounds

                                ScrollBar.vertical: ScrollBar {
                                    policy: ScrollBar.AsNeeded
                                }

                                Text {
                                    id: previewText

                                    width: parent.width - 8
                                    text: String(card.modelData.body_preview || "")
                                    textFormat: Text.MarkdownText
                                    wrapMode: Text.Wrap
                                    color: "#c7dbe3"
                                    linkColor: "#67e8f9"
                                    font.family: "JetBrains Mono"
                                    font.pixelSize: 11
                                    lineHeight: 1.35
                                    lineHeightMode: Text.ProportionalHeight
                                }
                            }
                        }
                    }
                }
            }

            Rectangle {
                width: parent.width
                height: 112
                radius: 8
                visible: !root.loading && !root.loadError && root.proposals.length === 0
                color: "#80020a12"
                border.width: 1
                border.color: "#2067e8f9"

                Column {
                    anchors.centerIn: parent
                    spacing: 8

                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "QUEUE IS CLEAR"
                        color: "#99cffafe"
                        font.family: "JetBrains Mono"
                        font.pixelSize: 12
                        font.letterSpacing: 1.0
                    }

                    Text {
                        width: Math.min(420, reviewScroll.width - 50)
                        text: "Agent proposals will appear here for owner approval or rejection."
                        color: "#527dd3fc"
                        horizontalAlignment: Text.AlignHCenter
                        wrapMode: Text.Wrap
                        font.family: "JetBrains Mono"
                        font.pixelSize: 9
                    }
                }
            }
        }
    }

    WebSocket {
        id: shellSocket

        url: "ws://127.0.0.1:8768"
        requestedSubprotocols: ["obsidience.shell.v1"]
        active: true
        onStatusChanged: status => {
            if (status === WebSocket.Closed || status === WebSocket.Error) {
                shellReconnect.restart()
            }
        }
    }

    Timer {
        id: shellReconnect

        interval: 1000
        repeat: false
        onTriggered: {
            shellSocket.active = false
            shellSocket.active = true
        }
    }
}
