"""Static contract for the live Hyprland shell slice."""

from __future__ import annotations

import json
import re
from pathlib import Path

import tomllib

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
    assert "hypridle" in policy["required"]["session"]
    assert "quickshell" in policy["required"]["shell"]
    assert "qt6-webengine" in policy["required"]["shell"]
    assert not {
        "kwin", "plasma-workspace", "plasma-login-manager", "kscreenlocker"
    }.intersection(package_names)


def test_hyprland_config_is_one_compositor_with_three_real_outputs() -> None:
    config = (
        SHELL_ROOT / "adapter" / "hyprland" / "hyprland.lua"
    ).read_text(encoding="utf-8")
    monitor_config = config.split("hl.config({", 1)[0]
    assert len(re.findall(r"^hl\.monitor\(\{$", config, re.MULTILINE)) == 3
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
    assert monitor_config.count("scale = 2") == 2
    assert monitor_config.count("vrr = 0") == 2
    assert "direct_scanout = 0" in config
    assert "allow_tearing = false" in config
    assert 'hl.on("hyprland.start"' in config
    assert "systemctl --user start --no-block" in config
    assert "recover-startup-pageflip" not in config
    assert not (SHELL_ROOT / "session" / "recover-startup-pageflip").exists()
    assert 'hl.on("layer.opened"' not in config
    assert "uwsm finalize" not in config
    assert "obsidience-shell-session.target" in config
    assert "follow_mouse = 0" in config
    assert "allow_session_lock_restore = true" in config
    assert 'name = "obsidience-module-pane"' in config
    assert r"initial_class = [[^io\.obsidience\.shell$]]" in config
    assert (
        r"initial_title = [[^obsidience-pane:[a-z][a-z0-9-]{0,47}$]]"
        in config
    )
    assert "tile = true" in config
    assert 'hl.bind("SUPER + RETURN"' in config
    assert config.count('hl.bind("ALT + TAB"') == 1
    assert config.count('hl.bind("ALT + SHIFT + TAB"') == 1
    assert 'hl.bind("ALT + TAB", hl.dsp.window.cycle_next())' in config
    assert (
        'hl.bind("ALT + SHIFT + TAB", '
        "hl.dsp.window.cycle_next({ next = false }))" in config
    )
    assert "move_pane.py focused focus" not in config
    assert "mouse:272" not in config
    assert "hl.dsp.window.drag()" not in config
    assert 'hl.bind("SUPER + SHIFT + ESCAPE"' in config
    assert 'hl.bind("SUPER + ESCAPE"' in config
    assert "move_pane.py focused close" in config
    assert config.count("hl.device({") == 1
    assert 'name = "saitek-cyborg-m.m.o.7-gaming-mouse"' in config
    assert 'accel_profile = "custom 1 0 0.125"' in config
    assert "sensitivity = 0" in config
    assert "kwin" not in config.casefold()
    assert "plasmashell" not in config.casefold()


def test_hypridle_locks_then_powers_down_all_displays() -> None:
    config = (SHELL_ROOT / "idle" / "hypridle.conf").read_text(encoding="utf-8")

    assert config.count("listener {") == 2
    assert config.count("timeout = 300") == 1
    assert config.count("timeout = 600") == 1
    assert "qs ipc" in config
    assert "call lock lock" in config
    assert "on-timeout = loginctl lock-session" in config
    assert "on-timeout = hyprctl dispatch" in config
    assert 'action = "off"' in config
    assert "on-resume = hyprctl dispatch" in config
    assert 'action = "on"' in config
    assert "ignore_dbus_inhibit = false" in config
    assert "ignore_systemd_inhibit = false" in config
    assert "ignore_wayland_inhibit = false" in config
    assert config.count("ignore_inhibit = true") == 2
    assert "systemctl suspend" not in config
    assert "hyprlock" not in config
    assert "HDMI-A-1" not in config
    assert "DP-8" not in config
    assert "HDMI-A-2" not in config


def test_shell_restart_preserves_or_recovers_the_secure_lock() -> None:
    session = SHELL_ROOT / "session"
    restart = (session / "restart-shell").read_text(encoding="utf-8")
    lock = (session / "session-lock").read_text(encoding="utf-8")
    service = (
        SHELL_ROOT / "systemd" / "obsidience-shell-host.service"
    ).read_text(encoding="utf-8")

    assert 'index("LOCK")' in lock
    assert 'call lock' in lock
    assert '"${ipc[@]}" lock' in lock
    assert '"$script_dir/session-lock" status' in restart
    assert 'state" == "secure" || "$state" == "locking"' in restart
    assert "restart obsidience-shell-session.target" in restart
    assert "obsidience-shell-host.service" in restart
    assert "obsidience-shell-knowledge.service" in restart
    assert "obsidience-shell-window-adapter.service" in restart
    assert "ExecStartPost=" in service
    assert "/session/session-lock recover" in service


