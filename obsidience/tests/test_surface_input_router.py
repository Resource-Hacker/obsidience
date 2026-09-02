from __future__ import annotations

import errno
import json
from pathlib import Path
import site
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

# The router is a system service and deliberately uses distro-owned D-Bus,
# evdev, GI, and Xlib bindings rather than duplicating them in the harness venv.
system_site = (
    Path(sys.base_prefix)
    / "lib"
    / f"python{sys.version_info.major}.{sys.version_info.minor}"
    / "site-packages"
)
if system_site.is_dir():
    site.addsitedir(str(system_site))

from obsidience.shell.input import router as router_module
from obsidience.shell.input.router import LegacyEndpoint, SurfaceInputRouter
from obsidience.shell.input.surface_layout import SurfaceLayout


def load_dbus_bridge():
    try:
        from obsidience.shell.input import dbus_bridge
    except ModuleNotFoundError as error:
        if error.name not in {"dbus", "gi"}:
            raise
        pytest.skip(f"system D-Bus bindings unavailable in test environment: {error.name}")
    return dbus_bridge


def layout() -> SurfaceLayout:
    return SurfaceLayout.from_dict(
        {
            "schema": "obsidience.surface-layout.v1",
            "revision": 0,
            "surfaces": [
                {
                    "id": "samsung",
                    "backend": "kwin-wayland",
                    "display": "wayland",
                    "pixel_width": 5120,
                    "pixel_height": 1440,
                    "logical_width": 5120,
                    "logical_height": 1440,
                    "device_scale": 1,
                    "map_rect": {"x": 0, "y": 0, "width": 5120, "height": 1440},
                },
                {
                    "id": "dp-4",
                    "backend": "x11",
                    "display": ":2",
                    "x_screen": 1,
                    "pixel_width": 3840,
                    "pixel_height": 1100,
                    "logical_width": 1920,
                    "logical_height": 550,
                    "device_scale": 2,
                    "map_rect": {"x": 0, "y": 1440, "width": 1706, "height": 489},
                },
                {
                    "id": "usb-c",
                    "backend": "x11",
                    "display": ":2",
                    "x_screen": 0,
                    "pixel_width": 3840,
                    "pixel_height": 2400,
                    "logical_width": 1920,
                    "logical_height": 1200,
                    "device_scale": 2,
                    "map_rect": {"x": 1706, "y": 1440, "width": 1707, "height": 1067},
                },
            ],
        }
    )


class FakeRoot:
    def __init__(self) -> None:
        self.warps: list[tuple[int, int]] = []
        self.cursor: list[str] = []

    def warp_pointer(self, x: int, y: int) -> None:
        self.warps.append((x, y))

    def xfixes_show_cursor(self) -> None:
        self.cursor.append("show")

    def xfixes_hide_cursor(self) -> None:
        self.cursor.append("hide")


class FakeScreen:
    def __init__(self, root: FakeRoot) -> None:
        self.root = root


class FakeDisplay:
    def __init__(self) -> None:
        self.roots = {0: FakeRoot(), 1: FakeRoot()}
        self.screen_calls: list[int] = []
        self.sync_count = 0

    def screen(self, index: int) -> FakeScreen:
        self.screen_calls.append(index)
        return FakeScreen(self.roots[index])

    def sync(self) -> None:
        self.sync_count += 1

    @staticmethod
    def keysym_to_keycode(keysym: int) -> int:
        return keysym


class FakeCursorController:
    def __init__(self) -> None:
        self.events: dict[str, list[str]] = {"dp-4": [], "usb-c": []}
        self.closed = False

    def set_visible(self, surface_id: str, visible: bool) -> None:
        self.events[surface_id].append("show" if visible else "hide")

    def close(self) -> None:
        self.closed = True


def endpoints(tmp_path: Path) -> tuple[LegacyEndpoint, ...]:
    return (
        LegacyEndpoint("dp-4", tmp_path / "dp4.cmd", tmp_path / "dp4.state"),
        LegacyEndpoint("usb-c", tmp_path / "usb.cmd", tmp_path / "usb.state"),
    )


