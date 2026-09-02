"""Runtime host for Surface-local application observation and activation."""

from __future__ import annotations

import logging
import signal

from gi.repository import GLib

from .hyprland import HyprlandSurfaceWindows
from .model import ApplicationWindow, WindowStateStore
from .transport import ShellWindowTransport
from .x11 import X11SurfaceWindows

LOGGER = logging.getLogger(__name__)


class WindowAdapterHost:
    def __init__(self) -> None:
        self.store = WindowStateStore()
        self.hyprland = HyprlandSurfaceWindows(self._update)
        self.x11 = {
            "usb-c": X11SurfaceWindows(
                surface_id="usb-c", display_name=":2.0", on_change=self._update
            ),
            "dp-4": X11SurfaceWindows(
                surface_id="dp-4", display_name=":2.1", on_change=self._update
            ),
        }
        self.transport = ShellWindowTransport(self.store, self._activate)
        self.loop = GLib.MainLoop()

    def run(self) -> None:
        self.hyprland.start()
        for provider in self.x11.values():
            provider.start()
        self.transport.start()
        signal.signal(signal.SIGTERM, lambda *_args: self.loop.quit())
        signal.signal(signal.SIGINT, lambda *_args: self.loop.quit())
        try:
            self.loop.run()
        finally:
            self.transport.stop()
            for provider in self.x11.values():
                provider.stop()
            self.hyprland.stop()

    def _update(
        self,
        surface_id: str,
        active_window_id: str,
        windows: tuple[ApplicationWindow, ...],
    ) -> None:
        self.store.update(surface_id, active_window_id, windows)

    def _activate(
        self, surface_id: str, window_id: str, expected_revision: int
    ) -> tuple[bool, str]:
        target = self.store.exact_window(surface_id, window_id, expected_revision)
        if target is None:
            return False, "stale_or_invalid"
        if surface_id == "samsung":
            dispatched, reason = self.hyprland.activate(target.window_id)
        else:
            provider = self.x11.get(surface_id)
            if provider is None:
                return False, "unknown_surface"
            dispatched, reason = provider.activate(target.window_id)
        if not dispatched:
            return False, reason
        if self.store.wait_active(surface_id, target.window_id, 2.0):
            return True, ""
        return False, "activation_not_observed"


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    WindowAdapterHost().run()


if __name__ == "__main__":
    main()
