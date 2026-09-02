"""Static contract for the live Hyprland shell slice."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
SHELL_ROOT = PROJECT_ROOT / "obsidience" / "shell"


def test_system_package_policy_is_small_additive_and_versionless() -> None:
    policy = tomllib.loads(
        (SHELL_ROOT / "system-packages.toml").read_text(encoding="utf-8")
    )
    assert policy["schema"] == "obsidience.system-packages.v1"
    assert policy["platform"] == "arch"
    assert policy["profile"] == "hyprland"
    assert policy["mode"] == "additive"
    assert set(policy["required"]) == {"host", "session", "shell", "services"}
    assert set(policy["protected"]) == {"boot_graphics", "workstation"}

    package_names: list[str] = []
    for group in (policy["required"], policy["protected"]):
        for packages in group.values():
            assert packages == sorted(packages)
            assert len(packages) == len(set(packages))
            assert all(re.fullmatch(r"[a-z0-9@._+\-]+", name) for name in packages)
            package_names.extend(packages)
    assert len(package_names) == len(set(package_names))
    assert "greetd" in policy["required"]["session"]
    assert "greetd-agreety" in policy["required"]["session"]
    assert "hyprland" in policy["required"]["session"]
    assert "quickshell" in policy["required"]["shell"]
    assert not {
        "kwin", "plasma-workspace", "plasma-login-manager", "kscreenlocker"
    }.intersection(package_names)


def test_hyprland_config_is_one_compositor_with_three_real_outputs() -> None:
    config = (
        SHELL_ROOT / "adapter" / "hyprland" / "hyprland.lua"
    ).read_text(encoding="utf-8")
    assert config.count("hl.monitor({") == 3
    assert 'output = "HDMI-A-1"' in config
    assert 'mode = "5120x1440@240"' in config
    assert 'position = "0x0"' in config
    assert "scale = 1" in config
    assert "bitdepth = 10" in config
    assert config.count('cm = "hdr"') == 1
    assert config.count("sdr_max_luminance = 225") == 1
    assert "vrr = 2" in config
    assert 'output = "HDMI-A-2"' in config
    assert 'mode = "3840x1100@60"' in config
    assert 'position = "0x1440"' in config
    assert 'output = "DP-8"' in config
    assert 'mode = "3840x2400@60"' in config
    assert 'position = "1920x1440"' in config
    assert config.count("scale = 2") == 2
    assert config.count("vrr = 0") == 2
    assert "direct_scanout = 0" in config
    assert "allow_tearing = false" in config
    assert 'hl.on("hyprland.start"' in config
    assert "systemctl --user start --no-block" in config
    assert "uwsm finalize" not in config
    assert "obsidience-shell-session.target" in config
    assert 'hl.bind("SUPER + RETURN"' in config
    assert 'hl.bind("SUPER + SHIFT + ESCAPE"' in config
    assert config.count("hl.device({") == 1
    assert 'name = "saitek-cyborg-m.m.o.7-gaming-mouse"' in config
    assert 'accel_profile = "custom 1 0 0.125"' in config
    assert "sensitivity = 0" in config
    assert "kwin" not in config.casefold()
    assert "plasmashell" not in config.casefold()


def test_greetd_launches_the_one_hyprland_session() -> None:
    session = SHELL_ROOT / "session"
    login = (session / "obsidience-shell-login").read_text(encoding="utf-8")
    desktop = (session / "obsidience.desktop").read_text(encoding="utf-8")
    installer = (session / "install-session").read_text(encoding="utf-8")
    greetd = (session / "greetd.toml").read_text(encoding="utf-8")

    assert (session / "obsidience-shell-login").stat().st_mode & 0o111
    assert (session / "install-session").stat().st_mode & 0o111
    assert "/dev/dri/by-path/pci-0000:01:00.0-card" in login
    assert "/dev/dri/by-path/pci-0000:7a:00.0-card" in login
    assert '"pci-0000:01:00.0"' in login
    assert '"pci-0000:7a:00.0"' in login
    assert 'export AQ_DRM_DEVICES="$main_drm_card:$side_drm_card"' in login
    assert "/usr/bin/uwsm start" in login
    assert "/usr/bin/Hyprland" in login
    assert "/Projects/obsidience/" in login
    assert "KWIN_DRM_DEVICES" not in login
    assert "Name=Obsidience" in desktop
    assert "obsidience-shell-login" in desktop
    assert "obsidience.desktop" in installer
    assert "/usr/local/share/wayland-sessions" in installer
    assert "/etc/greetd/config.toml" in installer
    assert "-m 0600" in installer
    assert "[initial_session]" in greetd
    assert "obsidience-shell-login" in greetd
    assert "plasmalogin.conf" not in installer


def test_hyprland_services_reuse_one_shell_and_one_graph() -> None:
    systemd = SHELL_ROOT / "systemd"
    target = (systemd / "obsidience-shell-session.target").read_text()
    host = (systemd / "obsidience-shell-host.service").read_text()
    knowledge = (
        systemd / "obsidience-shell-knowledge.service"
    ).read_text()
    notifications = (
        systemd / "obsidience-shell-notifications.service"
    ).read_text()

    combined = target + host + knowledge + notifications
    assert "main-compositor-ready.target" not in combined
    assert "org.kde.KWin" not in combined
    assert "plasma-" not in combined
    assert "graphical-session.target" not in combined
    assert "After=wayland-session@Hyprland.target" in target
    assert "BindsTo=wayland-session@Hyprland.target" in target
    assert "PartOf=wayland-session@Hyprland.target" in target
    assert "obsidience-shell-surface-usbc.service" not in target
    assert "obsidience-shell-surface-dp4.service" not in target
    assert "obsidience-shell-host.service" in target
    assert "obsidience-shell-knowledge.service" in target
    assert "OBSIDIENCE_SHELL_STATE_NAMESPACE" not in host
    assert "OBSIDIENCE_SHELL_PRIMARY_ONLY" not in host
    assert "obsidience/shell/qml" in host
    assert "surfaces/knowledge/host.py" in knowledge
    assert "OBSIDIENCE_KNOWLEDGE_ORIGIN=http://127.0.0.1:8765/shell/knowledge/" in knowledge
    assert "OBSIDIENCE_SURFACE_LAYOUT=%h/.config/obsidience-shell/surface-layout.json" in knowledge
    assert "Type=simple" in notifications
    assert "BusName=" not in notifications
    assert "ExecStart=/usr/bin/mako" in notifications


def test_hyprland_state_is_canonical_without_a_second_ui() -> None:
    qml = SHELL_ROOT / "qml"
    surface_layout = (qml / "api" / "SurfaceLayout.qml").read_text()
    placement = (qml / "workspace" / "PanePlacement.qml").read_text()
    dock_layout = (qml / "workspace" / "PaneDockLayout.qml").read_text()
    workspace = (qml / "workspace" / "PaneWorkspace.qml").read_text()
    assert "OBSIDIENCE_SHELL_STATE_NAMESPACE" not in surface_layout
    assert "OBSIDIENCE_SHELL_STATE_NAMESPACE" not in placement
    assert "OBSIDIENCE_SHELL_STATE_NAMESPACE" not in dock_layout
    assert "OBSIDIENCE_SHELL_PRIMARY_ONLY" not in workspace
    assert "secondaryDefaultSurfaceId" not in workspace
    layout = tomllib.loads(
        (SHELL_ROOT / "module.toml").read_text(encoding="utf-8")
    )
    assert layout["entrypoints"].count("obsidience/shell/qml/shell.qml") == 1
    assert not (qml / "hyprland-shell.qml").exists()

    assert not (SHELL_ROOT / "state" / "initial-hyprland-surface-layout.json").exists()
    initial = json.loads(
        (SHELL_ROOT / "state" / "initial-surface-layout.json").read_text(
            encoding="utf-8"
        )
    )
    assert initial["graph_surface_id"] == "samsung"
    surfaces = {surface["id"]: surface for surface in initial["surfaces"]}
    assert {surface["backend"] for surface in surfaces.values()} == {
        "hyprland-wayland"
    }
    assert surfaces["samsung"]["output"] == "HDMI-A-1"
    assert surfaces["usb-c"]["output"] == "DP-8"
    assert surfaces["dp-4"]["output"] == "HDMI-A-2"


def test_hyprland_and_uwsm_are_declared_runtime_plumbing() -> None:
    manifest = json.loads(
        (SHELL_ROOT / "REUSE_MANIFEST.json").read_text(encoding="utf-8")
    )
    upstreams = {item["name"]: item for item in manifest["upstreams"]}
    assert upstreams["Hyprland"]["package"] == "hyprland 0.55.2-2"
    assert upstreams["Universal Wayland Session Manager"]["package"] == (
        "uwsm 0.26.4-1"
    )
    assert "no Hyprland source" in upstreams["Hyprland"]["adaptation"]
    assert "does not duplicate UWSM" in upstreams[
        "Universal Wayland Session Manager"
    ]["adaptation"]
