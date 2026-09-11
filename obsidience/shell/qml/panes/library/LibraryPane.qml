pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtWebSockets
import "../../components/visual"

Rectangle {
    id: root

    property var nodes: []
    property var tasks: []
    property var navigationAgents: []
    property var expanded: ({})
    property var initializedShelves: ({})
    property var rows: []
    property string shelf: "task"
    property string query: ""
    property int reviewCount: 0
    property int acceptedCount: 0
    property int taskCount: 0
    property int toolCount: 0

    color: "#b302080e"
    clip: true

    function cleanLink(value) {
        return String(value ?? "").trim()
            .replace(/^\[\[/, "").replace(/\]\]$/, "").split("|")[0]
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

    function requestJson(method, path, body, callback) {
        const request = new XMLHttpRequest()
        request.open(method, "http://127.0.0.1:8765" + path)
        if (body !== undefined && body !== null) {
            request.setRequestHeader("content-type", "application/json")
        }
        request.onreadystatechange = function() {
            if (request.readyState !== XMLHttpRequest.DONE) {
                return
            }
            if (request.status < 200 || request.status >= 300) {
                callback(false, null, root.requestError(request, "Request failed (" + request.status + ")"))
                return
            }
            try {
                callback(true, request.responseText ? JSON.parse(request.responseText) : {}, "")
            } catch (error) {
                callback(false, null, "The harness returned invalid JSON.")
            }
        }
        request.send(body === undefined || body === null ? null : JSON.stringify(body))
    }

    function refresh() {
        requestJson("GET", "/api/graph", null, function(ok, payload) {
            if (!ok || !payload || !Array.isArray(payload.nodes)) {
                return
            }
            const groups = payload.navigation && Array.isArray(payload.navigation.groups)
                ? payload.navigation.groups : []
            const library = groups.find(group => group.id === "library")
            const members = new Set(library ? library.article_refs || [] : [])
            nodes = payload.nodes.filter(node => node && members.has(node.id)
                && (node.kind === "tool" || node.kind === "task"
                    || (Array.isArray(node.tags) && node.tags.includes("task-taxonomy"))))
            navigationAgents = groups.filter(group => group && group.role !== "library")
            updateCounts()
            rebuildRows()
        })
        requestJson("GET", "/api/tasks", null, function(ok, payload) {
            if (ok && Array.isArray(payload)) {
                tasks = payload
                rebuildRows()
            }
        })
        requestJson("GET", "/api/reviews", null, function(ok, payload) {
            if (ok && Array.isArray(payload)) {
                reviewCount = payload.length
            }
        })

    }

    function updateCounts() {
        taskCount = nodes.filter(node => node.kind === "task" && !node.synthetic).length
        toolCount = nodes.filter(node => node.kind === "tool" && !node.synthetic).length
        acceptedCount = nodes.filter(node => !node.synthetic).length
    }

    function rebuildRows() {
        const shelfNodes = nodes.filter(node => node.kind === shelf
            || (shelf === "task" && Array.isArray(node.tags)
                && node.tags.includes("task-taxonomy")))
        shelfNodes.sort((left, right) => {
            const leftOrder = Number.isFinite(Number(left.order))
                ? Number(left.order) : Number.MAX_SAFE_INTEGER
            const rightOrder = Number.isFinite(Number(right.order))
                ? Number(right.order) : Number.MAX_SAFE_INTEGER
            return leftOrder - rightOrder || String(left.title).localeCompare(String(right.title))
        })
        const byRef = {}
        for (const node of shelfNodes) {
            byRef[node.id] = node
        }
        const children = {}
        const childRefs = {}
        const parentOf = {}
        function resolve(raw) {
            const ref = root.cleanLink(raw)
            return byRef[ref]
        }
        for (const node of shelfNodes) {
            const childRows = []
            for (const raw of Array.isArray(node.children) ? node.children : []) {
                const child = resolve(raw)
                if (!child || child.id === node.id || parentOf[child.id]) {
                    continue
                }
                let cursor = node.id
                let cyclic = false
                while (parentOf[cursor]) {
                    cursor = parentOf[cursor]
                    if (cursor === child.id) {
                        cyclic = true
                        break
                    }
                }
                if (cyclic) {
                    continue
                }
                parentOf[child.id] = node.id
                childRefs[child.id] = true
                childRows.push(child)
            }
            children[node.id] = childRows
        }
        let roots = shelfNodes.filter(node => !childRefs[node.id])
        if (roots.length === 0) {
            roots = shelfNodes
        }

        if (!initializedShelves[shelf] && roots.length > 0) {
            const nextExpanded = Object.assign({}, expanded)
            for (const node of roots) {
                if ((children[node.id] || []).length > 0) {
                    nextExpanded[node.id] = true
                }
            }
            const nextInitialized = Object.assign({}, initializedShelves)
            nextInitialized[shelf] = true
            expanded = nextExpanded
            initializedShelves = nextInitialized
        }

        const taskByRef = {}
        for (const task of tasks) {
            taskByRef[task.ref] = task
        }
        const needle = query.trim().toLowerCase()
        const matchCache = {}
        const visiting = {}
        function matches(node) {
            if (!needle) {
                return true
            }
            return (String(node.title) + " " + String(node.id) + " "
                + (Array.isArray(node.tags) ? node.tags.join(" ") : ""))
                .toLowerCase().includes(needle)
        }
        function branchMatches(node) {
            if (matchCache[node.id] !== undefined) {
                return matchCache[node.id]
            }
            if (visiting[node.id]) {
                return false
            }
            visiting[node.id] = true
            const result = matches(node)
                || (children[node.id] || []).some(child => branchMatches(child))
            visiting[node.id] = false
            matchCache[node.id] = result
            return result
        }
        const visible = []
        const seen = {}
        function add(node, depth) {
            if (!node || seen[node.id] || !branchMatches(node)) {
                return
            }
            seen[node.id] = true
            const parentRef = parentOf[node.id] || ""
            let displayTitle = String(node.title)
            if (parentRef.startsWith("@library/Tools/")) {
                displayTitle = displayTitle.split(".").pop()
            }
            visible.push({
                "node": node,
                "depth": depth,
                "parentRef": parentRef,
                "displayTitle": displayTitle,
                "children": children[node.id] || [],
                "task": taskByRef[node.id] || null
            })
            if (!needle && !expanded[node.id]) {
                return
            }
            for (const child of children[node.id] || []) {
                add(child, depth + 1)
            }
        }
        for (const node of roots) {
            add(node, 0)
        }
        rows = visible
    }

    function selectShelf(nextShelf) {
        if (nextShelf === shelf) {
            return
        }
        shelf = nextShelf
        rebuildRows()
    }

    function toggleExpanded(ref) {
        const next = Object.assign({}, expanded)
        next[ref] = !next[ref]
        expanded = next
        rebuildRows()
    }

    function setQuery(value) {
        query = value
        rebuildRows()
    }

    function roleColor(role, dimmed) {
        const colors = {
            "executive": dimmed ? "#3467e8f9" : "#67e8f9",
            "guardian": dimmed ? "#3060a5fa" : "#60a5fa",
            "curator": dimmed ? "#30fbbf24" : "#fbbf24",
            "researcher": dimmed ? "#30c084fc" : "#c084fc"
        }
        return colors[role] || (dimmed ? "#305eead4" : "#5eead4")
    }

    function presentArticle(ref) {
        if (!ref || shellSocket.status !== WebSocket.Open) {
            return
        }
        shellSocket.sendTextMessage(JSON.stringify({
            "schema": "obsidience.shell.command.v1",
            "type": "pane.present",
            "pane_id": "reader",
            "selection": {"kind": "article", "ref": ref, "graph_id": "library"}
        }))
    }

    Component.onCompleted: refresh()

    Timer {
        interval: 10000
        repeat: true
        running: true
        onTriggered: root.refresh()
    }

    Rectangle {
        id: header

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        height: 54
        color: "#4005100f"

        Rectangle {
            anchors.left: parent.left
            anchors.leftMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            width: 30
            height: 30
            radius: 15
            color: "#175eead4"
            border.width: 1
            border.color: "#5a5eead4"

            RoleIcon {
                anchors.fill: parent
                anchors.margins: 3
                role: "library"
            }
        }

        Text {
            anchors.left: parent.left
            anchors.leftMargin: 52
            anchors.top: parent.top
            anchors.topMargin: 11
            text: "CURATED LIBRARY"
            color: "#a7f3d0"
            font.family: "JetBrains Mono"
            font.pixelSize: 10
            font.letterSpacing: 1.8
        }

        Text {
            anchors.left: parent.left
            anchors.leftMargin: 52
            anchors.top: parent.top
            anchors.topMargin: 31
            text: root.acceptedCount + " ACCEPTED   ·   "
                + root.reviewCount + " AWAITING CURATION"
            color: "#665eead4"
            font.family: "JetBrains Mono"
            font.pixelSize: 8
        }

        GlowButton {
            anchors.right: parent.right
            anchors.rightMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            width: 30
            height: 30
            text: "↻"
            accent: "#34d399"
            foreground: "#a7f3d0"
            idleBorderOpacity: 0
            hoverBorderOpacity: 0
            idleTextOpacity: 0.50
            hoverFillOpacity: 0.10
            textPixelSize: 14
            textLetterSpacing: 0
            contentHorizontalPadding: 0
            onClicked: root.refresh()
        }

        Rectangle {
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.bottom: parent.bottom
            height: 1
            color: "#305eead4"
        }
    }

    Row {
        id: shelves

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: header.bottom
        height: 38

        Repeater {
            model: [
                {"id": "task", "label": "TASKS"},
                {"id": "tool", "label": "TOOLS + SKILLS"}
            ]

            delegate: Rectangle {
                id: shelfButton

                required property var modelData
                width: shelves.width / 2
                height: shelves.height
                color: root.shelf === modelData.id ? "#175eead4" : "#4002080e"
                border.width: 1
                border.color: "#205eead4"

                Text {
                    anchors.centerIn: parent
                    text: shelfButton.modelData.label + "  "
                        + (shelfButton.modelData.id === "task" ? root.taskCount : root.toolCount)
                    color: root.shelf === shelfButton.modelData.id ? "#a7f3d0" : "#665eead4"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 9
                    font.letterSpacing: 1.1
                }

                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.selectShelf(shelfButton.modelData.id)
                }
            }
        }
    }

    TextField {
        id: searchField

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: shelves.bottom
        anchors.leftMargin: 10
        anchors.rightMargin: 10
        anchors.topMargin: 8
        height: 32
        text: root.query
        placeholderText: "Search " + (root.shelf === "task" ? "tasks" : "tools + skills")
        color: "#d1fae5"
        placeholderTextColor: "#3d5eead4"
        font.family: "JetBrains Mono"
        font.pixelSize: 10
        leftPadding: 10
        onTextChanged: root.setQuery(text)
        background: Rectangle {
            radius: 5
            color: "#d9020a0c"
            border.width: 1
            border.color: searchField.activeFocus ? "#805eead4" : "#305eead4"
        }
    }

    Rectangle {
        id: assignmentLegend

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: searchField.bottom
        anchors.leftMargin: 10
        anchors.rightMargin: 10
        anchors.topMargin: 6
        height: 30
        color: "transparent"
        border.width: 1
        border.color: "#185eead4"

        Text {
            anchors.left: parent.left
            anchors.leftMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            text: "CHECK OUT IN READER"
            color: "#405eead4"
            font.family: "JetBrains Mono"
            font.pixelSize: 8
            font.letterSpacing: 1.0
        }

        Row {
            anchors.right: parent.right
            anchors.rightMargin: 6
            anchors.verticalCenter: parent.verticalCenter
            spacing: 8

            Repeater {
                model: root.navigationAgents

                delegate: Row {
                    id: legendRole

                    required property var modelData
                    spacing: 3

                    Rectangle {
                        width: 17
                        height: 17
                        radius: 4
                        color: "#0d020a0c"
                        border.width: 1
                        border.color: root.roleColor(legendRole.modelData.role, true)

                        RoleIcon {
                            anchors.fill: parent
                            anchors.margins: 1
                            role: String(legendRole.modelData.role || "executive")
                        }
                    }

                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: String(legendRole.modelData.title).slice(0, 3).toUpperCase()
                        color: "#525eead4"
                        font.family: "JetBrains Mono"
                        font.pixelSize: 7
                    }
                }
            }
        }
    }

    ListView {
        id: libraryList

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: assignmentLegend.bottom
        anchors.bottom: parent.bottom
        anchors.topMargin: 4
        clip: true
        model: root.rows
        boundsBehavior: Flickable.StopAtBounds

        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
        }

        delegate: Rectangle {
            id: libraryRow

            required property var modelData
            width: libraryList.width
            height: 56
            color: rowMouse.containsMouse ? "#125eead4"
                : (modelData.node.kind === "knowledge" ? "#095eead4" : "transparent")
            border.width: 1
            border.color: modelData.node.kind === "knowledge" ? "#225eead4" : "#105eead4"

            MouseArea {
                id: rowMouse
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.NoButton
            }

            Rectangle {
                id: treeButton

                x: 7 + Math.min(90, libraryRow.modelData.depth * 15)
                y: 10
                width: 20
                height: 20
                radius: 3
                color: treeMouse.containsMouse && libraryRow.modelData.children.length > 0
                    ? "#185eead4" : "transparent"

                Text {
                    anchors.centerIn: parent
                    text: libraryRow.modelData.children.length === 0 ? "·"
                        : (root.expanded[libraryRow.modelData.node.id] ? "⌄" : "›")
                    color: libraryRow.modelData.children.length > 0 ? "#805eead4" : "#205eead4"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 13
                }

                MouseArea {
                    id: treeMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    enabled: libraryRow.modelData.children.length > 0
                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.toggleExpanded(libraryRow.modelData.node.id)
                }
            }

            Item {
                anchors.left: treeButton.right
                anchors.right: actions.left
                anchors.top: parent.top
                anchors.bottom: parent.bottom
                anchors.leftMargin: 3
                anchors.rightMargin: 6

                Text {
                    id: itemTitle

                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.topMargin: 8
                    text: libraryRow.modelData.displayTitle
                    color: libraryRow.modelData.children.length > 0 ? "#d1fae5" : "#b7ead8"
                    elide: Text.ElideRight
                    font.family: "JetBrains Mono"
                    font.pixelSize: 10
                    font.weight: libraryRow.modelData.children.length > 0
                        ? Font.DemiBold : Font.Normal
                    font.capitalization: libraryRow.modelData.children.length > 0
                        ? Font.AllUppercase : Font.MixedCase

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.presentArticle(libraryRow.modelData.node.id)
                    }
                }

                Text {
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: itemTitle.bottom
                    anchors.topMargin: 4
                    text: libraryRow.modelData.children.length > 0
                        ? libraryRow.modelData.children.length + " "
                            + (root.shelf === "task" ? "SUBTASKS" : "SUBTOOLS")
                        : (libraryRow.modelData.task
                            ? String(libraryRow.modelData.task.status).toUpperCase()
                            : (libraryRow.modelData.node.synthetic ? "ARTICLE" : libraryRow.modelData.node.id))
                    color: "#525eead4"
                    elide: Text.ElideRight
                    font.family: "JetBrains Mono"
                    font.pixelSize: 8
                }
            }

            Row {
                id: actions

                anchors.right: parent.right
                anchors.rightMargin: 8
                anchors.verticalCenter: parent.verticalCenter
                spacing: 5

                GlowButton {
                    id: skillButton

                    visible: root.shelf === "tool"
                    width: visible ? 50 : 0
                    height: 24
                    text: "SKILL"
                    accent: "#c084fc"
                    foreground: "#ddd6fe"
                    idleBorderOpacity: 0.20
                    hoverBorderOpacity: 0.45
                    idleTextOpacity: 0.60
                    textPixelSize: 7
                    textLetterSpacing: 0.8
                    contentHorizontalPadding: 6
                    onClicked: root.presentArticle("@library/Skills/"
                        + String(libraryRow.modelData.node.title).split(".").join("/"))
                }


            }
        }

        Text {
            anchors.centerIn: parent
            visible: root.rows.length === 0
            text: "NO MATCHING " + (root.shelf === "task" ? "TASKS" : "TOOLS + SKILLS")
            color: "#525eead4"
            font.family: "JetBrains Mono"
            font.pixelSize: 10
            font.letterSpacing: 1.0
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
