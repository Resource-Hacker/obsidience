#!/usr/bin/env python3
"""Single-owner physical input router for isolated Obsidience Surfaces."""

from __future__ import annotations

import ctypes
import errno
import fcntl
import os
import selectors
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from evdev import InputDevice, ecodes, list_devices
from Xlib import X, XK, display
from Xlib.ext import xtest

try:
    from .surface_layout import EDGES, Surface, SurfaceLayout
except ImportError:  # Direct source execution during recovery.
    from surface_layout import EDGES, Surface, SurfaceLayout


USER_UID = int(os.environ.get("DP4_USER_UID", "1000"))
USER_GID = int(os.environ.get("DP4_USER_GID", "1000"))
RUNTIME_DIR = Path(os.environ.get("DP4_RUNTIME_DIR", f"/run/user/{USER_UID}"))
LOCK_STATE_PATH = RUNTIME_DIR / "obsidience-shell" / "lock-state"
DEFAULT_LAYOUT_PATH = Path(__file__).resolve().parents[1] / "state" / "initial-surface-layout.json"
LAYOUT_PATH = Path(os.environ.get("OBSIDIENCE_SURFACE_LAYOUT", DEFAULT_LAYOUT_PATH))
LOG = Path(os.environ.get("OBSIDIENCE_SURFACE_ROUTER_LOG", "/tmp/obsidience-surface-router.log"))
MAIN_CURSOR_FIFO = Path(
    os.environ.get("EDGE_MAIN_CURSOR_FIFO", str(RUNTIME_DIR / "edge-main-cursor.cmd"))
)
MAIN_CURSOR_STATE = Path(
    os.environ.get("EDGE_MAIN_CURSOR_STATE", str(RUNTIME_DIR / "edge-main-cursor.state"))
)
MAIN_CURSOR_ACK_TIMEOUT = float(os.environ.get("EDGE_MAIN_CURSOR_ACK_TIMEOUT", "0.1"))
POINTER_MATCH = os.environ.get("DP4_POINTER_MATCH", "").strip().lower()
PANE_MOVE_PYTHON = Path(__file__).resolve().parents[3] / ".venv" / "bin" / "python"
PANE_MOVE_CLIENT = Path(__file__).with_name("move_pane.py")

META_KEYS = frozenset((ecodes.KEY_LEFTMETA, ecodes.KEY_RIGHTMETA))
SHIFT_KEYS = frozenset((ecodes.KEY_LEFTSHIFT, ecodes.KEY_RIGHTSHIFT))
CONTROL_KEYS = frozenset((ecodes.KEY_LEFTCTRL, ecodes.KEY_RIGHTCTRL))
ALT_KEYS = frozenset((ecodes.KEY_LEFTALT, ecodes.KEY_RIGHTALT))
MODIFIER_KEYS = META_KEYS | SHIFT_KEYS | CONTROL_KEYS | ALT_KEYS
PANE_MOVE_DIRECTIONS = {
    ecodes.KEY_LEFT: "left",
    ecodes.KEY_RIGHT: "right",
    ecodes.KEY_UP: "top",
    ecodes.KEY_DOWN: "bottom",
}

X11 = ctypes.CDLL("libX11.so.6")
XFIXES = ctypes.CDLL("libXfixes.so.3")
X11.XOpenDisplay.argtypes = [ctypes.c_char_p]
X11.XOpenDisplay.restype = ctypes.c_void_p
X11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
X11.XDefaultRootWindow.restype = ctypes.c_ulong
X11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
X11.XCloseDisplay.argtypes = [ctypes.c_void_p]
XFIXES.XFixesHideCursor.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
XFIXES.XFixesShowCursor.argtypes = [ctypes.c_void_p, ctypes.c_ulong]


@dataclass(frozen=True)
class LegacyEndpoint:
    surface_id: str
    fifo: Path
    state: Path


def legacy_endpoints(runtime_dir: Path = RUNTIME_DIR) -> tuple[LegacyEndpoint, ...]:
    return (
        LegacyEndpoint(
            "dp-4",
            runtime_dir / "dp4-edge-bridge.cmd",
            runtime_dir / "dp4-edge-bridge.state",
        ),
        LegacyEndpoint(
            "usb-c",
            runtime_dir / "usb-monitor-edge-bridge.cmd",
            runtime_dir / "usb-monitor-edge-bridge.state",
        ),
    )


IGNORED_NAME_PARTS = (
    "power button",
    "sleep button",
    "video bus",
    "pc speaker",
    "hda ",
    "aura led",
)

