"""One bounded WebSocket bridge between display adapters and the Shell API."""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections.abc import Callable

from websockets.sync.client import connect

from .model import WindowStateStore

LOGGER = logging.getLogger(__name__)
_TOKEN = re.compile(r"^[A-Za-z0-9._:-]{1,96}$")
_SURFACES = frozenset(("samsung", "usb-c", "dp-4"))
_ACTIONS = frozenset(("resize", "tile", "surface"))
_DIRECTIONS = frozenset(("left", "right", "top", "bottom"))


class ShellWindowTransport:
    def __init__(
        self,
        store: WindowStateStore,
        activate: Callable[[str, str, int], tuple[bool, str]],
        layout: Callable[
            [str, str, int, str, str, dict[str, tuple[int, int]]],
            tuple[bool, str],
        ],
    ) -> None:
        self.store = store
        self.activate = activate
        self.layout = layout
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="obsidience-window-transport",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                with connect(
                    "ws://127.0.0.1:8768",
                    subprotocols=["obsidience.shell.v1"],
                    open_timeout=2,
                    close_timeout=1,
                    max_size=65536,
                ) as socket:
                    socket.send(
                        json.dumps(
                            {
                                "schema": "obsidience.shell.command.v1",
                                "type": "window.adapter.subscribe",
                            },
                            separators=(",", ":"),
                        )
                    )
                    sent: dict[str, int] = {}
                    while not self._stop.is_set():
                        for state in self.store.snapshots():
                            if sent.get(state.surface_id) == state.revision:
                                continue
                            socket.send(
                                json.dumps(state.command(), separators=(",", ":"))
                            )
                            sent[state.surface_id] = state.revision
                        try:
                            message = socket.recv(timeout=0.10)
                        except TimeoutError:
                            continue
                        if isinstance(message, str):
                            self._handle(socket, message)
            except Exception as error:  # fail open for the desktop session
                LOGGER.warning("Window adapter reconnecting: %s", error)
                self._stop.wait(0.5)

    def _handle(self, socket, message: str) -> None:
        if len(message) > 65536:
            return
        try:
            event = json.loads(message)
        except json.JSONDecodeError:
            return
        if (
            not isinstance(event, dict)
            or event.get("schema") != "obsidience.shell.event.v1"
        ):
            return
        event_type = event.get("type")
        if event_type not in ("window.activation.request", "window.layout.request"):
            return
        token = event.get("token")
        surface_id = event.get("surface_id")
        window_id = event.get("window_id")
        revision = event.get("expected_revision")
        if (
            not isinstance(token, str)
            or _TOKEN.fullmatch(token) is None
            or not isinstance(surface_id, str)
            or not isinstance(window_id, str)
            or isinstance(revision, bool)
            or not isinstance(revision, int)
        ):
            return
        if event_type == "window.layout.request":
            action = event.get("action")
            direction = event.get("direction")
            grids = self._grids(event.get("workspace_tiling"))
            if action not in _ACTIONS or direction not in _DIRECTIONS or grids is None:
                return
            try:
                success, reason = self.layout(
                    surface_id, window_id, revision, action, direction, grids
                )
            except Exception as error:  # keep one failed command from dropping state
                LOGGER.warning("Window layout command failed: %s", error)
                success, reason = False, "layout_error"
            result_type = "window.layout.result"
        else:
            try:
                success, reason = self.activate(surface_id, window_id, revision)
            except Exception as error:  # keep one failed command from dropping state
                LOGGER.warning("Window activation failed: %s", error)
                success, reason = False, "activation_error"
            result_type = "window.activation.result"
        socket.send(
            json.dumps(
                {
                    "schema": "obsidience.shell.command.v1",
                    "type": result_type,
                    "token": token,
                    "surface_id": surface_id,
                    "window_id": window_id,
                    "success": success,
                    "reason": "" if success else str(reason)[:96],
                    "completed_at": time.time(),
                },
                separators=(",", ":"),
            )
        )

    @staticmethod
    def _grids(value: object) -> dict[str, tuple[int, int]] | None:
        if not isinstance(value, list) or len(value) != len(_SURFACES):
            return None
        grids: dict[str, tuple[int, int]] = {}
        for item in value:
            if not isinstance(item, dict):
                return None
            surface_id = item.get("surface_id")
            columns = item.get("columns")
            rows = item.get("rows")
            if (
                surface_id not in _SURFACES
                or surface_id in grids
                or isinstance(columns, bool)
                or not isinstance(columns, int)
                or isinstance(rows, bool)
                or not isinstance(rows, int)
                or not 1 <= columns <= 16
                or not 1 <= rows <= 16
            ):
                return None
            grids[surface_id] = (columns, rows)
        return grids if set(grids) == _SURFACES else None
