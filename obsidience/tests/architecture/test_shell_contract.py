"""Physical contract for the native Shell module."""

from __future__ import annotations

import json
from pathlib import Path

import tomllib

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
            "obsidience/shell/qml/lock/LockController.qml",
            "obsidience/shell/lock/pam.d/obsidience",
            "obsidience/shell/adapter/quickshell/build-runtime",
            "obsidience/shell/adapter/quickshell/patches/0001-satisfy-qtwebengine-host-contract.patch",
            "obsidience/shell/adapter/quickshell/patches/0002-guard-session-lock-reentrancy.patch",
            "obsidience/shell/adapter/quickshell/patches/0003-notify-session-unlock.patch",
            "obsidience/shell/adapter/hyprland/hyprland.lua",
            "obsidience/shell/adapter/hyprland/layout.lua",
            "obsidience/shell/idle/hypridle.conf",
            "obsidience/shell/session/greetd.toml",
            "obsidience/shell/session/obsidience-shell-login",
            "obsidience/shell/session/restart-shell",
            "obsidience/shell/session/session-lock",
            "obsidience/shell/surfaces/knowledge/host.py",
            "obsidience/shell/adapter/windows/host.py",
            "obsidience/shell/theme/apply.py",
        ],
        "source_roots": ["obsidience/shell"],
        "projections": ["obsidience/state/system/applications/obsidience"],
        "system_package_manifest": "obsidience/shell/system-packages.toml",
    }

def test_one_quickshell_host_owns_all_three_logical_surfaces() -> None:
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
    assert 'usbOutputName: "DP-8"' in shell_api
    assert 'dp4OutputName: "HDMI-A-2"' in shell_api
    assert "property ShellApi shellApi: ShellApi {}" in shell
    assert shell.count("Quickshell.screens.filter") == 3
    assert shell.count("PaneWorkspace {") == 1
    assert shell.count("Stage {") == 3
    assert shell.count("Variants {") == 3
    assert "targetScreens: root.workspaceScreens" in shell
    assert 'surfaceId: "samsung"' in shell
    assert 'surfaceId: "usb-c"' in shell
    assert 'surfaceId: "dp-4"' in shell
    assert shell.count("shellApi: root.shellApi") == 5
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
    assert shell.startswith(
        "//@ pragma AppId io.obsidience.shell\n"
        "//@ pragma NativeTextRendering\n"
    )
    assert not (SHELL_ROOT / "qml" / "panels" / "top" / "TopPanel.qml").exists()
    assert not (
        SHELL_ROOT / "qml" / "surfaces" / "background" / "Background.qml"
    ).exists()


def test_knowledge_graph_is_shell_owned_threejs_stage_content() -> None:
    stage = (SHELL_ROOT / "qml" / "surfaces" / "stage" / "Stage.qml").read_text()
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
    pane = (SHELL_ROOT / "qml" / "workspace" / "PaneWindow.qml").read_text()
    reader = (SHELL_ROOT / "qml" / "panes" / "reader" / "ReaderPane.qml").read_text()
    workspace = (
        SHELL_ROOT / "qml" / "workspace" / "PaneWorkspace.qml"
    ).read_text()
    shell = (SHELL_ROOT / "qml" / "shell.qml").read_text()

    assert "KnowledgeDesktop" not in stage
    assert not (SHELL_ROOT / "qml" / "surfaces" / "stage" / "X11Stage.qml").exists()
    assert not (SHELL_ROOT / "qml" / "surface.qml").exists()
    assert shell.count("PaneWorkspace {") == 1
    assert shell.count("Stage {") == 3
    assert "KnowledgeDesktop" not in pane
    assert 'gi.require_version("GtkLayerShell", "0.1")' in desktop
    assert 'gi.require_version("Gdk", "3.0")' in desktop
    assert 'gi.require_version("WebKit2", "4.1")' in desktop
    assert "WebKit2.WebView()" in desktop
    assert 'GtkLayerShell.set_namespace(window, "obsidience-knowledge-desktop")' in desktop
    assert "GtkLayerShell.Layer.BACKGROUND" in desktop
    assert "GtkLayerShell.KeyboardMode.ON_DEMAND" in desktop
    assert "window.set_accept_focus(True)" in desktop
    assert "GtkLayerShell.set_exclusive_zone(window, 0)" in desktop
    assert "display.get_n_monitors() != 1" not in desktop
    assert 'display.connect("monitor-added"' in desktop
    assert 'display.connect("monitor-removed"' in desktop
    assert 'monitor.connect("notify::geometry"' in desktop
    assert "Gio.File.new_for_path" in desktop
    assert 'monitor_directory(Gio.FileMonitorFlags.NONE, None)' in desktop
    assert 'record.get("graph_surface_id")' in desktop
    assert '"samsung": (5120, 1440)' in desktop
    assert '"usb-c": (1920, 1200)' in desktop
    assert '"dp-4": (1920, 550)' in desktop
    assert "self.window.hide()" in desktop
    assert "GtkLayerShell.set_monitor(self.window, monitor)" in desktop
    assert "self.window.show_all()" in desktop
    assert "self.window.destroy()" not in desktop
    assert "set_enable_webgl(True)" in desktop
    assert "HardwareAccelerationPolicy.ALWAYS" in desktop
    assert 'WEBKIT_DMABUF_RENDERER_FORCE_SHM", "1"' in desktop
    assert "was_unavailable" not in desktop
    assert "self.webview is not None and previous_surface_id != surface_id" in desktop
    assert "?surface=reader" not in desktop
    assert "?surface=knowledge" in desktop
    assert "Electron" not in desktop
    assert 'app.mount(' in api
    assert '"/shell/knowledge"' in api
    assert "class ShellKnowledgeFiles(StaticFiles):" in api
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
    assert 'selection: { kind: "article", ref, graph_id: graphId }' in shell_client
    assert "ShellCommandServer {" in shell
    fullscreen_state = (
        SHELL_ROOT / "qml" / "api" / "FullscreenState.qml"
    ).read_text()
    window_adapter = (
        SHELL_ROOT / "adapter" / "windows" / "hyprland.py"
    ).read_text()
    assert "property FullscreenState fullscreenState: FullscreenState {}" in shell
    assert "knowledgeVisible: !lockController.active" in shell
    assert "&& !fullscreenState.active" in shell
    assert "knowledgeVisible: root.knowledgeVisible" in shell
    assert '"/obsidience-shell-fullscreen.state"' in fullscreen_state
    assert "preload: true" in fullscreen_state
    assert "watchChanges: true" in fullscreen_state
    assert "onFileChanged: stateFile.reload()" in fullscreen_state
    assert "onLoaded: root.reloadState()" in fullscreen_state
    assert 'active = stateFile.text().trim() === "1"' in fullscreen_state
    assert 'active.get("fullscreen", 0)' in window_adapter
    assert '_FULLSCREEN_STATE.write_text("1\\n" if fullscreen else "0\\n"' in window_adapter
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
    assert '"surface_id": surfaceLayout.graphSurfaceId' in command_server
    assert '"visible": knowledgeVisible' in command_server
    assert "onKnowledgeVisibleChanged: broadcast(knowledgeState())" in command_server
    assert "onShellKnowledgeVisibility" in shell_client
    assert 'message.type !== "surface.state"' in shell_client
    assert "selectedSurfaceId === surfaceId && (lockMode || visible)" in renderer_surface
    assert 'const CENTERED_HUB = { x: 0.5, y: 0.5 } as const' in renderer_surface
    assert "{selectedSurfaceId === surfaceId ? (" in renderer_surface
    assert (
        "<GraphBackdrop visible={showGraph} lockMode={lockMode} "
        "hub={CENTERED_HUB} />"
        in renderer_surface
    )
    assert "{showGraph ? (\n        <GraphBackdrop" not in renderer_surface
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
    assert "labelMetadata={presentation.labelMetadata}" in graph_backdrop
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


