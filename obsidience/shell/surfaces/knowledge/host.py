"""Hardware-accelerated WebKit host for the canonical Three.js desktop graph."""

from __future__ import annotations

import os

os.environ.setdefault("GDK_BACKEND", "wayland")
os.environ.setdefault("WEBKIT_DMABUF_RENDERER_FORCE_SHM", "1")

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("WebKit2", "4.1")

from gi.repository import Gdk, GLib, Gtk, GtkLayerShell, WebKit2


KNOWLEDGE_URL = os.environ.get(
    "OBSIDIENCE_KNOWLEDGE_URL",
    "http://127.0.0.1:8765/shell/knowledge/?surface=knowledge&surface_id=samsung",
)


def _fail(message: str) -> None:
    print(f"obsidience knowledge desktop: {message}", flush=True)
    GLib.idle_add(lambda: os._exit(1))


class KnowledgeDesktop:
    """Keep one layer surface bound to the current Samsung output."""

    def __init__(self, display: Gdk.Display) -> None:
        self.display = display
        self.monitor: Gdk.Monitor | None = None
        self.watched_monitors: list[Gdk.Monitor] = []
        self.window: Gtk.Window | None = None
        self.webview: WebKit2.WebView | None = None
        display.connect("monitor-added", self._monitor_changed)
        display.connect("monitor-removed", self._monitor_changed)
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

    def _samsung_monitor(self) -> Gdk.Monitor | None:
        for index in range(self.display.get_n_monitors()):
            monitor = self.display.get_monitor(index)
            geometry = monitor.get_geometry()
            if geometry.width == 5120 and geometry.height == 1440:
                return monitor
        return None

    def _monitor_changed(self, *_args: object) -> None:
        self._watch_current_monitors()
        GLib.idle_add(self.refresh)

    def refresh(self) -> bool:
        monitor = self._samsung_monitor()
        if monitor is None:
            if self.monitor is not None:
                print("obsidience knowledge desktop: Samsung output unavailable", flush=True)
                self.monitor = None
                if self.window is not None:
                    self.window.hide()
            return False
        if self.window is not None and monitor == self.monitor:
            return False

        self.monitor = monitor
        geometry = monitor.get_geometry()

        if self.window is not None:
            GtkLayerShell.set_monitor(self.window, monitor)
            self.window.show_all()
            print(
                "obsidience knowledge desktop: "
                f"restored {geometry.width}x{geometry.height}",
                flush=True,
            )
            return False

        window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        window.set_title("Obsidience Knowledge Desktop")
        window.set_decorated(False)
        window.set_accept_focus(False)

        GtkLayerShell.init_for_window(window)
        GtkLayerShell.set_namespace(window, "obsidience-knowledge-desktop")
        GtkLayerShell.set_monitor(window, monitor)
        GtkLayerShell.set_layer(window, GtkLayerShell.Layer.BACKGROUND)
        GtkLayerShell.set_exclusive_zone(window, 0)
        GtkLayerShell.set_keyboard_mode(window, GtkLayerShell.KeyboardMode.NONE)
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
                f"ready {geometry.width}x{geometry.height} {KNOWLEDGE_URL}",
                flush=True,
            )
            if event == WebKit2.LoadEvent.FINISHED
            else None,
        )

        window.add(webview)
        webview.load_uri(KNOWLEDGE_URL)
        self.window = window
        self.webview = webview
        window.show_all()
        return False


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
