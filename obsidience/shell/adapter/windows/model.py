"""Bounded, display-server-neutral application-window state."""

from __future__ import annotations

import re
import threading
import time
from dataclasses import asdict, dataclass

MAX_WINDOWS = 256
MAX_TEXT = 512
MAX_COORDINATE = 131_072
MAX_EXTENT = 65_536
SURFACES = frozenset({"samsung", "usb-c", "dp-4"})
WINDOW_KINDS = frozenset({"application", "module"})
MODULE_APP_ID = "io.obsidience.shell"
PANE_ID = re.compile(r"^[a-z][a-z0-9-]{0,47}$")


def clean_text(value: object, maximum: int = MAX_TEXT) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.replace("\x00", "").split())[:maximum]


@dataclass(frozen=True, slots=True)
class LocalRect:
    x: int
    y: int
    width: int
    height: int

    def normalized(self) -> LocalRect | None:
        if (
            isinstance(self.x, bool)
            or not isinstance(self.x, int)
            or isinstance(self.y, bool)
            or not isinstance(self.y, int)
            or isinstance(self.width, bool)
            or not isinstance(self.width, int)
            or isinstance(self.height, bool)
            or not isinstance(self.height, int)
            or not -MAX_COORDINATE <= self.x <= MAX_COORDINATE
            or not -MAX_COORDINATE <= self.y <= MAX_COORDINATE
            or not 1 <= self.width <= MAX_EXTENT
            or not 1 <= self.height <= MAX_EXTENT
        ):
            return None
        return self


@dataclass(frozen=True, slots=True)
class ApplicationWindow:
    window_id: str
    app_id: str
    title: str
    local_rect: LocalRect = LocalRect(0, 0, 1, 1)
    pid: int = 0
    minimized: bool = False
    visible_on_workspace: bool = True
    window_kind: str = "application"
    pane_id: str = ""
    stable_id: str = ""

    def normalized(self) -> ApplicationWindow | None:
        window_id = clean_text(self.window_id, 128)
        app_id = clean_text(self.app_id, 256)
        local_rect = self.local_rect.normalized()
        window_kind = clean_text(self.window_kind, 16)
        pane_id = clean_text(self.pane_id, 48)
        stable_id = clean_text(self.stable_id, 128)
        if (
            not window_id
            or not app_id
            or local_rect is None
            or window_kind not in WINDOW_KINDS
        ):
            return None
        if window_kind == "module":
            if app_id != MODULE_APP_ID or PANE_ID.fullmatch(pane_id) is None:
                return None
        else:
            pane_id = ""
        pid = (
            self.pid
            if isinstance(self.pid, int) and not isinstance(self.pid, bool)
            else 0
        )
        return ApplicationWindow(
            window_id=window_id,
            app_id=app_id,
            title=clean_text(self.title),
            local_rect=local_rect,
            pid=max(0, pid),
            minimized=self.minimized is True,
            visible_on_workspace=self.visible_on_workspace is True,
            window_kind=window_kind,
            pane_id=pane_id,
            stable_id=stable_id,
        )


@dataclass(frozen=True, slots=True)
class SurfaceWindowState:
    surface_id: str
    revision: int
    active_window_id: str
    surface_awake: bool
    windows: tuple[ApplicationWindow, ...]

    def command(self) -> dict:
        windows = []
        for window in self.windows:
            record = asdict(window)
            if not record["stable_id"]:
                record.pop("stable_id")
            windows.append(record)
        return {
            "schema": "obsidience.shell.command.v1",
            "type": "window.state.publish",
            "surface_id": self.surface_id,
            "revision": self.revision,
            "active_window_id": self.active_window_id,
            "surface_awake": self.surface_awake,
            "windows": windows,
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
        surface_awake: bool = True,
    ) -> SurfaceWindowState | None:
        if (
            surface_id not in SURFACES
            or not isinstance(windows, (list, tuple))
            or not isinstance(surface_awake, bool)
        ):
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
        normalized.sort(
            key=lambda item: (
                item.app_id.casefold(),
                item.title.casefold(),
                item.window_id,
            )
        )
        active = clean_text(active_window_id, 128)
        if active not in seen:
            active = ""
        window_tuple = tuple(normalized)
        with self._condition:
            previous = self._states.get(surface_id)
            if (
                previous
                and previous.active_window_id == active
                and previous.surface_awake is surface_awake
                and previous.windows == window_tuple
            ):
                return previous
            state = SurfaceWindowState(
                surface_id=surface_id,
                revision=(previous.revision + 1) if previous else 1,
                active_window_id=active,
                surface_awake=surface_awake,
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

    def window_at_or_after(
        self, surface_id: str, window_id: str, observed_revision: int
    ) -> ApplicationWindow | None:
        """Resolve the same live window after unrelated state advances."""
        with self._condition:
            state = self._states.get(surface_id)
            if state is None or state.revision < observed_revision:
                return None
            return next(
                (window for window in state.windows if window.window_id == window_id),
                None,
            )

    def exact_active_window(
        self, surface_id: str, window_id: str, expected_revision: int
    ) -> ApplicationWindow | None:
        with self._condition:
            state = self._states.get(surface_id)
            if (
                state is None
                or state.revision != expected_revision
                or state.active_window_id != window_id
            ):
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

    def wait_absent(self, window_id: str, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        with self._condition:
            while time.monotonic() < deadline:
                if all(
                    window.window_id != window_id
                    for state in self._states.values()
                    for window in state.windows
                ):
                    return True
                self._condition.wait(max(0.01, deadline - time.monotonic()))
        return False
