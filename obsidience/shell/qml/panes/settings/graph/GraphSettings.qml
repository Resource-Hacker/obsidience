pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtWebSockets

Item {
    id: root

    readonly property string apiBase: "http://127.0.0.1:8765"
    readonly property string commandSchema: "obsidience.shell.command.v1"
    property var graphOptions: []
    property int selectedIndex: 0
    property var fields: []
    property var groups: []
    property string activeGroup: ""
    property var tuning: ({})
    property var savedTuning: ({})
    property var defaultTuning: ({})
    property var profiles: []
    property string activeProfile: "Default"
    property var displaySurfaces: []
    property string selectedDisplaySurfaceId: "samsung"
    property bool stateReady: false
    property bool savePending: false
    property bool resetArmed: false
    property bool newProfileVisible: false
    property string errorMessage: ""

    readonly property string selectedGraphId: graphOptions.length
        ? String(graphOptions[Math.max(0, Math.min(selectedIndex,
            graphOptions.length - 1))].graphId || "main") : "main"
    readonly property var profileOptions: profiles.concat(["New profile…"])
    readonly property bool dirty: stateReady
        && JSON.stringify(tuning) !== JSON.stringify(savedTuning)

    function responseError(request, fallback) {
        const raw = request.responseText || ""
        try {
            const parsed = JSON.parse(raw)
            if (parsed && typeof parsed.detail === "string" && parsed.detail) {
                return parsed.detail
            }
        } catch (error) {
        }
        return raw || fallback + " (" + request.status + ")"
    }

    function graphId(group) {
        const role = String(group.role || group.id || "").toLowerCase()
        if (role === "executive") return "main"
        if (role === "library") return "library"
        return String(group.title || group.id || role)
    }

    function graphLabel(group) {
        const title = String(group.title || group.id || "Graph")
        const role = String(group.role || group.id || "").toLowerCase()
        if (role === "library") return title
        const subtitle = String(group.subtitle || group.role || "")
        return subtitle && subtitle.toLowerCase() !== title.toLowerCase()
            ? title + " (" + subtitle + ")" : title
    }

    function refreshGraphs() {
        const current = selectedGraphId
        const xhr = new XMLHttpRequest()
        xhr.open("GET", apiBase + "/api/graph")
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE) return
            if (xhr.status < 200 || xhr.status >= 300) {
                root.errorMessage = root.responseError(xhr, "Graph inventory failed")
                return
            }
            try {
                const payload = JSON.parse(xhr.responseText)
                const navigation = payload && payload.navigation
                const source = navigation && Array.isArray(navigation.groups)
                    ? navigation.groups : []
                const roleOrder = {
                    "executive": 0,
                    "guardian": 1,
                    "curator": 2,
                    "researcher": 3,
                    "library": 5
                }
                root.graphOptions = source.map(group => ({
                    "graphId": root.graphId(group),
                    "label": root.graphLabel(group),
                    "order": roleOrder[String(group.role || group.id || "").toLowerCase()] ?? 4
                })).sort((left, right) => left.order - right.order
                    || left.label.localeCompare(right.label))
                const restored = root.graphOptions.findIndex(
                    option => option.graphId === current
                )
                root.selectedIndex = restored >= 0 ? restored : 0
                root.errorMessage = ""
                root.requestState()
            } catch (error) {
                root.errorMessage = "Obsidience returned invalid graph navigation."
            }
        }
        xhr.send()
    }

    function send(type, extra) {
        if (shellSocket.status !== WebSocket.Open) return false
        shellSocket.sendTextMessage(JSON.stringify(Object.assign({
            "schema": commandSchema,
            "type": type,
            "graph_id": selectedGraphId
        }, extra || {})))
        return true
    }

    function requestState() {
        stateReady = false
        send("graph.display.request")
        if (!send("graph.state.request")) {
            errorMessage = "Waiting for the graph renderer…"
        }
    }

    function applyState(message) {
        if (!message || message.type !== "graph.state"
                || message.graph_id !== selectedGraphId
                || !message.tuning || !message.default_tuning
                || !Array.isArray(message.fields)
                || !Array.isArray(message.profiles)
                || typeof message.profile !== "string") {
            return
        }
        tuning = Object.assign({}, message.tuning)
        savedTuning = Object.assign({}, message.tuning)
        defaultTuning = Object.assign({}, message.default_tuning)
        fields = message.fields
        profiles = message.profiles.slice()
        activeProfile = message.profile
        savePending = false
        const nextGroups = []
        for (const field of fields) {
            const group = String(field.group || "Other")
            if (!nextGroups.includes(group)) nextGroups.push(group)
        }
        groups = ["Display"].concat(nextGroups)
        if (!groups.includes(activeGroup)) {
            activeGroup = groups.length ? groups[0] : ""
        }
        stateReady = true
        errorMessage = ""
    }

    function applyDisplayState(message) {
        if (!message || message.type !== "graph.display.state"
                || typeof message.selected_surface_id !== "string"
                || !Array.isArray(message.surfaces)) {
            return
        }
        const options = []
        for (const surface of message.surfaces) {
            if (surface && typeof surface.id === "string"
                    && typeof surface.label === "string") {
                options.push({"id": surface.id, "label": surface.label})
            }
        }
        if (!options.some(surface => surface.id === message.selected_surface_id)) {
            return
        }
        displaySurfaces = options
        selectedDisplaySurfaceId = message.selected_surface_id
    }

    function selectDisplaySurface(index) {
        if (index < 0 || index >= displaySurfaces.length) return
        const surfaceId = String(displaySurfaces[index].id)
        if (surfaceId === selectedDisplaySurfaceId) return
        send("graph.display.select", {"surface_id": surfaceId})
    }

    function updateField(field, value) {
        if (!stateReady || !field || typeof field.key !== "string") return
        resetArmed = false
        const nextValue = Math.min(
            Number(field.max), Math.max(Number(field.min), Number(value))
        )
        tuning = Object.assign({}, tuning, {[field.key]: nextValue})
        send("graph.tuning.preview", {"tuning": tuning})
    }

    function selectProfile(profile) {
        newProfileVisible = false
        resetArmed = false
        if (profile !== activeProfile
                && send("graph.profile.select", {"profile": profile})) {
            stateReady = false
        }
    }

    function createProfile() {
        const profile = newProfileInput.text.trim().slice(0, 24)
        if (!profile || profile === "__new__") return
        newProfileVisible = false
        resetArmed = false
        if (send("graph.profile.create", {"profile": profile, "tuning": tuning})) {
            stateReady = false
            newProfileInput.text = ""
        }
    }

    function discard() {
        resetArmed = false
        tuning = Object.assign({}, savedTuning)
        send("graph.tuning.preview", {"tuning": tuning})
    }

    function reset() {
        resetArmed = false
        tuning = Object.assign({}, defaultTuning)
        send("graph.tuning.preview", {"tuning": tuning})
    }

    function save() {
        resetArmed = false
        if (send("graph.tuning.save", {"tuning": tuning})) {
            savePending = true
            stateReady = false
        }
    }

    function applySelection(message) {
        if (!message || message.type !== "graph.selection"
                || typeof message.graph_id !== "string") return
        const index = graphOptions.findIndex(
            option => option.graphId === message.graph_id
        )
        if (index < 0 || index === selectedIndex) return
        selectedIndex = index
        resetArmed = false
        newProfileVisible = false
        requestState()
    }

    function fieldValue(field) {
        return Number(tuning[field.key] ?? 0)
    }

    function valueText(field) {
        const value = fieldValue(field)
        const step = Number(field.step)
        const digits = step < 0.01 ? 3 : step < 1 ? 2 : 0
        return value.toFixed(digits)
            .replace(/\.0+$/, "").replace(/(\.\d*?)0+$/, "$1")
    }

    Component.onCompleted: refreshGraphs()
    onVisibleChanged: {
        if (visible) refreshGraphs()
    }

    WebSocket {
        id: shellSocket
        url: "ws://127.0.0.1:8768"
        requestedSubprotocols: ["obsidience.shell.v1"]
        active: true
        onStatusChanged: function() {
            if (status === WebSocket.Open) root.requestState()
        }
        onTextMessageReceived: message => {
            if (typeof message !== "string" || message.length > 65536) return
            try {
                const event = JSON.parse(message)
                if (event.schema === "obsidience.shell.event.v1") {
                    root.applySelection(event)
                    root.applyState(event)
                    root.applyDisplayState(event)
                }
            } catch (error) {
            }
        }
    }

    Timer {
        interval: 1200
        repeat: true
        running: root.visible && !root.stateReady
        onTriggered: root.requestState()
    }

    Column {
        id: header
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 12
        spacing: 5

        Row {
            id: selectors
            width: parent.width
            height: 43
            spacing: 8

            Item {
                width: selectors.width - selectors.spacing - 128
                height: parent.height

                Text {
                    anchors.left: parent.left
                    anchors.top: parent.top
                    text: "GRAPH"
                    color: "#9967e8f9"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 8
                    font.letterSpacing: 1.1
                }

                ComboBox {
                    id: graphSelector
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: 29
                    model: root.graphOptions
                    textRole: "label"
                    currentIndex: root.selectedIndex
                    displayText: root.graphOptions.length
                        ? String(root.graphOptions[Math.max(0, Math.min(
                            root.selectedIndex, root.graphOptions.length - 1
                        ))].label || "") : "GRAPH…"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 9
                    onActivated: index => {
                        root.selectedIndex = index
                        root.resetArmed = false
                        root.newProfileVisible = false
                        root.requestState()
                    }
                    background: Rectangle {
                        radius: 4
                        color: "#061019"
                        border.width: 1
                        border.color: "#4067e8f9"
                    }
                    contentItem: Text {
                        leftPadding: 8
                        rightPadding: graphSelector.indicator.width + 9
                        text: graphSelector.displayText.toUpperCase()
                        color: "#cffafe"
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                        font: graphSelector.font
                    }
                }
            }

            Item {
                width: 128
                height: parent.height

                Text {
                    anchors.left: parent.left
                    anchors.top: parent.top
                    text: "PROFILE"
                    color: "#9967e8f9"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 8
                    font.letterSpacing: 1.1
                }

                ComboBox {
                    id: profileSelector
                    anchors.left: parent.left
                    anchors.right: parent.right
                    anchors.bottom: parent.bottom
                    height: 29
                    model: root.profileOptions
                    currentIndex: Math.max(0, root.profiles.indexOf(root.activeProfile))
                    displayText: root.activeProfile || "Default"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 9
                    onActivated: index => {
                        if (index >= root.profiles.length) {
                            root.newProfileVisible = true
                            newProfileInput.forceActiveFocus()
                        } else {
                            root.selectProfile(String(root.profiles[index]))
                        }
                    }
                    background: Rectangle {
                        radius: 4
                        color: "#061019"
                        border.width: 1
                        border.color: "#4067e8f9"
                    }
                    contentItem: Text {
                        leftPadding: 8
                        rightPadding: profileSelector.indicator.width + 9
                        text: profileSelector.displayText.toUpperCase()
                        color: "#cffafe"
                        verticalAlignment: Text.AlignVCenter
                        elide: Text.ElideRight
                        font: profileSelector.font
                    }
                }
            }
        }

        Row {
            width: parent.width
            height: root.newProfileVisible ? 29 : 0
            visible: root.newProfileVisible
            spacing: 5

            TextField {
                id: newProfileInput
                width: parent.width - addProfileButton.width - parent.spacing
                height: 29
                maximumLength: 24
                placeholderText: "Profile name"
                color: "#cffafe"
                placeholderTextColor: "#667dd3fc"
                font.family: "JetBrains Mono"
                font.pixelSize: 9
                selectByMouse: true
                onAccepted: root.createProfile()
                background: Rectangle {
                    radius: 4
                    color: "#061019"
                    border.width: 1
                    border.color: "#4d67e8f9"
                }
            }

            Rectangle {
                id: addProfileButton
                width: 54
                height: 29
                radius: 4
                color: addProfileMouse.containsMouse ? "#1822d3ee" : "transparent"
                border.width: 1
                border.color: "#4067e8f9"

                Text {
                    anchors.centerIn: parent
                    text: "ADD"
                    color: "#cffafe"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 8
                    font.letterSpacing: 0.9
                }

                MouseArea {
                    id: addProfileMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.createProfile()
                }
            }
        }
    }

    Item {
        id: content
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: header.bottom
        anchors.bottom: footer.top
        anchors.leftMargin: 12
        anchors.rightMargin: 12
        anchors.topMargin: 10
        anchors.bottomMargin: 10

        Rectangle {
            id: sectionRail
            anchors.left: parent.left
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            width: 144
            radius: 5
            color: "#4d02070c"
            border.width: 1
            border.color: "#1867e8f9"

            Flickable {
                anchors.fill: parent
                anchors.margins: 4
                contentWidth: width
                contentHeight: sectionButtons.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds

                Column {
                    id: sectionButtons
                    width: parent.width
                    spacing: 2

                    Repeater {
                        model: root.groups
                        delegate: Rectangle {
                            id: sectionButton
                            required property string modelData
                            width: sectionButtons.width
                            height: 28
                            radius: 4
                            color: modelData === root.activeGroup
                                ? "#2667e8f9"
                                : sectionMouse.containsMouse ? "#1467e8f9" : "transparent"

                            Text {
                                anchors.left: parent.left
                                anchors.right: parent.right
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.leftMargin: 8
                                anchors.rightMargin: 6
                                text: sectionButton.modelData.toUpperCase()
                                color: sectionButton.modelData === root.activeGroup
                                    ? "#cffafe" : "#9967e8f9"
                                elide: Text.ElideRight
                                font.family: "JetBrains Mono"
                                font.pixelSize: 8
                                font.letterSpacing: 1.35
                            }

                            MouseArea {
                                id: sectionMouse
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.activeGroup = sectionButton.modelData
                            }
                        }
                    }
                }
            }
        }

        Flickable {
            id: settingsScroll
            anchors.left: sectionRail.right
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.leftMargin: 12
            clip: true
            contentWidth: width
            contentHeight: settings.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}

            Column {
                id: settings
                width: settingsScroll.width - 5
                spacing: 10

                Item {
                    width: settings.width
                    height: root.activeGroup === "Display" ? 92 : 0
                    visible: root.activeGroup === "Display"

                    Text {
                        anchors.left: parent.left
                        anchors.top: parent.top
                        text: "GRAPH SURFACE"
                        color: "#9967e8f9"
                        font.family: "JetBrains Mono"
                        font.pixelSize: 8
                        font.letterSpacing: 1.05
                    }

                    ComboBox {
                        id: graphSurfaceSelector
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: parent.top
                        anchors.topMargin: 17
                        height: 30
                        model: root.displaySurfaces
                        textRole: "label"
                        currentIndex: Math.max(0, root.displaySurfaces.findIndex(
                            surface => surface.id === root.selectedDisplaySurfaceId
                        ))
                        displayText: root.displaySurfaces.length
                            ? String(root.displaySurfaces[currentIndex].label || "")
                            : "WAITING FOR SURFACES…"
                        font.family: "JetBrains Mono"
                        font.pixelSize: 9
                        onActivated: index => root.selectDisplaySurface(index)
                        background: Rectangle {
                            radius: 4
                            color: "#061019"
                            border.width: 1
                            border.color: "#4067e8f9"
                        }
                        contentItem: Text {
                            leftPadding: 8
                            rightPadding: graphSurfaceSelector.indicator.width + 9
                            text: graphSurfaceSelector.displayText.toUpperCase()
                            color: "#cffafe"
                            verticalAlignment: Text.AlignVCenter
                            elide: Text.ElideRight
                            font: graphSurfaceSelector.font
                        }
                    }

                    Text {
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.top: graphSurfaceSelector.bottom
                        anchors.topMargin: 8
                        text: "The whole graph uses one Surface. Per-Agent placement comes later."
                        color: "#7dd3fc"
                        wrapMode: Text.Wrap
                        font.family: "JetBrains Mono"
                        font.pixelSize: 8
                    }
                }

                Repeater {
                    model: root.fields.filter(field => String(field.group || "Other")
                        === root.activeGroup)
                    delegate: Item {
                        id: fieldRow
                        required property var modelData
                        width: settings.width
                        height: modelData.options ? 49 : modelData.toggle ? 28 : 38

                        Text {
                            id: fieldLabel
                            anchors.left: parent.left
                            anchors.top: parent.top
                            width: parent.width - (fieldRow.modelData.toggle ? 55 : 82)
                            text: String(fieldRow.modelData.label
                                || fieldRow.modelData.key).toUpperCase()
                            color: "#9967e8f9"
                            elide: Text.ElideRight
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                            font.letterSpacing: 1.05

                            HoverHandler { id: labelHover }
                            ToolTip.visible: labelHover.hovered
                            ToolTip.delay: 450
                            ToolTip.text: String(fieldRow.modelData.description || "")
                        }

                        Text {
                            visible: !fieldRow.modelData.options && !fieldRow.modelData.toggle
                            anchors.right: parent.right
                            anchors.top: parent.top
                            text: root.valueText(fieldRow.modelData)
                            color: "#cccffafe"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                        }

                        ComboBox {
                            id: styleControl
                            visible: Array.isArray(fieldRow.modelData.options)
                                && fieldRow.modelData.options.length > 0
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            height: 30
                            model: fieldRow.modelData.options || []
                            currentIndex: Math.max(0, Math.min(model.length - 1,
                                Math.round(root.fieldValue(fieldRow.modelData))))
                            font.family: "JetBrains Mono"
                            font.pixelSize: 9
                            indicator: null
                            onActivated: index => root.updateField(fieldRow.modelData, index)
                            background: Rectangle {
                                radius: 4
                                color: "#061019"
                                border.width: 1
                                border.color: "#4067e8f9"
                            }
                            contentItem: Item {
                                GraphStylePortrait {
                                    id: selectedPortrait
                                    anchors.left: parent.left
                                    anchors.leftMargin: 7
                                    anchors.verticalCenter: parent.verticalCenter
                                    fieldKey: String(fieldRow.modelData.key)
                                    optionIndex: styleControl.currentIndex
                                }
                                Text {
                                    anchors.left: selectedPortrait.right
                                    anchors.right: optionArrow.left
                                    anchors.leftMargin: 8
                                    anchors.rightMargin: 8
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: styleControl.displayText.toUpperCase()
                                    color: "#cffafe"
                                    elide: Text.ElideRight
                                    font.family: styleControl.font.family
                                    font.pixelSize: styleControl.font.pixelSize
                                    font.letterSpacing: 0.7
                                }
                                Text {
                                    id: optionArrow
                                    anchors.right: parent.right
                                    anchors.rightMargin: 8
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "▾"
                                    color: "#8067e8f9"
                                    font.pixelSize: 9
                                }
                            }
                            delegate: ItemDelegate {
                                id: optionDelegate
                                required property var modelData
                                required property int index
                                width: styleControl.width - 2
                                height: 30
                                highlighted: styleControl.highlightedIndex === index
                                contentItem: Item {
                                    GraphStylePortrait {
                                        id: optionPortrait
                                        anchors.left: parent.left
                                        anchors.leftMargin: 6
                                        anchors.verticalCenter: parent.verticalCenter
                                        fieldKey: String(fieldRow.modelData.key)
                                        optionIndex: optionDelegate.index
                                    }
                                    Text {
                                        anchors.left: optionPortrait.right
                                        anchors.right: parent.right
                                        anchors.leftMargin: 8
                                        anchors.rightMargin: 5
                                        anchors.verticalCenter: parent.verticalCenter
                                        text: String(optionDelegate.modelData).toUpperCase()
                                        color: optionDelegate.highlighted
                                            || optionDelegate.index === styleControl.currentIndex
                                            ? "#cffafe" : "#b367e8f9"
                                        elide: Text.ElideRight
                                        font.family: "JetBrains Mono"
                                        font.pixelSize: 9
                                        font.letterSpacing: 0.7
                                    }
                                }
                                background: Rectangle {
                                    radius: 3
                                    color: optionDelegate.highlighted
                                        || optionDelegate.index === styleControl.currentIndex
                                        ? "#2667e8f9" : "transparent"
                                }
                            }
                            popup: Popup {
                                y: styleControl.height + 3
                                width: styleControl.width
                                implicitHeight: Math.min(contentItem.implicitHeight + 2, 210)
                                padding: 1
                                contentItem: ListView {
                                    clip: true
                                    implicitHeight: contentHeight
                                    model: styleControl.popup.visible
                                        ? styleControl.delegateModel : null
                                    currentIndex: styleControl.highlightedIndex
                                    ScrollIndicator.vertical: ScrollIndicator {}
                                }
                                background: Rectangle {
                                    radius: 4
                                    color: "#fa030a10"
                                    border.width: 1
                                    border.color: "#4d67e8f9"
                                }
                            }
                        }

                        Slider {
                            id: numericSlider
                            visible: !fieldRow.modelData.options && !fieldRow.modelData.toggle
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            height: 24
                            from: Number(fieldRow.modelData.min)
                            to: Number(fieldRow.modelData.max)
                            stepSize: Number(fieldRow.modelData.step)
                            value: root.fieldValue(fieldRow.modelData)
                            enabled: !(fieldRow.modelData.key === "sweepSpeed"
                                && Number(root.tuning.automaticSweepSpeed || 0) >= 0.5)
                            opacity: enabled ? 1 : 0.4
                            onMoved: root.updateField(fieldRow.modelData, value)
                            background: Rectangle {
                                x: numericSlider.leftPadding
                                y: numericSlider.topPadding
                                    + numericSlider.availableHeight / 2 - height / 2
                                width: numericSlider.availableWidth
                                height: 2
                                radius: 1
                                color: "#52616b"

                                Rectangle {
                                    width: numericSlider.visualPosition * parent.width
                                    height: parent.height
                                    radius: parent.radius
                                    color: "#67e8f9"
                                }
                            }
                            handle: Rectangle {
                                x: numericSlider.leftPadding + numericSlider.visualPosition
                                    * (numericSlider.availableWidth - width)
                                y: numericSlider.topPadding
                                    + numericSlider.availableHeight / 2 - height / 2
                                width: 14
                                height: 14
                                radius: 7
                                color: "#67e8f9"
                                border.width: 1
                                border.color: "#a5f3fc"
                            }
                        }

                        CheckBox {
                            id: toggleControl
                            visible: Boolean(fieldRow.modelData.toggle)
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            width: 16
                            height: 16
                            checked: root.fieldValue(fieldRow.modelData) >= 0.5
                            onToggled: root.updateField(
                                fieldRow.modelData, checked ? 1 : 0
                            )
                            indicator: Rectangle {
                                width: 14
                                height: 14
                                radius: 2
                                color: toggleControl.checked ? "#67e8f9" : "#061019"
                                border.width: 1
                                border.color: toggleControl.checked
                                    ? "#67e8f9" : "#6667e8f9"

                                Text {
                                    anchors.centerIn: parent
                                    visible: toggleControl.checked
                                    text: "✓"
                                    color: "#031017"
                                    font.pixelSize: 10
                                    font.bold: true
                                }
                            }
                        }
                    }
                }

                Text {
                    width: parent.width
                    visible: !root.stateReady || root.errorMessage !== ""
                    text: root.errorMessage || "Waiting for graph settings…"
                    color: root.errorMessage ? "#fda4af" : "#667dd3fc"
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    font.family: "JetBrains Mono"
                    font.pixelSize: 9
                }
            }
        }
    }

    Row {
        id: footer
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        anchors.margins: 12
        height: root.activeGroup === "Display" ? 0 : 32
        visible: root.activeGroup !== "Display"
        spacing: 8

        Repeater {
            model: [
                {"label": root.savePending ? "SAVING" : root.dirty ? "SAVE *" : "SAVED",
                    "action": "save", "enabled": root.dirty && !root.savePending,
                    "color": "#6ee7b7"},
                {"label": "DISCARD", "action": "discard",
                    "enabled": root.dirty, "color": "#67e8f9"},
                {"label": root.resetArmed ? "CONFIRM" : "RESET", "action": "reset",
                    "enabled": root.stateReady,
                    "color": root.resetArmed ? "#fda4af" : "#67e8f9"},
                {"label": "TEST THINKING", "action": "test",
                    "enabled": root.stateReady, "color": "#c4b5fd"}
            ]

            delegate: Rectangle {
                id: actionButton
                required property var modelData
                width: (footer.width - footer.spacing * 3) / 4
                height: footer.height
                radius: 5
                color: actionMouse.containsMouse && modelData.enabled
                    ? "#2022d3ee" : "#cc030a10"
                opacity: modelData.enabled ? 1 : 0.35
                border.width: 1
                border.color: modelData.color

                Text {
                    anchors.centerIn: parent
                    text: actionButton.modelData.label
                    color: actionButton.modelData.color
                    font.family: "JetBrains Mono"
                    font.pixelSize: 8
                    font.letterSpacing: 0.7
                }
                MouseArea {
                    id: actionMouse
                    anchors.fill: parent
                    enabled: actionButton.modelData.enabled
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        if (actionButton.modelData.action === "save") {
                            root.save()
                        } else if (actionButton.modelData.action === "discard") {
                            root.discard()
                        } else if (actionButton.modelData.action === "reset") {
                            if (root.resetArmed) root.reset()
                            else root.resetArmed = true
                        } else {
                            root.send("graph.thinking.test")
                        }
                    }
                }
            }
        }
    }
}
