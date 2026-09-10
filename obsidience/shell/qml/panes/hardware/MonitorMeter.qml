pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

ColumnLayout {
    id: root
    required property var shellTheme
    property string label: ""
    property var value: null
    readonly property bool available: typeof value === "number" && Number.isFinite(value)
    readonly property color accentColor: Qt.rgba(shellTheme.strongAccent.r, shellTheme.strongAccent.g, shellTheme.strongAccent.b, 1)
    spacing: 4
    Text { Layout.alignment: Qt.AlignHCenter; text: root.label; color: root.shellTheme.muted; font.pixelSize: 10 }
    ColumnLayout {
        Layout.fillWidth: true; Layout.fillHeight: true; spacing: 2
        Repeater {
            model: 20
            delegate: Rectangle {
                required property int index
                Layout.fillWidth: true; Layout.fillHeight: true; Layout.minimumHeight: 2
                color: root.available && root.value >= (20 - index) * 5 ? root.accentColor : root.shellTheme.selection
                opacity: root.available && root.value >= (20 - index) * 5 ? 0.85 : 0.5
                radius: 1
            }
        }
    }
    Text { Layout.alignment: Qt.AlignHCenter; text: root.available ? Math.round(root.value) + "%" : "—"; color: root.available ? root.shellTheme.text : root.shellTheme.muted; font.pixelSize: 11 }
}
