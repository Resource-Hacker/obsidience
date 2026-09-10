"""One bounded WebSocket bridge between display adapters and the Shell API."""

from __future__ import annotations

import json
import logging
import math
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
_PANE_ID = re.compile(r"^[a-z][a-z0-9-]{0,47}$")
_CLICK_TOKEN_LIMIT = 4096
_CLICK_WITNESS_FIELDS = frozenset((
    "stable_id", "pid", "process_start_time", "local_rect", "image_width",
    "image_height", "x", "y", "captured_at_unix_ns", "label",
))
_RECT_FIELDS = frozenset(("x", "y", "width", "height"))


class ShellWindowTransport:
    def __init__(
        self,
        store: WindowStateStore,
        activate: Callable[[str, str, int], tuple[bool, str, int]],
        close: Callable[[str, str, int], tuple[bool, str]],
        layout: Callable[
            [str, str, int, str, str, dict[str, tuple[int, int]]],
            tuple[bool, str],
        ],
        restore: Callable[
            [str, str, int, str, dict[str, object]], tuple[bool, str]
        ],
        place: Callable[
            [
                str,
                str,
                int,
                str,
                dict[str, tuple[int, int]],
                dict[str, object] | None,
            ],
            tuple[bool, str, int],
        ],
        configure_grid: Callable[[str, int, int], tuple[bool, str]],
        configure_policy: Callable[
            [int, bool, int, int, int, bool], tuple[bool, str]
        ],
        click: Callable[[str, str, int, dict, str, int], dict] | None = None,
    ) -> None:
        self.store = store
        self.activate = activate
        self.close = close
        self.layout = layout
        self.restore = restore
        self.place = place
        self.configure_grid = configure_grid
        self.configure_policy = configure_policy
        self.click = click
        # Never evict a consumed mutation token: reconnect cannot replay a click.
        self._click_tokens: set[str] = set()
        self._applied_grids: dict[str, tuple[int, int]] = {}
        self._applied_policy: tuple[int, bool, int, int, int, bool] | None = None
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
        if event_type == "window.click.request":
            self._handle_click(socket, event)
            return
        if event_type == "workspace.state":
            grids = self._grids(event.get("workspace_tiling"))
            policy = self._policy(event)
            if grids is None or policy is None:
                return
            if self._applied_policy != policy:
                try:
                    success, reason = self.configure_policy(*policy)
                except Exception as error:
                    LOGGER.warning("Workspace policy update failed: %s", error)
                else:
                    if success:
                        self._applied_policy = policy
                    else:
                        LOGGER.warning("Workspace policy update rejected: %s", reason)
            for surface_id in sorted(grids):
                dimensions = grids[surface_id]
                if self._applied_grids.get(surface_id) == dimensions:
                    continue
                try:
                    success, reason = self.configure_grid(
                        surface_id, dimensions[0], dimensions[1]
                    )
                except Exception as error:
                    LOGGER.warning("Workspace grid update failed: %s", error)
                    continue
                if success:
                    self._applied_grids[surface_id] = dimensions
                else:
                    LOGGER.warning(
                        "Workspace grid update rejected for %s: %s",
                        surface_id,
                        reason,
                    )
            return
        if event_type not in (
            "window.activation.request",
            "window.close.request",
            "window.layout.request",
            "window.layout.restore.request",
            "window.place.request",
        ):
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
        post_revision = 0
        verified_tile_bounds = None
        destination_surface_id = ""
        if event_type == "window.layout.restore.request":
            pane_id = event.get("pane_id")
            tile_bounds = self._tile_bounds(event.get("tile_bounds"), surface_id)
            if (
                not isinstance(pane_id, str)
                or _PANE_ID.fullmatch(pane_id) is None
                or tile_bounds is None
            ):
                return
            try:
                success, reason = self.restore(
                    surface_id, window_id, revision, pane_id, tile_bounds
                )
            except Exception as error:
                LOGGER.warning("Window layout restore failed: %s", error)
                success, reason = False, "restore_error"
            result_type = "window.layout.restore.result"
        elif event_type == "window.place.request":
            destination_surface_id = str(event.get("destination_surface_id", ""))
            grids = self._grids(event.get("workspace_tiling"))
            tile_value = event.get("tile_bounds")
            tile_bounds = (
                None
                if tile_value is None
                else self._tile_bounds(tile_value, destination_surface_id)
            )
            if (
                destination_surface_id not in _SURFACES
                or grids is None
                or (tile_value is not None and tile_bounds is None)
            ):
                return
            try:
                success, reason, post_revision = self.place(
                    surface_id,
                    window_id,
                    revision,
                    destination_surface_id,
                    grids,
                    tile_bounds,
                )
                if success:
                    verified_tile_bounds = tile_bounds
            except Exception as error:
                LOGGER.warning("Window placement failed: %s", error)
                success, reason, post_revision = False, "placement_error", 0
            result_type = "window.place.result"
        elif event_type == "window.close.request":
            try:
                success, reason = self.close(surface_id, window_id, revision)
            except Exception as error:  # keep one failed command from dropping state
                LOGGER.warning("Window close failed: %s", error)
                success, reason = False, "close_error"
            result_type = "window.close.result"
        elif event_type == "window.layout.request":
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
                success, reason, post_revision = self.activate(
                    surface_id, window_id, revision
                )
            except Exception as error:  # keep one failed command from dropping state
                LOGGER.warning("Window activation failed: %s", error)
                success, reason, post_revision = False, "activation_error", 0
            result_type = "window.activation.result"
        socket.send(
            json.dumps(
                {
                    "schema": "obsidience.shell.command.v1",
                    "type": result_type,
                    "token": token,
                    "surface_id": surface_id,
                    "window_id": window_id,
                    "destination_surface_id": destination_surface_id,
                    "success": success,
                    "reason": "" if success else str(reason)[:96],
                    "post_revision": post_revision if success else 0,
                    **({"verified_tile_bounds": verified_tile_bounds}
                       if event_type == "window.place.request" else {}),
                    "completed_at": time.time(),
                },
                separators=(",", ":"),
            )
        )

    def _handle_click(self, socket, event: dict) -> None:
        token = event.get("token")
        if not isinstance(token, str) or _TOKEN.fullmatch(token) is None:
            return
        surface_id = event.get("surface_id")
        window_id = event.get("window_id")
        revision = event.get("expected_revision")
        generation = event.get("lock_generation")
        witness = self._click_witness(event.get("witness"))
        result = {"ok": False, "reason": "invalid_click_request", "delivery": "not_dispatched"}
        if token in self._click_tokens:
            result = {"ok": False, "reason": "duplicate_token", "delivery": "uncertain"}
        elif len(self._click_tokens) >= _CLICK_TOKEN_LIMIT:
            result["reason"] = "click_token_capacity"
        else:
            self._click_tokens.add(token)
            if (
                set(event) == {"schema", "type", "token", "surface_id", "window_id",
                               "expected_revision", "witness", "lock_generation"}
                and isinstance(surface_id, str) and surface_id in _SURFACES
                and isinstance(window_id, str) and 1 <= len(window_id) <= 128
                and not any(ord(char) < 32 for char in window_id)
                and type(revision) is int and 1 <= revision <= 2**53 - 1
                and type(generation) is int and 0 <= generation <= 2**53 - 1
                and witness is not None
            ):
                if self.click is None:
                    result["reason"] = "click_unavailable"
                else:
                    try:
                        result = self.click(
                            surface_id, window_id, revision, witness, token, generation
                        )
                    except Exception as error:
                        LOGGER.warning("Window click failed: %s", error)
                        result = {"ok": False, "reason": "click_error", "delivery": "uncertain"}
        if (
            not isinstance(result, dict) or type(result.get("ok")) is not bool
            or result.get("delivery") not in ("acknowledged", "not_dispatched", "uncertain")
            or not isinstance(result.get("reason"), str)
            or (result["ok"] and result["delivery"] != "acknowledged")
        ):
            result = {"ok": False, "reason": "invalid_click_result", "delivery": "uncertain"}
        socket.send(json.dumps({
            "schema": "obsidience.shell.command.v1", "type": "window.click.result",
            "token": token, "surface_id": surface_id if isinstance(surface_id, str) else "",
            "window_id": window_id if isinstance(window_id, str) else "",
            "success": result["ok"], "reason": result["reason"][:96],
            "delivery": result["delivery"], "completed_at": time.time(),
        }, separators=(",", ":")))

    @staticmethod
    def _click_witness(value: object) -> dict | None:
        if not isinstance(value, dict) or set(value) != _CLICK_WITNESS_FIELDS:
            return None
        if (
            not isinstance(value["stable_id"], str)
            or re.fullmatch(r"[0-9a-f]{1,32}", value["stable_id"]) is None
            or not isinstance(value["label"], str)
            or not 1 <= len(value["label"]) <= 128 or not value["label"].strip()
            or any(ord(char) < 32 for char in value["label"])
            or any(type(value[key]) is not int or not 1 <= value[key] <= 2**63 - 1
                   for key in ("pid", "process_start_time", "captured_at_unix_ns"))
            or any(type(value[key]) is not int or not 1 <= value[key] <= 16_000_000
                   for key in ("image_width", "image_height"))
            or value["image_width"] * value["image_height"] > 16_000_000
            or any(type(value[key]) not in (int, float)
                   or not 0 <= value[key] < value[extent] or not math.isfinite(value[key])
                   for key, extent in (("x", "image_width"), ("y", "image_height")))
        ):
            return None
        rect = value["local_rect"]
        if (not isinstance(rect, dict) or set(rect) != _RECT_FIELDS
                or any(type(rect[key]) is not int for key in _RECT_FIELDS)):
            return None
        if (
            not -131_072 <= rect["x"] <= 131_072
            or not -131_072 <= rect["y"] <= 131_072
            or not 1 <= rect["width"] <= 65_536
            or not 1 <= rect["height"] <= 65_536
        ):
            return None
        return {**value, "local_rect": dict(rect)}

    @staticmethod
    def click_guard(token: str, surface_id: str, window_id: str,
                    revision: int, generation: int) -> bool:
        """Read current Shell authorization while the command receive loop is busy."""
        deadline = time.monotonic() + 0.5
        try:
            with connect(
                "ws://127.0.0.1:8768", subprotocols=["obsidience.shell.v1"],
                open_timeout=0.25, close_timeout=0.01, max_size=65536,
            ) as socket:
                socket.send(json.dumps({
                    "schema": "obsidience.shell.command.v1", "type": "window.click.guard",
                    "token": token, "surface_id": surface_id, "window_id": window_id,
                    "expected_revision": revision, "lock_generation": generation,
                }, separators=(",", ":")))
                while (remaining := deadline - time.monotonic()) > 0:
                    message = socket.recv(timeout=remaining)
                    if not isinstance(message, str):
                        return False
                    event = json.loads(message)
                    if (isinstance(event, dict)
                            and event.get("schema") == "obsidience.shell.event.v1"
                            and event.get("type") == "window.click.guard.result"
                            and event.get("token") == token):
                        return event.get("allowed") is True
        except Exception:
            return False
        return False

    @staticmethod
    def _tile_bounds(value: object, surface_id: str) -> dict[str, object] | None:
        if not isinstance(value, dict) or value.get("surface_id") != surface_id:
            return None
        fields = ("columns", "rows", "left", "top", "right", "bottom")
        numbers = [value.get(field) for field in fields]
        if any(
            isinstance(number, bool) or not isinstance(number, int)
            for number in numbers
        ):
            return None
        columns, rows, left, top, right, bottom = numbers
        if (
            not 1 <= columns <= 16
            or not 1 <= rows <= 16
            or not 0 <= left < right <= columns
            or not 0 <= top < bottom <= rows
        ):
            return None
        return {"surface_id": surface_id, **dict(zip(fields, numbers, strict=True))}

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

    @staticmethod
    def _policy(
        event: dict[str, object],
    ) -> tuple[int, bool, int, int, int, bool] | None:
        resize_limit = event.get("tile_resize_limit_percent", 25)
        oled_enabled = event.get("oled_mode_enabled", False)
        shift_distance = event.get("oled_shift_distance_px", 32)
        travel_duration = event.get("oled_travel_duration_seconds", 3600)
        glow_rotation_hours = event.get("oled_glow_rotation_hours", 3)
        session_locked = event.get("session_locked", False)
        if (
            isinstance(resize_limit, bool)
            or not isinstance(resize_limit, int)
            or not 0 <= resize_limit <= 25
            or not isinstance(oled_enabled, bool)
            or isinstance(shift_distance, bool)
            or not isinstance(shift_distance, int)
            or not 1 <= shift_distance <= 50
            or isinstance(travel_duration, bool)
            or not isinstance(travel_duration, int)
            or not 60 <= travel_duration <= 86400
            or isinstance(glow_rotation_hours, bool)
            or not isinstance(glow_rotation_hours, int)
            or not 1 <= glow_rotation_hours <= 24
            or not isinstance(session_locked, bool)
        ):
            return None
        return (
            resize_limit,
            oled_enabled,
            shift_distance,
            travel_duration,
            glow_rotation_hours,
            session_locked,
        )
