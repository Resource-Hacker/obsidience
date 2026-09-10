pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtWebSockets
import "../../components/visual"
import "../../workspace"

Rectangle {
    id: root

    required property PaneDockLayout dockLayout
    required property string surfaceId
    readonly property string apiBase: "http://127.0.0.1:8765"
    property bool manageMode: false
    property string feedDetailTab: "preview"
    property bool sourceExpanded: true
    property var previewData: null
    property bool previewLoading: false
    property string previewError: ""
    property int previewGeneration: 0
    property var connections: []
    property var feeds: []
    property var providers: []
    property var destinationNodes: []
    property int revision: -1
    property string selectedFeedId: ""
    property bool loading: false
    property bool busy: false
    property string busyLabel: ""
    property string errorMessage: ""
    property string notice: ""
    property int requestGeneration: 0
    property string draftName: ""
    property string draftUrl: ""
    property bool draftEnabled: true
    property string draftConnectionId: ""
    property string draftDestinationRef: ""
    property int draftInterval: 30
    property int draftItemLimit: 10
    property int draftMaxActiveArticles: 10
    property string draftDistillInstructions: ""
    readonly property var selectedFeed: feeds.find(row => row.id === selectedFeedId) || null
    readonly property var feedConnections: connections.filter(row => row.kind === "rss")
    readonly property var presets: presetRows()
    readonly property var destinationOptions: destinationNodes.filter(node => node.available === true
        || (selectedFeed && node.ref === selectedFeed.destination_ref))
        .map(node => Object.assign({}, node, {"label": destinationLabel(node)}))
    readonly property var draftDestinationNode: destinationNodes.find(node => node.ref === draftDestinationRef) || null
    readonly property bool destinationPermissionReady: !!selectedFeed && !!selectedFeed.destination_ref
        && draftDestinationRef === selectedFeed.destination_ref && !selectedFeed.destination_error
        && selectedFeed.auto_curate_supported === true && typeof selectedFeed.auto_curate === "boolean"
    readonly property bool destinationAutoCurate: destinationPermissionReady ? selectedFeed.auto_curate === true
        : !!draftDestinationNode && draftDestinationNode.auto_curate === true
    readonly property int instructionLength: Array.from(draftDistillInstructions).length
    readonly property bool hasUnsavedChanges: draftDiffers()
    readonly property bool canPreview: !busy && !loading && !previewLoading
        && revision >= 0 && draftConnectionId.length > 0 && draftUrl.trim().length > 0
    readonly property bool canSave: !busy && !loading && revision >= 0
        && draftName.trim().length > 0 && draftUrl.trim().length > 0
        && draftConnectionId.length > 0 && draftDestinationRef.length > 0
        && !!draftDestinationNode && draftDestinationNode.available === true
        && draftInterval >= 5 && draftInterval <= 1440 && draftItemLimit >= 1 && draftItemLimit <= 30
        && draftMaxActiveArticles >= 1 && draftMaxActiveArticles <= 1000 && instructionLength <= 500

    signal openCapturedItem(var item)
    signal openPreviewItem(var item)

    color: "#d0040c12"
    clip: true

    function connectionName(id) {
        const connection = connections.find(row => row.id === id)
        return connection ? connection.name : "Connection unavailable"
    }

    function destinationLabel(node) {
        const ancestry = node.ref.split("/").slice(0, -2).join(" / ")
        return node.title + (ancestry ? " · " + ancestry : "")
    }

    function timestamp(value) {
        if (value === undefined || value === null || value === "") return "Not checked"
        const date = new Date(typeof value === "number" && value < 100000000000 ? value * 1000 : value)
        return isNaN(date.getTime()) ? String(value) : date.toLocaleString()
    }

    function rowStatus(row) {
        if (row.running === true) return "Checking…"
        if (!row.enabled) return "Paused"
        if (row.connection_id && row.active === false) return "Connection paused"
        if (row.last_error) return "Check failed"
        if (row.status) return String(row.status).replace(/_/g, " ")
        return row.last_checked ? "Checked" : "Not checked"
    }

    function sameOrigin(first, second) {
        try {
            const a = new URL(first)
            const b = new URL(second)
            return (a.protocol === "https:" || a.protocol === "http:") && a.origin === b.origin
        } catch (error) { return false }
    }

    function presetRows() {
        const rows = [{"name": "Custom", "url": ""}]
        const connection = feedConnections.find(row => row.id === draftConnectionId)
        for (const provider of providers) for (const feed of provider.feeds || []) {
            if (connection && sameOrigin(connection.url, feed.url)) rows.push({
                "name": feed.name, "label": feed.name, "url": feed.url,
                "description": feed.description || provider.description || ""})
        }
        return rows
    }

    function offeringDescription() {
        const preset = presets.find(row => row.url === draftUrl.trim())
        return preset && preset.description ? preset.description
            : "Publisher titles, dates, links and any supplied text. Preview before collecting."
    }

    function usePreset(index) {
        const preset = presets[index]
        if (!preset || index === 0 || busy) return
        draftName = preset.label || preset.name
        draftUrl = preset.url
    }

    function loadDraft(row) {
        invalidatePreview()
        sourceExpanded = !row
        draftName = row ? row.name : ""
        draftEnabled = row ? row.enabled === true : true
        draftConnectionId = row ? row.connection_id : feedConnections.length ? feedConnections[0].id : ""
        const connection = feedConnections.find(item => item.id === draftConnectionId)
        draftUrl = row ? row.url : connection ? connection.url : ""
        draftInterval = row && Number.isInteger(row.interval_minutes) ? row.interval_minutes : 30
        draftItemLimit = row && Number.isInteger(row.item_limit) ? row.item_limit : 10
        draftMaxActiveArticles = row && Number.isInteger(row.max_active_articles) ? row.max_active_articles : 10
        draftDistillInstructions = row && typeof row.distill_instructions === "string" ? row.distill_instructions : ""
        draftDestinationRef = row && typeof row.destination_ref === "string" ? row.destination_ref : ""
    }

    function chooseFeedConnection(id) {
        const previous = feedConnections.find(row => row.id === draftConnectionId)
        const useConnectionEndpoint = !selectedFeed && (!draftUrl.trim()
            || (previous && draftUrl.trim() === previous.url))
        draftConnectionId = id
        const next = feedConnections.find(row => row.id === id)
        if (useConnectionEndpoint && next) draftUrl = next.url
    }

    function invalidatePreview() {
        ++previewGeneration
        previewData = null
        previewError = ""
        previewLoading = false
    }

    function previewUrlIdentity(value) {
        const url = new URL(value)
        url.hash = ""
        return url.href
    }

    function requestPreview() {
        if (!canPreview) return
        const generation = ++previewGeneration
        const context = {"revision": revision, "connection_id": draftConnectionId,
            "url": draftUrl.trim(), "item_limit": draftItemLimit}
        previewLoading = true
        previewError = ""
        const xhr = new XMLHttpRequest()
        xhr.open("POST", apiBase + "/api/feeds/preview")
        xhr.setRequestHeader("content-type", "application/json")
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE || !root || generation !== root.previewGeneration) return
            root.previewLoading = false
            if (xhr.status < 200 || xhr.status >= 300) {
                root.previewData = null
                root.previewError = root.requestError(xhr)
                return
            }
            try {
                const data = JSON.parse(xhr.responseText)
                if (data.revision !== context.revision || data.connection_id !== context.connection_id
                        || root.previewUrlIdentity(data.url) !== root.previewUrlIdentity(context.url)
                        || !Array.isArray(data.entries) || data.entries.length > 30
                        || !Number.isInteger(data.available_count) || data.available_count < 0
                        || data.entries.some(item => typeof item.title !== "string" || typeof item.summary !== "string")) {
                    throw new Error("Invalid preview")
                }
                root.previewData = data
                root.sourceExpanded = false
                if (!root.draftName.trim() && typeof data.feed_title === "string") root.draftName = data.feed_title.slice(0, 160)
            } catch (error) {
                root.previewData = null
                root.previewError = "The publisher preview could not be read. Try refreshing it."
            }
        }
        xhr.send(JSON.stringify(context))
    }

    function draftDiffers() {
        const row = selectedFeed
        if (!row) return !!draftName.trim() || !!draftUrl.trim() || !!draftDistillInstructions
        if (draftName.trim() !== row.name || draftUrl.trim() !== row.url || draftEnabled !== row.enabled) return true
        return draftConnectionId !== row.connection_id || draftDestinationRef !== row.destination_ref
            || draftInterval !== row.interval_minutes || draftItemLimit !== row.item_limit
            || draftMaxActiveArticles !== row.max_active_articles
            || draftDistillInstructions !== (row.distill_instructions || "")
    }

    function openFeed(id, tab) {
        if (busy) return
        manageMode = true
        selectedFeedId = id || ""
        errorMessage = ""
        notice = ""
        loadDraft(selectedFeed)
        feedDetailTab = tab === "settings" ? "settings" : "preview"
    }

    function selectRow(id) { openFeed(id, "preview") }
    function newRecord() { openFeed("", "preview") }

    function requestError(xhr) {
        try {
            const response = JSON.parse(xhr.responseText || "{}")
            if (typeof response.detail === "string") return response.detail.slice(0, 500)
        } catch (error) {}
        return "Request failed (HTTP " + xhr.status + ")."
    }

    function applySnapshot(payload, preserveDraft) {
        if (!payload || !Number.isInteger(payload.revision) || payload.revision < 0
                || !Array.isArray(payload.connections) || !Array.isArray(payload.feeds)
                || !Array.isArray(payload.providers) || !Array.isArray(payload.destination_nodes)) throw new Error("Invalid feed response")
        const previousSelection = selectedFeedId
        revision = payload.revision
        connections = payload.connections
        feeds = payload.feeds
        providers = payload.providers
        destinationNodes = payload.destination_nodes
        if (selectedFeedId && !selectedFeed) selectedFeedId = ""
        if (selectedFeed) {
            if (preserveDraft !== true) loadDraft(selectedFeed)
        } else if (previousSelection) loadDraft(null)
        else if (!draftConnectionId && feedConnections.length) loadDraft(null)
    }

    function refresh(preserveDraft) {
        if (busy) return
        const generation = ++requestGeneration
        loading = true
        const xhr = new XMLHttpRequest()
        xhr.open("GET", apiBase + "/api/connections")
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE || !root || generation !== root.requestGeneration) return
            root.loading = false
            if (xhr.status < 200 || xhr.status >= 300) {
                root.errorMessage = root.requestError(xhr)
                return
            }
            try {
                root.applySnapshot(JSON.parse(xhr.responseText), preserveDraft)
                root.errorMessage = ""
            } catch (error) {
                root.errorMessage = "The Harness returned invalid feed metadata."
            }
        }
        xhr.send()
    }

    function mutate(method, path, body, label, creating) {
        if (busy || loading || revision < 0) return
        busy = true
        busyLabel = label
        errorMessage = ""
        notice = ""
        ++requestGeneration
        const xhr = new XMLHttpRequest()
        xhr.open(method, apiBase + path)
        if (body !== null) xhr.setRequestHeader("content-type", "application/json")
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE || !root) return
            root.busy = false
            root.busyLabel = ""
            if (xhr.status < 200 || xhr.status >= 300) {
                root.errorMessage = root.requestError(xhr)
                return
            }
            try {
                const payload = JSON.parse(xhr.responseText)
                if (creating && typeof payload.created_id === "string") root.selectedFeedId = payload.created_id
                root.applySnapshot(payload)
                root.notice = root.selectedFeed && root.selectedFeed.last_error ? "" : label + " finished."
                if (label === "Save" && (path === "/api/feeds" || path.startsWith("/api/feeds/"))) {
                    root.notice = "Settings saved."
                    const retention = payload.retention_result
                    const statuses = {"blocked": "Article retirement is blocked.",
                        "review_required": "Article retirement needs review.",
                        "over_limit": "The feed remains over its active article limit."}
                    if (retention && statuses[retention.retention_status]) {
                        const detail = retention.retention_detail || retention.blocked_reason
                            || (root.selectedFeed && root.selectedFeed.retention_detail)
                        root.notice += " " + statuses[retention.retention_status]
                            + (typeof detail === "string" && detail ? " " + detail : "")
                    }
                }
                if (path.endsWith("/check")) browser.refresh()
            } catch (error) {
                root.revision = -1
                root.errorMessage = "The Harness returned invalid feed metadata. Refresh the list before making another change."
            }
        }
        xhr.send(body === null ? null : JSON.stringify(body))
    }

    function saveRecord() {
        if (!canSave) return
        const body = {"revision": revision, "name": draftName.trim(), "url": draftUrl.trim(),
            "enabled": draftEnabled, "connection_id": draftConnectionId, "interval_minutes": draftInterval,
            "item_limit": draftItemLimit, "destination_ref": draftDestinationRef,
            "max_active_articles": draftMaxActiveArticles, "distill_instructions": draftDistillInstructions}
        mutate(selectedFeedId ? "PATCH" : "POST", "/api/feeds" + (selectedFeedId ? "/" + encodeURIComponent(selectedFeedId) : ""),
            body, "Save", !selectedFeedId)
    }

    function setDestinationAutoCurate(enabled) {
        if (busy || loading || !destinationPermissionReady || typeof enabled !== "boolean") return
        const ref = selectedFeed.destination_ref
        const generation = ++requestGeneration
        busy = true
        busyLabel = "Saving Auto-curate"
        errorMessage = ""
        notice = ""
        const xhr = new XMLHttpRequest()
        xhr.open("PUT", apiBase + "/api/articles/" + ref.split("/").map(encodeURIComponent).join("/") + "/auto-curate")
        xhr.setRequestHeader("content-type", "application/json")
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE || !root || generation !== root.requestGeneration) return
            root.busy = false
            root.busyLabel = ""
            if (xhr.status < 200 || xhr.status >= 300) {
                root.errorMessage = root.requestError(xhr)
                return
            }
            try {
                const result = JSON.parse(xhr.responseText)
                if (result.article !== ref || result.enabled !== enabled) throw new Error("Invalid permission response")
                root.notice = "Auto-curate saved."
            } catch (error) {
                root.errorMessage = "The Harness returned an invalid Auto-curate response. Refresh the list to check the destination."
                return
            }
            root.refresh(true)
        }
        xhr.send(JSON.stringify({"enabled": enabled}))
    }

    function checkNow() {
        if (!selectedFeed || hasUnsavedChanges) return
        mutate("POST", "/api/feeds/" + encodeURIComponent(selectedFeedId) + "/check", null, "Collection", false)
    }

    function removeRecord() {
        if (!selectedFeed) return
        mutate("DELETE", "/api/feeds/" + encodeURIComponent(selectedFeedId) + "?revision=" + revision, null, "Remove", false)
    }

    function sendShellCommand(command) {
        if (shellSocket.status !== WebSocket.Open) {
            errorMessage = "Reader bridge is unavailable."
            return
        }
        errorMessage = ""
        shellSocket.sendTextMessage(JSON.stringify(command))
    }

    function readerText(value, limit) { return Array.from(String(value || "")).slice(0, limit).join("") }

    function presentCapturedItem(item) {
        if (!item || typeof item.source_path !== "string" || typeof item.source_id !== "string"
                || !/^[A-Za-z0-9_-]{1,128}$/.test(item.source_id)) return
        openCapturedItem(item)
        sendShellCommand({"schema": "obsidience.shell.command.v1", "type": "pane.present", "pane_id": "reader",
            "selection": {"kind": "source", "key": item.source_path, "feed_item_id": item.source_id}})
    }

    function presentPreviewItem(item) {
        if (!item) return
        const value = {"title": readerText(item.title, 300), "summary": readerText(item.summary, 4000),
            "reporting_url": readerText(item.reporting_url, 2048), "published": readerText(item.published, 100),
            "feed_title": readerText(item.feed_title, 300), "feed_url": readerText(item.feed_url, 2048)}
        openPreviewItem(value)
        sendShellCommand({"schema": "obsidience.shell.command.v1", "type": "pane.present", "pane_id": "reader",
            "selection": {"kind": "feed_preview", "item": value}})
    }

    function openConnectionSettings() {
        sendShellCommand({"schema": "obsidience.shell.command.v1", "type": "pane.present", "pane_id": "settings",
            "selection": {"kind": "settings", "section": "connections"}})
    }

    function applyShellEvent(message) {
        if (typeof message !== "string" || message.length > 65536) return
        let event
        try { event = JSON.parse(message) } catch (error) { return }
        if (!event || event.schema !== "obsidience.shell.event.v1") return
        if (event.type === "pane.dock.state" && event.layout) dockLayout.applyRecord(event.layout)
        if (event.type === "pane.state" && event.pane && event.pane.pane_id === "reader"
                && event.selection && event.selection.feed_item_id) browser.selectedItemId = event.selection.feed_item_id
    }

    function refreshBrowse() { refresh(true); browser.refresh() }

    function activeArticleLabel(feed) {
        const count = Number.isInteger(feed.active_article_count) ? feed.active_article_count : "?"
        return count + " / " + feed.max_active_articles + " active articles"
    }

    function retentionLabel(feed) {
        return {"within_limit":"Within limit", "review_required":"Archive needs review", "blocked":"Archive blocked",
            "over_limit":"Over article limit"}[feed.retention_status] || "Retention unavailable"
    }

    onDraftUrlChanged: invalidatePreview()
    onDraftConnectionIdChanged: invalidatePreview()
    onSelectedFeedIdChanged: invalidatePreview()
    onRevisionChanged: invalidatePreview()
    Component.onCompleted: refresh()

    WebSocket {
        id: shellSocket
        url: "ws://127.0.0.1:8768"
        requestedSubprotocols: ["obsidience.shell.v1"]
        active: root.visible
        onTextMessageReceived: message => root.applyShellEvent(message)
        onStatusChanged: status => {
            if (root.visible && (status === WebSocket.Closed || status === WebSocket.Error)) reconnect.restart()
        }
    }
    Timer {
        id: reconnect
        interval: 500
        repeat: false
        onTriggered: { if (root.visible) { shellSocket.active = false; shellSocket.active = true } }
    }

    component Caption: Text {
        color: "#97aebb"
        textFormat: Text.PlainText
        font.pixelSize: 13
        wrapMode: Text.Wrap
        lineHeight: 1.2
    }
    component SectionTitle: Text {
        textFormat: Text.PlainText
        color: "#e0f0f5"
        font.pixelSize: 16
        font.weight: Font.DemiBold
    }
    component Action: GlowButton {
        uppercase: false
        textPixelSize: 12
        textLetterSpacing: 0
        idleTextOpacity: 0.9
        implicitHeight: 34
    }
    component NavigationTab: TabButton {
        id: tab
        implicitWidth: Math.max(76, implicitContentWidth + 24)
        implicitHeight: 36
        contentItem: Text {
            text: tab.text
            textFormat: Text.PlainText
            color: tab.checked ? "#d8f5fb" : "#91aeba"
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            font.pixelSize: 14
            font.weight: tab.checked ? Font.DemiBold : Font.Normal
        }
        background: Item {
            Rectangle { anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; height: 2; color: tab.checked ? "#67e8f9" : "transparent" }
        }
    }
    component Choice: GlowComboBox {
        textPixelSize: 12
        textOpacity: 0.95
        implicitHeight: 36
    }
    component Field: TextField {
        color: "#e0f7ff"
        placeholderTextColor: "#70899a"
        font.pixelSize: 14
        selectByMouse: true
        implicitHeight: 38
        leftPadding: 10
        rightPadding: 10
        background: Rectangle { radius: 5; color: "#091722"; border.color: "#355369" }
    }
    component NumberField: SpinBox {
        palette.base: "#091722"
        palette.button: "#15303e"
        palette.buttonText: "#b7e3ee"
        palette.text: "#d9f5ff"
        palette.mid: "#284756"
        palette.highlight: "#67e8f9"
        font.pixelSize: 13
        implicitWidth: 128
        implicitHeight: 36
    }
    component Toggle: CheckBox {
        font.pixelSize: 13
        palette.windowText: "#d2e7ef"
        palette.base: "#091722"
        palette.button: "#15303e"
        palette.light: "#284756"
        palette.text: "#d9f5ff"
        palette.highlight: "#67e8f9"
    }
    component Divider: Rectangle {
        Layout.fillWidth: true
        Layout.preferredHeight: 1
        Layout.topMargin: 8
        Layout.bottomMargin: 8
        color: "#243743"
    }

    Rectangle {
        id: moduleHeader
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        height: 30
        color: "#091823"
        PaneModuleHeader {
            anchors.fill: parent; anchors.leftMargin: 8; anchors.rightMargin: 8
            moduleId: "feeds"; title: "Feeds"; tint: "#67e8f9"
            dockLayout: root.dockLayout; surfaceId: root.surfaceId
            countText: root.loading ? "LOADING" : String(root.feeds.length)
            onCommandRequested: command => root.sendShellCommand(command)
        }
    }
    FeedBrowser {
        id: browser
        objectName: "feed-browser"
        anchors.left: parent.left; anchors.right: parent.right
        anchors.top: moduleHeader.bottom; anchors.bottom: parent.bottom
        visible: !root.manageMode
        apiBase: root.apiBase
        actionError: root.errorMessage
        connections: root.connections
        feeds: root.feeds
        onOpenCapturedItem: item => root.presentCapturedItem(item)
        onManageFeedRequested: (id, tab) => root.openFeed(id, tab)
        onRefreshRequested: root.refreshBrowse()
        onConnectionSettingsRequested: root.openConnectionSettings()
    }
    ColumnLayout {
        anchors.left: parent.left; anchors.right: parent.right
        anchors.top: moduleHeader.bottom; anchors.bottom: parent.bottom
        anchors.margins: 12
        visible: root.manageMode
        spacing: 10
        Flow {
            Layout.fillWidth: true; spacing: 8
            Action { text: "Back to items"; enabled: !root.busy; onClicked: { root.manageMode = false; browser.refresh() } }
            Action { text: "New feed"; enabled: !root.busy && !root.loading; onClicked: root.newRecord() }
            Action { text: "Reload"; enabled: !root.busy && !root.loading; onClicked: root.refresh() }
        }
        Choice {
            objectName: "feed-record-picker"
            Layout.fillWidth: true
            model: root.feeds; textRole: "name"
            currentIndex: root.feeds.findIndex(row => row.id === root.selectedFeedId)
            displayText: currentIndex >= 0 ? currentText : "New feed"
            enabled: !root.busy
            onActivated: index => root.openFeed(root.feeds[index].id, "preview")
        }
        RowLayout {
            Layout.fillWidth: true
            TabBar {
                objectName: "feed-detail-navigation"
                Layout.preferredWidth: 174
                currentIndex: root.feedDetailTab === "preview" ? 0 : 1
                onCurrentIndexChanged: {
                    if (currentIndex === 0 || currentIndex === 1) {
                        const tab = currentIndex === 0 ? "preview" : "settings"
                        if (root.feedDetailTab !== tab) root.feedDetailTab = tab
                    }
                }
                background: Item {}
                NavigationTab { objectName: "feed-preview-tab"; text: "Preview" }
                NavigationTab { objectName: "feed-settings-tab"; text: "Settings" }
            }
            Item { Layout.fillWidth: true }
        }
        Caption { Layout.fillWidth: true; visible: root.loading || root.busy; text: root.busy ? root.busyLabel + "…" : "Loading…" }
        Caption { Layout.fillWidth: true; visible: !!root.errorMessage; text: root.errorMessage; color: "#fda4af" }
        Caption { Layout.fillWidth: true; visible: !!root.notice; text: root.notice; color: "#86efac" }
        ScrollView {
            id: editorScroll
            objectName: "feed-editor"
            Layout.fillWidth: true; Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true
            ColumnLayout {
                width: editorScroll.availableWidth
                spacing: 12
                        ColumnLayout {
                            Layout.fillWidth: true
                            visible: root.feedDetailTab === "preview"
                            spacing: 10
                            SectionTitle { Layout.fillWidth: true; text: root.sourceExpanded ? "Publisher source" : root.previewData && root.previewData.feed_title ? root.previewData.feed_title : root.connectionName(root.draftConnectionId); elide: Text.ElideRight }
                            Flow {
                                Layout.fillWidth: true; spacing: 8
                                Action { objectName: "feed-change-source"; text: root.sourceExpanded ? "Done" : "Change source"; enabled: !root.busy; onClicked: root.sourceExpanded = !root.sourceExpanded }
                                Action { objectName: "refresh-feed-preview-compact"; visible: !root.sourceExpanded; text: root.previewLoading ? "Loading…" : root.previewData ? "Refresh preview" : "Preview feed"; enabled: root.canPreview; emphasized: true; onClicked: root.requestPreview() }
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                visible: root.sourceExpanded
                                spacing: 10
                            GridLayout {
                                Layout.fillWidth: true
                                columns: editorScroll.availableWidth >= 550 ? 2 : 1
                                columnSpacing: 16; rowSpacing: 10
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 5
                                    Caption { text: "Connection" }
                                    Choice { objectName: "feed-connection"; Layout.fillWidth: true; model: root.feedConnections; textRole: "name"; currentIndex: root.feedConnections.findIndex(row => row.id === root.draftConnectionId); enabled: !root.busy; onActivated: index => root.chooseFeedConnection(root.feedConnections[index].id) }
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 5
                                    Caption { text: "Publisher section" }
                                    Choice { objectName: "feed-preset"; Layout.fillWidth: true; model: root.presets; textRole: "name"; currentIndex: Math.max(0, root.presets.findIndex(row => row.url === root.draftUrl.trim())); enabled: !root.busy; onActivated: index => root.usePreset(index) }
                                }
                            }
                            Caption { Layout.fillWidth: true; visible: !root.feedConnections.length; text: "Add an RSS / Atom connection in Settings to preview a feed." }
                            Action { visible: !root.feedConnections.length; text: "Open connection settings"; onClicked: root.openConnectionSettings() }
                            Caption { text: "Feed endpoint" }
                            Field { objectName: "feed-url"; Layout.fillWidth: true; text: root.draftUrl; maximumLength: 2048; placeholderText: "https://publisher.example/feed.xml"; enabled: !root.busy; onTextEdited: root.draftUrl = text }
                            Caption { Layout.fillWidth: true; text: root.previewData && root.previewData.feed_description ? root.previewData.feed_description : root.offeringDescription() }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                visible: root.sourceExpanded
                                Action { objectName: "refresh-feed-preview"; text: root.previewLoading ? "Loading preview…" : root.previewData ? "Refresh preview" : "Preview feed"; enabled: root.canPreview; emphasized: true; onClicked: root.requestPreview() }
                                Caption { Layout.fillWidth: true; text: "Preview only. Nothing is collected." }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                Caption { Layout.fillWidth: true; text: "Items per check · Unchanged items are skipped" }
                                NumberField { objectName: "feed-item-limit"; from: 1; to: 30; value: root.draftItemLimit; editable: true; enabled: !root.busy; onValueModified: root.draftItemLimit = value }
                            }
                            FeedPreview {
                                objectName: "publisher-feed-preview"
                                Layout.fillWidth: true
                                previewData: root.previewData
                                itemLimit: root.draftItemLimit
                                loading: root.previewLoading
                                errorMessage: root.previewError
                                onOpenPreviewItem: item => root.presentPreviewItem(item)
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            visible: root.feedDetailTab === "settings"
                            spacing: 10
                            Caption { text: "Feed name" }
                            Field { objectName: "feed-name"; Layout.fillWidth: true; text: root.draftName; maximumLength: 160; enabled: !root.busy; onTextEdited: root.draftName = text }
                            Divider {}
                            SectionTitle { text: "Collection" }
                            Toggle { objectName: "collection-enabled"; text: "Collect automatically"; checked: root.draftEnabled; enabled: !root.busy; onToggled: root.draftEnabled = checked }
                            RowLayout {
                                Layout.fillWidth: true
                                Caption { Layout.fillWidth: true; text: "Check every (minutes)" }
                                NumberField { objectName: "feed-interval"; from: 5; to: 1440; value: root.draftInterval; editable: true; enabled: !root.busy; onValueModified: root.draftInterval = value }
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                Caption { Layout.fillWidth: true; text: "Up to " + root.draftItemLimit + " publisher items per check" }
                                Action { text: "Choose items"; onClicked: root.feedDetailTab = "preview" }
                            }
                            Caption { Layout.fillWidth: true; visible: !!root.selectedFeed; text: root.selectedFeed ? root.rowStatus(root.selectedFeed) + " · Last collection: " + root.timestamp(root.selectedFeed.last_checked) : ""; color: root.selectedFeed && root.selectedFeed.last_error ? "#fda4af" : "#97aebb" }
                            Caption { Layout.fillWidth: true; visible: !!root.selectedFeed && !!root.selectedFeed.last_error; text: root.selectedFeed ? root.selectedFeed.last_error || "" : ""; color: "#fda4af" }
                            Divider {}
                            SectionTitle { text: "Knowledge graph" }
                            Caption { text: "Place articles under" }
                            Choice {
                                objectName: "feed-destination"
                                Layout.fillWidth: true
                                model: root.destinationOptions; textRole: "label"
                                currentIndex: root.destinationOptions.findIndex(node => node.ref === root.draftDestinationRef)
                                displayText: currentIndex >= 0 ? currentText : "Choose a Knowledge node"
                                enabled: !root.busy && !root.loading
                                onActivated: index => root.draftDestinationRef = root.destinationOptions[index].ref
                            }
                            Toggle {
                                objectName: "feed-auto-curate"
                                text: "Publish automatically (Auto-curate)"
                                checked: root.destinationAutoCurate
                                enabled: !root.busy && !root.loading && root.destinationPermissionReady
                                nextCheckState: function() { return checkState }
                                onClicked: root.setDestinationAutoCurate(!root.destinationAutoCurate)
                            }
                            Caption {
                                Layout.fillWidth: true
                                color: root.selectedFeed && root.selectedFeed.destination_error ? "#fda4af" : "#97aebb"
                                text: !root.draftDestinationRef ? "Choose the node for new articles before saving."
                                    : !root.selectedFeed || root.draftDestinationRef !== root.selectedFeed.destination_ref
                                        ? "Save to use this node. Its existing Auto-curate setting is retained."
                                    : root.selectedFeed.destination_error || (!root.destinationPermissionReady ? "The node's permission is unavailable. Reload saved settings to check it."
                                        : root.destinationAutoCurate ? "This node publishes eligible articles automatically. The setting also applies to other feeds using it."
                                            : "Articles for this node wait for Review before publication.")
                            }
                            RowLayout {
                                Layout.fillWidth: true
                                Caption { Layout.fillWidth: true; text: "Keep active articles" }
                                NumberField { objectName: "feed-active-limit"; from: 1; to: 1000; value: root.draftMaxActiveArticles; editable: true; enabled: !root.busy; onValueModified: root.draftMaxActiveArticles = value }
                            }
                            Caption { Layout.fillWidth: true; text: "Older articles from this feed move to the archive as new ones arrive. Their full text and Sources are kept. Protected articles can require Review." }
                            Caption { Layout.fillWidth: true; visible: !!root.selectedFeed; text: root.selectedFeed ? root.activeArticleLabel(root.selectedFeed) + " · " + root.retentionLabel(root.selectedFeed) : "" }
                            Caption { Layout.fillWidth: true; visible: !!root.selectedFeed && !!root.selectedFeed.retention_detail && root.selectedFeed.retention_status !== "within_limit"; text: root.selectedFeed ? root.selectedFeed.retention_detail || "" : ""; color: "#fbbf24" }
                            Divider {}
                            SectionTitle { text: "Instructions for Darwin" }
                            Caption { Layout.fillWidth: true; text: "Tell Darwin what to focus on or how to format the distillation. Optional." }
                            TextArea {
                                objectName: "feed-distill-instructions"
                                Layout.fillWidth: true; Layout.preferredHeight: 120
                                text: root.draftDistillInstructions; textFormat: TextEdit.PlainText
                                placeholderText: "Example: Focus on what changed, explain the practical impact, and preserve important numbers."
                                enabled: !root.busy; selectByMouse: true; wrapMode: TextEdit.Wrap
                                color: "#e0f7ff"; placeholderTextColor: "#70899a"
                                font.pixelSize: 14
                                leftPadding: 12; rightPadding: 12; topPadding: 10; bottomPadding: 10
                                onTextChanged: root.draftDistillInstructions = text
                                background: Rectangle { radius: 5; color: "#091722"; border.color: root.instructionLength > 500 ? "#fda4af" : "#355369" }
                            }
                            Caption { Layout.fillWidth: true; text: root.instructionLength + " / 500 characters · " + (root.instructionLength > 500 ? "Shorten before saving." : "Applies to newly collected item versions."); color: root.instructionLength > 500 ? "#fda4af" : "#97aebb" }
                            Divider {}
                            RowLayout {
                                Layout.fillWidth: true; visible: !!root.selectedFeed
                                Caption { Layout.fillWidth: true; text: "Removing a feed stops future collection and keeps its history." }
                                Action { text: "Remove feed"; accent: "#fda4af"; enabled: !root.busy && !root.loading; onClicked: root.removeRecord() }
                            }
                        }


            }
        }
        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: "#28404e" }
        Caption { Layout.fillWidth: true; visible: !root.draftDestinationRef; text: "Choose a destination in Settings before saving." }
        Caption { visible: root.hasUnsavedChanges; text: "Unsaved changes"; color: "#f5cf89" }
        Flow {
            Layout.fillWidth: true; spacing: 8
            Action { objectName: "feed-save"; text: root.selectedFeedId ? "Save changes" : "Create feed"; enabled: root.canSave; emphasized: true; onClicked: root.saveRecord() }
            Action { objectName: "feed-reset"; text: "Reset"; enabled: !root.busy && !root.loading && root.hasUnsavedChanges; onClicked: { root.loadDraft(root.selectedFeed); root.errorMessage = ""; root.notice = "" } }
            Action { objectName: "feed-collect-now"; visible: !!root.selectedFeed; text: "Collect now"; enabled: !root.busy && !root.loading && !root.hasUnsavedChanges; onClicked: root.checkNow() }
        }
    }
}