def active_router(
    tmp_path: Path,
    surface_id: str = "dp-4",
    *,
    pane_mover=None,
) -> SurfaceInputRouter:
    router = SurfaceInputRouter(
        layout(),
        endpoints=endpoints(tmp_path),
        x_connection=FakeDisplay(),
        cursor_controller=FakeCursorController(),
        mouse_scales={"dp-4": 1, "usb-c": 1},
        pane_mover=pane_mover,
    )
    router.connect_display()
    router.active = True
    router.current_surface_id = surface_id
    return router


def keyboard_event(code: int, value: int) -> SimpleNamespace:
    return SimpleNamespace(type=router_module.ecodes.EV_KEY, code=code, value=value)


def test_retired_device_event_does_not_release_surface_ownership(tmp_path: Path) -> None:
    router = active_router(tmp_path, surface_id="usb-c")
    router.return_to_samsung = Mock()
    retired_device = SimpleNamespace(
        path="/dev/input/event-retired",
        read=Mock(side_effect=OSError(errno.EBADF, "Bad file descriptor")),
    )

    router.handle_device(retired_device)

    router.return_to_samsung.assert_not_called()
    assert router.active is True
    assert router.current_surface_id == "usb-c"


def test_unexpected_device_error_retains_existing_fail_open_behavior(tmp_path: Path) -> None:
    router = active_router(tmp_path, surface_id="usb-c")
    router.return_to_samsung = Mock()
    failed_device = SimpleNamespace(
        path="/dev/input/event-failed",
        read=Mock(side_effect=OSError(errno.EIO, "Input/output error")),
    )

    router.handle_device(failed_device)

    router.return_to_samsung.assert_called_once_with()


def test_pane_move_invokes_existing_shell_command_client(monkeypatch) -> None:
    run = Mock(return_value=SimpleNamespace(returncode=0))
    monkeypatch.setattr(router_module.subprocess, "run", run)

    assert router_module.invoke_pane_move("usb-c", "right") is True
    run.assert_called_once_with(
        [
            str(router_module.PANE_MOVE_PYTHON),
            str(router_module.PANE_MOVE_CLIENT),
            "usb-c",
            "right",
        ],
        stdin=router_module.subprocess.DEVNULL,
        stdout=router_module.subprocess.DEVNULL,
        stderr=router_module.subprocess.DEVNULL,
        timeout=1.5,
        check=False,
    )


@pytest.mark.parametrize(
    ("arrow", "direction"),
    (
        (router_module.ecodes.KEY_LEFT, "left"),
        (router_module.ecodes.KEY_RIGHT, "right"),
        (router_module.ecodes.KEY_UP, "top"),
        (router_module.ecodes.KEY_DOWN, "bottom"),
    ),
)
def test_side_surface_meta_shift_arrow_moves_once_without_forwarding_arrow(
    monkeypatch,
    tmp_path: Path,
    arrow: int,
    direction: str,
) -> None:
    pane_mover = Mock(return_value=True)
    router = active_router(tmp_path, pane_mover=pane_mover)
    fake_input = Mock()
    monkeypatch.setattr(router_module.xtest, "fake_input", fake_input)

    router.handle_keyboard(keyboard_event(router_module.ecodes.KEY_LEFTMETA, 1))
    router.handle_keyboard(keyboard_event(router_module.ecodes.KEY_LEFTSHIFT, 1))
    router.handle_keyboard(keyboard_event(arrow, 1))
    router.handle_keyboard(keyboard_event(arrow, 2))
    router.handle_keyboard(keyboard_event(arrow, 0))
    router.handle_keyboard(keyboard_event(router_module.ecodes.KEY_LEFTSHIFT, 0))
    router.handle_keyboard(keyboard_event(router_module.ecodes.KEY_LEFTMETA, 0))

    pane_mover.assert_called_once_with("dp-4", direction)
    arrow_keycode = router_module.keysym_for_evdev(arrow)
    assert all(call.args[2] != arrow_keycode for call in fake_input.call_args_list)
    assert fake_input.call_count == 4


