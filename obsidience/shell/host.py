"""Minimal native Wayland shell host for the first Obsidience slice."""

from __future__ import annotations

import argparse
import signal
import sys
from datetime import datetime
from pathlib import Path

from .kwin import KWinObserver


PANEL_HEIGHT = 38


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the native Obsidience shell host")
    parser.add_argument("--output", default="HDMI-A-1")
    return parser


class ShellApplication:
    """Delay GTK imports so project tests do not require host GUI bindings."""

    def __init__(self, output_name: str) -> None:
        import gi

        gi.require_version("Gdk", "4.0")
        gi.require_version("Gtk", "4.0")
        gi.require_version("Gtk4LayerShell", "1.0")
        from gi.repository import Gdk, GLib, Gtk, Gtk4LayerShell, Pango

        self.Gdk = Gdk
        self.GLib = GLib
        self.Gtk = Gtk
        self.LayerShell = Gtk4LayerShell
        self.Pango = Pango
        self.output_name = output_name
        self.failed = False
        self.observer: KWinObserver | None = None
        self.active_label = None
        self.workspace_label = None
        self.clock_label = None
        self.background = None
        self.panel = None
        self.app = Gtk.Application(application_id="org.obsidience.Shell")
        self.app.connect("activate", self._activate)
        self.app.connect("shutdown", self._shutdown)
        for signal_number in (signal.SIGINT, signal.SIGTERM):
            GLib.unix_signal_add(
                GLib.PRIORITY_DEFAULT, signal_number, self._quit_from_signal
            )

    def run(self, argv: list[str]) -> int:
        status = self.app.run(argv)
        return 1 if self.failed else status

    def _activate(self, _app) -> None:
        try:
            if not self.LayerShell.is_supported():
                raise RuntimeError("KWin does not advertise the layer-shell protocol")
            display = self.Gdk.Display.get_default()
            if display is None:
                raise RuntimeError("Wayland display is unavailable")
            monitors = display.get_monitors()
            matches = [
                monitors.get_item(index)
                for index in range(monitors.get_n_items())
                if monitors.get_item(index).get_connector() == self.output_name
            ]
            if len(matches) != 1:
                raise RuntimeError(
                    f"expected exactly one output named {self.output_name}; found {len(matches)}"
                )
            monitor = matches[0]
            self._install_css(display)
            self._make_background(monitor)
            self._make_panel(monitor)
            self.observer = KWinObserver(self._refresh)
            self.observer.start()
            self._refresh()
            self.GLib.timeout_add_seconds(1, self._tick_clock)
            print(
                "obsidience-shell ready "
                f"output={self.output_name} layer_protocol={self.LayerShell.get_protocol_version()} "
                f"exclusive_zone={PANEL_HEIGHT}",
                flush=True,
            )
        except Exception as exc:
            self.failed = True
            print(f"obsidience-shell failed: {exc}", file=sys.stderr, flush=True)
            self.app.quit()

    def _install_css(self, display) -> None:
        provider = self.Gtk.CssProvider()
        provider.load_from_path(str(Path(__file__).parent / "resources" / "canary.css"))
        self.Gtk.StyleContext.add_provider_for_display(
            display, provider, self.Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _layer_window(self, monitor, *, name: str, layer, anchors: tuple) -> object:
        window = self.Gtk.ApplicationWindow(application=self.app)
        window.set_name(name)
        window.set_decorated(False)
        window.set_focusable(False)
        self.LayerShell.init_for_window(window)
        self.LayerShell.set_namespace(window, name)
        self.LayerShell.set_monitor(window, monitor)
        self.LayerShell.set_layer(window, layer)
        self.LayerShell.set_keyboard_mode(window, self.LayerShell.KeyboardMode.NONE)
        for edge in anchors:
            self.LayerShell.set_anchor(window, edge, True)
        return window

    def _make_background(self, monitor) -> None:
        edges = (
            self.LayerShell.Edge.TOP,
            self.LayerShell.Edge.RIGHT,
            self.LayerShell.Edge.BOTTOM,
            self.LayerShell.Edge.LEFT,
        )
        window = self._layer_window(
            monitor,
            name="obsidience-shell-background",
            layer=self.LayerShell.Layer.BACKGROUND,
            anchors=edges,
        )
        self.LayerShell.set_exclusive_zone(window, 0)
        window.connect("map", self._clear_input_region)
        window.set_child(self.Gtk.Box())
        window.present()
        self.background = window

    def _make_panel(self, monitor) -> None:
        window = self._layer_window(
            monitor,
            name="obsidience-shell-panel",
            layer=self.LayerShell.Layer.TOP,
            anchors=(
                self.LayerShell.Edge.TOP,
                self.LayerShell.Edge.RIGHT,
                self.LayerShell.Edge.LEFT,
            ),
        )
        self.LayerShell.set_exclusive_zone(window, PANEL_HEIGHT)
        window.set_default_size(1, PANEL_HEIGHT)

        row = self.Gtk.Box(orientation=self.Gtk.Orientation.HORIZONTAL, spacing=18)
        row.set_margin_start(16)
        row.set_margin_end(16)
        identity = self.Gtk.Label(label="OBSIDIENCE / DEVELOPMENT SHELL")
        identity.add_css_class("shell-identity")
        self.active_label = self.Gtk.Label(label="No active window", xalign=0)
        self.active_label.add_css_class("shell-state")
        self.active_label.set_ellipsize(self.Pango.EllipsizeMode.END)
        self.active_label.set_hexpand(True)
        self.workspace_label = self.Gtk.Label(label="Workspace")
        self.workspace_label.add_css_class("shell-muted")
        self.clock_label = self.Gtk.Label()
        self.clock_label.add_css_class("shell-state")
        for widget in (identity, self.active_label, self.workspace_label, self.clock_label):
            row.append(widget)
        window.set_child(row)
        window.present()
        self.panel = window

    def _clear_input_region(self, window) -> None:
        try:
            import cairo

            surface = window.get_surface()
            if surface is not None:
                surface.set_input_region(cairo.Region())
        except Exception as exc:
            self.failed = True
            print(f"obsidience-shell input region failed: {exc}", file=sys.stderr, flush=True)
            self.app.quit()

    def _refresh(self) -> None:
        if self.observer is None:
            return
        if self.active_label is not None:
            title = self.observer.active_title or "No active window"
            app_id = self.observer.active_app_id
            self.active_label.set_text(f"{title} · {app_id}" if app_id else title)
        if self.workspace_label is not None:
            self.workspace_label.set_text(self.observer.workspace_name)

    def _tick_clock(self) -> bool:
        if self.clock_label is not None:
            self.clock_label.set_text(datetime.now().astimezone().strftime("%H:%M:%S"))
        return True

    def _shutdown(self, _app) -> None:
        if self.observer is not None:
            self.observer.stop()
            self.observer = None
        print("obsidience-shell stopped", flush=True)

    def _quit_from_signal(self) -> bool:
        self.app.quit()
        return self.GLib.SOURCE_REMOVE


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    return ShellApplication(args.output).run([sys.argv[0]])