def test_one_shell_host_shares_displays_pane_and_surface_layout() -> None:
    shell = (SHELL_ROOT / "qml" / "shell.qml").read_text()
    shell_api = (SHELL_ROOT / "qml" / "api" / "ShellApi.qml").read_text()
    layout = (SHELL_ROOT / "qml" / "api" / "SurfaceLayout.qml").read_text()
    tiler = (SHELL_ROOT / "qml" / "api" / "WorkspaceTiler.qml").read_text()
    placement = (SHELL_ROOT / "qml" / "workspace" / "PanePlacement.qml").read_text()
    pane = (SHELL_ROOT / "qml" / "workspace" / "PaneWindow.qml").read_text()
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
    compositor = (
        SHELL_ROOT / "adapter" / "hyprland" / "hyprland.lua"
    ).read_text()
    initial_placement = json.loads(
        (SHELL_ROOT / "state" / "placements" / "displays-placement.json")
        .read_text()
    )
    initial_reader_placement = json.loads(
        (SHELL_ROOT / "state" / "placements" / "reader-placement.json")
        .read_text()
    )
    initial_terminal_placement = json.loads(
        (SHELL_ROOT / "state" / "placements" / "terminal-placement.json")
        .read_text()
    )
    initial_layout = json.loads(
        (SHELL_ROOT / "state" / "initial-surface-layout.json").read_text()
    )

    assert shell.count("PaneWorkspace {") == 1
    assert shell.count("Stage {") == 3
    assert shell.count("Variants {") == 3
    assert workspace.count("PaneWindow {") == 1
    assert "PaneCanvas" not in workspace
    assert 'readonly property var paneDefinitions' in workspace
    assert workspace.count('"label":') == 15
    assert "targetScreens: root.workspaceScreens" in shell
    assert shell.count("shellApi: root.shellApi") == 5
    assert "SurfaceLayout surfaceLayout: SurfaceLayout {}" in shell_api
    assert "ShellTheme theme: ShellTheme {}" in shell_api
    assert "readonly property int paneTopInset: 0" in layout
    assert "property int paneGridSize: 10" in layout
    assert "function normalizePaneGridSize(value)" in layout
    assert "function snapPaneValue(value)" in layout
    assert "function clampPaneSize(value, minimum, maximum)" in layout
    assert "function commitPaneGridSize(value)" in layout
    assert '"pane_grid_size": paneGridSize' in layout
    assert '"samsung": {"columns": 8, "rows": 2}' in layout
    assert '"usb-c": {"columns": 3, "rows": 2}' in layout
    assert '"dp-4": {"columns": 4, "rows": 1}' in layout
    assert "readonly property int workspaceTileGap: 5" in layout
    assert "function validTileBounds(" in layout
    assert "function nearestTiledPaneRect(" in layout
    assert "function tiledPaneRect(" in layout
    assert "function initialBounds(" in tiler
    assert "function boundsForRect(" in tiler
    assert "function resizeBounds(" in tiler
    assert "function translateBounds(" in tiler
    assert "function rectForBounds(" in tiler
    assert "extent - gap * (count + 1)" in tiler
    assert "function commitWorkspaceTiling(" in layout
    assert '"workspace_tiling": workspaceTiling' in layout
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
    assert "FloatingWindow {" in pane
    assert "PaneFrame {" in pane
    assert "required property var paneDefinition" in pane
    assert 'root.placement.paneId === "reader"' in pane
    assert "? dockHostComponent : root.paneDefinition.component" in pane
    assert "DisplaysPane" not in pane
    assert "ReaderPane" not in pane
    assert 'title: "obsidience-pane:" + placement.paneId' in pane
    assert "screen: activeScreen" in pane
    assert "placement.open && !moduleDocked" in pane
    assert "onMoveRequested: root.startSystemMove()" in pane
    assert "onResizeRequested: edges => root.startSystemResize(edges)" in pane
    assert "readonly property var defaultTileRect:" in pane
    assert "readonly property int defaultGuideTolerance: 5" in pane
    assert "readonly property bool tiled: defaultTileRect !== null" in pane
    assert "readonly property bool tiledResizeEnabled:" in pane
    assert "surfaceLayout.tileResizeLimitPercent > 0" in pane
    assert "readonly property bool resizeControlsEnabled: !tiled" in pane
    assert 'return "right"' in pane
    assert 'return "bottom"' in pane
    assert "readonly property bool defaultSizeFeedbackEnabled:" in pane
    assert '!shellApi.surfaceLayout.oledModeEnabled' in pane
    assert "defaultWidthReached: root.defaultWidthReached" in pane
    assert "defaultHeightReached: root.defaultHeightReached" in pane
    assert "verticalDefaultGuideEdge: root.verticalDefaultGuideEdge" in pane
    assert "horizontalDefaultGuideEdge: root.horizontalDefaultGuideEdge" in pane
    assert "onClosed: placement.dismiss()" not in pane
    assert "placement.hydrated" in pane
    assert "placement.dismiss()" in pane
    assert "default property alias contentData: content.data" in frame
    assert "property bool resizeFeedbackActive: false" in frame
    assert "property int resizeFeedbackEdges: 0" in frame
    assert "readonly property bool widthResizeFeedback:" in frame
    assert "readonly property bool heightResizeFeedback:" in frame
    assert "id: verticalDefaultGuide" in frame
    assert "id: horizontalDefaultGuide" in frame
    assert "id: widthResizeHandle" in frame
    assert "id: heightResizeHandle" in frame
    assert 'visible: root.verticalDefaultGuideEdge !== ""' in frame
    assert 'visible: root.horizontalDefaultGuideEdge !== ""' in frame
    assert "onPressed: root.beginResize(root.verticalResizeEdge)" in frame
    assert "onPressed: root.beginResize(root.horizontalResizeEdge)" in frame
    assert "root.verticalResizeEdge | root.horizontalResizeEdge" in frame
    assert "? Qt.SizeFDiagCursor : Qt.SizeBDiagCursor" in frame
    assert "&& root.widthResizeFeedback" in frame
    assert "&& root.heightResizeFeedback" in frame
    assert "resizeFeedbackActive = true" in frame
    assert "width: 30" in frame
    assert "resizeFeedbackTimer.restart()" in frame
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
    assert "function surfaceForScreen(screen)" in workspace
    assert "function screenForSurface(surfaceId)" in workspace
    assert "function launcherOpenFor(surfaceId)" in workspace
    assert "function toggleLauncher(surfaceId)" in workspace
    assert "surfaceId: root.surfaceForScreen(modelData)" in workspace
    assert "screenForSurface(" in pane
    assert "startSystemMove()" in pane
    assert "startSystemResize(edges)" in pane
    assert "property var activeScreen: null" in pane
    assert "property bool screenTransitionPending: true" in pane
    assert "property int screenTransitionGeneration: 0" in pane
    assert "visible: paneVisible && activeScreen !== null" in pane
    assert "function selectSurfaceScreen()" in pane
    assert "const generation = screenTransitionGeneration" in pane
    assert "const target = surfaceScreen" in pane
    assert "target === null || screen === target" in pane
    assert "screenTransitionPending = true" in pane
    assert "generation !== screenTransitionGeneration" in pane
    assert "generation === screenTransitionGeneration" in pane
    assert "activeScreen = target" in pane
    assert "Component.onCompleted: selectSurfaceScreen()" in pane
    assert "onSurfaceScreenChanged: selectSurfaceScreen()" in pane
    assert "signal moveRequested()" in frame
    assert "signal resizeRequested(int edges)" in frame
    assert not (SHELL_ROOT / "qml" / "workspace" / "PaneCanvas.qml").exists()
    assert not (SHELL_ROOT / "qml" / "workspace" / "PaneItem.qml").exists()
    assert not (SHELL_ROOT / "qml" / "workspace" / "PaneDragSession.qml").exists()
    assert "function presentPaneOn(" in workspace
    assert "onPresentRequested:" in workspace
    assert "function placementFor(paneId)" in workspace
    assert "function definitionFor(paneId)" in workspace
    assert "authoritative: true" in workspace
    assert "authoritative: true" not in shell
    assert '"drag-start"' not in command_server
    assert '"drag-route"' not in command_server
    assert '"drag-cancel"' not in command_server
    assert "obsidience-pane-drag" not in command_server
    assert "paneWorkspace.placementFor(paneId)" in command_server
    assert "function observeModuleWindows()" in command_server
    observe_modules = command_server.split(
        "function observeModuleWindows()", 1
    )[1].split("function windowResult", 1)[0]
    assert observe_modules.index(
        "if (sessionLocked || moduleRestorePending)"
    ) < observe_modules.index(
        "placement.observeNative("
    )
    lock_change = command_server.split(
        "onSessionLockedChanged:", 1
    )[1].split("property Connections graphDisplayConnections", 1)[0]
    assert "moduleWindowBindings = ({})" in lock_change
    assert "moduleRestorePending = null" in lock_change
    assert "observeModuleWindows()" in lock_change
    assert "function moduleCandidateMatchesIntent(" in command_server
    assert "property var moduleWindowBindings: ({})" in command_server
    assert "property var moduleRestorePending: null" in command_server
    assert "function requestModuleRestore(" in command_server
    assert '"window.layout.restore.request" : "window.place.request"' in command_server
    assert "request.destination_surface_id = bounds.surface_id" in command_server
    assert "request.workspace_tiling = surfaceLayout.workspaceTilingState()" in command_server
    assert "function finishModuleRestore(token, success)" in command_server
    assert "function settlePendingModuleRestore()" in command_server
    assert "placement.sameTileBounds(" in command_server
    assert 'command.type === "window.layout.restore.result"' in command_server
    restore_request = command_server.split(
        "&& requestModuleRestore(", 1
    )[1].split("if (binding &&", 1)[0]
    assert "return" in restore_request
    assert '"restore_failed": success !== true' in command_server
    failed_restore = command_server.split(
        'command.type === "window.layout.restore.result"', 1
    )[1].split('command.type === "window.close.result"', 1)[0]
    assert "finishModuleRestore(" in failed_restore
    assert '"result_received": true' in failed_restore
    assert "settlePendingModuleRestore()" in failed_restore
    assert "observeModuleWindows()" in failed_restore
    place_result = command_server.split(
        'command.type === "window.place.result"', 1
    )[1].split('command.type === "window.layout.restore.result"', 1)[0]
    assert '"result_received": true' in place_result
    assert "settlePendingModuleRestore()" in place_result
    assert "finishModuleRestore(command.token, false)" in place_result
    state_publish = command_server.split(
        'command.type === "window.state.publish"', 1
    )[1].split('command.type === "window.activation.result"', 1)[0]
    assert state_publish.index("settlePendingModuleRestore()") < state_publish.index(
        "observeModuleWindows()"
    )
    assert 'window.window_kind !== "module"' in command_server
    assert "placement.observeNative(" in command_server
    binding_policy = command_server.split(
        "function moduleCandidateMatchesIntent(", 1
    )[1].split("function observeModuleWindows()", 1)[0]
    # A unique remapped address may be moved to its saved Surface before settling.
    assert "!binding || binding.window_id !== window.window_id" in binding_policy
    assert "return true" in binding_policy
    # An unchanged exact address adopts a native Surface move unless a new
    # shell-selected Surface is still pending.
    assert "placement.surfaceId === binding.surface_id" in binding_policy
    assert "|| state.surface_id === placement.surfaceId" in binding_policy
    assert "duplicates[paneId]" in command_server
    assert 'appId !== "io.obsidience.shell"' in command_server
    assert "window.module.place.request" not in command_server
    assert "window.module.place.result" not in command_server
    assert "modulePlacementRequests" not in command_server
    assert "delete moduleWindowBindings" not in command_server
    subscribe_window_block = command_server.split(
        'command.type === "window.adapter.subscribe"', 1
    )[1].split('command.type === "window.state.publish"', 1)[0]
    assert "moduleWindowBindings = ({})" not in subscribe_window_block
    for workspace_id, monitor in (
        ("1", "HDMI-A-1"),
        ("2", "HDMI-A-2"),
        ("3", "DP-8"),
    ):
        rule = compositor.split(
            f'workspace = "{workspace_id}"', 1
        )[1].split("})", 1)[0]
        assert f'monitor = "{monitor}"' in rule
        assert "persistent = true" in rule
        assert "default = true" in rule
    assert "function broadcastToPaneClients(message)" not in command_server
    assert "function activePlacement(surfaceId)" not in command_server
    assert "function movePane(socket, placement, direction)" not in command_server
    assert 'command.type === "pane.move_active"' not in command_server
    assert 'command.type === "pane.tile_active"' not in command_server
    assert 'command.type === "pane.tile_move_active"' not in command_server
    assert 'command.type === "pane.deactivate"' not in command_server
    assert 'command.type === "window.layout_active"' in command_server
    assert '"type": "window.layout.request"' in command_server
    assert 'command.type === "window.close_active"' in command_server
    assert '"type": "window.close.request"' in command_server
    assert 'current.window_kind === "module"' in command_server
    assert "StandardPaths.GenericStateLocation" in placement
    assert "StandardPaths.RuntimeLocation" not in placement
    assert "shellApi.surfaceLayout.clampPaneX(" in launcher
    assert "shellApi.surfaceLayout.clampPaneY(" in launcher
    assert "function tiledHandoffRect(" in layout
    assert "workspaceTiler.entryBounds(" in layout
    assert "function commitDrag(" not in placement
    assert "function commitGeometry(" in placement
    assert "function observeNative(" in placement
    assert '"tile_bounds": tileBounds' in placement
    assert "record.tile_home" not in placement
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
    assert 'com.tmog.taskmanager' not in workspace
    assert 'paneId: "camera"' in workspace
    assert 'paneId: "settings"' in workspace
    assert 'paneId: "tuning"' not in workspace
    assert 'stateFileName: paneId + "-placement.json"' in placement
    assert "function present()" in placement
    assert "function dismiss()" in placement
    assert 'record.surface_id !== "dp-4"' in placement
    assert 'schema: "obsidience.surface-layout.v1"' in layout
    assert initial_layout["workspace_tiling"] == {
        "samsung": {"columns": 8, "rows": 2},
        "usb-c": {"columns": 3, "rows": 2},
        "dp-4": {"columns": 4, "rows": 1},
    }
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
    assert "import Quickshell.Widgets" in frame
    assert "ClippingRectangle {" in frame
    assert "contentUnderBorder: true" in frame
    assert "color: root.theme.surface" in frame
    assert "border.width: 0" in frame
    assert "RectangularShadow {" not in frame
    assert "anchors.margins: -3" not in frame
    assert "required property bool active" not in frame
    assert "root.theme.inactiveBorder" not in frame
    assert "Qt5Compat.GraphicalEffects" not in frame
    assert "layer.effect: MultiEffect" not in frame
    assert "height: root.theme.titleHeight" in frame
    assert "color: root.theme.separator" in frame
    assert '"frame":' not in workspace
    assert 'readonly property string schema: "obsidience.shell-theme.v1"' in theme
    assert "watchChanges: true" in theme
    assert "onFileChanged: paletteFile.reload()" in theme
    assert shell.startswith(
        "//@ pragma AppId io.obsidience.shell\n"
        "//@ pragma NativeTextRendering\n"
    )
    assert not (SHELL_ROOT / "qml" / "surface.qml").exists()
    assert not (
        SHELL_ROOT / "systemd" / "obsidience-shell-surface-usbc.service"
    ).exists()
    assert not (
        SHELL_ROOT / "systemd" / "obsidience-shell-surface-dp4.service"
    ).exists()
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
    assert surfaces["samsung"]["backend"] == "hyprland-wayland"
    assert surfaces["samsung"]["display"] == "wayland"
    assert surfaces["samsung"]["output"] == "HDMI-A-1"
    assert surfaces["samsung"]["x_screen"] is None
    assert surfaces["usb-c"]["logical_width"] == 1920
    assert surfaces["usb-c"]["logical_height"] == 1200
    assert surfaces["usb-c"]["device_scale"] == 2
    assert surfaces["usb-c"]["backend"] == "hyprland-wayland"
    assert surfaces["usb-c"]["display"] == "wayland"
    assert surfaces["usb-c"]["output"] == "DP-8"
    assert surfaces["usb-c"]["x_screen"] is None
    assert surfaces["dp-4"]["logical_width"] == 1920
    assert surfaces["dp-4"]["logical_height"] == 550
    assert surfaces["dp-4"]["device_scale"] == 2
    assert surfaces["dp-4"]["backend"] == "hyprland-wayland"
    assert surfaces["dp-4"]["display"] == "wayland"
    assert surfaces["dp-4"]["output"] == "HDMI-A-2"
    assert surfaces["dp-4"]["x_screen"] is None

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
    assert definitions.count('"icon":') == 15
    assert '"label": "Hardware"' in definitions
    assert '"label": "Feeds"' in definitions
    assert '"label": "Connections"' not in definitions
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
    hyprland = (
        SHELL_ROOT / "adapter" / "windows" / "hyprland.py"
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

    assert "HyprlandSurfaceWindows" in host
    assert '"type": "window.state.publish"' in model
    assert '"type": "application.state"' in server
    assert 'event.type === "application.state"' in launcher
    assert '"type": "window.activate"' in launcher
    assert 'command.type !== "window.activate"' in server
    assert '"window_id": entry.window_id' in launcher
    assert '"surface_id": surfaceId' in launcher
    assert "windowStates[surfaceId]" in server
    assert "for (const surfaceId of Object.keys(windowStates))" in server
    assert 'hl.dsp.focus({{ window = "address:{window_id}" }})' in hyprland
    assert 'self._command("eval", f"hl.dispatch({expression})")' in hyprland
    assert 'command.type === "window.layout_active"' in server
    assert '"type": "window.layout.request"' in server
    assert 'command.type === "window.place"' in server
    assert '"type": "window.place.request"' in server
    assert 'result_type = "window.place.result"' in transport
    assert "self.store.exact_window(" in host
    assert "follow = false" in hyprland
    assert '"window.close.request"' in transport
    assert 'result_type = "window.close.result"' in transport
    assert "self.store.exact_active_window(" in host
    assert "self.store.wait_absent(" in host
    assert "self.hyprland.close(" in host
    assert 'self._layout_message(' in hyprland
    assert 'hl.dsp.window.close({{ window = "address:{window_id}" }})' in hyprland
    assert '"clients", "-j"' not in hyprland
    assert 'self._json("clients")' in hyprland
    assert ".socket2.sock" in hyprland
    assert "-m obsidience.shell.adapter.windows.host" in service
    assert "obsidience-shell-window-adapter.service" in target


def test_settings_sections_share_one_pane_without_a_second_store() -> None:
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
    input_settings = (
        SHELL_ROOT
        / "qml"
        / "panes"
        / "settings"
        / "input"
        / "InputSettings.qml"
    ).read_text()
    input_adapter = (
        SHELL_ROOT / "adapter" / "hyprland" / "input.py"
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
    assert '{"id": "input", "label": "Input"' in settings
    assert '{"id": "workspace", "label": "Workspace"' in settings
    assert "GraphSettings {}" in settings
    assert "InputSettings {}" in settings
    assert "WorkspaceSettings {}" in settings
    assert 'model: [\n                    {"id": "mouse", "label": "Mouse"},' in input_settings
    assert '{"id": "keyboard", "label": "Keyboard"}' in input_settings
    assert 'xhr.open("GET", apiBase + "/api/input")' in input_settings
    assert '"HARDWARE DPI"' in input_settings
    assert '"EFFECTIVE DPI"' in input_settings
    assert '"REPEAT RATE"' in input_settings
    assert '"CAPS LOCK"' in input_settings
    assert "FileView" not in input_settings
    assert "hyprctl" not in input_settings
    assert 'HYPRCTL = "/usr/bin/hyprctl"' in input_adapter
    assert '"schema": "obsidience.input.v1"' in input_adapter
    assert 'text: "PANE GRID"' in workspace_settings
    assert '"id": "tiling", "label": "Workspace tiling"' in workspace_settings
    assert 'text: "WORKSPACE TILING"' in workspace_settings
    assert "id: sectionRail" in workspace_settings
    assert "width: 144" in workspace_settings
    assert "height: 28" in workspace_settings
    assert "anchors.left: sectionRail.right" in workspace_settings
    assert '"#2667e8f9"' in workspace_settings
    assert '"#1467e8f9"' in workspace_settings
    assert 'width: modelData.id === "tiling" ? 156 : 112' not in workspace_settings
    assert "property int paneGridSize: 10" in workspace_settings
    assert "property int minimumPaneGridSize: 1" in workspace_settings
    assert "property int maximumPaneGridSize: 100" in workspace_settings
    assert 'send("workspace.state.request")' in workspace_settings
    assert 'send("workspace.grid.set", {"pane_grid_size": next})' in workspace_settings
    assert 'send("workspace.tiling.set", {' in workspace_settings
    assert "property var workspaceTiling: []" in workspace_settings
    assert 'message.type !== "workspace.state"' in workspace_settings
    assert "SpinBox {" in workspace_settings
    assert "FileView" not in workspace_settings
    assert "StandardPaths" not in workspace_settings
    assert '"type": "workspace.state"' in command_server
    assert 'command.type === "workspace.state.request"' in command_server
    assert 'command.type === "workspace.grid.set"' in command_server
    assert "surfaceLayout.commitPaneGridSize(command.pane_grid_size)" in command_server
    assert 'command.type === "workspace.tiling.set"' in command_server
    assert "surfaceLayout.commitWorkspaceTiling(" in command_server
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


def test_workspace_tile_behavior_uses_the_surface_layout_authority() -> None:
    layout = (SHELL_ROOT / "qml" / "api" / "SurfaceLayout.qml").read_text()
    command_server = (
        SHELL_ROOT / "qml" / "api" / "ShellCommandServer.qml"
    ).read_text()
    workspace_settings = (
        SHELL_ROOT
        / "qml"
        / "panes"
        / "settings"
        / "workspace"
        / "WorkspaceSettings.qml"
    ).read_text()
    initial = json.loads(
        (SHELL_ROOT / "state" / "initial-surface-layout.json").read_text()
    )

    assert initial["schema"] == "obsidience.surface-layout.v1"
    assert initial["tile_resize_limit_percent"] == 25
    assert initial["oled_mode_enabled"] is False
    assert initial["oled_shift_distance_px"] == 32
    assert initial["oled_travel_duration_seconds"] == 3600
    assert initial["oled_glow_rotation_hours"] == 3

    assert "readonly property int minimumTileResizeLimitPercent: 0" in layout
    assert "readonly property int maximumTileResizeLimitPercent: 25" in layout
    assert "readonly property int minimumOledShiftDistancePx: 1" in layout
    assert "readonly property int maximumOledShiftDistancePx: 50" in layout
    assert "readonly property int minimumOledTravelDurationSeconds: 60" in layout
    assert "readonly property int maximumOledTravelDurationSeconds: 86400" in layout
    assert "readonly property int minimumOledGlowRotationHours: 1" in layout
    assert "readonly property int maximumOledGlowRotationHours: 24" in layout
    assert "property int tileResizeLimitPercent: 25" in layout
    assert "property bool oledModeEnabled: false" in layout
    assert "property int oledShiftDistancePx: 32" in layout
    assert "property int oledTravelDurationSeconds: 3600" in layout
    assert "property int oledGlowRotationHours: 3" in layout
    assert "function normalizeTileResizeLimitPercent(value)" in layout
    assert "function normalizeOledShiftDistancePx(value)" in layout
    assert "function normalizeOledTravelDurationSeconds(value)" in layout
    assert "function normalizeOledGlowRotationHours(value)" in layout
    assert 'typeof record.oled_mode_enabled === "boolean"' in layout
    assert '"tile_resize_limit_percent": tileResizeLimitPercent' in layout
    assert '"oled_mode_enabled": oledModeEnabled' in layout
    assert '"oled_shift_distance_px": oledShiftDistancePx' in layout
    assert '"oled_travel_duration_seconds": oledTravelDurationSeconds' in layout
    assert '"oled_glow_rotation_hours": oledGlowRotationHours' in layout
    assert "function commitTileResizeLimitPercent(value)" in layout

    oled_commit = layout.split("function commitOledSettings(", 1)[1].split(
        "function commitWorkspaceTiling", 1
    )[0]
    assert 'typeof enabled !== "boolean"' in oled_commit
    assert "shiftDistancePx < minimumOledShiftDistancePx" in oled_commit
    assert "shiftDistancePx > maximumOledShiftDistancePx" in oled_commit
    assert "travelDurationSeconds < minimumOledTravelDurationSeconds" in oled_commit
    assert "travelDurationSeconds > maximumOledTravelDurationSeconds" in oled_commit
    assert "glowRotationHours < minimumOledGlowRotationHours" in oled_commit
    assert "glowRotationHours > maximumOledGlowRotationHours" in oled_commit
    assert oled_commit.count("revision += 1") == 1
    assert oled_commit.count("writeState()") == 1

    assert (
        '"tile_resize_limit_percent": surfaceLayout.tileResizeLimitPercent'
        in command_server
    )
    assert '"oled_mode_enabled": surfaceLayout.oledModeEnabled' in command_server
    assert (
        '"oled_shift_distance_px": surfaceLayout.oledShiftDistancePx'
        in command_server
    )
    assert (
        '"oled_travel_duration_seconds": '
        "surfaceLayout.oledTravelDurationSeconds"
        in command_server
    )
    assert (
        '"oled_glow_rotation_hours": surfaceLayout.oledGlowRotationHours'
        in command_server
    )
    assert 'command.type === "workspace.tile.limit.set"' in command_server
    assert "surfaceLayout.commitTileResizeLimitPercent(" in command_server
    assert 'command.type === "workspace.oled.set"' in command_server
    assert "surfaceLayout.commitOledSettings(" in command_server

    assert '{"id": "behavior", "label": "Tile behavior"}' in workspace_settings
    assert 'text: "TILE BEHAVIOR"' in workspace_settings
    assert 'text: "EXPAND / CONTRACT LIMIT"' in workspace_settings
    assert 'text: "OLED MODE"' in workspace_settings
    assert 'text: "MAXIMUM DRIFT"' in workspace_settings
    assert 'text: "BORDER GLOW ROTATION"' in workspace_settings
    assert (
        "Per-seam drift can change a pane by up to twice its value"
        in workspace_settings
    )
    assert "Travel is nominal active time" in workspace_settings
    assert "motion starts at center" in workspace_settings
    assert "chrome stays consistent on every Surface" in workspace_settings
    assert 'send("workspace.tile.limit.set", {' in workspace_settings
    assert 'send("workspace.oled.set", {' in workspace_settings
    assert 'typeof message.oled_mode_enabled !== "boolean"' in workspace_settings
    assert "root.minimumTileResizeLimitPercent" in workspace_settings
    assert "root.maximumTileResizeLimitPercent" in workspace_settings
    assert "root.minimumOledShiftDistancePx" in workspace_settings
    assert "root.maximumOledShiftDistancePx" in workspace_settings
    assert "root.minimumOledTravelDurationSeconds" in workspace_settings
    assert "root.maximumOledTravelDurationSeconds" in workspace_settings
    assert "root.minimumOledGlowRotationHours" in workspace_settings
    assert "root.maximumOledGlowRotationHours" in workspace_settings
    assert "FileView" not in workspace_settings


def test_shell_owns_one_secure_graph_lock_with_pam_authentication() -> None:
    shell = (SHELL_ROOT / "qml" / "shell.qml").read_text()
    controller = (SHELL_ROOT / "qml" / "lock" / "LockController.qml").read_text()
    surface = (SHELL_ROOT / "qml" / "lock" / "LockSurface.qml").read_text()
    workspace = (SHELL_ROOT / "qml" / "workspace" / "PaneWorkspace.qml").read_text()
    pane_window = (SHELL_ROOT / "qml" / "workspace" / "PaneWindow.qml").read_text()
    pane_launcher = (SHELL_ROOT / "qml" / "workspace" / "PaneLauncher.qml").read_text()
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
    pam = (SHELL_ROOT / "lock" / "pam.d" / "obsidience").read_text()

    assert 'import "lock"' in shell
    assert "property LockController lockController: LockController {" in shell
    assert "shellApi: root.shellApi" in shell
    assert "!lockController.active" in shell
    assert shell.count("locked: root.lockController.active") == 3
    assert "required property bool locked" not in workspace
    assert "required property bool locked" not in pane_window
    assert "required property bool locked" not in pane_launcher
    assert "&& !locked" not in pane_window
    assert "active: root.paneVisible" in pane_window
    assert "visible: true" in pane_launcher
    assert "{selectedSurfaceId === surfaceId ? (" in renderer_surface
    assert "<GraphBackdrop visible={showGraph}" in renderer_surface
    assert not (SHELL_ROOT / "qml" / "api" / "LockState.qml").exists()
    assert not (SHELL_ROOT / "state" / "initial-unlocked-state").exists()

    assert "import Quickshell.Services.Pam" in controller
    assert "import Quickshell.Wayland" in controller
    assert "readonly property bool active: sessionLock.locked" in controller
    assert "readonly property bool secure: sessionLock.secure" in controller
    assert "sessionLock.locked = true" in controller
    assert "authenticating = pam.start()" in controller
    assert "PamContext {" in controller
    assert 'configDirectory: "/etc/pam.d"' in controller
    assert 'config: "obsidience"' in controller
    assert "result === PamResult.Success && sessionLock.secure" in controller
    assert "sessionLock.locked = false" in controller
    assert "WlSessionLock {" in controller
    assert "WlSessionLockSurface {" in controller
    assert "LockSurface {" in controller
    assert "graphSurfaceId: root.shellApi.surfaceLayout.graphSurfaceId" in controller
    assert 'target: "lock"' in controller
    assert "return root.requestLock()" in controller

    assert "import QtWebEngine" in surface
    assert "surfaceId === graphSurfaceId" in surface
    assert '"?surface=knowledge&surface_id="' in surface
    assert '"&lock=1"' in surface
    assert "WebEngineView {" in surface
    assert "active: root.showsGraph" in surface
    assert "visible: !root.showsGraph" in surface
    assert "enabled: false" in surface
    assert "echoMode: TextInput.Password" in surface
    assert "onAccepted: root.controller.tryUnlock()" in surface
    assert "onClicked: root.controller.tryUnlock()" in surface
    assert pam == "auth include system-auth\n"

    assert not (SHELL_ROOT / "input" / "dbus_bridge.py").exists()
    assert not (SHELL_ROOT / "lock" / "wallpaper" / "metadata.json").exists()
    assert not (
        SHELL_ROOT / "lock" / "wallpaper" / "contents" / "ui" / "main.qml"
    ).exists()


def test_pane_shortcut_move_is_atomic_and_has_one_owner_per_display_path() -> None:
    command_server = (
        SHELL_ROOT / "qml" / "api" / "ShellCommandServer.qml"
    ).read_text()
    pane_window = (
        SHELL_ROOT / "qml" / "workspace" / "PaneWindow.qml"
    ).read_text()
    compositor = (
        SHELL_ROOT / "adapter" / "hyprland" / "hyprland.lua"
    ).read_text()
    move_client = (SHELL_ROOT / "input" / "move_pane.py").read_text()
    assert "FloatingWindow {" in pane_window
    assert "startSystemMove()" in pane_window
    assert "startSystemResize(edges)" in pane_window
    assert not (SHELL_ROOT / "qml" / "workspace" / "PaneCanvas.qml").exists()
    assert not (SHELL_ROOT / "qml" / "workspace" / "PaneDragSession.qml").exists()
    assert 'command.type === "pane.move_active"' not in command_server
    assert "activePaneBySurface" not in command_server
    assert "function movePane(" not in command_server
    assert '"pane.move_active"' not in move_client
    assert '"pane.tile_active"' not in move_client
    assert '"pane.tile_move_active"' not in move_client
    assert '"pane.dismiss_active"' not in move_client
    assert '"source_surface_id": surface_id' in move_client
    assert '"window.layout_active"' in move_client
    assert '"window.close_active"' in move_client
    assert 'command.type === "pane.dismiss_active"' not in command_server
    assert 'command.type === "window.close_active"' in command_server
    assert '"type": "window.close.request"' in command_server
    assert 'event.get("reason") == "no_active_pane"' not in move_client
    assert 'subprotocols=[SUBPROTOCOL]' in move_client
    assert 'command.type === "focus.cycle"' not in command_server
    assert '"type": "pane.focus.request"' not in command_server
    assert "function focusCandidates(surfaceId)" not in command_server
    assert 'title: "obsidience-pane:" + placement.paneId' in pane_window
    assert '"type": "focus.cycle"' not in move_client
    assert 'event.get("type") == "focus.cycle.result"' not in move_client
    assert compositor.count('hl.bind("ALT + TAB"') == 1
    assert compositor.count('hl.bind("ALT + SHIFT + TAB"') == 1
    assert 'hl.bind("ALT + TAB", hl.dsp.window.cycle_next())' in compositor
    assert "hl.dsp.window.cycle_next({ next = false })" in compositor
    assert "move_pane.py focused focus" not in compositor
    assert compositor.count('hl.bind("SUPER + SHIFT +') == 5
    assert compositor.count('hl.bind("SUPER + LEFT"') == 1
    assert compositor.count('hl.bind("SUPER + RIGHT"') == 1
    assert compositor.count('hl.bind("SUPER + UP"') == 1
    assert compositor.count('hl.bind("SUPER + DOWN"') == 1
    assert compositor.count('hl.bind("SUPER + CTRL +') == 4
    assert "move_pane.py focused resize left" in compositor
    assert "move_pane.py focused tile right" in compositor
    assert "move_pane.py focused surface top" in compositor
    assert "move_pane.py focused surface bottom" in compositor
    assert "move_pane.py focused close" in compositor
    assert '"HDMI-A-1": "samsung"' in move_client
    assert '"DP-8": "usb-c"' in move_client
    assert '"HDMI-A-2": "dp-4"' in move_client
    assert '["/usr/bin/hyprctl", "monitors", "-j"]' in move_client
    assert 'surface_argument == "focused"' in move_client
    assert not (SHELL_ROOT / "input" / "router.py").exists()
    assert not (SHELL_ROOT / "input" / "dbus_bridge.py").exists()
    assert "router" not in move_client.lower()
    assert "drag-start" not in command_server
    assert "drag-route" not in command_server
    assert "obsidience-pane-drag" not in command_server


def test_reader_explorers_share_one_native_dock_layout() -> None:
    workspace = (
        SHELL_ROOT / "qml" / "workspace" / "PaneWorkspace.qml"
    ).read_text()
    pane = (SHELL_ROOT / "qml" / "workspace" / "PaneWindow.qml").read_text()
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
    assert 'root.dockLayout.isDocked("knowledge")' in workspace
    assert 'root.dockLayout.isDocked("source")' in workspace
    assert 'root.dockLayout.isDocked("feeds")' in workspace
    assert "root.readerPlacement.surfaceId" in workspace
    assert "root.knowledgePlacement.surfaceId" in workspace
    assert "root.sourcePlacement.surfaceId" in workspace
    assert 'root.placement.paneId === "reader"' in pane
    assert "PaneDockHost {" in pane
    assert host.count("PaneDockStack {") == 2
    assert '"Dock left · top"' in host
    assert '"Dock left · bottom"' in host
    assert '"Dock right · top"' in host
    assert '"Dock right · bottom"' in host
    assert "availableWidth * 0.30" in stack
    assert "Math.min(380, Math.max(240" in stack
    assert "model: [0, 1]" in stack
    assert "y: modelData * root.height / 2" in stack
    assert "height: root.height / 2" in stack
    assert "dockLayout.slotState" in stack
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
    assert 'textFormat: root.feedItemMode || root.previewMode ? Text.PlainText : Text.MarkdownText' in reader
    assert 'root.sourceMode ? 1100 : root.indexArticle ? 920 : 720' in reader
    assert '"SYSTEM"' in source
    assert 'title: "Knowledge"' in knowledge


def test_knowledge_explorer_absorbs_native_folder_articles_once() -> None:
    knowledge = (
        SHELL_ROOT / "qml" / "panes" / "knowledge" / "KnowledgePane.qml"
    ).read_text()
    assert 'if (parent && file.kind === "knowledge"' in knowledge
    assert '=== currentPath.split("/").pop().toLowerCase()' in knowledge
    assert 'parent.ref = file.ref' in knowledge
    assert 'subject.ref = declared.article_ref || declared.id' in knowledge
    assert '|| file.ref === declared.article_ref) continue' in knowledge
    assert '["index", "readme"].includes' not in knowledge
    assert '(index|readme)' not in knowledge
    panes = PROJECT_ROOT / "obsidience" / "ui" / "src" / "renderer" / "src" / "panes"
    reader = (panes / "reader-pane.tsx").read_text()
    graph = (panes / "graph-backdrop.tsx").read_text()
    assert 'basename.toLowerCase() === parent.path.split("/").pop()?.toLowerCase()' in reader
    assert '&& file.ref !== declared.article_ref' in reader
    assert '!subjectArticleRefs.has(candidate.id)' in reader
    assert 'row.article_ref ? [row.article_ref] : []' in reader
    assert '!subjectArticleRefs.has(node.id)' in graph
    assert 'subject.article_ref ? [subject.article_ref] : []' in graph


def test_reader_child_labels_use_canonical_graph_titles() -> None:
    reader = (SHELL_ROOT / "qml" / "panes" / "reader" / "ReaderPane.qml").read_text()
    assert 'request.open("GET", "http://127.0.0.1:8765/api/graph")' in reader
    assert "loadArticleTitles(generation)" in reader
    assert "generation !== root.requestGeneration" in reader
    assert "titles[node.id] = node.title" in reader
    assert "titles[subject.id] = subject.title" in reader
    assert "titles[subject.article_ref] = subject.title" in reader
    assert "root.articleLabel(childButton.modelData)" in reader
    assert "root.articleLabel(sourceArticleButton.modelData)" in reader
    assert 'modelData.split("/").pop()' not in reader


def test_login_entry_installs_as_a_greeter_readable_file() -> None:
    desktop = (SHELL_ROOT / "session" / "obsidience.desktop").read_text()
    greetd = (SHELL_ROOT / "session" / "greetd.toml").read_text()
    installer = (SHELL_ROOT / "session" / "install-session").read_text()
    assert "TryExec=/home/wissenschafter/Projects/obsidience/" in desktop
    assert "session_dir=/usr/local/share/wayland-sessions" in installer
    assert 'install -o root -g root -m 0644 "$session_source" "$session_target"' in installer
    assert 'install -o root -g root -m 0600 "$greetd_source" "$greetd_target"' in installer
    assert "[default_session]" in greetd
    assert "obsidience-shell-login" in greetd


def test_live_shell_runtime_dependencies_are_pinned_without_kde_shell_entries() -> None:
    manifest = json.loads((SHELL_ROOT / "REUSE_MANIFEST.json").read_text())
    packages = {
        upstream["name"]: upstream.get("package")
        for upstream in manifest["upstreams"]
    }
    assert packages["Quickshell"] == "quickshell 0.3.1-1.1"
    assert packages["gtk-layer-shell"] == "gtk-layer-shell 0.10.1-1.1"
    assert packages["WebKitGTK"] == "webkit2gtk-4.1 2.52.6-1"
    assert packages["PyGObject"] == "python-gobject 3.56.3-1"
    assert packages["QMLTermWidget"] == "qmltermwidget 2.0.0.git1-1.1"
    assert packages["Qt WebEngine"] == "qt6-webengine 6.11.2-1"
    assert packages["Qt WebSockets"] == "qt6-websockets 6.11.1-1.1"
    assert "KScreenLocker" not in packages
    assert "KWin MCP" not in packages


def test_quickshell_runtime_pins_webengine_and_session_lock_fixes() -> None:
    manifest = json.loads((SHELL_ROOT / "REUSE_MANIFEST.json").read_text())
    upstreams = {item["name"]: item for item in manifest["upstreams"]}
    quickshell = upstreams["Quickshell"]
    assert quickshell["commit"] == "1a4716cde794a59928d9d9fc15f2afc7a95de360"
    assert quickshell["patches"] == [
        "adapter/quickshell/patches/0001-satisfy-qtwebengine-host-contract.patch",
        "adapter/quickshell/patches/0002-guard-session-lock-reentrancy.patch",
        "adapter/quickshell/patches/0003-notify-session-unlock.patch",
    ]
    webengine_patch = (SHELL_ROOT / quickshell["patches"][0]).read_text()
    assert webengine_patch.count("diff --git") == 2
    assert sum(line.startswith("@@ ") for line in webengine_patch.splitlines()) == 2
    assert "-\tauto qArgC = 0;" in webengine_patch
    assert "+\tauto qArgC = 1;" in webengine_patch
    assert "+\tQCoreApplication::setAttribute(Qt::AA_ShareOpenGLContexts);" in webengine_patch
    lock_patch = (SHELL_ROOT / quickshell["patches"][1]).read_text()
    assert lock_patch.count("diff --git") == 3
    assert "if (this->realizing || !this->manager)" in lock_patch
    assert "if (this->isLocked() && !this->realizing)" in lock_patch
    unlock_patch = (SHELL_ROOT / quickshell["patches"][2]).read_text()
    assert unlock_patch.count("diff --git") == 1
    assert "const auto wasLocked = this->isLocked();" in unlock_patch
    assert "if (wasLocked) emit this->lockStateChanged();" in unlock_patch
    assert quickshell["upstream_backports"] == [
        {
            "commit": "afb2c27cd6d600d221d9379a332ee1b321a68487",
            "subject": "wayland/lock: guard against reentrancy during surface creation",
        }
    ]
    assert quickshell["runtime"] == {
        "path": "/home/wissenschafter/.local/opt/obsidience-quickshell/"
        "quickshell-0.3.1-webengine-lock-5f4d2585/quickshell",
        "sha256": "5f4d25850c0112fbc7fd718bbdc859e85db888120aecd010a051f5b51b50de05",
    }
    recipe = (SHELL_ROOT / "adapter/quickshell/build-runtime").read_text()
    assert 'lock_patch_file="$script_dir/patches/0002-guard-session-lock-reentrancy.patch"' in recipe
    assert 'git -C "$source_dir" apply --check "$lock_patch_file"' in recipe
    assert 'git -C "$source_dir" apply "$lock_patch_file"' in recipe
    assert 'unlock_patch_file="$script_dir/patches/0003-notify-session-unlock.patch"' in recipe
    assert 'git -C "$source_dir" apply "$unlock_patch_file"' in recipe
    assert "readonly source_date_epoch=1787279335" in recipe
    assert 'git ls-files -z | xargs -0 touch -d "@$SOURCE_DATE_EPOCH" --' in recipe


def test_workspace_tiler_reuses_only_attested_omarchy_geometry() -> None:
    manifest = json.loads((SHELL_ROOT / "REUSE_MANIFEST.json").read_text())
    upstreams = {item["name"]: item for item in manifest["upstreams"]}
    geometry = upstreams["Omarchy Windows Aero Snap geometry"]
    assert geometry["commit"] == "8337344c69046f09f59c68280e5df2577d3273c5"
    assert geometry["license"] == "MIT"
    assert geometry["notice"] == "LICENSES/Omarchy-Windows-MIT.txt"
    assert "arbitrary integer NxM bounds" in geometry["adaptation"]
    assert "plugin" in geometry["adaptation"]
    assert (SHELL_ROOT / geometry["notice"]).is_file()


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
    shell = (SHELL_ROOT / "qml" / "shell.qml").read_text()
    workspace = (
        SHELL_ROOT / "qml" / "workspace" / "PaneWorkspace.qml"
    ).read_text()
    host = (
        SHELL_ROOT / "systemd" / "obsidience-shell-host.service"
    ).read_text()

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
    assert shell.count("PaneWorkspace {") == 1
    assert not (SHELL_ROOT / "qml" / "surface.qml").exists()
    assert "property Component terminalComponent: Component { TerminalPane {} }" in workspace
    assert '"label": "Terminal"' in workspace
    assert '"component": terminalComponent' in workspace
    assert "state/placements/." in host
    assert ".local/state/obsidience-shell/placements" in host
    assert len(list((SHELL_ROOT / "state" / "placements").glob(
        "*-placement.json"
    ))) == 15
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
