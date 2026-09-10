pragma ComponentBehavior: Bound

import QtQuick

Item {
    id: root

    readonly property string apiBase: "http://127.0.0.1:8765"
    property string activeSection: "mouse"
    property var inputState: ({})
    property string errorMessage: ""

    readonly property var mouse: inputState.mouse || ({})
    readonly property var keyboard: inputState.keyboard || ({})

    function display(value, suffix) {
        if (value === null || value === undefined || value === "") {
            return "UNAVAILABLE"
        }
        return String(value) + (suffix || "")
    }

    function refresh() {
        const xhr = new XMLHttpRequest()
        xhr.open("GET", apiBase + "/api/input")
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE || !root) return
            if (xhr.status < 200 || xhr.status >= 300) {
                root.errorMessage = "Input state unavailable (" + xhr.status + ")"
                return
            }
            try {
                root.inputState = JSON.parse(xhr.responseText) || ({})
                root.errorMessage = ""
            } catch (error) {
                root.errorMessage = "Input state was invalid"
            }
        }
        xhr.send()
    }

    Component.onCompleted: refresh()
    onVisibleChanged: if (visible) refresh()

    Column {
        anchors.fill: parent
        anchors.margins: 18
        spacing: 14

        Text {
            text: "INPUT"
            color: "#d9f9fe"
            font.family: "JetBrains Mono"
            font.pixelSize: 11
            font.bold: true
            font.letterSpacing: 1.8
        }

        Row {
            spacing: 8

            Repeater {
                model: [
                    {"id": "mouse", "label": "Mouse"},
                    {"id": "keyboard", "label": "Keyboard"}
                ]

                delegate: Rectangle {
                    id: tab

                    required property var modelData
                    width: 112
                    height: 30
                    radius: 4
                    color: root.activeSection === modelData.id
                        ? "#202f4a18" : tabMouse.containsMouse ? "#141b3214" : "transparent"
                    border.width: 1
                    border.color: root.activeSection === modelData.id
                        ? "#80a3e635" : "#3067e8f9"

                    Text {
                        anchors.centerIn: parent
                        text: String(tab.modelData.label).toUpperCase()
                        color: root.activeSection === tab.modelData.id
                            ? "#e6f9fe" : "#91a9bfd3"
                        font.family: "JetBrains Mono"
                        font.pixelSize: 9
                        font.bold: true
                        font.letterSpacing: 1.2
                    }

                    MouseArea {
                        id: tabMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.activeSection = tab.modelData.id
                    }
                }
            }
        }

        Rectangle {
            width: parent.width
            height: 220
            radius: 6
            color: "#a8061019"
            border.width: 1
            border.color: "#3467e8f9"

            Column {
                anchors.fill: parent
                anchors.margins: 14
                spacing: 10

                Text {
                    width: parent.width
                    text: root.activeSection === "mouse"
                        ? String(root.mouse.name || "DETECTING MOUSE…").toUpperCase()
                        : String(root.keyboard.name || "DETECTING KEYBOARD…").toUpperCase()
                    color: "#d1f7fe"
                    elide: Text.ElideRight
                    font.family: "JetBrains Mono"
                    font.pixelSize: 10
                    font.bold: true
                    font.letterSpacing: 1.1
                }

                Repeater {
                    model: root.activeSection === "mouse" ? [
                        ["HARDWARE DPI", root.display(root.mouse.hardware_dpi,
                            root.mouse.hardware_maximum_verified ? " · MAX VERIFIED" : "")],
                        ["EFFECTIVE DPI", root.display(root.mouse.effective_dpi, "")],
                        ["PROFILE", String(
                            root.mouse.acceleration_profile || "unavailable"
                        ).toUpperCase()],
                        ["MULTIPLIER", root.display(root.mouse.multiplier, "×")],
                        ["SENSITIVITY", root.display(root.mouse.sensitivity, "")],
                        ["COMPOSITOR", root.mouse.compositor_applied
                            ? "ACTIVE" : "UNAVAILABLE"]
                    ] : [
                        ["LAYOUT", String(root.keyboard.layout || "unavailable").toUpperCase()],
                        ["REPEAT RATE", root.display(root.keyboard.repeat_rate_hz, " HZ")],
                        ["REPEAT DELAY", root.display(root.keyboard.repeat_delay_ms, " MS")],
                        ["CAPS LOCK", root.keyboard.caps_lock_mapping
                            ? "→ " + String(root.keyboard.caps_lock_mapping).toUpperCase()
                            : "UNMAPPED"]
                    ]

                    delegate: Row {
                        id: factRow

                        required property var modelData
                        width: parent.width
                        height: 22

                        Text {
                            width: 150
                            text: String(factRow.modelData[0])
                            color: "#7899b8c5"
                            font.family: "JetBrains Mono"
                            font.pixelSize: 8
                            font.letterSpacing: 1.0
                        }

                        Text {
                            width: parent.width - 150
                            text: String(factRow.modelData[1])
                            color: "#cffafe"
                            elide: Text.ElideRight
                            font.family: "JetBrains Mono"
                            font.pixelSize: 9
                        }
                    }
                }

                Text {
                    visible: root.errorMessage !== ""
                    text: root.errorMessage
                    color: "#fda4af"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 8
                }
            }
        }

        Text {
            width: parent.width
            text: root.activeSection === "mouse"
                ? "The physical mouse stays at its verified maximum; "
                    + "Hyprland applies one flat desktop multiplier on every Surface."
                : "Keyboard controls will expand here as they are added "
                    + "to the shared input adapter."
            color: "#758db8c7"
            wrapMode: Text.WordWrap
            font.family: "JetBrains Mono"
            font.pixelSize: 8
        }
    }
}
