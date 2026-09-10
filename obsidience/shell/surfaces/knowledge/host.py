"""Hardware-accelerated WebKit host for the canonical Three.js desktop graph."""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("GDK_BACKEND", "wayland")
os.environ.setdefault("WEBKIT_DMABUF_RENDERER_FORCE_SHM", "1")

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("WebKit2", "4.1")

from gi.repository import Gdk, Gio, GLib, Gtk, GtkLayerShell, WebKit2


KNOWLEDGE_ORIGIN = os.environ.get(
    "OBSIDIENCE_KNOWLEDGE_ORIGIN",
    "http://127.0.0.1:8765/shell/knowledge/",
)
LAYOUT_PATH = Path(
    os.environ.get(
        "OBSIDIENCE_SURFACE_LAYOUT",
        str(Path.home() / ".config/obsidience-shell/surface-layout.json"),
    )
)
SURFACE_SIZES = {
    "samsung": (5120, 1440),
    "usb-c": (1920, 1200),
    "dp-4": (1920, 550),
}


def _fail(message: str) -> None:
    print(f"obsidience knowledge desktop: {message}", flush=True)
    GLib.idle_add(lambda: os._exit(1))


class KnowledgeDesktop:
    """Keep one graph layer bound to the selected Obsidience Surface."""

    def __init__(self, display: Gdk.Display) -> None:
        self.display = display
        self.monitor: Gdk.Monitor | None = None
        self.surface_id = ""
        self.watched_monitors: list[Gdk.Monitor] = []
        self.window: Gtk.Window | None = None
        self.webview: WebKit2.WebView | None = None
        display.connect("monitor-added", self._monitor_changed)
        display.connect("monitor-removed", self._monitor_changed)
        self.layout_monitor = Gio.File.new_for_path(
            str(LAYOUT_PATH.parent)
        ).monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self.layout_monitor.connect("changed", self._layout_changed)
        self._watch_current_monitors()
        self.refresh()

    def _watch_monitor(self, monitor: Gdk.Monitor) -> None:
        if monitor in self.watched_monitors:
            return
        monitor.connect("notify::geometry", self._monitor_changed)
        self.watched_monitors.append(monitor)

    def _watch_current_monitors(self) -> None:
        for index in range(self.display.get_n_monitors()):
            self._watch_monitor(self.display.get_monitor(index))

    @staticmethod
    def _selected_surface_id() -> str:
        try:
            record = json.loads(LAYOUT_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return "samsung"
        candidate = record.get("graph_surface_id") if isinstance(record, dict) else None
        return candidate if candidate in SURFACE_SIZES else "samsung"

    def _target_monitor(self, surface_id: str) -> Gdk.Monitor | None:
        expected_size = SURFACE_SIZES[surface_id]
        for index in range(self.display.get_n_monitors()):
            monitor = self.display.get_monitor(index)
            geometry = monitor.get_geometry()
            if (geometry.width, geometry.height) == expected_size:
                return monitor
        return None

    def _monitor_changed(self, *_args: object) -> None:
        self._watch_current_monitors()
        GLib.idle_add(self.refresh)

    def _layout_changed(self, *_args: object) -> None:
        GLib.idle_add(self.refresh)

    def refresh(self) -> bool:
        surface_id = self._selected_surface_id()
        monitor = self._target_monitor(surface_id)
        if monitor is None:
            if self.monitor is not None:
                print(
                    f"obsidience knowledge desktop: {surface_id} unavailable",
                    flush=True,
                )
                self.monitor = None
                if self.window is not None:
                    self.window.hide()
            return False
        if (
            self.window is not None
            and monitor == self.monitor
            and surface_id == self.surface_id
        ):
            return False

        self.monitor = monitor
        previous_surface_id = self.surface_id
        self.surface_id = surface_id
        geometry = monitor.get_geometry()

        if self.window is not None:
            GtkLayerShell.set_monitor(self.window, monitor)
            # Rebind a returning monitor without discarding its resident page.
            # Navigation is needed only when the logical Surface changes.
            if self.webview is not None and previous_surface_id != surface_id:
                self.webview.load_request(self._knowledge_request(surface_id))
            self.window.show_all()
            print(
                "obsidience knowledge desktop: "
                f"restored {surface_id} {geometry.width}x{geometry.height}",
                flush=True,
            )
            return False

        window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        window.set_title("Obsidience Knowledge Desktop")
        window.set_decorated(False)
        window.set_accept_focus(True)

        GtkLayerShell.init_for_window(window)
        GtkLayerShell.set_namespace(window, "obsidience-knowledge-desktop")
        GtkLayerShell.set_monitor(window, monitor)
        GtkLayerShell.set_layer(window, GtkLayerShell.Layer.BACKGROUND)
        GtkLayerShell.set_exclusive_zone(window, 0)
        # Native on-demand focus lets the trace disclosures receive Tab/Enter
        # only after user interaction; the background never reserves keyboard focus.
        GtkLayerShell.set_keyboard_mode(window, GtkLayerShell.KeyboardMode.ON_DEMAND)
        for edge in (
            GtkLayerShell.Edge.TOP,
            GtkLayerShell.Edge.RIGHT,
            GtkLayerShell.Edge.BOTTOM,
            GtkLayerShell.Edge.LEFT,
        ):
            GtkLayerShell.set_anchor(window, edge, True)

        webview = WebKit2.WebView()
        settings = webview.get_settings()
        settings.set_enable_webgl(True)
        settings.set_hardware_acceleration_policy(
            WebKit2.HardwareAccelerationPolicy.ALWAYS
        )
        webview.set_background_color(Gdk.RGBA(0.0078, 0.0235, 0.0471, 1.0))
        webview.connect(
            "load-failed",
            lambda _view, _event, uri, error: _fail(
                f"load failed for {uri}: {error}"
            )
            or False,
        )
        webview.connect(
            "web-process-terminated",
            lambda _view, reason: _fail(f"WebKit process terminated: {reason}"),
        )
        webview.connect(
            "load-changed",
            lambda _view, event: print(
                "obsidience knowledge desktop: "
                f"ready {surface_id} {geometry.width}x{geometry.height}",
                flush=True,
            )
            if event == WebKit2.LoadEvent.FINISHED
            else None,
        )

        window.add(webview)
        webview.load_request(self._knowledge_request(surface_id))
        self.window = window
        self.webview = webview
        window.show_all()
        return False

    @staticmethod
    def _knowledge_url(surface_id: str) -> str:
        return (
            f"{KNOWLEDGE_ORIGIN}?surface=knowledge"
            f"&surface_id={surface_id}"
        )

    @staticmethod
    def _knowledge_request(surface_id: str) -> WebKit2.URIRequest:
        request = WebKit2.URIRequest.new(
            KnowledgeDesktop._knowledge_url(surface_id)
        )
        # Revalidate the mutable entrypoint, including copies cached before the
        # server advertised no-cache. Keep persistent preferences and hashed assets.
        request.get_http_headers().replace("Cache-Control", "no-cache")
        return request


def main() -> int:
    display = Gdk.Display.get_default()
    if display is None:
        raise RuntimeError("knowledge desktop requires a Wayland display")
    desktop = KnowledgeDesktop(display)
    Gtk.main()
    del desktop
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
