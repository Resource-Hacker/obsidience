pragma ComponentBehavior: Bound

import QtQuick

Item {
    id: root

    property var levels: []
    property bool capturing: false
    readonly property int barCount: 32
    implicitWidth: 256
    implicitHeight: 24
    Accessible.name: "Microphone input level history"

    Row {
        anchors.fill: parent
        spacing: 3

        Repeater {
            model: root.barCount

            Rectangle {
                required property int index
                readonly property int sampleIndex: index - (root.barCount - root.levels.length)
                readonly property real amplitude: sampleIndex >= 0
                    ? Math.max(0, Math.min(1, Number(root.levels[sampleIndex]) || 0)) : 0
                objectName: "inputBar" + index
                anchors.verticalCenter: parent.verticalCenter
                width: Math.max(1, (root.width - (root.barCount - 1) * 3) / root.barCount)
                height: 2 + Math.max(0, root.height - 2) * amplitude
                radius: width / 2
                color: root.capturing ? "#67e8f9" : "#6b67e8f9"

                Behavior on height {
                    NumberAnimation { duration: 75; easing.type: Easing.OutQuad }
                }
            }
        }
    }
}
