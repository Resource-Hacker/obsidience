"""Behavioral contracts for the bounded Surface window-state model."""

from __future__ import annotations

from obsidience.shell.adapter.windows.hyprland import _monitor_route
from obsidience.shell.adapter.windows.model import (
    ApplicationWindow,
    WindowStateStore,
)


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
