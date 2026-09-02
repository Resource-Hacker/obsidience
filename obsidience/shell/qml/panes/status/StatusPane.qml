pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls

Item {
    id: root

    readonly property string apiBase: "http://127.0.0.1:8765"
    property var status: null
    property var models: []
    property var benchmarkResults: ({})
    property string benchmarkingId: ""
    property string statusError: ""
    property string modelsError: ""
    property string actionError: ""
    property var configuringModel: null
    property var configAllowedDevices: []
    property int configContextTokens: 0
    property int configMaxOutputTokens: 0
    property real configGpuUtilization: 0
    property int configMaxSequences: 1
    property bool savingModel: false

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
        request("GET", "/api/status", null, function(payload) {
            root.status = payload
            root.statusError = ""
        }, function(message) {
            root.statusError = message
        })
        request("GET", "/api/models", null, function(payload) {
            const rows = payload && Array.isArray(payload.models)
                ? payload.models : []
            root.models = rows.filter(model => model && model.task_capable === true)
            root.modelsError = ""
        }, function(message) {
            root.modelsError = message
        })
    }

    function gpuLabel(device) {
        if (device === "rtx4080") {
            return "RTX 4080 SUPER"
        }
        if (device === "rtx4000") {
            return "RTX 4000 Ada"
        }
        return String(device)
    }

    function layoutLabel(layout) {
        return Array.isArray(layout)
            ? layout.map(device => gpuLabel(device)).join(" + ") : ""
    }

    function validLayouts(model) {
        const allowed = Array.isArray(model.allowed_devices)
            ? model.allowed_devices : []
        const layouts = Array.isArray(model.device_sets) ? model.device_sets : []
        return layouts.filter(layout => Array.isArray(layout)
            && layout.every(device => allowed.indexOf(device) >= 0))
    }

    function benchmarkDevices(model) {
        if (Array.isArray(model.active_devices) && model.active_devices.length) {
            return model.active_devices
        }
        if (Array.isArray(model.assigned_devices) && model.assigned_devices.length) {
            return model.assigned_devices
        }
        const layouts = validLayouts(model)
        return layouts.length ? layouts[0] : []
    }

    function resultFor(model) {
        const result = benchmarkResults[model.id] || model.last_benchmark || null
        return result && result.contract ? result : null
    }

    function configure(model) {
        configuringModel = model
        configAllowedDevices = Array.isArray(model.allowed_devices)
            ? model.allowed_devices.slice() : []
        configContextTokens = Number(model.context_tokens || 0)
        configMaxOutputTokens = Number(model.max_output_tokens || 0)
        configGpuUtilization = Number(model.gpu_memory_utilization || 0)
        configMaxSequences = Number(model.max_num_seqs || 1)
        actionError = ""
    }

    function canRemoveDevice(device) {
        if (!configuringModel || configAllowedDevices.indexOf(device) < 0) {
            return false
        }
        const after = configAllowedDevices.filter(candidate => candidate !== device)
        const layouts = Array.isArray(configuringModel.device_sets)
            ? configuringModel.device_sets : []
        return !layouts.some(layout => Array.isArray(layout)
            && layout.every(candidate => after.indexOf(candidate) >= 0))
    }

    function toggleAllowedDevice(device) {
        const selected = configAllowedDevices.indexOf(device) >= 0
        if (selected && canRemoveDevice(device)) {
            return
        }
        configAllowedDevices = selected
            ? configAllowedDevices.filter(candidate => candidate !== device)
            : configAllowedDevices.concat([device])
    }

    function saveConfiguration() {
        if (!configuringModel || savingModel) {
            return
        }
        savingModel = true
        actionError = ""
        const modelId = configuringModel.id
        request(
            "PATCH",
            "/api/models/" + encodeURIComponent(modelId),
            {
                "allowed_devices": configAllowedDevices,
                "context_tokens": configContextTokens,
                "max_output_tokens": configMaxOutputTokens,
                "gpu_memory_utilization": configGpuUtilization,
                "max_num_seqs": configMaxSequences
            },
            function(payload) {
                root.savingModel = false
                root.configuringModel = null
                root.actionError = "Model settings saved; Hardware defaults were reconciled."
                root.refresh()
            },
            function(message) {
                root.savingModel = false
                root.actionError = message
            }
        )
    }

    function benchmark(model) {
        if (benchmarkingId || model.installed !== true) {
            return
        }
        const devices = benchmarkDevices(model)
        if (!devices.length) {
            actionError = "No valid enabled GPU layout for " + model.label + "."
            return
        }
        benchmarkingId = model.id
        actionError = ""
        request(
            "POST",
            "/api/models/" + encodeURIComponent(model.id) + "/benchmark",
            {"devices": devices},
            function(payload) {
                const next = {}
                for (const key of Object.keys(root.benchmarkResults)) {
                    next[key] = root.benchmarkResults[key]
                }
                next[model.id] = payload
                root.benchmarkResults = next
                root.benchmarkingId = ""
                root.refresh()
            },
            function(message) {
                root.actionError = message
                root.benchmarkingId = ""
            }
        )
    }

    Component.onCompleted: refresh()
    onVisibleChanged: {
        if (visible) {
            refresh()
        }
    }

    Timer {
        interval: 10000
        repeat: true
        running: root.visible
        onTriggered: root.refresh()
    }

    Flickable {
        id: scroll

        anchors.fill: parent
        clip: true
        contentWidth: width
        contentHeight: content.implicitHeight + 28
        boundsBehavior: Flickable.StopAtBounds

        ScrollBar.vertical: ScrollBar {}

        Column {
            id: content

            x: 14
            y: 14
            width: Math.max(220, scroll.width - 28)
            spacing: 10

            Rectangle {
                width: content.width
                height: headerColumn.implicitHeight + 20
                radius: 8
                color: "#17071119"
                border.width: 1
                border.color: "#2467e8f9"

                Column {
                    id: headerColumn

                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.top: parent.top
                    anchors.margins: 10
                    spacing: 5

                    Text {
                        width: parent.width
                        text: "TASK REASONING MODELS"
                        color: "#e6faff"
                        font.family: "JetBrains Mono"
                        font.pixelSize: 10
                        font.letterSpacing: 1.6
                    }

                    Text {
                        width: parent.width
                        text: "Selected per Task with that Task's reasoning effort. Fixed speech transport remains under Hardware."
                        color: "#7367e8f9"
                        wrapMode: Text.Wrap
                        font.family: "JetBrains Mono"
                        font.pixelSize: 9
                        lineHeight: 1.35
                        lineHeightMode: Text.ProportionalHeight
                    }
                }
            }

            Text {
                width: content.width
                visible: root.modelsError !== "" && root.models.length === 0
                text: "MODELS SERVICE UNAVAILABLE · " + root.modelsError
                color: "#fda4af"
                wrapMode: Text.Wrap
                font.family: "JetBrains Mono"
                font.pixelSize: 9
            }

            Repeater {
                model: root.models

                delegate: Rectangle {
                    id: modelCard

                    required property var modelData
                    readonly property var comparison: root.resultFor(modelData)
                    readonly property var layouts: root.validLayouts(modelData)
                    readonly property color stateColor: modelData.loaded === true
                        ? "#6ee7b7" : modelData.installed === true
                            ? "#7367e8f9" : "#fda4af"

                    width: content.width
                    height: cardColumn.implicitHeight + 22
                    radius: 8
                    color: modelData.loaded === true ? "#12064a3b"
                        : modelData.installed === true ? "#12071119" : "#16a11828"
                    border.width: 1
                    border.color: modelData.loaded === true ? "#406ee7b7"
                        : modelData.installed === true ? "#2467e8f9" : "#40fda4af"

                    Column {
                        id: cardColumn

                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 11
                        spacing: 7

                        Item {
                            width: parent.width
                            height: Math.max(modelName.implicitHeight, modelState.implicitHeight)

                            Text {
                                id: modelName

                                anchors.left: parent.left
                                anchors.right: modelState.left
                                anchors.rightMargin: 10
                                text: modelCard.modelData.label || modelCard.modelData.id
                                color: "#e6faff"
                                elide: Text.ElideRight
                                font.family: "JetBrains Mono"
                                font.pixelSize: 11
                                font.weight: Font.Medium
                            }

                            Text {
                                id: modelState

                                anchors.right: parent.right
                                text: modelCard.modelData.loaded === true ? "● LOADED"
                                    : modelCard.modelData.installed === true
                                        ? String(modelCard.modelData.state || "INSTALLED").toUpperCase()
                                        : "NOT INSTALLED"
                                color: modelCard.stateColor
                                font.family: "JetBrains Mono"
                                font.pixelSize: 8
                                font.letterSpacing: 0.8
                            }
                        }

                        Text {
                            width: parent.width
                            text: modelCard.modelData.purpose || ""
                            color: "#807dd3fc"
                            wrapMode: Text.Wrap
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                            lineHeight: 1.35
                            lineHeightMode: Text.ProportionalHeight
                        }

                        Grid {
                            width: parent.width
                            columns: 2
                            columnSpacing: 12
                            rowSpacing: 4

                            Repeater {
                                model: [
                                    "QUANTIZATION",
                                    String(modelCard.modelData.quantization || "—"),
                                    "CONTEXT",
                                    Math.round(Number(modelCard.modelData.context_tokens || 0) / 1024) + "K",
                                    "WORKS WITH",
                                    modelCard.layouts.length
                                        ? modelCard.layouts.map(layout => root.layoutLabel(layout)).join(" · ")
                                        : "NO ENABLED LAYOUT"
                                ]

                                delegate: Text {
                                    required property string modelData
                                    required property int index
                                    width: (cardColumn.width - 12) / 2
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
                            text: Array.isArray(modelCard.modelData.capabilities)
                                ? modelCard.modelData.capabilities.map(value => String(value).toUpperCase()).join(" · ")
                                : ""
                            color: "#99c4b5fd"
                            elide: Text.ElideRight
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                            font.letterSpacing: 0.8
                        }

                        Row {
                            width: parent.width
                            spacing: 7

                            Repeater {
                                model: [
                                    {
                                        "label": "TTFT",
                                        "value": modelCard.comparison && modelCard.comparison.ttft_ms !== undefined
                                            ? Number(modelCard.comparison.ttft_ms).toFixed(1) + " ms"
                                            : "Not recorded"
                                    },
                                    {
                                        "label": "THROUGHPUT",
                                        "value": modelCard.comparison && modelCard.comparison.tokens_per_second !== undefined
                                            ? Number(modelCard.comparison.tokens_per_second).toFixed(2) + " tok/s"
                                            : "Not recorded"
                                    }
                                ]

                                delegate: Rectangle {
                                    required property var modelData
                                    width: (cardColumn.width - 7) / 2
                                    height: 46
                                    radius: 6
                                    color: "#11064a3b"
                                    border.width: 1
                                    border.color: "#246ee7b7"

                                    Column {
                                        anchors.left: parent.left
                                        anchors.right: parent.right
                                        anchors.verticalCenter: parent.verticalCenter
                                        anchors.margins: 8
                                        spacing: 3

                                        Text {
                                            width: parent.width
                                            text: parent.parent.modelData.label
                                            color: "#666ee7b7"
                                            font.family: "JetBrains Mono"
                                            font.pixelSize: 7
                                            font.letterSpacing: 1.0
                                        }

                                        Text {
                                            width: parent.width
                                            text: parent.parent.modelData.value
                                            color: "#b86ee7b7"
                                            elide: Text.ElideRight
                                            font.family: "JetBrains Mono"
                                            font.pixelSize: 9
                                        }
                                    }
                                }
                            }
                        }

                        Text {
                            width: parent.width
                            text: "SOURCE · " + String(modelCard.modelData.source_manifest || "unregistered")
                            color: "#527dd3fc"
                            elide: Text.ElideMiddle
                            font.family: "JetBrains Mono"
                            font.pixelSize: 7
                        }

                        Row {
                            spacing: 8

                            Rectangle {
                                id: benchmarkButton

                                width: 112
                                height: 27
                                radius: 5
                                enabled: modelCard.modelData.installed === true
                                    && root.benchmarkingId === ""
                                color: benchmarkMouse.containsMouse && enabled
                                    ? "#2634d399" : "#12071119"
                                border.width: 1
                                border.color: enabled ? "#526ee7b7" : "#2467e8f9"

                                Text {
                                    anchors.centerIn: parent
                                    text: root.benchmarkingId === modelCard.modelData.id
                                        ? "TESTING…" : "BENCHMARK"
                                    color: benchmarkButton.enabled ? "#a76ee7b7" : "#5267e8f9"
                                    font.family: "JetBrains Mono"
                                    font.pixelSize: 8
                                    font.letterSpacing: 1.0
                                }

                                MouseArea {
                                    id: benchmarkMouse

                                    anchors.fill: parent
                                    enabled: benchmarkButton.enabled
                                    hoverEnabled: true
                                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                                    onClicked: root.benchmark(modelCard.modelData)
                                }
                            }

                            Rectangle {
                                id: configureButton

                                width: 104
                                height: 27
                                radius: 5
                                color: configureMouse.containsMouse
                                    ? "#2634d399" : "#12071119"
                                border.width: 1
                                border.color: "#4067e8f9"

                                Text {
                                    anchors.centerIn: parent
                                    text: "CONFIGURE"
                                    color: "#a67dd3fc"
                                    font.family: "JetBrains Mono"
                                    font.pixelSize: 8
                                    font.letterSpacing: 1.0
                                }

                                MouseArea {
                                    id: configureMouse

                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.configure(modelCard.modelData)
                                }
                            }
                        }
                    }
                }
            }

            Text {
                width: content.width
                visible: root.actionError !== ""
                text: root.actionError
                color: "#fda4af"
                wrapMode: Text.Wrap
                font.family: "JetBrains Mono"
                font.pixelSize: 9
            }

            Text {
                width: content.width
                visible: root.status !== null
                text: root.status
                    ? root.status.notes + " ARTICLES · " + root.status.tasks
                        + " TASKS · " + root.status.sources + " SOURCE FILES · "
                        + root.status.source_issues + " SOURCE ISSUES"
                    : ""
                color: root.statusError ? "#fda4af" : "#5267e8f9"
                wrapMode: Text.Wrap
                font.family: "JetBrains Mono"
                font.pixelSize: 8
                font.letterSpacing: 0.6
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        z: 20
        visible: root.configuringModel !== null
        color: "#f5020609"

        Flickable {
            id: configurationScroll

            anchors.fill: parent
            anchors.margins: 14
            clip: true
            contentWidth: width
            contentHeight: configurationColumn.implicitHeight + 24
            boundsBehavior: Flickable.StopAtBounds

            ScrollBar.vertical: ScrollBar {}

            Column {
                id: configurationColumn

                width: configurationScroll.width
                spacing: 12

                Item {
                    width: parent.width
                    height: 34

                    Text {
                        anchors.left: parent.left
                        anchors.right: closeConfiguration.left
                        anchors.rightMargin: 12
                        anchors.verticalCenter: parent.verticalCenter
                        text: root.configuringModel
                            ? root.configuringModel.label : "MODEL SETTINGS"
                        color: "#e6faff"
                        elide: Text.ElideRight
                        font.family: "JetBrains Mono"
                        font.pixelSize: 13
                        font.weight: Font.Medium
                    }

                    Rectangle {
                        id: closeConfiguration

                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        width: 28
                        height: 22
                        radius: 5
                        color: closeConfigurationMouse.containsMouse
                            ? "#2634d399" : "#12071119"
                        border.width: 1
                        border.color: "#4067e8f9"

                        Text {
                            anchors.centerIn: parent
                            text: "×"
                            color: "#9967e8f9"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 11
                        }

                        MouseArea {
                            id: closeConfigurationMouse

                            anchors.fill: parent
                            enabled: !root.savingModel
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.configuringModel = null
                        }
                    }
                }

                Rectangle {
                    width: parent.width
                    height: allowedColumn.implicitHeight + 22
                    radius: 8
                    color: "#17071119"
                    border.width: 1
                    border.color: "#2467e8f9"

                    Column {
                        id: allowedColumn

                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 11
                        spacing: 7

                        Text {
                            width: parent.width
                            text: "ALLOWED GPUS"
                            color: "#a67dd3fc"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 9
                            font.letterSpacing: 1.2
                        }

                        Text {
                            width: parent.width
                            text: "Tasks may place this model only on selected devices. Hardware defaults are configured separately."
                            color: "#667dd3fc"
                            wrapMode: Text.Wrap
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                            lineHeight: 1.35
                            lineHeightMode: Text.ProportionalHeight
                        }

                        Repeater {
                            model: root.configuringModel
                                && Array.isArray(root.configuringModel.supported_devices)
                                ? root.configuringModel.supported_devices : []

                            delegate: Rectangle {
                                id: deviceChoice

                                required property string modelData
                                readonly property bool selected: root.configAllowedDevices.indexOf(modelData) >= 0
                                readonly property bool locked: selected
                                    && root.canRemoveDevice(modelData)

                                width: allowedColumn.width
                                height: 32
                                radius: 6
                                color: deviceChoiceMouse.containsMouse && !locked
                                    ? "#2634d399" : "#12071119"
                                border.width: 1
                                border.color: selected ? "#6767e8f9" : "#2467e8f9"

                                Text {
                                    anchors.left: parent.left
                                    anchors.leftMargin: 10
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: (deviceChoice.selected ? "● " : "○ ")
                                        + root.gpuLabel(deviceChoice.modelData)
                                    color: deviceChoice.locked ? "#667dd3fc" : "#cffafe"
                                    font.family: "JetBrains Mono"
                                    font.pixelSize: 9
                                }

                                Text {
                                    anchors.right: parent.right
                                    anchors.rightMargin: 10
                                    anchors.verticalCenter: parent.verticalCenter
                                    visible: deviceChoice.locked
                                    text: "REQUIRED"
                                    color: "#99fde68a"
                                    font.family: "JetBrains Mono"
                                    font.pixelSize: 7
                                    font.letterSpacing: 0.8
                                }

                                MouseArea {
                                    id: deviceChoiceMouse

                                    anchors.fill: parent
                                    enabled: !deviceChoice.locked && !root.savingModel
                                    hoverEnabled: true
                                    cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                                    onClicked: root.toggleAllowedDevice(deviceChoice.modelData)
                                }
                            }
                        }
                    }
                }

                Rectangle {
                    width: parent.width
                    height: profileGrid.childrenRect.height + 36
                    radius: 8
                    color: "#140c0a1d"
                    border.width: 1
                    border.color: "#24a78bfa"

                    Grid {
                        id: profileGrid

                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.margins: 12
                        columns: width >= 520 ? 2 : 1
                        columnSpacing: 10
                        rowSpacing: 10

                        Repeater {
                            model: [
                                {"label": "CONTEXT", "kind": "context"},
                                {"label": "MAX OUTPUT", "kind": "output"},
                                {"label": "GPU UTILIZATION", "kind": "utilization"},
                                {"label": "MAX SEQUENCES", "kind": "sequences"}
                            ]

                            delegate: Column {
                                id: profileField

                                required property var modelData
                                width: profileGrid.columns === 1
                                    ? profileGrid.width
                                    : (profileGrid.width - profileGrid.columnSpacing) / 2
                                spacing: 5

                                Text {
                                    width: parent.width
                                    text: profileField.modelData.label
                                    color: "#80c4b5fd"
                                    font.family: "JetBrains Mono"
                                    font.pixelSize: 8
                                    font.letterSpacing: 1.0
                                }

                                TextField {
                                    width: parent.width
                                    height: 32
                                    enabled: !root.savingModel
                                    text: profileField.modelData.kind === "context"
                                        ? String(root.configContextTokens)
                                        : profileField.modelData.kind === "output"
                                            ? String(root.configMaxOutputTokens)
                                            : profileField.modelData.kind === "utilization"
                                                ? String(root.configGpuUtilization)
                                                : String(root.configMaxSequences)
                                    color: "#cffafe"
                                    selectionColor: "#8067e8f9"
                                    selectedTextColor: "#020609"
                                    font.family: "JetBrains Mono"
                                    font.pixelSize: 9

                                    background: Rectangle {
                                        radius: 5
                                        color: "#020a12"
                                        border.width: 1
                                        border.color: parent.activeFocus
                                            ? "#80a78bfa" : "#40a78bfa"
                                    }

                                    onEditingFinished: {
                                        const value = Number(text)
                                        if (!isFinite(value)) {
                                            return
                                        }
                                        if (profileField.modelData.kind === "context") {
                                            root.configContextTokens = Math.round(value)
                                        } else if (profileField.modelData.kind === "output") {
                                            root.configMaxOutputTokens = Math.round(value)
                                        } else if (profileField.modelData.kind === "utilization") {
                                            root.configGpuUtilization = value
                                        } else {
                                            root.configMaxSequences = Math.round(value)
                                        }
                                    }
                                }
                            }
                        }
                    }
                }

                Text {
                    width: parent.width
                    visible: root.actionError !== ""
                    text: root.actionError
                    color: root.actionError.indexOf("saved") >= 0 ? "#6ee7b7" : "#fda4af"
                    wrapMode: Text.Wrap
                    font.family: "JetBrains Mono"
                    font.pixelSize: 9
                }

                Row {
                    anchors.right: parent.right
                    spacing: 8

                    Rectangle {
                        id: cancelModelButton

                        width: 90
                        height: 30
                        radius: 5
                        enabled: !root.savingModel
                        color: cancelModelMouse.containsMouse && enabled
                            ? "#2634d399" : "#12071119"
                        border.width: 1
                        border.color: "#4067e8f9"

                        Text {
                            anchors.centerIn: parent
                            text: "CANCEL"
                            color: "#a67dd3fc"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                            font.letterSpacing: 1.0
                        }

                        MouseArea {
                            id: cancelModelMouse

                            anchors.fill: parent
                            enabled: cancelModelButton.enabled
                            hoverEnabled: true
                            cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                            onClicked: root.configuringModel = null
                        }
                    }

                    Rectangle {
                        id: saveModelButton

                        width: 112
                        height: 30
                        radius: 5
                        enabled: !root.savingModel
                        color: saveModelMouse.containsMouse && enabled
                            ? "#2634d399" : "#12071119"
                        border.width: 1
                        border.color: enabled ? "#526ee7b7" : "#2467e8f9"

                        Text {
                            anchors.centerIn: parent
                            text: root.savingModel ? "SAVING…" : "SAVE MODEL"
                            color: saveModelButton.enabled ? "#a76ee7b7" : "#5267e8f9"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                            font.letterSpacing: 1.0
                        }

                        MouseArea {
                            id: saveModelMouse

                            anchors.fill: parent
                            enabled: saveModelButton.enabled
                            hoverEnabled: true
                            cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                            onClicked: root.saveConfiguration()
                        }
                    }
                }
            }
        }
    }
}
