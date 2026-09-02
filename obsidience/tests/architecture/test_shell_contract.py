"""Physical contract for the native Shell module."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from obsidience.shell.adapter.kwin import BUS_NAME, parse_window_list


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SHELL_ROOT = PROJECT_ROOT / "obsidience" / "shell"


def test_shell_manifest_names_one_real_module() -> None:
    manifest = tomllib.loads((SHELL_ROOT / "module.toml").read_text(encoding="utf-8"))
    assert manifest == {
        "schema": "obsidience.module.v1",
        "id": "shell",
        "name": "Shell",
        "summary": "Owns modular desktop Surfaces and isolates compositor-specific integration.",
        "package": "obsidience.shell",
        "entrypoints": [
            "obsidience/shell/qml/shell.qml",
            "obsidience/shell/qml/surface.qml",
            "obsidience/shell/surfaces/knowledge/host.py",
            "obsidience/shell/surfaces/lock/host.py",
            "obsidience/shell/adapter/windows/host.py",
            "obsidience/shell/theme/apply.py",
            "obsidience/shell/lock/wallpaper/contents/ui/main.qml",
        ],
        "source_roots": ["obsidience/shell"],
        "projections": ["obsidience/state/system/applications/obsidience"],
        "runtime_dependencies": [
            "packagekit 1.3.6-1.1",
            "quickshell 0.3.0-2.1",
            "gtk-layer-shell 0.10.1-1.1",
            "kscreenlocker 6.6.5-1.1",
            "webkit2gtk-4.1 2.52.4-1",
            "python-gobject 3.56.3-1",
            "python-dbus 1.4.0-2",
            "python-websockets 16.1.1-1.1",
            "python-xlib 0.33-6",
            "qmltermwidget 2.0.0.git1-1.1",
            "qt6-webengine 6.11.1-2",
            "qt6-websockets 6.11.1-1.1",
            "ttf-jetbrains-mono 2.304-2",
        ],
    }


def test_shell_session_replaces_only_plasmashell() -> None:
    target = (SHELL_ROOT / "systemd" / "obsidience-shell-session.target").read_text()
    compositor = (SHELL_ROOT / "session" / "obsidience-shell-compositor").read_text()
    host = (SHELL_ROOT / "systemd" / "obsidience-shell-host.service").read_text()
    autostart_override = (
        SHELL_ROOT
        / "systemd"
        / r"wayland-session-xdg-autostart@obsidience\x2dshell\x2dcompositor.target"
    )
    assert "main-compositor-ready.target" in target
    assert "obsidience-shell-host.service" in target
    assert "obsidience-shell-window-adapter.service" in target
    assert "jarvis" not in target.lower()
    assert "hermes" not in target.lower()
    assert "plasmashell" not in target
    assert "kwin_wayland" in compositor
    assert "--xwayland" in compositor
    assert "/usr/bin/quickshell" in host
    assert "obsidience/shell/qml" in host
    assert "QT_QPA_PLATFORM=wayland" in host
    assert "LD_PRELOAD" not in host
    assert "/usr/bin/python" not in host
    assert "StartLimitBurst=3" in host
    assert "DISPLAY=" not in host
    assert autostart_override.is_file()


def test_quickshell_canary_owns_only_the_samsung_surface() -> None:
    shell = (SHELL_ROOT / "qml" / "shell.qml").read_text()
    shell_api = (SHELL_ROOT / "qml" / "api" / "ShellApi.qml").read_text()
    stage = (SHELL_ROOT / "qml" / "surfaces" / "stage" / "Stage.qml").read_text()
    stage_content = (
        SHELL_ROOT / "qml" / "surfaces" / "stage" / "StageContent.qml"
    ).read_text()
    identity = (
        SHELL_ROOT / "qml" / "components" / "identity" / "Identity.qml"
    ).read_text()
    assert 'primaryOutputName: "HDMI-A-1"' in shell_api
    assert "property ShellApi shellApi: ShellApi {}" in shell
    assert "Quickshell.screens.filter" in shell
    assert shell.count("model: root.targetScreens") == 1
    assert "PaneWorkspace {" in shell
    assert "targetScreens: root.targetScreens" in shell
    assert shell.count("shellApi: root.shellApi") == 2
    assert 'import "surfaces/stage"' in shell
    assert "WlrLayer.Bottom" in stage
    assert "aboveWindows: false" in stage
    assert "mask: Region {}" in stage
    assert 'color: "transparent"' in stage
    assert "anchors.leftMargin: 20" in stage_content
    assert "anchors.topMargin: 12" in stage_content
    assert 'text: "OBSIDIENCE"' in identity
    assert "font.pixelSize: 13" in identity
    assert "font.letterSpacing: 5.2" in identity
    assert "blurMax: 12" in identity
    assert "shadowEnabled: true" in identity
    assert shell.startswith("//@ pragma NativeTextRendering\n")
    assert not (SHELL_ROOT / "qml" / "panels" / "top" / "TopPanel.qml").exists()
    assert not (
        SHELL_ROOT / "qml" / "surfaces" / "background" / "Background.qml"
    ).exists()


def test_knowledge_graph_is_shell_owned_threejs_stage_content() -> None:
    stage = (SHELL_ROOT / "qml" / "surfaces" / "stage" / "Stage.qml").read_text()
    x11_stage = (
        SHELL_ROOT / "qml" / "surfaces" / "stage" / "X11Stage.qml"
    ).read_text()
    desktop = (
        SHELL_ROOT
        / "surfaces"
        / "knowledge"
        / "host.py"
    ).read_text()
    api = (
        PROJECT_ROOT
        / "obsidience"
        / "harness"
        / "interfaces"
        / "api"
        / "app.py"
    ).read_text()
    service = (
        SHELL_ROOT / "systemd" / "obsidience-shell-knowledge.service"
    ).read_text()
    target = (
        SHELL_ROOT / "systemd" / "obsidience-shell-session.target"
    ).read_text()
    renderer_main = (
        PROJECT_ROOT / "obsidience" / "ui" / "src" / "renderer" / "src" / "main.tsx"
    ).read_text()
    renderer_surface = (
        PROJECT_ROOT
        / "obsidience"
        / "ui"
        / "src"
        / "renderer"
        / "src"
        / "surfaces"
        / "knowledge-desktop.tsx"
    ).read_text()
    reader_surface = (
        PROJECT_ROOT
        / "obsidience"
        / "ui"
        / "src"
        / "renderer"
        / "src"
        / "surfaces"
        / "reader-desktop.tsx"
    )
    shell_client = (
        PROJECT_ROOT
        / "obsidience"
        / "ui"
        / "src"
        / "renderer"
        / "src"
        / "lib"
        / "shell-client.ts"
    ).read_text()
    command_server = (
        SHELL_ROOT / "qml" / "api" / "ShellCommandServer.qml"
    ).read_text()
    placement = (SHELL_ROOT / "qml" / "workspace" / "PanePlacement.qml").read_text()
    pane = (SHELL_ROOT / "qml" / "workspace" / "PaneItem.qml").read_text()
    reader = (SHELL_ROOT / "qml" / "panes" / "reader" / "ReaderPane.qml").read_text()
    workspace = (
        SHELL_ROOT / "qml" / "workspace" / "PaneWorkspace.qml"
    ).read_text()
    samsung = (SHELL_ROOT / "qml" / "shell.qml").read_text()
    isolated = (SHELL_ROOT / "qml" / "surface.qml").read_text()

    assert "KnowledgeDesktop" not in stage
    assert "WlrLayershell" not in x11_stage
    assert "aboveWindows: locked" in x11_stage
    assert "mask: Region {}" in x11_stage
    assert 'surfaceId: "samsung"' in samsung
    assert isolated.count("X11Stage {") == 1
    assert isolated.count("model: root.targetScreens") == 1
    assert "PaneWorkspace {" in samsung
    assert "PaneWorkspace {" in isolated
    assert "targetScreens: root.targetScreens" in samsung
    assert "targetScreens: root.targetScreens" in isolated
    assert "surfaceId: root.surfaceId" in isolated
    assert "KnowledgeDesktop" not in pane
    assert "KnowledgeDesktop" not in x11_stage
    assert 'gi.require_version("GtkLayerShell", "0.1")' in desktop
    assert 'gi.require_version("Gdk", "3.0")' in desktop
    assert 'gi.require_version("WebKit2", "4.1")' in desktop
    assert "WebKit2.WebView()" in desktop
    assert 'GtkLayerShell.set_namespace(window, "obsidience-knowledge-desktop")' in desktop
    assert "GtkLayerShell.Layer.BACKGROUND" in desktop
    assert "GtkLayerShell.KeyboardMode.NONE" in desktop
    assert "GtkLayerShell.set_exclusive_zone(window, 0)" in desktop
    assert "display.get_n_monitors() != 1" not in desktop
    assert 'display.connect("monitor-added"' in desktop
    assert 'display.connect("monitor-removed"' in desktop
    assert 'monitor.connect("notify::geometry"' in desktop
    assert "self.window.hide()" in desktop
    assert "GtkLayerShell.set_monitor(self.window, monitor)" in desktop
    assert "self.window.show_all()" in desktop
    assert "self.window.destroy()" not in desktop
    assert "set_enable_webgl(True)" in desktop
    assert "HardwareAccelerationPolicy.ALWAYS" in desktop
    assert 'WEBKIT_DMABUF_RENDERER_FORCE_SHM", "1"' in desktop
    assert "?surface=reader" not in desktop
    assert "?surface=knowledge" in desktop
    assert "Electron" not in desktop
    assert 'app.mount(' in api
    assert '"/shell/knowledge"' in api
    assert "StaticFiles(" in api
    assert '"ui" / "out" / "renderer"' in api
    assert "/usr/bin/python3" in service
    assert "surfaces/knowledge/host.py" in service
    assert "GDK_BACKEND=wayland" in service
    assert "WEBKIT_DMABUF_RENDERER_FORCE_SHM=1" in service
    assert "QT_QPA_PLATFORM" not in service
    assert "QSG_RHI_BACKEND" not in service
    assert "PartOf=obsidience-shell-session.target" in service
    assert "obsidience-shell-knowledge.service" in target
    assert 'surface === "knowledge"' in renderer_main
    assert 'surface === "reader"' not in renderer_main
    assert "?surface=reader" not in renderer_main
    assert "dataset.obsidienceSurface" in renderer_main
    assert 'import("./surfaces/knowledge-desktop")' in renderer_main
    assert "GraphBackdrop" in renderer_surface
    assert "presentShellReader" in renderer_surface
    assert not reader_surface.exists()
    assert "QtWebEngine" not in reader
    assert "WebEngineView" not in reader
    assert "ReaderPaneBody" not in reader
    assert "QtWebSockets" in reader
    assert "WebSocket {" in reader
    assert 'url: "ws://127.0.0.1:8768"' in reader
    assert 'requestedSubprotocols: ["obsidience.shell.v1"]' in reader
    assert '"pane.state"' in reader
    assert 'event.pane.pane_id !== "reader"' in reader
    assert 'selection.kind === "article"' in reader
    assert 'selection.kind === "source"' in reader
    assert "new XMLHttpRequest()" in reader
    assert '"api/source-files/" : "api/articles/"' in reader
    assert "encodeURI(ref)" in reader
    assert "Text.MarkdownText" in reader
    assert "linkColor:" in reader
    assert 'const SHELL_URL = "ws://127.0.0.1:8768"' in shell_client
    assert 'const SHELL_SUBPROTOCOL = "obsidience.shell.v1"' in shell_client
    assert 'type: "pane.present"' in shell_client
    assert 'pane_id: "reader"' in shell_client
    assert 'selection: { kind: "article", ref }' in shell_client
    assert "ShellCommandServer {" in samsung
    fullscreen_state = (
        SHELL_ROOT / "qml" / "api" / "FullscreenState.qml"
    ).read_text()
    edge_adapter = (
        SHELL_ROOT / "adapter" / "kwin" / "surface_edges.js"
    ).read_text()
    input_bridge = (SHELL_ROOT / "input" / "dbus_bridge.py").read_text()
    assert "property FullscreenState fullscreenState: FullscreenState {}" in samsung
    assert "knowledgeVisible: !lockState.active && !fullscreenState.active" in samsung
    assert "knowledgeVisible: root.knowledgeVisible" in samsung
    assert '"/obsidience-shell-fullscreen.state"' in fullscreen_state
    assert "preload: true" in fullscreen_state
    assert "watchChanges: true" in fullscreen_state
    assert "onFileChanged: stateFile.reload()" in fullscreen_state
    assert "onLoaded: root.reloadState()" in fullscreen_state
    assert 'active = stateFile.text().trim() === "1"' in fullscreen_state
    assert "function reportFullscreen()" in edge_adapter
    assert 'window.output.name === "HDMI-A-1"' in edge_adapter
    assert '"ReportFullscreen"' in edge_adapter
    assert "def ReportFullscreen(self, state: str)" in input_bridge
    assert 'FULLSCREEN_STATE.write_text(value + "\\n"' in input_bridge
    assert "ShellCommandServer" not in isolated
    assert "WebSocketServer" in command_server
    assert 'host: "127.0.0.1"' in command_server
    assert "port: 8768" in command_server
    assert 'subprotocol: "obsidience.shell.v1"' in command_server
    assert 'command.type !== "pane.present"' in command_server
    assert 'command.pane_id !== "reader"' in command_server
    assert 'selection.kind !== "article" && selection.kind !== "source"' in command_server
    assert 'selection.kind === "article" ? "ref" : "key"' in command_server
    assert (
        "presentPlacementOnSurface(readerPlacement, readerPlacement.surfaceId)"
        in command_server
    )
    assert "broadcast(readerState())" in command_server
    assert '"type": "surface.state"' in command_server
    assert '"surface_id": "samsung"' in command_server
    assert '"visible": knowledgeVisible' in command_server
    assert "onKnowledgeVisibleChanged: broadcast(knowledgeState())" in command_server
    assert "onShellKnowledgeVisibility" in shell_client
    assert 'message.type !== "surface.state"' in shell_client
    assert "selectedSurfaceId === surfaceId && (lockMode || visible)" in renderer_surface
    assert 'const CENTERED_HUB = { x: 0.5, y: 0.5 } as const' in renderer_surface
    assert '<GraphBackdrop visible lockMode={lockMode} hub={CENTERED_HUB} />' in renderer_surface
    assert 'surfaceId !== "samsung" || lockMode' in renderer_surface
    assert "OBSIDIENCE" in renderer_surface
    assert 'query.get("lock") === "1"' in renderer_surface
    graph_backdrop = (
        PROJECT_ROOT
        / "obsidience"
        / "ui"
        / "src"
        / "renderer"
        / "src"
        / "panes"
        / "graph-backdrop.tsx"
    ).read_text()
    graph_styles = (
        PROJECT_ROOT
        / "obsidience"
        / "ui"
        / "src"
        / "renderer"
        / "src"
        / "styles"
        / "globals.css"
    ).read_text()
    graph_scene = (
        PROJECT_ROOT
        / "obsidience"
        / "ui"
        / "src"
        / "renderer"
        / "src"
        / "components"
        / "themes"
        / "obsidience"
        / "knowledge-3d-scene.tsx"
    ).read_text()
    graph_labels = (
        PROJECT_ROOT
        / "obsidience"
        / "ui"
        / "src"
        / "renderer"
        / "src"
        / "components"
        / "themes"
        / "obsidience"
        / "knowledge-3d-labels.ts"
    ).read_text()
    assert "export function GraphBackdrop({" in graph_backdrop
    assert "hub = DEFAULT_KNOWLEDGE_HUB_ANCHOR" in graph_backdrop
    assert "anchor: hub" in graph_backdrop
    assert "hub={hub}" in graph_backdrop
    assert "lockMode = false" in graph_backdrop
    assert "if (!visible) return" in graph_backdrop
    assert "visible={visible}" in graph_backdrop
    assert "antialias: true" in graph_scene
    assert graph_scene.count("new THREE.WebGLRenderer") == 1
    assert "createKnowledge3dLabelLayer" in graph_scene
    assert "renderer.autoClear = false" in graph_scene
    assert "renderer.clearDepth()" in graph_scene
    assert graph_scene.index("renderer.render(scene, camera)") < graph_scene.index(
        "labelLayer.render(renderer)"
    )
    assert "onProjected" not in graph_scene
    assert "new THREE.WebGLRenderer" not in graph_labels
    assert "new THREE.OrthographicCamera" in graph_labels
    assert "new THREE.CanvasTexture" in graph_labels
    assert "new THREE.Sprite" in graph_labels
    assert "new THREE.Line" in graph_labels
    assert "ProjectedGraphLabels" not in graph_backdrop
    assert "onProjected={setProjected}" not in graph_backdrop
    assert "<svg" not in graph_backdrop
    assert "labelIds={labelIds}" in graph_backdrop
    assert "activeLabelNodeIds={lockMode ? new Set<string>() : gatedMainNodeIds}" in graph_backdrop
    assert "labelMetadata={model.labelMetadata}" in graph_backdrop
    assert "obsidience-knowledge-map-drift" not in graph_styles
    assert "obsidience-knowledge-tag-active-lock" not in graph_styles
    assert "obsidience-knowledge-tag-scan" not in graph_styles
    assert ".obsidience-knowledge-map {" not in graph_styles
    assert "obsidience-knowledge-trace-flow" in graph_styles
    assert "obsidience-knowledge-node-wave" not in graph_styles
    assert ".obsidience-knowledge-tag" not in graph_styles
    assert ".obsidience-knowledge-label-leader" not in graph_styles
    assert "property Component readerComponent: Component { ReaderPane {} }" in workspace
    assert '"label": "Reader"' in workspace
    assert '"component": readerComponent' in workspace
    assert '"frame":' not in workspace
    assert "required property var paneDefinition" in pane
    assert 'root.placement.paneId === "reader"' in pane
    assert "? dockHostComponent : root.paneDefinition.component" in pane
    assert "ReaderPane" not in pane
    assert "WebEngineView" not in pane
    assert 'property string paneId: "displays"' in placement
    assert "stateFileName" in placement
    assert "function present()" in placement
    assert "function dismiss()" in placement
    assert "Knowledge3dScene" not in renderer_surface


def test_surface_hosts_share_displays_pane_and_surface_layout() -> None:
    samsung = (SHELL_ROOT / "qml" / "shell.qml").read_text()
    isolated = (SHELL_ROOT / "qml" / "surface.qml").read_text()
    shell_api = (SHELL_ROOT / "qml" / "api" / "ShellApi.qml").read_text()
    layout = (SHELL_ROOT / "qml" / "api" / "SurfaceLayout.qml").read_text()
    placement = (SHELL_ROOT / "qml" / "workspace" / "PanePlacement.qml").read_text()
    pane = (SHELL_ROOT / "qml" / "workspace" / "PaneItem.qml").read_text()
    canvas = (SHELL_ROOT / "qml" / "workspace" / "PaneCanvas.qml").read_text()
    drag_session = (
        SHELL_ROOT / "qml" / "workspace" / "PaneDragSession.qml"
    ).read_text()
    command_server = (
        SHELL_ROOT / "qml" / "api" / "ShellCommandServer.qml"
    ).read_text()
    launcher = (
        SHELL_ROOT / "qml" / "workspace" / "PaneLauncher.qml"
    ).read_text()
    workspace = (
        SHELL_ROOT / "qml" / "workspace" / "PaneWorkspace.qml"
    ).read_text()
    frame = (SHELL_ROOT / "qml" / "workspace" / "PaneFrame.qml").read_text()
    theme = (SHELL_ROOT / "qml" / "api" / "ShellTheme.qml").read_text()
    displays = (
        SHELL_ROOT / "qml" / "panes" / "displays" / "DisplaysPane.qml"
    ).read_text()
    usb_service = (
        SHELL_ROOT / "systemd" / "obsidience-shell-surface-usbc.service"
    ).read_text()
    dp4_service = (
        SHELL_ROOT / "systemd" / "obsidience-shell-surface-dp4.service"
    ).read_text()
    initial_placement = json.loads(
        (SHELL_ROOT / "state" / "initial-pane-placement.json").read_text()
    )
    initial_reader_placement = json.loads(
        (SHELL_ROOT / "state" / "initial-reader-placement.json").read_text()
    )
    initial_terminal_placement = json.loads(
        (SHELL_ROOT / "state" / "initial-terminal-placement.json").read_text()
    )
    initial_layout = json.loads(
        (SHELL_ROOT / "state" / "initial-surface-layout.json").read_text()
    )

    assert samsung.count("PaneWorkspace {") == 1
    assert isolated.count("PaneWorkspace {") == 1
    assert "PaneWindow" not in workspace
    assert workspace.count("PaneCanvas {") == 1
    assert 'readonly property var paneDefinitions' in workspace
    assert workspace.count('"label":') == 14
    assert 'surfaceId: "samsung"' in samsung
    assert "shellApi: root.shellApi" in samsung
    assert 'Quickshell.env("OBSIDIENCE_SURFACE_ID")' in isolated
    assert "surfaceId: root.surfaceId" in isolated
    assert "targetSurface.output" in isolated
    assert "shellApi: root.shellApi" in isolated
    assert "SurfaceLayout surfaceLayout: SurfaceLayout {}" in shell_api
    assert "ShellTheme theme: ShellTheme {}" in shell_api
    assert "readonly property int paneTopInset: 0" in layout
    assert "property int paneGridSize: 10" in layout
    assert "function normalizePaneGridSize(value)" in layout
    assert "function snapPaneValue(value)" in layout
    assert "function clampPaneSize(value, minimum, maximum)" in layout
    assert "function commitPaneGridSize(value)" in layout
    assert '"pane_grid_size": paneGridSize' in layout
    assert "function clampPaneX(surfaceRecord, paneWidth, value)" in layout
    assert "function clampPaneY(surfaceRecord, paneHeight, value)" in layout
    clamp_x = layout.split("function clampPaneX", 1)[1].split(
        "function clampPaneY", 1
    )[0]
    clamp_y = layout.split("function clampPaneY", 1)[1].split(
        "function replaceRect", 1
    )[0]
    assert "snapPaneValue(value)" in clamp_x
    assert "snapPaneValue(value)" in clamp_y
    assert "FocusScope {" in pane
    assert "PaneFrame {" in pane
    assert "required property var paneDefinition" in pane
    assert 'root.placement.paneId === "reader"' in pane
    assert "? dockHostComponent : root.paneDefinition.component" in pane
    assert "DisplaysPane" not in pane
    assert "ReaderPane" not in pane
    assert "PanelWindow {" in canvas
    assert "left: true" in canvas
    assert "right: true" in canvas
    assert "top: true" in canvas
    assert "bottom: true" in canvas
    assert "mask: Region { id: inputMask }" in canvas
    assert "focusable: hasLocalPane" in canvas
    assert "Repeater {" in canvas
    assert "PaneItem {" in canvas
    assert "inputMask.regions.push(region)" in canvas
    assert "width: paneVisible ? renderWidth : 0" in pane
    assert "height: paneVisible ? renderHeight : 0" in pane
    assert pane.count("shellApi.surfaceLayout.clampPaneSize(") >= 4
    assert "resizeStartWidth = renderWidth" in pane
    assert "resizeStartHeight = renderHeight" in pane
    assert "dragSession.previewLocal" in pane
    assert "dragSession.finish" in pane
    assert "placement.previewResize" in pane
    assert "placement.commitResize" in pane
    assert "DisplaysPane" not in canvas
    assert "default property alias contentData: content.data" in frame
    launcher_anchors = launcher.split("anchors {", 1)[1].split("}", 1)[0]
    assert "bottom: true" in launcher_anchors
    assert "top: true" not in launcher_anchors
    assert "left: true" not in launcher_anchors
    assert "right: true" not in launcher_anchors
    assert "readonly property int shelfMaximumWidth: 1200" in launcher
    assert "readonly property int edgeTriggerHeight: 12" in launcher
    assert "mask: Region { item: shelfSurface }" in launcher
    assert "width: 352" in launcher
    assert 'color: "#cc020b14"' in launcher
    assert '\n                    text: String(modelData.title)' not in launcher
    assert "glyph: String(paneButton.modelData.icon" in launcher
    assert "Repeater {" in displays
    assert "previewSurface" not in displays
    assert "dragOffsetX" in displays
    assert "dragOffsetY" in displays
    assert "commitSurfaceAt" in displays
    assert 'text: "DRAG SURFACES TO DEFINE TOUCHING EDGES"' in displays
    assert "currentSurface.logical_width" in pane
    assert "currentSurface.logical_height" in pane
    assert pane.count("shellApi.surfaceLayout.clampPaneX(") >= 2
    assert pane.count("shellApi.surfaceLayout.clampPaneY(") >= 2
    assert "placement.paneId, placement, renderX, renderY" in pane
    assert "placement.transfer" not in pane
    assert "placement.previewMove" not in pane
    assert "placement.commitMove" not in pane
    assert "dragSession.prepare" not in pane
    assert "transferAtEdge" not in pane
    assert "crossedEdges" not in pane
    assert "surfaceLayout.route" not in pane
    assert "dragSession.previewLocal" in pane
    assert "dragSession.finish" in pane
    assert "dragCancelled" not in pane
    assert "dragCancelled" not in frame
    assert "root.dragFinished(titleBar.moved)" in frame.split("onCanceled:", 1)[1]
    assert "required property PaneDragSession dragSession" in pane
    assert '"/run/user/1000/dp4-edge-bridge.cmd"' not in pane
    assert "PaneDragSession" in workspace
    assert "dragSession: root.dragSession" in workspace
    assert 'property string activePaneId: ""' in canvas
    assert "function activatePane(paneId)" in canvas
    assert "dragSession.activatePane(placement)" in canvas
    assert "Shortcut {" not in canvas
    assert "activeInCanvas: root.activePaneId === placement.paneId" in canvas
    assert "z: activeInCanvas ? 1000000 : placement.zOrder" in pane
    assert "signal activated(string paneId)" in pane
    assert "forceActiveFocus(Qt.MouseFocusReason)" in pane
    assert "PointHandler {" in pane
    assert "acceptedButtons: Qt.LeftButton" in pane
    assert "onActiveChanged: if (active)" in pane
    assert "MouseArea {" not in pane
    assert "function presentPaneOn(" in workspace
    assert "onPresentRequested:" in workspace
    assert "function placementFor(paneId)" in workspace
    assert "authoritative: true" in samsung
    assert "authoritative: false" in isolated
    assert 'url: "ws://127.0.0.1:8768"' in drag_session
    assert "Math.round(startX) : placement.x" in drag_session
    assert "Math.round(startY) : placement.y" in drag_session
    assert drag_session.index("Math.round(startX)") < drag_session.index("token = next")
    assert drag_session.index("Math.round(startY)") < drag_session.index("token = next")
    assert '"type": "pane.drag.commit"' in drag_session
    assert '"type": "pane.activate"' in drag_session
    assert '"type": "pane.move"' not in drag_session
    assert '"type": "pane.subscribe"' in drag_session
    assert '"type": "pane.drag.prepare"' not in drag_session
    assert '"type": "pane.drag.ready"' not in drag_session
    assert '"drag-start"' not in command_server
    assert '"drag-route"' not in command_server
    assert '"drag-cancel"' not in command_server
    assert "obsidience-pane-drag" not in command_server
    assert "placement.commitDrag(" in command_server
    assert "paneWorkspace.placementFor(paneId)" in command_server
    assert "function broadcastToPaneClients(message)" in command_server
    assert "function activePlacement(surfaceId)" in command_server
    assert "function movePane(socket, placement, direction)" in command_server
    assert 'command.type === "pane.move_active"' in command_server
    assert "surfaceLayout.moveRoute(" in command_server
    assert command_server.count("surfaceLayout.clampPaneX(") >= 4
    assert command_server.count("surfaceLayout.clampPaneY(") >= 4
    assert "y = surfaceLayout.paneTopInset" in command_server
    assert "shellApi.surfaceLayout.clampPaneX(" in launcher
    assert "shellApi.surfaceLayout.clampPaneY(" in launcher
    assert "paneWorkspace.presentPaneOn(placement, destination.id, x, y)" in command_server
    assert '"type": "pane.moved"' in command_server
    assert "function commitDrag(" in placement
    assert "!authoritative || revision !== expectedRevision" in placement
    assert "function transfer(" not in placement
    assert "samsungUsbStart" not in pane
    assert "samsungUsbEnd" not in pane
    assert "placementFile.setText" in placement
    assert "atomicWrites: true" in placement
    assert "watchChanges: true" in placement
    assert 'schema: "obsidience.surface-placement.v1"' in placement
    assert 'property string paneId: "displays"' in placement
    assert 'paneId: "reader"' in workspace
    assert 'paneId: "terminal"' in workspace
    assert 'paneId: "chat"' in workspace
    assert 'paneId: "library"' in workspace
    assert 'paneId: "tasks"' in workspace
    assert 'paneId: "reviews"' in workspace
    assert 'paneId: "knowledge"' in workspace
    assert 'paneId: "source"' in workspace
    assert 'paneId: "status"' in workspace
    assert 'paneId: "hardware"' in workspace
    assert 'paneId: "camera"' in workspace
    assert 'paneId: "settings"' in workspace
    assert 'paneId: "tuning"' not in workspace
    assert 'stateFileName: paneId === "displays"' in placement
    assert "function present()" in placement
    assert "function dismiss()" in placement
    assert 'record.surface_id !== "dp-4"' in placement
    assert 'schema: "obsidience.surface-layout.v1"' in layout
    for pane_path in (SHELL_ROOT / "qml" / "panes").rglob("*.qml"):
        pane_source = pane_path.read_text()
        assert "PaneFrame {" not in pane_source
        assert "onDragStarted:" not in pane_source
    assert "StandardPaths.ConfigLocation" in layout
    assert '"/obsidience-shell/surface-layout.json"' in layout
    assert "snapThreshold: 120" in layout
    assert "function commitSurfaceAt(" in layout
    assert "function touching(" in layout
    assert "function route(" in layout
    assert "function moveRoute(" in layout
    assert "layoutFile.setText" in layout
    assert "atomicWrites: true" in layout
    assert "watchChanges: true" in layout
    assert "required property ShellTheme theme" in frame
    assert "theme: root.shellApi.theme" in pane
    assert "color: root.theme.surface" in frame
    assert "border.color: root.theme.accent" in frame
    assert "shadowColor: root.theme.shadow" in frame
    assert "shadowOpacity: 0.08" in frame
    assert "height: root.theme.titleHeight" in frame
    assert "color: root.theme.separator" in frame
    assert '"frame":' not in workspace
    assert 'readonly property string schema: "obsidience.shell-theme.v1"' in theme
    assert "watchChanges: true" in theme
    assert "onFileChanged: paletteFile.reload()" in theme
    assert "QT_QPA_PLATFORM=xcb" in usb_service
    assert "OBSIDIENCE_THEME_PATH=" in usb_service
    assert isolated.startswith("//@ pragma NativeTextRendering\n")
    assert "DISPLAY=:2.0" in usb_service
    assert "OBSIDIENCE_SURFACE_ID=usb-c" in usb_service
    assert "DISPLAY=:2.1" in dp4_service
    assert "OBSIDIENCE_SURFACE_ID=dp-4" in dp4_service
    assert "OBSIDIENCE_THEME_PATH=" in dp4_service
    assert "surface.qml" in usb_service
    assert "surface.qml" in dp4_service
    assert "--no-duplicate" not in usb_service
    assert "--no-duplicate" not in dp4_service
    assert "%h/.config/obsidience-shell/surface-layout.json" in usb_service
    assert "%h/.config/obsidience-shell/surface-layout.json" in dp4_service
    assert initial_placement["surface_id"] == "samsung"
    assert initial_placement["pane_id"] == "displays"
    assert initial_reader_placement["surface_id"] == "samsung"
    assert initial_reader_placement["pane_id"] == "reader"
    assert initial_reader_placement["open"] is False
    assert initial_terminal_placement["surface_id"] == "samsung"
    assert initial_terminal_placement["pane_id"] == "terminal"
    assert initial_terminal_placement["open"] is True

    assert initial_layout["schema"] == "obsidience.surface-layout.v1"
    assert initial_layout["revision"] == 0
    assert initial_layout["graph_surface_id"] == "samsung"
    assert initial_layout["pane_grid_size"] == 10
    surfaces = {surface["id"]: surface for surface in initial_layout["surfaces"]}
    assert set(surfaces) == {"samsung", "usb-c", "dp-4"}
    assert surfaces["samsung"]["logical_width"] == 5120
    assert surfaces["samsung"]["logical_height"] == 1440
    assert surfaces["usb-c"]["logical_width"] == 1920
    assert surfaces["usb-c"]["logical_height"] == 1200
    assert surfaces["usb-c"]["device_scale"] == 2
    assert surfaces["dp-4"]["logical_width"] == 1920
    assert surfaces["dp-4"]["logical_height"] == 550
    assert surfaces["dp-4"]["device_scale"] == 2

    samsung_rect = surfaces["samsung"]["map_rect"]
    dp4_rect = surfaces["dp-4"]["map_rect"]
    usb_rect = surfaces["usb-c"]["map_rect"]
    assert samsung_rect["y"] + samsung_rect["height"] == dp4_rect["y"]
    assert samsung_rect["y"] + samsung_rect["height"] == usb_rect["y"]
    assert dp4_rect["x"] + dp4_rect["width"] == usb_rect["x"]


def test_shell_bar_has_one_ordered_native_application_and_pane_surface() -> None:
    launcher = (
        SHELL_ROOT / "qml" / "workspace" / "PaneLauncher.qml"
    ).read_text()
    application_launcher = (
        SHELL_ROOT / "qml" / "workspace" / "ApplicationLauncher.qml"
    ).read_text()
    workspace = (
        SHELL_ROOT / "qml" / "workspace" / "PaneWorkspace.qml"
    ).read_text()
    markers = (
        "id: applicationLauncherButton",
        "id: realtimeContainer",
        "id: runningApplicationRow",
        "id: paneRow",
        "id: clockLabel",
    )
    positions = tuple(launcher.index(marker) for marker in markers)
    assert positions == tuple(sorted(positions))
    assert "SystemClock {" in launcher
    assert "precision: SystemClock.Minutes" in launcher
    assert "implicitHeight: launcherRow.implicitHeight + 4" in launcher
    assert "anchors.margins: 2" in launcher
    assert launcher.count("Layout.topMargin: 4") == 4
    assert "property bool shelfOpen: false" in launcher
    assert "id: shelfSurface" in launcher
    assert "id: shelfHover" in launcher
    assert launcher.count("parent: shelfSurface") == 2
    assert "id: shelfHideTimer" in launcher
    assert "interval: 250" in launcher
    assert "enabled: root.shelfOpen" in launcher
    assert "opacity: root.shelfOpen ? 1 : 0" in launcher
    assert "visible: root.shelfOpen\n        z: 0" in launcher
    assert "opacity: root.shelfOpen ? 1 : 0\n        z: 1" in launcher
    assert "ToolTip.visible: hovered" not in launcher
    assert "DesktopEntries.applications" in application_launcher
    assert "entry.execute()" in application_launcher
    assert "\nPopupWindow {" in application_launcher
    assert "required property Item anchorItem" in application_launcher
    assert "anchorItem: applicationLauncherButton" in launcher
    assert "item: root.anchorItem" in application_launcher
    assert "edges: Edges.Top | Edges.Left" in application_launcher
    assert "gravity: Edges.Top | Edges.Right" in application_launcher
    assert "grabFocus: true" in application_launcher
    assert "Qt.FramelessWindowHint" not in application_launcher
    assert 'title: "Obsidience Applications"' not in application_launcher
    assert "Keys.priority: Keys.BeforeItem" in application_launcher
    assert "ApplicationLauncher {" in launcher
    assert "shelfWidth: root.width" in launcher
    assert "ApplicationLauncher {" not in workspace
    assert "model: root.runningApplications" in launcher
    applications_pane = (
        SHELL_ROOT / "qml" / "panes" / "applications" / "ApplicationsPane.qml"
    ).read_text()
    assert '"/api/applications"' in applications_pane
    assert '"/api/applications/search?q="' in applications_pane
    assert '"/api/applications/" + action' in applications_pane
    assert 'paneId: "applications"' in workspace
    assert '"label": "Applications"' in workspace


def test_pane_registry_is_the_single_source_for_titles_and_icons() -> None:
    workspace = (
        SHELL_ROOT / "qml" / "workspace" / "PaneWorkspace.qml"
    ).read_text()
    launcher = (
        SHELL_ROOT / "qml" / "workspace" / "PaneLauncher.qml"
    ).read_text()
    shell_icon = (
        SHELL_ROOT / "qml" / "components" / "visual" / "ShellIcon.qml"
    ).read_text()
    definitions = workspace.split(
        "readonly property var paneDefinitions", 1
    )[1].split("Variants {", 1)[0]
    assert definitions.count('"icon":') == 14
    assert '"label": "Chat"' in definitions
    assert '"label": "Applications"' in definitions
    assert '"title": "Chat"' in definitions
    assert '"title": "Executive"' not in definitions
    assert "glyph: String(paneButton.modelData.icon" in launcher
    assert "function paneIcon" not in launcher
    assert "Canvas {" in shell_icon
    assert '["reader", "source", "models"]' in shell_icon
    assert 'function paintReader(context)' in shell_icon


def test_window_state_and_activation_use_one_bounded_shell_transport() -> None:
    server = (
        SHELL_ROOT / "qml" / "api" / "ShellCommandServer.qml"
    ).read_text()
    launcher = (
        SHELL_ROOT / "qml" / "workspace" / "PaneLauncher.qml"
    ).read_text()
    observer = (
        SHELL_ROOT / "adapter" / "kwin" / "observer.js"
    ).read_text()
    host = (
        SHELL_ROOT / "adapter" / "windows" / "host.py"
    ).read_text()
    transport = (
        SHELL_ROOT / "adapter" / "windows" / "transport.py"
    ).read_text()
    model = (
        SHELL_ROOT / "adapter" / "windows" / "model.py"
    ).read_text()
    service = (
        SHELL_ROOT / "systemd" / "obsidience-shell-window-adapter.service"
    ).read_text()
    target = (
        SHELL_ROOT / "systemd" / "obsidience-shell-session.target"
    ).read_text()

    assert "KWinSurfaceWindows" in host
    assert '"type": "window.state.publish"' in model
    assert '"type": "application.state"' in server
    assert 'event.type === "application.state"' in launcher
    assert '"type": "window.activate"' in launcher
    assert 'command.type !== "window.activate"' in server
    assert '"window_id": entry.window_id' in launcher
    assert '"surface_id": surfaceId' in launcher
    assert "windowStates[surfaceId]" in server
    assert "for (const surfaceId of Object.keys(windowStates))" in server
    assert "activateWindow" not in observer
    assert "closeWindow" not in observer
    assert "/usr/bin/python -m obsidience.shell.adapter.windows.host" in service
    assert "obsidience-shell-window-adapter.service" in target


def test_graph_settings_live_in_one_sectioned_settings_pane_without_a_second_store() -> None:
    settings = (
        SHELL_ROOT / "qml" / "panes" / "settings" / "SettingsPane.qml"
    ).read_text()
    tuning = (
        SHELL_ROOT / "qml" / "panes" / "settings" / "graph" / "GraphSettings.qml"
    ).read_text()
    portrait = (
        SHELL_ROOT
        / "qml"
        / "panes"
        / "settings"
        / "graph"
        / "GraphStylePortrait.qml"
    ).read_text()
    workspace_settings = (
        SHELL_ROOT
        / "qml"
        / "panes"
        / "settings"
        / "workspace"
        / "WorkspaceSettings.qml"
    ).read_text()
    command_server = (
        SHELL_ROOT / "qml" / "api" / "ShellCommandServer.qml"
    ).read_text()
    workspace = (
        SHELL_ROOT / "qml" / "workspace" / "PaneWorkspace.qml"
    ).read_text()
    renderer_client = (
        PROJECT_ROOT
        / "obsidience"
        / "ui"
        / "src"
        / "renderer"
        / "src"
        / "lib"
        / "shell-client.ts"
    ).read_text()
    renderer_store = (
        PROJECT_ROOT
        / "obsidience"
        / "ui"
        / "src"
        / "renderer"
        / "src"
        / "lib"
        / "graph-tuning.ts"
    ).read_text()

    assert 'text: "GRAPH"' in tuning
    assert 'text: "PROFILE"' in tuning
    assert "displayText: root.graphOptions.length" in tuning
    assert "text: graphSelector.displayText.toUpperCase()" in tuning
    assert "text: profileSelector.displayText.toUpperCase()" in tuning
    assert 'if (role === "library") return title' in tuning
    assert 'width: 144' in tuning
    assert 'profileOptions: profiles.concat(["New profile…"])' in tuning
    assert 'send("graph.profile.select"' in tuning
    assert 'send("graph.profile.create"' in tuning
    assert 'groups = ["Display"].concat(nextGroups)' in tuning
    assert 'text: "GRAPH SURFACE"' in tuning
    assert 'send("graph.display.request")' in tuning
    assert 'send("graph.display.select", {"surface_id": surfaceId})' in tuning
    assert "Per-Agent placement comes later" in tuning
    assert 'root.send("graph.thinking.test")' in tuning
    assert 'property string activeSection: "graph"' in settings
    assert '{"id": "graph", "label": "Graph"' in settings
    assert '{"id": "workspace", "label": "Workspace"' in settings
    assert "GraphSettings {}" in settings
    assert "WorkspaceSettings {}" in settings
    assert 'text: "PANE GRID"' in workspace_settings
    assert "property int paneGridSize: 10" in workspace_settings
    assert "property int minimumPaneGridSize: 1" in workspace_settings
    assert "property int maximumPaneGridSize: 100" in workspace_settings
    assert 'send("workspace.state.request")' in workspace_settings
    assert 'send("workspace.grid.set", {"pane_grid_size": next})' in workspace_settings
    assert 'message.type !== "workspace.state"' in workspace_settings
    assert "SpinBox {" in workspace_settings
    assert "FileView" not in workspace_settings
    assert "StandardPaths" not in workspace_settings
    assert '"type": "workspace.state"' in command_server
    assert 'command.type === "workspace.state.request"' in command_server
    assert 'command.type === "workspace.grid.set"' in command_server
    assert "surfaceLayout.commitPaneGridSize(command.pane_grid_size)" in command_server
    assert "GraphStylePortrait {" in tuning
    assert "ToolTip.text:" in tuning
    assert "resetArmed" in tuning
    assert '"CONFIRM" : "RESET"' in tuning
    assert "LIVE THREE.JS GRAPH SETTINGS" not in tuning
    assert "FileView" not in settings
    assert "FileView" not in tuning
    assert "StandardPaths" not in tuning

    save_body = tuning.split("function save()", 1)[1].split(
        "function applySelection", 1
    )[0]
    assert "savePending = true" in save_body
    assert "savedTuning =" not in save_body

    for command in (
        "graph.state.request",
        "graph.tuning.preview",
        "graph.tuning.save",
        "graph.profile.select",
        "graph.profile.create",
        "graph.thinking.test",
        "graph.selection.publish",
        "graph.display.request",
        "graph.display.select",
    ):
        assert command in tuning or command in renderer_client
        assert command in command_server or command == "graph.selection.publish"

    assert 'action === "profile.select"' in renderer_client
    assert 'action === "profile.create"' in renderer_client
    assert "selectGraphTuningProfile" in renderer_client
    assert "saveGraphTuningProfile" in renderer_client
    assert 'PROFILE_KEY = "obsidience.graph-tuning-profiles.v2"' in renderer_store
    assert "Object.keys(current.profiles).length >= 32" in renderer_store
    assert 'type: "graph.selection.publish"' in renderer_client
    assert '"type": "graph.selection"' in command_server
    assert '"type": "graph.display.state"' in command_server
    assert "surfaceLayout.commitGraphSurface(command.surface_id)" in command_server
    assert "selectedGraphSurfaceId" in renderer_client

    assert "Canvas {" in portrait
    assert 'color: "#67e8f9"' in tuning
    for field in ("articleStyle", "ringStyle", "coreStyle"):
        assert field in portrait
    assert '"label": "Settings", "title": "Settings", "icon": "settings"' in workspace
    assert '"title": "Graph Tuning"' not in workspace
    assert "defaultWidth: 800" in workspace
    assert "defaultHeight: 680" in workspace
    assert '"minWidth": 680, "minHeight": 440' in workspace


def test_one_kscreenlocker_event_quarantines_and_covers_every_surface() -> None:
    shell = (SHELL_ROOT / "qml" / "shell.qml").read_text()
    isolated = (SHELL_ROOT / "qml" / "surface.qml").read_text()
    lock_state = (SHELL_ROOT / "qml" / "api" / "LockState.qml").read_text()
    stage_content = (
        SHELL_ROOT / "qml" / "surfaces" / "stage" / "StageContent.qml"
    ).read_text()
    x11_stage = (
        SHELL_ROOT / "qml" / "surfaces" / "stage" / "X11Stage.qml"
    ).read_text()
    lock_graph = (SHELL_ROOT / "surfaces" / "lock" / "host.py").read_text()
    workspace = (SHELL_ROOT / "qml" / "workspace" / "PaneWorkspace.qml").read_text()
    canvas = (SHELL_ROOT / "qml" / "workspace" / "PaneCanvas.qml").read_text()
    launcher = (SHELL_ROOT / "qml" / "workspace" / "PaneLauncher.qml").read_text()
    wallpaper = (
        SHELL_ROOT / "lock" / "wallpaper" / "contents" / "ui" / "main.qml"
    ).read_text()
    metadata = json.loads(
        (SHELL_ROOT / "lock" / "wallpaper" / "metadata.json").read_text()
    )
    dbus_bridge = (SHELL_ROOT / "input" / "dbus_bridge.py").read_text()
    router = (SHELL_ROOT / "input" / "router.py").read_text()
    bridge_unit = (SHELL_ROOT / "systemd" / "dp4-edge-dbus.service").read_text()
    router_unit = (SHELL_ROOT / "systemd" / "dp4-edge-bridge.service").read_text()

    assert "property LockState lockState: LockState {}" in shell
    assert "property LockState lockState: LockState {}" in isolated
    assert "!lockState.active && !fullscreenState.active" in shell
    assert shell.count("locked: root.lockState.active") == 2
    assert isolated.count("locked: root.lockState.active") == 2
    assert '"/obsidience-shell/lock-state"' in lock_state
    assert "property bool active: true" in lock_state
    assert 'active = stateFile.text().trim() !== "0"' in lock_state
    assert "required property bool locked" in workspace
    assert "visible: hasLocalPane && !locked" in canvas
    assert "focusable: hasLocalPane && !locked" in canvas
    assert "visible: !locked" in launcher
    assert "visible: !content.locked" in stage_content
    assert "aboveWindows: locked" in x11_stage
    assert "mask: Region {}" in x11_stage
    assert "QtWebEngine" not in x11_stage
    assert "WebKit2.WebView" in lock_graph
    assert "input_shape_combine_region(cairo.Region(), 0, 0)" in lock_graph
    assert 'return "lock-graph" if selected else "lock-solid"' in lock_graph
    assert 'return "desktop-graph" if selected else "hidden"' in lock_graph

    assert metadata["KPackageStructure"] == "Plasma/Wallpaper"
    assert metadata["KPlugin"]["Id"] == "org.obsidience.lockgraph"
    assert "import QtWebEngine" in wallpaper
    assert "WebEngineView" in wallpaper
    assert "surface_id=samsung&lock=1" in wallpaper
    assert "authenticator" not in wallpaper.lower()
    assert "password" not in wallpaper.lower()

    assert 'signal_name="AboutToLock"' in dbus_bridge
    assert 'signal_name="ActiveChanged"' in dbus_bridge
    assert "screen_saver.GetActive()" in dbus_bridge
    assert "def lock(self)" in router
    assert "def unlock(self)" in router
    assert 'if command == "lock"' in router
    assert 'if command == "unlock"' in router
    assert "if self.locked:" in router
    assert "BindsTo=dp4-edge-dbus.service" in router_unit
    assert "After=dp4-edge-dbus.service" in router_unit
    assert "ExecStartPost=/usr/bin/systemctl --user --no-block start dp4-edge-bridge.service" in bridge_unit
    assert "ExecStopPost=/usr/bin/systemctl --user --no-block stop dp4-edge-bridge.service" in bridge_unit


def test_pane_shortcut_move_is_atomic_and_has_one_owner_per_display_path() -> None:
    command_server = (
        SHELL_ROOT / "qml" / "api" / "ShellCommandServer.qml"
    ).read_text()
    drag_session = (
        SHELL_ROOT / "qml" / "workspace" / "PaneDragSession.qml"
    ).read_text()
    canvas = (
        SHELL_ROOT / "qml" / "workspace" / "PaneCanvas.qml"
    ).read_text()
    adapter = (SHELL_ROOT / "adapter" / "kwin" / "surface_edges.js").read_text()
    dbus_adapter = (SHELL_ROOT / "input" / "dbus_bridge.py").read_text()
    move_client = (SHELL_ROOT / "input" / "move_pane.py").read_text()
    input_router = (SHELL_ROOT / "input" / "router.py").read_text()
    move = command_server.split("function movePane", 1)[1].split(
        "function handlePaneCommand", 1
    )[0]

    assert "Shortcut {" not in canvas
    assert "dragSession.activatePane(placement)" in canvas
    assert '"type": "pane.activate"' in drag_session
    assert '"surface_id": placement.surfaceId' in drag_session
    assert '"expected_revision": placement.revision' in drag_session
    assert 'command.type === "pane.move_active"' in command_server
    assert "activePaneBySurface" in command_server
    assert "paneWorkspace.topPlacement(surfaceId)" in command_server
    assert "placement.open !== true" in move
    assert "surfaceLayout.moveRoute(" in move
    assert "paneWorkspace.presentPaneOn(" in move
    assert '"type": "pane.move_active"' in move_client
    assert '"source_surface_id": surface_id' in move_client
    assert 'subprotocols=[SUBPROTOCOL]' in move_client
    assert "def MovePane(self, surface_id: str, direction: str)" in dbus_adapter
    assert "PANE_MOVE_CLIENT" in dbus_adapter
    assert adapter.count("registerShortcut(") == 4
    assert '"Meta+Shift+Left"' in adapter
    assert '"Meta+Shift+Right"' in adapter
    assert '"Meta+Shift+Up"' in adapter
    assert '"Meta+Shift+Down"' in adapter
    assert '"MovePane"' in adapter
    assert "PANE_MOVE_DIRECTIONS" in input_router
    assert "consumed_pane_move_keys" in input_router
    assert "self.pane_mover(surface_id, direction)" in input_router
    assert "PANE_MOVE_CLIENT" in input_router
    assert "router" not in move.lower()
    assert "drag-start" not in command_server
    assert "drag-route" not in command_server
    assert "obsidience-pane-drag" not in command_server


def test_reader_explorers_share_one_native_dock_layout() -> None:
    workspace = (
        SHELL_ROOT / "qml" / "workspace" / "PaneWorkspace.qml"
    ).read_text()
    pane = (SHELL_ROOT / "qml" / "workspace" / "PaneItem.qml").read_text()
    layout = (
        SHELL_ROOT / "qml" / "workspace" / "PaneDockLayout.qml"
    ).read_text()
    host = (
        SHELL_ROOT / "qml" / "workspace" / "PaneDockHost.qml"
    ).read_text()
    stack = (
        SHELL_ROOT / "qml" / "workspace" / "PaneDockStack.qml"
    ).read_text()
    header = (
        SHELL_ROOT / "qml" / "workspace" / "PaneModuleHeader.qml"
    ).read_text()
    command_server = (
        SHELL_ROOT / "qml" / "api" / "ShellCommandServer.qml"
    ).read_text()
    knowledge = (
        SHELL_ROOT / "qml" / "panes" / "knowledge" / "KnowledgePane.qml"
    ).read_text()
    source = (
        SHELL_ROOT / "qml" / "panes" / "source" / "SourcePane.qml"
    ).read_text()
    reader = (
        SHELL_ROOT / "qml" / "panes" / "reader" / "ReaderPane.qml"
    ).read_text()

    assert 'schema: "obsidience.pane-dock-layout.v1"' in layout
    assert '"knowledge": {' in layout and '"source": {' in layout
    assert '"host_pane_id": "reader"' in layout
    assert '"side": "left"' in layout and '"side": "right"' in layout
    assert '"collapsed": false' in layout
    assert '"/obsidience-shell/pane-dock-layout.json"' in layout
    assert "atomicWrites: true" in layout and "watchChanges: true" in layout
    assert "property PaneDockLayout dockLayout" in workspace
    assert 'root.placement.paneId === "reader"' in pane
    assert "PaneDockHost {" in pane
    assert host.count("PaneDockStack {") == 2
    assert '"Dock left · top"' in host
    assert '"Dock left · bottom"' in host
    assert '"Dock right · top"' in host
    assert '"Dock right · bottom"' in host
    assert "availableWidth * 0.30" in stack
    assert "Math.min(380, Math.max(240" in stack
    assert "root.width - collapsedRail.width" in stack
    assert "activeArea.height / Math.max" in stack
    assert 'baseCommand("pane.dock")' in header
    assert 'baseCommand("pane.float")' in header
    assert 'baseCommand("pane.collapse")' in header
    assert "enabled: root.docked" in header
    assert "hoverEnabled: root.docked" in header
    assert "visible: root.docked" in header
    assert 'command.type === "pane.expand"' in command_server
    assert "paneWorkspace.presentPaneOn" in command_server
    assert "Electron" not in host + stack + header + reader + knowledge + source
    assert 'color: "#bf020a12"' in knowledge
    assert 'color: "#c708050f"' in source
    assert 'textFormat: Text.MarkdownText' in reader
    assert 'root.sourceMode ? 1100 : root.indexArticle ? 920 : 720' in reader
    assert '"SYSTEM"' in source
    assert 'title: "Knowledge"' in knowledge


def test_surface_edge_adapter_is_execution_attested_and_cache_safe() -> None:
    adapter = (SHELL_ROOT / "adapter" / "kwin" / "surface_edges.js").read_text()
    loader = (SHELL_ROOT / "adapter" / "kwin" / "load_surface_edges.sh").read_text()
    dbus_adapter = (SHELL_ROOT / "input" / "dbus_bridge.py").read_text()

    assert "registerScreenEdge(KWin.ElectricBottom, enterFromBottomEdge)" in adapter
    assert "workspace.cursorPosChanged.connect(trackBottomEdge)" in adapter
    assert adapter.count("registerShortcut(") == 4
    assert '"MovePane"' in adapter
    assert '"AdapterReady"' in adapter
    assert "assert(edgeRegistered" in adapter
    assert 'if [[ "${1:-}" == "--check" ]]' in loader
    assert 'generation="$(sha256sum "$script" | cut -c1-12)"' in loader
    assert 'script="${adapter_dir}/surface_edges.js"' in loader
    assert ".local/share/kwin/scripts" not in loader
    assert "for attempt in 1 2" in loader
    assert "failed_names=()" in loader
    assert "did not execute its readiness handshake" in loader
    assert "def AdapterReady(self, token: str)" in dbus_adapter
    assert "def MovePane(self, surface_id: str, direction: str)" in dbus_adapter


def test_login_entry_installs_as_a_greeter_readable_file() -> None:
    desktop = (SHELL_ROOT / "session" / "obsidience.desktop").read_text()
    installer = (SHELL_ROOT / "session" / "install-session").read_text()
    assert "TryExec=" not in desktop
    assert "session_dir=/usr/local/share/wayland-sessions" in installer
    assert 'install -o root -g root -m 0644 "$session_source" "$session_target"' in installer
    assert "chmod" not in installer
    assert "/home/wissenschafter" not in installer


def test_noctalia_boundary_is_pinned_and_visual_neutral() -> None:
    manifest = json.loads((SHELL_ROOT / "REUSE_MANIFEST.json").read_text())
    noctalia = manifest["upstreams"][0]
    assert noctalia["commit"] == "74e6c2790dd8f39bf496e90e479a9ae370846eed"
    assert noctalia["license"] == "MIT"
    assert len(noctalia["selected_sources"]) == 4
    excluded = noctalia["adaptation"].lower()
    assert all(word in excluded for word in ("renderer", "themes", "assets", "plugins"))
    packages = {
        upstream["name"]: upstream.get("package")
        for upstream in manifest["upstreams"]
    }
    assert packages["Quickshell"] == "quickshell 0.3.0-2.1"
    assert packages["gtk-layer-shell"] == "gtk-layer-shell 0.10.1-1.1"
    assert packages["WebKitGTK"] == "webkit2gtk-4.1 2.52.4-1"
    assert packages["PyGObject"] == "python-gobject 3.56.3-1"
    assert packages["QMLTermWidget"] == "qmltermwidget 2.0.0.git1-1.1"
    assert packages["Qt WebSockets"] == "qt6-websockets 6.11.1-1.1"
    assert packages["KScreenLocker"] == "kscreenlocker 6.6.5-1.1"
    assert packages["Qt WebEngine"] == "qt6-webengine 6.11.1-2"
    observer = (SHELL_ROOT / "adapter" / "kwin" / "observer.js").read_text()
    assert BUS_NAME in observer
    assert "activateWindow" not in observer
    assert "closeWindow" not in observer
    assert "MoveMouse" not in observer


def test_window_feed_is_bounded_and_rejects_malformed_rows() -> None:
    field = "\x1e"
    record = field.join(("id", "app", "Title", "desktop", "HDMI-A-1"))
    assert parse_window_list(record)[0].title == "Title"
    assert parse_window_list(field.join(("bad", "row"))) == ()
    assert parse_window_list("x" * 128_001) == ()


def test_every_pane_uses_the_generic_surface_placement_contract() -> None:
    workspace = (
        PROJECT_ROOT
        / "obsidience"
        / "ui"
        / "src"
        / "renderer"
        / "src"
        / "components"
        / "themes"
        / "obsidience"
        / "workspace"
        / "workspace-state.ts"
    ).read_text()
    assert "surfaceId: SurfaceId" in workspace
    assert "placePaneOnSurface" in workspace
    assert "readerSurface" not in workspace
    assert "ReaderSurface" not in workspace


def test_native_qml_uses_the_supported_embedded_javascript_surface() -> None:
    qml_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (SHELL_ROOT / "qml").rglob("*.qml")
    )
    assert ".flatMap(" not in qml_sources


def test_native_terminal_is_one_tmux_view_inside_the_generic_pane() -> None:
    terminal = (
        SHELL_ROOT / "qml" / "panes" / "terminal" / "TerminalPane.qml"
    ).read_text()
    attach = (
        SHELL_ROOT
        / "qml"
        / "panes"
        / "terminal"
        / "attach-shared-tmux"
    ).read_text()
    samsung = (SHELL_ROOT / "qml" / "shell.qml").read_text()
    isolated = (SHELL_ROOT / "qml" / "surface.qml").read_text()
    workspace = (
        SHELL_ROOT / "qml" / "workspace" / "PaneWorkspace.qml"
    ).read_text()
    host = (SHELL_ROOT / "systemd" / "obsidience-shell-host.service").read_text()

    assert "import QMLTermWidget 2.0" in terminal
    assert "import QtWebSockets" in terminal
    assert "QMLTermWidget {" in terminal
    assert "QMLTermSession {" in terminal
    assert "anchors.fill: parent" in terminal
    assert "anchors.margins: 4" in terminal
    assert "pixelSize: 14" in terminal
    assert 'family: "JetBrains Mono"' in terminal
    assert "letterSpacing: 0.25" not in terminal
    assert "lineSpacing: 0" in terminal
    assert "useFBORendering: false" in terminal
    assert "fitTerminalFont" not in terminal
    assert "fittedLetterSpacing" not in terminal
    assert "fittedLineSpacing" not in terminal
    assert "width / 62" not in terminal
    assert "height / 30" not in terminal
    assert 'shellProgram: "/home/wissenschafter/Projects/obsidience/' in terminal
    assert 'url: "ws://127.0.0.1:8765/ws/trace"' in terminal
    assert "slice(-500)" in terminal
    assert '"snapshot"' in terminal
    assert '"entry"' in terminal
    assert "node-pty" not in terminal
    assert "xterm" not in terminal.lower()
    assert "Electron" not in terminal
    assert 'tmux=/usr/bin/tmux' in attach
    assert 'new-session -d -t =codex -s obsidience-ui' in attach
    assert "display-message -p -t '=obsidience-ui:'" in attach
    assert 'detach-client -s =obsidience-ui' in attach
    assert "window-size largest" in attach
    assert 'attach-session -t =obsidience-ui' in attach
    assert "ignore-size" not in attach
    assert "new-window" not in attach
    assert "rename-window" not in attach
    assert "respawn-pane" not in attach
    assert "kill-pane" not in attach
    assert "kill-session" not in attach
    assert "codex exec" not in attach.lower()
    assert "codex resume" not in attach.lower()
    assert "PaneWorkspace {" in samsung
    assert "PaneWorkspace {" in isolated
    assert "property Component terminalComponent: Component { TerminalPane {} }" in workspace
    assert '"label": "Terminal"' in workspace
    assert '"component": terminalComponent' in workspace
    assert "initial-terminal-placement.json" in host
    assert not (
        PROJECT_ROOT / "obsidience" / "ui" / "src" / "main" / "terminal"
        / "local-terminal.ts"
    ).exists()
    assert not (
        PROJECT_ROOT / "obsidience" / "ui" / "src" / "renderer" / "src"
        / "panes" / "terminal-pane.tsx"
    ).exists()
    ui_package = json.loads(
        (PROJECT_ROOT / "obsidience" / "ui" / "package.json").read_text()
    )
    assert "node-pty" not in ui_package.get("dependencies", {})
    assert "@xterm/xterm" not in ui_package["devDependencies"]
    assert "@xterm/addon-fit" not in ui_package["devDependencies"]