KEYSYM_NAMES = {
    "KEY_ESC": "Escape",
    "KEY_BACKSPACE": "BackSpace",
    "KEY_TAB": "Tab",
    "KEY_ENTER": "Return",
    "KEY_SPACE": "space",
    "KEY_CAPSLOCK": "Caps_Lock",
    "KEY_LEFTSHIFT": "Shift_L",
    "KEY_RIGHTSHIFT": "Shift_R",
    "KEY_LEFTCTRL": "Control_L",
    "KEY_RIGHTCTRL": "Control_R",
    "KEY_LEFTALT": "Alt_L",
    "KEY_RIGHTALT": "Alt_R",
    "KEY_LEFTMETA": "Super_L",
    "KEY_RIGHTMETA": "Super_R",
    "KEY_COMPOSE": "Menu",
    "KEY_UP": "Up",
    "KEY_DOWN": "Down",
    "KEY_LEFT": "Left",
    "KEY_RIGHT": "Right",
    "KEY_HOME": "Home",
    "KEY_END": "End",
    "KEY_PAGEUP": "Page_Up",
    "KEY_PAGEDOWN": "Page_Down",
    "KEY_INSERT": "Insert",
    "KEY_DELETE": "Delete",
    "KEY_GRAVE": "grave",
    "KEY_MINUS": "minus",
    "KEY_EQUAL": "equal",
    "KEY_LEFTBRACE": "bracketleft",
    "KEY_RIGHTBRACE": "bracketright",
    "KEY_BACKSLASH": "backslash",
    "KEY_SEMICOLON": "semicolon",
    "KEY_APOSTROPHE": "apostrophe",
    "KEY_COMMA": "comma",
    "KEY_DOT": "period",
    "KEY_SLASH": "slash",
    "KEY_SYSRQ": "Print",
    "KEY_SCROLLLOCK": "Scroll_Lock",
    "KEY_PAUSE": "Pause",
    "KEY_NUMLOCK": "Num_Lock",
    "KEY_KPSLASH": "KP_Divide",
    "KEY_KPASTERISK": "KP_Multiply",
    "KEY_KPMINUS": "KP_Subtract",
    "KEY_KPPLUS": "KP_Add",
    "KEY_KPENTER": "KP_Enter",
    "KEY_KPDOT": "KP_Decimal",
    "KEY_KP0": "KP_0",
    "KEY_KP1": "KP_1",
    "KEY_KP2": "KP_2",
    "KEY_KP3": "KP_3",
    "KEY_KP4": "KP_4",
    "KEY_KP5": "KP_5",
    "KEY_KP6": "KP_6",
    "KEY_KP7": "KP_7",
    "KEY_KP8": "KP_8",
    "KEY_KP9": "KP_9",
}

BUTTON_MAP = {
    ecodes.BTN_LEFT: 1,
    ecodes.BTN_MIDDLE: 2,
    ecodes.BTN_RIGHT: 3,
    ecodes.BTN_SIDE: 8,
    ecodes.BTN_EXTRA: 9,
    ecodes.BTN_FORWARD: 9,
    ecodes.BTN_BACK: 8,
}


