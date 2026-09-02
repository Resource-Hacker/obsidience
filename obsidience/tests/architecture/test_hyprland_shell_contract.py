"""Static contract for the isolated Hyprland shell slice."""

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
    assert set(policy["required"]) == {
        "host", "session", "shell", "services", "compatibility"
    }
    assert set(policy["protected"]) == {
        "boot_graphics", "kwin_rollback", "workstation"
    }

    package_names: list[str] = []
    for group in (policy["required"], policy["protected"]):
        for packages in group.values():
            assert packages == sorted(packages)
            assert len(packages) == len(set(packages))
            assert all(re.fullmatch(r"[a-z0-9@._+\-]+", name) for name in packages)
            package_names.extend(packages)
    assert len(package_names) == len(set(package_names))
    assert "hyprland" in policy["required"]["session"]
    assert "quickshell" in policy["required"]["shell"]
    assert "kwin" in policy["protected"]["kwin_rollback"]
    assert "plasma-workspace" in policy["protected"]["kwin_rollback"]


def test_hyprland_config_is_one_samsung_only_compositor_contract() -> None:
    config = (
        SHELL_ROOT / "adapter" / "hyprland" / "hyprland.lua"
    ).read_text(encoding="utf-8")
    assert 'output = "HDMI-A-1"' in config
    assert 'mode = "5120x1440@240"' in config
    assert 'position = "0x0"' in config
    assert "scale = 1" in config
    assert "bitdepth = 10" in config
    assert "vrr = 2" in config
    assert "direct_scanout = 0" in config
    assert "allow_tearing = false" in config
    assert 'hl.on("hyprland.start"' in config
    assert "uwsm finalize && systemctl --user start" in config
    assert "obsidience-hyprland-session.target" in config
    assert 'hl.bind("SUPER + RETURN"' in config
    assert 'hl.bind("SUPER + SHIFT + ESCAPE"' in config
    assert "kwin" not in config.casefold()
    assert "plasmashell" not in config.casefold()


def test_hyprland_session_coexists_with_the_kde_recovery_session() -> None:
    session = SHELL_ROOT / "session"
    login = (session / "obsidience-hyprland-login").read_text(encoding="utf-8")
    desktop = (session / "obsidience-hyprland.desktop").read_text(encoding="utf-8")
    installer = (session / "install-hyprland-session").read_text(encoding="utf-8")

    assert (session / "obsidience.desktop").is_file()
    assert (session / "obsidience-shell-login").is_file()
    assert (session / "obsidience-hyprland-login").stat().st_mode & 0o111
    assert (session / "install-hyprland-session").stat().st_mode & 0o111
    assert "/dev/dri/by-path/pci-0000:01:00.0-card" in login
    assert '"pci-0000:01:00.0"' in login
    assert 'export AQ_DRM_DEVICES="$drm_card"' in login
    assert "/usr/bin/uwsm start" in login
    assert "/usr/bin/Hyprland" in login
    assert "/Projects/obsidience-hyprland/" in login
    assert "KWIN_DRM_DEVICES" not in login
    assert "Name=Obsidience (Hyprland)" in desktop
    assert "obsidience-hyprland-login" in desktop
    assert "obsidience-hyprland.desktop" in installer
    assert "/usr/local/share/wayland-sessions" in installer
    assert "plasmalogin.conf" not in installer


def test_hyprland_services_reuse_one_shell_and_one_graph() -> None:
    systemd = SHELL_ROOT / "systemd"
    target = (systemd / "obsidience-hyprland-session.target").read_text()
    host = (systemd / "obsidience-shell-hyprland-host.service").read_text()
    knowledge = (
        systemd / "obsidience-shell-hyprland-knowledge.service"
    ).read_text()
    notifications = (
        systemd / "obsidience-shell-hyprland-notifications.service"
    ).read_text()

    combined = target + host + knowledge + notifications
    assert "main-compositor-ready.target" not in combined
    assert "org.kde.KWin" not in combined
    assert "plasma-" not in combined
    assert "obsidience-shell-surface-usbc.service" not in target
    assert "obsidience-shell-surface-dp4.service" not in target
    assert "obsidience-shell-hyprland-host.service" in target
    assert "obsidience-shell-hyprland-knowledge.service" in target
    assert "OBSIDIENCE_SHELL_STATE_NAMESPACE=obsidience-hyprland" in host
    assert "OBSIDIENCE_SHELL_PRIMARY_ONLY=1" in host
    assert "obsidience/shell/qml" in host
    assert "surfaces/knowledge/host.py" in knowledge
    assert "shell/knowledge/?surface=knowledge&surface_id=samsung" in knowledge
    assert "Type=simple" in notifications
    assert "BusName=" not in notifications
    assert "ExecStart=/usr/bin/mako" in notifications


def test_hyprland_canary_state_is_isolated_without_a_second_ui() -> None:
    qml = SHELL_ROOT / "qml"
    for path in (
        qml / "api" / "SurfaceLayout.qml",
        qml / "api" / "LockState.qml",
        qml / "api" / "FullscreenState.qml",
        qml / "workspace" / "PanePlacement.qml",
        qml / "workspace" / "PaneDockLayout.qml",
    ):
        assert "OBSIDIENCE_SHELL_STATE_NAMESPACE" in path.read_text()

    workspace = (qml / "workspace" / "PaneWorkspace.qml").read_text()
    assert "OBSIDIENCE_SHELL_PRIMARY_ONLY" in workspace
    assert "secondaryDefaultSurfaceId" in workspace
    layout = tomllib.loads(
        (SHELL_ROOT / "module.toml").read_text(encoding="utf-8")
    )
    assert layout["entrypoints"].count("obsidience/shell/qml/shell.qml") == 1
    assert not (qml / "hyprland-shell.qml").exists()

    initial = (
        SHELL_ROOT / "state" / "initial-hyprland-surface-layout.json"
    ).read_text(encoding="utf-8")
    assert '"backend": "hyprland-wayland"' in initial
    assert '"graph_surface_id": "samsung"' in initial


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
