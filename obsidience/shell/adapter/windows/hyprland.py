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
_STATE_NAMESPACE = os.environ.get("OBSIDIENCE_SHELL_STATE_NAMESPACE", "")
_FULLSCREEN_STATE = (
    _RUNTIME_DIR / _STATE_NAMESPACE / "fullscreen-state"
    if _STATE_NAMESPACE
    else _RUNTIME_DIR / "obsidience-shell-fullscreen.state"
)


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
        clients = self._json("clients")
        active = self._json("activewindow")
        windows: list[ApplicationWindow] = []
        if isinstance(clients, list):
            for client in clients[:256]:
                if not isinstance(client, dict) or client.get("mapped") is False:
                    continue
                address = str(client.get("address", ""))
                app_id = str(client.get("class") or client.get("initialClass") or "")
                if _ADDRESS.fullmatch(address) is None or not app_id:
                    continue
                pid = client.get("pid", 0)
                windows.append(
                    ApplicationWindow(
                        window_id=address,
                        app_id=app_id,
                        title=str(client.get("title") or app_id),
                        pid=pid if isinstance(pid, int) and not isinstance(pid, bool) else 0,
                        minimized=client.get("hidden") is True,
                    )
                )
        active_id = ""
        if isinstance(active, dict):
            candidate = str(active.get("address", ""))
            if _ADDRESS.fullmatch(candidate):
                active_id = candidate
        fullscreen = bool(active_id and int(active.get("fullscreen", 0) or 0) > 0)
        _FULLSCREEN_STATE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _FULLSCREEN_STATE.write_text("1\n" if fullscreen else "0\n", encoding="utf-8")
        self.on_change("samsung", active_id, tuple(windows))

    def _json(self, name: str) -> object:
        result = self._command(name, "-j")
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
