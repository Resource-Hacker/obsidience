#!/usr/bin/env python3
"""Small D-Bus boundary between KWin and the Surface input router."""

from __future__ import annotations

import errno
import os
import subprocess
import time
from pathlib import Path

import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib


BUS_NAME = "org.wissenschafter.DP4Bridge"
OBJECT_PATH = "/org/wissenschafter/DP4Bridge"
IFACE = "org.wissenschafter.DP4Bridge"
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
DP4_FIFO = RUNTIME_DIR / "dp4-edge-bridge.cmd"
USB_FIFO = RUNTIME_DIR / "usb-monitor-edge-bridge.cmd"
DP4_STATE = RUNTIME_DIR / "dp4-edge-bridge.state"
USB_STATE = RUNTIME_DIR / "usb-monitor-edge-bridge.state"
CURSOR_STATE = RUNTIME_DIR / "edge-main-cursor-observed.state"
ADAPTER_READY_STATE = RUNTIME_DIR / "obsidience-surface-edge-adapter.ready"
FULLSCREEN_STATE = RUNTIME_DIR / "obsidience-shell-fullscreen.state"
LOCK_STATE_DIR = RUNTIME_DIR / "obsidience-shell"
LOCK_STATE = LOCK_STATE_DIR / "lock-state"
ROUTER_SERVICE = "dp4-edge-bridge.service"
PANE_MOVE_PYTHON = Path(
    "/home/wissenschafter/Projects/obsidience/.venv/bin/python"
)
PANE_MOVE_CLIENT = Path(
    "/home/wissenschafter/Projects/obsidience/obsidience/shell/input/move_pane.py"
)
EDGES = frozenset(("left", "right", "top", "bottom"))
SURFACES = frozenset(("samsung", "usb-c", "dp-4"))
SCREENSAVER_BUS = "org.freedesktop.ScreenSaver"
SCREENSAVER_PATH = "/ScreenSaver"
SCREENSAVER_IFACE = "org.freedesktop.ScreenSaver"
KDE_SCREENSAVER_IFACE = "org.kde.screensaver"


