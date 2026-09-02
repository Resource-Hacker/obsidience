"""Behavioral contracts for the bounded Surface window-state model."""

from __future__ import annotations

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
