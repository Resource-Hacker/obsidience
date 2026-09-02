"""Bounded, display-server-neutral application-window state."""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass

MAX_WINDOWS = 256
MAX_TEXT = 512
SURFACES = frozenset({"samsung", "usb-c", "dp-4"})


def clean_text(value: object, maximum: int = MAX_TEXT) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.replace("\x00", "").split())[:maximum]


@dataclass(frozen=True, slots=True)
class ApplicationWindow:
    window_id: str
    app_id: str
    title: str
    pid: int = 0
    minimized: bool = False

    def normalized(self) -> ApplicationWindow | None:
        window_id = clean_text(self.window_id, 128)
        app_id = clean_text(self.app_id, 256)
        if not window_id or not app_id:
            return None
        pid = self.pid if isinstance(self.pid, int) and not isinstance(self.pid, bool) else 0
        return ApplicationWindow(
            window_id=window_id,
            app_id=app_id,
            title=clean_text(self.title),
            pid=max(0, pid),
            minimized=self.minimized is True,
        )


@dataclass(frozen=True, slots=True)
class SurfaceWindowState:
    surface_id: str
    revision: int
    active_window_id: str
    windows: tuple[ApplicationWindow, ...]

    def command(self) -> dict:
        return {
            "schema": "obsidience.shell.command.v1",
            "type": "window.state.publish",
            "surface_id": self.surface_id,
            "revision": self.revision,
            "active_window_id": self.active_window_id,
            "windows": [asdict(window) for window in self.windows],
        }


class WindowStateStore:
    """Own one revisioned snapshot per Surface and no display-server behavior."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._states: dict[str, SurfaceWindowState] = {}
        self.changed = threading.Event()

    def update(
        self,
        surface_id: str,
        active_window_id: object,
        windows: object,
    ) -> SurfaceWindowState | None:
        if surface_id not in SURFACES or not isinstance(windows, (list, tuple)):
            return None
        normalized: list[ApplicationWindow] = []
        seen: set[str] = set()
        for candidate in windows[:MAX_WINDOWS]:
            if not isinstance(candidate, ApplicationWindow):
                continue
            window = candidate.normalized()
            if window is None or window.window_id in seen:
                continue
            seen.add(window.window_id)
            normalized.append(window)
        normalized.sort(key=lambda item: (item.app_id.casefold(), item.title.casefold(), item.window_id))
        active = clean_text(active_window_id, 128)
        if active not in seen:
            active = ""
        window_tuple = tuple(normalized)
        with self._condition:
            previous = self._states.get(surface_id)
            if previous and previous.active_window_id == active and previous.windows == window_tuple:
                return previous
            state = SurfaceWindowState(
                surface_id=surface_id,
                revision=(previous.revision + 1) if previous else 1,
                active_window_id=active,
                windows=window_tuple,
            )
            self._states[surface_id] = state
            self.changed.set()
            self._condition.notify_all()
            return state

    def snapshots(self) -> tuple[SurfaceWindowState, ...]:
        with self._condition:
            return tuple(self._states[key] for key in sorted(self._states))

    def exact_window(
        self, surface_id: str, window_id: str, expected_revision: int
    ) -> ApplicationWindow | None:
        with self._condition:
            state = self._states.get(surface_id)
            if state is None or state.revision != expected_revision:
                return None
            return next(
                (window for window in state.windows if window.window_id == window_id),
                None,
            )

    def wait_active(self, surface_id: str, window_id: str, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        with self._condition:
            while time.monotonic() < deadline:
                state = self._states.get(surface_id)
                if state and state.active_window_id == window_id:
                    return True
                self._condition.wait(max(0.01, deadline - time.monotonic()))
        return False
