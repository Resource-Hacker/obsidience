pragma ComponentBehavior: Bound

import QtCore
import QtQml
import Quickshell
import Quickshell.Io

QtObject {
    id: root

    readonly property string schema: "obsidience.pane-dock-layout.v1"
    readonly property string stateNamespace: Quickshell.env(
        "OBSIDIENCE_SHELL_STATE_NAMESPACE"
    )
    readonly property string statePath: stateNamespace
        ? StandardPaths.writableLocation(StandardPaths.ConfigLocation)
            + "/" + stateNamespace + "/pane-dock-layout.json"
        : StandardPaths.writableLocation(StandardPaths.ConfigLocation)
            + "/obsidience-shell/pane-dock-layout.json"

    property bool authoritative: false
    property int revision: 0
    property var modules: defaultModules()

    function defaultModules() {
        return {
            "knowledge": {
                "pane_id": "knowledge",
                "host_pane_id": "reader",
                "side": "left",
                "order": 0,
                "collapsed": false
            },
            "source": {
                "pane_id": "source",
                "host_pane_id": "reader",
                "side": "right",
                "order": 0,
                "collapsed": false
            }
        }
    }

    function isNumber(value) {
        return typeof value === "number" && Number.isFinite(value)
    }

    function cleanPaneId(value) {
        return typeof value === "string"
            && /^[a-z][a-z0-9-]{0,47}$/.test(value) ? value : ""
    }

    function normalizeModule(value) {
        if (!value || typeof value !== "object" || Array.isArray(value)) {
            return null
        }
        const paneId = cleanPaneId(value.pane_id)
        const hostPaneId = cleanPaneId(value.host_pane_id)
        if (!paneId || !hostPaneId || paneId === hostPaneId
                || (value.side !== "left" && value.side !== "right")
                || !isNumber(value.order)) {
            return null
        }
        return {
            "pane_id": paneId,
            "host_pane_id": hostPaneId,
            "side": value.side,
            "order": Math.round(value.order),
            "collapsed": value.collapsed === true
        }
    }

    function applyRecord(record) {
        if (!record || record.schema !== schema
                || !isNumber(record.revision) || record.revision < revision
                || !Array.isArray(record.modules) || record.modules.length > 16) {
            return false
        }
        const next = {}
        for (const value of record.modules) {
            const module = normalizeModule(value)
            if (!module || next[module.pane_id]) {
                return false
            }
            next[module.pane_id] = module
        }
        modules = next
        revision = Math.round(record.revision)
        return true
    }

    function reloadState() {
        const content = layoutFile.text()
        if (!content) {
            return
        }
        try {
            if (!applyRecord(JSON.parse(content))) {
                console.warn("Ignored invalid pane dock layout")
            }
        } catch (error) {
            console.warn("Ignored invalid pane dock layout:", error)
        }
    }

    function moduleState(paneId) {
        const state = modules[paneId]
        return state ? state : {
            "pane_id": paneId,
            "host_pane_id": "",
            "side": "floating",
            "order": 0,
            "collapsed": false
        }
    }

    function isDocked(paneId) {
        return modules[paneId] !== undefined
    }

    function modulesFor(hostPaneId, side, collapsed) {
        const result = []
        for (const paneId of Object.keys(modules)) {
            const state = modules[paneId]
            if (state.host_pane_id === hostPaneId && state.side === side
                    && (collapsed === undefined
                        || state.collapsed === collapsed)) {
                result.push(state)
            }
        }
        result.sort(function(left, right) {
            if (left.order !== right.order) {
                return left.order - right.order
            }
            return left.pane_id.localeCompare(right.pane_id)
        })
        return result
    }

    function record() {
        const values = []
        for (const paneId of Object.keys(modules).sort()) {
            values.push(modules[paneId])
        }
        return {
            "schema": schema,
            "revision": revision,
            "modules": values
        }
    }

    function writeState() {
        if (authoritative) {
            layoutFile.setText(JSON.stringify(record(), null, 2) + "\n")
        }
    }

    function commitDock(expectedRevision, paneId, hostPaneId, side, position) {
        if (!authoritative || revision !== expectedRevision
                || !cleanPaneId(paneId) || !cleanPaneId(hostPaneId)
                || paneId === hostPaneId
                || (side !== "left" && side !== "right")
                || (position !== "top" && position !== "bottom")) {
            return false
        }
        const peers = modulesFor(hostPaneId, side)
            .filter(value => value.pane_id !== paneId)
        let order = 0
        if (peers.length > 0) {
            order = position === "top"
                ? peers[0].order - 1
                : peers[peers.length - 1].order + 1
        }
        const next = Object.assign({}, modules)
        next[paneId] = {
            "pane_id": paneId,
            "host_pane_id": hostPaneId,
            "side": side,
            "order": order,
            "collapsed": false
        }
        modules = next
        revision += 1
        writeState()
        return true
    }

    function commitFloat(expectedRevision, paneId) {
        if (!authoritative || revision !== expectedRevision
                || !cleanPaneId(paneId) || !modules[paneId]) {
            return false
        }
        const next = Object.assign({}, modules)
        delete next[paneId]
        modules = next
        revision += 1
        writeState()
        return true
    }

    function commitCollapsed(expectedRevision, paneId, collapsed) {
        if (!authoritative || revision !== expectedRevision
                || !cleanPaneId(paneId) || !modules[paneId]) {
            return false
        }
        const next = Object.assign({}, modules)
        next[paneId] = Object.assign({}, modules[paneId], {
            "collapsed": collapsed === true
        })
        modules = next
        revision += 1
        writeState()
        return true
    }

    Component.onCompleted: {
        if (authoritative && !layoutFile.text()) {
            writeState()
        }
    }

    property FileView layoutFile: FileView {
        id: layoutFile

        path: root.statePath
        preload: true
        blockLoading: true
        watchChanges: true
        atomicWrites: true

        onLoaded: root.reloadState()
        onTextChanged: root.reloadState()
        onFileChanged: layoutFile.reload()
    }
}
