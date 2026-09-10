"""Behavioral contracts for the bounded Surface window-state model."""

from __future__ import annotations

import json
from types import SimpleNamespace

from obsidience.shell.adapter.windows import hyprland as hyprland_module
from obsidience.shell.adapter.windows.hyprland import (
    HyprlandSurfaceWindows,
    _module_pane_id,
    _monitor_route,
)
from obsidience.shell.adapter.windows.model import (
    ApplicationWindow,
    LocalRect,
    WindowStateStore,
)
from obsidience.shell.adapter.windows.transport import ShellWindowTransport


def test_window_state_is_bounded_sanitized_and_revisioned() -> None:
    store = WindowStateStore()
    windows = tuple(
        ApplicationWindow(f"0x{index:08x}", "example", f"Window {index}")
        for index in range(300)
    )
    state = store.update("usb-c", "0x00000000", windows)
    assert state is not None
    assert state.revision == 1
    assert len(state.windows) == 256
    assert state.active_window_id == "0x00000000"

    unchanged = store.update("usb-c", "0x00000000", windows)
    assert unchanged is state
    assert unchanged.revision == 1

    changed = store.update("usb-c", "0x00000001", windows)
    assert changed is not None
    assert changed.revision == 2
    assert changed.active_window_id == "0x00000001"


def test_window_state_exposes_typed_module_identity_and_local_geometry() -> None:
    store = WindowStateStore()
    module = ApplicationWindow(
        "0x123",
        "io.obsidience.shell",
        "Settings",
        LocalRect(1080, 80, 800, 680),
        pid=42,
        window_kind="module",
        pane_id="settings",
    )
    state = store.update("usb-c", module.window_id, (module,))
    assert state is not None
    assert state.command()["windows"] == [
        {
            "window_id": "0x123",
            "app_id": "io.obsidience.shell",
            "title": "Settings",
            "local_rect": {"x": 1080, "y": 80, "width": 800, "height": 680},
            "pid": 42,
            "minimized": False,
            "visible_on_workspace": True,
            "window_kind": "module",
            "pane_id": "settings",
        }
    ]
    assert state.command()["surface_awake"] is True


def test_window_state_exposes_optional_compositor_stable_id() -> None:
    store = WindowStateStore()
    window = ApplicationWindow(
        "0x123", "example", "Example", stable_id="18000002"
    )
    state = store.update("samsung", window.window_id, (window,))
    assert state is not None
    assert state.command()["windows"][0]["stable_id"] == "18000002"


def test_invalid_module_identity_is_filtered() -> None:
    store = WindowStateStore()
    wrong_app = ApplicationWindow(
        "0x123",
        "example",
        "Settings",
        window_kind="module",
        pane_id="settings",
    )
    invalid_pane = ApplicationWindow(
        "0x124",
        "io.obsidience.shell",
        "Settings",
        window_kind="module",
        pane_id="Settings",
    )
    state = store.update("usb-c", "", (wrong_app, invalid_pane))
    assert state is not None
    assert state.windows == ()


def test_exact_window_rejects_stale_revision_and_unknown_surface() -> None:
    store = WindowStateStore()
    target = ApplicationWindow("exact-id", "example", "Exact")
    state = store.update("dp-4", "", (target,))
    assert state is not None
    assert store.exact_window("dp-4", "exact-id", state.revision) == target
    assert store.exact_window("dp-4", "exact-id", state.revision - 1) is None
    assert store.exact_window("usb-c", "exact-id", state.revision) is None


def test_window_at_or_after_keeps_exact_identity_across_unrelated_updates() -> None:
    store = WindowStateStore()
    target = ApplicationWindow("exact-id", "app", "Target")
    first = store.update("dp-4", "", (target,))
    assert first is not None
    second = store.update(
        "dp-4",
        "other-id",
        (target, ApplicationWindow("other-id", "other", "Other")),
    )
    assert second is not None and second.revision > first.revision

    assert store.window_at_or_after("dp-4", "exact-id", first.revision) == target
    assert store.window_at_or_after("dp-4", "missing", first.revision) is None
    assert store.window_at_or_after("dp-4", "exact-id", second.revision + 1) is None
    assert store.window_at_or_after("usb-c", "exact-id", first.revision) is None
    assert store.update("unknown", "", (target,)) is None


