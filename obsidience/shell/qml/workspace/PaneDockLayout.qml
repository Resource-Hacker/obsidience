pragma ComponentBehavior: Bound

import QtCore
import QtQml
import Quickshell.Io

QtObject {
    id: root

    readonly property string schema: "obsidience.pane-dock-layout.v1"
    readonly property string statePath: StandardPaths.writableLocation(
        StandardPaths.ConfigLocation
    ) + "/obsidience-shell/pane-dock-layout.json"

    property bool authoritative: false
    property int revision: 0
    property var modules: defaultModules()

    function canDock(paneId, hostPaneId) {
        return hostPaneId === "reader"
            && ["knowledge", "source", "feeds"].indexOf(paneId) >= 0
    }

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
        if (!canDock(paneId, hostPaneId)
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
                || !Array.isArray(record.modules) || record.modules.length > 3) {
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
        // Older layouts used unbounded ordering. Preserve their relative
        // positions once, then retain two exact slots on each Reader side.
        const occupied = {}
        const legacySides = {}
        const originalSlots = {}
        for (const module of Object.values(next)) {
            const key = module.side + module.order
            if ((module.order !== 0 && module.order !== 1) || originalSlots[key]) {
                legacySides[module.side] = true
            }
            originalSlots[key] = true
        }
        const sideCounts = {"left": 0, "right": 0}
        const values = Object.values(next).sort(function(left, right) {
            return left.side.localeCompare(right.side) || left.order - right.order
                || left.pane_id.localeCompare(right.pane_id)
        })
        for (const module of values) {
            const preferred = legacySides[module.side]
                ? Math.min(1, sideCounts[module.side]++) : module.order
            const choices = [[module.side, preferred], [module.side, 1 - preferred],
                [module.side === "left" ? "right" : "left", 0],
                [module.side === "left" ? "right" : "left", 1]]
            const slot = choices.find(value => !occupied[value[0] + value[1]])
            module.side = slot[0]
            module.order = slot[1]
            occupied[module.side + module.order] = true
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

    function slotState(hostPaneId, side, order) {
        return modulesFor(hostPaneId, side).find(value => value.order === order) || null
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
                || !canDock(paneId, hostPaneId)
                || (side !== "left" && side !== "right")
                || (position !== "top" && position !== "bottom")) {
            return false
        }
        const order = position === "top" ? 0 : 1
        const prior = modules[paneId]
        const occupant = slotState(hostPaneId, side, order)
        const next = Object.assign({}, modules)
        if (occupant && occupant.pane_id !== paneId) {
            let replacement
            if (prior) {
                // Moving one docked module onto another swaps their slots;
                // collapsed state belongs to the module and remains intact.
                replacement = [prior.side, prior.order]
            } else {
                const otherSide = side === "left" ? "right" : "left"
                replacement = [[side, 1 - order], [otherSide, 0], [otherSide, 1]]
                    .find(value => !slotState(hostPaneId, value[0], value[1]))
            }
            if (!replacement) return false
            next[occupant.pane_id] = Object.assign({}, occupant, {
                "side": replacement[0], "order": replacement[1]
            })
        }
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
