pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtWebSockets
import "../../components/visual"
import "../../workspace"

Rectangle {
    id: root

    required property PaneDockLayout dockLayout
    required property string surfaceId

    readonly property string systemPrefix: "obsidience/state/system"
    readonly property string evidencePrefix: "obsidience/evidence"
    readonly property string vaultPrefix: "obsidience/vault"
    readonly property var checkoutAgents: [
        {"id": "executive", "label": "Executive", "role": "executive"},
        {"id": "guardian", "label": "Heimdall", "role": "guardian"},
        {"id": "curator", "label": "Alexandria", "role": "curator"},
        {"id": "researcher", "label": "Darwin", "role": "researcher"}
    ]

    property var files: []
    property var issues: []
    property var systemKnowledge: ({})
    property bool systemRefreshBusy: false
    property string systemError: ""
    property int systemRequestGeneration: 0
    property var checkouts: ({})
    property var articleRefs: ({})
    property var busyCheckouts: ({})
    property var visibleRows: []
    property var expandedPaths: ({
        "@view/system": true,
        "@view/knowledge": true
    })
    property string selectedRef: ""
    property string selectedKey: ""
    property string query: ""
    property bool showAll: true
    property bool loading: false
    property string errorMessage: ""
    property string bridgeError: ""
    property int requestGeneration: 0

    color: "#c708050f"
    clip: true

    function checkoutKey(tree, agent) {
        return tree + "\u0000" + agent
    }

    function isCheckedOut(tree, agent) {
        return checkouts[checkoutKey(tree, agent)] === true
    }

    function readableBytes(bytes) {
        const value = Number(bytes || 0)
        if (value < 1024) return value + " B"
        if (value < 1048576) return (value / 1024).toFixed(1) + " KB"
        if (value < 1073741824) return (value / 1048576).toFixed(1) + " MB"
        if (value < 1099511627776) return (value / 1073741824).toFixed(1) + " GB"
        return (value / 1099511627776).toFixed(1) + " TB"
    }

    function sourceMatchesArticle(file, ref) {
        if (!file || !Array.isArray(file.articles)) return false
        if (file.articles.indexOf(ref) >= 0) return true
        if (articleRefs[ref] && file.articles.indexOf(articleRefs[ref]) >= 0) return true
        if (!ref.startsWith("@branch/")) return false
        const branch = ref.slice("@branch/".length)
        if (branch === "ADMECH Workstation" && file.storage === "system") return true
        return file.articles.some(article => article === branch
            || article.startsWith(branch + "/"))
    }

    function route(file) {
        if (file.path === systemPrefix + "/system.json"
                || file.path.startsWith(systemPrefix + "/hardware/")
                || file.path.startsWith(systemPrefix + "/applications/")) {
            return {"parent": "system", "relative": file.path.slice(systemPrefix.length + 1), "base": systemPrefix}
        }
        if (file.path.startsWith(vaultPrefix + "/")) {
            return {"parent": "knowledge", "relative": file.path.slice(vaultPrefix.length + 1), "base": vaultPrefix}
        }
        if (file.path.startsWith(evidencePrefix + "/")) {
            return {"parent": "evidence", "relative": file.path.slice(evidencePrefix.length + 1), "base": evidencePrefix}
        }
        // During an evidence migration, keep any remaining exact old files
        // outside System without claiming that their physical path changed.
        if (file.path.startsWith(systemPrefix + "/snapshots/")) {
            return {"parent": "evidence", "relative": file.path.slice(systemPrefix.length + 1), "base": systemPrefix}
        }
        return {"parent": "project", "relative": file.path, "base": ""}
    }

    function folder(key, name, backingPath, subtitle, virtual, order) {
        return {"key": key, "name": name, "folder": true,
            "backingPath": backingPath || "", "subtitle": subtitle || "",
            "virtual": virtual === true, "order": order === undefined ? 999 : order,
            "children": []}
    }

    function buildTree(scopedFiles) {
        const system = folder("@view/system", "SYSTEM", systemPrefix,
            "Hardware and Applications · read only", true, 0)
        const knowledge = folder("@view/knowledge", "KNOWLEDGE MARKDOWN", vaultPrefix,
            "Actual graph Articles · obsidience/vault", true, 1)
        const evidence = folder("@view/evidence", "EVIDENCE", evidencePrefix,
            "Captured references and agent handoffs · obsidience/evidence", true, 2)
        evidence.children = [
            folder(evidencePrefix + "/raw", "raw", evidencePrefix + "/raw",
                "Immutable captured references", false, 0),
            folder(evidencePrefix + "/inbox", "inbox", evidencePrefix + "/inbox",
                "Darwin’s cited handoffs to Alexandria", false, 1),
            folder(evidencePrefix + "/system", "system", evidencePrefix + "/system",
                "Immutable System evidence versions", false, 2),
            folder(evidencePrefix + "/incoming", "incoming", evidencePrefix + "/incoming",
                "Manual text imports · capture and queue Darwin Learn; originals remain", false, 3)
        ]
        const project = folder("@view/project", "PROJECT FILES", "",
            "Application code and project documents · exact paths", true, 3)
        const parents = {"system": system, "knowledge": knowledge, "evidence": evidence, "project": project}
        for (const file of scopedFiles) {
            const target = route(file)
            const parts = target.relative.split("/").filter(Boolean)
            const filename = parts.pop() || file.name
            let children = parents[target.parent].children
            let prefix = target.base
            for (const part of parts) {
                prefix = prefix ? prefix + "/" + part : part
                let child = children.find(node => node.folder && node.key === prefix)
                if (!child) {
                    const breadcrumb = Array.isArray(file.system_breadcrumbs)
                        ? file.system_breadcrumbs.find(item => item.path === prefix) : null
                    child = folder(prefix, breadcrumb ? breadcrumb.title : part, prefix, "", false)
                    children.push(child)
                }
                children = child.children
            }
            children.push({"key": file.key, "name": file.system_label || filename,
                "folder": false, "file": file, "children": []})
        }
        function sort(nodes) {
            nodes.sort(function(left, right) {
                const order = (left.order ?? 999) - (right.order ?? 999)
                if (order) return order
                if (left.folder !== right.folder) return left.folder ? -1 : 1
                return left.name.localeCompare(right.name)
            })
            for (const node of nodes) sort(node.children)
        }
        const roots = [system, knowledge, evidence, project]
        sort(roots)
        return roots
    }

    function filterTree(nodes, needle) {
        if (!needle) return nodes
        const result = []
        for (const node of nodes) {
            const children = filterTree(node.children || [], needle)
            const searchable = node.name + " " + node.key + " "
                + (node.subtitle || "") + " "
                + (node.file && Array.isArray(node.file.articles)
                    ? node.file.articles.join(" ") : "")
            if (searchable.toLowerCase().includes(needle) || children.length) {
                result.push(Object.assign({}, node, {"children": children}))
            }
        }
        return result
    }

    function rebuildRows() {
        let scoped = files
        if (selectedRef && !showAll) {
            scoped = files.filter(file => file.path.startsWith(evidencePrefix + "/")
                || file.key === selectedKey
                || sourceMatchesArticle(file, selectedRef))
        }
        const tree = filterTree(buildTree(scoped), query.trim().toLowerCase())
        const rows = []
        function rowNode(node) {
            return Object.assign({
                "key": "", "name": "", "folder": false,
                "subtitle": "", "backingPath": "", "virtual": false,
                "file": {"key": "", "storage": "", "size": 0},
                "children": []
            }, node || {})
        }
        function append(nodes, depth) {
            for (const node of nodes) {
                rows.push({"type": node.folder ? "folder" : "file",
                    "node": rowNode(node), "depth": depth})
                if (node.folder && (expandedPaths[node.key] || query.trim())) {
                    append(node.children || [], depth + 1)
                }
            }
        }
        append(tree, 0)
        if (!rows.length) rows.push({"type": "empty", "node": rowNode(null),
            "depth": 0})
        for (const issue of issues) rows.push({"type": "issue", "issue": issue,
            "node": rowNode(null), "depth": 0})
        visibleRows = rows
    }

    function toggleFolder(key) {
        const next = Object.assign({}, expandedPaths)
        next[key] = !next[key]
        expandedPaths = next
        rebuildRows()
    }

    function refresh() {
        loading = true
        errorMessage = ""
        requestGeneration += 1
        const generation = requestGeneration
        let sourcePayload = null
        let checkoutPayload = null
        let graphPayload = {}
        let failed = false
        const sourceFiles = Object.create(null)
        const sourceIssues = Object.create(null)
        const sourceCursors = Object.create(null)
        let sourceScope = undefined
        function finish() {
            if (!root || failed || generation !== root.requestGeneration || sourcePayload === null
                    || checkoutPayload === null) return
            root.files = sourcePayload.files
            root.issues = sourcePayload.issues
            const next = {}
            for (const assignment of checkoutPayload.assignments || []) {
                next[root.checkoutKey(assignment.tree, assignment.agent)] = true
            }
            root.checkouts = next
            const refs = {}
            for (const group of (graphPayload.navigation || {}).groups || []) {
                if (group.id === "executive") refs["@vault"] = group.root_ref
                for (const subject of group.subjects || []) {
                    if (subject.article_ref) refs[subject.id] = subject.article_ref
                }
            }
            root.articleRefs = refs
            root.loading = false
            root.rebuildRows()
        }
        function load(path, accept, optional) {
            const request = new XMLHttpRequest()
            request.open("GET", "http://127.0.0.1:8765" + path)
            request.onreadystatechange = function() {
                if (request.readyState !== XMLHttpRequest.DONE || !root || failed
                        || generation !== root.requestGeneration) return
                if (request.status < 200 || request.status >= 300) {
                    if (optional) { accept({}); finish(); return }
                    if (generation === root.requestGeneration) {
                        failed = true
                        root.loading = false
                        root.errorMessage = request.responseText
                            || "Source hierarchy is unavailable."
                    }
                    return
                }
                try { accept(JSON.parse(request.responseText)); finish() }
                catch (error) {
                    if (optional) { accept({}); finish(); return }
                    if (root && generation === root.requestGeneration) {
                        failed = true
                        root.loading = false
                        root.errorMessage = "Source hierarchy response was invalid."
                    }
                }
            }
            request.send()
        }
        function loadSource(after) {
            load("/api/source-files" + (after === null ? ""
                : "?after=" + encodeURIComponent(after)), payload => {
                if (!payload || !Array.isArray(payload.files)
                        || !Array.isArray(payload.issues)) throw new Error("invalid source")
                for (const file of payload.files) {
                    if (!file || typeof file.key !== "string" || !file.key
                            || typeof file.path !== "string" || !file.path) {
                        throw new Error("invalid source file")
                    }
                    sourceFiles[file.key] = file
                }
                for (const issue of payload.issues) {
                    if (!issue || typeof issue.path !== "string"
                            || typeof issue.status !== "string" || typeof issue.detail !== "string") {
                        throw new Error("invalid source issue")
                    }
                    sourceIssues[JSON.stringify([issue.path, issue.status, issue.detail])] = issue
                }
                const coverage = payload.coverage
                // A first legacy response is a complete pre-pagination view.
                if (coverage === undefined && after === null) {
                    sourcePayload = {"files": Object.values(sourceFiles), "issues": Object.values(sourceIssues)}
                    return
                }
                if (!coverage || coverage.consistency !== "live" || typeof coverage.complete !== "boolean"
                        || coverage.returned !== payload.files.length || !Number.isInteger(coverage.limit)
                        || coverage.limit < 1 || coverage.limit > 2000 || payload.files.length > coverage.limit
                        || !(coverage.scope === null || typeof coverage.scope === "string")
                        || (sourceScope !== undefined && coverage.scope !== sourceScope)) {
                    throw new Error("invalid source coverage")
                }
                sourceScope = coverage.scope
                if (coverage.complete) {
                    if (coverage.next_cursor !== null) throw new Error("invalid source completion")
                    sourcePayload = {"files": Object.values(sourceFiles), "issues": Object.values(sourceIssues)}
                    return
                }
                const next = coverage.next_cursor
                if (typeof next !== "string" || !next || sourceCursors[next]
                        || !payload.files.length || next !== payload.files[payload.files.length - 1].key) {
                    throw new Error("source pagination did not advance")
                }
                sourceCursors[next] = true
                loadSource(next)
            })
        }
        loadSource(null)
        load("/api/source-checkouts", payload => {
            checkoutPayload = payload && Array.isArray(payload.assignments)
                ? payload : {"assignments": []}
        })
        load("/api/graph", payload => { graphPayload = payload || {} }, true)
    }

    function sendShellCommand(command) {
        if (shellSocket.status !== WebSocket.Open) {
            bridgeError = "Reader bridge is unavailable."
            return
        }
        bridgeError = ""
        shellSocket.sendTextMessage(JSON.stringify(command))
    }

    function presentSource(key) {
        if (!key) return
        sendShellCommand({"schema": "obsidience.shell.command.v1",
            "type": "pane.present", "pane_id": "reader",
            "selection": {"kind": "source", "key": key}})
    }

    function toggleCheckout(tree, agent) {
        const key = checkoutKey(tree, agent)
        if (busyCheckouts[key]) return
        const nextBusy = Object.assign({}, busyCheckouts)
        nextBusy[key] = true
        busyCheckouts = nextBusy
        const checkedOut = !isCheckedOut(tree, agent)
        const request = new XMLHttpRequest()
        request.open("PUT", "http://127.0.0.1:8765/api/source-checkouts/"
            + encodeURI(tree))
        request.setRequestHeader("content-type", "application/json")
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE) return
            const busy = Object.assign({}, root.busyCheckouts)
            delete busy[key]
            root.busyCheckouts = busy
            if (request.status < 200 || request.status >= 300) {
                root.errorMessage = request.responseText || "Source checkout failed."
                return
            }
            const assignments = Object.assign({}, root.checkouts)
            if (checkedOut) assignments[key] = true
            else delete assignments[key]
            root.checkouts = assignments
        }
        request.send(JSON.stringify({"agent": agent, "checked_out": checkedOut}))
    }

    function applyShellEvent(message) {
        if (typeof message !== "string" || message.length > 65536) return
        let event
        try { event = JSON.parse(message) } catch (error) { return }
        if (!event || event.schema !== "obsidience.shell.event.v1") return
        if (event.type === "pane.state" && event.pane
                && event.pane.pane_id === "reader" && event.selection) {
            if (event.selection.kind === "article") {
                selectedRef = String(event.selection.ref || "")
            } else if (event.selection.kind === "source") {
                selectedKey = String(event.selection.key || "")
            }
            rebuildRows()
        } else if (event.type === "pane.dock.state" && event.layout) {
            dockLayout.applyRecord(event.layout)
        }
    }

    function systemKnowledgeLabel() {
        if (systemRefreshBusy) return "System · Recording current observations…"
        if (systemError) return systemError
        const report = systemKnowledge || {}
        if (report.status === "uninitialized" || !report.status) return "System · No recorded observations yet"
        const timestamp = report.updated_at ? new Date(report.updated_at) : null
        const recorded = timestamp && !isNaN(timestamp.getTime())
            ? " · Checked " + timestamp.toLocaleString() : ""
        return "System · " + Number(report.current_count || 0) + "/"
            + (Array.isArray(report.categories) ? report.categories.length : 0) + " current"
            + (report.status === "degraded" ? " · Some observations unavailable" : "") + recorded
    }

    function systemKnowledgeDetails() {
        const categories = Array.isArray(systemKnowledge.categories) ? systemKnowledge.categories : []
        const unavailable = categories.filter(item => item.status !== "current")
            .map(item => item.title + ": " + (item.detail || item.status))
        return systemKnowledgeLabel() + "\nImmutable evidence; refresh records newly observed versions."
            + (unavailable.length ? "\n" + unavailable.join("\n") : "")
    }

    function loadSystemKnowledge(capture) {
        if (systemRefreshBusy) return
        const generation = ++systemRequestGeneration
        if (capture) systemRefreshBusy = true
        systemError = ""
        const request = new XMLHttpRequest()
        request.open(capture ? "POST" : "GET", "http://127.0.0.1:8765/api/system/"
            + (capture ? "refresh" : "knowledge"))
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE || !root
                    || generation !== root.systemRequestGeneration) return
            root.systemRefreshBusy = false
            if (request.status < 200 || request.status >= 300) {
                root.systemError = capture ? "System refresh failed · previous evidence retained"
                    : "System evidence status unavailable"
                return
            }
            try {
                const report = JSON.parse(request.responseText)
                if (!report || ["ready", "degraded", "uninitialized"].indexOf(report.status) < 0
                        || !Array.isArray(report.categories)) throw new Error("Invalid system status")
                root.systemKnowledge = report
                if (capture) root.refresh()
            } catch (error) {
                root.systemError = "System evidence status unavailable"
            }
        }
        request.send()
    }

    Component.onCompleted: { refresh(); loadSystemKnowledge(false) }
    onQueryChanged: rebuildRows()
    onShowAllChanged: rebuildRows()

    WebSocket {
        id: shellSocket
        url: "ws://127.0.0.1:8768"
        requestedSubprotocols: ["obsidience.shell.v1"]
        active: true
        onTextMessageReceived: message => root.applyShellEvent(message)
        onStatusChanged: status => {
            if (status === WebSocket.Open) root.bridgeError = ""
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

    Rectangle {
        id: moduleHeader
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: root.selectedRef ? 118 : 86
        color: "#c708050f"

        PaneModuleHeader {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: 8
            anchors.rightMargin: 8
            anchors.topMargin: 3
            moduleId: "source"
            title: "◫  Source"
            tint: "#c4b5fd"
            dockLayout: root.dockLayout
            surfaceId: root.surfaceId
            countText: root.loading ? "LOADING" : String(root.files.length)
            onCommandRequested: command => root.sendShellCommand(command)
        }

        TextField {
            id: filterField
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: 8
            anchors.rightMargin: 8
            anchors.topMargin: 25
            height: 24
            placeholderText: "Filter files"
            text: root.query
            color: "#f5f3ff"
            placeholderTextColor: "#59c4b5fd"
            selectByMouse: true
            font.family: "JetBrains Mono"
            font.pixelSize: 9
            leftPadding: 8
            rightPadding: 8
            topPadding: 3
            bottomPadding: 3
            onTextChanged: root.query = text
            background: Rectangle {
                radius: 4
                color: "#08050f"
                border.width: 1
                border.color: filterField.activeFocus ? "#80c4b5fd" : "#33c4b5fd"
            }
        }

        Item {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.margins: 8
            anchors.topMargin: 54
            height: 24
            Text {
                anchors.left: parent.left
                anchors.right: refreshSystem.left
                anchors.rightMargin: 6
                anchors.verticalCenter: parent.verticalCenter
                text: root.systemKnowledgeLabel()
                color: root.systemError || root.systemKnowledge.status === "degraded" ? "#fcd34d" : "#99c4b5fd"
                elide: Text.ElideRight
                font.family: "JetBrains Mono"
                font.pixelSize: 8
                MouseArea {
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.NoButton
                    ToolTip.visible: containsMouse
                    ToolTip.text: root.systemKnowledgeDetails()
                }
            }
            Button {
                id: refreshSystem
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                width: 104
                height: 23
                text: root.systemRefreshBusy ? "REFRESHING…" : "REFRESH SYSTEM"
                enabled: !root.systemRefreshBusy
                onClicked: root.loadSystemKnowledge(true)
                contentItem: Text {
                    text: refreshSystem.text
                    color: "#c4b5fd"
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    font.family: "JetBrains Mono"
                    font.pixelSize: 8
                }
                background: Rectangle {
                    radius: 3
                    color: refreshSystem.hovered ? "#1ac4b5fd" : "#0ac4b5fd"
                    border.width: 1
                    border.color: "#40c4b5fd"
                }
            }
        }

        Rectangle {
            visible: root.selectedRef !== ""
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: 8
            anchors.rightMargin: 8
            anchors.bottomMargin: 7
            height: 25
            radius: 4
            color: "#0a67e8f9"
            border.width: 1
            border.color: "#1f67e8f9"
            Text {
                anchors.left: parent.left
                anchors.right: scopeButton.left
                anchors.leftMargin: 7
                anchors.rightMargin: 6
                anchors.verticalCenter: parent.verticalCenter
                text: root.showAll ? "All Source" : "Article · " + root.selectedRef
                color: "#8ccffafe"
                elide: Text.ElideRight
                font.family: "JetBrains Mono"
                font.pixelSize: 7
            }
            Rectangle {
                id: scopeButton
                anchors.right: parent.right
                anchors.rightMargin: 4
                anchors.verticalCenter: parent.verticalCenter
                width: 48
                height: 17
                radius: 3
                color: scopeMouse.containsMouse ? "#1267e8f9" : "transparent"
                border.width: 1
                border.color: scopeMouse.containsMouse ? "#6667e8f9" : "#2667e8f9"
                Text {
                    anchors.centerIn: parent
                    text: root.showAll ? "ARTICLE" : "ALL"
                    color: "#a5f3fc"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 7
                    font.letterSpacing: 0.84
                }
                MouseArea {
                    id: scopeMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.showAll = !root.showAll
                }
            }
        }
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: "#1ac4b5fd"
        }
    }

    Text {
        id: statusLine
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: moduleHeader.bottom
        height: visible ? 24 : 0
        visible: root.errorMessage !== "" || root.bridgeError !== ""
        text: root.errorMessage || root.bridgeError
        color: "#fda4af"
        leftPadding: 8
        rightPadding: 8
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
        font.family: "JetBrains Mono"
        font.pixelSize: 8
    }

    ListView {
        id: hierarchyView
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: statusLine.bottom
        anchors.bottom: parent.bottom
        anchors.margins: 6
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        model: root.visibleRows
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        delegate: Item {
            id: row
            required property var modelData
            width: hierarchyView.width
            height: modelData.type === "folder" && modelData.node.subtitle ? 34
                : modelData.type === "issue" ? 30 : 24

            Rectangle {
                id: folderRow
                visible: row.modelData.type === "folder"
                anchors.fill: parent
                radius: 3
                color: folderMouse.containsMouse ? "#0ec4b5fd"
                    : row.modelData.node.virtual ? "#05ffffff" : "transparent"

                Text {
                    id: folderChevron
                    anchors.left: parent.left
                    anchors.leftMargin: 4 + row.modelData.depth * 12
                    anchors.top: parent.top
                    anchors.topMargin: row.modelData.node.subtitle ? 7 : 6
                    width: 12
                    text: root.expandedPaths[row.modelData.node.key] ? "⌄" : "›"
                    color: "#8cc4b5fd"
                    horizontalAlignment: Text.AlignHCenter
                    font.family: "JetBrains Mono"
                    font.pixelSize: 9
                }
                Text {
                    id: folderIcon
                    anchors.left: folderChevron.right
                    anchors.top: folderChevron.top
                    width: 15
                    text: row.modelData.node.key === "@view/system" ? "▣"
                        : row.modelData.node.key.indexOf("compute") >= 0 ? "◇"
                        : row.modelData.node.key.indexOf("drives") >= 0 ? "▰"
                        : row.modelData.node.key.indexOf("devices") >= 0 ? "⌘"
                        : row.modelData.node.key.indexOf("applications") >= 0 ? "▦"
                        : row.modelData.node.key === root.systemPrefix + "/hardware/network" ? "⌁" : "▱"
                    color: row.modelData.node.key.indexOf("hardware") >= 0
                        ? "#b36ee7b7" : "#99c4b5fd"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 10
                }
                Text {
                    anchors.left: folderIcon.right
                    anchors.right: checkoutRow.left
                    anchors.rightMargin: 4
                    anchors.top: folderChevron.top
                    text: row.modelData.node.name
                    color: row.modelData.node.key === "@view/system"
                        ? "#e6ecfeff" : "#bff5f3ff"
                    elide: Text.ElideRight
                    font.family: "JetBrains Mono"
                    font.pixelSize: row.modelData.node.key === "@view/system" ? 10 : 9
                    font.weight: row.modelData.node.virtual ? Font.DemiBold : Font.Normal
                    font.letterSpacing: row.modelData.node.virtual ? 0.63 : 0
                }
                Text {
                    visible: row.modelData.node.subtitle !== ""
                    anchors.left: folderIcon.right
                    anchors.right: checkoutRow.left
                    anchors.rightMargin: 4
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 5
                    text: row.modelData.node.subtitle
                    color: "#52ddd6fe"
                    elide: Text.ElideRight
                    font.family: "JetBrains Mono"
                    font.pixelSize: 7
                }
                Row {
                    id: checkoutRow
                    anchors.right: parent.right
                    anchors.rightMargin: 3
                    anchors.verticalCenter: parent.verticalCenter
                    visible: row.modelData.node.backingPath !== ""
                    spacing: 2
                    Repeater {
                        model: root.checkoutAgents
                        delegate: Rectangle {
                            id: checkoutButton
                            required property var modelData
                            readonly property bool checked: root.isCheckedOut(
                                row.modelData.node.backingPath, modelData.id
                            )
                            readonly property color tint: roleGlyph.tint
                            width: 18
                            height: 18
                            radius: 4
                            color: checked
                                ? Qt.rgba(tint.r, tint.g, tint.b, 0.13) : "#a602070c"
                            border.width: 1
                            border.color: Qt.rgba(tint.r, tint.g, tint.b,
                                checked ? 0.72 : checkoutMouse.containsMouse ? 0.36 : 0.10)
                            opacity: checked || checkoutMouse.containsMouse ? 1 : 0.45
                            RoleIcon {
                                id: roleGlyph
                                anchors.centerIn: parent
                                width: 14
                                height: 14
                                role: checkoutButton.modelData.role
                            }
                            MouseArea {
                                id: checkoutMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                enabled: !root.busyCheckouts[root.checkoutKey(
                                    row.modelData.node.backingPath,
                                    checkoutButton.modelData.id)]
                                onClicked: root.toggleCheckout(
                                    row.modelData.node.backingPath,
                                    checkoutButton.modelData.id
                                )
                                ToolTip.visible: containsMouse
                                ToolTip.delay: 400
                                ToolTip.text: (checkoutButton.checked ? "Return " : "Check out ")
                                    + row.modelData.node.backingPath + " "
                                    + (checkoutButton.checked ? "from " : "to ")
                                    + checkoutButton.modelData.label
                            }
                        }
                    }
                }
                MouseArea {
                    id: folderMouse
                    anchors.left: parent.left
                    anchors.right: checkoutRow.left
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.toggleFolder(row.modelData.node.key)
                    ToolTip.visible: containsMouse
                    ToolTip.delay: 400
                    ToolTip.text: [row.modelData.node.subtitle,
                        row.modelData.node.backingPath].filter(Boolean).join("\n")
                }
            }

            Rectangle {
                id: fileRow
                visible: row.modelData.type === "file"
                anchors.fill: parent
                radius: 3
                color: row.modelData.node && row.modelData.node.file.key === root.selectedKey
                    ? "#1fc4b5fd" : fileMouse.containsMouse ? "#0ec4b5fd" : "transparent"
                Text {
                    id: fileIcon
                    anchors.left: parent.left
                    anchors.leftMargin: 17 + row.modelData.depth * 12
                    anchors.verticalCenter: parent.verticalCenter
                    width: 15
                    text: "▤"
                    color: row.modelData.node && row.modelData.node.file.storage === "system"
                        ? "#996ee7b7"
                        : row.modelData.node && row.modelData.node.file.storage === "knowledge"
                            ? "#997dd3fc" : row.modelData.node
                                && row.modelData.node.file.storage === "code"
                                ? "#9967e8f9" : "#8cc4b5fd"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 10
                }
                Text {
                    anchors.left: fileIcon.right
                    anchors.right: fileSize.left
                    anchors.rightMargin: 5
                    anchors.verticalCenter: parent.verticalCenter
                    text: row.modelData.node ? row.modelData.node.name : ""
                    color: row.modelData.node && row.modelData.node.file.key === root.selectedKey
                        ? "#f5f3ff" : "#8fede9fe"
                    elide: Text.ElideRight
                    font.family: "JetBrains Mono"
                    font.pixelSize: 9
                }
                Text {
                    id: fileSize
                    anchors.right: parent.right
                    anchors.rightMargin: 4
                    anchors.verticalCenter: parent.verticalCenter
                    text: row.modelData.node
                        ? root.readableBytes(row.modelData.node.file.size || 0) : ""
                    color: "#40c4b5fd"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 7
                }
                MouseArea {
                    id: fileMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.presentSource(row.modelData.node.file.key)
                }
            }

            Text {
                visible: row.modelData.type === "empty"
                anchors.fill: parent
                wrapMode: Text.Wrap
                text: root.selectedRef && !root.showAll
                    ? "This Article has no linked physical Source files."
                    : "No physical Obsidience Source files are available."
                color: "#59ede9fe"
                font.family: "JetBrains Mono"
                font.pixelSize: 9
            }

            Rectangle {
                visible: row.modelData.type === "issue"
                anchors.fill: parent
                anchors.margins: 2
                radius: 4
                color: "#09fcd34d"
                border.width: 1
                border.color: "#33fcd34d"
                Text {
                    anchors.fill: parent
                    anchors.margins: 6
                    text: row.modelData.issue
                        ? row.modelData.issue.status + " · " + row.modelData.issue.path : ""
                    color: "#b3fde68a"
                    elide: Text.ElideRight
                    font.family: "JetBrains Mono"
                    font.pixelSize: 8
                }
            }
        }
    }
}