def test_exact_active_window_rejects_inactive_or_stale_target() -> None:
    store = WindowStateStore()
    active = ApplicationWindow("active-id", "example", "Active")
    inactive = ApplicationWindow("inactive-id", "example", "Inactive")
    state = store.update("samsung", active.window_id, (active, inactive))
    assert state is not None
    assert (
        store.exact_active_window("samsung", active.window_id, state.revision) == active
    )
    assert (
        store.exact_active_window("samsung", inactive.window_id, state.revision) is None
    )
    assert (
        store.exact_active_window("samsung", active.window_id, state.revision - 1)
        is None
    )


def test_wait_absent_observes_window_removal() -> None:
    store = WindowStateStore()
    target = ApplicationWindow("closing-id", "example", "Closing")
    assert store.update("samsung", target.window_id, (target,)) is not None
    assert store.wait_absent(target.window_id, 0.01) is False
    assert store.update("samsung", "", ()) is not None
    assert store.wait_absent(target.window_id, 0.01) is True


def test_close_rejects_a_stale_active_window(monkeypatch) -> None:
    backend = HyprlandSurfaceWindows(lambda *_: None)
    dispatched: list[str] = []
    monkeypatch.setattr(backend, "_json", lambda *_: {"address": "0x222"})
    monkeypatch.setattr(backend, "_dispatch", dispatched.append)

    assert backend.close("0x111") == (False, "focus_changed")
    assert dispatched == []


def test_layout_message_pins_the_exact_window_address(monkeypatch) -> None:
    backend = HyprlandSurfaceWindows(lambda *_args: None)
    messages: list[str] = []
    monkeypatch.setattr(
        backend,
        "_json",
        lambda name, *_args: []
        if name == "monitors"
        else {"address": "0x123", "monitor": 0},
    )
    monkeypatch.setattr(
        backend,
        "_layout_message",
        lambda message: (
            messages.append(message)
            or SimpleNamespace(returncode=0, stdout="ok\n", stderr="")
        ),
    )
    monkeypatch.setattr(backend, "_publish", lambda: None)

    grids = {"samsung": (8, 2), "usb-c": (3, 2), "dp-4": (4, 1)}
    assert backend.layout("samsung", "0x123", "resize", "right", grids) == (
        True,
        "",
    )
    assert messages == ["resize 0x123 right samsung 8 2"]


def test_restore_applies_exact_semantic_tile_bounds(monkeypatch) -> None:
    backend = HyprlandSurfaceWindows(lambda *_args: None)
    messages: list[str] = []
    monkeypatch.setattr(
        backend,
        "_layout_message",
        lambda message: (
            messages.append(message)
            or SimpleNamespace(returncode=0, stdout="ok\n", stderr="")
        ),
    )
    monkeypatch.setattr(backend, "_publish", lambda: None)
    bounds = {
        "surface_id": "samsung",
        "columns": 8,
        "rows": 2,
        "left": 5,
        "top": 0,
        "right": 8,
        "bottom": 2,
    }

    assert backend.restore("samsung", "0x123", bounds) == (True, "")
    assert messages == ["restore 0x123 samsung 8 2 5 0 8 2"]
    assert backend.restore("usb-c", "0x123", bounds) == (
        False,
        "invalid_restore",
    )
    assert len(messages) == 1


