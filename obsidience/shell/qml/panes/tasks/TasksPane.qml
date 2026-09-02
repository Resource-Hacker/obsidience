pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtWebSockets
import "../../components/visual"

Rectangle {
    id: root

    property var tasks: []
    property var graphNodes: []
    property var navigationAgents: []
    property var models: []
    property var rows: []
    property var taskCatalog: []
    property var expanded: ({})
    property bool hierarchyInitialized: false
    property bool tasksLoaded: false
    property bool creating: false
    property string busyRef: ""
    property string taskLoadError: ""
    property string actionError: ""
    property string createTaskRef: ""
    property string createSchedule: ""
    property string createRequest: ""
    property int scheduledCount: 0
    property int eventCount: 0
    property int runningCount: 0
    property int boardCount: 0
    property bool tasksRequestActive: false
    property bool graphRequestActive: false
    property bool modelsRequestActive: false

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
            let payload
            try {
                payload = request.responseText ? JSON.parse(request.responseText) : {}
            } catch (error) {
                callback(false, null, "The harness returned invalid JSON.")
                return
            }
            callback(true, payload, "")
        }
        request.send(body === undefined || body === null ? null : JSON.stringify(body))
    }

    function refreshTasks() {
        if (tasksRequestActive) {
            return
        }
        tasksRequestActive = true
        requestJson("GET", "/api/tasks", null, (ok, payload, error) => {
            if (!root) {
                return
            }
            root.tasksRequestActive = false
            root.tasksLoaded = true
            if (!ok || !Array.isArray(payload)) {
                root.taskLoadError = error || "Task activations unavailable."
                return
            }
            root.taskLoadError = ""
            root.tasks = payload
            root.taskCatalog = payload.slice().sort((left, right) =>
                String(left.title).localeCompare(String(right.title)))
            root.rebuildRows()
        })
    }

    function refreshReferenceData() {
        if (!graphRequestActive) {
            graphRequestActive = true
        requestJson("GET", "/api/graph", null, (ok, payload) => {
            if (!root) {
                return
            }
            root.graphRequestActive = false
            if (!ok || !payload || !Array.isArray(payload.nodes)) {
                return
            }
            root.graphNodes = payload.nodes
            const groups = payload.navigation && Array.isArray(payload.navigation.groups)
                ? payload.navigation.groups : []
            root.navigationAgents = groups.filter(
                group => group && group.role !== "library"
            )
            root.rebuildRows()
        })
        }
        if (!modelsRequestActive) {
            modelsRequestActive = true
        requestJson("GET", "/api/models", null, (ok, payload) => {
            if (!root) {
                return
            }
            root.modelsRequestActive = false
            if (ok && payload && Array.isArray(payload.models)) {
                root.models = payload.models.filter(
                    model => model && model.task_capable
                )
            }
        })
        }
    }

    function refresh() {
        refreshTasks()
        refreshReferenceData()
    }

    function appendUnique(map, key, value) {
        const list = map[key] || []
        if (!list.some(candidate => candidate.ref === value.ref)) {
            list.push(value)
        }
        map[key] = list
    }

    function rebuildRows() {
        const byRef = {}
        for (const node of graphNodes) {
            if (node && (node.kind === "task"
                    || (Array.isArray(node.tags) && node.tags.includes("task-taxonomy")))) {
                byRef[node.id] = {
                    "ref": node.id,
                    "title": node.title,
                    "children": Array.isArray(node.children) ? node.children : [],
                    "synthetic": Boolean(node.synthetic)
                }
            }
        }
        const operationalByRef = {}
        for (const task of tasks) {
            operationalByRef[task.ref] = task
            if (!byRef[task.ref]) {
                byRef[task.ref] = {
                    "ref": task.ref,
                    "title": task.title,
                    "children": Array.isArray(task.subtask_refs) ? task.subtask_refs : [],
                    "synthetic": false
                }
            }
        }

        const graphChildren = {}
        const graphParents = {}
        for (const ref of Object.keys(byRef)) {
            const node = byRef[ref]
            const children = []
            for (const childRef of node.children) {
                const child = byRef[childRef]
                if (!child) {
                    continue
                }
                children.push(child)
                appendUnique(graphParents, child.ref, node)
            }
            graphChildren[ref] = children
        }
        const executionChildren = {}
        for (const task of tasks) {
            executionChildren[task.ref] = (Array.isArray(task.subtask_refs)
                ? task.subtask_refs : []).map(ref => byRef[ref]).filter(Boolean)
        }

        const boardTasks = tasks.filter(task => Boolean(task.schedule)
            || ((Array.isArray(task.triggers) && task.triggers.length > 0)
                && task.enabled !== false)
            || task.status === "running")
        scheduledCount = tasks.filter(task => Boolean(task.schedule)).length
        eventCount = tasks.reduce((count, task) => count
            + (task.enabled === false || !Array.isArray(task.triggers)
                ? 0 : task.triggers.length), 0)
        runningCount = tasks.filter(task => task.status === "running"
            && Number(task.subtasks || 0) === 0).length
        boardCount = boardTasks.length

        const seedRefs = {}
        const scopedRefs = {}
        const ancestorRefs = {}
        const operationalRefs = {}

        function includeExecution(ref, seen) {
            if (seen[ref]) {
                return
            }
            seen[ref] = true
            operationalRefs[ref] = true
            for (const child of executionChildren[ref] || []) {
                scopedRefs[child.ref] = true
                includeExecution(child.ref, seen)
            }
        }
        function includeAncestors(ref, seen) {
            if (seen[ref]) {
                return
            }
            seen[ref] = true
            scopedRefs[ref] = true
            for (const parent of graphParents[ref] || []) {
                ancestorRefs[parent.ref] = true
                includeAncestors(parent.ref, seen)
            }
        }
        function includeGraphDescendants(ref, seen) {
            if (seen[ref]) {
                return
            }
            seen[ref] = true
            for (const child of graphChildren[ref] || []) {
                scopedRefs[child.ref] = true
                includeGraphDescendants(child.ref, seen)
            }
        }

        for (const task of boardTasks) {
            seedRefs[task.ref] = true
            scopedRefs[task.ref] = true
            includeExecution(task.ref, {})
        }
        for (const ref of Object.keys(operationalRefs)) {
            includeAncestors(ref, {})
        }
        for (const ref of Object.keys(operationalRefs)) {
            if ((executionChildren[ref] || []).length === 0) {
                includeGraphDescendants(ref, {})
            }
        }

        const scopedChildren = {}
        for (const ref of Object.keys(scopedRefs)) {
            scopedChildren[ref] = (graphChildren[ref] || [])
                .filter(child => Boolean(scopedRefs[child.ref]))
        }
        function graphContains(source, target, seen) {
            if (source === target) {
                return true
            }
            if (seen[source]) {
                return false
            }
            seen[source] = true
            return (graphChildren[source] || []).some(child =>
                graphContains(child.ref, target, seen))
        }
        for (const parent of Object.keys(executionChildren)) {
            for (const child of executionChildren[parent]) {
                if (!scopedRefs[parent] || !scopedRefs[child.ref]
                        || graphContains(parent, child.ref, {})) {
                    continue
                }
                appendUnique(scopedChildren, parent, child)
            }
        }
        const scopedParents = {}
        for (const parent of Object.keys(scopedChildren)) {
            for (const child of scopedChildren[parent]) {
                appendUnique(scopedParents, child.ref, byRef[parent])
            }
        }
        const roots = Object.keys(scopedRefs).map(ref => byRef[ref]).filter(node =>
            node && (scopedParents[node.ref] || []).length === 0)

        const assigneesByRef = {}
        function collectAssignees(ref, stack) {
            if (assigneesByRef[ref]) {
                return assigneesByRef[ref]
            }
            if (stack[ref]) {
                return []
            }
            const nextStack = Object.assign({}, stack)
            nextStack[ref] = true
            const direct = operationalByRef[ref] && operationalByRef[ref].assignee
            const collected = direct ? [direct] : []
            if (!direct) {
                for (const child of scopedChildren[ref] || []) {
                    for (const assignee of collectAssignees(child.ref, nextStack)) {
                        collected.push(assignee)
                    }
                }
            }
            const unique = []
            const seen = {}
            for (const assignee of collected) {
                const key = cleanLink(assignee)
                if (key && !seen[key]) {
                    unique.push(assignee)
                    seen[key] = true
                }
            }
            assigneesByRef[ref] = unique
            return unique
        }
        for (const ref of Object.keys(scopedRefs)) {
            collectAssignees(ref, {})
        }

        if (!hierarchyInitialized && roots.length > 0) {
            const defaults = {}
            for (const ref of Object.keys(ancestorRefs)
                    .concat(Object.keys(seedRefs), Object.keys(operationalRefs))) {
                if ((scopedChildren[ref] || []).length > 0) {
                    defaults[ref] = true
                }
            }
            expanded = defaults
            hierarchyInitialized = true
        }

        const visible = []
        const seenRows = {}
        function add(node, depth, parent, inheritedOwner, inheritedExclusion) {
            if (!node || seenRows[node.ref]) {
                return
            }
            seenRows[node.ref] = true
            const task = operationalByRef[node.ref] || null
            const ownsTrigger = Boolean(seedRefs[node.ref])
            const scopeOwner = ownsTrigger ? null : inheritedOwner
            const exclusions = scopeOwner && Array.isArray(scopeOwner.excluded_subtask_refs)
                ? scopeOwner.excluded_subtask_refs : []
            const exactExcluded = scopeOwner && exclusions.includes(node.ref)
                ? node.ref : ""
            const excludedBy = ownsTrigger ? "" : (inheritedExclusion || exactExcluded)
            const assignmentSource = task && task.assignee ? [task.assignee]
                : scopeOwner && scopeOwner.assignee ? [scopeOwner.assignee]
                : (assigneesByRef[node.ref] || [])
            visible.push({
                "node": node,
                "task": task,
                "depth": depth,
                "parent": parent,
                "scopeOwner": scopeOwner,
                "excludedBy": excludedBy,
                "children": scopedChildren[node.ref] || [],
                "assignees": assignmentSource
            })
            if (!expanded[node.ref]) {
                return
            }
            const childOwner = task && operationalRefs[node.ref]
                ? task : inheritedOwner
            for (const child of scopedChildren[node.ref] || []) {
                add(child, depth + 1, node, childOwner, excludedBy)
            }
        }
        for (const node of roots) {
            add(node, 0, null, null, "")
        }
        rows = visible
    }

    function toggleExpanded(ref) {
        const next = Object.assign({}, expanded)
        next[ref] = !next[ref]
        expanded = next
        rebuildRows()
    }

    function updateTaskField(ref, field, value) {
        tasks = tasks.map(task => {
            if (task.ref !== ref) {
                return task
            }
            const next = Object.assign({}, task)
            next[field] = value
            return next
        })
        rebuildRows()
    }

    function setReasoning(task, effort) {
        if (!task || task.status === "running") {
            return
        }
        updateTaskField(task.ref, "reasoning_effort", effort)
        requestJson("PATCH", "/api/tasks/" + encodeURI(task.ref) + "/reasoning", {
            "reasoning_effort": effort
        }, function(ok, payload, error) {
            if (!ok) {
                actionError = error
                refresh()
            }
        })
    }

    function setModel(task, modelId) {
        if (!task || task.status === "running") {
            return
        }
        updateTaskField(task.ref, "model", modelId)
        requestJson("PATCH", "/api/tasks/" + encodeURI(task.ref) + "/model", {
            "model": modelId
        }, function(ok, payload, error) {
            if (!ok) {
                actionError = error
                refresh()
                return
            }
            updateTaskField(task.ref, "resolved_model", String(payload.resolved_model || ""))
        })
    }

    function toggleExclusion(owner, taskRef, currentlyExcluded) {
        if (!owner || owner.status === "running") {
            return
        }
        const exclusions = Array.isArray(owner.excluded_subtask_refs)
            ? owner.excluded_subtask_refs.slice() : []
        const index = exclusions.indexOf(taskRef)
        if (currentlyExcluded && index >= 0) {
            exclusions.splice(index, 1)
        } else if (!currentlyExcluded && index < 0) {
            exclusions.push(taskRef)
        }
        updateTaskField(owner.ref, "excluded_subtask_refs", exclusions)
        requestJson("PATCH", "/api/tasks/" + encodeURI(owner.ref) + "/exclusions", {
            "excluded_subtask_refs": exclusions
        }, function(ok, payload, error) {
            if (!ok) {
                actionError = error
                refresh()
            } else {
                updateTaskField(owner.ref, "excluded_subtask_refs",
                    Array.isArray(payload.excluded_subtask_refs)
                        ? payload.excluded_subtask_refs : exclusions)
            }
        })
    }

    function runNow(task) {
        if (!task || busyRef || task.status === "running") {
            return
        }
        actionError = ""
        busyRef = task.ref
        requestJson("POST", "/api/tasks/" + encodeURI(task.ref) + "/run", {
            "reasoning_effort": task.reasoning_effort
        }, function(ok, payload, error) {
            busyRef = ""
            if (!ok) {
                actionError = error
            }
            refresh()
        })
    }

    function activateTask() {
        if (!createTaskRef) {
            return
        }
        actionError = ""
        const body = {"task": createTaskRef}
        if (createSchedule.trim()) {
            body.schedule = createSchedule.trim()
        }
        if (createRequest.trim()) {
            body.params = {"request": createRequest.trim()}
        }
        requestJson("POST", "/api/tasks", body, function(ok, payload, error) {
            if (!ok) {
                actionError = error.slice(0, 220)
                return
            }
            creating = false
            createTaskRef = ""
            createSchedule = ""
            createRequest = ""
            refresh()
        })
    }

    function modelOptions(task) {
        const options = [{
            "id": "auto",
            "label": "Auto · " + shortModel(task ? task.resolved_model : "")
        }]
        for (const model of models) {
            if (model.available) {
                options.push({
                    "id": model.id,
                    "label": model.label + " · " + model.quantization
                })
            }
        }
        return options
    }

    function optionIndex(options, id) {
        const index = options.findIndex(option => option.id === id)
        return index >= 0 ? index : 0
    }

    function shortModel(value) {
        const lower = String(value || "").toLowerCase()
        if (lower.includes("qwen")) {
            return "Qwen"
        }
        if (lower.includes("muse")) {
            return "Muse"
        }
        return "Gemma"
    }

    function taskDetail(row) {
        const task = row.task
        const details = []
        if (row.excludedBy) {
            details.push("EXCLUDED · " + String(row.excludedBy).split("/").pop())
        } else {
            if (task && task.schedule) {
                details.push("TRIGGER · SCHEDULE · " + task.schedule)
            }
            if (task && Array.isArray(task.triggers) && task.triggers.length) {
                details.push("TRIGGER · EVENT · " + task.triggers.join(" · "))
            }
            if (task && Number(task.queue_depth || 0) > 0) {
                details.push(String(task.queue_depth) + " QUEUED")
            }
            if (task && ["running", "review", "failed", "blocked"].includes(task.status)) {
                details.push(String(task.status).toUpperCase())
            }
            if (task && task.blocked_reason) {
                details.push(task.blocked_reason)
            }
            if (!task?.schedule && !(task && Array.isArray(task.triggers)
                    && task.triggers.length) && row.scopeOwner) {
                details.push("INHERITS · " + row.scopeOwner.title)
            } else if (details.length === 0 && row.parent) {
                details.push("INCLUDED · PARENT · " + row.parent.title)
            } else if (details.length === 0 && row.children.length > 0) {
                details.push(row.children.length + " INCLUDED SUBTASKS")
            }
        }
        return details.join("   ·   ")
    }

    function roleColor(role, dimmed) {
        const colors = {
            "executive": dimmed ? "#3467e8f9" : "#67e8f9",
            "guardian": dimmed ? "#3060a5fa" : "#60a5fa",
            "curator": dimmed ? "#30fbbf24" : "#fbbf24",
            "researcher": dimmed ? "#30c084fc" : "#c084fc"
        }
        return colors[role] || (dimmed ? "#307dd3fc" : "#7dd3fc")
    }

    function roleAssigned(assignees, group) {
        if (!group || !Array.isArray(assignees)) {
            return false
        }
        const rootRef = String(group.root_ref || "").toLowerCase()
        const title = String(group.title || "").toLowerCase()
        const role = String(group.role || group.id || "").toLowerCase()
        return assignees.some(value => {
            const ref = cleanLink(value).toLowerCase()
            const leaf = ref.split("/").pop() || ""
            return ref === rootRef || leaf === title || leaf === role
                || ref.includes("/" + title + "/")
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
        interval: 3000
        repeat: true
        running: true
        onTriggered: root.refreshTasks()
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
            anchors.leftMargin: 12
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - 104
            text: root.scheduledCount + " SCHEDULES   ·   "
                + root.eventCount + " EVENTS"
                + (root.runningCount > 0 ? "   ·   ● " + root.runningCount + " RUNNING" : "")
                + "   ·   TASK CATALOG LIVES IN LIBRARY"
            color: root.runningCount > 0 ? "#8f5eead4" : "#667dd3fc"
            elide: Text.ElideRight
            font.family: "JetBrains Mono"
            font.pixelSize: 9
            font.letterSpacing: 1.0
        }

        GlowButton {
            id: createButton

            anchors.right: refreshButton.left
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            width: 28
            height: 28
            text: root.creating ? "×" : "+"
            foreground: "#67e8f9"
            idleBorderOpacity: 0.15
            idleTextOpacity: 0.60
            textPixelSize: 14
            textLetterSpacing: 0
            onClicked: root.creating = !root.creating
        }

        GlowButton {
            id: refreshButton

            anchors.right: parent.right
            anchors.rightMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            width: 28
            height: 28
            text: "↻"
            foreground: "#67e8f9"
            idleBorderOpacity: 0.15
            idleTextOpacity: 0.50
            textPixelSize: 13
            textLetterSpacing: 0
            onClicked: root.refresh()
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
        id: creator

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: header.bottom
        height: root.creating ? 126 : 0
        visible: root.creating
        color: "#9903101a"
        border.width: 1
        border.color: "#2467e8f9"

        GlowComboBox {
            id: taskSelector

            anchors.left: parent.left
            anchors.right: scheduleField.left
            anchors.top: parent.top
            anchors.margins: 10
            anchors.rightMargin: 8
            height: 30
            model: root.taskCatalog
            textRole: "title"
            valueRole: "ref"
            displayText: root.createTaskRef
                ? (root.taskCatalog.find(task => task.ref === root.createTaskRef)?.title || "TASK…")
                : "TASK…"
            fieldColor: "#020a12"
            foreground: "#cffafe"
            textOpacity: 1.0
            textPixelSize: 10
            onActivated: index => root.createTaskRef = model[index].ref
        }

        TextField {
            id: scheduleField

            anchors.right: parent.right
            anchors.rightMargin: 10
            anchors.top: parent.top
            anchors.topMargin: 10
            width: Math.min(230, parent.width * 0.32)
            height: 30
            text: root.createSchedule
            placeholderText: "schedule trigger · cron"
            color: "#d9f8ff"
            placeholderTextColor: "#4d7dd3fc"
            font.family: "JetBrains Mono"
            font.pixelSize: 10
            onTextChanged: root.createSchedule = text
            background: Rectangle {
                radius: 5
                color: "#e6020a12"
                border.width: 1
                border.color: scheduleField.activeFocus ? "#7367e8f9" : "#3367e8f9"
            }
        }

        TextArea {
            id: requestField

            anchors.left: parent.left
            anchors.right: activateButton.left
            anchors.top: taskSelector.bottom
            anchors.bottom: parent.bottom
            anchors.leftMargin: 10
            anchors.rightMargin: 8
            anchors.topMargin: 8
            anchors.bottomMargin: 10
            text: root.createRequest
            placeholderText: "optional target or request"
            color: "#d9f8ff"
            placeholderTextColor: "#4d7dd3fc"
            wrapMode: TextEdit.Wrap
            font.family: "JetBrains Mono"
            font.pixelSize: 10
            onTextChanged: root.createRequest = text
            background: Rectangle {
                radius: 5
                color: "#e6020a12"
                border.width: 1
                border.color: requestField.activeFocus ? "#7367e8f9" : "#3367e8f9"
            }
        }

        GlowButton {
            id: activateButton

            anchors.right: parent.right
            anchors.rightMargin: 10
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 10
            width: 130
            height: 68
            enabled: root.createTaskRef !== ""
            text: root.createSchedule.trim() ? "SCHEDULE TASK" : "RUN TASK"
            foreground: "#cffafe"
            idleBorderOpacity: 0.40
            idleTextOpacity: 1.0
            disabledOpacity: 0.40
            textPixelSize: 10
            textLetterSpacing: 1.8
            onClicked: root.activateTask()
        }
    }

    Rectangle {
        id: errorStrip

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: creator.bottom
        height: (root.actionError || root.taskLoadError) ? 30 : 0
        visible: height > 0
        color: "#39190a12"
        border.width: 1
        border.color: "#36fb7185"

        Text {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 12
            text: root.actionError || root.taskLoadError
            color: "#fda4af"
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
            font.family: "JetBrains Mono"
            font.pixelSize: 9
        }
    }

    Rectangle {
        id: columns

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: errorStrip.bottom
        height: root.boardCount > 0 ? 26 : 0
        visible: height > 0
        color: "#e603101a"
        border.width: 1
        border.color: "#2467e8f9"

        Repeater {
            model: [
                {"label": "TASK", "x": 0.01, "width": 0.41},
                {"label": "AGENT", "x": 0.42, "width": 0.16},
                {"label": "MODEL", "x": 0.58, "width": 0.19},
                {"label": "REASON", "x": 0.77, "width": 0.12},
                {"label": "ACTION", "x": 0.89, "width": 0.11}
            ]
            delegate: Text {
                required property var modelData
                x: columns.width * modelData.x
                width: columns.width * modelData.width
                anchors.verticalCenter: parent.verticalCenter
                text: modelData.label
                color: "#4d67e8f9"
                horizontalAlignment: modelData.label === "TASK" ? Text.AlignLeft : Text.AlignHCenter
                font.family: "JetBrains Mono"
                font.pixelSize: 8
                font.letterSpacing: 1.2
            }
        }
    }

    ListView {
        id: taskList

        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: columns.bottom
        anchors.bottom: parent.bottom
        clip: true
        model: root.rows
        boundsBehavior: Flickable.StopAtBounds

        ScrollBar.vertical: ScrollBar {
            policy: ScrollBar.AsNeeded
        }

        delegate: Rectangle {
            id: taskRow

            required property var modelData
            width: taskList.width
            height: 56
            color: modelData.excludedBy ? "#08071119"
                : ((modelData.task && modelData.task.status === "running")
                    || (modelData.scopeOwner && modelData.scopeOwner.status === "running"))
                    ? "#145eead4" : rowMouse.containsMouse ? "#0d67e8f9" : "transparent"
            opacity: modelData.excludedBy ? 0.52 : 1.0
            border.width: 1
            border.color: "#1267e8f9"

            MouseArea {
                id: rowMouse
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.NoButton
            }

            Item {
                id: taskCell

                x: 0
                width: taskRow.width * 0.42
                height: parent.height

                Rectangle {
                    id: expandButton

                    x: 6 + Math.min(82, taskRow.modelData.depth * 14)
                    y: 10
                    width: 20
                    height: 20
                    radius: 3
                    color: expandMouse.containsMouse && taskRow.modelData.children.length > 0
                        ? "#2034d399" : "transparent"

                    Text {
                        anchors.centerIn: parent
                        text: taskRow.modelData.children.length === 0 ? "·"
                            : (root.expanded[taskRow.modelData.node.ref] ? "⌄" : "›")
                        color: taskRow.modelData.children.length > 0 ? "#9967e8f9" : "#2467e8f9"
                        font.family: "JetBrains Mono"
                        font.pixelSize: 13
                    }

                    MouseArea {
                        id: expandMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        enabled: taskRow.modelData.children.length > 0
                        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: root.toggleExpanded(taskRow.modelData.node.ref)
                    }
                }

                Text {
                    id: taskTitle

                    anchors.left: expandButton.right
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.leftMargin: 2
                    anchors.rightMargin: 6
                    anchors.topMargin: 8
                    text: String(taskRow.modelData.task
                        ? taskRow.modelData.task.title : taskRow.modelData.node.title)
                    color: taskRow.modelData.children.length > 0 ? "#e6faff" : "#b6eaf2"
                    elide: Text.ElideRight
                    font.family: "JetBrains Mono"
                    font.pixelSize: 10
                    font.weight: taskRow.modelData.children.length > 0 ? Font.DemiBold : Font.Normal
                    font.capitalization: taskRow.modelData.children.length > 0
                        ? Font.AllUppercase : Font.MixedCase

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.presentArticle(taskRow.modelData.node.ref)
                    }
                }

                Text {
                    anchors.left: taskTitle.left
                    anchors.right: parent.right
                    anchors.top: taskTitle.bottom
                    anchors.rightMargin: 6
                    anchors.topMargin: 4
                    text: root.taskDetail(taskRow.modelData)
                    color: taskRow.modelData.excludedBy ? "#bffbbf24"
                        : (taskRow.modelData.task && taskRow.modelData.task.blocked_reason)
                            ? "#bffb7185" : "#527dd3fc"
                    elide: Text.ElideRight
                    font.family: "JetBrains Mono"
                    font.pixelSize: 8
                }
            }

            Item {
                id: agentCell

                x: taskRow.width * 0.42
                width: taskRow.width * 0.16
                height: parent.height

                Row {
                    anchors.centerIn: parent
                    spacing: 3

                    Repeater {
                        model: root.navigationAgents

                        delegate: Rectangle {
                            id: roleBadge

                            required property var modelData
                            readonly property bool selected: root.roleAssigned(
                                taskRow.modelData.assignees,
                                modelData
                            )
                            width: 24
                            height: 24
                            radius: 5
                            color: selected ? Qt.alpha(root.roleColor(modelData.role, false), 0.14)
                                : "#8a020a0c"
                            border.width: 1
                            border.color: root.roleColor(modelData.role, !selected)
                            opacity: selected ? 1.0 : 0.56

                            RoleIcon {
                                anchors.fill: parent
                                anchors.margins: 2
                                role: String(roleBadge.modelData.role || "executive")
                            }
                        }
                    }
                }
            }

            Item {
                x: taskRow.width * 0.58
                width: taskRow.width * 0.19
                height: parent.height

                GlowComboBox {
                    id: modelBox

                    readonly property var options: root.modelOptions(taskRow.modelData.task)
                    anchors.centerIn: parent
                    width: parent.width - 8
                    height: 28
                    visible: Boolean(taskRow.modelData.task)
                    enabled: taskRow.modelData.task && taskRow.modelData.task.runbook
                        && taskRow.modelData.task.status !== "running"
                    model: options
                    textRole: "label"
                    valueRole: "id"
                    currentIndex: root.optionIndex(options,
                        taskRow.modelData.task ? taskRow.modelData.task.model : "auto")
                    textPixelSize: 8
                    onActivated: index => root.setModel(taskRow.modelData.task, options[index].id)
                }
            }

            Item {
                x: taskRow.width * 0.77
                width: taskRow.width * 0.12
                height: parent.height

                GlowComboBox {
                    id: reasoningBox

                    anchors.centerIn: parent
                    width: parent.width - 8
                    height: 28
                    visible: Boolean(taskRow.modelData.task)
                    enabled: taskRow.modelData.task && taskRow.modelData.task.runbook
                        && taskRow.modelData.task.status !== "running"
                    model: ["none", "low", "medium", "high", "xhigh"]
                    currentIndex: taskRow.modelData.task
                        ? Math.max(0, model.indexOf(taskRow.modelData.task.reasoning_effort)) : 0
                    displayText: currentText.toUpperCase()
                    textPixelSize: 8
                    onActivated: index => root.setReasoning(taskRow.modelData.task, model[index])
                }
            }

            Item {
                x: taskRow.width * 0.89
                width: taskRow.width * 0.11
                height: parent.height

                Row {
                    anchors.centerIn: parent
                    spacing: 5

                    GlowButton {
                        id: exclusionButton

                        readonly property bool exactExcluded: taskRow.modelData.excludedBy
                            === taskRow.modelData.node.ref
                        readonly property bool inheritedExcluded: Boolean(taskRow.modelData.excludedBy)
                            && !exactExcluded
                        visible: Boolean(taskRow.modelData.scopeOwner) && !inheritedExcluded
                        width: visible ? 24 : 0
                        height: 24
                        text: exactExcluded ? "+" : "−"
                        accent: exactExcluded ? "#5eead4" : "#fbbf24"
                        foreground: accent
                        idleBorderOpacity: exactExcluded ? 0.35 : 0.25
                        idleTextOpacity: 1.0
                        textPixelSize: 13
                        textLetterSpacing: 0
                        contentHorizontalPadding: 0
                        enabled: taskRow.modelData.scopeOwner
                            && taskRow.modelData.scopeOwner.status !== "running"
                        onClicked: root.toggleExclusion(
                            taskRow.modelData.scopeOwner,
                            taskRow.modelData.node.ref,
                            exactExcluded
                        )
                    }

                    GlowButton {
                        id: runButton

                        visible: Boolean(taskRow.modelData.task
                            && taskRow.modelData.task.runbook
                            && !taskRow.modelData.excludedBy)
                        width: visible ? 24 : 0
                        height: 24
                        text: "▶"
                        idleBorderOpacity: 0.25
                        idleTextOpacity: 0.70
                        textPixelSize: 9
                        textLetterSpacing: 0
                        contentHorizontalPadding: 0
                        enabled: taskRow.modelData.task
                            && root.busyRef !== taskRow.modelData.task.ref
                            && taskRow.modelData.task.status !== "running"
                        onClicked: root.runNow(taskRow.modelData.task)
                    }
                }
            }
        }

        Text {
            anchors.centerIn: parent
            visible: root.tasksLoaded && !root.taskLoadError && root.boardCount === 0
            text: "NO SCHEDULED, EVENT-TRIGGERED, OR RUNNING TASKS"
            color: "#527dd3fc"
            horizontalAlignment: Text.AlignHCenter
            font.family: "JetBrains Mono"
            font.pixelSize: 10
            font.letterSpacing: 1.0
        }

        Text {
            anchors.centerIn: parent
            visible: !root.tasksLoaded
            text: "LOADING TASK ACTIVATIONS…"
            color: "#527dd3fc"
            font.family: "JetBrains Mono"
            font.pixelSize: 10
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
