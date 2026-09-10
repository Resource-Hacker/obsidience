pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../../../components/visual"

Item {
    id: root

    readonly property string apiBase: "http://127.0.0.1:8765"
    property var hardware: null
    property bool loading: false
    property string changing: ""
    property string errorMessage: ""
    property string notice: ""
    readonly property bool busy: loading || changing !== ""
    readonly property var gpuSlots: hardware ? hardware.slots.filter(slot => slot.kind === "gpu") : []
    readonly property var interfaces: hardware ? hardware.interfaces : []
    readonly property var voices: hardware ? hardware.speech.voices : []

    function applySnapshot(payload) {
        if (!payload || !Array.isArray(payload.slots) || !Array.isArray(payload.interfaces)
                || !payload.speech || !Array.isArray(payload.speech.voices)
                || typeof payload.speech.voice !== "string") throw new Error("Invalid settings")
        hardware = payload
    }

    function responseError(xhr) {
        try {
            const payload = JSON.parse(xhr.responseText || "{}")
            if (typeof payload.detail === "string") return payload.detail.slice(0, 500)
        } catch (error) {}
        return "Settings could not be updated (HTTP " + xhr.status + ")."
    }

    function request(method, path, body, onSuccess, onFailure) {
        const xhr = new XMLHttpRequest()
        xhr.open(method, apiBase + path)
        if (body !== null) xhr.setRequestHeader("content-type", "application/json")
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE || !root) return
            if (xhr.status < 200 || xhr.status >= 300) {
                onFailure(root.responseError(xhr))
                return
            }
            try { onSuccess(JSON.parse(xhr.responseText)) }
            catch (error) { onFailure("Settings could not be read. Reload to check the saved values.") }
        }
        xhr.send(body === null ? null : JSON.stringify(body))
    }

    function refresh() {
        if (busy) return
        loading = true
        request("GET", "/api/hardware", null, function(payload) {
            root.applySnapshot(payload)
            root.loading = false
            root.errorMessage = ""
        }, function(message) {
            root.loading = false
            root.errorMessage = message
        })
    }

    function optionIndex(options, selected) {
        return options ? Array.from(options).findIndex(option => option.id === selected) : -1
    }

    function optionText(option) {
        return String(option.label || option.id)
            + (option.linked === true ? " · Both GPUs" : "")
            + (option.available === false ? " · Unavailable" : "")
    }

    function optionRows(options) {
        return Array.from(options || []).map(option =>
            Object.assign({}, option, {"displayLabel": optionText(option)}))
    }

    function assignSlot(device, component) {
        const slot = gpuSlots.find(row => row.id === device)
        const option = slot && slot.options.find(row => row.id === component)
        if (busy || !slot || !option || option.available !== true
                || slot.selected === component || hardware.switching === true) return
        changing = device
        errorMessage = ""
        notice = ""
        request("PATCH", "/api/hardware", {"device": device, "component": component}, function(payload) {
            root.applySnapshot(payload)
            root.changing = ""
            root.notice = "Model residency saved."
        }, function(message) {
            root.changing = ""
            root.errorMessage = message
        })
    }

    function assignInterface(hardwareInterface, selection) {
        const row = interfaces.find(item => item.id === hardwareInterface)
        const option = row && row.options.find(item => item.id === selection)
        if (busy || !row || !option || option.available !== true || row.selected === selection) return
        changing = hardwareInterface
        errorMessage = ""
        notice = ""
        request("PATCH", "/api/hardware/interfaces", {"interface": hardwareInterface, "selection": selection}, function(payload) {
            root.applySnapshot(payload)
            root.changing = ""
            root.notice = "Device selection saved."
        }, function(message) {
            root.changing = ""
            root.errorMessage = message
        })
    }

    function assignVoice(voice) {
        if (busy || !hardware || hardware.speech.voice === voice
                || !voices.some(option => option.id === voice && option.available !== false)) return
        changing = "speech-voice"
        errorMessage = ""
        notice = ""
        request("PATCH", "/api/hardware/voice", {"voice": voice}, function() {
            root.changing = ""
            root.notice = "Voice saved."
            root.refresh()
        }, function(message) {
            root.changing = ""
            root.errorMessage = message
        })
    }

    Component.onCompleted: refresh()
    onVisibleChanged: { if (visible) refresh() }

    component Copy: Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: "#97aebb"
        font.pixelSize: 13
        lineHeight: 1.2
    }
    component Heading: Copy {
        color: "#e0f0f5"
        font.pixelSize: 16
        font.weight: Font.DemiBold
    }
    component Choice: GlowComboBox {
        id: choice
        Layout.fillWidth: true
        textRole: "displayLabel"
        valueRole: "id"
        textPixelSize: 13
        textOpacity: 0.95
        implicitHeight: 36
        delegate: ItemDelegate {
            id: choiceOption
            required property var modelData
            width: choice.width
            enabled: modelData.available !== false
            text: modelData.displayLabel
            font.pixelSize: 13
            contentItem: Text {
                text: choiceOption.text
                textFormat: Text.PlainText
                elide: Text.ElideRight
                color: choiceOption.enabled ? "#d9eef5" : "#69818e"
                font.pixelSize: 13
                verticalAlignment: Text.AlignVCenter
            }
        }
    }
    component Divider: Rectangle {
        Layout.fillWidth: true
        Layout.preferredHeight: 1
        Layout.topMargin: 4
        Layout.bottomMargin: 4
        color: "#28404e"
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 10
        RowLayout {
            Layout.fillWidth: true
            Heading { text: "AI & Voice"; font.pixelSize: 18 }
            GlowButton {
                objectName: "ai-voice-reload"
                text: "Reload"
                uppercase: false; textPixelSize: 12; textLetterSpacing: 0
                implicitHeight: 32
                enabled: !root.busy
                onClicked: root.refresh()
            }
        }
        Copy { visible: root.busy; text: root.loading ? "Loading settings…" : "Applying selection…" }
        Copy { visible: !!root.errorMessage; text: root.errorMessage; color: "#fda4af" }
        Copy { visible: !!root.notice; text: root.notice; color: "#86efac" }
        ScrollView {
            id: settingsScroll
            objectName: "ai-voice-scroll"
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true
            ColumnLayout {
                width: settingsScroll.availableWidth
                visible: !!root.hardware
                spacing: 10
                Heading { text: "Model residency" }
                Copy { text: "Idle defaults return when Tasks release the hardware." }
                Repeater {
                    model: root.gpuSlots
                    delegate: ColumnLayout {
                        id: slotRow
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 5
                        Copy { text: slotRow.modelData.label; color: "#d9eef5" }
                        Choice {
                            objectName: "ai-slot-" + slotRow.modelData.id
                            model: root.optionRows(slotRow.modelData.options)
                            currentIndex: root.optionIndex(slotRow.modelData.options, slotRow.modelData.selected)
                            enabled: !root.busy && root.hardware.switching !== true
                            onActivated: index => {
                                root.assignSlot(slotRow.modelData.id, model[index].id)
                                currentIndex = Qt.binding(() => root.optionIndex(slotRow.modelData.options, slotRow.modelData.selected))
                            }
                        }
                    }
                }
                Divider {}
                Heading { text: "Devices" }
                Copy { text: "Audio changes apply next session. System defaults are kept." }
                Repeater {
                    model: root.interfaces
                    delegate: ColumnLayout {
                        id: interfaceRow
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 5
                        Copy { text: interfaceRow.modelData.label; color: "#d9eef5" }
                        Choice {
                            objectName: "ai-interface-" + interfaceRow.modelData.id
                            model: root.optionRows(interfaceRow.modelData.options)
                            currentIndex: root.optionIndex(interfaceRow.modelData.options, interfaceRow.modelData.selected)
                            enabled: !root.busy
                            onActivated: index => {
                                root.assignInterface(interfaceRow.modelData.id, model[index].id)
                                currentIndex = Qt.binding(() => root.optionIndex(interfaceRow.modelData.options, interfaceRow.modelData.selected))
                            }
                        }
                    }
                }
                Divider {}
                Heading { text: "Voice" }
                Choice {
                    objectName: "ai-voice-selection"
                    model: root.optionRows(root.voices)
                    currentIndex: root.hardware ? root.optionIndex(root.voices, root.hardware.speech.voice) : -1
                    enabled: !root.busy
                    onActivated: index => {
                        root.assignVoice(model[index].id)
                        currentIndex = Qt.binding(() => root.hardware ? root.optionIndex(root.voices, root.hardware.speech.voice) : -1)
                    }
                }
                Copy { text: "Pocket character voice for spoken replies." }
            }
        }
    }
}