def write_lock_state(locked: bool) -> None:
    """Atomically project KScreenLocker's state for every Surface host."""

    LOCK_STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(LOCK_STATE_DIR, 0o700)
    temporary = LOCK_STATE.with_name(f".{LOCK_STATE.name}.{os.getpid()}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    try:
        os.write(descriptor, b"1\n" if locked else b"0\n")
    finally:
        os.close(descriptor)
    os.replace(temporary, LOCK_STATE)
    os.chmod(LOCK_STATE, 0o600)


def lock_active() -> bool:
    """Fail closed until the KScreenLocker projection is available."""

    try:
        return LOCK_STATE.read_text(encoding="utf-8").strip() != "0"
    except OSError:
        return True


def start_router(fifo: Path) -> None:
    subprocess.run(
        ["systemctl", "--user", "start", ROUTER_SERVICE],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    for _ in range(40):
        if fifo.exists():
            return
        time.sleep(0.025)


class SurfaceBridge(dbus.service.Object):
    def _send(self, fifo: Path, command: str) -> bool:
        payload = (command.rstrip() + "\n").encode("utf-8")
        for attempt in range(2):
            try:
                fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
                try:
                    os.write(fd, payload)
                finally:
                    os.close(fd)
                return True
            except OSError as exc:
                if attempt == 0 and exc.errno in (errno.ENOENT, errno.ENXIO, errno.EPIPE):
                    start_router(fifo)
                    continue
                return False
        return False

    @staticmethod
    def _integer(value: object, default: int = 0) -> int:
        try:
            return int(str(value).strip())
        except ValueError:
            return default

    @dbus.service.method(IFACE, in_signature="s", out_signature="b")
    def Enter(self, x: str) -> bool:
        if lock_active():
            return False
        return self._send(DP4_FIFO, f"enter {self._integer(x)}")

    @dbus.service.method(IFACE, in_signature="s", out_signature="b")
    def EnterUsb(self, x: str) -> bool:
        if lock_active():
            return False
        return self._send(USB_FIFO, f"enter {self._integer(x)}")

    @dbus.service.method(IFACE, in_signature="sss", out_signature="b")
    def EnterMapped(self, edge: str, x: str, y: str) -> bool:
        if lock_active():
            return False
        normalized_edge = str(edge).strip().lower()
        if normalized_edge not in EDGES:
            return False
        return self._send(
            DP4_FIFO,
            f"enter-map samsung {normalized_edge} {self._integer(x)} {self._integer(y)}",
        )

    @dbus.service.method(IFACE, in_signature="", out_signature="b")
    def Exit(self) -> bool:
        return self._send(DP4_FIFO, "exit")

    @dbus.service.method(IFACE, in_signature="", out_signature="b")
    def Refresh(self) -> bool:
        return self._send(DP4_FIFO, "refresh")

    @dbus.service.method(IFACE, in_signature="", out_signature="s")
    def State(self) -> str:
        if lock_active():
            return "locked"
        for state_path in (DP4_STATE, USB_STATE):
            try:
                state = state_path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if state.startswith("active"):
                return state
        return "inactive"

    @dbus.service.method(IFACE, in_signature="ss", out_signature="b")
    def ReportCursor(self, x: str, y: str) -> bool:
        try:
            CURSOR_STATE.write_text(f"{x} {y}\n", encoding="utf-8")
            return True
        except OSError:
            return False

    @dbus.service.method(IFACE, in_signature="s", out_signature="b")
    def AdapterReady(self, token: str) -> bool:
        if str(token) != "ready":
            return False
        try:
            ADAPTER_READY_STATE.write_text("ready\n", encoding="utf-8")
            return True
        except OSError:
            return False

    @dbus.service.method(IFACE, in_signature="s", out_signature="b")
    def ReportFullscreen(self, state: str) -> bool:
        value = str(state).strip()
        if value not in ("0", "1"):
            return False
        try:
            FULLSCREEN_STATE.write_text(value + "\n", encoding="utf-8")
            return True
        except OSError:
            return False

    @dbus.service.method(IFACE, in_signature="ss", out_signature="b")
    def MovePane(self, surface_id: str, direction: str) -> bool:
        if lock_active():
            return False
        surface = str(surface_id).strip().lower()
        edge = str(direction).strip().lower()
        if surface not in SURFACES or edge not in EDGES:
            return False
        try:
            result = subprocess.run(
                [str(PANE_MOVE_PYTHON), str(PANE_MOVE_CLIENT), surface, edge],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=1.5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0


class LockStateProjection:
    """Translate KScreenLocker signals into one shell state and router gate."""

    def __init__(self, bus, bridge: SurfaceBridge) -> None:
        self.bridge = bridge
        bus.add_signal_receiver(
            self._about_to_lock,
            signal_name="AboutToLock",
            dbus_interface=KDE_SCREENSAVER_IFACE,
            bus_name=SCREENSAVER_BUS,
            path=SCREENSAVER_PATH,
        )
        bus.add_signal_receiver(
            self._active_changed,
            signal_name="ActiveChanged",
            dbus_interface=SCREENSAVER_IFACE,
            bus_name=SCREENSAVER_BUS,
            path=SCREENSAVER_PATH,
        )

        # Seed before the router starts. A missing authority is treated as locked.
        try:
            proxy = bus.get_object(SCREENSAVER_BUS, SCREENSAVER_PATH)
            screen_saver = dbus.Interface(proxy, dbus_interface=SCREENSAVER_IFACE)
            active = bool(screen_saver.GetActive())
        except Exception:
            active = True
        write_lock_state(active)

    def _route(self, locked: bool) -> None:
        write_lock_state(locked)
        command = "lock" if locked else "unlock"
        # Both compatibility FIFOs feed the same one-owner router. One command
        # is the lock transition; duplicating it per Surface adds no authority.
        self.bridge._send(DP4_FIFO, command)

    def _about_to_lock(self) -> None:
        self._route(True)

    def _active_changed(self, active) -> None:
        self._route(bool(active))


def main() -> None:
    FULLSCREEN_STATE.write_text("0\n", encoding="utf-8")
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus()
    bus_name = dbus.service.BusName(BUS_NAME, bus=bus)
    bridge = SurfaceBridge(bus_name, OBJECT_PATH)
    LockStateProjection(bus, bridge)
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
