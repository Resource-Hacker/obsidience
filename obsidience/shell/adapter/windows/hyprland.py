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
_OUTPUT = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000"))
_FULLSCREEN_STATE = _RUNTIME_DIR / "obsidience-shell-fullscreen.state"
_SURFACE_BY_OUTPUT = {
    "HDMI-A-1": "samsung",
    "DP-8": "usb-c",
    "HDMI-A-2": "dp-4",
}
_OUTPUT_BY_SURFACE = {surface: output for output, surface in _SURFACE_BY_OUTPUT.items()}
_ACTIONS = frozenset(("resize", "tile", "surface"))
_DIRECTIONS = frozenset(("left", "right", "top", "bottom"))


def _number(value: object) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _monitor_route(
    monitors: object,
    active: object,
    source_surface: str,
    direction: str,
) -> tuple[str, str, str, float] | None:
    """Return destination Surface, output, entry edge, and axis ratio."""

    if not isinstance(monitors, list) or not isinstance(active, dict):
        return None
    active_monitor = active.get("monitor")
    at = active.get("at")
    size = active.get("size")
    if (
        isinstance(active_monitor, bool)
        or not isinstance(active_monitor, int)
        or not isinstance(at, list)
        or len(at) != 2
        or not isinstance(size, list)
        or len(size) != 2
    ):
        return None
    rectangles: dict[int, tuple[str, str, float, float, float, float]] = {}
    for monitor in monitors:
        if not isinstance(monitor, dict):
            continue
        monitor_id = monitor.get("id")
        output = str(monitor.get("name", ""))
        surface = _SURFACE_BY_OUTPUT.get(output)
        x = _number(monitor.get("x"))
        y = _number(monitor.get("y"))
        width = _number(monitor.get("width"))
        height = _number(monitor.get("height"))
        scale = _number(monitor.get("scale"))
        if (
            isinstance(monitor_id, bool)
            or not isinstance(monitor_id, int)
            or surface is None
            or x is None
            or y is None
            or width is None
            or height is None
            or scale is None
            or scale <= 0
        ):
            continue
        rectangles[monitor_id] = (
            surface,
            output,
            x,
            y,
            width / scale,
            height / scale,
        )
    source = rectangles.get(active_monitor)
    if source is None or source[0] != source_surface:
        return None
    at_x, at_y = _number(at[0]), _number(at[1])
    size_x, size_y = _number(size[0]), _number(size[1])
    if None in (at_x, at_y, size_x, size_y):
        return None
    source_x, source_y, source_w, source_h = source[2:]
    horizontal = direction in ("top", "bottom")
    axis = at_x + size_x / 2 if horizontal else at_y + size_y / 2
    boundary = (
        source_x
        if direction == "left"
        else source_x + source_w
        if direction == "right"
        else source_y
        if direction == "top"
        else source_y + source_h
    )
    entry_edge = {
        "left": "right",
        "right": "left",
        "top": "bottom",
        "bottom": "top",
    }[direction]
    best: tuple[float, str, str, str, float] | None = None
    for monitor_id, target in rectangles.items():
        if monitor_id == active_monitor:
            continue
        target_surface, output, x, y, width, height = target
        target_boundary = (
            x + width
            if entry_edge == "right"
            else x
            if entry_edge == "left"
            else y + height
            if entry_edge == "bottom"
            else y
        )
        if abs(boundary - target_boundary) >= 0.5:
            continue
        source_start = source_x if horizontal else source_y
        source_extent = source_w if horizontal else source_h
        target_start = x if horizontal else y
        target_extent = width if horizontal else height
        overlap_start = max(source_start, target_start)
        overlap_end = min(source_start + source_extent, target_start + target_extent)
        if overlap_end <= overlap_start:
            continue
        mapped = max(overlap_start, min(axis, overlap_end - 0.001))
        distance = abs(axis - mapped)
        ratio = max(0.0, min(1.0, (mapped - target_start) / target_extent))
        candidate = (distance, target_surface, output, entry_edge, ratio)
        if best is None or candidate < best:
            best = candidate
    return best[1:] if best else None


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
        result = self._dispatch(f'hl.dsp.focus({{ window = "address:{window_id}" }})')
        if not self._accepted(result):
            return False, "hyprland_rejected"
        self._publish()
        return True, ""

    def close(self, window_id: str) -> tuple[bool, str]:
        if _ADDRESS.fullmatch(window_id) is None:
            return False, "invalid_window_id"
        active = self._json("activewindow")
        if not isinstance(active, dict) or active.get("address") != window_id:
            return False, "focus_changed"
        result = self._dispatch(
            f'hl.dsp.window.close({{ window = "address:{window_id}" }})'
        )
        if not self._accepted(result):
            return False, "hyprland_rejected"
        self._publish()
        return True, ""

    def configure_grid(
        self, surface_id: str, columns: int, rows: int
    ) -> tuple[bool, str]:
        if (
            surface_id not in _OUTPUT_BY_SURFACE
            or isinstance(columns, bool)
            or not isinstance(columns, int)
            or isinstance(rows, bool)
            or not isinstance(rows, int)
            or not 1 <= columns <= 16
            or not 1 <= rows <= 16
        ):
            return False, "invalid_grid"
        result = self._layout_message(f"grid {surface_id} {columns} {rows}")
        if not self._accepted(result):
            return False, "layout_rejected"
        return True, ""

    def layout(
        self,
        surface_id: str,
        window_id: str,
        action: str,
        direction: str,
        grids: dict[str, tuple[int, int]],
    ) -> tuple[bool, str]:
        if (
            surface_id not in _OUTPUT_BY_SURFACE
            or _ADDRESS.fullmatch(window_id) is None
            or action not in _ACTIONS
            or direction not in _DIRECTIONS
            or surface_id not in grids
        ):
            return False, "invalid_layout_command"
        monitors = self._json("monitors", "all")
        active = self._json("activewindow")
        if not isinstance(active, dict) or active.get("address") != window_id:
            return False, "focus_changed"
        if action != "surface":
            columns, rows = grids[surface_id]
            operation = "resize" if action == "resize" else "translate"
            result = self._layout_message(
                f"{operation} {direction} {surface_id} {columns} {rows}"
            )
            if not self._accepted(result):
                return False, "layout_rejected"
            self._publish()
            return True, ""

        route = _monitor_route(monitors, active, surface_id, direction)
        if route is None:
            return False, "surface_boundary"
        destination_surface, output, edge, ratio = route
        if destination_surface not in grids or _OUTPUT.fullmatch(output) is None:
            return False, "invalid_destination"
        columns, rows = grids[destination_surface]
        prepared = self._layout_message(
            f"transfer {destination_surface} {columns} {rows} {edge} {ratio:.6f}"
        )
        if not self._accepted(prepared):
            return False, "layout_rejected"
        moved = self._dispatch(
            "hl.dsp.window.move({ "
            f'monitor = "{output}", follow = true, '
            f'window = "address:{window_id}" }}'
            ")"
        )
        if not self._accepted(moved):
            self._layout_message("cancel")
            return False, "move_rejected"
        current = self._json("activewindow")
        destination_ids = {
            monitor.get("id")
            for monitor in monitors
            if isinstance(monitor, dict) and monitor.get("name") == output
        }
        if (
            not isinstance(current, dict)
            or current.get("address") != window_id
            or current.get("monitor") not in destination_ids
        ):
            return False, "move_not_observed"
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
                        pid=pid
                        if isinstance(pid, int) and not isinstance(pid, bool)
                        else 0,
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

    def _dispatch(self, expression: str) -> subprocess.CompletedProcess[str]:
        return self._command("eval", f"hl.dispatch({expression})")

    def _layout_message(self, message: str) -> subprocess.CompletedProcess[str]:
        return self._dispatch(f'hl.dsp.layout("{message}")')

    @staticmethod
    def _accepted(result: subprocess.CompletedProcess[str]) -> bool:
        return result.returncode == 0 and result.stdout.strip().startswith("ok")

    @staticmethod
    def _event_socket() -> Path:
        signature = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE", "")
        runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/1000"))
        path = runtime / "hypr" / signature / ".socket2.sock"
        if not signature or not path.is_socket():
            raise RuntimeError("Hyprland event socket unavailable")
        return path
