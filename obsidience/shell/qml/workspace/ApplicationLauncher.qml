pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Widgets
import "../components/visual"

PopupWindow {
    id: root

    required property Item anchorItem
    required property var surfaceScreen
    required property bool requestedVisible
    required property real shelfWidth
    required property real shelfHeight

    signal dismissRequested()

    visible: requestedVisible
    implicitWidth: Math.min(440, shelfWidth)
    implicitHeight: Math.min(
        640,
        surfaceScreen ? surfaceScreen.height - shelfHeight - 20 : 640
    )
    color: "transparent"
    grabFocus: true

    anchor {
        item: root.anchorItem
        edges: Edges.Top | Edges.Left
        gravity: Edges.Top | Edges.Right
        adjustment: PopupAdjustment.Slide
    }

    function matches(entry) {
        if (!entry || entry.noDisplay) {
            return false
        }
        const query = searchField.text.trim().toLowerCase()
        if (!query) {
            return true
        }
        return [entry.name, entry.genericName, entry.comment]
            .concat(entry.keywords || [])
            .join(" ").toLowerCase().indexOf(query) >= 0
    }

    function launch(entry) {
        if (!entry || entry.noDisplay) {
            return
        }
        entry.execute()
        dismissRequested()
    }

    onVisibleChanged: {
        if (visible) {
            searchField.text = ""
            Qt.callLater(() => searchField.forceActiveFocus())
        } else if (requestedVisible) {
            dismissRequested()
        }
    }

    Rectangle {
        anchors.fill: parent
        radius: 6
        color: "#f2030a10"
        border.width: 1
        border.color: "#5c67e8f9"

        Rectangle {
            anchors.fill: parent
            anchors.margins: 1
            radius: 5
            color: "transparent"
            border.width: 1
            border.color: "#1a67e8f9"
        }
    }

    Column {
        anchors.fill: parent
        anchors.margins: 12
        spacing: 10

        Row {
            width: parent.width
            height: 30
            spacing: 8

            ShellIcon {
                anchors.verticalCenter: parent.verticalCenter
                width: 18
                height: 18
                glyph: "launcher"
            }

            Text {
                anchors.verticalCenter: parent.verticalCenter
                width: parent.width - 60
                text: "APPLICATIONS"
                color: "#d9cffafe"
                font.family: "JetBrains Mono"
                font.pixelSize: 11
                font.weight: Font.DemiBold
                font.letterSpacing: 2.2
            }

            GlowButton {
                width: 28
                height: 28
                text: "×"
                uppercase: false
                contentHorizontalPadding: 0
                textPixelSize: 16
                textLetterSpacing: 0
                onClicked: root.dismissRequested()
            }
        }

        TextField {
            id: searchField

            width: parent.width
            height: 34
            placeholderText: "Search applications"
            color: "#d9cffafe"
            placeholderTextColor: "#6667e8f9"
            selectionColor: "#5567e8f9"
            selectedTextColor: "#ffffff"
            font.family: "JetBrains Mono"
            font.pixelSize: 11
            leftPadding: 10
            rightPadding: 10

            Keys.priority: Keys.BeforeItem
            Keys.onPressed: event => {
                if (event.key === Qt.Key_Escape) {
                    event.accepted = true
                    root.dismissRequested()
                }
            }

            background: Rectangle {
                radius: 4
                color: "#d908131e"
                border.width: 1
                border.color: searchField.activeFocus
                    ? "#8067e8f9" : "#3367e8f9"
            }
        }

        ListView {
            id: applicationList

            width: parent.width
            height: parent.height - 84
            clip: true
            spacing: 4
            model: DesktopEntries.applications
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar {}

            delegate: Item {
                id: applicationRow

                required property var modelData
                readonly property bool included: root.matches(modelData)

                width: applicationList.width
                height: included ? 40 : 0
                visible: included

                Rectangle {
                    anchors.fill: parent
                    radius: 4
                    color: applicationMouse.containsMouse
                        ? "#1f67e8f9" : "transparent"
                    border.width: 1
                    border.color: applicationMouse.containsMouse
                        ? "#5967e8f9" : "#1467e8f9"
                }

                IconImage {
                    anchors.left: parent.left
                    anchors.leftMargin: 9
                    anchors.verticalCenter: parent.verticalCenter
                    width: 22
                    height: 22
                    source: Quickshell.iconPath(
                        applicationRow.modelData.icon,
                        "application-x-executable"
                    )
                    asynchronous: true
                    mipmap: true
                }

                Column {
                    anchors.left: parent.left
                    anchors.leftMargin: 42
                    anchors.right: parent.right
                    anchors.rightMargin: 9
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 1

                    Text {
                        width: parent.width
                        text: applicationRow.modelData.name || "Application"
                        color: "#e6cffafe"
                        elide: Text.ElideRight
                        font.family: "JetBrains Mono"
                        font.pixelSize: 10
                        font.weight: Font.Medium
                    }

                    Text {
                        width: parent.width
                        visible: text !== ""
                        text: applicationRow.modelData.genericName || ""
                        color: "#8067e8f9"
                        elide: Text.ElideRight
                        font.family: "JetBrains Mono"
                        font.pixelSize: 8
                    }
                }

                MouseArea {
                    id: applicationMouse

                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.launch(applicationRow.modelData)
                }
            }
        }
    }
}