def log(message: str) -> None:
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n"
    try:
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(line)
    except OSError:
        pass
    print(line, end="", flush=True)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def invoke_pane_move(surface_id: str, direction: str) -> bool:
    try:
        result = subprocess.run(
            [str(PANE_MOVE_PYTHON), str(PANE_MOVE_CLIENT), surface_id, direction],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=1.5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def key_name(code: int) -> str:
    name = ecodes.KEY.get(code, "")
    if isinstance(name, list):
        name = name[0]
    return name


def keysym_for_evdev(code: int) -> int:
    name = key_name(code)
    if not name:
        return 0
    if name in KEYSYM_NAMES:
        return XK.string_to_keysym(KEYSYM_NAMES[name])
    if name.startswith("KEY_") and len(name) == 5 and name[-1].isalpha():
        return XK.string_to_keysym(name[-1].lower())
    if name.startswith("KEY_") and len(name) == 5 and name[-1].isdigit():
        return XK.string_to_keysym(name[-1])
    if name.startswith("KEY_F") and name[5:].isdigit():
        return XK.string_to_keysym(name[4:])
    return 0


def classify_devices() -> list[tuple[InputDevice, str]]:
    raw = []
    for path in sorted(list_devices()):
        try:
            device = InputDevice(path)
            flags = fcntl.fcntl(device.fd, fcntl.F_GETFL)
            fcntl.fcntl(device.fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            capabilities = device.capabilities()
        except Exception as exc:
            log(f"skip {path}: {exc}")
            continue

        name = (device.name or "").strip()
        lower_name = name.lower()
        if any(part in lower_name for part in IGNORED_NAME_PARTS):
            device.close()
            continue

        keys = set(capabilities.get(ecodes.EV_KEY, []))
        relative = set(capabilities.get(ecodes.EV_REL, []))
        raw.append(
            (
                path,
                device,
                lower_name,
                ecodes.REL_X in relative and ecodes.REL_Y in relative,
                bool(keys & set(BUTTON_MAP)),
                ecodes.KEY_A in keys and ecodes.KEY_SPACE in keys,
            )
        )

    has_keyd_keyboard = any(
        lower_name == "keyd virtual keyboard" and has_text
        for _path, _device, lower_name, _pointer, _buttons, has_text in raw
    )
    pointer_candidates = [item for item in raw if item[3] and item[4] and "virtual" not in item[2]]
    if POINTER_MATCH:
        preferred = [item for item in pointer_candidates if POINTER_MATCH in item[2]]
    else:
        preferred = [item for item in pointer_candidates if "g502 x plus" in item[2]] or pointer_candidates
    preferred_paths = {item[0] for item in preferred}

    devices = []
    for path, device, lower_name, _pointer, _buttons, has_text in raw:
        role = None
        if path in preferred_paths:
            role = "pointer"
        elif has_text and (not has_keyd_keyboard or lower_name == "keyd virtual keyboard"):
            role = "keyboard"
        if role:
            devices.append((device, role))
            log(f"device {role}: {device.path} {device.name}")
        else:
            device.close()
    return devices


class XFixesCursorController:
    """One native XFixes cursor reference per isolated X screen."""

    def __init__(self, surfaces: tuple[Surface, ...]):
        self.connections: dict[str, tuple[int, int]] = {}
        try:
            for surface in surfaces:
                display_name = f"{surface.display}.{surface.x_screen}".encode()
                connection = X11.XOpenDisplay(display_name)
                if not connection:
                    raise RuntimeError(f"cannot open X cursor display {display_name.decode()}")
                root = X11.XDefaultRootWindow(connection)
                self.connections[surface.id] = (connection, root)
        except Exception:
            self.close()
            raise

    def set_visible(self, surface_id: str, visible: bool) -> None:
        connection, root = self.connections[surface_id]
        if visible:
            XFIXES.XFixesShowCursor(connection, root)
        else:
            XFIXES.XFixesHideCursor(connection, root)
        X11.XSync(connection, 0)

    def close(self) -> None:
        for connection, _root in self.connections.values():
            X11.XCloseDisplay(connection)
        self.connections.clear()


class SurfaceInputRouter:
    """One evdev grab and one X connection across every isolated X Surface."""

    def __init__(
        self,
        layout: SurfaceLayout,
        *,
        endpoints: tuple[LegacyEndpoint, ...] | None = None,
        x_connection=None,
        cursor_controller=None,
        selector=None,
        mouse_scales: dict[str, float] | None = None,
        layout_path: Path | None = None,
        pane_mover: Callable[[str, str], bool] | None = None,
        locked: bool = False,
    ):
        self.layout = layout
        self.layout_path = layout_path
        self.layout_mtime_ns = self._layout_mtime()
        self.endpoints = endpoints or legacy_endpoints()
        self.selector = selector or selectors.DefaultSelector()
        self.display = x_connection
        self.cursor_controller = cursor_controller
        self.roots: dict[str, object] = {}
        self.cursor_visible: dict[str, bool] = {}
        self.devices: list[tuple[InputDevice, str]] = []
        self.device_roles: dict[int, str] = {}
        self.active = False
        self.locked = locked
        self.current_surface_id: str | None = None
        self.x = 0
        self.y = 0
        self.fx = 0.0
        self.fy = 0.0
        self.pressed_keys: set[int] = set()
        self.pressed_buttons: set[int] = set()
        self.held_modifiers: set[int] = set()
        self.consumed_pane_move_keys: set[int] = set()
        self.pane_mover = invoke_pane_move if pane_mover is None else pane_mover
        self.stop = False

        x_surfaces = self._validate_layout(layout)
        self.x_surfaces = x_surfaces
        self.x_surface_ids = frozenset(surface.id for surface in x_surfaces)
        if mouse_scales is None:
            samsung_scale = float(
                os.environ.get(
                    "ADMECH_SAMSUNG_MOUSE_SCALE",
                    os.environ.get(
                        "ADMECH_DP4_MOUSE_SCALE",
                        os.environ.get("DP4_MOUSE_SCALE", "1"),
                    ),
                )
            )
            mouse_scales = {
                "samsung": samsung_scale,
                "dp-4": float(
                    os.environ.get(
                        "ADMECH_DP4_MOUSE_SCALE",
                        os.environ.get("DP4_MOUSE_SCALE", "1"),
                    )
                ),
                "usb-c": float(
                    os.environ.get(
                        "ADMECH_USB_MOUSE_SCALE",
                        os.environ.get("EDGE_MOUSE_SCALE", "1"),
                    )
                ),
            }
        self.mouse_scales = mouse_scales

    @staticmethod
    def _validate_layout(layout: SurfaceLayout) -> tuple[Surface, ...]:
        x_surfaces = tuple(surface for surface in layout.surfaces if surface.backend == "x11")
        display_names = {surface.display for surface in x_surfaces}
        if not x_surfaces or display_names != {":2"}:
            raise ValueError("isolated Surfaces must share the single X display :2")
        if any(surface.x_screen is None for surface in x_surfaces):
            raise ValueError("every isolated X Surface must declare x_screen")
        return x_surfaces

    def _layout_mtime(self) -> int | None:
        if self.layout_path is None:
            return None
        try:
            return self.layout_path.stat().st_mtime_ns
        except OSError:
            return None

    def reload_layout_if_changed(self) -> None:
        mtime = self._layout_mtime()
        if mtime is None or mtime == self.layout_mtime_ns:
            return
        self.layout_mtime_ns = mtime
        try:
            candidate = SurfaceLayout.from_file(self.layout_path)
            x_surfaces = self._validate_layout(candidate)
            old_screens = {surface.id: surface.x_screen for surface in self.x_surfaces}
            new_screens = {surface.id: surface.x_screen for surface in x_surfaces}
            if old_screens != new_screens:
                raise ValueError("live layout edits cannot change X screen identity")
            if self.current_surface_id is not None:
                candidate.surface(self.current_surface_id)
        except (OSError, ValueError) as exc:
            log(f"ignored invalid Surface layout update: {exc}")
            return
        self.layout = candidate
        self.x_surfaces = x_surfaces
        log(f"loaded Surface layout revision {candidate.revision}")

    @property
    def current_surface(self) -> Surface:
        if self.current_surface_id is None:
            raise RuntimeError("input router has no active Surface")
        return self.layout.surface(self.current_surface_id)

    def connect_display(self) -> None:
        if not self.roots:
            if self.display is None:
                self.display = display.Display(":2")
            for surface in self.x_surfaces:
                self.roots[surface.id] = self.display.screen(surface.x_screen).root
            if self.cursor_controller is None:
                self.cursor_controller = XFixesCursorController(self.x_surfaces)
            self.set_active_cursor(None)

    def set_active_cursor(self, surface_id: str | None) -> None:
        if not self.roots or self.cursor_controller is None:
            return
        for candidate_id in self.roots:
            visible = candidate_id == surface_id
            if self.cursor_visible.get(candidate_id) == visible:
                continue
            try:
                self.cursor_controller.set_visible(candidate_id, visible)
                self.cursor_visible[candidate_id] = visible
            except Exception as exc:
                log(f"cursor visibility failed for {candidate_id}: {exc}")

    def close_cursor_controller(self) -> None:
        if self.cursor_controller is None:
            return
        try:
            self.cursor_controller.close()
        finally:
            self.cursor_controller = None
            self.cursor_visible.clear()

    def write_states(self) -> None:
        for endpoint in self.endpoints:
            if self.active and endpoint.surface_id == self.current_surface_id:
                text = f"active {self.x} {self.y}"
            else:
                text = "inactive"
            try:
                endpoint.state.write_text(text + "\n", encoding="utf-8")
                os.chown(endpoint.state, USER_UID, USER_GID)
                os.chmod(endpoint.state, 0o600)
            except OSError as exc:
                log(f"state write failed for {endpoint.surface_id}: {exc}")

    def refresh_devices(self) -> None:
        self.close_devices()
        self.devices = classify_devices()
        self.device_roles = {device.fd: role for device, role in self.devices}

    def close_devices(self) -> None:
        for device, _role in self.devices:
            try:
                self.selector.unregister(device.fd)
            except Exception:
                pass
            try:
                device.ungrab()
            except Exception:
                pass
            try:
                device.close()
            except Exception:
                pass
        self.devices = []
        self.device_roles = {}

    def flush_devices(self) -> None:
        for device, _role in self.devices:
            while True:
                try:
                    if not list(device.read()):
                        break
                except (BlockingIOError, OSError):
                    break

    def grab_devices(self, *, log_failures: bool = True) -> bool:
        device_lost = False
        self.flush_devices()
        for device, role in self.devices:
            try:
                try:
                    self.selector.unregister(device.fd)
                except Exception:
                    pass
                device.grab()
                self.selector.register(device.fd, selectors.EVENT_READ, device)
                log(f"grabbed {role}: {device.path} {device.name}")
            except OSError as exc:
                device_lost |= exc.errno in (errno.EBADF, errno.ENODEV, errno.ENXIO)
                if log_failures:
                    log(f"grab failed {device.path} {device.name}: {exc}")
        return device_lost

    def ungrab_devices(self) -> None:
        for device, _role in self.devices:
            try:
                self.selector.unregister(device.fd)
            except Exception:
                pass
            try:
                device.ungrab()
            except Exception:
                pass

    def capture_ready(self) -> bool:
        required = {role for _device, role in self.devices}
        grabbed = {
            role
            for device, role in self.devices
            if self.selector.get_map().get(device.fd) is not None
        }
        return "pointer" in grabbed and required <= grabbed

    def enter_target(
        self,
        surface_id: str,
        x: int,
        y: int,
        *,
        allow_active_switch: bool,
    ) -> bool:
        if self.locked:
            log(f"entry refused while session is locked: {surface_id}")
            return False
        surface = self.layout.surface(surface_id)
        if surface.backend != "x11" or surface.display != ":2":
            log(f"entry refused: {surface_id} is not an isolated X Surface")
            return False
        self.connect_display()
        if self.active:
            if not allow_active_switch:
                log("ignored duplicate Samsung entry while isolated capture is active")
                return False
            self.switch_target(surface_id, x, y)
            return True

        if not self.devices:
            self.refresh_devices()
        if not any(role == "pointer" for _device, role in self.devices):
            self.close_devices()
            self.write_states()
            log("entry refused: no pointer device available")
            return False

        device_lost = self.grab_devices()
        if not self.capture_ready() and device_lost:
            self.ungrab_devices()
            self.refresh_devices()
            self.grab_devices()
        if not self.capture_ready():
            self.ungrab_devices()
            self.write_states()
            log("entry refused: input devices could not be grabbed")
            return False

        self.active = True
        self.current_surface_id = surface_id
        self.set_position(x, y)
        self.set_active_cursor(surface_id)
        self.write_states()
        log(f"entered {surface_id} at {self.x},{self.y}")
        return True

    def set_position(self, x: float, y: float) -> None:
        surface = self.current_surface
        self.fx = clamp(float(x), 0, surface.pixel_width - 1)
        self.fy = clamp(float(y), 0, surface.pixel_height - 1)
        self.warp_current()

    def warp_current(self) -> None:
        surface = self.current_surface
        self.x = round(clamp(self.fx, 0, surface.pixel_width - 1))
        self.y = round(clamp(self.fy, 0, surface.pixel_height - 1))
        self.roots[surface.id].warp_pointer(self.x, self.y)
        self.display.sync()

    def switch_target(self, surface_id: str, x: int, y: int) -> None:
        if self.locked:
            raise RuntimeError("cannot switch Surface while session is locked")
        if not self.active:
            raise RuntimeError("cannot switch an inactive input router")
        destination = self.layout.surface(surface_id)
        if destination.backend != "x11" or destination.display != ":2":
            raise ValueError(f"cannot switch capture to {surface_id}")
        source_id = self.current_surface_id
        self.current_surface_id = surface_id
        self.set_position(x, y)
        self.set_active_cursor(surface_id)
        self.write_states()
        log(f"switched isolated Surface {source_id} -> {surface_id} at {self.x},{self.y}")

    def move_main_cursor_at(
        self,
        main_x: int,
        main_y: int,
        *,
        wait_for_ack: bool,
    ) -> bool:
        samsung = self.layout.surface("samsung")
        main_x = round(clamp(main_x, 0, samsung.pixel_width - 1))
        main_y = round(clamp(main_y, 0, samsung.pixel_height - 1))
        token = time.time_ns()
        try:
            fd = os.open(MAIN_CURSOR_FIFO, os.O_WRONLY | os.O_NONBLOCK)
            try:
                if wait_for_ack:
                    command = f"warp {main_x} {main_y} {token}\n"
                else:
                    command = f"move {main_x} {main_y}\n"
                os.write(fd, command.encode())
            finally:
                os.close(fd)
        except OSError as exc:
            log(f"Samsung cursor restore unavailable: {exc}")
            return False

        if not wait_for_ack:
            return True

        deadline = time.monotonic() + MAIN_CURSOR_ACK_TIMEOUT
        while time.monotonic() < deadline:
            try:
                state = MAIN_CURSOR_STATE.read_text(encoding="utf-8").strip()
            except OSError:
                state = ""
            if state == f"ack {token}":
                return True
            if state == f"failed {token}":
                return False
            time.sleep(0.002)
        return False

    def restore_main_cursor_at(self, main_x: int, main_y: int) -> bool:
        return self.move_main_cursor_at(main_x, main_y, wait_for_ack=True)

    def park_main_cursor(self) -> bool:
        """Clip the inactive Samsung cursor at its unmapped bottom-right edge."""
        samsung = self.layout.surface("samsung")
        return self.move_main_cursor_at(
            samsung.pixel_width - 1,
            samsung.pixel_height - 1,
            wait_for_ack=True,
        )

    def release_injected(self) -> None:
        if self.display is None:
            return
        for button in tuple(self.pressed_buttons):
            try:
                xtest.fake_input(self.display, X.ButtonRelease, button)
            except Exception:
                pass
        self.pressed_buttons.clear()
        for keycode in tuple(self.pressed_keys):
            try:
                xtest.fake_input(self.display, X.KeyRelease, keycode)
            except Exception:
                pass
        self.pressed_keys.clear()
        self.held_modifiers.clear()
        self.consumed_pane_move_keys.clear()
        self.display.sync()

    def exit(self, reason: str, *, main_position: tuple[int, int] | None = None) -> None:
        if not self.active:
            self.set_active_cursor(None)
            self.write_states()
            return
        if main_position is not None:
            self.restore_main_cursor_at(*main_position)
        self.release_injected()
        self.ungrab_devices()
        self.active = False
        self.current_surface_id = None
        self.set_active_cursor(None)
        self.write_states()
        log(f"released isolated input ownership: {reason}")

    def lock(self) -> None:
        """Neutralize side-Surface input before KScreenLocker takes control."""

        already_quarantined = self.locked and not self.active
        self.locked = True
        if not already_quarantined:
            self.release_injected()
            self.ungrab_devices()
        self.active = False
        self.current_surface_id = None
        try:
            self.connect_display()
        except Exception as exc:
            log(f"locked cursor concealment unavailable: {exc}")
        self.set_active_cursor(None)
        self.write_states()
        log("session locked; isolated Surface input disabled")

    def unlock(self) -> None:
        """Permit future edge entry without restoring prior side ownership."""

        self.locked = False
        self.active = False
        self.current_surface_id = None
        self.set_active_cursor(None)
        self.write_states()
        log("session unlocked; isolated Surface input remains released")

    def cross_edge(self, edge: str) -> bool:
        self.reload_layout_if_changed()
        route = self.layout.route(
            self.current_surface_id,
            edge,
            self.fx,
            self.fy,
        )
        if route is None:
            return False
        destination = self.layout.surface(route.destination_id)
        if destination.backend == "x11" and destination.display == ":2":
            self.switch_target(destination.id, route.x, route.y)
            return True
        if destination.id == "samsung":
            self.exit(
                f"{self.current_surface_id} {edge} edge to Samsung",
                main_position=(route.x, route.y),
            )
            return True
        return False

    def return_to_samsung(self) -> None:
        if not self.active:
            self.exit("return while inactive")
            return
        self.reload_layout_if_changed()
        route = self.layout.route(
            self.current_surface_id,
            "top",
            self.fx,
            0,
        )
        if route is not None and route.destination_id == "samsung":
            self.exit("command return to Samsung", main_position=(route.x, route.y))
        else:
            self.exit("command return without mapped Samsung edge")

    def apply_pointer_motion(self, dx: int, dy: int) -> None:
        if not self.active or (dx == 0 and dy == 0):
            return
        self.reload_layout_if_changed()
        scale = self.mouse_scales.get(self.current_surface_id, 1.0)
        self.fx += dx * scale
        self.fy += dy * scale
        surface = self.current_surface

        crossings = (
            ("top", self.fy <= 0 and dy < 0),
            ("bottom", self.fy >= surface.pixel_height - 1 and dy > 0),
            ("right", self.fx >= surface.pixel_width - 1 and dx > 0),
            ("left", self.fx <= 0 and dx < 0),
        )
        for edge, crossed in crossings:
            if crossed and self.cross_edge(edge):
                return

        surface = self.current_surface
        self.fx = clamp(self.fx, 0, surface.pixel_width - 1)
        self.fy = clamp(self.fy, 0, surface.pixel_height - 1)
        self.warp_current()

    def scroll_button(self, button: int) -> None:
        xtest.fake_input(self.display, X.ButtonPress, button)
        xtest.fake_input(self.display, X.ButtonRelease, button)

    def handle_pointer_button(self, event) -> None:
        if event.type != ecodes.EV_KEY or event.code not in BUTTON_MAP:
            return
        button = BUTTON_MAP[event.code]
        if event.value:
            if button in self.pressed_buttons:
                return
            self.pressed_buttons.add(button)
            xtest.fake_input(self.display, X.ButtonPress, button)
        else:
            if button not in self.pressed_buttons:
                return
            self.pressed_buttons.discard(button)
            xtest.fake_input(self.display, X.ButtonRelease, button)
        self.display.sync()

    def handle_keyboard(self, event) -> None:
        if self.locked:
            return
        if event.type != ecodes.EV_KEY or event.value not in (0, 1, 2):
            return

        if event.code in MODIFIER_KEYS:
            if event.value == 0:
                self.held_modifiers.discard(event.code)
            else:
                self.held_modifiers.add(event.code)

        if (
            event.code == ecodes.KEY_TAB
            and event.value == 1
            and self.held_modifiers & ALT_KEYS
        ):
            self.return_to_samsung()
            return

        direction = PANE_MOVE_DIRECTIONS.get(event.code)
        if direction is not None:
            if event.code in self.consumed_pane_move_keys:
                if event.value == 0:
                    self.consumed_pane_move_keys.discard(event.code)
                return
            exact_modifiers = (
                bool(self.held_modifiers & META_KEYS)
                and bool(self.held_modifiers & SHIFT_KEYS)
                and not self.held_modifiers & (CONTROL_KEYS | ALT_KEYS)
            )
            surface_id = self.current_surface_id
            if (
                event.value == 1
                and exact_modifiers
                and self.active
                and surface_id in self.x_surface_ids
            ):
                self.consumed_pane_move_keys.add(event.code)
                try:
                    moved = self.pane_mover(surface_id, direction)
                except Exception as exc:
                    log(f"pane move failed for {surface_id} {direction}: {exc}")
                else:
                    if not moved:
                        log(f"pane move failed for {surface_id} {direction}")
                return

        keysym = keysym_for_evdev(event.code)
        if not keysym:
            return
        keycode = self.display.keysym_to_keycode(keysym)
        if not keycode:
            return
        if event.value == 0:
            self.pressed_keys.discard(keycode)
            xtest.fake_input(self.display, X.KeyRelease, keycode)
        else:
            self.pressed_keys.add(keycode)
            xtest.fake_input(self.display, X.KeyPress, keycode)
        self.display.sync()

    def handle_pointer_events(self, events) -> None:
        dx = 0
        dy = 0
        for event in events:
            if event.type == ecodes.EV_REL:
                if event.code == ecodes.REL_X:
                    dx += event.value
                elif event.code == ecodes.REL_Y:
                    dy += event.value
                elif event.code == ecodes.REL_WHEEL:
                    button = 4 if event.value > 0 else 5
                    for _ in range(abs(event.value)):
                        self.scroll_button(button)
                elif event.code == ecodes.REL_HWHEEL:
                    button = 7 if event.value > 0 else 6
                    for _ in range(abs(event.value)):
                        self.scroll_button(button)
            elif event.type == ecodes.EV_SYN and event.code == ecodes.SYN_REPORT:
                self.apply_pointer_motion(dx, dy)
                dx = 0
                dy = 0
            else:
                self.handle_pointer_button(event)
        self.apply_pointer_motion(dx, dy)

    def handle_device(self, device: InputDevice) -> None:
        if self.locked:
            return
        try:
            events = list(device.read())
        except BlockingIOError:
            return
        except OSError as exc:
            log(f"device read failed {device.path}: {exc}")
            if exc.errno in (errno.EBADF, errno.ENODEV, errno.ENXIO):
                return
            self.return_to_samsung()
            return
        if not self.active:
            return
        if self.device_roles.get(device.fd) == "pointer":
            self.handle_pointer_events(events)
        elif self.active:
            for event in events:
                if not self.active:
                    break
                self.handle_keyboard(event)

    def refresh_capture(self) -> None:
        was_active = self.active
        target = self.current_surface_id
        position = (self.x, self.y)
        if was_active:
            self.release_injected()
            self.ungrab_devices()
            self.active = False
            self.current_surface_id = None
        self.refresh_devices()
        if was_active and target is not None:
            self.enter_target(target, *position, allow_active_switch=False)
        else:
            self.write_states()

    def enter_from_map(self, source_id: str, edge: str, x: int, y: int) -> None:
        self.reload_layout_if_changed()
        route = self.layout.route(source_id, edge, x, y)
        if route is None:
            log(f"no Surface touches {source_id} {edge} at {x},{y}")
            return
        self.enter_target(
            route.destination_id,
            route.x,
            route.y,
            allow_active_switch=False,
        )

    def switch_to_peer(self) -> None:
        if not self.active:
            return
        self.reload_layout_if_changed()
        for edge in EDGES:
            route = self.layout.route(self.current_surface_id, edge, self.fx, self.fy)
            if route is None:
                continue
            destination = self.layout.surface(route.destination_id)
            if destination.backend == "x11" and destination.display == ":2":
                self.switch_target(destination.id, route.x, route.y)
                return

    def handle_command(self, line: str, legacy_surface_id: str) -> None:
        self.reload_layout_if_changed()
        parts = line.strip().split()
        if not parts:
            return
        command = parts[0].lower()
        if command == "lock":
            self.lock()
            return
        if command == "unlock":
            self.unlock()
            return
        if self.locked:
            if command == "status":
                self.write_states()
            else:
                log(f"ignored {command} while session is locked")
            return
        try:
            if command == "enter":
                x = int(parts[1]) if len(parts) > 1 else self.layout.surface(legacy_surface_id).pixel_width // 2
                self.enter_target(legacy_surface_id, x, 12, allow_active_switch=False)
            elif command == "enterxy":
                self.enter_target(
                    legacy_surface_id,
                    int(parts[1]),
                    int(parts[2]),
                    allow_active_switch=True,
                )
            elif command == "enter-map" and len(parts) == 5:
                self.enter_from_map(parts[1], parts[2], int(parts[3]), int(parts[4]))
            elif command == "enter-target" and len(parts) == 4:
                self.enter_target(parts[1], int(parts[2]), int(parts[3]), allow_active_switch=True)
            elif command == "switchxy" and len(parts) == 4:
                self.enter_target(parts[1], int(parts[2]), int(parts[3]), allow_active_switch=True)
            elif command == "exit":
                self.return_to_samsung()
            elif command == "exitxy" and len(parts) == 3:
                self.exit("explicit Samsung return", main_position=(int(parts[1]), int(parts[2])))
            elif command == "toggle":
                if self.active:
                    self.return_to_samsung()
                else:
                    x = int(parts[1]) if len(parts) > 1 else self.layout.surface(legacy_surface_id).pixel_width // 2
                    self.enter_target(legacy_surface_id, x, 12, allow_active_switch=False)
            elif command == "refresh":
                self.refresh_capture()
            elif command == "handoff":
                self.switch_to_peer()
            elif command == "status":
                self.write_states()
            else:
                log(f"ignored malformed or unknown command: {line.strip()}")
        except (IndexError, ValueError) as exc:
            log(f"ignored malformed command {line.strip()!r}: {exc}")

    def run(self, fifo_fds: dict[int, LegacyEndpoint]) -> None:
        for fifo_fd, endpoint in fifo_fds.items():
            self.selector.register(fifo_fd, selectors.EVENT_READ, ("fifo", endpoint))
        self.write_states()
        if self.locked:
            self.lock()
        log("Surface input router ready; one evdev owner, X display :2, two legacy FIFOs")
        while not self.stop:
            for key, _mask in self.selector.select(timeout=1.0):
                if isinstance(key.data, tuple) and key.data[0] == "fifo":
                    endpoint = key.data[1]
                    try:
                        data = os.read(key.fd, 4096).decode("utf-8", errors="replace")
                    except BlockingIOError:
                        continue
                    for line in data.splitlines():
                        self.handle_command(line, endpoint.surface_id)
                else:
                    self.handle_device(key.data)
        self.exit("shutdown")
        self.close_devices()
        self.close_cursor_controller()


def make_fifo(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.exists() and not stat.S_ISFIFO(path.stat().st_mode):
            path.unlink()
        if not path.exists():
            os.mkfifo(path, 0o600)
    except FileNotFoundError:
        os.mkfifo(path, 0o600)
    os.chown(path, USER_UID, USER_GID)
    os.chmod(path, 0o600)
    return os.open(path, os.O_RDWR | os.O_NONBLOCK)


def main() -> int:
    if os.geteuid() != 0:
        print("Surface input router must run as root to grab evdev devices", file=sys.stderr)
        return 1
    layout = SurfaceLayout.from_file(LAYOUT_PATH)
    endpoints = legacy_endpoints()
    fifo_fds = {make_fifo(endpoint.fifo): endpoint for endpoint in endpoints}
    try:
        locked = LOCK_STATE_PATH.read_text(encoding="utf-8").strip() != "0"
    except OSError:
        locked = True
    router = SurfaceInputRouter(
        layout,
        endpoints=endpoints,
        layout_path=LAYOUT_PATH,
        locked=locked,
    )

    def stop(_signum, _frame) -> None:
        router.stop = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        router.run(fifo_fds)
    finally:
        for fifo_fd in fifo_fds:
            try:
                os.close(fifo_fd)
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