def test_place_moves_the_exact_window_without_following_focus(monkeypatch) -> None:
    backend = HyprlandSurfaceWindows(lambda *_args: None)
    messages: list[str] = []
    dispatches: list[str] = []
    monitors = [{"id": 2, "name": "DP-8"}]
    clients = [{"address": "0x123", "monitor": 2}]
    monkeypatch.setattr(
        backend,
        "_json",
        lambda name, *_args: monitors if name == "monitors" else clients,
    )
    monkeypatch.setattr(
        backend,
        "_layout_message",
        lambda message: (
            messages.append(message)
            or SimpleNamespace(returncode=0, stdout="ok\n", stderr="")
        ),
    )
    monkeypatch.setattr(
        backend,
        "_dispatch",
        lambda expression: (
            dispatches.append(expression)
            or SimpleNamespace(returncode=0, stdout="ok\n", stderr="")
        ),
    )
    monkeypatch.setattr(backend, "_publish", lambda: None)
    grids = {"samsung": (8, 2), "usb-c": (3, 2), "dp-4": (4, 1)}
    tile = {
        "surface_id": "usb-c",
        "columns": 3,
        "rows": 2,
        "left": 0,
        "top": 0,
        "right": 1,
        "bottom": 1,
    }

    assert backend.place("samsung", "0x123", "usb-c", grids, tile) == (
        True,
        "",
    )
    assert messages == [
        "place 0x123 usb-c 3 2 0 0 1 1",
        "verify-place 0x123 usb-c 3 2 0 0 1 1",
    ]
    assert len(dispatches) == 1
    assert 'window = "address:0x123"' in dispatches[0]
    assert "follow = false" in dispatches[0]
    assert "focus" not in dispatches[0]


def test_same_surface_tile_requires_one_authoritative_layout_verification(monkeypatch) -> None:
    backend = HyprlandSurfaceWindows(lambda *_args: None)
    messages = []

    def message(value):
        messages.append(value)
        return SimpleNamespace(
            returncode=0,
            stdout="obsidience: placement not observed" if value.startswith("verify-place") else "ok\n",
            stderr="",
        )

    monkeypatch.setattr(backend, "_layout_message", message)
    monkeypatch.setattr(backend, "_publish", lambda: None)
    tile = {
        "surface_id": "samsung", "columns": 8, "rows": 2,
        "left": 0, "top": 0, "right": 2, "bottom": 2,
    }
    assert backend.place("samsung", "0x123", "samsung", {"samsung": (8, 2)}, tile) == (
        False, "placement_not_observed"
    )
    assert messages == [
        "place 0x123 samsung 8 2 0 0 2 2",
        "verify-place 0x123 samsung 8 2 0 0 2 2",
    ]


def test_transport_returns_the_placement_post_revision() -> None:
    placed: list[tuple[object, ...]] = []
    sent: list[str] = []
    transport = ShellWindowTransport(
        WindowStateStore(),
        lambda *_args: (True, "", 1),
        lambda *_args: (True, ""),
        lambda *_args: (True, ""),
        lambda *_args: (True, ""),
        lambda *args: (placed.append(args) or True, "", 7),
        lambda *_args: (True, ""),
        lambda *_args: (True, ""),
    )
    socket = SimpleNamespace(send=sent.append)
    event = {
        "schema": "obsidience.shell.event.v1",
        "type": "window.place.request",
        "token": "tool.place.1",
        "surface_id": "samsung",
        "window_id": "0x123",
        "expected_revision": 4,
        "destination_surface_id": "usb-c",
        "tile_bounds": None,
        "workspace_tiling": [
            {"surface_id": "samsung", "columns": 8, "rows": 2},
            {"surface_id": "usb-c", "columns": 3, "rows": 2},
            {"surface_id": "dp-4", "columns": 4, "rows": 1},
        ],
    }

    transport._handle(socket, json.dumps(event))
    assert placed == [
        ("samsung", "0x123", 4, "usb-c", {
            "samsung": (8, 2), "usb-c": (3, 2), "dp-4": (4, 1)
        }, None)
    ]
    result = json.loads(sent[0])
    assert result["type"] == "window.place.result"
    assert result["destination_surface_id"] == "usb-c"
    assert result["post_revision"] == 7
    assert result["verified_tile_bounds"] is None

    tile = {"surface_id": "usb-c", "columns": 3, "rows": 2,
            "left": 0, "top": 0, "right": 1, "bottom": 2}
    event["tile_bounds"] = tile
    transport._handle(socket, json.dumps(event))
    assert json.loads(sent[-1])["verified_tile_bounds"] == tile
    transport.place = lambda *_args: (False, "placement_not_observed", 0)
    transport._handle(socket, json.dumps(event))
    assert json.loads(sent[-1])["verified_tile_bounds"] is None


