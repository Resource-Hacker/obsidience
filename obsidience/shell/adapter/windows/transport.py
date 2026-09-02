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


class ShellWindowTransport:
    def __init__(
        self,
        store: WindowStateStore,
        activate: Callable[[str, str, int], tuple[bool, str]],
    ) -> None:
        self.store = store
        self.activate = activate
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
                            socket.send(json.dumps(state.command(), separators=(",", ":")))
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
        if not isinstance(event, dict) or event.get("schema") != "obsidience.shell.event.v1":
            return
        if event.get("type") != "window.activation.request":
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
        try:
            success, reason = self.activate(surface_id, window_id, revision)
        except Exception as error:  # keep one failed command from dropping state
            LOGGER.warning("Window activation failed: %s", error)
            success, reason = False, "activation_error"
        socket.send(
            json.dumps(
                {
                    "schema": "obsidience.shell.command.v1",
                    "type": "window.activation.result",
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
