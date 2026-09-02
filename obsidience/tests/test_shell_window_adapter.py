"""Behavioral contracts for the bounded Surface window-state model."""

from __future__ import annotations

import json

from obsidience.shell.adapter.windows.hyprland import (
    HyprlandSurfaceWindows,
    _monitor_route,
)
from obsidience.shell.adapter.windows.model import (
    ApplicationWindow,
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


def test_exact_window_rejects_stale_revision_and_unknown_surface() -> None:
    store = WindowStateStore()
    target = ApplicationWindow("exact-id", "example", "Exact")
    state = store.update("dp-4", "", (target,))
    assert state is not None
    assert store.exact_window("dp-4", "exact-id", state.revision) == target
    assert store.exact_window("dp-4", "exact-id", state.revision - 1) is None
    assert store.exact_window("usb-c", "exact-id", state.revision) is None
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
    transport = ShellWindowTransport(
        WindowStateStore(),
        lambda *_args: (True, ""),
        lambda *_args: (True, ""),
        lambda *_args: (True, ""),
        lambda surface_id, columns, rows: (
            applied.append((surface_id, columns, rows)) or True,
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

    transport._handle(object(), json.dumps(event))
    assert len(applied) == 3

    event["workspace_tiling"][1] = {
        "surface_id": "usb-c",
        "columns": 4,
        "rows": 2,
    }
    transport._handle(object(), json.dumps(event))
    assert applied[-1] == ("usb-c", 4, 2)
    assert len(applied) == 4