def test_failed_transfer_cancels_only_the_exact_window(monkeypatch) -> None:
    backend = HyprlandSurfaceWindows(lambda *_args: None)
    messages: list[str] = []
    monitors = [
        {
            "id": 0,
            "name": "HDMI-A-1",
            "x": 0,
            "y": 0,
            "width": 5120,
            "height": 1440,
            "scale": 1,
        },
        {
            "id": 1,
            "name": "HDMI-A-2",
            "x": 0,
            "y": 1440,
            "width": 3840,
            "height": 1100,
            "scale": 2,
        },
    ]
    active = {
        "address": "0x123",
        "monitor": 0,
        "at": [5, 5],
        "size": [634, 713],
    }
    monkeypatch.setattr(
        backend,
        "_json",
        lambda name, *_args: monitors if name == "monitors" else active,
    )
    monkeypatch.setattr(
        backend,
        "_layout_message",
        lambda message: (
            messages.append(message)
            or SimpleNamespace(returncode=0, stdout="ok\n", stderr="")
        ),
    )
    monkeypatch.setattr(
        backend,
        "_dispatch",
        lambda _expression: SimpleNamespace(
            returncode=1, stdout="rejected\n", stderr=""
        ),
    )

    grids = {"samsung": (8, 2), "usb-c": (3, 2), "dp-4": (4, 1)}
    assert backend.layout("samsung", "0x123", "surface", "bottom", grids) == (
        False,
        "move_rejected",
    )
    assert messages[0].startswith("transfer 0x123 dp-4 4 1 top ")
    assert messages[1] == "cancel 0x123"


def test_module_classification_requires_both_exact_initial_fields() -> None:
    assert (
        _module_pane_id(
            {
                "initialClass": "io.obsidience.shell",
                "initialTitle": "obsidience-pane:settings",
            }
        )
        == "settings"
    )
    assert (
        _module_pane_id(
            {
                "initialClass": "io.obsidience.shell",
                "initialTitle": "Settings",
            }
        )
        == ""
    )
    assert (
        _module_pane_id(
            {
                "initialClass": "other",
                "initialTitle": "obsidience-pane:settings",
            }
        )
        == ""
    )
    assert (
        _module_pane_id(
            {
                "initialClass": "io.obsidience.shell",
                "initialTitle": "obsidience-pane:Settings",
            }
        )
        == ""
    )


def test_hyprland_projection_uses_monitor_local_geometry(monkeypatch, tmp_path) -> None:
    published: dict[str, tuple[str, tuple[ApplicationWindow, ...], bool]] = {}
    backend = HyprlandSurfaceWindows(
        lambda surface, active, windows, awake: published.__setitem__(
            surface, (active, windows, awake)
        )
    )
    monitors = [
        {
            "id": 2,
            "name": "DP-8",
            "x": 1920,
            "y": 1440,
            "width": 3840,
            "height": 2400,
            "scale": 2,
            "dpmsStatus": True,
            "activeWorkspace": {"id": 3, "name": "3"},
        }
    ]
    clients = [
        {
            "address": "0x123",
            "class": "quickshell",
            "initialClass": "io.obsidience.shell",
            "initialTitle": "obsidience-pane:settings",
            "title": "Settings",
            "monitor": 2,
            "at": [3000, 1520],
            "size": [800, 680],
            "pid": 42,
            "workspace": {"id": 3, "name": "3"},
            "mapped": True,
        },
        {
            "address": "0x124",
            "class": "io.obsidience.shell",
            "initialClass": "io.obsidience.shell",
            "initialTitle": "Settings",
            "title": "Not a module",
            "monitor": 2,
            "at": [1920, 1440],
            "size": [640, 480],
            "workspace": {"id": 4, "name": "4"},
            "mapped": True,
        },
        {
            "address": "0x125",
            "class": "example",
            "initialClass": "example",
            "initialTitle": "Example",
            "monitor": 2,
            "at": [1920, 1440],
            "size": [0, 480],
            "mapped": True,
        },
    ]

    def state(name, *_args):
        return {
            "monitors": monitors,
            "clients": clients,
            "activewindow": {"address": "0x123", "monitor": 2, "fullscreen": 0},
        }[name]

    monkeypatch.setattr(backend, "_json", state)
    monkeypatch.setattr(
        hyprland_module, "_FULLSCREEN_STATE", tmp_path / "fullscreen.state"
    )
    backend._publish()

    active, windows, awake = published["usb-c"]
    assert active == "0x123"
    assert awake is True
    assert len(windows) == 2
    module = next(window for window in windows if window.window_id == "0x123")
    assert module.window_kind == "module"
    assert module.pane_id == "settings"
    assert module.app_id == "io.obsidience.shell"
    assert module.local_rect == LocalRect(1080, 80, 800, 680)
    assert module.visible_on_workspace is True
    ordinary = next(window for window in windows if window.window_id == "0x124")
    assert ordinary.window_kind == "application"
    assert ordinary.pane_id == ""
    assert ordinary.visible_on_workspace is False


