pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Layouts

Rectangle {
    id: root
    required property var shellTheme
    property string title: ""
    property string value: ""
    property string detail: ""
    property var values: []
    property real maximum: 100
    property string scaleLabel: "100%"
    property int plotHeight: 120
    readonly property color accentColor: Qt.rgba(shellTheme.strongAccent.r, shellTheme.strongAccent.g, shellTheme.strongAccent.b, 1)
    implicitHeight: body.implicitHeight + 20
    color: shellTheme.inactiveSurface
    border.color: shellTheme.separator
    radius: 3
    ColumnLayout {
        id: body
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        anchors.margins: 10
        spacing: 5
        RowLayout {
            Layout.fillWidth: true
            Text { Layout.fillWidth: true; text: root.title; textFormat: Text.PlainText; color: root.shellTheme.text; font.pixelSize: 13; font.weight: Font.DemiBold; elide: Text.ElideRight }
            Text { text: root.value; textFormat: Text.PlainText; color: root.accentColor; font.pixelSize: 14; font.weight: Font.DemiBold }
        }
        RowLayout {
            Layout.fillWidth: true; spacing: 5
            Text { Layout.fillWidth: true; text: root.scaleLabel; textFormat: Text.PlainText; color: root.shellTheme.muted; font.pixelSize: 10 }
            Text { text: "Now"; color: root.shellTheme.muted; font.pixelSize: 10 }
        }
        MonitorTrend {
            Layout.fillWidth: true; Layout.preferredHeight: root.plotHeight
            values: root.values; maximum: root.maximum
            lineColor: root.accentColor; gridColor: root.shellTheme.separator
        }
        Text { Layout.fillWidth: true; text: root.detail; visible: !!text; textFormat: Text.PlainText; color: root.shellTheme.muted; font.pixelSize: 11; wrapMode: Text.Wrap }
    }
}
