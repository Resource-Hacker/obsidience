pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls

Item {
    id: root

    readonly property string apiBase: "http://127.0.0.1:8765"
    property var hardware: null
    property string changing: ""
    property string errorMessage: ""
    property bool loading: false

    function responseError(request, fallback) {
        const raw = request.responseText || ""
        try {
            const parsed = JSON.parse(raw)
            if (parsed && typeof parsed.detail === "string" && parsed.detail) {
                return parsed.detail
            }
        } catch (error) {
            // Plain-text failures are already useful.
        }
        return raw || fallback + " (" + request.status + ")"
    }

    function request(method, path, body, onSuccess, onFailure) {
        const xhr = new XMLHttpRequest()
        xhr.open(method, apiBase + path)
        if (body !== null) {
            xhr.setRequestHeader("content-type", "application/json")
        }
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE) {
                return
            }
            if (xhr.status < 200 || xhr.status >= 300) {
                onFailure(responseError(xhr, "Request failed"))
                return
            }
            try {
                onSuccess(JSON.parse(xhr.responseText))
            } catch (error) {
                onFailure("Obsidience returned invalid JSON.")
            }
        }
        xhr.send(body === null ? null : JSON.stringify(body))
    }

    function refresh() {
        if (changing) {
            return
        }
        loading = hardware === null
        request("GET", "/api/hardware", null, function(payload) {
            root.hardware = payload
            root.loading = false
            root.errorMessage = ""
        }, function(message) {
            root.loading = false
            root.errorMessage = message
        })
    }

    function assignSlot(device, component) {
        if (changing) {
            return
        }
        changing = device
        errorMessage = ""
        request("PATCH", "/api/hardware", {
            "device": device,
            "component": component
        }, function(payload) {
            root.hardware = payload
            root.changing = ""
        }, function(message) {
            root.errorMessage = message
            root.changing = ""
            root.refresh()
        })
    }

    function assignInterface(hardwareInterface, selection) {
        if (changing) {
            return
        }
        changing = hardwareInterface
        errorMessage = ""
        request("PATCH", "/api/hardware/interfaces", {
            "interface": hardwareInterface,
            "selection": selection
        }, function(payload) {
            root.hardware = payload
            root.changing = ""
        }, function(message) {
            root.errorMessage = message
            root.changing = ""
            root.refresh()
        })
    }

    function assignVoice(voice) {
        if (changing) {
            return
        }
        changing = "speech-voice"
        errorMessage = ""
        request("PATCH", "/api/hardware/voice", {"voice": voice}, function() {
            root.changing = ""
            root.refresh()
        }, function(message) {
            root.errorMessage = message
            root.changing = ""
        })
    }

    function optionIndex(options, selected) {
        if (!Array.isArray(options)) {
            return -1
        }
        for (let index = 0; index < options.length; index += 1) {
            if (options[index] && options[index].id === selected) {
                return index
            }
        }
        return -1
    }

    function selectedOption(slot) {
        const options = slot && Array.isArray(slot.options) ? slot.options : []
        const index = optionIndex(options, slot ? slot.selected : "")
        return index >= 0 ? options[index] : null
    }

    function optionText(option) {
        if (!option) {
            return ""
        }
        return String(option.label || option.id)
            + (option.linked === true ? " · USES BOTH GPUS" : "")
            + (option.available === false ? " · UNAVAILABLE" : "")
    }

    function clampPercent(value) {
        const number = Number(value)
        return isFinite(number) ? Math.max(0, Math.min(100, number)) : 0
    }

    function percentText(value) {
        return value === null || value === undefined
            ? "SAMPLING…" : Number(value).toFixed(1) + "%"
    }

    function memoryLabel(value) {
        if (value === null || value === undefined) {
            return "—"
        }
        return Number(value) >= 1024
            ? (Number(value) / 1024).toFixed(1) + " GiB"
            : Number(value).toFixed(0) + " MiB"
    }

    function memoryDetail(sensors) {
        if (!sensors || sensors.memory_total_mib === null
                || sensors.memory_total_mib === undefined) {
            return "UNAVAILABLE"
        }
        return memoryLabel(sensors.memory_used_mib) + " / "
            + memoryLabel(sensors.memory_total_mib)
    }

    function sensorReadings(sensors) {
        if (!sensors || sensors.status !== "online") {
            return []
        }
        const rows = []
        if (sensors.temperature_c !== null && sensors.temperature_c !== undefined) {
            rows.push({"label": "TEMPERATURE", "value": Number(sensors.temperature_c).toFixed(1) + " °C"})
        }
        if (sensors.power_w !== null && sensors.power_w !== undefined) {
            const watts = Number(sensors.power_w)
            const value = sensors.power_limit_w !== null && sensors.power_limit_w !== undefined
                ? watts.toFixed(1) + " / " + Number(sensors.power_limit_w).toFixed(0) + " W"
                : watts < 0.1 ? (watts * 1000).toFixed(0) + " mW" : watts.toFixed(1) + " W"
            rows.push({"label": "POWER", "value": value})
        }
        if (sensors.clock_core_mhz !== null && sensors.clock_core_mhz !== undefined) {
            rows.push({"label": "CORE CLOCK", "value": sensors.clock_core_mhz + " MHz"})
        }
        if (sensors.clock_memory_mhz !== null && sensors.clock_memory_mhz !== undefined) {
            rows.push({"label": "MEMORY CLOCK", "value": sensors.clock_memory_mhz + " MHz"})
        }
        if (sensors.fan_percent !== null && sensors.fan_percent !== undefined) {
            rows.push({"label": "FAN", "value": sensors.fan_percent + "%"})
        }
        if (sensors.pstate) {
            rows.push({"label": "POWER STATE", "value": String(sensors.pstate)})
        }
        if (sensors.pcie_generation !== null && sensors.pcie_generation !== undefined
                && sensors.pcie_width !== null && sensors.pcie_width !== undefined) {
            rows.push({"label": "PCIE LINK", "value": "GEN " + sensors.pcie_generation + " ×" + sensors.pcie_width})
        }
        if (sensors.memory_controller_percent !== null
                && sensors.memory_controller_percent !== undefined) {
            rows.push({"label": "MEMORY ENGINE", "value": sensors.memory_controller_percent + "%"})
        }
        if (sensors.encoder_percent !== null && sensors.encoder_percent !== undefined) {
            rows.push({"label": "ENCODER", "value": sensors.encoder_percent + "%"})
        }
        if (sensors.decoder_percent !== null && sensors.decoder_percent !== undefined) {
            rows.push({"label": "DECODER", "value": sensors.decoder_percent + "%"})
        }
        if (sensors.media_engine_percent !== null && sensors.media_engine_percent !== undefined) {
            rows.push({"label": "MEDIA ENGINE", "value": sensors.media_engine_percent + "%"})
        }
        if (sensors.load_1m !== null && sensors.load_1m !== undefined) {
            rows.push({
                "label": "LOAD AVERAGE",
                "value": sensors.load_1m + " · " + sensors.load_5m + " · " + sensors.load_15m
            })
        }
        if (sensors.physical_cores !== null && sensors.physical_cores !== undefined) {
            rows.push({
                "label": "TOPOLOGY",
                "value": sensors.physical_cores + " CORES · " + sensors.threads + " THREADS"
            })
        }
        if (sensors.driver) {
            rows.push({"label": "DRIVER", "value": String(sensors.driver)})
        }
        return rows
    }

    Component.onCompleted: refresh()
    onVisibleChanged: {
        if (visible) {
            refresh()
        }
    }

    Timer {
        interval: 3000
        repeat: true
        running: root.visible && root.changing === ""
        onTriggered: root.refresh()
    }

    Text {
        anchors.centerIn: parent
        visible: root.hardware === null
        width: Math.max(120, parent.width - 40)
        text: root.errorMessage || "READING HARDWARE ASSIGNMENTS…"
        color: root.errorMessage ? "#fda4af" : "#667dd3fc"
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.Wrap
        font.family: "JetBrains Mono"
        font.pixelSize: 10
        font.letterSpacing: 0.8
    }

    Flickable {
        id: scroll

        anchors.fill: parent
        visible: root.hardware !== null
        clip: true
        contentWidth: width
        contentHeight: content.implicitHeight + 28
        boundsBehavior: Flickable.StopAtBounds

        ScrollBar.vertical: ScrollBar {}

        Column {
            id: content

            x: 14
            y: 14
            width: Math.max(240, scroll.width - 28)
            spacing: 10

            Rectangle {
                width: content.width
                height: warmHeader.implicitHeight + 20
                radius: 8
                color: "#17071119"
                border.width: 1
                border.color: "#2467e8f9"

                Column {
                    id: warmHeader

                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 10
                    spacing: 5

                    Text {
                        width: parent.width
                        text: "WARM DEFAULTS"
                        color: "#e6faff"
                        font.family: "JetBrains Mono"
                        font.pixelSize: 10
                        font.letterSpacing: 1.6
                    }

                    Text {
                        width: parent.width
                        text: "Loaded while hardware is idle. A Task may lease an allowed device, then the displaced default returns."
                        color: "#7367e8f9"
                        wrapMode: Text.Wrap
                        font.family: "JetBrains Mono"
                        font.pixelSize: 8
                        lineHeight: 1.35
                        lineHeightMode: Text.ProportionalHeight
                    }
                }
            }

            Repeater {
                model: root.hardware && Array.isArray(root.hardware.slots)
                    ? root.hardware.slots : []

                delegate: Rectangle {
                    id: slotCard

                    required property var modelData
                    readonly property bool busy: root.changing === modelData.id
                        || (root.hardware && root.hardware.switching === true)
                    readonly property var sensorRows: root.sensorReadings(modelData.sensors)

                    width: content.width
                    height: slotColumn.implicitHeight + 24
                    radius: 9
                    color: "#b803101a"
                    border.width: 1
                    border.color: "#2467e8f9"

                    Column {
                        id: slotColumn

                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 12
                        spacing: 8

                        Item {
                            width: parent.width
                            height: 17

                            Text {
                                anchors.left: parent.left
                                anchors.right: slotState.left
                                anchors.rightMargin: 10
                                text: slotCard.modelData.label
                                color: "#e6faff"
                                elide: Text.ElideRight
                                font.family: "JetBrains Mono"
                                font.pixelSize: 11
                            }

                            Text {
                                id: slotState

                                anchors.right: parent.right
                                text: slotCard.busy ? "APPLYING"
                                    : slotCard.modelData.selected === "none" ? "IDLE" : "DEFAULT"
                                color: slotCard.busy ? "#fde68a"
                                    : slotCard.modelData.selected === "none" ? "#5267e8f9" : "#6ee7b7"
                                font.family: "JetBrains Mono"
                                font.pixelSize: 8
                                font.letterSpacing: 1.0
                            }
                        }

                        Text {
                            width: parent.width
                            visible: !slotCard.modelData.sensors
                                || slotCard.modelData.sensors.status !== "online"
                            text: "SENSOR TELEMETRY UNAVAILABLE"
                            color: "#99fda4af"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                        }

                        Item {
                            width: parent.width
                            height: 32
                            visible: slotCard.modelData.sensors
                                && slotCard.modelData.sensors.status === "online"

                            Text {
                                anchors.left: parent.left
                                anchors.top: parent.top
                                text: String(slotCard.modelData.sensors.memory_label || "MEMORY").toUpperCase()
                                color: "#667dd3fc"
                                font.family: "JetBrains Mono"
                                font.pixelSize: 7
                                font.letterSpacing: 1.0
                            }

                            Text {
                                anchors.right: parent.right
                                anchors.top: parent.top
                                text: root.percentText(slotCard.modelData.sensors.memory_used_percent)
                                    + " · " + root.memoryDetail(slotCard.modelData.sensors)
                                color: "#b8f7ff"
                                font.family: "JetBrains Mono"
                                font.pixelSize: 8
                            }

                            Rectangle {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                height: 5
                                radius: 3
                                color: "#4d000000"
                                border.width: 1
                                border.color: "#2467e8f9"

                                Rectangle {
                                    width: parent.width * root.clampPercent(
                                        slotCard.modelData.sensors.memory_used_percent
                                    ) / 100
                                    height: parent.height
                                    radius: parent.radius
                                    color: "#b8a78bfa"

                                    Behavior on width { NumberAnimation { duration: 400 } }
                                }
                            }
                        }

                        Item {
                            width: parent.width
                            height: 32
                            visible: slotCard.modelData.sensors
                                && slotCard.modelData.sensors.status === "online"

                            Text {
                                anchors.left: parent.left
                                anchors.top: parent.top
                                text: "UTILIZATION"
                                color: "#667dd3fc"
                                font.family: "JetBrains Mono"
                                font.pixelSize: 7
                                font.letterSpacing: 1.0
                            }

                            Text {
                                anchors.right: parent.right
                                anchors.top: parent.top
                                text: root.percentText(slotCard.modelData.sensors.utilization_percent)
                                    + " · LIVE COMPUTE"
                                color: "#b8f7ff"
                                font.family: "JetBrains Mono"
                                font.pixelSize: 8
                            }

                            Rectangle {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.bottom: parent.bottom
                                height: 5
                                radius: 3
                                color: "#4d000000"
                                border.width: 1
                                border.color: "#2467e8f9"

                                Rectangle {
                                    width: parent.width * root.clampPercent(
                                        slotCard.modelData.sensors.utilization_percent
                                    ) / 100
                                    height: parent.height
                                    radius: parent.radius
                                    color: "#b867e8f9"

                                    Behavior on width { NumberAnimation { duration: 400 } }
                                }
                            }
                        }

                        Grid {
                            id: readingsGrid

                            width: parent.width
                            columns: width >= 620 ? 3 : 2
                            columnSpacing: 6
                            rowSpacing: 6
                            height: childrenRect.height

                            Repeater {
                                model: slotCard.sensorRows

                                delegate: Rectangle {
                                    id: readingCard

                                    required property var modelData
                                    width: (readingsGrid.width
                                        - readingsGrid.columnSpacing * (readingsGrid.columns - 1))
                                        / readingsGrid.columns
                                    height: 42
                                    radius: 5
                                    color: "#12071119"
                                    border.width: 1
                                    border.color: "#16067e8f9"

                                    Column {
                                        anchors.left: parent.left
                                        anchors.right: parent.right
                                        anchors.verticalCenter: parent.verticalCenter
                                        anchors.margins: 7
                                        spacing: 3

                                        Text {
                                            width: parent.width
                                            text: readingCard.modelData.label
                                            color: "#527dd3fc"
                                            elide: Text.ElideRight
                                            font.family: "JetBrains Mono"
                                            font.pixelSize: 7
                                            font.letterSpacing: 0.7
                                        }

                                        Text {
                                            width: parent.width
                                            text: readingCard.modelData.value
                                            color: "#b8f7ff"
                                            elide: Text.ElideRight
                                            font.family: "JetBrains Mono"
                                            font.pixelSize: 8
                                        }
                                    }
                                }
                            }
                        }

                        Rectangle {
                            width: parent.width
                            height: 1
                            color: "#2467e8f9"
                        }

                        ComboBox {
                            id: slotSelector

                            property var optionRows: Array.isArray(slotCard.modelData.options)
                                ? slotCard.modelData.options : []

                            width: parent.width
                            model: optionRows
                            textRole: "label"
                            valueRole: "id"
                            currentIndex: root.optionIndex(optionRows, slotCard.modelData.selected)
                            enabled: !slotCard.busy
                            font.family: "JetBrains Mono"
                            font.pixelSize: 9

                            contentItem: Text {
                                leftPadding: 8
                                rightPadding: slotSelector.indicator.width + 12
                                text: root.optionText(root.selectedOption(slotCard.modelData))
                                color: slotSelector.enabled ? "#cffafe" : "#667dd3fc"
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideRight
                                font: slotSelector.font
                            }

                            background: Rectangle {
                                radius: 5
                                color: "#020a12"
                                border.width: 1
                                border.color: slotSelector.activeFocus
                                    ? "#8067e8f9" : "#4067e8f9"
                            }

                            delegate: ItemDelegate {
                                required property var modelData
                                width: slotSelector.width
                                enabled: modelData.available === true
                                text: root.optionText(modelData)
                                font: slotSelector.font
                            }

                            onActivated: index => {
                                const option = optionRows[index]
                                if (option && option.available === true) {
                                    root.assignSlot(slotCard.modelData.id, option.id)
                                }
                            }
                        }

                        Text {
                            width: parent.width
                            text: slotCard.modelData.note || ""
                            color: "#667dd3fc"
                            wrapMode: Text.Wrap
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                            lineHeight: 1.35
                            lineHeightMode: Text.ProportionalHeight
                        }

                        Text {
                            width: parent.width
                            visible: {
                                const selected = root.selectedOption(slotCard.modelData)
                                return selected && selected.linked === true
                            }
                            text: "LINKED ASSIGNMENT · BOTH GPU ROWS MOVE TOGETHER"
                            color: "#99fde68a"
                            wrapMode: Text.Wrap
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                        }
                    }
                }
            }

            Rectangle {
                width: content.width
                height: interfaceHeader.implicitHeight + 20
                radius: 8
                color: "#140c0a1d"
                border.width: 1
                border.color: "#24a78bfa"

                Column {
                    id: interfaceHeader

                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 10
                    spacing: 5

                    Text {
                        width: parent.width
                        text: "INPUTS AND OUTPUTS"
                        color: "#e6faff"
                        font.family: "JetBrains Mono"
                        font.pixelSize: 10
                        font.letterSpacing: 1.6
                    }

                    Text {
                        width: parent.width
                        text: "Realtime freezes the selected microphone and speaker at its next start. Camera chooses the physical device used by Camera and Camera Tools."
                        color: "#80c4b5fd"
                        wrapMode: Text.Wrap
                        font.family: "JetBrains Mono"
                        font.pixelSize: 8
                        lineHeight: 1.35
                        lineHeightMode: Text.ProportionalHeight
                    }
                }
            }

            Repeater {
                model: root.hardware && Array.isArray(root.hardware.interfaces)
                    ? root.hardware.interfaces : []

                delegate: Rectangle {
                    id: interfaceCard

                    required property var modelData
                    readonly property bool busy: root.changing === modelData.id
                    readonly property var selected: root.selectedOption(modelData)

                    width: content.width
                    height: interfaceColumn.implicitHeight + 24
                    radius: 9
                    color: "#b8080b18"
                    border.width: 1
                    border.color: "#24a78bfa"

                    Column {
                        id: interfaceColumn

                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 12
                        spacing: 7

                        Item {
                            width: parent.width
                            height: 17

                            Text {
                                anchors.left: parent.left
                                anchors.right: interfaceState.left
                                anchors.rightMargin: 10
                                text: interfaceCard.modelData.label
                                color: "#e6faff"
                                elide: Text.ElideRight
                                font.family: "JetBrains Mono"
                                font.pixelSize: 11
                            }

                            Text {
                                id: interfaceState

                                anchors.right: parent.right
                                text: interfaceCard.busy ? "SAVING"
                                    : interfaceCard.selected && interfaceCard.selected.available
                                        ? "AVAILABLE" : "MISSING"
                                color: interfaceCard.busy ? "#fde68a"
                                    : interfaceCard.selected && interfaceCard.selected.available
                                        ? "#6ee7b7" : "#fda4af"
                                font.family: "JetBrains Mono"
                                font.pixelSize: 8
                                font.letterSpacing: 1.0
                            }
                        }

                        ComboBox {
                            id: interfaceSelector

                            property var optionRows: Array.isArray(interfaceCard.modelData.options)
                                ? interfaceCard.modelData.options : []

                            width: parent.width
                            model: optionRows
                            textRole: "label"
                            valueRole: "id"
                            currentIndex: root.optionIndex(optionRows, interfaceCard.modelData.selected)
                            enabled: !interfaceCard.busy
                            font.family: "JetBrains Mono"
                            font.pixelSize: 9

                            contentItem: Text {
                                leftPadding: 8
                                rightPadding: interfaceSelector.indicator.width + 12
                                text: root.optionText(interfaceCard.selected)
                                color: interfaceSelector.enabled ? "#e9d5ff" : "#667dd3fc"
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideRight
                                font: interfaceSelector.font
                            }

                            background: Rectangle {
                                radius: 5
                                color: "#020a12"
                                border.width: 1
                                border.color: interfaceSelector.activeFocus
                                    ? "#80a78bfa" : "#40a78bfa"
                            }

                            delegate: ItemDelegate {
                                required property var modelData
                                width: interfaceSelector.width
                                enabled: modelData.available === true
                                text: root.optionText(modelData)
                                font: interfaceSelector.font
                            }

                            onActivated: index => {
                                const option = optionRows[index]
                                if (option && option.available === true) {
                                    root.assignInterface(interfaceCard.modelData.id, option.id)
                                }
                            }
                        }

                        Text {
                            width: parent.width
                            text: interfaceCard.selected
                                ? interfaceCard.selected.detail || "" : ""
                            color: "#80c4b5fd"
                            elide: Text.ElideRight
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                        }

                        Text {
                            width: parent.width
                            text: interfaceCard.modelData.note || ""
                            color: "#667dd3fc"
                            wrapMode: Text.Wrap
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                            lineHeight: 1.35
                            lineHeightMode: Text.ProportionalHeight
                        }
                    }
                }
            }

            Rectangle {
                id: speechCard

                width: content.width
                height: speechColumn.implicitHeight + 24
                radius: 9
                color: "#b803101a"
                border.width: 1
                border.color: "#2467e8f9"

                Column {
                    id: speechColumn

                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 12
                    spacing: 7

                    Text {
                        width: parent.width
                        text: "FIXED REALTIME SPEECH"
                        color: "#e6faff"
                        font.family: "JetBrains Mono"
                        font.pixelSize: 10
                        font.letterSpacing: 1.4
                    }

                    Grid {
                        width: parent.width
                        columns: 2
                        columnSpacing: 10
                        rowSpacing: 4

                        Repeater {
                            model: root.hardware && root.hardware.speech ? [
                                "TRANSPORT", root.hardware.speech.transport,
                                "TURN TAKING", root.hardware.speech.turn_taking,
                                "STREAMING ASR", root.hardware.speech.asr,
                                "ASR HARDWARE", root.hardware.speech.asr_device
                                    + " · " + root.hardware.speech.asr_chunk_ms + " ms",
                                "SPEECH OUTPUT", root.hardware.speech.tts
                                    + " · " + root.hardware.speech.tts_device
                            ] : []

                            delegate: Text {
                                required property string modelData
                                required property int index
                                width: (speechColumn.width - 10) / 2
                                text: modelData
                                color: index % 2 === 0 ? "#667dd3fc" : "#b8f7ff"
                                horizontalAlignment: index % 2 === 0
                                    ? Text.AlignLeft : Text.AlignRight
                                elide: Text.ElideRight
                                font.family: "JetBrains Mono"
                                font.pixelSize: 8
                            }
                        }
                    }

                    Text {
                        width: parent.width
                        text: "VOICE"
                        color: "#667dd3fc"
                        font.family: "JetBrains Mono"
                        font.pixelSize: 8
                        font.letterSpacing: 1.0
                    }

                    ComboBox {
                        id: voiceSelector

                        property var optionRows: root.hardware && root.hardware.speech
                            && Array.isArray(root.hardware.speech.voices)
                            ? root.hardware.speech.voices : []

                        width: parent.width
                        model: optionRows
                        textRole: "label"
                        valueRole: "id"
                        currentIndex: root.optionIndex(
                            optionRows,
                            root.hardware && root.hardware.speech
                                ? root.hardware.speech.voice : ""
                        )
                        enabled: root.changing !== "speech-voice"
                        font.family: "JetBrains Mono"
                        font.pixelSize: 9

                        background: Rectangle {
                            radius: 5
                            color: "#020a12"
                            border.width: 1
                            border.color: voiceSelector.activeFocus
                                ? "#8067e8f9" : "#4067e8f9"
                        }

                        onActivated: index => {
                            const voice = optionRows[index]
                            if (voice) {
                                root.assignVoice(voice.id)
                            }
                        }
                    }

                    Text {
                        width: parent.width
                        text: "Speech transport is infrastructure, not a Task model. Only the Pocket character voice is selectable."
                        color: "#667dd3fc"
                        wrapMode: Text.Wrap
                        font.family: "JetBrains Mono"
                        font.pixelSize: 8
                        lineHeight: 1.35
                        lineHeightMode: Text.ProportionalHeight
                    }
                }
            }

            Text {
                width: content.width
                visible: root.errorMessage !== ""
                text: root.errorMessage
                color: "#fda4af"
                wrapMode: Text.Wrap
                font.family: "JetBrains Mono"
                font.pixelSize: 9
            }

            Text {
                width: content.width
                text: "SENSORS ARE READ-ONLY AND LOCAL · RESIDENCY AND MEDIA SELECTIONS USE THE EXISTING HARDWARE API"
                color: "#527dd3fc"
                wrapMode: Text.Wrap
                horizontalAlignment: Text.AlignHCenter
                font.family: "JetBrains Mono"
                font.pixelSize: 8
                font.letterSpacing: 0.6
            }
        }
    }
}