def test_monitor_route_uses_logical_surface_geometry() -> None:
    monitors = [
        {
            "id": 0,
            "name": "HDMI-A-1",
            "x": 0,
            "y": 0,
            "width": 5120,
            "height": 1440,
            "scale": 1,
        },
        {
            "id": 1,
            "name": "HDMI-A-2",
            "x": 0,
            "y": 1440,
            "width": 3840,
            "height": 1100,
            "scale": 2,
        },
        {
            "id": 2,
            "name": "DP-8",
            "x": 1920,
            "y": 1440,
            "width": 3840,
            "height": 2400,
            "scale": 2,
        },
    ]
    left_window = {
        "monitor": 0,
        "at": [5, 5],
        "size": [634, 713],
    }
    right_window = {
        "monitor": 0,
        "at": [3200, 5],
        "size": [634, 713],
    }

    assert _monitor_route(monitors, left_window, "samsung", "bottom") == (
        "dp-4",
        "HDMI-A-2",
        "top",
        0.16770833333333332,
    )
    destination = _monitor_route(monitors, right_window, "samsung", "bottom")
    assert destination is not None
    assert destination[:3] == ("usb-c", "DP-8", "top")
    assert _monitor_route(monitors, left_window, "samsung", "left") is None


def test_workspace_state_applies_only_changed_native_grids() -> None:
    applied: list[tuple[str, int, int]] = []
    policies: list[tuple[int, bool, int, int, int, bool]] = []
    transport = ShellWindowTransport(
        WindowStateStore(),
        lambda *_args: (True, ""),
        lambda *_args: (True, ""),
        lambda *_args: (True, ""),
        lambda *_args: (True, ""),
        lambda *_args: (True, "", 1),
        lambda surface_id, columns, rows: (
            applied.append((surface_id, columns, rows)) or True,
            "",
        ),
        lambda limit, enabled, distance, duration, glow_hours, locked: (
            policies.append(
                (limit, enabled, distance, duration, glow_hours, locked)
            )
            or True,
            "",
        ),
    )
    event = {
        "schema": "obsidience.shell.event.v1",
        "type": "workspace.state",
        "workspace_tiling": [
            {"surface_id": "samsung", "columns": 8, "rows": 2},
            {"surface_id": "usb-c", "columns": 3, "rows": 2},
            {"surface_id": "dp-4", "columns": 4, "rows": 1},
        ],
    }

    transport._handle(object(), json.dumps(event))
    assert applied == [("dp-4", 4, 1), ("samsung", 8, 2), ("usb-c", 3, 2)]
    assert policies == [(25, False, 32, 3600, 3, False)]

    transport._handle(object(), json.dumps(event))
    assert len(applied) == 3
    assert len(policies) == 1

    event["workspace_tiling"][1] = {
        "surface_id": "usb-c",
        "columns": 4,
        "rows": 2,
    }
    transport._handle(object(), json.dumps(event))
    assert applied[-1] == ("usb-c", 4, 2)
    assert len(applied) == 4

    event["tile_resize_limit_percent"] = 20
    event["oled_mode_enabled"] = True
    event["oled_shift_distance_px"] = 40
    event["oled_travel_duration_seconds"] = 1800
    event["oled_glow_rotation_hours"] = 2
    event["session_locked"] = True
    transport._handle(object(), json.dumps(event))
    assert len(applied) == 4
    assert policies[-1] == (20, True, 40, 1800, 2, True)
    assert len(policies) == 2


