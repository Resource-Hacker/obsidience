pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../api"

Rectangle {
    id: root
    color: "#050c14"
    property int mode: 0
    property var metadataMatches: []
    property var selectedMetadata: null
    property var sourceChoices: []
    property var selectedSource: null
    property bool acquisitionReady: false
    property string acquisitionReadiness: ""
    property var items: []
    property var selected: null
    property var savedResume: null
    property bool resumeLoading: false
    property string resumeReason: ""
    property var resumeRequest: null
    property int resumeEpoch: 0
    property int selectionEpoch: 0
    property var playback: null
    property int offset: 0
    property int nextOffset: -1
    property bool loading: false
    property bool selecting: false
    property bool serverAvailable: false
    property string message: ""
    property string pendingRequest: ""
    property string pendingOperation: ""
    property int receiptChecks: 0
    property var requests: []
    property bool disposed: false
    property int viewEpoch: 0
    property bool receiptReading: false

    function cancelReads() {
        viewEpoch += 1
        selectionEpoch += 1
        clearSavedResume()
        const pending = requests.slice()
        requests = requests.filter(item => item.mediaMutation)
        for (const xhr of pending) if (!xhr.mediaMutation) xhr.abort()
        loading = false
        selecting = false
        receiptReading = false
    }

    function request(method, path, body, callback) {
        if (disposed || !visible) return
        const xhr = new XMLHttpRequest()
        xhr.mediaMutation = method === "POST"
        const epoch = viewEpoch
        requests.push(xhr)
        xhr.open(method, "http://127.0.0.1:8765/api/media" + path)
        if (body !== null) xhr.setRequestHeader("Content-Type", "application/json")
        if (path.startsWith("/commands")) xhr.setRequestHeader("X-Obsidience-Owner", ShellCommandToken.value)
        xhr.onreadystatechange = function() {
            if (root.disposed || xhr.readyState !== XMLHttpRequest.DONE) return
            root.requests = root.requests.filter(item => item !== xhr)
            if (!root.visible || (!xhr.mediaMutation && root.viewEpoch !== epoch)) return
            let data = null
            try { data = JSON.parse(xhr.responseText) } catch (error) {}
            callback(xhr.status >= 200 && xhr.status < 300, data)
        }
        xhr.send(body === null ? null : JSON.stringify(body))
        return xhr
    }
    function clearSavedResume() {
        resumeEpoch += 1
        savedResume = null
        resumeLoading = false
        resumeReason = ""
        const xhr = resumeRequest
        resumeRequest = null
        if (xhr) {
            requests = requests.filter(item => item !== xhr)
            xhr.abort()
        }
    }
    function readSavedResume() {
        clearSavedResume()
        if (disposed || !visible || mode !== 0 || !selected) return
        const itemId = selected.item_id
        const epoch = resumeEpoch
        resumeLoading = true
        resumeRequest = request("GET", "/resume?item_id=" + encodeURIComponent(itemId), null, function(ok, data) {
            if (root.resumeEpoch !== epoch || !root.visible || root.mode !== 0
                    || !root.selected || root.selected.item_id !== itemId) return
            root.resumeRequest = null
            root.resumeLoading = false
            if (ok && data && data.available === true && data.item_id === itemId
                    && data.persistence === "read_back" && typeof data.position === "number"
                    && isFinite(data.position) && data.position >= 0) root.savedResume = data
            else root.resumeReason = (data && (data.reason || data.detail)) || "Stored progress unavailable."
        })
    }
    function savedPosition(seconds) {
        const value = Math.floor(seconds)
        return Math.floor(value / 3600) + ":" + ("0" + Math.floor(value % 3600 / 60)).slice(-2)
            + ":" + ("0" + value % 60).slice(-2)
    }
    onSelectedChanged: readSavedResume()
    onModeChanged: { cancelReads(); if (visible) readSavedResume() }
    onVisibleChanged: {
        cancelReads()
        if (visible) { refreshStatus(); readSavedResume(); if (pendingRequest) checkReceipt() }
    }

    function refreshStatus() {
        request("GET", "/status", null, function(ok, data) {
            if (!ok) { root.message = "Media status unavailable."; return }
            root.serverAvailable = data.server_available === true
            root.playback = data.tv || null
            root.acquisitionReady = !!data.acquisition && data.acquisition.enabled === true && data.acquisition.ready === true
            root.acquisitionReadiness = data.acquisition && data.acquisition.readiness ? data.acquisition.readiness : ""
        })
    }
    function browse(index, completionMessage) {
        if (!visible || loading || pendingRequest) return
        loading = true
        selectionEpoch += 1
        selected = null
        request("GET", "/catalogue?query=" + encodeURIComponent(query.text.trim()) + "&offset=" + index + "&limit=20", null,
                function(ok, data) {
            root.loading = false
            root.items = ok && data.available ? data.items : []
            root.offset = index
            root.nextOffset = ok && data.next_offset !== null && data.next_offset !== undefined ? data.next_offset : -1
            root.message = ok && data.available ? (completionMessage || "Choose one exact source.")
                : (data && (data.reason || data.detail)) || "Catalogue unavailable."
        })
    }
    function choose(row) {
        if (!visible || selecting || pendingRequest) return
        selecting = true
        const epoch = ++selectionEpoch
        selected = null
        request("GET", "/selection?item_id=" + encodeURIComponent(row.item_id) + "&media_source_id=" + encodeURIComponent(row.media_source_id), null,
                function(ok, data) {
            root.selecting = false
            if (root.selectionEpoch !== epoch) return
            if (ok) root.selected = data
            root.message = ok ? "Selected: " + data.title : (data && data.detail) || "This source is unavailable."
        })
    }
    function searchTitles() {
        if (!visible || loading || pendingRequest) return
        loading = true
        metadataMatches = []
        selectedMetadata = null
        sourceChoices = []
        selectedSource = null
        request("GET", "/search?query=" + encodeURIComponent(query.text.trim()) + "&content_type=" + (contentType.currentIndex === 0 ? "movie" : "series"), null,
                function(ok, data) {
            root.loading = false
            root.metadataMatches = ok && data.available ? data.matches : []
            root.message = ok && data.available ? "Choose the exact title and year; then inspect its sources." : (data && (data.reason || data.detail)) || "Discovery unavailable."
        })
    }
    function chooseTitle(row) {
        cancelReads()
        selectedMetadata = row
        sourceChoices = []
        selectedSource = null
        message = "Selected title: " + row.title + (row.year ? " · " + row.year : "")
    }
    function findSources() {
        if (!visible || loading || pendingRequest || !selectedMetadata) return
        loading = true
        selectedSource = null
        sourceChoices = []
        let path = "/sources?metadata_token=" + encodeURIComponent(selectedMetadata.metadata_token)
        if (selectedMetadata.type === "series") path += "&season=" + season.value + "&episode=" + episode.value
        request("GET", path, null, function(ok, data) {
            root.loading = false
            root.sourceChoices = ok && data.available ? data.candidates : []
            root.message = ok && data.available ? (data.ambiguous_best_tie ? "Several sources have equal rank. Choose one exact source." : "Choose one source to register in the library.")
                : (data && (data.reason || data.detail)) || "Sources unavailable."
        })
    }
    function sourceScope(row) {
        if (row.acquisition_scope === "series_pack")
            return "Series pack · all " + row.registered_files + " files · included seasons "
                + row.season_numbers.join(", ")
                + (row.pack_episodes ? " · " + row.pack_episodes + " episodes" : "")
        if (row.acquisition_scope === "season_pack")
            return "Season " + row.season + " pack · all " + row.registered_files + " files"
                + (row.pack_episodes ? " · " + row.pack_episodes + " episodes" : "")
        if (row.file_episode !== undefined && row.file_episode !== null)
            return "Season " + row.file_season + " · episode " + row.file_episode
                + (row.file_episode_end > row.file_episode ? "–" + row.file_episode_end : "") + " file"
        return ""
    }
    function sourceLabel(row) {
        const scope = sourceScope(row)
        return (scope ? scope + " · " : "") + row.release_label + " · " + (row.resolution ? row.resolution + "p" : "resolution unknown")
            + (row.hdr ? " · HDR" : "") + (row.remux ? " · Remux" : "")
            + (row.size_bytes ? " · " + (row.size_bytes / 1073741824).toFixed(1) + " GB release" : "")
            + ((row.acquisition_scope === "season_pack" || row.acquisition_scope === "series_pack") && row.selected_size_bytes ? " · " + (row.selected_size_bytes / 1073741824).toFixed(1) + " GB selected file" : "")
            + (row.cached ? " · TorBox cached" : " · " + (row.seeders === null ? "availability unknown" : row.seeders + " peers"))
            + (row.recommended ? " · Recommended" : "")
    }
    function uuid() {
        return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function(c) {
            const n = Math.floor(Math.random() * 16)
            return (c === "x" ? n : ((n & 3) | 8)).toString(16)
        })
    }
    function command(operation, resumeSaved) {
        if (!visible || pendingRequest || !ShellCommandToken.value) return
        const body = {request_id: uuid(), operation: operation}
        if (operation === "acquire" || operation === "refresh_source") {
            if (!selectedSource || !acquisitionReady) return
            body.preview_token = selectedSource.preview_token
        } else if (operation === "server" && selected && mode === 0) {
            body.selection = {item_id: selected.item_id, media_source_id: selected.media_source_id, source_revision: selected.source_revision}
        } else if (operation !== "server") {
            if (destination.currentIndex !== 1) { message = "Choose the registered TV destination."; return }
            body.destination = "tv"
            if (operation === "play") {
                if (!selected) return
                if (resumeSaved === true && (!savedResume || savedResume.position <= 0)) return
                body.resume = resumeSaved === true
                body.selection = {item_id: selected.item_id, media_source_id: selected.media_source_id, source_revision: selected.source_revision}
            } else {
                if (!playback || !playback.generation || !playback.source) return
                body.generation = playback.generation
                body.source = playback.source
                if (operation === "seek") body.position = position.value
            }
        }
        pendingRequest = body.request_id
        pendingOperation = operation
        receiptChecks = 0
        message = "Submitting owner command…"
        request("POST", "/commands", body, function(ok, data) {
            if (!ok) {
                root.message = (data && data.detail) || "Command delivery is unknown. Check its receipt; do not resend."
                // A transport failure may follow admission. Read its UUID, never resend it.
                if (data && data.detail) { root.pendingRequest = ""; root.pendingOperation = "" }
            } else root.message = "Command admitted; waiting for its receipt."
            root.checkReceipt()
        })
    }
    function checkReceipt() {
        if (!visible || receiptReading || !pendingRequest || receiptChecks >= 30) return
        receiptReading = true
        receiptChecks += 1
        request("GET", "/commands/" + pendingRequest, null, function(ok, data) {
            root.receiptReading = false
            if (ok && data.settled) {
                const completionMessage = data.summary || ("Command " + data.state)
                root.message = completionMessage
                const acquired = (root.pendingOperation === "acquire" || root.pendingOperation === "refresh_source") && data.state === "completed"
                root.pendingRequest = ""
                root.pendingOperation = ""
                root.refreshStatus()
                if (acquired) {
                    root.mode = 0
                    root.selectedSource = null
                    root.sourceChoices = []
                    query.text = ""
                    root.browse(0, completionMessage)
                }
            } else if (root.receiptChecks >= 30) {
                root.message = "No settled receipt yet. This command will not be resent."
            }
        })
    }
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 10
        Label { text: "MEDIA"; color: "#67e8f9"; font.pixelSize: 22 }
        TabBar {
            Layout.fillWidth: true
            currentIndex: root.mode
            enabled: !root.loading && !root.pendingRequest
            onCurrentIndexChanged: { root.mode = currentIndex; root.message = "" }
            TabButton { text: "Library" }
            TabButton { text: "Discover" }
        }
        RowLayout {
            ComboBox { id: contentType; visible: root.mode === 1; model: ["Movies", "Series"]; onCurrentIndexChanged: { root.cancelReads(); root.metadataMatches = []; root.selectedMetadata = null; root.sourceChoices = []; root.selectedSource = null } }
            TextField { id: query; Layout.fillWidth: true; maximumLength: 160; placeholderText: root.mode === 0 ? "Search the catalogue" : "Search titles"; onAccepted: root.mode === 0 ? root.browse(0) : root.searchTitles() }
            Button { text: "Search"; enabled: !root.loading && !root.pendingRequest; onClicked: root.mode === 0 ? root.browse(0) : root.searchTitles() }
            Button { text: root.mode === 0 && root.selected ? "Open selected in Jellyfin" : "Open Jellyfin"; enabled: root.serverAvailable && !root.pendingRequest; onClicked: root.command("server") }
        }
        ListView {
            Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 4
            model: root.mode === 0 ? root.items : root.metadataMatches
            delegate: ItemDelegate {
                required property var modelData
                width: ListView.view.width
                text: modelData.title + (modelData.year ? " · " + modelData.year : "")
                      + (modelData.series ? " · " + modelData.series + " S" + modelData.season + " E" + modelData.episode : "")
                      + (root.mode === 0 ? " · source " + modelData.media_source_id : " · " + modelData.imdb_id)
                enabled: !root.selecting && !root.pendingRequest
                onClicked: root.mode === 0 ? root.choose(modelData) : root.chooseTitle(modelData)
            }
        }
        RowLayout {
            visible: root.mode === 1
            Label { text: root.selectedMetadata ? root.selectedMetadata.title : "Choose a title"; color: "#dbeafe"; Layout.fillWidth: true; elide: Text.ElideRight }
            Label { visible: !!root.selectedMetadata && root.selectedMetadata.type === "series"; text: "Season / episode"; color: "#94a3b8" }
            SpinBox { id: season; visible: !!root.selectedMetadata && root.selectedMetadata.type === "series"; from: 1; to: 99; value: 1; editable: true; onValueChanged: { root.cancelReads(); root.sourceChoices = []; root.selectedSource = null } }
            SpinBox { id: episode; visible: !!root.selectedMetadata && root.selectedMetadata.type === "series"; from: 1; to: 99; value: 1; editable: true; onValueChanged: { root.cancelReads(); root.sourceChoices = []; root.selectedSource = null } }
            Button { text: "Find sources"; enabled: !!root.selectedMetadata && !root.loading && !root.pendingRequest; onClicked: root.findSources() }
        }
        ListView {
            visible: root.mode === 1 && root.sourceChoices.length > 0
            Layout.fillWidth: true; Layout.preferredHeight: 180; clip: true; spacing: 4
            model: root.sourceChoices
            delegate: ItemDelegate {
                required property var modelData
                width: ListView.view.width
                text: root.sourceLabel(modelData)
                highlighted: root.selectedSource !== null && root.selectedSource.preview_token === modelData.preview_token
                enabled: !root.pendingRequest
                onClicked: { root.selectedSource = modelData; root.message = "Chosen source: " + root.sourceLabel(modelData) }
            }
        }
        RowLayout {
            visible: root.mode === 1
            Button { text: root.selectedSource && root.selectedSource.acquisition_scope === "series_pack"
                    ? "Register series pack (" + root.selectedSource.registered_files + " files)"
                    : root.selectedSource && root.selectedSource.acquisition_scope === "season_pack"
                    ? "Register season pack (" + root.selectedSource.registered_files + " files)" : "Acquire selected source"; enabled: root.selectedSource !== null && root.acquisitionReady && !root.pendingRequest; onClicked: root.command("acquire") }
            Button { text: "Refresh readiness"; onClicked: root.refreshStatus() }
            Button { text: "Refresh registered source"; enabled: root.selectedSource !== null && root.acquisitionReady && !root.pendingRequest; onClicked: root.command("refresh_source") }
            Label { text: root.acquisitionReady ? (root.selectedSource && root.selectedSource.acquisition_scope === "series_pack"
                        ? "Registers all " + root.selectedSource.registered_files + " files across all included seasons: "
                            + root.selectedSource.season_numbers.join(", ")
                            + ". Registration does not start playback; season playback stays within the requested season."
                        : root.selectedSource && root.selectedSource.acquisition_scope === "season_pack"
                        ? "Registers all " + root.selectedSource.registered_files + " files in the Season " + root.selectedSource.season
                            + " pack. Registration does not start playback."
                        : "Registration does not start playback") : (root.acquisitionReadiness || "Acquisition unavailable"); color: "#94a3b8"; Layout.fillWidth: true; wrapMode: Text.Wrap }
        }
        RowLayout {
            visible: root.mode === 0
            Button { text: "Previous"; enabled: root.offset > 0 && !root.loading && !root.pendingRequest; onClicked: root.browse(Math.max(0, root.offset - 20)) }
            Button { text: "Next"; enabled: root.nextOffset >= 0 && !root.loading && !root.pendingRequest; onClicked: root.browse(root.nextOffset) }
            Label { text: root.selected ? root.selected.title : "No source selected"; color: "#dbeafe"; Layout.fillWidth: true; elide: Text.ElideRight }
        }
        Label {
            visible: root.mode === 0 && root.selected !== null
            text: root.resumeLoading ? "Reading stored progress…"
                : root.savedResume ? (root.savedResume.position > 0
                    ? "Stored progress: " + root.savedPosition(root.savedResume.position)
                    : "No saved resume position")
                : "Stored progress unavailable: " + root.resumeReason
            color: "#94a3b8"; Layout.fillWidth: true; wrapMode: Text.Wrap
        }
        RowLayout {
            visible: root.mode === 0
            ComboBox { id: destination; model: ["Choose destination", "Registered TV"] }
            Button { text: "Play selected on TV"; enabled: root.selected !== null && destination.currentIndex === 1 && !root.pendingRequest; onClicked: root.command("play") }
            Button {
                text: "Resume on TV"
                visible: root.savedResume !== null && root.savedResume.position > 0
                enabled: root.selected !== null && destination.currentIndex === 1 && !root.pendingRequest && !root.resumeLoading
                onClicked: root.command("play", true)
            }
            Button { text: "Refresh playback"; onClicked: { root.refreshStatus(); root.readSavedResume() } }
        }
        Label { visible: root.mode === 0; text: root.playback ? "TV player: " + root.playback.playback + (root.playback.title ? " · " + root.playback.title : "") : "TV playback unavailable"; color: "#94a3b8"; Layout.fillWidth: true; elide: Text.ElideRight }
        RowLayout {
            visible: root.mode === 0
            enabled: destination.currentIndex === 1 && root.playback !== null && !!root.playback.generation && !root.pendingRequest
            Button { text: "Pause"; onClicked: root.command("pause") }
            Button { text: "Resume"; onClicked: root.command("resume") }
            Button { text: "Stop"; onClicked: root.command("stop") }
            SpinBox { id: position; from: 0; to: 86400; editable: true }
            Button { text: "Seek to seconds"; onClicked: root.command("seek") }
        }
        Label { text: root.message; color: "#dbeafe"; wrapMode: Text.Wrap; Layout.fillWidth: true }
        Button { text: "Check command receipt"; visible: !!root.pendingRequest; onClicked: { root.receiptChecks = 0; root.checkReceipt() } }
    }
    Timer { interval: 1000; repeat: true; running: root.visible && !!root.pendingRequest && root.receiptChecks < 30; onTriggered: root.checkReceipt() }
    Component.onCompleted: { refreshStatus(); browse(0) }
    Component.onDestruction: {
        disposed = true
        clearSavedResume()
        for (const xhr of requests) xhr.abort()
        requests = []
    }
}
