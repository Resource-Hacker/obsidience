pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import QtWebEngine

Rectangle {
    id: root

    color: "#050c14"

    WebEngineView {
        id: viewer

        anchors.fill: parent
        url: "http://127.0.0.1:8769/"
        backgroundColor: "#050c14"
        settings.errorPageEnabled: false
        property bool loadFailed: false

        onLoadingChanged: info => {
            loadFailed = info.status === WebEngineView.LoadFailedStatus
        }
        onNavigationRequested: request => {
            if (!request.url.toString().startsWith("http://127.0.0.1:8769/"))
                request.action = WebEngineNavigationRequest.IgnoreRequest
        }
        onNewWindowRequested: request => {}
    }

    Button {
        anchors.centerIn: parent
        visible: viewer.loadFailed
        text: "Reconnect TFT ledger"
        onClicked: viewer.reload()
    }
}