def test_side_surface_pane_move_requires_exact_modifiers(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pane_mover = Mock(return_value=True)
    router = active_router(tmp_path, pane_mover=pane_mover)
    fake_input = Mock()
    monkeypatch.setattr(router_module.xtest, "fake_input", fake_input)

    for code in (
        router_module.ecodes.KEY_LEFTMETA,
        router_module.ecodes.KEY_LEFTSHIFT,
        router_module.ecodes.KEY_LEFTCTRL,
    ):
        router.handle_keyboard(keyboard_event(code, 1))
    router.handle_keyboard(keyboard_event(router_module.ecodes.KEY_LEFT, 1))
    router.handle_keyboard(keyboard_event(router_module.ecodes.KEY_LEFT, 2))
    router.handle_keyboard(keyboard_event(router_module.ecodes.KEY_LEFT, 0))

    pane_mover.assert_not_called()
    arrow_keycode = router_module.keysym_for_evdev(router_module.ecodes.KEY_LEFT)
    arrow_events = [
        call.args[1]
        for call in fake_input.call_args_list
        if call.args[2] == arrow_keycode
    ]
    assert arrow_events == [
        router_module.X.KeyPress,
        router_module.X.KeyPress,
        router_module.X.KeyRelease,
    ]


def test_pane_move_chord_is_not_intercepted_without_side_surface_ownership(
    monkeypatch,
    tmp_path: Path,
) -> None:
    pane_mover = Mock(return_value=True)
    router = SurfaceInputRouter(
        layout(),
        endpoints=endpoints(tmp_path),
        x_connection=FakeDisplay(),
        cursor_controller=FakeCursorController(),
        pane_mover=pane_mover,
    )
    fake_input = Mock()
    monkeypatch.setattr(router_module.xtest, "fake_input", fake_input)

    router.handle_keyboard(keyboard_event(router_module.ecodes.KEY_LEFTMETA, 1))
    router.handle_keyboard(keyboard_event(router_module.ecodes.KEY_LEFTSHIFT, 1))
    router.handle_keyboard(keyboard_event(router_module.ecodes.KEY_RIGHT, 1))

    pane_mover.assert_not_called()
    right_keycode = router_module.keysym_for_evdev(router_module.ecodes.KEY_RIGHT)
    assert any(call.args[2] == right_keycode for call in fake_input.call_args_list)


def test_touching_rectangles_are_the_only_edge_map() -> None:
    surface_layout = layout()

    assert surface_layout.route("samsung", "bottom", 1705, 1439).destination_id == "dp-4"
    assert surface_layout.route("samsung", "bottom", 1706, 1439).destination_id == "usb-c"
    assert surface_layout.route("dp-4", "right", 3839, 550).destination_id == "usb-c"
    assert surface_layout.route("usb-c", "left", 0, 550).destination_id == "dp-4"
    assert surface_layout.route("usb-c", "left", 0, 2000) is None
    assert surface_layout.route("usb-c", "top", 1920, 0).destination_id == "samsung"


def test_one_x_connection_supplies_both_screen_roots(monkeypatch, tmp_path: Path) -> None:
    connection = FakeDisplay()
    open_display = Mock(return_value=connection)
    monkeypatch.setattr("obsidience.shell.input.router.display.Display", open_display)
    router = SurfaceInputRouter(
        layout(),
        endpoints=endpoints(tmp_path),
        cursor_controller=FakeCursorController(),
    )

    router.connect_display()
    router.connect_display()

    open_display.assert_called_once_with(":2")
    assert connection.screen_calls == [1, 0]
    assert router.roots == {"dp-4": connection.roots[1], "usb-c": connection.roots[0]}


def test_cursor_visibility_changes_are_not_reference_counted_twice(tmp_path: Path) -> None:
    connection = FakeDisplay()
    cursor = FakeCursorController()
    router = SurfaceInputRouter(
        layout(),
        endpoints=endpoints(tmp_path),
        x_connection=connection,
        cursor_controller=cursor,
    )

    router.connect_display()
    router.set_active_cursor("dp-4")
    router.set_active_cursor("dp-4")
    router.set_active_cursor("usb-c")
    router.set_active_cursor("usb-c")

    assert cursor.events["dp-4"] == ["hide", "show", "hide"]
    assert cursor.events["usb-c"] == ["hide", "show"]


def test_dbus_main_keeps_the_well_known_name_owner(monkeypatch) -> None:
    dbus_bridge = load_dbus_bridge()
    bus = object()
    bus_name = object()
    bus_name_factory = Mock(return_value=bus_name)
    bridge_factory = Mock()
    projection_factory = Mock()
    loop = Mock()

    monkeypatch.setattr(dbus_bridge, "DBusGMainLoop", Mock())
    monkeypatch.setattr(dbus_bridge.dbus, "SessionBus", Mock(return_value=bus))
    monkeypatch.setattr(dbus_bridge.dbus.service, "BusName", bus_name_factory)
    monkeypatch.setattr(dbus_bridge, "SurfaceBridge", bridge_factory)
    monkeypatch.setattr(dbus_bridge, "LockStateProjection", projection_factory)
    monkeypatch.setattr(dbus_bridge.GLib, "MainLoop", Mock(return_value=loop))

    dbus_bridge.main()

    bus_name_factory.assert_called_once_with(dbus_bridge.BUS_NAME, bus=bus)
    bridge_factory.assert_called_once_with(bus_name, dbus_bridge.OBJECT_PATH)
    projection_factory.assert_called_once_with(bus, bridge_factory.return_value)
    loop.run.assert_called_once_with()


def test_dbus_adapter_readiness_requires_the_exact_token(monkeypatch, tmp_path: Path) -> None:
    dbus_bridge = load_dbus_bridge()
    ready_state = tmp_path / "edge-adapter.ready"
    bridge = object.__new__(dbus_bridge.SurfaceBridge)
    monkeypatch.setattr(dbus_bridge, "ADAPTER_READY_STATE", ready_state)

    assert bridge.AdapterReady("wrong") is False
    assert not ready_state.exists()

    assert bridge.AdapterReady("ready") is True
    assert ready_state.read_text(encoding="utf-8") == "ready\n"


def test_dbus_pane_move_is_validated_and_bounded(monkeypatch, tmp_path: Path) -> None:
    dbus_bridge = load_dbus_bridge()
    bridge = object.__new__(dbus_bridge.SurfaceBridge)
    run = Mock(return_value=SimpleNamespace(returncode=0))
    lock_state = tmp_path / "lock-state"
    lock_state.write_text("0\n", encoding="utf-8")
    monkeypatch.setattr(dbus_bridge, "LOCK_STATE", lock_state)
    monkeypatch.setattr(dbus_bridge.subprocess, "run", run)

    assert bridge.MovePane("unknown", "left") is False
    assert bridge.MovePane("usb-c", "diagonal") is False
    run.assert_not_called()

    assert bridge.MovePane(" DP-4 ", " RIGHT ") is True
    run.assert_called_once_with(
        [
            str(dbus_bridge.PANE_MOVE_PYTHON),
            str(dbus_bridge.PANE_MOVE_CLIENT),
            "dp-4",
            "right",
        ],
        stdin=dbus_bridge.subprocess.DEVNULL,
        stdout=dbus_bridge.subprocess.DEVNULL,
        stderr=dbus_bridge.subprocess.DEVNULL,
        timeout=1.5,
        check=False,
    )


def test_dbus_lock_projection_is_atomic_and_routes_the_one_router(
    monkeypatch,
    tmp_path: Path,
) -> None:
    dbus_bridge = load_dbus_bridge()
    lock_dir = tmp_path / "obsidience-shell"
    lock_state = lock_dir / "lock-state"
    monkeypatch.setattr(dbus_bridge, "LOCK_STATE_DIR", lock_dir)
    monkeypatch.setattr(dbus_bridge, "LOCK_STATE", lock_state)
    get_active = Mock(return_value=False)
    monkeypatch.setattr(
        dbus_bridge.dbus,
        "Interface",
        Mock(return_value=SimpleNamespace(GetActive=get_active)),
    )
    bus = SimpleNamespace(
        add_signal_receiver=Mock(),
        get_object=Mock(return_value=object()),
    )
    bridge = SimpleNamespace(_send=Mock(return_value=True))

    projection = dbus_bridge.LockStateProjection(bus, bridge)

    assert lock_state.read_text(encoding="utf-8") == "0\n"
    assert lock_state.stat().st_mode & 0o777 == 0o600
    assert bridge._send.call_count == 0
    projection._about_to_lock()
    assert lock_state.read_text(encoding="utf-8") == "1\n"
    bridge._send.assert_called_once_with(dbus_bridge.DP4_FIFO, "lock")
    projection._active_changed(False)
    assert lock_state.read_text(encoding="utf-8") == "0\n"
    assert bridge._send.call_args_list == [
        ((dbus_bridge.DP4_FIFO, "lock"),),
        ((dbus_bridge.DP4_FIFO, "unlock"),),
    ]


def test_locked_router_releases_once_rejects_entry_and_does_not_restore(
    monkeypatch,
    tmp_path: Path,
) -> None:
    router = active_router(tmp_path, surface_id="usb-c")
    router.release_injected = Mock()
    router.ungrab_devices = Mock()
    router.enter_target = Mock(wraps=router.enter_target)
    pane_mover = Mock(return_value=True)
    router.pane_mover = pane_mover
    fake_input = Mock()
    monkeypatch.setattr(router_module.xtest, "fake_input", fake_input)

    router.handle_command("lock", "usb-c")

    assert router.locked is True
    assert router.active is False
    assert router.current_surface_id is None
    router.release_injected.assert_called_once_with()
    router.ungrab_devices.assert_called_once_with()

    router.handle_command("lock", "dp-4")
    router.handle_command("enter 20", "usb-c")
    router.handle_command("toggle 20", "usb-c")
    router.handle_command("handoff", "usb-c")
    router.handle_command("refresh", "usb-c")
    router.handle_keyboard(keyboard_event(router_module.ecodes.KEY_LEFTMETA, 1))

    router.release_injected.assert_called_once_with()
    router.ungrab_devices.assert_called_once_with()
    router.enter_target.assert_not_called()
    pane_mover.assert_not_called()
    fake_input.assert_not_called()

    router.handle_command("unlock", "usb-c")
    assert router.locked is False
    assert router.active is False
    assert router.current_surface_id is None


def test_peer_switch_preserves_grab_and_held_state(tmp_path: Path) -> None:
    router = active_router(tmp_path)
    router.set_position(3838, 550)
    router.pressed_buttons = {1}
    router.pressed_keys = {42}
    router.release_injected = Mock()
    router.ungrab_devices = Mock()

    router.apply_pointer_motion(2, 0)

    assert router.active is True
    assert router.current_surface_id == "usb-c"
    assert router.x == 12
    assert router.pressed_buttons == {1}
    assert router.pressed_keys == {42}
    router.release_injected.assert_not_called()
    router.ungrab_devices.assert_not_called()
    assert (tmp_path / "dp4.state").read_text() == "inactive\n"
    assert (tmp_path / "usb.state").read_text().startswith("active 12 ")


def test_non_touching_part_of_usb_edge_does_not_switch(tmp_path: Path) -> None:
    router = active_router(tmp_path, "usb-c")
    router.set_position(1, 2000)

    router.apply_pointer_motion(-2, 0)

    assert router.current_surface_id == "usb-c"
    assert router.x == 0


def test_samsung_return_is_the_only_release_boundary(tmp_path: Path) -> None:
    router = active_router(tmp_path, "usb-c")
    router.set_position(1920, 1)
    router.restore_main_cursor_at = Mock(return_value=True)
    router.release_injected = Mock()
    router.ungrab_devices = Mock()

    router.apply_pointer_motion(0, -2)

    assert router.active is False
    assert router.current_surface_id is None
    router.release_injected.assert_called_once_with()
    router.ungrab_devices.assert_called_once_with()
    main_x, main_y = router.restore_main_cursor_at.call_args.args
    assert 1706 <= main_x <= 3412
    assert main_y >= 1427
    assert (tmp_path / "dp4.state").read_text() == "inactive\n"
    assert (tmp_path / "usb.state").read_text() == "inactive\n"


def test_legacy_fifos_and_new_commands_select_layout_surfaces(tmp_path: Path) -> None:
    router = active_router(tmp_path)
    router.release_injected = Mock()
    router.ungrab_devices = Mock()

    router.handle_command("enterxy 20 30", "usb-c")
    assert (router.current_surface_id, router.x, router.y) == ("usb-c", 20, 30)

    router.handle_command("switchxy dp-4 40 50", "usb-c")
    assert (router.current_surface_id, router.x, router.y) == ("dp-4", 40, 50)
    router.release_injected.assert_not_called()
    router.ungrab_devices.assert_not_called()

    router.active = False
    router.current_surface_id = None
    router.enter_target = Mock(return_value=True)
    router.handle_command("enter-map samsung bottom 1706 1439", "dp-4")
    router.enter_target.assert_called_once_with("usb-c", 0, 12, allow_active_switch=False)


def test_cursor_move_is_unacknowledged_while_warp_keeps_exact_ack(
    monkeypatch,
    tmp_path: Path,
) -> None:
    router = SurfaceInputRouter(
        layout(),
        endpoints=endpoints(tmp_path),
        x_connection=FakeDisplay(),
        cursor_controller=FakeCursorController(),
    )
    state_path = tmp_path / "main-cursor.state"
    fifo_path = tmp_path / "main-cursor.cmd"
    writes: list[bytes] = []
    monkeypatch.setattr(router_module, "MAIN_CURSOR_FIFO", fifo_path)
    monkeypatch.setattr(router_module, "MAIN_CURSOR_STATE", state_path)
    monkeypatch.setattr(router_module.time, "time_ns", Mock(return_value=123))
    monkeypatch.setattr(router_module.os, "open", Mock(return_value=42))
    monkeypatch.setattr(
        router_module.os,
        "write",
        lambda _fd, payload: writes.append(payload) or len(payload),
    )
    monkeypatch.setattr(router_module.os, "close", Mock())

    state_path.write_text("failed 123\n", encoding="utf-8")
    assert router.move_main_cursor_at(11, 12, wait_for_ack=False) is True
    assert writes == [b"move 11 12\n"]

    state_path.write_text("ack 123\n", encoding="utf-8")
    assert router.move_main_cursor_at(13, 14, wait_for_ack=True) is True
    assert writes[-1] == b"warp 13 14 123\n"


def test_layout_hot_reload_keeps_last_good_geometry(tmp_path: Path) -> None:
    layout_path = tmp_path / "surface-layout.json"
    original = layout()
    raw = {
        "schema": original.schema,
        "revision": 0,
        "surfaces": [
            {
                "id": surface.id,
                "backend": surface.backend,
                "display": surface.display,
                "x_screen": surface.x_screen,
                "pixel_width": surface.pixel_width,
                "pixel_height": surface.pixel_height,
                "logical_width": surface.logical_width,
                "logical_height": surface.logical_height,
                "device_scale": surface.device_scale,
                "map_rect": {
                    "x": surface.map_rect.x,
                    "y": surface.map_rect.y,
                    "width": surface.map_rect.width,
                    "height": surface.map_rect.height,
                },
            }
            for surface in original.surfaces
        ],
    }
    layout_path.write_text(json.dumps(raw))
    router = SurfaceInputRouter(
        original,
        endpoints=endpoints(tmp_path),
        x_connection=FakeDisplay(),
        layout_path=layout_path,
    )

    raw["revision"] = 1
    raw["surfaces"][2]["map_rect"]["x"] = 1800
    layout_path.write_text(json.dumps(raw))
    router.reload_layout_if_changed()
    assert router.layout.revision == 1
    assert router.layout.surface("usb-c").map_rect.x == 1800

    layout_path.write_text("not json")
    router.reload_layout_if_changed()
    assert router.layout.revision == 1
    assert router.layout.surface("usb-c").map_rect.x == 1800


def test_non_numeric_screen_and_revision_raise_value_error() -> None:
    raw = {
        "schema": "obsidience.surface-layout.v1",
        "revision": "zero",
        "surfaces": [],
    }
    try:
        SurfaceLayout.from_dict(raw)
    except ValueError as exc:
        assert "revision" in str(exc)
    else:
        raise AssertionError("string revision was accepted")

    raw = {
        "schema": "obsidience.surface-layout.v1",
        "revision": 0,
        "surfaces": [
            {
                "id": "usb-c",
                "backend": "x11",
                "display": ":2",
                "x_screen": "zero",
                "pixel_width": 1,
                "pixel_height": 1,
                "logical_width": 1,
                "logical_height": 1,
                "device_scale": 1,
                "map_rect": {"x": 0, "y": 0, "width": 1, "height": 1},
            }
        ],
    }
    try:
        SurfaceLayout.from_dict(raw)
    except ValueError as exc:
        assert "x_screen" in str(exc)
    else:
        raise AssertionError("string x_screen was accepted")
