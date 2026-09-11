pragma ComponentBehavior: Bound
import QtQuick
import QtWebSockets

QtObject {
    id: root
    property var nodes: []
    property var rows: ({})
    property var revisions: ({})
    property bool pending: false
    property bool active: true
    onActiveChanged: { generation += 1; if (active) refresh() }
    property string error: ""
    property int generation: 0
    signal changed()
    property WebSocket updates: WebSocket {
        url: "ws://127.0.0.1:8765/ws/activity"
        active: root.active
        onTextMessageReceived: message => {
            let event
            try { event = JSON.parse(message) } catch (problem) { return }
            if (event.type === "activity" && event.phase === "graph_changed") {
                root.refresh()
                root.changed()
            }
        }
        onStatusChanged: status => {
            if (status === WebSocket.Open) { root.refresh(); root.changed() }
            if (root.active && (status === WebSocket.Closed || status === WebSocket.Error)) root.reconnect.restart()
        }
    }
    property Timer reconnect: Timer {
        interval: 1000
        repeat: false
        onTriggered: { root.updates.active = false; root.updates.active = Qt.binding(() => root.active) }
    }

    function key(ref, agent) { return ref + "\u0000" + agent }
    function canonical(node) {
        const ref = String(node.ref || node.id || "").replace(/\.md$/, "")
        const item = nodes.find(item => item.id === ref)
        return item && item.article_ref ? item.article_ref : ref
    }
    function state(node, agent) {
        const ref = canonical(node)
        const actual = nodes.find(item => item.id === ref)
        return rows[key(ref, agent)] || {checked: false, editable: Boolean(revisions[agent])
            && Boolean(actual) && actual.kind === "task" && !actual.synthetic}
    }
    function hint(node, agent) {
        const item = state(node, agent.role)
        if (item.private) return "Private Observations of another Agent"
        if (item.owned) return agent.title + " owns this Article"
        if (item.derived) return "Selected by assigned Tasks; change the Task assignment"
        if (item.partial) return "Partially checked out; toggle this complete branch for " + agent.title
        if (item.inherited && !item.editable) return "Inherited Task assignment"
        if (item.inherited && item.checked) return "Inherited Knowledge; click to exclude this scope"
        return (item.checked ? "Remove from " : "Check out to ") + agent.title
    }
    function applyManifest(manifest) {
        const selected = {}
        for (const item of manifest.dependencies || [])
            selected[key(item.ref, item.agent)] = {checked: true, derived: true, editable: false}
        for (const item of manifest.assignments || [])
            selected[key(item.ref, item.agent)] = Object.assign({}, item, {
                checked: item.direct || item.inherited, editable: item.direct || !item.inherited})
        for (const item of manifest.knowledge || [])
            if (item.ref) selected[key(item.ref, item.agent)] = item
        rows = selected
        revisions = manifest.revisions || {}
    }
    function refresh() {
        if (!active) return
        const current = ++generation
        const request = new XMLHttpRequest()
        request.open("GET", "http://127.0.0.1:8765/api/library/assignments")
        request.onreadystatechange = function() {
            if (!root || current !== root.generation || request.readyState !== XMLHttpRequest.DONE) return
            if (request.status < 200 || request.status >= 300) { root.error = "Checkout state is unavailable."; return }
            try { root.applyManifest(JSON.parse(request.responseText)) }
            catch (problem) { root.error = "Checkout response was invalid." }
        }
        request.send()
    }
    function toggle(node, agent) {
        const item = state(node, agent.role)
        const revision = revisions[agent.role]
        if (pending || !item.editable || !revision) return
        pending = true
        error = ""
        const request = new XMLHttpRequest()
        request.open("PUT", "http://127.0.0.1:8765/api/library/assignments/" + encodeURIComponent(canonical(node)))
        request.setRequestHeader("Content-Type", "application/json")
        request.onreadystatechange = function() {
            if (!root || request.readyState !== XMLHttpRequest.DONE) return
            root.pending = false
            if (request.status >= 200 && request.status < 300) root.changed()
            else root.error = request.status === 409 ? "Checkout changed. Refresh and retry." : "Checkout was not changed."
            root.refresh()
        }
        request.send(JSON.stringify({agent: agent.role, assigned: !item.checked, expected_revision: revision}))
    }
}
