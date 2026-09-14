"""Read-only semantic scene projected by the native Obsidience shell."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import threading
from dataclasses import dataclass

from websockets.asyncio.client import connect

from obsidience.harness.computer.applications import (
    application_window_name,
    matches_application_window,
)


LOGGER = logging.getLogger(__name__)
SHELL_URL = "ws://127.0.0.1:8768"
SHELL_SUBPROTOCOL = "obsidience.shell.v1"
EVENT_SCHEMA = "obsidience.shell.event.v1"
SURFACE_IDS = ("samsung", "usb-c", "dp-4")
MAX_MESSAGE_BYTES = 131_072
MAX_WINDOWS = 256
# Preserve the existing scene budget plus a fixed allowance for the three grids.
MAX_SEMANTIC_MANIFEST_CHARS = 1024
MAX_SEMANTIC_TITLE_CHARS = 80
_PANE_ID = re.compile(r"^[a-z][a-z0-9-]{0,47}$")


class SceneUnavailable(RuntimeError):
    """The shell has not supplied one complete current scene."""


class SceneLocked(SceneUnavailable):
    """The shell scene is private while the session is locked."""


class SceneManifestTooLarge(SceneUnavailable):
    """The complete semantic scene cannot fit its model-facing bound."""


class SceneTargetNotFound(LookupError):
    """No current window matches an exact target selector."""


class SceneTargetAmbiguous(LookupError):
    """More than one current window matches an exact target selector."""


class SceneTargetStale(RuntimeError):
    """A previously resolved target no longer belongs to the current scene."""


@dataclass(frozen=True, slots=True)
class SceneRect:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class SceneWindow:
    window_id: str
    stable_id: str
    app_id: str
    title: str
    pid: int
    minimized: bool
    visible_on_workspace: bool
    window_kind: str
    pane_id: str
    local_rect: SceneRect

    @property
    def semantic_kind(self) -> str:
        return "pane" if self.window_kind == "module" else "application"

    @property
    def semantic_name(self) -> str:
        return self.pane_id or application_window_name(self.app_id, self.title)


@dataclass(frozen=True, slots=True)
class SceneSurface:
    surface_id: str
    revision: int
    active_window_id: str
    awake: bool
    windows: tuple[SceneWindow, ...]


@dataclass(frozen=True, slots=True)
class SceneSnapshot:
    generation: int
    workspace: dict[str, object]
    surfaces: tuple[SceneSurface, ...]

    @property
    def tile_grids(self) -> dict[str, dict[str, int]]:
        """Publish only validated semantic grid counts, never pixel geometry."""
        return {
            grid["surface_id"]: {"columns": grid["columns"], "rows": grid["rows"]}
            for grid in self.workspace["workspace_tiling"]
        }


@dataclass(frozen=True, slots=True)
class SceneTarget:
    generation: int
    surface_id: str
    surface_revision: int
    surface_awake: bool
    active: bool
    window: SceneWindow


def _integer(value: object, minimum: int, maximum: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value if minimum <= value <= maximum else None


def _text(value: object, maximum: int, *, required: bool = False) -> str | None:
    if not isinstance(value, str) or len(value) > maximum:
        return None
    if any(ord(character) < 32 for character in value):
        return None
    if required and not value:
        return None
    return value


def _semantic_title(value: str) -> str:
    title = " ".join(value.split())
    if len(title) <= MAX_SEMANTIC_TITLE_CHARS:
        return title
    return title[: MAX_SEMANTIC_TITLE_CHARS - 1].rstrip() + "…"


def _workspace(event: dict[str, object]) -> dict[str, object] | None:
    revision = _integer(event.get("revision"), 0, 2**31 - 1)
    tiling = event.get("workspace_tiling")
    if revision is None or not isinstance(tiling, list) or len(tiling) != 3:
        return None
    seen: set[str] = set()
    for row in tiling:
        if not isinstance(row, dict):
            return None
        surface_id = row.get("surface_id")
        columns = _integer(row.get("columns"), 1, 16)
        rows = _integer(row.get("rows"), 1, 16)
        zones = _integer(row.get("zones"), 1, 256)
        if (
            surface_id not in SURFACE_IDS
            or surface_id in seen
            or columns is None
            or rows is None
            or zones != columns * rows
        ):
            return None
        seen.add(surface_id)
    if seen != set(SURFACE_IDS):
        return None
    return copy.deepcopy(event)


def _rect(value: object) -> SceneRect | None:
    if not isinstance(value, dict):
        return None
    x = _integer(value.get("x"), -32_768, 32_768)
    y = _integer(value.get("y"), -32_768, 32_768)
    width = _integer(value.get("width"), 1, 32_768)
    height = _integer(value.get("height"), 1, 32_768)
    if None in (x, y, width, height):
        return None
    return SceneRect(x=x, y=y, width=width, height=height)


def _window(value: object) -> SceneWindow | None:
    if not isinstance(value, dict):
        return None
    window_id = _text(value.get("window_id"), 128, required=True)
    stable_id = _text(value.get("stable_id", ""), 128)
    app_id = _text(value.get("app_id"), 256, required=True)
    title = _text(value.get("title"), 512, required=True)
    pane_id = _text(value.get("pane_id", ""), 48)
    window_kind = value.get("window_kind")
    pid = _integer(value.get("pid"), 0, 2**31 - 1)
    local_rect = _rect(value.get("local_rect"))
    if (
        window_id is None
        or stable_id is None
        or app_id is None
        or title is None
        or pane_id is None
        or window_kind not in {"application", "module"}
        or pid is None
        or local_rect is None
        or not isinstance(value.get("minimized"), bool)
        or not isinstance(value.get("visible_on_workspace"), bool)
    ):
        return None
    if window_kind == "module":
        if app_id != "io.obsidience.shell" or _PANE_ID.fullmatch(pane_id) is None:
            return None
    elif pane_id:
        return None
    return SceneWindow(
        window_id=window_id,
        stable_id=stable_id,
        app_id=app_id,
        title=title,
        pid=pid,
        minimized=value["minimized"],
        visible_on_workspace=value["visible_on_workspace"],
        window_kind=window_kind,
        pane_id=pane_id,
        local_rect=local_rect,
    )


def _surface(event: dict[str, object]) -> SceneSurface | None:
    surface_id = event.get("surface_id")
    revision = _integer(event.get("revision"), 1, 2**31 - 1)
    values = event.get("windows")
    active_window_id = _text(event.get("active_window_id"), 128)
    if (
        surface_id not in SURFACE_IDS
        or revision is None
        or active_window_id is None
        or not isinstance(event.get("surface_awake"), bool)
        or not isinstance(values, list)
        or len(values) > MAX_WINDOWS
    ):
        return None
    windows: list[SceneWindow] = []
    seen: set[str] = set()
    for value in values:
        window = _window(value)
        if window is None or window.window_id in seen:
            return None
        seen.add(window.window_id)
        windows.append(window)
    if active_window_id and active_window_id not in seen:
        return None
    return SceneSurface(
        surface_id=surface_id,
        revision=revision,
        active_window_id=active_window_id,
        awake=event["surface_awake"],
        windows=tuple(windows),
    )


class ShellSceneCache:
    """Own one complete, connection-bound shell scene and exact target leases."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self._change_sequence = 0
        self._generation = 0
        self._connected = False
        self._workspace: dict[str, object] | None = None
        self._surfaces: dict[str, SceneSurface] = {}

    def connect(self) -> int:
        with self._lock:
            self._generation += 1
            self._connected = True
            self._workspace = None
            self._surfaces = {}
            self._notify_changed()
            return self._generation

    def disconnect(self, generation: int) -> None:
        with self._lock:
            if generation != self._generation:
                return
            self._connected = False
            self._workspace = None
            self._surfaces = {}
            self._notify_changed()

    def accept(self, generation: int, event: object) -> bool:
        if (
            not isinstance(event, dict)
            or event.get("schema") != EVENT_SCHEMA
        ):
            return False
        event_type = event.get("type")
        workspace = _workspace(event) if event_type == "workspace.state" else None
        surface = _surface(event) if event_type == "application.state" else None
        if workspace is None and surface is None:
            return False
        with self._lock:
            if not self._connected or generation != self._generation:
                return False
            if workspace is not None:
                current_revision = (
                    self._workspace.get("revision") if self._workspace else None
                )
                revision = workspace["revision"]
                if isinstance(current_revision, int) and revision < current_revision:
                    return False
                if workspace == self._workspace:
                    return False
                self._workspace = workspace
                self._notify_changed()
                return True
            assert surface is not None
            current = self._surfaces.get(surface.surface_id)
            if current is not None and surface.revision <= current.revision:
                return False
            self._surfaces[surface.surface_id] = surface
            self._notify_changed()
            return True

    def _notify_changed(self) -> None:
        self._change_sequence += 1
        self._changed.notify_all()

    def change_token(self) -> int:
        with self._lock:
            return self._change_sequence

    def wait_for_change(self, token: int, timeout: float) -> int:
        """Wait on the existing scene publisher; never enumerate another scene."""
        with self._changed:
            self._changed.wait_for(lambda: token != self._change_sequence, max(0.0, timeout))
            return self._change_sequence

    def snapshot(self) -> SceneSnapshot:
        with self._lock:
            if (
                not self._connected
                or self._workspace is None
                or set(self._surfaces) != set(SURFACE_IDS)
            ):
                raise SceneUnavailable("shell scene is not hydrated")
            return SceneSnapshot(
                generation=self._generation,
                workspace=copy.deepcopy(self._workspace),
                surfaces=tuple(self._surfaces[key] for key in SURFACE_IDS),
            )

    def semantic_manifest(self) -> dict[str, object]:
        """Return every addressable semantic name without native identities."""
        scene = self.snapshot()
        if scene.workspace.get("session_locked") is True:
            raise SceneLocked("shell scene is locked")
        manifest: dict[str, object] = {
            "available": True,
            "fields": ["kind", "name", "title", "focused", "visible"],
            "tile_units": "grid_edges",
            "tile_grids": scene.tile_grids,
            "surface_awake": {
                surface.surface_id: surface.awake for surface in scene.surfaces
            },
            "surfaces": {
                surface.surface_id: [
                    [
                        window.semantic_kind,
                        window.semantic_name,
                        _semantic_title(window.title),
                        window.window_id == surface.active_window_id,
                        surface.awake
                        and window.visible_on_workspace
                        and not window.minimized,
                    ]
                    for window in surface.windows
                ]
                for surface in scene.surfaces
            },
        }
        encoded = json.dumps(manifest, separators=(",", ":"), sort_keys=True)
        if len(encoded) > MAX_SEMANTIC_MANIFEST_CHARS:
            raise SceneManifestTooLarge("shell scene exceeds its semantic bound")
        return manifest

    def activation_binding(self) -> dict[str, object]:
        """Return one safe activation value; absence is explicit and never raises."""

        try:
            return self.semantic_manifest()
        except SceneLocked:
            return {"available": False, "reason": "locked"}
        except SceneManifestTooLarge:
            return {"available": False, "reason": "scene_too_large"}
        except SceneUnavailable:
            return {"available": False, "reason": "unavailable"}

    def resolve(
        self,
        *,
        window_id: str = "",
        stable_id: str = "",
        pane_id: str = "",
        app_id: str = "",
        title: str = "",
        surface_id: str = "",
    ) -> SceneTarget:
        selectors = {
            "window_id": window_id,
            "stable_id": stable_id,
            "pane_id": pane_id,
            "app_id": app_id,
            "title": title,
        }
        if not any(selectors.values()):
            raise ValueError("an exact scene target selector is required")
        if surface_id and surface_id not in SURFACE_IDS:
            raise ValueError("unknown Surface")
        scene = self.snapshot()
        matches: list[SceneTarget] = []
        for surface in scene.surfaces:
            if surface_id and surface.surface_id != surface_id:
                continue
            for window in surface.windows:
                if all(
                    not expected or getattr(window, field) == expected
                    for field, expected in selectors.items()
                ):
                    matches.append(
                        SceneTarget(
                            generation=scene.generation,
                            surface_id=surface.surface_id,
                            surface_revision=surface.revision,
                            surface_awake=surface.awake,
                            active=window.window_id == surface.active_window_id,
                            window=window,
                        )
                    )
        if not matches:
            raise SceneTargetNotFound("no exact shell target matched")
        if len(matches) != 1:
            raise SceneTargetAmbiguous("exact shell target matched multiple windows")
        return matches[0]

    def resolve_semantic(
        self, kind: str, name: str = "", surface_id: str = "", *, title: str = ""
    ) -> SceneTarget:
        """Resolve the same public selector for observation, activation and placement."""
        if kind not in {"application", "pane", "focused"}:
            raise ValueError("unknown target kind")
        if surface_id and surface_id not in SURFACE_IDS:
            raise ValueError("unknown Surface")
        if title and kind != "application":
            raise ValueError("title disambiguation requires an application")
        scene = self.snapshot()
        if scene.workspace.get("session_locked") is True:
            raise SceneLocked("shell scene is locked")
        matches = []
        for surface in scene.surfaces:
            if surface_id and surface.surface_id != surface_id:
                continue
            for window in surface.windows:
                if kind == "focused":
                    matched = window.window_id == surface.active_window_id
                elif kind == "pane":
                    matched = window.window_kind == "module" and window.pane_id == name
                else:
                    matched = window.window_kind == "application" and (
                        window.app_id == name
                        or matches_application_window(name, window.app_id, window.title)
                    )
                if matched and (not title or _semantic_title(window.title) == title):
                    matches.append(
                        SceneTarget(
                            generation=scene.generation,
                            surface_id=surface.surface_id,
                            surface_revision=surface.revision,
                            surface_awake=surface.awake,
                            active=window.window_id == surface.active_window_id,
                            window=window,
                        )
                    )
        if not matches:
            raise SceneTargetNotFound("no semantic shell target matched")
        if len(matches) != 1:
            raise SceneTargetAmbiguous("semantic target matched multiple windows")
        return matches[0]

    def validate(self, target: SceneTarget) -> SceneTarget:
        scene = self.snapshot()
        if target.generation != scene.generation:
            raise SceneTargetStale("shell connection changed")
        surface = next(
            (item for item in scene.surfaces if item.surface_id == target.surface_id),
            None,
        )
        if surface is None or surface.revision != target.surface_revision:
            raise SceneTargetStale("Surface state changed")
        if surface.awake is not target.surface_awake:
            raise SceneTargetStale("Surface power changed")
        window = next(
            (
                item
                for item in surface.windows
                if item.window_id == target.window.window_id
            ),
            None,
        )
        if window != target.window:
            raise SceneTargetStale("window identity changed")
        return SceneTarget(
            generation=scene.generation,
            surface_id=surface.surface_id,
            surface_revision=surface.revision,
            surface_awake=surface.awake,
            active=window.window_id == surface.active_window_id,
            window=window,
        )


