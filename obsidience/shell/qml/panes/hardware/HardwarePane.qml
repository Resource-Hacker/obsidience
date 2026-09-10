pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Window
import QtQuick.Controls
import QtQuick.Layouts
import QtWebSockets
import "../../components/visual"

Rectangle {
    id: root
    required property var shellTheme
    property string apiBase: "http://127.0.0.1:8765"
    property string activeSection: "overview"
    property string activeDevice: ""
    property var snapshot: null
    property var history: []
    property bool monitoringAllowed: true
    readonly property bool monitorActive: visible && monitoringAllowed && !!Window.window && Window.window.visible && !disposing
    property bool loading: false
    property bool disposing: false
    property bool historyGap: false
    property string errorMessage: ""
    property string settingsError: ""
    property int requestGeneration: 0
    property var activeRequest: null
    readonly property bool compact: width < 900
    readonly property color accentColor: Qt.rgba(shellTheme.strongAccent.r, shellTheme.strongAccent.g, shellTheme.strongAccent.b, 1)
    readonly property var cpu: snapshot ? snapshot.cpu || {} : ({})
    readonly property var memory: snapshot ? snapshot.memory || {} : ({})
    readonly property var gpus: snapshot ? snapshot.gpus || [] : []
    readonly property var storage: snapshot ? snapshot.storage || {} : ({})
    readonly property var networks: snapshot ? snapshot.network || [] : []
    readonly property var physicalNetworks: networks.filter(row => row.is_physical === true)
    readonly property var processes: snapshot ? snapshot.processes || [] : []
    readonly property var sections: [
        {"id":"overview", "label":"Summary", "icon":"hardware"},
        {"id":"cpu", "label":"CPU", "icon":"hardware"},
        {"id":"memory", "label":"Memory", "icon":"models"},
        {"id":"gpus", "label":"GPUs", "icon":"displays"},
        {"id":"storage", "label":"Storage", "icon":"source"},
        {"id":"network", "label":"Network", "icon":"connections"},
        {"id":"processes", "label":"Processes", "icon":"tasks"}
    ]
    readonly property var selectedGpu: gpus.find(row => row.device === activeDevice) || gpus[0] || ({})
    readonly property var selectedDisk: Array.from(storage.devices || []).find(row => row.id === activeDevice) || null
    readonly property var selectedNetwork: networks.find(row => row.id === activeDevice) || networks[0] || ({})
    readonly property string sectionTitle: activeSection === "gpus" && selectedGpu.name ? selectedGpu.name : activeSection === "storage" && selectedDisk ? selectedDisk.name : activeSection === "network" && selectedNetwork.id ? selectedNetwork.id : (sections.find(row => row.id === activeSection) || sections[0]).label
    color: shellTheme.surface
    clip: true

    function finite(value) { return typeof value === "number" && Number.isFinite(value) }
    function number(value, suffix) { return finite(value) ? Number.isInteger(value) ? String(value) + suffix : value.toFixed(1) + suffix : "Unavailable" }
    function percent(value) { return finite(value) ? value.toFixed(1) + "%" : "Unavailable" }
    function bytes(value) {
        if (!finite(value)) return "Unavailable"
        const units = ["B", "KiB", "MiB", "GiB", "TiB"]
        let index = 0
        while (value >= 1024 && index < units.length - 1) { value /= 1024; index++ }
        return value.toFixed(index === 0 ? 0 : 1) + " " + units[index]
    }
    function rate(value) { return finite(value) ? bytes(value) + "/s" : "Awaiting rate" }
    function mib(value) { return finite(value) ? bytes(value * 1048576) : "Unavailable" }
    function sum(rows, key) {
        const values = Array.from(rows || []).map(row => row[key])
        return values.length && values.every(value => finite(value)) ? values.reduce((total, value) => total + value, 0) : null
    }
    function gpuDetail(gpu) {
        if (gpu.status !== "online") return "No current sensor reading"
        const parts = []
        if (finite(gpu.memory_used_mib) && finite(gpu.memory_total_mib)) parts.push(mib(gpu.memory_used_mib) + " of " + mib(gpu.memory_total_mib))
        if (finite(gpu.temperature_c)) parts.push(number(gpu.temperature_c, " °C"))
        return parts.join(" · ")
    }
    function gpuReadings(gpu) {
        const fields = [
            {label:"Core clock",key:"clock_core_mhz",unit:" MHz"},
            {label:"Memory clock",key:"clock_memory_mhz",unit:" MHz"},
            {label:"Temperature",key:"temperature_c",unit:" °C"},
            {label:"Power",key:"power_w",unit:" W"},
            {label:"Power limit",key:"power_limit_w",unit:" W"},
            {label:"Fan",key:"fan_percent",unit:"%"},
            {label:"Memory controller",key:"memory_controller_percent",unit:"%"},
            {label:"Media engine",key:"media_engine_percent",unit:"%"},
            {label:"Video encode",key:"encoder_percent",unit:"%"},
            {label:"Video decode",key:"decoder_percent",unit:"%"}
        ]
        const rows = fields.filter(field => finite(gpu[field.key])).map(field => ({label:field.label,value:number(gpu[field.key],field.unit)}))
        if (finite(gpu.memory_used_mib) && finite(gpu.memory_total_mib)) rows.unshift({label:gpu.memory_label || "Dedicated memory",value:mib(gpu.memory_used_mib) + " / " + mib(gpu.memory_total_mib)})
        if (gpu.pstate) rows.push({label:"Power state",value:gpu.pstate})
        if (finite(gpu.pcie_generation) && finite(gpu.pcie_width)) rows.push({label:"PCIe link",value:"Gen " + gpu.pcie_generation + " ×" + gpu.pcie_width})
        return rows
    }
    function sampledTime() {
        if (!snapshot) return "Waiting for the first reading"
        const date = new Date(snapshot.captured_at)
        return "Updated " + (isNaN(date.getTime()) ? "time unavailable" : Qt.formatDateTime(date, "hh:mm:ss"))
    }
    function series(key) { return history.map(row => row.values && finite(row.values[key]) ? row.values[key] : null) }
    function rateScale(values) {
        const valid = Array.from(values || []).filter(value => finite(value))
        return valid.length ? rate(Math.max(1, ...valid)) : "Rate unavailable"
    }
    function snapshotValues(payload) {
        const values = {"cpu":payload.cpu ? payload.cpu.utilization_percent : null,
            "memory":payload.memory ? payload.memory.used_percent : null,
            "disk-read":sum(payload.storage && payload.storage.devices, "read_bytes_per_second"),
            "disk-write":sum(payload.storage && payload.storage.devices, "write_bytes_per_second"),
            "net-receive":sum((payload.network || []).filter(row => row.is_physical === true), "received_bytes_per_second"),
            "net-send":sum((payload.network || []).filter(row => row.is_physical === true), "sent_bytes_per_second")}
        for (const gpu of payload.gpus || []) values["gpu:" + gpu.device] = gpu.status === "online" ? gpu.utilization_percent : null
        for (const disk of payload.storage && payload.storage.devices || []) {
            values["disk-read:" + disk.id] = disk.read_bytes_per_second
            values["disk-write:" + disk.id] = disk.write_bytes_per_second
        }
        for (const network of payload.network || []) {
            values["receive:" + network.id] = network.received_bytes_per_second
            values["send:" + network.id] = network.sent_bytes_per_second
        }
        return values
    }
    function applySnapshot(payload) {
        if (!payload || payload.schema !== "obsidience.hardware-monitor.v1"
                || typeof payload.sample_id !== "string" || !payload.sample_id
                || typeof payload.captured_at !== "string" || !payload.cpu || !payload.memory || !payload.storage
                || !Array.isArray(payload.gpus) || !Array.isArray(payload.network)
                || !Array.isArray(payload.processes) || !Array.isArray(payload.problems)) throw new Error("Invalid monitor response")
        if (snapshot && snapshot.sample_id === payload.sample_id) return
        const gap = historyGap || (snapshot && new Date(payload.captured_at).getTime() - new Date(snapshot.captured_at).getTime() > 6000)
        const rows = history.slice()
        if (gap && rows.length) rows.push({"values":null})
        rows.push({"sample_id":payload.sample_id, "values":snapshotValues(payload)})
        history = rows.slice(-120)
        historyGap = false
        snapshot = payload
    }
    function stopRequest() {
        requestGeneration++
        const xhr = activeRequest
        activeRequest = null
        loading = false
        if (xhr) { xhr.onreadystatechange = function() {}; xhr.abort() }
    }
    function refresh() {
        if (!monitorActive || loading) return
        const generation = ++requestGeneration
        const xhr = new XMLHttpRequest()
        activeRequest = xhr
        loading = true
        xhr.open("GET", apiBase + "/api/hardware/monitor")
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE || root.disposing || generation !== root.requestGeneration) return
            root.activeRequest = null
            root.loading = false
            if (xhr.status < 200 || xhr.status >= 300) {
                root.errorMessage = "Monitor unavailable (HTTP " + xhr.status + "). Last reading retained."
                root.historyGap = true
                return
            }
            try { root.applySnapshot(JSON.parse(xhr.responseText)); root.errorMessage = "" }
            catch (error) { root.errorMessage = "Monitor returned an invalid reading. Last reading retained."; root.historyGap = true }
        }
        xhr.send()
    }
    function showSettings() {
        if (shellSocket.status !== WebSocket.Open) { settingsError = "Settings bridge is unavailable."; return }
        settingsError = ""
        shellSocket.sendTextMessage(JSON.stringify({"schema":"obsidience.shell.command.v1", "type":"pane.present",
            "pane_id":"settings", "selection":{"kind":"settings", "section":"ai-voice"}}))
    }
    Component.onCompleted: refresh()
    Component.onDestruction: { disposing = true; stopRequest() }
    onMonitorActiveChanged: {
        if (monitorActive) refresh()
        else { historyGap = true; stopRequest() }
    }
    Timer { interval: 2000; repeat: true; running: root.monitorActive; onTriggered: root.refresh() }
    Timer {
        interval: 10000; running: root.loading
        onTriggered: { root.stopRequest(); root.errorMessage = "Monitor timed out. Last reading retained."; root.historyGap = true }
    }
    WebSocket {
        id: shellSocket
        url: "ws://127.0.0.1:8768"
        requestedSubprotocols: ["obsidience.shell.v1"]
        active: root.visible
        onStatusChanged: status => { if (root.visible && (status === WebSocket.Error || status === WebSocket.Closed)) reconnect.restart() }
    }
    Timer { id: reconnect; interval: 1000; onTriggered: { if (root.visible) { shellSocket.active = false; shellSocket.active = true } } }

    component Copy: Text {
        Layout.fillWidth: true; textFormat: Text.PlainText; wrapMode: Text.Wrap
        color: root.shellTheme.muted; font.pixelSize: 12; lineHeight: 1.1
    }
    component Heading: Copy { color: root.shellTheme.text; font.pixelSize: 15; font.weight: Font.DemiBold }
    component Action: GlowButton {
        uppercase: false; textPixelSize: 11; textLetterSpacing: 0
        foreground: root.shellTheme.text; accent: root.accentColor
        implicitHeight: 28
    }
    component Readings: ColumnLayout {
        id: readings
        property var rows: []
        spacing: 7
        Repeater {
            model: readings.rows
            delegate: RowLayout {
                required property var modelData
                Layout.fillWidth: true; spacing: 14
                Copy { text: parent.modelData.label }
                Copy { Layout.fillWidth: false; text: parent.modelData.value; color: root.shellTheme.text; horizontalAlignment: Text.AlignRight }
            }
        }
    }
    component ProcessTable: ColumnLayout {
        id: table
        property var rows: []
        property bool small: false
        spacing: 2
        RowLayout {
            Layout.fillWidth: true; spacing: 8
            Copy { visible: !table.small; Layout.preferredWidth: 46; Layout.fillWidth: false; text: "PID"; font.pixelSize: 10 }
            Copy { text: "Process"; font.pixelSize: 10 }
            Copy { Layout.preferredWidth: table.small ? 48 : 72; Layout.fillWidth: false; text: table.small ? "CPU %" : "CPU % of system"; font.pixelSize: 10; horizontalAlignment: Text.AlignRight }
            Copy { visible: !table.small; Layout.preferredWidth: 80; Layout.fillWidth: false; text: "Memory"; font.pixelSize: 10; horizontalAlignment: Text.AlignRight }
        }
        Repeater {
            model: table.rows
            delegate: Rectangle {
                id: processRow
                required property var modelData
                required property int index
                objectName: (table.small ? "hardware-top-process-" : "hardware-process-") + modelData.pid + "-" + modelData.started_at
                Layout.fillWidth: true; implicitHeight: table.small ? 22 : 30
                color: index % 2 === 0 ? root.shellTheme.selection : "transparent"
                RowLayout {
                    anchors.fill: parent; anchors.leftMargin: 3; anchors.rightMargin: 3; spacing: 8
                    Copy { visible: !table.small; Layout.preferredWidth: 43; Layout.fillWidth: false; text: processRow.modelData.pid; font.pixelSize: 11 }
                    Copy { text: processRow.modelData.name; color: root.shellTheme.text; maximumLineCount: 1; elide: Text.ElideRight; font.pixelSize: table.small ? 10 : 12 }
                    Copy { Layout.preferredWidth: table.small ? 45 : 72; Layout.fillWidth: false; text: root.finite(processRow.modelData.cpu_percent) ? root.percent(processRow.modelData.cpu_percent) : "—"; horizontalAlignment: Text.AlignRight; font.pixelSize: 11 }
                    Copy { visible: !table.small; Layout.preferredWidth: 77; Layout.fillWidth: false; text: root.bytes(processRow.modelData.memory_bytes); horizontalAlignment: Text.AlignRight; font.pixelSize: 11 }
                }
            }
        }
    }
    component DeviceButton: ItemDelegate {
        id: deviceButton
        property string deviceId: ""
        property string label: ""
        Layout.fillWidth: true; implicitHeight: 29
        Accessible.name: label
        background: Rectangle { color: root.activeDevice === deviceButton.deviceId ? root.shellTheme.selection : deviceButton.hovered ? root.shellTheme.hover : "transparent"; radius: 3 }
        contentItem: Text { text: deviceButton.label; textFormat: Text.PlainText; leftPadding: 19; color: root.activeDevice === deviceButton.deviceId ? root.shellTheme.text : root.shellTheme.muted; font.pixelSize: 11; elide: Text.ElideRight; verticalAlignment: Text.AlignVCenter }
        onClicked: { root.activeDevice = deviceId; detailScroll.contentItem.contentY = 0 }
        ToolTip.visible: hovered; ToolTip.text: label; ToolTip.delay: 500
    }

    RowLayout {
        anchors.fill: parent; spacing: 0
        Rectangle {
            Layout.preferredWidth: root.compact ? 154 : 184
            Layout.fillHeight: true
            color: root.shellTheme.inactiveSurface
            Rectangle { anchors.right: parent.right; height: parent.height; width: 1; color: root.shellTheme.separator }
            ScrollView {
                id: navigationScroll
                objectName: "hardware-navigation"
                anchors.fill: parent; anchors.margins: 6
                contentWidth: availableWidth; clip: true
                ColumnLayout {
                    width: navigationScroll.availableWidth; spacing: 3
                    Repeater {
                        model: root.sections
                        delegate: ColumnLayout {
                            id: navGroup
                            required property var modelData
                            Layout.fillWidth: true; spacing: 1
                            Copy { visible: navGroup.modelData.id === "cpu"; text: "PERFORMANCE"; font.pixelSize: 9; font.letterSpacing: 1; topPadding: 12; bottomPadding: 5; leftPadding: 9 }
                            ItemDelegate {
                                id: navigation
                                objectName: "hardware-nav-" + navGroup.modelData.id
                                Layout.fillWidth: true; implicitHeight: 34
                                Accessible.name: navGroup.modelData.label
                                background: Rectangle { radius: 3; color: root.activeSection === navGroup.modelData.id ? root.shellTheme.selection : navigation.hovered ? root.shellTheme.hover : "transparent" }
                                contentItem: RowLayout {
                                    spacing: 8
                                    ShellIcon { Layout.preferredWidth: 17; Layout.preferredHeight: 17; iconColor: root.accentColor; iconOpacity: root.activeSection === navGroup.modelData.id ? 1 : 0.5; glyph: navGroup.modelData.icon }
                                    Text { Layout.fillWidth: true; text: navGroup.modelData.label; color: root.activeSection === navGroup.modelData.id ? root.shellTheme.text : root.shellTheme.muted; font.pixelSize: 12; elide: Text.ElideRight }
                                }
                                onClicked: { root.activeSection = navGroup.modelData.id; root.activeDevice = ""; detailScroll.contentItem.contentY = 0 }
                            }
                            Repeater {
                                model: root.activeSection === navGroup.modelData.id && navGroup.modelData.id === "gpus" ? root.gpus : []
                                delegate: DeviceButton { required property var modelData; deviceId: modelData.device; label: modelData.name || modelData.device; objectName: "hardware-device-" + deviceId }
                            }
                            Repeater {
                                model: root.activeSection === navGroup.modelData.id && navGroup.modelData.id === "storage" ? root.storage.devices || [] : []
                                delegate: DeviceButton { required property var modelData; deviceId: modelData.id; label: modelData.name; objectName: "hardware-device-" + deviceId }
                            }
                            Repeater {
                                model: root.activeSection === navGroup.modelData.id && navGroup.modelData.id === "network" ? root.networks : []
                                delegate: DeviceButton { required property var modelData; deviceId: modelData.id; label: modelData.id; objectName: "hardware-device-" + deviceId }
                            }
                        }
                    }
                }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            Layout.margins: 10; spacing: 7
            RowLayout {
                Layout.fillWidth: true
                Heading { objectName: "hardware-section-title"; text: root.sectionTitle; font.pixelSize: 19; maximumLineCount: 1; elide: Text.ElideRight }
                Action { objectName: "hardware-refresh"; text: root.loading ? "Reading…" : "Refresh"; enabled: !root.loading; onClicked: root.refresh() }
            }
            Copy { text: root.sampledTime(); font.pixelSize: 10 }
            Copy { objectName: "hardware-error"; visible: !!root.errorMessage || !!root.settingsError; text: root.errorMessage || root.settingsError; color: "#fda4af" }
            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: root.shellTheme.separator }
            ScrollView {
                id: detailScroll
                objectName: "hardware-details"
                Layout.fillWidth: true; Layout.fillHeight: true
                contentWidth: availableWidth; clip: true
                ColumnLayout {
                    width: detailScroll.availableWidth; spacing: 10
                    Copy { visible: !root.snapshot; text: root.errorMessage ? "Use Refresh to try again." : "Reading local hardware…" }
                    Copy { visible: !!root.snapshot && root.snapshot.problems.length > 0; text: root.snapshot ? root.snapshot.problems.map(row => row.component + ": " + row.message).join(" · ") : ""; color: "#f5cf89" }
                    ColumnLayout {
                        objectName: "hardware-summary"
                        visible: !!root.snapshot && root.activeSection === "overview"
                        Layout.fillWidth: true; spacing: 9
                        RowLayout {
                            Layout.fillWidth: true; spacing: 8
                            Rectangle {
                                Layout.preferredWidth: 94; Layout.preferredHeight: summaryCpu.height
                                color: root.shellTheme.inactiveSurface; border.color: root.shellTheme.separator; radius: 3
                                ColumnLayout {
                                    anchors.fill: parent; anchors.margins: 8; spacing: 7
                                    Copy { text: "SYSTEM"; color: root.accentColor; font.pixelSize: 10; font.weight: Font.DemiBold }
                                    RowLayout {
                                        Layout.fillWidth: true; Layout.fillHeight: true; spacing: 7
                                        MonitorMeter { Layout.fillWidth: true; Layout.fillHeight: true; shellTheme: root.shellTheme; label: "CPU"; value: root.cpu.utilization_percent }
                                        MonitorMeter { Layout.fillWidth: true; Layout.fillHeight: true; shellTheme: root.shellTheme; label: "RAM"; value: root.memory.used_percent }
                                    }
                                }
                            }
                            MonitorPlot {
                                id: summaryCpu
                                objectName: "hardware-summary-cpu-plot"
                                Layout.fillWidth: true; shellTheme: root.shellTheme
                                title: "CPU overview"; value: root.percent(root.cpu.utilization_percent)
                                detail: root.number(root.cpu.clock_core_mhz, " MHz") + " · " + root.number(root.cpu.temperature_c, " °C") + " · " + root.number(root.cpu.threads, " logical cores")
                                values: root.series("cpu"); plotHeight: 100
                            }
                            Rectangle {
                                visible: detailScroll.availableWidth >= 850
                                Layout.preferredWidth: 228; Layout.preferredHeight: summaryCpu.height
                                color: root.shellTheme.inactiveSurface; border.color: root.shellTheme.separator; radius: 3
                                ColumnLayout {
                                    anchors.fill: parent; anchors.margins: 8; spacing: 4
                                    Copy { text: "TOP CPU PROCESSES"; color: root.accentColor; font.pixelSize: 10; font.weight: Font.DemiBold }
                                    ProcessTable { Layout.fillWidth: true; rows: root.processes.slice(0, 5); small: true }
                                    Item { Layout.fillHeight: true }
                                }
                            }
                        }
                        MonitorPlot {
                            objectName: "hardware-summary-memory-plot"
                            Layout.fillWidth: true; shellTheme: root.shellTheme
                            title: "Memory utilization"; value: root.bytes(root.memory.used_bytes) + " / " + root.bytes(root.memory.total_bytes)
                            values: root.series("memory"); plotHeight: 76
                            detail: "Available " + root.bytes(root.memory.available_bytes) + " · Cached " + root.bytes(root.memory.cached_bytes) + " · Swap " + root.bytes(root.memory.swap_used_bytes)
                        }
                        Readings {
                            Layout.fillWidth: true
                            rows: [
                                {label:"CPU load · 1 / 5 / 15 min", value:[root.cpu.load_1m,root.cpu.load_5m,root.cpu.load_15m].map(value => root.number(value, "")).join(" / ")},
                                {label:"Storage · read / write", value:root.rate(root.sum(root.storage.devices,"read_bytes_per_second")) + " / " + root.rate(root.sum(root.storage.devices,"write_bytes_per_second"))},
                                {label:"Physical network · receive / send", value:root.rate(root.sum(root.physicalNetworks,"received_bytes_per_second")) + " / " + root.rate(root.sum(root.physicalNetworks,"sent_bytes_per_second"))}
                            ]
                        }
                        Repeater {
                            model: root.gpus
                            delegate: ColumnLayout {
                                id: summaryGpu
                                required property var modelData
                                Layout.fillWidth: true; spacing: 4
                                RowLayout {
                                    Layout.fillWidth: true
                                    Copy { text: summaryGpu.modelData.name || summaryGpu.modelData.device; elide: Text.ElideRight; maximumLineCount: 1 }
                                    Copy { Layout.fillWidth: false; text: summaryGpu.modelData.status === "online" ? root.percent(summaryGpu.modelData.utilization_percent) + (root.finite(summaryGpu.modelData.temperature_c) ? " · " + root.number(summaryGpu.modelData.temperature_c, " °C") : "") : "Unavailable"; color: root.shellTheme.text }
                                }
                                Rectangle {
                                    Layout.fillWidth: true; implicitHeight: 5; color: root.shellTheme.selection
                                    Rectangle { height: parent.height; width: root.finite(summaryGpu.modelData.utilization_percent) && summaryGpu.modelData.status === "online" ? parent.width * Math.min(1, summaryGpu.modelData.utilization_percent / 100) : 0; color: root.accentColor; opacity: 0.75 }
                                }
                            }
                        }
                        Heading { visible: detailScroll.availableWidth < 850; text: "Top CPU processes"; topPadding: 6 }
                        ProcessTable { objectName: "hardware-summary-top-processes"; visible: detailScroll.availableWidth < 850; Layout.fillWidth: true; rows: root.processes.slice(0, 5); small: true }
                    }
                    ColumnLayout {
                        visible: !!root.snapshot && root.activeSection === "cpu"
                        Layout.fillWidth: true; spacing: 12
                        MonitorPlot { Layout.fillWidth: true; shellTheme: root.shellTheme; title: "Utilization"; value: root.percent(root.cpu.utilization_percent); detail: root.number(root.cpu.physical_cores, " physical cores") + " · " + root.number(root.cpu.threads, " logical cores"); values: root.series("cpu"); plotHeight: 200 }
                        Readings { Layout.fillWidth: true; rows: [{label:"Clock",value:root.number(root.cpu.clock_core_mhz," MHz")},{label:"Temperature",value:root.number(root.cpu.temperature_c," °C")},{label:"Load average · 1 / 5 / 15 min",value:[root.cpu.load_1m,root.cpu.load_5m,root.cpu.load_15m].map(value => root.number(value, "")).join(" / ")}] }
                        Heading { text: "Logical processors" }
                        GridLayout {
                            Layout.fillWidth: true; columns: Math.max(2, Math.floor(detailScroll.availableWidth / 105)); columnSpacing: 8; rowSpacing: 6
                            Repeater {
                                model: root.cpu.per_core_percent || []
                                delegate: ColumnLayout {
                                    id: coreReading
                                    required property var modelData
                                    required property int index
                                    Layout.fillWidth: true; spacing: 3
                                    RowLayout { Layout.fillWidth: true; Copy { text: "CPU " + coreReading.index; font.pixelSize: 10 } Copy { Layout.fillWidth: false; text: root.finite(coreReading.modelData) ? Math.round(coreReading.modelData) + "%" : "—"; color: root.shellTheme.text; font.pixelSize: 10 } }
                                    Rectangle { Layout.fillWidth: true; implicitHeight: 4; color: root.shellTheme.selection; Rectangle { height: parent.height; width: root.finite(coreReading.modelData) ? parent.width * Math.min(1,coreReading.modelData / 100) : 0; color: root.accentColor; opacity: 0.75 } }
                                }
                            }
                        }
                        Copy { visible: !root.cpu.per_core_percent || !root.cpu.per_core_percent.length; text: "Per-core readings are unavailable." }
                    }
                    ColumnLayout {
                        visible: !!root.snapshot && root.activeSection === "memory"
                        Layout.fillWidth: true; spacing: 12
                        MonitorPlot { Layout.fillWidth: true; shellTheme: root.shellTheme; title: "Memory utilization"; value: root.percent(root.memory.used_percent); detail: root.bytes(root.memory.used_bytes) + " of " + root.bytes(root.memory.total_bytes); values: root.series("memory"); plotHeight: 200 }
                        Readings { Layout.fillWidth: true; rows: [{label:"In use",value:root.bytes(root.memory.used_bytes)},{label:"Available",value:root.bytes(root.memory.available_bytes)},{label:"Cached",value:root.bytes(root.memory.cached_bytes)},{label:"Swap in use",value:root.bytes(root.memory.swap_used_bytes)},{label:"Swap capacity",value:root.bytes(root.memory.swap_total_bytes)}] }
                    }
                    ColumnLayout {
                        visible: !!root.snapshot && root.activeSection === "gpus"
                        Layout.fillWidth: true; spacing: 12
                        MonitorPlot { Layout.fillWidth: true; shellTheme: root.shellTheme; title: root.selectedGpu.name || "GPU utilization"; value: root.selectedGpu.status === "online" ? root.percent(root.selectedGpu.utilization_percent) : "Unavailable"; detail: root.gpuDetail(root.selectedGpu); values: root.series("gpu:" + root.selectedGpu.device); plotHeight: 200 }
                        Readings { Layout.fillWidth: true; visible: root.selectedGpu.status === "online"; rows: root.gpuReadings(root.selectedGpu) }
                        Copy { visible: !root.gpus.length; text: "No GPU readings are available." }
                    }
                    ColumnLayout {
                        visible: !!root.snapshot && root.activeSection === "storage"
                        Layout.fillWidth: true; spacing: 12
                        MonitorPlot { Layout.fillWidth: true; shellTheme: root.shellTheme; title: "Read throughput"; value: root.rate(root.selectedDisk ? root.selectedDisk.read_bytes_per_second : root.sum(root.storage.devices,"read_bytes_per_second")); values: root.series(root.selectedDisk ? "disk-read:" + root.selectedDisk.id : "disk-read"); maximum: 0; scaleLabel: root.rateScale(values); plotHeight: 100 }
                        MonitorPlot { Layout.fillWidth: true; shellTheme: root.shellTheme; title: "Write throughput"; value: root.rate(root.selectedDisk ? root.selectedDisk.write_bytes_per_second : root.sum(root.storage.devices,"write_bytes_per_second")); values: root.series(root.selectedDisk ? "disk-write:" + root.selectedDisk.id : "disk-write"); maximum: 0; scaleLabel: root.rateScale(values); plotHeight: 100 }
                        Readings { visible: !!root.selectedDisk; Layout.fillWidth: true; rows: [{label:"Device",value:root.selectedDisk ? root.selectedDisk.name : ""},{label:"I/O busy",value:root.percent(root.selectedDisk ? root.selectedDisk.io_busy_percent : null)}] }
                        Heading { text: "All mounted filesystems" }
                        Repeater {
                            model: root.storage.filesystems || []
                            delegate: ColumnLayout {
                                id: filesystemRow
                                required property var modelData
                                Layout.fillWidth: true; spacing: 5
                                Copy { text: Array.from(filesystemRow.modelData.mount_points || []).join(" · ") || filesystemRow.modelData.source || filesystemRow.modelData.id; color: root.shellTheme.text }
                                Rectangle { Layout.fillWidth: true; implicitHeight: 6; color: root.shellTheme.selection; Rectangle { height: parent.height; width: root.finite(filesystemRow.modelData.used_percent) ? parent.width * Math.min(1,filesystemRow.modelData.used_percent / 100) : 0; color: root.accentColor; opacity: 0.75 } }
                                Copy { text: root.percent(filesystemRow.modelData.used_percent) + " used · " + root.bytes(filesystemRow.modelData.available_bytes) + " available · " + (filesystemRow.modelData.filesystem || "Unknown format"); font.pixelSize: 11 }
                            }
                        }
                        Copy { visible: !root.storage.filesystems || !root.storage.filesystems.length; text: "Filesystem readings are unavailable." }
                    }
                    ColumnLayout {
                        visible: !!root.snapshot && root.activeSection === "network"
                        Layout.fillWidth: true; spacing: 12
                        MonitorPlot { Layout.fillWidth: true; shellTheme: root.shellTheme; title: "Receive"; value: root.rate(root.selectedNetwork.received_bytes_per_second); values: root.series("receive:" + root.selectedNetwork.id); maximum: 0; scaleLabel: root.rateScale(values); plotHeight: 110 }
                        MonitorPlot { Layout.fillWidth: true; shellTheme: root.shellTheme; title: "Send"; value: root.rate(root.selectedNetwork.sent_bytes_per_second); values: root.series("send:" + root.selectedNetwork.id); maximum: 0; scaleLabel: root.rateScale(values); plotHeight: 110 }
                        Readings { Layout.fillWidth: true; rows: [{label:"Interface",value:root.selectedNetwork.id || "Unavailable"},{label:"State",value:root.selectedNetwork.state || "Unavailable"},{label:"Link speed",value:root.number(root.selectedNetwork.speed_mbps," Mbps")},{label:"Received",value:root.bytes(root.selectedNetwork.total_received_bytes)},{label:"Sent",value:root.bytes(root.selectedNetwork.total_sent_bytes)}] }
                        Copy { visible: !root.networks.length; text: "No network interfaces are available." }
                    }
                    ColumnLayout {
                        visible: !!root.snapshot && root.activeSection === "processes"
                        Layout.fillWidth: true; spacing: 8
                        Copy { text: "Top " + root.processes.length + " processes by CPU use"; font.pixelSize: 11 }
                        ProcessTable { Layout.fillWidth: true; rows: root.processes }
                        Copy { visible: !root.processes.length; text: "No process readings are available." }
                    }
                }
            }
            Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: root.shellTheme.separator }
            RowLayout {
                Layout.fillWidth: true; spacing: 5
                Copy { text: !root.snapshot ? "Connecting" : root.errorMessage ? "Monitor unavailable" : root.snapshot.problems.length ? root.snapshot.problems.length + " sensor notices" : "Local sensors"; font.pixelSize: 10 }
                Action { objectName: "hardware-ai-voice-settings"; text: "AI & Voice settings"; onClicked: root.showSettings() }
            }
        }
    }
}
