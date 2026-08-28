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
        "entrypoints": ["obsidience/shell/qml/shell.qml"],
        "source_roots": ["obsidience/shell"],
        "projections": ["obsidience/state/system/applications/obsidience"],
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
    background = (
        SHELL_ROOT / "qml" / "surfaces" / "background" / "Background.qml"
    ).read_text()
    panel = (
        SHELL_ROOT / "qml" / "panels" / "top" / "TopPanel.qml"
    ).read_text()
    assert 'primaryOutputName: "HDMI-A-1"' in shell_api
    assert "property ShellApi shellApi: ShellApi {}" in shell
    assert "Quickshell.screens.filter" in shell
    assert shell.count("model: root.targetScreens") == 2
    assert shell.count("shellApi: root.shellApi") == 2
    assert 'import "surfaces/background"' in shell
    assert 'import "panels/top"' in shell
    assert "WlrLayer.Background" in background
    assert "mask: Region {}" in background
    assert "exclusiveZone: 38" in panel
    assert "WlrLayer.Top" in panel
    assert 'text: "OBSIDIENCE"' in panel


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
