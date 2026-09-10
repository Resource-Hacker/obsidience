pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../../components/visual"

Rectangle {
    id: root
    readonly property string apiBase: "http://127.0.0.1:8765"
    property var connections: []
    property var providers: []
    property int revision: -1
    property string selectedConnectionId: ""
    property bool loading: false
    property bool busy: false
    property string busyLabel: ""
    property string errorMessage: ""
    property string notice: ""
    property int requestGeneration: 0
    property string draftName: ""
    property string draftUrl: ""
    property string draftKind: "rss"
    property string draftAuthMode: "none"
    property bool draftEnabled: true
    property string credentialSecret: ""
    readonly property var selectedConnection: connections.find(row => row.id === selectedConnectionId) || null
    readonly property var presets: [{"name":"Custom", "url":""}].concat(providers)
    readonly property bool credentialReady: !!selectedConnection
        && (selectedConnection.credential_set === true || selectedConnection.credential_ready === true)
    readonly property bool credentialContextSaved: !!selectedConnection
        && selectedConnection.auth_mode !== "none"
        && draftAuthMode === selectedConnection.auth_mode && draftUrl.trim() === selectedConnection.url
    readonly property bool hasUnsavedChanges: !selectedConnection ? !!draftName.trim() || !!draftUrl.trim()
        : draftName.trim() !== selectedConnection.name || draftUrl.trim() !== selectedConnection.url
            || draftKind !== selectedConnection.kind || draftAuthMode !== selectedConnection.auth_mode
            || draftEnabled !== selectedConnection.enabled
    readonly property bool canSave: !busy && !loading && revision >= 0
        && !!draftName.trim() && !!draftUrl.trim()

    color: "#d0040c12"
    clip: true

    function loadDraft(row) {
        credentialSecret = ""
        draftName = row ? row.name : ""
        draftUrl = row ? row.url : ""
        draftKind = row ? row.kind : "rss"
        draftAuthMode = row ? row.auth_mode : "none"
        draftEnabled = row ? row.enabled === true : true
    }

    function selectRow(id) {
        if (busy) return
        selectedConnectionId = id
        notice = ""
        errorMessage = ""
        loadDraft(selectedConnection)
    }

    function newRecord() { selectRow("") }

    function usePreset(index) {
        const preset = presets[index]
        if (!preset || index === 0 || busy) return
        draftName = preset.name
        draftUrl = preset.url
        draftKind = preset.kind || "rss"
        draftAuthMode = "none"
    }

    function sameOrigin(first, second) {
        try {
            const a = new URL(first)
            const b = new URL(second)
            return (a.protocol === "https:" || a.protocol === "http:") && a.origin === b.origin
        } catch (error) { return false }
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

    function requestError(xhr, credential) {
        if (credential) return "Credential change failed (HTTP " + xhr.status + ")."
        try {
            const response = JSON.parse(xhr.responseText || "{}")
            if (typeof response.detail === "string") return response.detail.slice(0, 500)
        } catch (error) {}
        return "Request failed (HTTP " + xhr.status + ")."
    }

    function offeringDescription() {
        const provider = providers.find(row => row.kind === draftKind && sameOrigin(row.url, draftUrl.trim()))
        return provider && provider.description ? provider.description : draftKind === "http_api"
            ? "Connect read-only access to an API endpoint. A connection does not create a feed or an agent Tool."
            : "Connect to this publisher once. Choose which content to collect in the Feeds pane."
    }

    function applySnapshot(payload, preserveDraft) {
        if (!payload || !Number.isInteger(payload.revision) || payload.revision < 0
                || !Array.isArray(payload.connections) || !Array.isArray(payload.providers)) throw new Error("Invalid connections response")
        const initial = revision < 0
        const previousSelection = selectedConnectionId
        revision = payload.revision
        connections = payload.connections
        providers = payload.providers
        if (initial && !selectedConnectionId && connections.length) selectedConnectionId = connections[0].id
        if (selectedConnectionId && !selectedConnection) selectedConnectionId = ""
        if (selectedConnection && preserveDraft !== true) loadDraft(selectedConnection)
        else if (previousSelection && !selectedConnection) loadDraft(null)
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
                root.errorMessage = root.requestError(xhr, false)
                return
            }
            try {
                root.applySnapshot(JSON.parse(xhr.responseText), preserveDraft)
                root.errorMessage = ""
            } catch (error) {
                root.errorMessage = "The Harness returned invalid connection metadata."
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
                root.errorMessage = root.requestError(xhr, path.indexOf("/credential") >= 0)
                return
            }
            try {
                const payload = JSON.parse(xhr.responseText)
                if (creating && typeof payload.created_id === "string") root.selectedConnectionId = payload.created_id
                root.applySnapshot(payload)
                root.notice = root.selectedConnection && root.selectedConnection.last_error ? "" : label + " finished."
            } catch (error) {
                root.revision = -1
                root.errorMessage = "Connection settings could not be read. Reload before making another change."
            }
        }
        xhr.send(body === null ? null : JSON.stringify(body))
    }

    function saveRecord() {
        if (!canSave) return
        const body = {"revision":revision, "name":draftName.trim(), "url":draftUrl.trim(),
            "kind":draftKind, "auth_mode":draftAuthMode, "enabled":draftEnabled}
        mutate(selectedConnectionId ? "PATCH" : "POST", "/api/connections"
            + (selectedConnectionId ? "/" + encodeURIComponent(selectedConnectionId) : ""), body, "Save", !selectedConnectionId)
    }

    function checkNow() {
        if (!selectedConnection || hasUnsavedChanges) return
        mutate("POST", "/api/connections/" + encodeURIComponent(selectedConnectionId) + "/check", null, "Connection test", false)
    }

    function removeRecord() {
        if (!selectedConnection) return
        mutate("DELETE", "/api/connections/" + encodeURIComponent(selectedConnectionId) + "?revision=" + revision, null, "Remove", false)
    }

    function saveCredential() {
        if (busy || loading || !credentialContextSaved || !credentialSecret.trim()) return
        const secret = credentialSecret
        credentialSecret = ""
        mutate("PUT", "/api/connections/" + encodeURIComponent(selectedConnection.id) + "/credential",
            {"revision": revision, "secret": secret}, "Credential save", "")
    }

    function removeCredential() {
        if (!credentialContextSaved) return
        credentialSecret = ""
        mutate("DELETE", "/api/connections/" + encodeURIComponent(selectedConnection.id)
            + "/credential?revision=" + revision, null, "Credential removal", "")
    }

    Component.onCompleted: refresh()
    onDraftUrlChanged: credentialSecret = ""
    onDraftAuthModeChanged: credentialSecret = ""
    onDraftKindChanged: credentialSecret = ""
    onVisibleChanged: { if (!visible) credentialSecret = "" }
    Component.onDestruction: credentialSecret = ""

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


    ColumnLayout {
        anchors.fill: parent; anchors.margins: 16
        spacing: 12
        RowLayout {
            Layout.fillWidth: true
            SectionTitle { Layout.fillWidth: true; text: "Connections"; font.pixelSize: 21 }
            Action { text: "New"; enabled: !root.busy && !root.loading; onClicked: root.newRecord() }
            Action { text: "Reload"; enabled: !root.busy && !root.loading; onClicked: root.refresh() }
        }
        Caption { Layout.fillWidth: true; text: "Access to publishers and third-party services." }
        Choice {
            objectName: "connection-record-picker"
            Layout.fillWidth: true
            model: root.connections; textRole: "name"
            currentIndex: root.connections.findIndex(row => row.id === root.selectedConnectionId)
            displayText: currentIndex >= 0 ? currentText : "New connection"
            enabled: !root.busy
            onActivated: index => root.selectRow(root.connections[index].id)
        }
        Caption { Layout.fillWidth: true; visible: root.busy || root.loading; text: root.busy ? root.busyLabel + "…" : "Loading…" }
        Caption { Layout.fillWidth: true; visible: !!root.errorMessage; text: root.errorMessage; color: "#fda4af" }
        Caption { Layout.fillWidth: true; visible: !!root.notice; text: root.notice; color: "#86efac" }
        ScrollView {
            id: editorScroll
            Layout.fillWidth: true; Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true
            ColumnLayout {
                width: editorScroll.availableWidth
                spacing: 10
                Caption { text: "Provider"; visible: !root.selectedConnection }
                Choice { Layout.fillWidth: true; visible: !root.selectedConnection; model: root.presets; textRole: "name"; enabled: !root.busy; onActivated: index => root.usePreset(index) }
                Caption { text: "Connection name" }
                Field { objectName: "connection-name"; Layout.fillWidth: true; text: root.draftName; maximumLength: 160; enabled: !root.busy; onTextEdited: root.draftName = text }
                Caption { text: "Access type" }
                Choice { Layout.fillWidth: true; model: ["RSS / Atom", "HTTP API"]; currentIndex: root.draftKind === "http_api" ? 1 : 0; enabled: !root.busy; onActivated: index => root.draftKind = index ? "http_api" : "rss" }
                Caption { text: "Service address" }
                Field { objectName: "connection-url"; Layout.fillWidth: true; text: root.draftUrl; maximumLength: 2048; placeholderText: "https://…"; enabled: !root.busy; onTextEdited: root.draftUrl = text }
                Caption { Layout.fillWidth: true; text: root.offeringDescription() }
                Toggle { objectName: "connection-enabled"; text: "Connection enabled"; checked: root.draftEnabled; enabled: !root.busy; onToggled: root.draftEnabled = checked }
                Divider {}
                SectionTitle { text: "Authentication" }
                Choice { Layout.fillWidth: true; model: ["None", "Bearer token", "Bot token"]; currentIndex: ["none", "bearer", "bot"].indexOf(root.draftAuthMode); enabled: !root.busy; onActivated: index => root.draftAuthMode = ["none", "bearer", "bot"][index] }
                Caption { Layout.fillWidth: true; visible: root.draftAuthMode !== "none"; text: !root.credentialContextSaved ? "Save the URL and authentication first, then add a credential." : root.credentialReady ? "Credential stored. Enter a replacement below." : "No credential stored." }
                Field { objectName: "connection-credential"; Layout.fillWidth: true; visible: root.draftAuthMode !== "none"; text: root.credentialSecret; echoMode: TextInput.Password; placeholderText: "Credential (never shown again)"; maximumLength: 4096; enabled: !root.busy && root.credentialContextSaved; onTextEdited: root.credentialSecret = text }
                Flow {
                    Layout.fillWidth: true; spacing: 8
                    visible: root.draftAuthMode !== "none" && !!root.selectedConnection
                    Action { text: "Save credential"; enabled: !root.busy && !root.loading && root.credentialContextSaved && !!root.credentialSecret.trim(); onClicked: root.saveCredential() }
                    Action { text: "Remove credential"; enabled: !root.busy && !root.loading && root.credentialContextSaved && root.credentialReady; onClicked: root.removeCredential() }
                }
                Divider { visible: !!root.selectedConnection }
                Caption { Layout.fillWidth: true; visible: !!root.selectedConnection; text: root.selectedConnection ? root.rowStatus(root.selectedConnection) + " · Last test: " + root.timestamp(root.selectedConnection.last_checked) : "" }
                Caption { Layout.fillWidth: true; visible: !!root.selectedConnection && !!root.selectedConnection.last_error; text: root.selectedConnection ? root.selectedConnection.last_error || "" : ""; color: "#fda4af" }
                Action { visible: !!root.selectedConnection; text: "Remove connection"; accent: "#fda4af"; enabled: !root.busy && !root.loading; onClicked: root.removeRecord() }
            }
        }
        Rectangle { Layout.fillWidth: true; Layout.preferredHeight: 1; color: "#28404e" }
        Caption { visible: root.hasUnsavedChanges; text: "Unsaved changes"; color: "#f5cf89" }
        Flow {
            Layout.fillWidth: true; spacing: 8
            Action { objectName: "connection-save"; text: root.selectedConnection ? "Save changes" : "Create connection"; enabled: root.canSave; emphasized: true; onClicked: root.saveRecord() }
            Action { objectName: "connection-reset"; text: "Reset"; enabled: !root.busy && !root.loading && root.hasUnsavedChanges; onClicked: root.loadDraft(root.selectedConnection) }
            Action { objectName: "connection-test"; text: "Test access"; visible: !!root.selectedConnection; enabled: !root.busy && !root.loading && !root.hasUnsavedChanges; onClicked: root.checkNow() }
        }
    }
}
