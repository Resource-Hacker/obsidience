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
    readonly property var checkoutAgents: [
        {"id": "executive", "label": "Executive", "role": "executive"},
        {"id": "guardian", "label": "Heimdall", "role": "guardian"},
        {"id": "curator", "label": "Alexandria", "role": "curator"},
        {"id": "researcher", "label": "Darwin", "role": "researcher"}
    ]

    property var files: []
    property var issues: []
    property var storage: null
    property var checkouts: ({})
    property var busyCheckouts: ({})
    property var visibleRows: []
    property var expandedPaths: ({
        "@view/system": true,
        "@view/system/hardware": true,
        "@view/system/hardware/drives": true,
        "@view/system/hardware/drives/system-volume": true,
        "@view/system/hardware/drives/system-volume/obsidience": true,
        "@view/system/applications": true
    })
    property string selectedRef: ""
    property string selectedKey: ""
    property string query: ""
    property bool showAll: false
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
        if (!ref.startsWith("@branch/")) return false
        const branch = ref.slice("@branch/".length)
        if (branch === "ADMECH Workstation" && file.storage === "system") return true
        return file.articles.some(article => article === branch
            || article.startsWith(branch + "/"))
    }

    function route(file) {
        const compute = systemPrefix + "/hardware/compute/"
        const devices = systemPrefix + "/hardware/devices/"
        const applications = systemPrefix + "/applications/"
        const network = systemPrefix + "/network/"
        const volume = systemPrefix + "/hardware/drives/system-volume/"
        const models = "obsidience/evidence/models/"
        if (file.path.startsWith(compute)) {
            return {"parent": "compute", "relative": file.path.slice(compute.length),
                "base": compute.slice(0, -1)}
        }
        if (file.path.startsWith(devices)) {
            return {"parent": "devices", "relative": file.path.slice(devices.length),
                "base": devices.slice(0, -1)}
        }
        if (file.path.startsWith(applications)) {
            return {"parent": "applications",
                "relative": file.path.slice(applications.length),
                "base": applications.slice(0, -1)}
        }
        if (file.path.startsWith(network)) {
            return {"parent": "network", "relative": file.path.slice(network.length),
                "base": network.slice(0, -1)}
        }
        if (file.path === volume + "obsidience.json") {
            return {"parent": "obsidience", "relative": file.name,
                "base": volume.slice(0, -1)}
        }
        if (file.path === volume + "ai-models.json") {
            return {"parent": "models", "relative": file.name,
                "base": volume.slice(0, -1)}
        }
        if (file.path.startsWith(models)) {
            return {"parent": "models", "relative": file.path.slice(models.length),
                "base": models.slice(0, -1)}
        }
        if (file.path === systemPrefix + "/system.json") {
            return {"parent": "system", "relative": file.name, "base": systemPrefix}
        }
        const productPrefix = "obsidience/"
        return {"parent": "obsidience",
            "relative": file.path.startsWith(productPrefix)
                ? file.path.slice(productPrefix.length) : file.path,
            "base": file.path.startsWith(productPrefix) ? "obsidience" : ""}
    }

    function storageLocation(id) {
        if (!storage || !Array.isArray(storage.locations)) return null
        return storage.locations.find(value => value.id === id) || null
    }

    function storageFilesystem(location) {
        if (!location || !storage || !Array.isArray(storage.filesystems)) return null
        return storage.filesystems.find(value => value.id === location.filesystem_id) || null
    }

    function folder(key, name, backingPath, subtitle, virtual, order) {
        return {"key": key, "name": name, "folder": true,
            "backingPath": backingPath || "", "subtitle": subtitle || "",
            "virtual": virtual === true, "order": order === undefined ? 999 : order,
            "children": []}
    }

    function buildTree(scopedFiles) {
        if (!scopedFiles.length) return []
        const obsLocation = storageLocation("obsidience")
        const modelLocation = storageLocation("models")
        const sharedFilesystem = storage && Array.isArray(storage.filesystems)
                && storage.filesystems.length === 1 ? storage.filesystems[0] : null
        const obsidience = folder("@view/system/hardware/drives/system-volume/obsidience",
            "OBSIDIENCE", "obsidience", obsLocation && obsLocation.available
                ? obsLocation.path + " · shared filesystem · no quota"
                : "Storage unavailable", true, 0)
        const models = folder("@view/system/hardware/drives/system-volume/models",
            modelLocation && modelLocation.label ? modelLocation.label : "AI Models",
            "obsidience/evidence/models", modelLocation && modelLocation.available
                ? modelLocation.path + " · shared filesystem · no quota"
                : "Storage unavailable", true, 1)
        const volume = folder("@view/system/hardware/drives/system-volume",
            "SYSTEM VOLUME", systemPrefix + "/hardware/drives/system-volume",
            sharedFilesystem ? "BTRFS · one shared physical capacity pool"
                : "Physical storage volume", true, 0)
        volume.filesystem = sharedFilesystem
        volume.children = [obsidience, models]
        const compute = folder("@view/system/hardware/compute", "COMPUTE",
            systemPrefix + "/hardware/compute", "Processors and accelerators", true, 0)
        const drives = folder("@view/system/hardware/drives", "DRIVES",
            systemPrefix + "/hardware/drives", "Volumes and their actual files", true, 1)
        drives.children = [volume]
        const devices = folder("@view/system/hardware/devices", "DEVICES",
            systemPrefix + "/hardware/devices", "Input and output", true, 2)
        const hardware = folder("@view/system/hardware", "HARDWARE",
            systemPrefix + "/hardware", "Physical computer", true, 0)
        hardware.children = [compute, drives, devices]
        const applications = folder("@view/system/applications", "APPLICATIONS",
            systemPrefix + "/applications",
            "Obsidience shell and integrated applications", true, 1)
        const system = folder("@view/system", "SYSTEM", systemPrefix, "This PC", true, 0)
        system.children = [hardware, applications]
        const network = folder("@view/network", "NETWORK", systemPrefix + "/network",
            "Connections and remote systems", true, 1)
        const parents = {"system": system, "obsidience": obsidience,
            "compute": compute, "devices": devices,
            "applications": applications, "network": network, "models": models}
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
                    const systemFolder = prefix.startsWith(systemPrefix + "/")
                    child = folder(prefix,
                        systemFolder ? part.replace(/[-_]+/g, " ").toUpperCase() : part,
                        prefix, "", false)
                    children.push(child)
                }
                children = child.children
            }
            children.push({"key": file.key, "name": filename,
                "folder": false, "file": file, "children": []})
        }
        function prune(nodes) {
            const result = []
            for (const node of nodes) {
                if (!node.folder) { result.push(node); continue }
                node.children = prune(node.children)
                if (node.children.length || node.key === "@view/system"
                        || node.key === "@view/system/hardware"
                        || node.key === "@view/system/hardware/drives"
                        || node.key === "@view/system/hardware/drives/system-volume"
                        || node.key === "@view/system/hardware/drives/system-volume/obsidience") {
                    result.push(node)
                }
            }
            return result
        }
        function sort(nodes) {
            nodes.sort(function(left, right) {
                if (left.order !== undefined || right.order !== undefined) {
                    const difference = (left.order ?? 999) - (right.order ?? 999)
                    if (difference) return difference
                }
                if (left.folder !== right.folder) return left.folder ? -1 : 1
                return left.name.localeCompare(right.name)
            })
            for (const node of nodes) sort(node.children)
        }
        const roots = prune([system, network])
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
            scoped = files.filter(file => file.key === selectedKey
                || sourceMatchesArticle(file, selectedRef))
        }
        const tree = filterTree(buildTree(scoped), query.trim().toLowerCase())
        const rows = []
        function rowNode(node) {
            return Object.assign({
                "key": "", "name": "", "folder": false,
                "subtitle": "", "backingPath": "", "virtual": false,
                "filesystem": null,
                "file": {"key": "", "storage": "", "size": 0},
                "children": []
            }, node || {})
        }
        function append(nodes, depth) {
            for (const node of nodes) {
                rows.push({"type": node.folder ? "folder" : "file",
                    "node": rowNode(node), "depth": depth})
                if (node.key === "@view/system/hardware/drives/system-volume"
                        && node.filesystem && (expandedPaths[node.key] || query.trim())) {
                    rows.push({"type": "capacity", "node": rowNode(node),
                        "depth": depth + 1})
                }
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
        let hardwarePayload = null
        let checkoutPayload = null
        function finish() {
            if (!root || generation !== root.requestGeneration || sourcePayload === null
                    || hardwarePayload === null || checkoutPayload === null) return
            root.files = sourcePayload.files
            root.issues = sourcePayload.issues
            root.storage = hardwarePayload.storage || null
            const next = {}
            for (const assignment of checkoutPayload.assignments || []) {
                next[root.checkoutKey(assignment.tree, assignment.agent)] = true
            }
            root.checkouts = next
            root.loading = false
            root.rebuildRows()
        }
        function load(path, accept) {
            const request = new XMLHttpRequest()
            request.open("GET", "http://127.0.0.1:8765" + path)
            request.onreadystatechange = function() {
                if (request.readyState !== XMLHttpRequest.DONE || !root) return
                if (request.status < 200 || request.status >= 300) {
                    if (generation === root.requestGeneration) {
                        root.loading = false
                        root.errorMessage = request.responseText
                            || "Source hierarchy is unavailable."
                    }
                    return
                }
                try { accept(JSON.parse(request.responseText)); finish() }
                catch (error) {
                    if (root && generation === root.requestGeneration) {
                        root.loading = false
                        root.errorMessage = "Source hierarchy response was invalid."
                    }
                }
            }
            request.send()
        }
        load("/api/source-files", payload => {
            if (!payload || !Array.isArray(payload.files)
                    || !Array.isArray(payload.issues)) throw new Error("invalid source")
            sourcePayload = payload
        })
        load("/api/hardware", payload => { hardwarePayload = payload || {} })
        load("/api/source-checkouts", payload => {
            checkoutPayload = payload && Array.isArray(payload.assignments)
                ? payload : {"assignments": []}
        })
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
                showAll = false
            } else if (event.selection.kind === "source") {
                selectedKey = String(event.selection.key || "")
            }
            rebuildRows()
        } else if (event.type === "pane.dock.state" && event.layout) {
            dockLayout.applyRecord(event.layout)
        }
    }

    Component.onCompleted: refresh()
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
        height: root.selectedRef ? 88 : 56
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
            height: modelData.type === "capacity" ? 50
                : modelData.type === "folder" && modelData.node.subtitle ? 34
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
                        : row.modelData.node.key === "@view/network" ? "⌁" : "▱"
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

            Rectangle {
                visible: row.modelData.type === "capacity"
                anchors.fill: parent
                anchors.leftMargin: 18 + row.modelData.depth * 12
                anchors.rightMargin: 4
                anchors.topMargin: 2
                anchors.bottomMargin: 4
                radius: 4
                color: "#060ea5e9"
                border.width: 1
                border.color: "#1a7dd3fc"
                property var filesystem: row.modelData.node
                    ? row.modelData.node.filesystem : null
                Text {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 6
                    text: parent.filesystem
                        ? String(parent.filesystem.filesystem || "Filesystem").toUpperCase()
                            + " · shared by Obsidience and AI Models"
                        : "Shared filesystem"
                    color: "#737dd3fc"
                    elide: Text.ElideRight
                    font.family: "JetBrains Mono"
                    font.pixelSize: 7
                }
                Rectangle {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.leftMargin: 6
                    anchors.rightMargin: 6
                    height: 4
                    radius: 2
                    color: "#1a7dd3fc"
                    Rectangle {
                        width: parent.width * Math.max(0, Math.min(100,
                            parent.parent.filesystem
                                ? parent.parent.filesystem.used_percent : 0)) / 100
                        height: parent.height
                        radius: 2
                        gradient: Gradient {
                            orientation: Gradient.Horizontal
                            GradientStop { position: 0; color: "#8c22d3ee" }
                            GradientStop { position: 1; color: "#a6a78bfa" }
                        }
                    }
                }
                Text {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    anchors.margins: 6
                    text: parent.filesystem
                        ? root.readableBytes(parent.filesystem.used_bytes) + " used · "
                            + root.readableBytes(parent.filesystem.available_bytes)
                            + " free · " + root.readableBytes(parent.filesystem.total_bytes)
                            + " total" : "Capacity unavailable"
                    color: "#527dd3fc"
                    elide: Text.ElideRight
                    font.family: "JetBrains Mono"
                    font.pixelSize: 7
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
