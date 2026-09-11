pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtWebSockets
import "../../components/knowledge"

Item {
    id: root

    ArticleCheckouts {
        id: checkouts
        nodes: root.articleGraph.nodes
        active: root.visible && !root.sourceMode && root.articleRef !== ""
        onChanged: root.loadArticleTitles(root.requestGeneration)
    }

    property string articleRef: ""
    property string graphId: ""
    property string sourceKey: ""
    property string feedItemId: ""
    property var previewItem: ({})
    property bool followShellSelection: true
    property var feedProvenance: ({})
    property string selectionKind: "article"
    property string articleTitle: ""
    property string articleKind: ""
    property string articleBody: ""
    property var articleChildren: []
    property var articleTitles: ({})
    property var articleGraph: ({nodes: [], links: []})
    property var articleMeta: ({})
    property bool articleReadOnly: false
    property string articleManagedBy: ""
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
    property int citationRequestGeneration: 0
    property bool editing: false
    property bool saving: false
    property bool autoCurateSupported: false
    property bool autoCurateEnabled: false
    property bool curationBusy: false
    property string draftTitle: ""
    property string draftBody: ""

    readonly property bool previewMode: selectionKind === "feed_preview"
    readonly property bool sourceMode: selectionKind === "source" || previewMode
    readonly property bool feedItemMode: selectionKind === "source" && feedItemId.length > 0
    readonly property bool indexArticle: !sourceMode && articleChildren.length > 0
    readonly property var articleLinks: articleConnections(false)
    readonly property var articleBacklinks: articleConnections(true)
    readonly property bool pythonSource: sourceMode
        && (sourceMediaType.indexOf("python") >= 0
            || articleTitle.toLowerCase().endsWith(".py"))
    readonly property bool codeSource: sourceMode && sourceReadable
        && (sourceStorage === "code" || pythonSource)
    readonly property string sourceClass: previewMode ? "Publisher preview · not collected"
        : feedItemMode ? "Captured provider content"
        : sourceStorage === "knowledge"
        ? "Knowledge Article file"
        : sourceStorage === "code"
            ? articleChildren.length ? "Article-linked application code" : "Application code"
            : sourceStorage === "system" ? "System evidence · read only"
                : "Immutable raw source"

    function applyShellEvent(text) {
        if (!followShellSelection) return
        if (typeof text !== "string" || text.length > 65536) return
        let event
        try { event = JSON.parse(text) } catch (error) { return }
        const selection = event ? event.selection : null
        if (!event || event.schema !== "obsidience.shell.event.v1"
                || event.type !== "pane.state" || !event.pane
                || event.pane.pane_id !== "reader" || !selection) return
        if (selection.kind === "article" && typeof selection.ref === "string"
                && selection.ref.trim()) {
            const selectedGraph = typeof selection.graph_id === "string" ? selection.graph_id : ""
            if (selectionKind === "article" && articleRef === selection.ref.trim()
                    && graphId === selectedGraph) return
            requestGeneration += 1
            graphId = selectedGraph
            selectionKind = "article"
            feedItemId = ""
            previewItem = ({})
            sourceKey = ""
            articleRef = selection.ref.trim()
        } else if (selection.kind === "source" && typeof selection.key === "string"
                && selection.key.trim()) {
            const selectedFeedItem = typeof selection.feed_item_id === "string" ? selection.feed_item_id : ""
            if (selectionKind === "source" && sourceKey === selection.key.trim()
                    && feedItemId === selectedFeedItem) return
            requestGeneration += 1
            graphId = ""
            selectionKind = "source"
            articleRef = ""
            feedItemId = selectedFeedItem
            previewItem = ({})
            sourceKey = selection.key.trim()
        } else if (selection.kind === "feed_preview" && selection.item
                && typeof selection.item.title === "string"
                && typeof selection.item.summary === "string") {
            const fields = ["title", "summary", "reporting_url", "published", "feed_title", "feed_url"]
            if (previewMode && fields.every(field => previewItem[field] === selection.item[field])) return
            requestGeneration += 1
            graphId = ""
            selectionKind = "feed_preview"
            articleRef = ""
            sourceKey = ""
            feedItemId = ""
            previewItem = selection.item
        } else return
        Qt.callLater(root.loadDocument)
    }

    function presentArticle(ref) {
        if (typeof ref !== "string" || !ref.trim()
                || shellSocket.status !== WebSocket.Open) return
        shellSocket.sendTextMessage(JSON.stringify({
            "schema": "obsidience.shell.command.v1",
            "type": "pane.present",
            "pane_id": "reader",
            "selection": {"kind": "article", "ref": ref.trim(), "graph_id": graphId}
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
        articleGraph = {nodes: [], links: []}
        articleMeta = {}
        articleReadOnly = false
        articleManagedBy = ""
        autoCurateSupported = false
        autoCurateEnabled = false
        curationBusy = false
        documentPath = ""
        sourceStorage = ""
        sourceMediaType = ""
        sourceSize = 0
        sourceReadable = true
        sourceTruncated = false
        feedProvenance = ({})
        errorMessage = ""
        noticeMessage = ""
        editing = false
        saving = false
    }

    function articleLabel(ref) {
        const clean = String(ref).trim().replace(/^\[\[/, "").replace(/\]\]$/, "")
            .split("|")[0].split("#")[0]
        return articleTitles[clean] || clean
    }

    function articleConnections(incoming) {
        if (sourceMode) return []
        const nodes = new Map(articleGraph.nodes.map(node => [node.id, node]))
        const selected = nodes.get(articleRef)
        const ref = (selected && selected.article_ref) || documentPath || articleRef
        const groups = (articleGraph.navigation || {}).groups || []
        const group = groups.find(item => graphId === (item.id === "executive" ? "main"
            : item.id === "library" ? "library" : item.root_ref.split("/")[1]))
        if (graphId && !group) return []
        const members = group ? new Set(group.article_refs || []) : null
        const links = articleGraph.links.filter(link => (incoming ? link.target : link.source) === ref
            && (!members || (members.has(link.source) && members.has(link.target)
                && (!link.for_agent || group.id === "library" || link.for_agent === group.root_ref)
                && (group.id === "library" || !link.derived
                    || (link.via || []).every(path => members.has(path))))))
        const refs = new Set(links.map(link => incoming ? link.source : link.target))
        return [...refs].filter(target => target !== ref && nodes.has(target))
            .map(target => ({ref: target, title: nodes.get(target).title,
                kind: nodes.get(target).kind,
                detail: [...new Set(links.filter(link => link.derived
                    && (incoming ? link.source : link.target) === target)
                    .map(link => ((link.via || []).length
                        ? "via " + link.via.map(path => articleLabel(path)).join(" → ")
                        : "Applicable procedure")
                        + (link.for_agent ? " · " + articleLabel(link.for_agent) : "")))].join("; ")}))
            .sort((left, right) => left.title.localeCompare(right.title)
                || left.ref.localeCompare(right.ref))
    }

    function loadArticleTitles(generation) {
        checkouts.refresh()
        const request = new XMLHttpRequest()
        request.open("GET", "http://127.0.0.1:8765/api/graph")
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE
                    || generation !== root.requestGeneration
                    || request.status < 200 || request.status >= 300) return
            try {
                const graph = JSON.parse(request.responseText)
                const titles = {}
                for (const node of graph.nodes || []) titles[node.id] = node.title
                for (const group of graph.navigation.groups || []) {
                    titles[group.root_ref] = group.title
                    for (const subject of group.subjects || []) {
                        titles[subject.id] = subject.title
                        if (subject.article_ref) titles[subject.article_ref] = subject.title
                    }
                }
                root.articleTitles = titles
                root.articleGraph = {nodes: graph.nodes || [], links: graph.links || [],
                    navigation: graph.navigation || {groups: []}}
            } catch (error) {}
        }
        request.send()
    }

    function loadDocument() {
        const ref = feedItemMode ? feedItemId : sourceMode ? sourceKey.trim() : articleRef.trim()
        requestGeneration += 1
        const generation = requestGeneration
        resetDocument()
        if (previewMode) {
            loading = false
            articleTitle = previewItem.title || "Untitled item"
            articleBody = previewItem.summary || "The publisher did not include a text summary in this feed."
            articleKind = "feed_preview"
            sourceMediaType = "text/plain"
            feedProvenance = previewItem
            return
        }
        if (!ref) { loading = false; return }
        const expectedSourceKey = sourceKey
        loading = true
        if (!feedItemMode) loadArticleTitles(generation)
        const request = new XMLHttpRequest()
        request.open("GET", "http://127.0.0.1:8765/"
            + (feedItemMode ? "api/feeds/items/" : sourceMode ? "api/source-files/" : "api/articles/")
            + (feedItemMode ? encodeURIComponent(ref) : encodeURI(ref))
            + (!root.sourceMode && root.graphId && root.graphId !== "library"
                ? "?graph_id=" + encodeURIComponent(root.graphId) : ""))
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
                if (root.feedItemMode) {
                    if (document.source_id !== ref || typeof document.content_text !== "string"
                            || document.source_path !== expectedSourceKey) throw new Error("Invalid feed item")
                    root.articleTitle = typeof document.title === "string" ? document.title : ref
                    root.articleKind = "source"
                    root.articleBody = document.content_text
                    root.documentPath = document.source_path
                    root.sourceStorage = "raw"
                    root.sourceMediaType = "text/plain"
                    root.feedProvenance = document
                } else if (root.sourceMode) {
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
                    root.articleManagedBy = typeof document.managed_by === "string"
                        ? document.managed_by : ""
                    root.articleReadOnly = document.read_only === true || root.articleManagedBy === "system"
                    root.autoCurateSupported = !root.articleReadOnly && document.auto_curate_supported === true
                    root.autoCurateEnabled = document.auto_curate === true
                    root.documentPath = typeof document.ref === "string" ? document.ref : ref
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
        if (sourceMode || articleReadOnly || loading || saving || !articleRef) return
        draftTitle = articleTitle
        draftBody = articleBody
        noticeMessage = ""
        editing = true
    }

    function setAutoCurate(enabled) {
        if (sourceMode || articleReadOnly || !autoCurateSupported || curationBusy || loading || editing || !articleRef) return
        const ref = articleRef
        const generation = requestGeneration
        curationBusy = true
        errorMessage = ""
        noticeMessage = ""
        const request = new XMLHttpRequest()
        request.open("PUT", "http://127.0.0.1:8765/api/articles/" + encodeURI(ref) + "/auto-curate")
        request.setRequestHeader("content-type", "application/json")
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE
                    || generation !== root.requestGeneration || root.articleRef !== ref || root.sourceMode) return
            root.curationBusy = false
            if (request.status < 200 || request.status >= 300) {
                root.errorMessage = request.responseText || "Auto-curation permission could not be saved."
                return
            }
            root.loadDocument()
            root.noticeMessage = "Auto-curation permission saved. Task triggers are unchanged."
        }
        request.send(JSON.stringify({"enabled": enabled}))
    }

    function cancelEdit() {
        draftTitle = articleTitle
        draftBody = articleBody
        noticeMessage = ""
        editing = false
    }

    function saveArticle() {
        if (sourceMode || articleReadOnly || saving || !articleRef || !draftTitle.trim()) return
        const ref = articleRef
        const generation = requestGeneration
        const title = draftTitle.trim()
        const body = draftBody
        saving = true
        noticeMessage = ""
        errorMessage = ""
        const request = new XMLHttpRequest()
        request.open("PATCH", "http://127.0.0.1:8765/api/articles/" + encodeURI(ref))
        request.setRequestHeader("content-type", "application/json")
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE
                    || generation !== root.requestGeneration
                    || root.selectionKind !== "article" || root.articleRef !== ref) return
            root.saving = false
            if (request.status < 200 || request.status >= 300) {
                root.errorMessage = request.responseText || "Article could not be saved."
                return
            }
            root.articleTitle = title
            root.articleBody = body
            root.editing = false
            root.noticeMessage = "Article saved."
        }
        request.send(JSON.stringify({"title": title, "body": body}))
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

    function openArticleLink(link) {
        const value = String(link)
        if (value.startsWith("obsidience-ref:")) {
            presentArticle(decodeURIComponent(value.slice("obsidience-ref:".length)))
            return
        }
        if (value.startsWith("source://")) {
            openSourceCitation(value)
            return
        }
        // Qt parses Markdown. This only resolves its document URL within our vault.
        if (/^[a-z][a-z0-9+.-]*:/i.test(value) || value.startsWith("//")) return
        const path = decodeURIComponent(value.split("#")[0])
        if (!path.toLowerCase().endsWith(".md")) return
        const parts = path.startsWith("/") ? [] : articleRef.split("/").slice(0, -1)
        for (const part of path.split("/")) {
            if (!part || part === ".") continue
            if (part === "..") { if (!parts.length) return; parts.pop() }
            else parts.push(part)
        }
        presentArticle(parts.join("/").slice(0, -3))
    }

    function openSourceCitation(citation) {
        if (!/^source:\/\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(citation)
                || selectionKind !== "article" || shellSocket.status !== WebSocket.Open) return
        const id = citation.slice("source://".length).toLowerCase()
        const generation = requestGeneration
        const citationGeneration = ++citationRequestGeneration
        const ref = articleRef
        const graph = graphId
        const request = new XMLHttpRequest()
        request.open("GET", "http://127.0.0.1:8765/api/sources/" + id)
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE || !root
                    || generation !== root.requestGeneration
                    || citationGeneration !== root.citationRequestGeneration
                    || root.selectionKind !== "article" || root.articleRef !== ref || root.graphId !== graph) return
            if (request.status < 200 || request.status >= 300) {
                root.errorMessage = "The cited Source could not be opened."
                return
            }
            try {
                const source = JSON.parse(request.responseText)
                const path = source.source_path
                if (source.id !== id || source.citation !== "source://" + id || source.immutable !== true
                        || typeof path !== "string" || path.length > 4096
                        || !(path.startsWith("obsidience/evidence/")
                            || path.startsWith("obsidience/state/system/snapshots/"))
                        || /[\\?#\u0000]/.test(path)
                        || path.split("/").some(part => !part || part === "." || part === "..")) {
                    throw new Error("Invalid Source identity")
                }
                if (shellSocket.status !== WebSocket.Open) throw new Error("Reader unavailable")
                root.errorMessage = ""
                shellSocket.sendTextMessage(JSON.stringify({
                    "schema": "obsidience.shell.command.v1", "type": "pane.present", "pane_id": "reader",
                    "selection": {"kind": "source", "key": path}
                }))
            } catch (error) {
                root.errorMessage = "The cited Source identity could not be verified."
            }
        }
        request.send()
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

    onArticleRefChanged: { if (selectionKind === "article") Qt.callLater(root.loadDocument) }
    onSourceKeyChanged: { if (selectionKind === "source") Qt.callLater(root.loadDocument) }
    onFeedItemIdChanged: { if (sourceMode) Qt.callLater(root.loadDocument) }
    Component.onCompleted: loadDocument()

    WebSocket {
        id: shellSocket
        url: "ws://127.0.0.1:8768"
        requestedSubprotocols: ["obsidience.shell.v1"]
        active: root.followShellSelection
        onTextMessageReceived: message => root.applyShellEvent(message)
        onStatusChanged: status => {
            if (root.followShellSelection && (status === WebSocket.Closed || status === WebSocket.Error)) {
                reconnectTimer.restart()
            }
        }
    }

    Timer {
        id: reconnectTimer
        interval: 500
        repeat: false
        onTriggered: { if (root.followShellSelection) { shellSocket.active = false; shellSocket.active = true } }
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
                text: !root.followShellSelection && root.sourceMode ? "Select a captured item to read it here."
                    : "Select an article in Knowledge, a file in Source, or an item in Feeds to read it here."
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
                        visible: root.sourceMode || root.articleReadOnly || root.indexArticle
                        width: parent.width
                        text: root.sourceMode ? root.sourceClass
                            : root.articleManagedBy === "system" ? "Generated from System evidence · read only"
                            : root.articleReadOnly ? "Read only" : "Knowledge index"
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
                        textFormat: Text.PlainText
                        color: root.sourceMode ? "#f5f3ff" : "#ecfeff"
                        wrapMode: Text.WrapAtWordBoundaryOrAnywhere
                        font.family: "JetBrains Mono"
                        font.pixelSize: root.indexArticle ? 22 : 18
                        font.weight: Font.DemiBold
                        font.letterSpacing: root.indexArticle ? 0.55 : 0.72
                        lineHeightMode: Text.ProportionalHeight
                        lineHeight: root.indexArticle ? 1.1 : 1.25
                    }
                    AgentCheckoutButtons {
                        visible: !root.sourceMode && !root.editing && root.articleRef !== ""
                        controller: checkouts
                        node: ({ref: root.documentPath || root.articleRef, kind: root.articleKind})
                        agents: (root.articleGraph.navigation || {}).groups || []
                        buttonSize: 24
                    }
                    Text {
                        visible: !root.sourceMode && checkouts.error !== ""
                        width: parent.width
                        text: checkouts.error
                        textFormat: Text.PlainText
                        color: "#fda4af"
                        wrapMode: Text.Wrap
                        font.family: "JetBrains Mono"
                        font.pixelSize: 9
                    }
                    Text {
                        visible: root.sourceMode
                        width: parent.width
                        text: root.previewMode ? [root.feedProvenance.feed_title, root.feedProvenance.published,
                            root.feedProvenance.reporting_url].filter(value => !!value).join(" · ")
                            : root.feedItemMode ? [root.feedProvenance.feed_name, root.feedProvenance.published,
                            root.feedProvenance.reporting_url].filter(value => !!value).join(" · ")
                            + "\n" + root.documentPath : root.documentPath
                        textFormat: Text.PlainText
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

                    CheckBox {
                        id: autoCurateControl
                        visible: !root.sourceMode && !root.articleReadOnly && root.autoCurateSupported && !root.editing
                        enabled: !root.loading && !root.curationBusy
                        height: 23
                        checked: root.autoCurateEnabled
                        nextCheckState: function() { return checkState }
                        onClicked: root.setAutoCurate(!root.autoCurateEnabled)
                        spacing: 5
                        leftPadding: 0
                        rightPadding: 0
                        indicator: Rectangle {
                            y: (autoCurateControl.height - height) / 2
                            width: 14; height: 14; radius: 2
                            color: autoCurateControl.checked ? "#67e8f9" : "#061019"
                            border.width: 1
                            border.color: autoCurateControl.checked ? "#67e8f9" : "#6667e8f9"
                            Text {
                                anchors.centerIn: parent
                                visible: autoCurateControl.checked
                                text: "✓"; color: "#031017"; font.pixelSize: 10; font.bold: true
                            }
                        }
                        contentItem: Text {
                            leftPadding: 19
                            text: root.curationBusy ? "SAVING…" : "AUTO-CURATE"
                            color: "#b3a5f3fc"; font.family: "JetBrains Mono"
                            font.pixelSize: 8; font.letterSpacing: 0.72
                            verticalAlignment: Text.AlignVCenter
                        }
                        ToolTip.visible: hovered
                        ToolTip.text: "Allow supported automatic maintenance here. Child settings may override it; Task triggers stay unchanged."
                    }

                    Repeater {
                        model: root.sourceMode && !root.feedItemMode && !root.previewMode ? [
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
                        visible: !root.sourceMode && !root.articleReadOnly && !root.editing
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
                            text: root.articleLabel(sourceArticleButton.modelData)
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
                visible: !root.editing && (!root.sourceMode || root.feedItemMode || root.previewMode) && root.articleTitle !== ""
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
                    objectName: "reader-prose"
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: root.indexArticle ? 15 : 0
                    textFormat: root.feedItemMode || root.previewMode ? Text.PlainText : Text.MarkdownText
                    text: root.feedItemMode || root.previewMode ? root.articleBody : root.wikiMarkdown(root.articleBody)
                    color: "#d1ecfeff"
                    linkColor: "#a5f3fc"
                    wrapMode: Text.Wrap
                    font.family: "JetBrains Mono"
                    font.pixelSize: 13
                    lineHeightMode: Text.FixedHeight
                    lineHeight: 24
                    onLinkActivated: link => root.openArticleLink(link)
                }
            }

            Rectangle {
                visible: root.sourceMode && !root.feedItemMode && !root.previewMode && root.articleTitle !== ""
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
                            text: root.articleLabel(childButton.modelData)
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

            Repeater {
                model: root.editing || root.sourceMode ? [] : [
                    {title: "LINKS TO", articles: root.articleLinks},
                    {title: "LINKED FROM", articles: root.articleBacklinks}
                ]
                delegate: Column {
                    id: connectionSection
                    required property var modelData
                    visible: modelData.articles.length > 0
                    width: documentColumn.width
                    spacing: 7
                    Text {
                        text: connectionSection.modelData.title
                        color: "#7367e8f9"
                        font.family: "JetBrains Mono"
                        font.pixelSize: 8
                        font.letterSpacing: 1.28
                    }
                    Repeater {
                        model: connectionSection.modelData.articles
                        delegate: Rectangle {
                            id: connectionButton
                            required property var modelData
                            width: documentColumn.width
                            height: modelData.detail ? 44 : 28
                            radius: 4
                            color: connectionMouse.containsMouse ? "#1267e8f9" : "#08071119"
                            border.width: 1
                            border.color: connectionMouse.containsMouse ? "#6667e8f9" : "#2667e8f9"
                            Text {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                height: 28
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                verticalAlignment: Text.AlignVCenter
                                text: connectionButton.modelData.title + " · " + connectionButton.modelData.kind
                                color: "#b3cffafe"
                                elide: Text.ElideRight
                                font.family: "JetBrains Mono"
                                font.pixelSize: 9
                            }
                            Text {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                anchors.leftMargin: 10
                                anchors.rightMargin: 10
                                height: 18
                                text: connectionButton.modelData.detail
                                visible: text.length > 0
                                color: "#7367e8f9"
                                elide: Text.ElideRight
                                font.family: "JetBrains Mono"
                                font.pixelSize: 8
                            }
                            ToolTip.visible: connectionMouse.containsMouse && modelData.detail.length > 0
                            ToolTip.text: modelData.detail
                            MouseArea {
                                id: connectionMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.presentArticle(connectionButton.modelData.ref)
                            }
                        }
                    }
                }
            }
        }
    }
}
