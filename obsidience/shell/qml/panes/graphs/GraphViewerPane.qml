pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Controls.Basic
import QtWebEngine

Rectangle {
    id: root

    required property string surfaceId
    property bool monitoringAllowed: true
    color: "#02060c"

    WebEngineView {
        id: viewer

        anchors.fill: parent
        url: "http://127.0.0.1:8765/shell/knowledge/?surface=graph&viewer=1"
        backgroundColor: "#02060c"
        settings.errorPageEnabled: false
        property bool loadFailed: false
        readonly property bool graphVisible: root.visible && root.monitoringAllowed

        function publishVisibility() {
            runJavaScript("document.documentElement.dataset.paneVisible = " + JSON.stringify(String(graphVisible))
                + ";document.documentElement.dataset.paneSurface = " + JSON.stringify(root.surfaceId)
                + ";window.dispatchEvent(new CustomEvent('obsidience-pane-visibility', {detail: "
                + (graphVisible ? "true" : "false") + "}));window.dispatchEvent(new CustomEvent('obsidience-pane-surface', {detail: "
                + JSON.stringify(root.surfaceId) + "}))")
        }
        onGraphVisibleChanged: publishVisibility()
        onLoadingChanged: info => {
            loadFailed = info.status === WebEngineView.LoadFailedStatus
            if (info.status === WebEngineView.LoadSucceededStatus) publishVisibility()
        }
        onNavigationRequested: request => {
            // Reader/Source navigation crosses the existing Shell API. This
            // display never becomes an external browser or a credential host.
            if (!request.url.toString().startsWith("http://127.0.0.1:8765/shell/knowledge/"))
                request.action = WebEngineNavigationRequest.IgnoreRequest
        }
        onNewWindowRequested: request => {}
        onJavaScriptConsoleMessage: (level, message, lineNumber, sourceID) => {
            if (level === WebEngineView.ErrorMessageLevel)
                console.warn("Graph viewer: " + message.slice(0, 600))
        }
    }

    onSurfaceIdChanged: viewer.publishVisibility()

    Button {
        anchors.centerIn: parent
        visible: viewer.loadFailed
        text: "Reconnect graph viewer"
        onClicked: viewer.reload()
    }
}
