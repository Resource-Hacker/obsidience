pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtWebSockets

Item {
    id: root

    property string articleRef: ""
    property string sourceKey: ""
    property string selectionKind: "article"
    property string articleTitle: ""
    property string articleKind: ""
    property string articleBody: ""
    property var articleChildren: []
    property var articleMeta: ({})
    property string documentPath: ""
    property string sourceStorage: ""
    property string sourceMediaType: ""
    property int sourceSize: 0
    property bool sourceReadable: true
    property bool sourceTruncated: false
    property string errorMessage: ""
    property string noticeMessage: ""
    property bool loading: false
    property int requestGeneration: 0
    property bool editing: false
    property bool saving: false
    property string draftTitle: ""
    property string draftBody: ""

    readonly property bool sourceMode: selectionKind === "source"
    readonly property bool indexArticle: !sourceMode && articleChildren.length > 0
    readonly property bool pythonSource: sourceMode
        && (sourceMediaType.indexOf("python") >= 0
            || articleTitle.toLowerCase().endsWith(".py"))
    readonly property bool codeSource: sourceMode && sourceReadable
        && (sourceStorage === "code" || pythonSource)
    readonly property string sourceClass: sourceStorage === "knowledge"
        ? "Knowledge Article file"
        : sourceStorage === "code"
            ? articleChildren.length ? "Article-linked application code" : "Application code"
            : sourceStorage === "system" ? "System descriptor · read only"
                : "Immutable raw source"

    function applyShellEvent(text) {
        if (typeof text !== "string" || text.length > 65536) return
        let event
        try { event = JSON.parse(text) } catch (error) { return }
        const selection = event ? event.selection : null
        if (!event || event.schema !== "obsidience.shell.event.v1"
                || event.type !== "pane.state" || !event.pane
                || event.pane.pane_id !== "reader" || !selection) return
        if (selection.kind === "article" && typeof selection.ref === "string"
                && selection.ref.trim()) {
            selectionKind = "article"
            sourceKey = ""
            articleRef = selection.ref.trim()
        } else if (selection.kind === "source" && typeof selection.key === "string"
                && selection.key.trim()) {
            selectionKind = "source"
            articleRef = ""
            sourceKey = selection.key.trim()
        }
    }

    function presentArticle(ref) {
        if (typeof ref !== "string" || !ref.trim()
                || shellSocket.status !== WebSocket.Open) return
        shellSocket.sendTextMessage(JSON.stringify({
            "schema": "obsidience.shell.command.v1",
            "type": "pane.present",
            "pane_id": "reader",
            "selection": {"kind": "article", "ref": ref.trim()}
        }))
    }

    function readableBytes(bytes) {
        const value = Number(bytes || 0)
        if (value < 1024) return value + " B"
        if (value < 1048576) return (value / 1024).toFixed(1) + " KB"
        if (value < 1073741824) return (value / 1048576).toFixed(1) + " MB"
        return (value / 1073741824).toFixed(1) + " GB"
    }

    function resetDocument() {
        articleTitle = ""
        articleKind = ""
        articleBody = ""
        articleChildren = []
        articleMeta = {}
        documentPath = ""
        sourceStorage = ""
        sourceMediaType = ""
        sourceSize = 0
        sourceReadable = true
        sourceTruncated = false
        errorMessage = ""
        noticeMessage = ""
        editing = false
    }

    function loadDocument() {
        const ref = sourceMode ? sourceKey.trim() : articleRef.trim()
        requestGeneration += 1
        const generation = requestGeneration
        resetDocument()
        if (!ref) { loading = false; return }
        loading = true
        const request = new XMLHttpRequest()
        request.open("GET", "http://127.0.0.1:8765/"
            + (sourceMode ? "api/source-files/" : "api/articles/") + encodeURI(ref))
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE
                    || generation !== root.requestGeneration) return
            root.loading = false
            if (request.status < 200 || request.status >= 300) {
                root.errorMessage = request.responseText || "Document could not be loaded."
                return
            }
            try {
                const document = JSON.parse(request.responseText)
                if (root.sourceMode) {
                    root.articleTitle = typeof document.name === "string" ? document.name : ref
                    root.articleKind = typeof document.storage === "string"
                        ? document.storage : "source"
                    root.sourceReadable = typeof document.content === "string"
                    root.articleBody = root.sourceReadable ? document.content : ""
                    root.articleChildren = Array.isArray(document.articles)
                        ? document.articles.filter(value => typeof value === "string") : []
                    root.documentPath = typeof document.path === "string" ? document.path : ref
                    root.sourceStorage = typeof document.storage === "string"
                        ? document.storage : "source"
                    root.sourceMediaType = typeof document.media_type === "string"
                        ? document.media_type : "file"
                    root.sourceSize = Number(document.size || 0)
                    root.sourceTruncated = document.truncated === true
                } else {
                    root.articleTitle = typeof document.title === "string" ? document.title : ref
                    root.articleKind = typeof document.kind === "string"
                        ? document.kind : "knowledge"
                    root.articleBody = typeof document.body === "string" ? document.body : ""
                    root.articleChildren = Array.isArray(document.children)
                        ? document.children.filter(value => typeof value === "string") : []
                    root.articleMeta = document.meta && typeof document.meta === "object"
                        ? document.meta : {}
                    root.documentPath = ref
                    root.draftTitle = root.articleTitle
                    root.draftBody = root.articleBody
                }
            } catch (error) {
                root.errorMessage = "Document response was invalid."
            }
        }
        request.send()
    }

    function startEdit() {
        draftTitle = articleTitle
        draftBody = articleBody
        noticeMessage = ""
        editing = true
    }

    function cancelEdit() {
        draftTitle = articleTitle
        draftBody = articleBody
        noticeMessage = ""
        editing = false
    }

    function saveArticle() {
        if (sourceMode || saving || !articleRef || !draftTitle.trim()) return
        saving = true
        noticeMessage = ""
        errorMessage = ""
        const request = new XMLHttpRequest()
        request.open("PATCH", "http://127.0.0.1:8765/api/articles/" + encodeURI(articleRef))
        request.setRequestHeader("content-type", "application/json")
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE) return
            root.saving = false
            if (request.status < 200 || request.status >= 300) {
                root.errorMessage = request.responseText || "Article could not be saved."
                return
            }
            root.articleTitle = root.draftTitle.trim()
            root.articleBody = root.draftBody
            root.editing = false
            root.noticeMessage = "Article saved."
        }
        request.send(JSON.stringify({"title": draftTitle.trim(), "body": draftBody}))
    }

    function wikiMarkdown(content) {
        return String(content || "").replace(
            /\[\[([^\]|\n]+)(?:\|([^\]\n]+))?\]\]/g,
            function(match, rawRef, rawLabel) {
                const ref = String(rawRef).trim()
                const label = String(rawLabel || ref.split("/").pop() || ref).trim()
                return "[" + label + "](obsidience-ref:" + encodeURIComponent(ref) + ")"
            }
        )
    }

    function escapeHtml(value) {
        return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;")
            .replace(/>/g, "&gt;").replace(/\"/g, "&quot;")
    }

    function pythonLine(line) {
        const tokenPattern = /(#.*$)|("""[^\n]*?"""|'''[^\n]*?'''|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|\b(and|as|assert|async|await|break|case|class|continue|def|del|elif|else|except|finally|for|from|global|if|import|in|is|lambda|match|nonlocal|not|or|pass|raise|return|try|while|with|yield)\b|\b(True|False|None|self|cls)\b|\b([0-9]+(?:\.[0-9]+)?)\b/g
        let result = ""
        let offset = 0
        let match
        while ((match = tokenPattern.exec(line)) !== null) {
            result += escapeHtml(line.slice(offset, match.index))
            const token = escapeHtml(match[0])
            if (match[1] !== undefined) {
                result += "<span style='color:#64748b;font-style:italic'>"
                    + token + "</span>"
            } else if (match[2] !== undefined) {
                result += "<span style='color:#6ee7b7'>" + token + "</span>"
            } else if (match[3] !== undefined) {
                result += "<span style='color:#f0abfc;font-weight:600'>"
                    + token + "</span>"
            } else if (match[4] !== undefined) {
                result += "<span style='color:#fcd34d'>" + token + "</span>"
            } else {
                result += "<span style='color:#fdba74'>" + token + "</span>"
            }
            offset = match.index + match[0].length
        }
        return result + escapeHtml(line.slice(offset))
    }

    function highlightedSource() {
        if (!pythonSource) return "<pre>" + escapeHtml(articleBody) + "</pre>"
        return "<pre>" + articleBody.split("\n").map(pythonLine).join("\n") + "</pre>"
    }

    function lineNumbers() {
        const count = Math.max(1, articleBody.split("\n").length)
        const rows = []
        for (let index = 1; index <= count; index += 1) rows.push(String(index))
        return rows.join("\n")
    }

    onArticleRefChanged: { if (selectionKind === "article") loadDocument() }
    onSourceKeyChanged: { if (selectionKind === "source") loadDocument() }
    Component.onCompleted: loadDocument()

    WebSocket {
        id: shellSocket
        url: "ws://127.0.0.1:8768"
        requestedSubprotocols: ["obsidience.shell.v1"]
        active: true
        onTextMessageReceived: message => root.applyShellEvent(message)
        onStatusChanged: status => {
            if (status === WebSocket.Closed || status === WebSocket.Error) {
                reconnectTimer.restart()
            }
        }
    }

    Timer {
        id: reconnectTimer
        interval: 500
        repeat: false
        onTriggered: { shellSocket.active = false; shellSocket.active = true }
    }

    Flickable {
        id: documentScroll
        anchors.fill: parent
        clip: true
        contentWidth: width
        contentHeight: documentColumn.implicitHeight + 48
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        Column {
            id: documentColumn
            x: (documentScroll.width - width) / 2
            y: 16
            width: Math.max(180, Math.min(
                root.sourceMode ? 1100 : root.indexArticle ? 920 : 720,
                documentScroll.width - 40
            ))
            spacing: 14

            Text {
                width: parent.width
                visible: !root.articleTitle && !root.loading && !root.errorMessage
                text: "Select an article in Knowledge or click a graph node to read it here."
                color: "#59cffafe"
                wrapMode: Text.Wrap
                font.family: "JetBrains Mono"
                font.pixelSize: 11
                lineHeightMode: Text.FixedHeight
                lineHeight: 20
            }

            Text {
                width: parent.width
                visible: root.loading || root.errorMessage !== ""
                text: root.loading ? "Loading…" : root.errorMessage
                color: root.errorMessage ? "#fecdd3" : "#667dd3fc"
                wrapMode: Text.Wrap
                font.family: "JetBrains Mono"
                font.pixelSize: 10
            }

            Item {
                id: documentHeader
                width: parent.width
                height: visible ? headerColumn.implicitHeight + 16 : 0
                visible: root.articleTitle !== "" && !root.loading

                Column {
                    id: headerColumn
                    anchors.left: parent.left
                    anchors.right: actionRow.left
                    anchors.rightMargin: 12
                    anchors.top: parent.top
                    spacing: 5

                    Text {
                        visible: root.sourceMode || root.indexArticle
                        width: parent.width
                        text: root.sourceMode ? root.sourceClass : "Knowledge index"
                        color: root.sourceMode ? "#80c4b5fd" : "#7367e8f9"
                        font.family: "JetBrains Mono"
                        font.pixelSize: 8
                        font.capitalization: Font.AllUppercase
                        font.letterSpacing: root.sourceMode ? 1.76 : 1.92
                    }
                    TextField {
                        visible: root.editing
                        width: parent.width
                        height: 30
                        text: root.draftTitle
                        color: "#ecfeff"
                        selectByMouse: true
                        font.family: "JetBrains Mono"
                        font.pixelSize: 13
                        onTextChanged: root.draftTitle = text
                        background: Rectangle {
                            radius: 4; color: "#020a12"; border.width: 1
                            border.color: "#3367e8f9"
                        }
                    }
                    Text {
                        visible: !root.editing
                        width: parent.width
                        text: root.articleTitle
                        color: root.sourceMode ? "#f5f3ff" : "#ecfeff"
                        wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                        font.family: "JetBrains Mono"
                        font.pixelSize: root.indexArticle ? 22 : 18
                        font.weight: Font.DemiBold
                        font.letterSpacing: root.indexArticle ? 0.55 : 0.72
                        lineHeightMode: Text.ProportionalHeight
                        lineHeight: root.indexArticle ? 1.1 : 1.25
                    }
                    Text {
                        visible: root.sourceMode
                        width: parent.width
                        text: root.documentPath
                        color: "#59ede9fe"
                        wrapMode: Text.WrapAnywhere
                        font.family: "JetBrains Mono"
                        font.pixelSize: 8
                    }
                }

                Row {
                    id: actionRow
                    anchors.right: parent.right
                    anchors.top: parent.top
                    spacing: 6

                    Repeater {
                        model: root.sourceMode ? [
                            root.sourceMediaType || "file",
                            root.readableBytes(root.sourceSize)
                        ] : []
                        delegate: Rectangle {
                            id: pill
                            required property string modelData
                            width: pillText.implicitWidth + 16
                            height: 21
                            radius: 10
                            color: "#09c4b5fd"
                            border.width: 1
                            border.color: "#26c4b5fd"
                            Text {
                                id: pillText
                                anchors.centerIn: parent
                                text: pill.modelData
                                color: "#8cddd6fe"
                                font.family: "JetBrains Mono"
                                font.pixelSize: 8
                                font.capitalization: Font.AllUppercase
                                font.letterSpacing: 0.96
                            }
                        }
                    }

                    Rectangle {
                        visible: !root.sourceMode && !root.editing
                        width: 54
                        height: 23
                        radius: 4
                        color: editMouse.containsMouse ? "#1267e8f9" : "transparent"
                        border.width: 1
                        border.color: editMouse.containsMouse ? "#8067e8f9" : "#4067e8f9"
                        Text {
                            anchors.centerIn: parent
                            text: "✎  EDIT"
                            color: "#b3a5f3fc"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                            font.letterSpacing: 0.72
                        }
                        MouseArea {
                            id: editMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.startEdit()
                        }
                    }
                }

                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: 1
                    color: root.sourceMode ? "#1fc4b5fd" : "#1a67e8f9"
                }
            }

            Row {
                visible: root.sourceMode && root.articleChildren.length > 0
                width: parent.width
                spacing: 6
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: "ARTICLE"
                    color: "#66c4b5fd"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 8
                    font.letterSpacing: 1.28
                }
                Repeater {
                    model: root.articleChildren
                    delegate: Rectangle {
                        id: sourceArticleButton
                        required property string modelData
                        width: Math.min(240, sourceArticleText.implicitWidth + 16)
                        height: 24
                        radius: 4
                        color: sourceArticleMouse.containsMouse ? "#1267e8f9" : "transparent"
                        border.width: 1
                        border.color: sourceArticleMouse.containsMouse
                            ? "#7367e8f9" : "#2e67e8f9"
                        Text {
                            id: sourceArticleText
                            anchors.centerIn: parent
                            text: sourceArticleButton.modelData.split("/").pop()
                            color: "#a6cffafe"
                            elide: Text.ElideRight
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                        }
                        MouseArea {
                            id: sourceArticleMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.presentArticle(sourceArticleButton.modelData)
                        }
                    }
                }
            }

            TextArea {
                visible: root.editing
                width: parent.width
                height: Math.max(360, implicitHeight)
                text: root.draftBody
                color: "#d1ecfeff"
                selectByMouse: true
                wrapMode: TextEdit.Wrap
                font.family: "JetBrains Mono"
                font.pixelSize: 12
                leftPadding: 12
                rightPadding: 12
                topPadding: 10
                bottomPadding: 10
                onTextChanged: root.draftBody = text
                background: Rectangle {
                    radius: 6; color: "#e6020a12"; border.width: 1
                    border.color: "#3367e8f9"
                }
            }

            Row {
                visible: root.editing
                spacing: 8
                Rectangle {
                    width: 96; height: 27; radius: 4
                    color: saveMouse.containsMouse ? "#1767e8f9" : "transparent"
                    border.width: 1; border.color: "#5967e8f9"
                    opacity: root.saving || !root.draftTitle.trim() ? 0.40 : 1
                    Text {
                        anchors.centerIn: parent
                        text: root.saving ? "SAVING" : "SAVE ARTICLE"
                        color: "#cffafe"; font.family: "JetBrains Mono"
                        font.pixelSize: 8; font.letterSpacing: 0.84
                    }
                    MouseArea {
                        id: saveMouse; anchors.fill: parent; hoverEnabled: true
                        enabled: !root.saving && root.draftTitle.trim() !== ""
                        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: root.saveArticle()
                    }
                }
                Rectangle {
                    width: 58; height: 27; radius: 4; color: "transparent"
                    border.width: 1; border.color: "#3367e8f9"
                    Text {
                        anchors.centerIn: parent; text: "CANCEL"; color: "#99a5f3fc"
                        font.family: "JetBrains Mono"; font.pixelSize: 8
                    }
                    MouseArea {
                        anchors.fill: parent; cursorShape: Qt.PointingHandCursor
                        onClicked: root.cancelEdit()
                    }
                }
            }

            Rectangle {
                visible: !root.editing && !root.sourceMode && root.articleTitle !== ""
                width: parent.width
                height: articleText.implicitHeight + (root.indexArticle ? 30 : 0)
                radius: root.indexArticle ? 7 : 0
                color: root.indexArticle ? "#d9020a12" : "transparent"
                border.width: root.indexArticle ? 1 : 0
                border.color: "#1a67e8f9"
                Rectangle {
                    visible: root.indexArticle
                    anchors.left: parent.left
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    width: 2
                    radius: 1
                    color: "#6622d3ee"
                }
                Text {
                    id: articleText
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: root.indexArticle ? 15 : 0
                    textFormat: Text.MarkdownText
                    text: root.wikiMarkdown(root.articleBody)
                    color: "#d1ecfeff"
                    linkColor: "#a5f3fc"
                    wrapMode: Text.Wrap
                    font.family: "JetBrains Mono"
                    font.pixelSize: 13
                    lineHeightMode: Text.FixedHeight
                    lineHeight: 24
                    onLinkActivated: link => {
                        const value = String(link)
                        if (value.startsWith("obsidience-ref:")) {
                            root.presentArticle(decodeURIComponent(
                                value.slice("obsidience-ref:".length)
                            ))
                        }
                    }
                }
            }

            Rectangle {
                visible: root.sourceMode && root.articleTitle !== ""
                width: parent.width
                height: !root.sourceReadable ? 84
                    : Math.max(90, Math.min(900, sourceText.implicitHeight + 28))
                radius: 7
                color: root.codeSource ? "#f504070d" : "#eb05070d"
                border.width: 1
                border.color: "#24c4b5fd"
                clip: true

                Text {
                    visible: !root.sourceReadable
                    anchors.fill: parent
                    anchors.margins: 20
                    text: "This binary source is stored here, but it does not have a text preview."
                    color: "#8fede9fe"
                    wrapMode: Text.Wrap
                    font.family: "JetBrains Mono"
                    font.pixelSize: 10
                    lineHeightMode: Text.FixedHeight
                    lineHeight: 20
                }

                Flickable {
                    id: codeScroll
                    visible: root.sourceReadable
                    anchors.fill: parent
                    anchors.margins: 12
                    clip: true
                    contentWidth: codeRow.implicitWidth
                    contentHeight: codeRow.implicitHeight
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }

                    Row {
                        id: codeRow
                        spacing: 12
                        Text {
                            width: 48
                            text: root.lineNumbers()
                            color: "#5264748b"
                            horizontalAlignment: Text.AlignRight
                            font.family: "JetBrains Mono"
                            font.pixelSize: 11
                            lineHeightMode: Text.ProportionalHeight
                            lineHeight: 1.72
                        }
                        Rectangle {
                            width: 1
                            height: Math.max(lineNumberText.implicitHeight, sourceText.implicitHeight)
                            color: "#1fc4b5fd"
                        }
                        Text {
                            id: lineNumberText
                            visible: false
                            text: root.lineNumbers()
                            font.family: "JetBrains Mono"
                            font.pixelSize: 11
                            lineHeightMode: Text.ProportionalHeight
                            lineHeight: 1.72
                        }
                        Text {
                            id: sourceText
                            textFormat: Text.RichText
                            text: root.highlightedSource()
                            color: "#d1e2e8f0"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 11
                            lineHeightMode: Text.ProportionalHeight
                            lineHeight: 1.72
                        }
                    }
                }
            }

            Text {
                visible: root.sourceMode && root.sourceTruncated
                width: parent.width
                text: "… source preview truncated"
                color: "#b3fcd34d"
                font.family: "JetBrains Mono"
                font.pixelSize: 9
            }

            Text {
                visible: root.noticeMessage !== ""
                width: parent.width
                text: root.noticeMessage
                color: "#b36ee7b7"
                font.family: "JetBrains Mono"
                font.pixelSize: 9
            }

            Column {
                visible: !root.editing && !root.sourceMode
                    && root.articleChildren.length > 0
                width: parent.width
                spacing: 7
                Text {
                    text: root.articleKind === "task" ? "SUBTASKS"
                        : root.articleKind === "tool" ? "SUBTOOLS"
                        : root.articleKind === "skill" ? "SUBSKILLS"
                        : root.articleKind === "runbook" ? "SUBRUNBOOKS" : "CHILDREN"
                    color: "#7367e8f9"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 8
                    font.letterSpacing: 1.28
                }
                Repeater {
                    model: root.articleChildren
                    delegate: Rectangle {
                        id: childButton
                        required property string modelData
                        width: documentColumn.width
                        height: 28
                        radius: 4
                        color: childMouse.containsMouse ? "#1267e8f9" : "#08071119"
                        border.width: 1
                        border.color: childMouse.containsMouse ? "#6667e8f9" : "#2667e8f9"
                        Text {
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            anchors.leftMargin: 10
                            anchors.rightMargin: 10
                            text: childButton.modelData.split("/").pop()
                            color: "#b3cffafe"
                            elide: Text.ElideRight
                            font.family: "JetBrains Mono"
                            font.pixelSize: 9
                        }
                        MouseArea {
                            id: childMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.presentArticle(childButton.modelData)
                        }
                    }
                }
            }
        }
    }
}