def test_transport_restores_only_valid_exact_module_bounds() -> None:
    restored: list[tuple[object, ...]] = []
    sent: list[str] = []
    transport = ShellWindowTransport(
        WindowStateStore(),
        lambda *_args: (True, ""),
        lambda *_args: (True, ""),
        lambda *_args: (True, ""),
        lambda *args: (restored.append(args) or True, ""),
        lambda *_args: (True, "", 1),
        lambda *_args: (True, ""),
        lambda *_args: (True, ""),
    )
    socket = SimpleNamespace(send=sent.append)
    event = {
        "schema": "obsidience.shell.event.v1",
        "type": "window.layout.restore.request",
        "token": "restore.reader.1",
        "surface_id": "samsung",
        "window_id": "0x123",
        "pane_id": "reader",
        "expected_revision": 4,
        "tile_bounds": {
            "surface_id": "samsung",
            "columns": 8,
            "rows": 2,
            "left": 5,
            "top": 0,
            "right": 8,
            "bottom": 2,
        },
    }

    transport._handle(socket, json.dumps(event))
    assert restored == [
        (
            "samsung",
            "0x123",
            4,
            "reader",
            event["tile_bounds"],
        )
    ]
    result = json.loads(sent[0])
    assert result["type"] == "window.layout.restore.result"
    assert result["success"] is True

    event["tile_bounds"] = {**event["tile_bounds"], "right": 9}
    transport._handle(socket, json.dumps(event))
    assert len(restored) == 1
    assert len(sent) == 1


def test_workspace_policy_rejects_invalid_or_partial_values() -> None:
    defaults = {
        "tile_resize_limit_percent": 25,
        "oled_mode_enabled": False,
        "oled_shift_distance_px": 32,
        "oled_travel_duration_seconds": 3600,
        "oled_glow_rotation_hours": 3,
        "session_locked": False,
    }
    assert ShellWindowTransport._policy({}) == (25, False, 32, 3600, 3, False)
    assert ShellWindowTransport._policy(defaults) == (
        25, False, 32, 3600, 3, False
    )

    for field, value in (
        ("tile_resize_limit_percent", True),
        ("tile_resize_limit_percent", -1),
        ("tile_resize_limit_percent", 26),
        ("tile_resize_limit_percent", 2.5),
        ("oled_mode_enabled", 1),
        ("oled_shift_distance_px", False),
        ("oled_shift_distance_px", 0),
        ("oled_shift_distance_px", 51),
        ("oled_travel_duration_seconds", True),
        ("oled_travel_duration_seconds", 59),
        ("oled_travel_duration_seconds", 86401),
        ("oled_glow_rotation_hours", True),
        ("oled_glow_rotation_hours", 0),
        ("oled_glow_rotation_hours", 25),
        ("session_locked", 0),
    ):
        candidate = dict(defaults)
        candidate[field] = value
        assert ShellWindowTransport._policy(candidate) is None


def test_hyprland_policy_message_is_bounded_and_atomic(monkeypatch) -> None:
    backend = HyprlandSurfaceWindows(lambda *_args: None)
    messages: list[str] = []
    monkeypatch.setattr(
        backend,
        "_layout_message",
        lambda message: (
            messages.append(message)
            or SimpleNamespace(returncode=0, stdout="ok\n", stderr="")
        ),
    )

    assert backend.configure_policy(25, True, 32, 3600, 3, False) == (True, "")
    assert messages == ["settings 25 1 32 3600 3 0"]
    assert backend.configure_policy(26, True, 50, 3600, 1, False) == (
        False,
        "invalid_policy",
    )
    assert backend.configure_policy(25, 1, 50, 3600, 1, False) == (
        False,
        "invalid_policy",
    )
    assert backend.configure_policy(25, True, 0, 3600, 1, False) == (
        False,
        "invalid_policy",
    )
    assert backend.configure_policy(25, True, 51, 3600, 1, False) == (
        False,
        "invalid_policy",
    )
    assert backend.configure_policy(25, True, 50, 59, 1, False) == (
        False,
        "invalid_policy",
    )
    assert backend.configure_policy(25, True, 50, 3600, 0, False) == (
        False,
        "invalid_policy",
    )
    assert len(messages) == 1
