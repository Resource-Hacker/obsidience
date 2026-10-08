//@ pragma AppId io.obsidience.shell
pragma ComponentBehavior: Bound

import QtQuick
import QtWebEngine
import Quickshell
import Quickshell.Wayland
import "api"

ShellRoot {
    id: root
    Component.onCompleted: Quickshell.watchFiles = false
    property SurfaceLayout layout: SurfaceLayout {}
    // This native connection survives failed HTML navigation; the page's own
    // reconnect logic cannot run until its JavaScript has loaded.
    readonly property RealtimeState backend: RealtimeState {}
    readonly property string origin: Quickshell.env("OBSIDIENCE_KNOWLEDGE_ORIGIN") || "http://127.0.0.1:8765/shell/knowledge/"
    property WebEngineProfile graphProfile: WebEngineProfile {
        storageName: "obsidience-graph-stage"
        offTheRecord: false
        persistentCookiesPolicy: WebEngineProfile.NoPersistentCookies
    }

    Variants {
        model: Quickshell.screens.filter(screen => root.layout.surfaces.some(surface =>
            surface.output === screen.name && (surface.id === "samsung" || surface.id === root.layout.graphSurfaceId)))

        PanelWindow {
            id: stage
            required property var modelData
            screen: modelData
            readonly property string surfaceId: root.layout.surfaces.find(surface => surface.output === modelData.name)?.id || ""
            color: "#02060c"
            exclusiveZone: 0
            anchors { top: true; right: true; bottom: true; left: true }
            WlrLayershell.layer: WlrLayer.Background
            WlrLayershell.namespace: "obsidience-knowledge-desktop"
            WlrLayershell.keyboardFocus: WlrKeyboardFocus.OnDemand

            WebEngineView {
                id: graph
                readonly property bool backendConnected: root.backend.connected
                property bool loadFailed: false
                property bool recoveryAttempted: false

                // Match the lock Surface: one failed-page recovery per backend
                // connection, without reloading healthy resident graph scenes.
                function recoverFailedPage() {
                    if (!backendConnected || !loadFailed || loading
                            || recoveryAttempted) return
                    recoveryAttempted = true
                    console.info("Retrying failed graph page: " + stage.surfaceId)
                    reload()
                }

                onBackendConnectedChanged: {
                    if (!backendConnected) recoveryAttempted = false
                    else Qt.callLater(recoverFailedPage)
                }

                profile: root.graphProfile
                anchors.fill: parent
                url: root.origin + "?surface=" + (stage.surfaceId === "samsung" ? "stage" : "knowledge")
                    + "&surface_id=" + encodeURIComponent(stage.surfaceId)
                backgroundColor: "#02060c"
                settings.errorPageEnabled: false
                settings.playbackRequiresUserGesture: false
                onNavigationRequested: request => {
                    if (!request.url.toString().startsWith(root.origin))
                        request.action = WebEngineNavigationRequest.IgnoreRequest
                }
                onNewWindowRequested: request => {}
                onJavaScriptConsoleMessage: (level, message) => {
                    if (level === WebEngineView.ErrorMessageLevel || level === WebEngineView.WarningMessageLevel)
                        console.warn("Graph stage " + stage.surfaceId + ": " + message.slice(0, 600))
                }
                onLoadingChanged: info => {
                    if (info.status === WebEngineView.LoadSucceededStatus) {
                        loadFailed = false
                        console.info("Graph page loaded: " + stage.surfaceId)
                    } else if (info.status === WebEngineView.LoadFailedStatus) {
                        loadFailed = true
                        console.warn("Graph stage load failed: " + info.errorString)
                        Qt.callLater(recoverFailedPage)
                    }
                }
            }
        }
    }
}
