"""Runtime host for Surface-local application observation and activation."""

from __future__ import annotations

import logging
import signal
import time
from dataclasses import asdict

from gi.repository import GLib

from .hyprland import HyprlandSurfaceWindows
from .model import ApplicationWindow, WindowStateStore
from .transport import ShellWindowTransport

LOGGER = logging.getLogger(__name__)


class WindowAdapterHost:
    def __init__(self) -> None:
        self.store = WindowStateStore()
        self.hyprland = HyprlandSurfaceWindows(self._update)
        self.transport = ShellWindowTransport(
            self.store,
            self._activate,
            self._close,
            self._layout,
            self._restore,
            self._place,
            self.hyprland.configure_grid,
            self.hyprland.configure_policy,
            click=self._click,
        )
        self.loop = GLib.MainLoop()

    def run(self) -> None:
        self.hyprland.start()
        self.transport.start()
        signal.signal(signal.SIGTERM, lambda *_args: self.loop.quit())
        signal.signal(signal.SIGINT, lambda *_args: self.loop.quit())
        try:
            self.loop.run()
        finally:
            self.transport.stop()
            self.hyprland.stop()

    def _update(
        self,
        surface_id: str,
        active_window_id: str,
        windows: tuple[ApplicationWindow, ...],
        surface_awake: bool,
    ) -> None:
        self.store.update(surface_id, active_window_id, windows, surface_awake)

    def _activate(
        self, surface_id: str, window_id: str, expected_revision: int
    ) -> tuple[bool, str, int]:
        target = self.store.exact_window(surface_id, window_id, expected_revision)
        if target is None:
            return False, "stale_or_invalid", 0
        dispatched, reason = self.hyprland.activate(target.window_id)
        if not dispatched:
            return False, reason, 0
        if self.store.wait_active(surface_id, target.window_id, 2.0):
            return True, "", self._post_revision(surface_id, target.window_id)
        return False, "activation_not_observed", 0

    def _layout(
        self,
        surface_id: str,
        window_id: str,
        expected_revision: int,
        action: str,
        direction: str,
        grids: dict[str, tuple[int, int]],
    ) -> tuple[bool, str]:
        target = self.store.exact_active_window(
            surface_id, window_id, expected_revision
        )
        if target is None:
            return False, "stale_or_inactive"
        return self.hyprland.layout(
            surface_id, target.window_id, action, direction, grids
        )

    def _close(
        self, surface_id: str, window_id: str, expected_revision: int
    ) -> tuple[bool, str]:
        target = self.store.exact_active_window(
            surface_id, window_id, expected_revision
        )
        if target is None:
            return False, "stale_or_inactive"
        dispatched, reason = self.hyprland.close(target.window_id)
        if not dispatched:
            return False, reason
        if self.store.wait_absent(target.window_id, 2.0):
            return True, ""
        return False, "close_not_observed"

    def _restore(
        self,
        surface_id: str,
        window_id: str,
        expected_revision: int,
        pane_id: str,
        tile_bounds: dict[str, object],
    ) -> tuple[bool, str]:
        target = self.store.window_at_or_after(
            surface_id, window_id, expected_revision
        )
        if (
            target is None
            or target.window_kind != "module"
            or target.pane_id != pane_id
        ):
            return False, "stale_or_invalid"
        return self.hyprland.restore(surface_id, window_id, tile_bounds)

    def _place(
        self,
        surface_id: str,
        window_id: str,
        expected_revision: int,
        destination_surface_id: str,
        grids: dict[str, tuple[int, int]],
        tile_bounds: dict[str, object] | None,
    ) -> tuple[bool, str, int]:
        target = self.store.exact_window(surface_id, window_id, expected_revision)
        if target is None:
            return False, "stale_or_invalid", 0
        dispatched, reason = self.hyprland.place(
            surface_id,
            target.window_id,
            destination_surface_id,
            grids,
            tile_bounds,
        )
        if not dispatched:
            return False, reason, 0
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            revision = self._post_revision(
                destination_surface_id, target.window_id
            )
            if revision:
                return True, "", revision
            time.sleep(0.02)
        return False, "placement_not_observed", 0

    def _post_revision(self, surface_id: str, window_id: str) -> int:
        for state in self.store.snapshots():
            if state.surface_id == surface_id and any(
                window.window_id == window_id for window in state.windows
            ):
                return state.revision
        return 0

    def _click(
        self, surface_id: str, window_id: str, expected_revision: int,
        witness: dict, token: str, lock_generation: int,
    ) -> dict:
        target = self.store.exact_window(surface_id, window_id, expected_revision)
        state = next((state for state in self.store.snapshots()
                      if state.surface_id == surface_id), None)
        reason = ""
        if target is None or state is None or state.revision != expected_revision:
            reason = "stale_scene"
        elif target.window_kind != "application":
            reason = "unsupported_target"
        elif not state.surface_awake or target.minimized or not target.visible_on_workspace:
            reason = "target_not_visible"
        elif (
            ShellWindowTransport._click_witness(witness) is None
            or witness["stable_id"] != target.stable_id
            or witness["pid"] != target.pid
            or witness["local_rect"] != asdict(target.local_rect)
        ):
            reason = "stale_witness"
        if reason:
            return {"ok": False, "reason": reason, "delivery": "not_dispatched"}
        return self.hyprland.click(
            surface_id, target, witness,
            guard=lambda: self.transport.click_guard(
                token, surface_id, window_id, expected_revision, lock_generation
            ),
        )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    WindowAdapterHost().run()


if __name__ == "__main__":
    main()
