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

    property var files: []
    property var graphNodes: []
    property var navigation: ({"groups": []})
    property var groups: []
    property var visibleRows: []
    property var expandedGroups: ({"executive": true})
    property var expandedPaths: ({})
    property string selectedRef: ""
    property string selectedGraphId: ""
    property string query: ""
    property bool loading: false
    property string errorMessage: ""
    property string bridgeError: ""
    property int requestGeneration: 0

    color: "#bf020a12"
    clip: true

    function cleanRef(value) {
        if (typeof value !== "string") return ""
        return value.trim().replace(/^\[\[/, "").replace(/\]\]$/, "")
            .split("|")[0]
    }

    function roleTint(role) {
        switch (role) {
        case "curator": return "#fbbf24"
        case "researcher": return "#c084fc"
        case "guardian": return "#60a5fa"
        case "library": return "#34d399"
        default: return "#67e8f9"
        }
    }

    function graphMap() {
        const result = {}
        for (const node of graphNodes) {
            if (node && typeof node.id === "string") result[node.id] = node
        }
        return result
    }

    function graphNode(ref, byId, namespace, visiting) {
        const node = byId[ref]
        if (!node || visiting[ref]) return null
        const nextVisiting = Object.assign({}, visiting)
        nextVisiting[ref] = true
        const children = []
        for (const rawChild of Array.isArray(node.children) ? node.children : []) {
            const child = graphNode(cleanRef(rawChild), byId, namespace, nextVisiting)
            if (child) children.push(child)
        }
        return {
            "key": "projection:" + namespace + ":" + ref,
            "name": typeof node.title === "string" ? node.title : ref.split("/").pop(),
            "path": ref,
            "folder": children.length > 0,
            "ref": ref,
            "kind": typeof node.kind === "string" ? node.kind : "knowledge",
            "virtual": true,
            "children": children
        }
    }

    function projectionRoots(refs, namespace, allowedRefs) {
        const byId = graphMap()
        if (Array.isArray(allowedRefs)) {
            const allowed = new Set(allowedRefs)
            for (const ref of Object.keys(byId)) {
                if (!allowed.has(ref)) delete byId[ref]
            }
        }
        const aliases = {}
        for (const node of Object.values(byId)) {
            if (node.article_ref) aliases[node.article_ref] = node.id
        }
        const requested = {}
        for (const rawRef of refs) {
            const canonical = cleanRef(rawRef)
            const ref = aliases[canonical] || canonical
            if (byId[ref]) requested[ref] = true
        }
        const parent = {}
        for (const node of Object.values(byId)) {
            for (const rawChild of Array.isArray(node.children) ? node.children : []) {
                parent[cleanRef(rawChild)] = node.id
            }
        }
        for (const ref of Object.keys(requested)) {
            let cursor = parent[ref]
            const seen = {}
            while (cursor && !seen[cursor]) {
                seen[cursor] = true
                requested[cursor] = true
                cursor = parent[cursor]
            }
        }
        const roots = Object.keys(requested).filter(function(ref) {
            let cursor = parent[ref]
            const seen = {}
            while (cursor && !seen[cursor]) {
                seen[cursor] = true
                if (requested[cursor]) return false
                cursor = parent[cursor]
            }
            return true
        })
        const result = []
        for (const ref of roots) {
            const projected = graphNode(ref, byId, namespace, {})
            if (projected) result.push(projected)
        }
        result.sort((left, right) => left.name.localeCompare(right.name))
        return result
    }

    function buildFileTree(entries, stripPrefix) {
        const roots = []
        const folders = {}
        const prefix = String(stripPrefix || "").replace(/\/$/, "")
        for (const file of entries) {
            if (!file || typeof file.path !== "string"
                    || typeof file.ref !== "string") continue
            const displayPath = prefix && file.path.startsWith(prefix + "/")
                ? file.path.slice(prefix.length + 1) : file.path
            const parts = displayPath.replace(/\.md$/i, "").split("/")
                .filter(Boolean)
            const basename = parts.pop() || file.title
            let siblings = roots
            let currentPath = prefix
            let parent = null
            for (const part of parts) {
                currentPath = currentPath ? currentPath + "/" + part : part
                const key = "folder:" + currentPath
                let folder = folders[key]
                if (!folder) {
                    folder = {
                        "key": key, "name": part, "path": currentPath,
                        "folder": true, "ref": "@branch/" + currentPath,
                        "kind": "knowledge", "children": []
                    }
                    folders[key] = folder
                    siblings.push(folder)
                }
                parent = folder
                siblings = folder.children
            }
            if (parent && file.kind === "knowledge"
                    && String(basename).toLowerCase()
                        === currentPath.split("/").pop().toLowerCase()) {
                parent.ref = file.ref
                parent.kind = file.kind
                parent.name = file.title
            } else {
                siblings.push({
                    "key": "file:" + file.ref,
                    "name": file.title || basename,
                    "path": file.path,
                    "folder": false,
                    "ref": file.ref,
                    "kind": file.kind || "knowledge",
                    "children": []
                })
            }
        }
        function sort(rows) {
            rows.sort(function(left, right) {
                if (left.folder !== right.folder) return left.folder ? -1 : 1
                return left.name.toLowerCase().localeCompare(right.name.toLowerCase())
            })
            for (const node of rows) sort(node.children)
        }
        sort(roots)
        return roots
    }

    function subjectTree(group) {
        const subjects = {}
        const roots = []
        for (const subject of Array.isArray(group.subjects) ? group.subjects : []) {
            subjects[subject.id] = {
                "key": "subject:" + group.id + ":" + subject.id,
                "name": subject.title, "path": subject.id,
                "folder": true, "ref": subject.id, "kind": "knowledge",
                "virtual": true, "children": []
            }
        }
        for (const subject of Array.isArray(group.subjects) ? group.subjects : []) {
            const node = subjects[subject.id]
            if (subject.parent_id && subjects[subject.parent_id]) {
                subjects[subject.parent_id].children.push(node)
            } else {
                roots.push(node)
            }
        }
        return {"roots": roots, "subjects": subjects}
    }

    function subjectByTitle(subjects, title) {
        const needle = String(title || "").toLowerCase()
        for (const id of Object.keys(subjects)) {
            if (String(subjects[id].name).toLowerCase() === needle) return subjects[id]
        }
        return null
    }

    function groupFiles(groupId) {
        if (groupId === "guardian") {
            return files.filter(file => file.path.startsWith("Agents/Heimdall/"))
        }
        if (groupId === "curator") {
            return files.filter(file => file.path.startsWith("Agents/Alexandria/"))
        }
        if (groupId === "researcher") {
            return files.filter(file => file.path.startsWith("Agents/Darwin/")
                || file.path.startsWith("Sources/"))
        }
        if (groupId === "library") {
            return files.filter(file => /^(Tools|Skills|Tasks)\//.test(file.path))
        }
        return files.filter(file => !file.path.startsWith("Agents/Heimdall/")
            && !file.path.startsWith("Agents/Alexandria/")
            && !file.path.startsWith("Agents/Darwin/")
            && !/^(Tools|Skills|Tasks)\//.test(file.path))
    }

    function countRefs(nodes) {
        const refs = {}
        function visit(rows) {
            for (const node of rows) {
                if (node.ref && !String(node.ref).startsWith("@")) refs[node.ref] = true
                visit(node.children || [])
            }
        }
        visit(nodes)
        return Object.keys(refs).length
    }

    function buildGroups() {
        const result = []
        const byId = graphMap()
        for (const group of Array.isArray(navigation.groups)
                ? navigation.groups : []) {
            const spec = subjectTree(group)
            const identity = byId[group.root_ref]
            if (group.id === "library") {
                // Match the Library graph: a Tool represents its paired Skill,
                // and Task taxonomy indexes retain the declared hierarchy.
                const capabilities = spec.subjects["@library/Tools"]
                const tasks = spec.subjects["@library/Tasks"]
                const members = group.article_refs || []
                const libraryNodes = graphNodes.filter(node => members.includes(node.id))
                if (capabilities) {
                    capabilities.children = projectionRoots(
                        libraryNodes.filter(node => node.kind === "tool").map(node => node.id),
                        "library:capabilities", members
                    )
                }
                if (tasks) {
                    tasks.children = projectionRoots(
                        libraryNodes.filter(node => node.kind === "task"
                            || (Array.isArray(node.tags) && node.tags.includes("task-taxonomy")))
                            .map(node => node.id), "library:tasks", members
                    )
                }
                result.push({
                    "id": group.id, "label": group.title,
                    "subtitle": group.subtitle, "role": group.role,
                    "rootRef": group.root_ref, "tree": spec.roots,
                    "count": countRefs(spec.roots)
                })
                // Raw files belong to Source, not a duplicate Library tree.
                continue
            } else if (identity && identity.dependencies) {
                for (const field of ["tools", "skills", "runbooks", "tasks"]) {
                    const subjectId = group.id === "executive"
                        ? "@branch/" + field.slice(0, 1).toUpperCase() + field.slice(1)
                        : "@sat/" + group.root_ref.split("/")[1] + "/" + field
                    const subject = spec.subjects[subjectId]
                    if (subject) {
                        subject.children = projectionRoots(
                            Array.isArray(identity.dependencies[field])
                                ? identity.dependencies[field] : [],
                            group.id + ":" + field,
                            group.article_refs || []
                        )
                    }
                }
            }

            const members = new Set(group.article_refs || [])
            const physical = groupFiles(group.id).filter(file =>
                file.kind === "knowledge" && members.has(file.ref))
            if (group.id === "executive") {
                // Navigation owns folder identity, title and parentage. Attach
                // each physical leaf once; its declared Article is the folder.
                for (const declared of group.subjects || []) {
                    if (!declared.path) continue
                    const subject = spec.subjects[declared.id]
                    subject.ref = declared.article_ref || declared.id
                    for (const file of physical) {
                        if (file.kind !== "knowledge"
                                || file.path.slice(0, file.path.lastIndexOf("/")) !== declared.path
                                || file.ref === declared.article_ref) continue
                        subject.children.push({
                            "key": "file:" + file.ref, "name": file.title,
                            "path": file.path, "folder": false, "ref": file.ref,
                            "kind": file.kind, "children": []
                        })
                    }
                }
                const subagents = spec.subjects["@agent/Subagents"]
                if (subagents) subagents.children = projectionRoots(
                    graphNodes.filter(node => node.kind === "agent" && node.id !== group.root_ref)
                        .map(node => node.id), "executive:subagents"
                )
                result.push({
                    "id": group.id, "label": group.title,
                    "subtitle": group.subtitle, "role": group.role,
                    "rootRef": group.root_ref, "tree": spec.roots,
                    "count": countRefs(spec.roots)
                })
                continue
            }
            let prefix = ""
            if (group.id === "guardian") prefix = "Agents/Heimdall"
            if (group.id === "curator") prefix = "Agents/Alexandria"
            if (group.id === "researcher") prefix = "Agents/Darwin"
            if (group.id === "executive") prefix = "Agents/Executive"
            const localFiles = prefix
                ? physical.filter(file => file.path.startsWith(prefix + "/")) : []
            const localTree = buildFileTree(localFiles, prefix)
            for (const node of localTree) {
                const subject = subjectByTitle(spec.subjects, node.name)
                if (subject) {
                    subject.children = subject.children.concat(node.children)
                    if (node.ref && !String(node.ref).startsWith("@branch/")) {
                        subject.ref = node.ref
                    }
                } else {
                    spec.roots.push(node)
                }
            }
            const remaining = physical.filter(file => !prefix
                || !file.path.startsWith(prefix + "/"))
            spec.roots = spec.roots.concat(buildFileTree(remaining, ""))
            result.push({
                "id": group.id, "label": group.title,
                "subtitle": group.subtitle, "role": group.role,
                "rootRef": group.root_ref, "tree": spec.roots,
                "count": countRefs(spec.roots)
            })
        }
        groups = result
        if (Object.keys(expandedPaths).length === 0) {
            const defaults = {}
            for (const group of result) {
                for (const node of group.tree) if (node.folder) defaults[node.key] = true
            }
            expandedPaths = defaults
        }
        revealSelection()
        rebuildRows()
    }

    function filteredTree(nodes, needle) {
        if (!needle) return nodes
        const result = []
        for (const node of nodes) {
            const children = filteredTree(node.children || [], needle)
            if (String(node.name).toLowerCase().includes(needle)
                    || String(node.ref || "").toLowerCase().includes(needle)
                    || children.length > 0) {
                result.push(Object.assign({}, node, {"children": children}))
            }
        }
        return result
    }

    function rebuildRows() {
        const rows = []
        const needle = query.trim().toLowerCase()
        function rowNode(node) {
            return Object.assign({
                "key": "", "name": "", "ref": "", "kind": "knowledge",
                "folder": false, "children": []
            }, node || {})
        }
        for (const group of groups) {
            const tree = filteredTree(group.tree, needle)
            const groupMatches = (group.label + " " + group.subtitle)
                .toLowerCase().includes(needle)
            if (needle && !groupMatches && tree.length === 0) continue
            rows.push({"type": "group", "group": group,
                "node": rowNode(null), "depth": 0})
            if (!expandedGroups[group.id] && !needle) continue
            function append(nodes, depth) {
                for (const node of nodes) {
                    rows.push({"type": "node", "group": group,
                        "node": rowNode(node), "depth": depth})
                    if (node.folder && (expandedPaths[node.key] || needle)) {
                        append(node.children || [], depth + 1)
                    }
                }
            }
            if (tree.length) append(tree, 0)
            else rows.push({"type": "empty", "group": group,
                "node": rowNode(null), "depth": 0})
        }
        visibleRows = rows
    }

    function setExpanded(map, key, value) {
        const next = Object.assign({}, map)
        next[key] = value
        return next
    }

    function toggleGroup(groupId) {
        expandedGroups = setExpanded(expandedGroups, groupId, !expandedGroups[groupId])
        rebuildRows()
    }

    function toggleNode(key) {
        expandedPaths = setExpanded(expandedPaths, key, !expandedPaths[key])
        rebuildRows()
    }

    function findPath(nodes, ref) {
        for (const node of nodes) {
            if (node.ref === ref) return [node]
            const child = findPath(node.children || [], ref)
            if (child) return [node].concat(child)
        }
        return null
    }

    function revealSelection() {
        if (!selectedRef) return
        for (const group of groups) {
            if (selectedGraphId && graphIdForGroup(group) !== selectedGraphId) continue
            const path = findPath(group.tree, selectedRef)
            if (!path) continue
            expandedGroups = setExpanded(expandedGroups, group.id, true)
            const next = Object.assign({}, expandedPaths)
            for (const node of path) if (node.folder) next[node.key] = true
            expandedPaths = next
            return
        }
    }

    function refresh() {
        loading = true
        errorMessage = ""
        requestGeneration += 1
        const generation = requestGeneration
        let nextFiles = null
        let nextGraph = null
        function finish() {
            if (!root || generation !== root.requestGeneration
                    || nextFiles === null || nextGraph === null) return
            root.files = nextFiles
            root.graphNodes = Array.isArray(nextGraph.nodes) ? nextGraph.nodes : []
            root.navigation = nextGraph.navigation
                && Array.isArray(nextGraph.navigation.groups)
                ? nextGraph.navigation : {"groups": []}
            root.loading = false
            root.buildGroups()
        }
        function fail(message) {
            if (root && generation === root.requestGeneration) {
                root.loading = false
                root.errorMessage = message
            }
        }
        const filesRequest = new XMLHttpRequest()
        filesRequest.open("GET", "http://127.0.0.1:8765/api/files")
        filesRequest.onreadystatechange = function() {
            if (filesRequest.readyState !== XMLHttpRequest.DONE) return
            if (filesRequest.status < 200 || filesRequest.status >= 300) {
                fail(filesRequest.responseText || "Knowledge hierarchy is unavailable.")
                return
            }
            try {
                nextFiles = JSON.parse(filesRequest.responseText)
                if (!Array.isArray(nextFiles)) throw new Error("invalid files")
                finish()
            } catch (error) { fail("Knowledge hierarchy response was invalid.") }
        }
        const graphRequest = new XMLHttpRequest()
        graphRequest.open("GET", "http://127.0.0.1:8765/api/graph")
        graphRequest.onreadystatechange = function() {
            if (graphRequest.readyState !== XMLHttpRequest.DONE) return
            if (graphRequest.status < 200 || graphRequest.status >= 300) {
                fail(graphRequest.responseText || "Knowledge graph is unavailable.")
                return
            }
            try {
                nextGraph = JSON.parse(graphRequest.responseText)
                if (!nextGraph || !Array.isArray(nextGraph.nodes)) {
                    throw new Error("invalid graph")
                }
                finish()
            } catch (error) { fail("Knowledge graph response was invalid.") }
        }
        filesRequest.send()
        graphRequest.send()
    }

    function sendShellCommand(command) {
        if (shellSocket.status !== WebSocket.Open) {
            bridgeError = "Reader bridge is unavailable."
            return
        }
        bridgeError = ""
        shellSocket.sendTextMessage(JSON.stringify(command))
    }

    function graphIdForGroup(group) {
        return group.id === "executive" ? "main"
            : group.id === "library" ? "library" : group.rootRef.split("/")[1]
    }

    function presentArticle(ref, group) {
        if (!ref) return
        sendShellCommand({"schema": "obsidience.shell.command.v1",
            "type": "pane.present", "pane_id": "reader",
            "selection": {"kind": "article", "ref": ref,
                "graph_id": graphIdForGroup(group)}})
    }

    function applyShellEvent(message) {
        if (typeof message !== "string" || message.length > 65536) return
        let event
        try { event = JSON.parse(message) } catch (error) { return }
        if (!event || event.schema !== "obsidience.shell.event.v1") return
        if (event.type === "pane.state" && event.pane
                && event.pane.pane_id === "reader" && event.selection
                && event.selection.kind === "article") {
            selectedRef = String(event.selection.ref || "")
            selectedGraphId = String(event.selection.graph_id || "")
            revealSelection()
            rebuildRows()
        } else if (event.type === "pane.dock.state" && event.layout) {
            dockLayout.applyRecord(event.layout)
        }
    }

    Component.onCompleted: refresh()
    onQueryChanged: rebuildRows()

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
        height: 56
        color: "#bf020a12"

        PaneModuleHeader {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.leftMargin: 8
            anchors.rightMargin: 8
            anchors.topMargin: 3
            moduleId: "knowledge"
            title: "Knowledge"
            tint: "#67e8f9"
            dockLayout: root.dockLayout
            surfaceId: root.surfaceId
            countText: root.loading ? "LOADING" : String(root.files.length)
            onCommandRequested: command => root.sendShellCommand(command)
        }

        TextField {
            id: filterField
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            anchors.leftMargin: 8
            anchors.rightMargin: 8
            anchors.bottomMargin: 7
            height: 24
            placeholderText: "Filter articles"
            text: root.query
            color: "#ecfeff"
            placeholderTextColor: "#5967e8f9"
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
                color: "#020a12"
                border.width: 1
                border.color: filterField.activeFocus ? "#8067e8f9" : "#3367e8f9"
            }
        }
        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: "#1a67e8f9"
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
        spacing: 1
        boundsBehavior: Flickable.StopAtBounds
        model: root.visibleRows
        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

        delegate: Item {
            id: row
            required property var modelData
            width: hierarchyView.width
            height: modelData.type === "group" ? 50
                : modelData.type === "empty" ? 24 : 22

            Rectangle {
                id: groupCard
                visible: row.modelData.type === "group"
                anchors.fill: parent
                anchors.bottomMargin: 2
                radius: 4
                color: "#e6030b12"
                border.width: 1
                border.color: Qt.rgba(groupTint.r, groupTint.g, groupTint.b, 0.33)
                readonly property color groupTint: root.roleTint(row.modelData.group.role)

                RoleIcon {
                    anchors.left: parent.left
                    anchors.leftMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    width: 31
                    height: 31
                    role: row.modelData.group.role
                }
                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 48
                    anchors.right: readButton.left
                    anchors.rightMargin: 24
                    anchors.top: parent.top
                    anchors.topMargin: 10
                    text: row.modelData.group.label
                    color: groupCard.groupTint
                    elide: Text.ElideRight
                    font.family: "JetBrains Mono"
                    font.pixelSize: 10
                    font.capitalization: Font.AllUppercase
                    font.letterSpacing: 1.6
                }
                Text {
                    anchors.left: parent.left
                    anchors.leftMargin: 48
                    anchors.right: readButton.left
                    anchors.rightMargin: 6
                    anchors.bottom: parent.bottom
                    anchors.bottomMargin: 9
                    text: row.modelData.group.subtitle + " · " + row.modelData.group.count
                    color: "#59cffafe"
                    elide: Text.ElideRight
                    font.family: "JetBrains Mono"
                    font.pixelSize: 8
                    font.capitalization: Font.AllUppercase
                    font.letterSpacing: 0.96
                }
                Text {
                    anchors.right: readButton.left
                    anchors.rightMargin: 8
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.expandedGroups[row.modelData.group.id] ? "⌄" : "›"
                    color: groupCard.groupTint
                    font.family: "JetBrains Mono"
                    font.pixelSize: 13
                }
                Rectangle {
                    id: readButton
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    width: 32
                    color: readMouse.containsMouse
                        ? Qt.rgba(groupCard.groupTint.r, groupCard.groupTint.g,
                            groupCard.groupTint.b, 0.08) : "transparent"
                    Rectangle {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        anchors.bottom: parent.bottom
                        width: 1
                        color: Qt.rgba(groupCard.groupTint.r, groupCard.groupTint.g,
                            groupCard.groupTint.b, 0.20)
                    }
                    Text {
                        anchors.centerIn: parent
                        text: "▤"
                        color: Qt.rgba(groupCard.groupTint.r, groupCard.groupTint.g,
                            groupCard.groupTint.b, 0.68)
                        font.family: "JetBrains Mono"
                        font.pixelSize: 11
                    }
                    MouseArea {
                        id: readMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.presentArticle(row.modelData.group.rootRef, row.modelData.group)
                    }
                }
                MouseArea {
                    anchors.left: parent.left
                    anchors.right: readButton.left
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.toggleGroup(row.modelData.group.id)
                }
            }

            Text {
                visible: row.modelData.type === "empty"
                anchors.fill: parent
                leftPadding: 24
                verticalAlignment: Text.AlignVCenter
                text: "No knowledge assigned."
                color: "#4dcffafe"
                font.family: "JetBrains Mono"
                font.pixelSize: 8
            }

            Rectangle {
                id: nodeRow
                visible: row.modelData.type === "node"
                anchors.fill: parent
                color: row.modelData.node && row.modelData.node.ref === root.selectedRef
                    && (!root.selectedGraphId || root.graphIdForGroup(row.modelData.group) === root.selectedGraphId)
                    ? "#1a67e8f9"
                    : nodeMouse.containsMouse ? "#0c67e8f9" : "transparent"

                Text {
                    id: chevron
                    anchors.left: parent.left
                    anchors.leftMargin: 4 + row.modelData.depth * 12
                    anchors.verticalCenter: parent.verticalCenter
                    width: 16
                    text: row.modelData.node && row.modelData.node.folder
                        ? (root.expandedPaths[row.modelData.node.key] ? "⌄" : "›") : ""
                    color: "#7367e8f9"
                    horizontalAlignment: Text.AlignHCenter
                    font.family: "JetBrains Mono"
                    font.pixelSize: 10
                    MouseArea {
                        anchors.fill: parent
                        enabled: row.modelData.node && row.modelData.node.folder
                        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: mouse => {
                            mouse.accepted = true
                            root.toggleNode(row.modelData.node.key)
                        }
                    }
                }
                Text {
                    id: nodeIcon
                    anchors.left: chevron.right
                    anchors.verticalCenter: parent.verticalCenter
                    width: 16
                    text: row.modelData.node && row.modelData.node.folder ? "▱" : "▤"
                    color: row.modelData.node && row.modelData.node.folder
                        ? "#9967e8f9" : "#6667e8f9"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 10
                }
                Text {
                    anchors.left: nodeIcon.right
                    anchors.right: kindLabel.left
                    anchors.rightMargin: 4
                    anchors.verticalCenter: parent.verticalCenter
                    text: row.modelData.node ? row.modelData.node.name : ""
                    color: row.modelData.node && row.modelData.node.ref === root.selectedRef
                        && (!root.selectedGraphId || root.graphIdForGroup(row.modelData.group) === root.selectedGraphId)
                        ? "#ecfeff" : "#a6cffafe"
                    elide: Text.ElideRight
                    font.family: "JetBrains Mono"
                    font.pixelSize: 9
                }
                Text {
                    id: kindLabel
                    anchors.right: parent.right
                    anchors.rightMargin: 5
                    anchors.verticalCenter: parent.verticalCenter
                    text: row.modelData.node && !row.modelData.node.folder
                        ? String(row.modelData.node.kind || "").toUpperCase() : ""
                    color: "#5267e8f9"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 7
                }
                MouseArea {
                    id: nodeMouse
                    anchors.left: nodeIcon.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    hoverEnabled: true
                    cursorShape: row.modelData.node && row.modelData.node.ref
                        ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: {
                        if (row.modelData.node && row.modelData.node.ref) {
                            root.presentArticle(row.modelData.node.ref, row.modelData.group)
                        }
                    }
                }
            }
        }
    }
}