def test_native_windows_use_the_obsidience_grid_and_theme() -> None:
    adapter = SHELL_ROOT / "adapter" / "hyprland"
    config = (adapter / "hyprland.lua").read_text(encoding="utf-8")
    layout = (adapter / "layout.lua").read_text(encoding="utf-8")

    assert config.count("layout.lua") == 1
    assert 'layout = "lua:obsidience"' in config
    assert 'active_border = "rgba(67e8f966)"' in config
    assert 'inactive_border = "rgb(294b54)"' in config
    assert "gaps_in = { top = 2, right = 3, bottom = 3, left = 2 }" in config
    assert "gaps_out = 5" in config
    assert "resize_on_border = true" in config
    assert "extend_border_grab_area = 15" in config
    assert "hover_icon_on_border = true" in config
    assert "rounding = 12" in config
    assert "range = 3" in config
    assert "glow = {" in config
    assert "enabled = false" in config
    assert "range = 5" in config
    assert 'hl.layout.register("obsidience"' in layout
    assert "local GAP = 5" in layout
    assert "local NATIVE_GAP_START = 2" in layout
    assert '["HDMI-A-1"] = { surface = "samsung", columns = 8, rows = 2 }' in layout
    assert '["DP-8"] = { surface = "usb-c", columns = 3, rows = 2 }' in layout
    assert '["HDMI-A-2"] = { surface = "dp-4", columns = 4, rows = 1 }' in layout
    assert "target:place(box)" in layout
    assert "last_placed[id] = box" in layout
    assert "local function context_is_current(key, ctx)" in layout
    assert "state.ctx = nil" in layout
    assert "local function configure_oled_glow(enabled)" in layout
    assert "oled_glow_rotation_hours = 3" in layout
    assert "360 * oled_motion.active_seconds" in layout
    assert "settings.oled_glow_rotation_hours * 3600" in layout
    assert "local oled_timer = nil" in layout
    assert layout.count("hl.timer(") == 1
    assert "obsidience-oled-phase" not in layout
    assert "publish_oled_phase" not in layout
    assert "hl.exec" not in layout
    assert "io.open" not in layout
    assert "local function y_component(state, grid, cut, left, right)" in layout
    assert "hl.animation" not in layout


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
    assert initial["tile_resize_limit_percent"] == 25
    assert initial["oled_mode_enabled"] is False
    assert initial["oled_shift_distance_px"] == 32
    assert initial["oled_travel_duration_seconds"] == 3600
    assert initial["oled_glow_rotation_hours"] == 3
    assert initial["workspace_tiling"] == {
        "samsung": {"columns": 8, "rows": 2},
        "usb-c": {"columns": 3, "rows": 2},
        "dp-4": {"columns": 4, "rows": 1},
    }
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
    hyprland = upstreams["Hyprland"]
    assert hyprland["package"] == "hyprland 0.56.2-2.4"
    assert hyprland["commit"] == "efb50993780079460b0cbed1363e2166a2de1d9f"
    assert hyprland["selected_sources"] == [
        {
            "path": "src/desktop/state/ViewHitTester.cpp",
            "sha256": (
                "1bcc02a03db80b0519e516b41b3e0d0e70df08d6aa50b006b6a4362854524a09"
            ),
        },
        {
            "path": "src/config/lua/layout/LuaLayoutProvider.cpp",
            "sha256": (
                "e8a0977e7cd1604d0e86b0b85681eb5b6941b2109294f5e5aae8d20cf7dbb4ba"
            ),
        },
        {
            "path": "meta/generateLuaStubs.py",
            "sha256": (
                "da2cdb373e6ba757369495f4087216c29fdda142af852aaa79e3590d7c0a29ed"
            ),
        },
    ]
    assert hyprland["patches"] == [
        "adapter/hyprland/patches/0001-hit-test-overlapping-tiled-windows.patch",
        "adapter/hyprland/patches/0002-forward-lua-layout-resize.patch",
    ]
    hit_test_patch = (SHELL_ROOT / hyprland["patches"][0]).read_text(
        encoding="utf-8"
    )
    resize_patch = (SHELL_ROOT / hyprland["patches"][1]).read_text(
        encoding="utf-8"
    )
    assert (
        hit_test_patch.count(
            "+        for (auto const& w : WINDOWS | std::views::reverse)"
        )
        == 2
    )
    assert "tiledMainAt(LASTFOCUSED)" in hit_test_patch
    assert 'lua_getfield(L, -1, "resize");' in resize_patch
    assert "guardedPCall(5, 0" in resize_patch
    assert 'return "bottom-right";' in resize_patch
    assert '"resize",' in resize_patch
    assert "if (!lua_isfunction(L, -1))" in resize_patch
    assert resize_patch.count("recalculate();") >= 4
    assert "visible front-to-back order" in hyprland["adaptation"]
    assert "optional Lua layout callback" in hyprland["adaptation"]
    aquamarine = upstreams["Aquamarine"]
    assert aquamarine["package"] == "aquamarine 0.14.0-2.4"
    assert aquamarine["patches"] == [
        "adapter/hyprland/patches/aquamarine/0001-crtc-pageflip-accounting.patch",
        "adapter/hyprland/patches/aquamarine/0002-buffer-commit-plane-rotation.patch",
        "adapter/hyprland/patches/aquamarine/0003-release-fb-reference.patch",
        "adapter/hyprland/patches/aquamarine/0004-mgpu-blit-safeguards.patch",
        "adapter/hyprland/patches/aquamarine/0005-pageflip-id-optional.patch",
        "adapter/hyprland/patches/aquamarine/0006-preserve-multigpu-on-resize.patch",
    ]
    pageflip_patch = (SHELL_ROOT / aquamarine["patches"][0]).read_text(
        encoding="utf-8"
    )
    buffer_commit_patch = (SHELL_ROOT / aquamarine["patches"][1]).read_text(
        encoding="utf-8"
    )
    release_reference_patch = (
        SHELL_ROOT / aquamarine["patches"][2]
    ).read_text(encoding="utf-8")
    mgpu_guard_patch = (SHELL_ROOT / aquamarine["patches"][3]).read_text(
        encoding="utf-8"
    )
    optional_id_patch = (SHELL_ROOT / aquamarine["patches"][4]).read_text(
        encoding="utf-8"
    )
    swapchain_patch = (SHELL_ROOT / aquamarine["patches"][5]).read_text(
        encoding="utf-8"
    )
    assert pageflip_patch.startswith(
        "From 3f33dd35e09bb6b155d8576563d6053aa4b898c6 "
    )
    assert "pending pageflips need to live in the crtc" in pageflip_patch
    assert buffer_commit_patch.startswith(
        "From 40cde956f4998e3853e32c0e3f3729fa5340c0ad "
    )
    assert "only rotate plane FBs on buffer commits" in buffer_commit_patch
    assert "state->needsReconfig()" in buffer_commit_patch
    assert release_reference_patch.startswith(
        "From 9f05429c75bb4fee3501c040e457e7bd69b737c3 "
    )
    assert "[this](SP<CDRMFB>& fb)" in release_reference_patch
    assert mgpu_guard_patch.startswith(
        "From b65c12201b66ff344689a0093148ff8a38e644cd "
    )
    assert "mgpu swapchain has no buffer" in mgpu_guard_patch
    assert optional_id_patch.startswith(
        "From f66fb773b406e3a63970cce001c8b45e17fa075a "
    )
    assert "std::optional<uintptr_t>" in optional_id_patch
    assert ".multigpu = options.multigpu" in swapchain_patch
    assert aquamarine["upstream_backports"] == [
        {
            "commit": "3f33dd35e09bb6b155d8576563d6053aa4b898c6",
            "subject": "drm: move pending pageflips to the crtc",
        },
        {
            "commit": "40cde956f4998e3853e32c0e3f3729fa5340c0ad",
            "subject": "drm: only rotate plane FBs on buffer commits",
        },
        {
            "commit": "9f05429c75bb4fee3501c040e457e7bd69b737c3",
            "subject": "drm: use reference in lambda",
        },
        {
            "commit": "b65c12201b66ff344689a0093148ff8a38e644cd",
            "subject": "drm: safeguard blit from releaseMgpuResources",
        },
        {
            "commit": "f66fb773b406e3a63970cce001c8b45e17fa075a",
            "subject": "drm: make pendingPageflip id std::optional",
        },
        {
            "commit": "639ee4cdc1a44a05de4e50a9067f4b8a4f210666",
            "subject": "swapchain: preserve multigpu flag in resize() (#356)",
        },
    ]
    assert "complete five-commit upstream page-flip" in aquamarine["adaptation"]
    assert "without any Obsidience watcher" in aquamarine["adaptation"]
    assert upstreams["Universal Wayland Session Manager"]["package"] == (
        "uwsm 0.26.7-1"
    )
    assert "does not duplicate UWSM" in upstreams[
        "Universal Wayland Session Manager"
    ]["adaptation"]
