pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtWebEngine
import "../components/identity"

Rectangle {
    id: root

    required property var controller
    required property string surfaceId
    required property string graphSurfaceId
    readonly property bool showsGraph: surfaceId !== ""
        && surfaceId === graphSurfaceId
    readonly property url graphUrl: "http://127.0.0.1:8765/shell/knowledge/"
        + "?surface=knowledge&surface_id="
        + encodeURIComponent(surfaceId) + "&lock=1"

    color: "#02060c"

    Loader {
        anchors.fill: parent
        active: root.showsGraph

        sourceComponent: Component {
            WebEngineView {
                id: graphView

                // Reuse the host's existing Harness connection; speech need
                // not be enabled. A failed navigation gets one recovery per
                // connected interval without replacing the secure lock.
                readonly property bool backendConnected:
                    root.controller.shellApi.realtime.connected
                property bool loadFailed: false
                property bool recoveryAttempted: false

                function recoverFailedPage() {
                    if (!backendConnected || !loadFailed || loading
                            || recoveryAttempted) return
                    recoveryAttempted = true
                    reload()
                }

                onBackendConnectedChanged: {
                    if (!backendConnected) recoveryAttempted = false
                    else Qt.callLater(recoverFailedPage)
                }

                onLoadingChanged: info => {
                    if (info.status === WebEngineView.LoadSucceededStatus) {
                        loadFailed = false
                    } else if (info.status === WebEngineView.LoadFailedStatus) {
                        loadFailed = true
                        Qt.callLater(recoverFailedPage)
                    }
                }

                anchors.fill: parent
                url: root.graphUrl
                backgroundColor: "#02060c"
                settings.errorPageEnabled: false
                visible: !loadFailed
                enabled: false
                focus: false
            }
        }
    }

    Identity {
        anchors.left: parent.left
        anchors.top: parent.top
        anchors.leftMargin: 20
        anchors.topMargin: 12
        visible: !root.showsGraph
    }

    Rectangle {
        id: unlockPanel

        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: parent.verticalCenter
        width: Math.min(440, parent.width - 48)
        height: 132
        radius: 12
        color: "#ed030a10"
        border.width: 1
        border.color: root.controller.secure ? "#8067e8f9" : "#40536f78"

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 18
            spacing: 10

            Text {
                Layout.fillWidth: true
                text: root.controller.secure ? "UNLOCK OBSIDIENCE" : "SECURING SESSION"
                color: "#cffafe"
                font.family: "JetBrains Mono"
                font.pixelSize: 11
                font.letterSpacing: 2.2
                renderType: Text.NativeRendering
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 8

                TextField {
                    id: passwordField

                    Layout.fillWidth: true
                    Layout.preferredHeight: 40
                    focus: true
                    enabled: root.controller.secure
                        && !root.controller.authenticating
                    echoMode: TextInput.Password
                    inputMethodHints: Qt.ImhSensitiveData
                    placeholderText: "Password"
                    placeholderTextColor: "#8067e8f9"
                    color: "#cffafe"
                    selectionColor: "#4067e8f9"
                    selectedTextColor: "#cffafe"
                    font.family: "JetBrains Mono"
                    font.pixelSize: 12

                    background: Rectangle {
                        radius: 7
                        color: "#e602080e"
                        border.width: 1
                        border.color: passwordField.activeFocus
                            ? "#b367e8f9" : "#40536f78"
                    }

                    onTextEdited: root.controller.password = text
                    onAccepted: root.controller.tryUnlock()

                    Connections {
                        target: root.controller

                        function onPasswordChanged() {
                            if (passwordField.text !== root.controller.password) {
                                passwordField.text = root.controller.password
                            }
                        }
                    }
                }

                Button {
                    id: unlockButton

                    Layout.preferredWidth: 86
                    Layout.preferredHeight: 40
                    enabled: root.controller.secure
                        && !root.controller.authenticating
                        && root.controller.password.length > 0
                    focusPolicy: Qt.NoFocus

                    contentItem: Text {
                        text: root.controller.authenticating ? "WAIT" : "UNLOCK"
                        color: unlockButton.enabled ? "#cffafe" : "#66536f78"
                        font.family: "JetBrains Mono"
                        font.pixelSize: 10
                        font.letterSpacing: 1.4
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        renderType: Text.NativeRendering
                    }

                    background: Rectangle {
                        radius: 7
                        color: unlockButton.hovered ? "#2b102a36" : "#e602080e"
                        border.width: 1
                        border.color: unlockButton.enabled
                            ? "#8067e8f9" : "#40536f78"
                    }

                    onClicked: root.controller.tryUnlock()
                }
            }

            Text {
                Layout.fillWidth: true
                visible: root.controller.authenticationFailed
                text: "Incorrect password"
                color: "#fb7185"
                font.family: "JetBrains Mono"
                font.pixelSize: 10
                renderType: Text.NativeRendering
            }
        }
    }
}