class ShellSceneClient:
    """Keep the Harness's read-only scene cache synced to the one shell host."""

    def __init__(self, url: str = SHELL_URL) -> None:
        self.url = url
        self.cache = ShellSceneCache()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(
                self._run(), name="obsidience-shell-scene"
            )

    async def stop(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def change_token(self) -> int:
        return self.cache.change_token()

    def wait_for_change(self, token: int, timeout: float) -> int:
        return self.cache.wait_for_change(token, timeout)

    def snapshot(self) -> SceneSnapshot:
        return self.cache.snapshot()

    def semantic_manifest(self) -> dict[str, object]:
        return self.cache.semantic_manifest()

    def activation_binding(self) -> dict[str, object]:
        return self.cache.activation_binding()

    def resolve(self, **selectors: str) -> SceneTarget:
        return self.cache.resolve(**selectors)

    def resolve_semantic(
        self, kind: str, name: str = "", surface_id: str = "", *, title: str = ""
    ) -> SceneTarget:
        return self.cache.resolve_semantic(kind, name, surface_id, title=title)

    def validate(self, target: SceneTarget) -> SceneTarget:
        return self.cache.validate(target)

    async def _run(self) -> None:
        while True:
            generation = 0
            try:
                async with connect(
                    self.url,
                    subprotocols=[SHELL_SUBPROTOCOL],
                    open_timeout=2,
                    close_timeout=1,
                    max_size=MAX_MESSAGE_BYTES,
                ) as socket:
                    generation = self.cache.connect()
                    async for message in socket:
                        if (
                            not isinstance(message, str)
                            or len(message) > MAX_MESSAGE_BYTES
                        ):
                            continue
                        try:
                            event = json.loads(message)
                        except json.JSONDecodeError:
                            continue
                        self.cache.accept(generation, event)
            except asyncio.CancelledError:
                raise
            except Exception as error:  # shell absence must not stop the Harness
                LOGGER.debug("Shell scene reconnecting: %s", error)
            finally:
                if generation:
                    self.cache.disconnect(generation)
            await asyncio.sleep(0.5)


SCENE = ShellSceneClient()
