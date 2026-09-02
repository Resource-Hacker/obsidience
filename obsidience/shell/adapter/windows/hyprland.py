"""Event-driven Hyprland window observation and exact-address activation."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

from .model import ApplicationWindow

_ADDRESS = re.compile(r"^0x[0-9a-fA-F]+$")
_RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000"))
_FULLSCREEN_STATE = _RUNTIME_DIR / "obsidience-shell-fullscreen.state"
_SURFACE_BY_OUTPUT = {
    "HDMI-A-1": "samsung",
    "DP-8": "usb-c",
    "HDMI-A-2": "dp-4",
}


class HyprlandSurfaceWindows:
    def __init__(
        self,
        on_change: Callable[[str, str, tuple[ApplicationWindow, ...]], None],
    ) -> None:
        self.on_change = on_change
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run,
            name="obsidience-windows-samsung",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def activate(self, window_id: str) -> tuple[bool, str]:
        if _ADDRESS.fullmatch(window_id) is None:
            return False, "invalid_window_id"
        result = self._command("dispatch", "focuswindow", f"address:{window_id}")
        if result.returncode != 0:
            return False, "hyprland_rejected"
        self._publish()
        return True, ""

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._publish()
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as event_socket:
                    event_socket.settimeout(0.5)
                    event_socket.connect(str(self._event_socket()))
                    pending = b""
                    while not self._stop.is_set():
                        try:
                            chunk = event_socket.recv(4096)
                        except TimeoutError:
                            continue
                        if not chunk:
                            break
                        pending += chunk
                        lines = pending.split(b"\n")
                        pending = lines.pop()
                        if lines:
                            self._publish()
            except (OSError, RuntimeError, ValueError, json.JSONDecodeError):
                self._stop.wait(0.5)

    def _publish(self) -> None:
        monitors = self._json("monitors", "all")
        clients = self._json("clients")
        active = self._json("activewindow")
        monitor_surfaces: dict[int, str] = {}
        if isinstance(monitors, list):
            for monitor in monitors:
                if not isinstance(monitor, dict):
                    continue
                monitor_id = monitor.get("id")
                surface_id = _SURFACE_BY_OUTPUT.get(str(monitor.get("name", "")))
                if (
                    isinstance(monitor_id, int)
                    and not isinstance(monitor_id, bool)
                    and surface_id is not None
                ):
                    monitor_surfaces[monitor_id] = surface_id

        windows_by_surface: dict[str, list[ApplicationWindow]] = {
            surface_id: [] for surface_id in _SURFACE_BY_OUTPUT.values()
        }
        if isinstance(clients, list):
            for client in clients[:256]:
                if not isinstance(client, dict) or client.get("mapped") is False:
                    continue
                surface_id = monitor_surfaces.get(client.get("monitor"))
                if surface_id is None:
                    continue
                address = str(client.get("address", ""))
                app_id = str(client.get("class") or client.get("initialClass") or "")
                if _ADDRESS.fullmatch(address) is None or not app_id:
                    continue
                pid = client.get("pid", 0)
                windows_by_surface[surface_id].append(
                    ApplicationWindow(
                        window_id=address,
                        app_id=app_id,
                        title=str(client.get("title") or app_id),
                        pid=pid if isinstance(pid, int) and not isinstance(pid, bool) else 0,
                        minimized=client.get("hidden") is True,
                    )
                )
        active_id = ""
        active_surface = ""
        if isinstance(active, dict):
            candidate = str(active.get("address", ""))
            if _ADDRESS.fullmatch(candidate):
                active_id = candidate
                active_surface = monitor_surfaces.get(active.get("monitor"), "")
        fullscreen = bool(
            active_surface == "samsung"
            and active_id
            and isinstance(active, dict)
            and int(active.get("fullscreen", 0) or 0) > 0
        )
        _FULLSCREEN_STATE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _FULLSCREEN_STATE.write_text("1\n" if fullscreen else "0\n", encoding="utf-8")
        for surface_id, windows in windows_by_surface.items():
            self.on_change(
                surface_id,
                active_id if surface_id == active_surface else "",
                tuple(windows),
            )

    def _json(self, *arguments: str) -> object:
        result = self._command(*arguments, "-j")
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip()[:256])
        return json.loads(result.stdout)

    @staticmethod
    def _command(*arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["/usr/bin/hyprctl", *arguments],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )

    @staticmethod
    def _event_socket() -> Path:
        signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
        runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000"))
        path = runtime / "hypr" / signature / ".socket2.sock"
        if not signature or not path.is_socket():
            raise RuntimeError("Hyprland event socket unavailable")
        return path
