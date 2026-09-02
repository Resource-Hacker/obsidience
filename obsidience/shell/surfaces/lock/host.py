#!/usr/bin/env python3
"""X11 graph desktop and input-empty lock cover for one Obsidience Surface."""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("GDK_BACKEND", "x11")

import cairo
import gi

gi.require_version("Gdk", "3.0")
gi.require_version("Gio", "2.0")
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")

from gi.repository import Gdk, Gio, GLib, Gtk, WebKit2


RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
LOCK_STATE_PATH = Path(
    os.environ.get(
        "OBSIDIENCE_LOCK_STATE",
        str(RUNTIME_DIR / "obsidience-shell" / "lock-state"),
    )
)
LAYOUT_PATH = Path(
    os.environ.get(
        "OBSIDIENCE_SURFACE_LAYOUT",
        str(Path.home() / ".config" / "obsidience-shell" / "surface-layout.json"),
    )
)
SURFACE_ID = os.environ.get("OBSIDIENCE_SURFACE_ID", "")
KNOWLEDGE_URL = os.environ.get(
    "OBSIDIENCE_KNOWLEDGE_URL",
    "http://127.0.0.1:8765/shell/knowledge/?surface=knowledge",
)
SURFACE_IDS = {"samsung", "usb-c", "dp-4"}
GRAPH_MODES = {"desktop-graph", "lock-graph"}


def lock_active(path: Path = LOCK_STATE_PATH) -> bool:
    """Fail closed unless Obsidience projects the exact unlocked value."""

    try:
        return path.read_bytes() not in (b"0", b"0\n")
    except OSError:
        return True


def selected_graph_surface(path: Path = LAYOUT_PATH) -> str:
    """Read the one global graph Surface, defaulting safely to Samsung."""

    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return "samsung"
    value = record.get("graph_surface_id") if isinstance(record, dict) else None
    return value if value in SURFACE_IDS else "samsung"


class SideGraphPresenter:
    """Show one side graph when selected and one privacy cover while locked."""

    def __init__(
        self,
        screen: Gdk.Screen,
        surface_id: str = SURFACE_ID,
        lock_path: Path = LOCK_STATE_PATH,
        layout_path: Path = LAYOUT_PATH,
    ) -> None:
        if surface_id not in {"usb-c", "dp-4"}:
            raise RuntimeError("side graph presenter requires usb-c or dp-4")
        self.screen = screen
        self.surface_id = surface_id
        self.lock_path = lock_path
        self.layout_path = layout_path
        self.mode = ""
        self.window: Gtk.Window | None = None
        self.webview: WebKit2.WebView | None = None
        self.retry_source: int | None = None
        self.monitors: list[Gio.FileMonitor] = []

        for path in (lock_path, layout_path):
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            monitor = Gio.File.new_for_path(str(path.parent)).monitor_directory(
                Gio.FileMonitorFlags.NONE, None
            )
            monitor.connect("changed", self._state_changed)
            self.monitors.append(monitor)
        self.refresh()

    def _state_changed(self, *_args: object) -> None:
        self.refresh()

    def desired_mode(self) -> str:
        locked = lock_active(self.lock_path)
        selected = selected_graph_surface(self.layout_path) == self.surface_id
        if locked:
            return "lock-graph" if selected else "lock-solid"
        return "desktop-graph" if selected else "hidden"

    def refresh(self, *, force: bool = False) -> None:
        mode = self.desired_mode()
        if not force and mode == self.mode and (
            mode == "hidden" or self.window is not None
        ):
            return
        self.hide()
        self.mode = mode
        if mode != "hidden":
            self.show(mode)

    def show(self, mode: str) -> None:
        locked = mode.startswith("lock-")
        graph = mode in GRAPH_MODES
        width = self.screen.get_width()
        height = self.screen.get_height()
        window = Gtk.Window(
            type=Gtk.WindowType.POPUP if locked else Gtk.WindowType.TOPLEVEL
        )
        window.set_title(f"Obsidience {self.surface_id} graph")
        window.set_decorated(False)
        window.set_accept_focus(False)
        window.set_focus_on_map(False)
        window.set_skip_pager_hint(True)
        window.set_skip_taskbar_hint(True)
        window.set_default_size(width, height)
        window.move(0, 0)
        window.resize(width, height)
        window.override_background_color(
            Gtk.StateFlags.NORMAL, Gdk.RGBA(0.0078, 0.0235, 0.0471, 1.0)
        )
        if locked:
            window.set_keep_above(True)
        else:
            window.set_keep_below(True)
            window.set_type_hint(Gdk.WindowTypeHint.DESKTOP)

        if graph:
            webview = WebKit2.WebView()
            settings = webview.get_settings()
            settings.set_enable_webgl(True)
            settings.set_hardware_acceleration_policy(
                WebKit2.HardwareAccelerationPolicy.ALWAYS
            )
            webview.set_background_color(Gdk.RGBA(0.0078, 0.0235, 0.0471, 1.0))
            webview.connect("load-failed", self._load_failed)
            webview.connect("load-changed", self._load_changed)
            webview.connect("web-process-terminated", self._web_process_terminated)
            window.add(webview)
            self.webview = webview

        self.window = window
        window.show_all()
        if locked:
            window.get_window().input_shape_combine_region(cairo.Region(), 0, 0)
        if self.webview is not None:
            self.webview.load_uri(
                KNOWLEDGE_URL + ("&lock=1" if locked else "")
            )
        print(
            f"obsidience {self.surface_id} graph: {mode} {width}x{height}",
            flush=True,
        )

    def hide(self) -> None:
        if self.retry_source is not None:
            GLib.source_remove(self.retry_source)
            self.retry_source = None
        if self.window is not None:
            self.window.destroy()
        self.window = None
        self.webview = None

    def _schedule_retry(self) -> None:
        if self.retry_source is None and self.mode in GRAPH_MODES:
            self.retry_source = GLib.timeout_add_seconds(1, self._retry_load)

    def _retry_load(self) -> bool:
        self.retry_source = None
        if self.webview is not None and self.mode in GRAPH_MODES:
            self.webview.load_uri(
                KNOWLEDGE_URL + ("&lock=1" if self.mode == "lock-graph" else "")
            )
        return False

    def _load_failed(self, _view, _event, uri, error) -> bool:
        print(f"obsidience {self.surface_id} graph unavailable at {uri}: {error}", flush=True)
        self._schedule_retry()
        return False

    def _load_changed(self, _view, event) -> None:
        if event == WebKit2.LoadEvent.FINISHED:
            print(f"obsidience {self.surface_id} graph: ready", flush=True)

    def _web_process_terminated(self, _view, reason) -> None:
        print(f"obsidience {self.surface_id} WebKit terminated: {reason}", flush=True)
        self._schedule_retry()


def main() -> int:
    screen = Gdk.Screen.get_default()
    if screen is None:
        raise RuntimeError("side graph presenter requires one X11 screen")
    presenter = SideGraphPresenter(screen)
    Gtk.main()
    del presenter
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
