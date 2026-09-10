"""One exact, non-replaying command path from Harness Tools to the Shell."""

from __future__ import annotations

import json
import secrets
import time

from websockets.sync.client import connect

from obsidience.harness.host.scene import (
    EVENT_SCHEMA,
    SCENE,
    SHELL_SUBPROTOCOL,
    SHELL_URL,
    SURFACE_IDS,
    SceneTarget,
    SceneTargetAmbiguous,
    SceneTargetNotFound,
    SceneTargetStale,
    SceneUnavailable,
)

COMMAND_SCHEMA = "obsidience.shell.command.v1"
COMMAND_TIMEOUT_SECONDS = 3.0
POST_STATE_TIMEOUT_SECONDS = 2.0


class ShellCommandUnavailable(RuntimeError):
    """The sole Shell command boundary could not accept a request."""


class EffectNotObserved(RuntimeError):
    """Delivery or its required post-state is uncertain."""


class InvalidTarget(ValueError):
    """The semantic target contract is malformed."""


class InvalidDestination(ValueError):
    """The destination Surface or tile contract is malformed."""


def _failure(
    code: str, *, delivery: str = "not_dispatched", correction_allowed: bool = False,
) -> dict[str, object]:
    messages = {
        "scene_unavailable": "The current Shell scene is unavailable.",
        "target_missing": "No current Shell target matched that exact name.",
        "target_ambiguous": "That name matches more than one current Shell target.",
        "invalid_destination": "The destination Surface or tile is invalid.",
        "stale_scene": "The Shell scene changed before the result could be verified.",
        "effect_not_observed": (
            "The requested effect was not verified in fresh Shell state."
        ),
        "shell_scene_command_unavailable": (
            "The Shell command boundary is unavailable."
        ),
    }
    return {
        "status": "unavailable"
        if code in {"scene_unavailable", "shell_scene_command_unavailable"}
        else "failed",
        "effect_applied": None if delivery == "uncertain" else False,
        "delivery": delivery,
        "must_not_replay": True,
        "correction_allowed": correction_allowed,
        "failure": {
            "code": code,
            "message": messages[code],
            "retryable": False,
        },
    }


def _target(value: object) -> tuple[str, str, str]:
    if not isinstance(value, dict) or set(value) - {"kind", "name", "surface"}:
        raise InvalidTarget("invalid target")
    kind = value.get("kind")
    name = value.get("name")
    surface = value.get("surface", "")
    if (
        kind not in {"application", "pane"}
        or not isinstance(name, str)
        or not name
        or len(name) > (256 if kind == "application" else 48)
        or any(ord(character) < 32 for character in name)
        or not isinstance(surface, str)
        or (surface and surface not in SURFACE_IDS)
    ):
        raise InvalidTarget("invalid target")
    return kind, name, surface


def _scene_target(target: SceneTarget) -> SceneTarget:
    scene = SCENE.snapshot()
    if scene.workspace.get("session_locked") is True:
        raise SceneUnavailable("shell scene is locked")
    return SCENE.validate(target)


def _tile_bounds(
    destination: object, workspace: dict[str, object]
) -> tuple[str, dict[str, int] | None]:
    if (
        not isinstance(destination, dict)
        or set(destination) - {"surface", "tile"}
        or destination.get("surface") not in SURFACE_IDS
    ):
        raise InvalidDestination("invalid destination")
    surface = destination["surface"]
    grid = next(
        (
            value
            for value in workspace.get("workspace_tiling", [])
            if isinstance(value, dict) and value.get("surface_id") == surface
        ),
        None,
    )
    if grid is None:
        raise InvalidDestination("invalid destination")
    tile = destination.get("tile")
    if tile is None:
        return surface, None
    if not isinstance(tile, dict) or set(tile) != {
        "left",
        "top",
        "right",
        "bottom",
    }:
        raise InvalidDestination("invalid destination")
    numbers = [tile[field] for field in ("left", "top", "right", "bottom")]
    columns, rows = grid.get("columns"), grid.get("rows")
    if (
        any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in numbers
        )
        or isinstance(columns, bool)
        or not isinstance(columns, int)
        or isinstance(rows, bool)
        or not isinstance(rows, int)
    ):
        raise InvalidDestination("invalid destination")
    left, top, right, bottom = numbers
    if not 0 <= left < right <= columns or not 0 <= top < bottom <= rows:
        raise InvalidDestination("invalid destination")
    return surface, {
        "surface_id": surface,
        "columns": columns,
        "rows": rows,
        "left": left,
        "top": top,
        "right": right,
        "bottom": bottom,
    }


def _send_command(
    command: dict[str, object], result_type: str, *,
    timeout: float = COMMAND_TIMEOUT_SECONDS, cancel_event=None,
) -> dict[str, object]:
    sent = False
    try:
        with connect(
            SHELL_URL,
            subprotocols=[SHELL_SUBPROTOCOL],
            open_timeout=2,
            close_timeout=1,
            max_size=131_072,
        ) as socket:
            # A send failure may follow a partial write: delivery is then uncertain.
            if cancel_event is not None and cancel_event.is_set():
                raise ShellCommandUnavailable("command was cancelled")
            sent = True
            socket.send(json.dumps(command, separators=(",", ":")))
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if cancel_event is not None and cancel_event.is_set():
                    # Closing this owning socket invalidates the Shell click guard.
                    raise EffectNotObserved("command was cancelled")
                remaining = max(0.01, deadline - time.monotonic())
                try:
                    message = socket.recv(timeout=min(0.05, remaining) if cancel_event is not None else remaining)
                except TimeoutError:
                    if cancel_event is not None:
                        continue
                    raise
                if not isinstance(message, str) or len(message) > 131_072:
                    continue
                try:
                    result = json.loads(message)
                except json.JSONDecodeError:
                    continue
                if (
                    isinstance(result, dict)
                    and result.get("schema") == EVENT_SCHEMA
                    and result.get("type") == result_type
                    and result.get("token") == command["token"]
                    and result.get("surface_id") == command["surface_id"]
                    and result.get("window_id") == command["window_id"]
                    and (
                        result_type != "window.place.result"
                        or result.get("destination_surface_id")
                        == command["destination_surface_id"]
                    )
                ):
                    return result
    except Exception as error:
        if sent:
            raise EffectNotObserved("command result was not observed") from error
        raise ShellCommandUnavailable("shell command connection failed") from error
    raise EffectNotObserved("command result was not observed")


def _same_identity(before: SceneTarget, after: SceneTarget) -> bool:
    return (
        before.generation == after.generation
        and before.window.window_id == after.window.window_id
        and before.window.stable_id == after.window.stable_id
        and before.window.app_id == after.window.app_id
        and before.window.pid == after.window.pid
        and before.window.window_kind == after.window.window_kind
        and before.window.pane_id == after.window.pane_id
    )


def _post_target(
    before: SceneTarget,
    surface_id: str,
    post_revision: int,
    *,
    must_be_active: bool = False,
) -> SceneTarget:
    if (
        isinstance(post_revision, bool)
        or not isinstance(post_revision, int)
        or post_revision < 1
    ):
        raise EffectNotObserved("command returned no post-state revision")
    deadline = time.monotonic() + POST_STATE_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            scene = SCENE.snapshot()
            if scene.workspace.get("session_locked") is True:
                raise SceneTargetStale("shell scene locked")
            after = SCENE.resolve(window_id=before.window.window_id)
        except (SceneTargetNotFound, SceneTargetAmbiguous, SceneUnavailable):
            time.sleep(0.02)
            continue
        if scene.generation != before.generation or not _same_identity(before, after):
            raise SceneTargetStale("window identity changed")
        if (
            after.surface_id == surface_id
            and after.surface_revision >= post_revision
            and (not must_be_active or after.active)
        ):
            return after
        time.sleep(0.02)
    raise EffectNotObserved("fresh post-state was not observed")


def _result_failure(result: dict[str, object]) -> dict[str, object] | None:
    if result.get("success") is True:
        return None
    reason = str(result.get("reason", ""))
    code = {
        "scene_unavailable": "scene_unavailable",
        "shell_scene_command_unavailable": "shell_scene_command_unavailable",
        "stale_scene": "stale_scene",
        "stale_or_invalid": "stale_scene",
        "stale_or_inactive": "stale_scene",
        "invalid_destination": "invalid_destination",
    }.get(reason, "effect_not_observed")
    return _failure(
        code, delivery="uncertain" if code == "effect_not_observed" else "rejected"
    )


def activate(args: dict[str, object]) -> dict[str, object]:
    dispatched = False
    try:
        if set(args) != {"target"}:
            raise InvalidTarget("invalid target")
        kind, name, surface = _target(args["target"])
        target = _scene_target(SCENE.resolve_semantic(kind, name, surface))
        token = "tool." + secrets.token_hex(16)
        dispatched = True
        result = _send_command(
            {
                "schema": COMMAND_SCHEMA,
                "type": "window.activate",
                "token": token,
                "surface_id": target.surface_id,
                "window_id": target.window.window_id,
                "expected_revision": target.surface_revision,
            },
            "window.activation.result",
        )
        failure = _result_failure(result)
        if failure:
            return failure
        after = _post_target(
            target,
            target.surface_id,
            result.get("post_revision", 0),
            must_be_active=True,
        )
        return {
            "status": "completed",
            "effect_applied": not target.active,
            "must_not_replay": True,
            "target": {
                "kind": after.window.semantic_kind,
                "name": after.window.semantic_name,
                "surface": after.surface_id,
            },
            "active": True,
        }
    except InvalidTarget:
        return _failure("target_missing")
    except SceneTargetNotFound:
        return _failure("target_missing")
    except SceneTargetAmbiguous:
        return _failure("target_ambiguous")
    except SceneTargetStale:
        return _failure(
            "stale_scene", delivery="uncertain" if dispatched else "not_dispatched"
        )
    except SceneUnavailable:
        return _failure(
            "scene_unavailable", delivery="uncertain" if dispatched else "not_dispatched"
        )
    except ShellCommandUnavailable:
        return _failure("shell_scene_command_unavailable")
    except EffectNotObserved:
        return _failure("effect_not_observed", delivery="uncertain")


def place(args: dict[str, object]) -> dict[str, object]:
    dispatched = False
    try:
        if set(args) != {"target", "destination"}:
            raise InvalidDestination("invalid destination")
        kind, name, surface = _target(args["target"])
        target = SCENE.resolve_semantic(kind, name, surface)
        scene = SCENE.snapshot()
        if scene.workspace.get("session_locked") is True:
            raise SceneUnavailable("shell scene is locked")
        destination_surface, tile_bounds = _tile_bounds(
            args["destination"], scene.workspace
        )
        target = SCENE.validate(target)
        token = "tool." + secrets.token_hex(16)
        dispatched = True
        result = _send_command(
            {
                "schema": COMMAND_SCHEMA,
                "type": "window.place",
                "token": token,
                "surface_id": target.surface_id,
                "window_id": target.window.window_id,
                "expected_revision": target.surface_revision,
                "destination_surface_id": destination_surface,
                "tile_bounds": tile_bounds,
            },
            "window.place.result",
        )
        failure = _result_failure(result)
        if failure:
            return failure
        if tile_bounds is not None:
            verified = result.get("verified_tile_bounds")
            if (
                not isinstance(verified, dict)
                or verified != tile_bounds
                or any(type(verified.get(field)) is not int for field in (
                    "columns", "rows", "left", "top", "right", "bottom"
                ))
            ):
                raise EffectNotObserved("exact tile bounds were not attested")
        after = _post_target(
            target, destination_surface, result.get("post_revision", 0)
        )
        destination: dict[str, object] = {"surface": destination_surface}
        if tile_bounds is not None:
            destination["tile"] = {
                field: tile_bounds[field]
                for field in ("left", "top", "right", "bottom")
            }
        return {
            "status": "completed",
            "effect_applied": (
                target.surface_id != after.surface_id
                or target.window.local_rect != after.window.local_rect
            ),
            "must_not_replay": True,
            "target": {
                "kind": after.window.semantic_kind,
                "name": after.window.semantic_name,
                "surface": after.surface_id,
            },
            "destination": destination,
            "previous": {"surface": target.surface_id},
            "observed": {
                "surface": after.surface_id,
                "active": after.active,
                **({"tile": destination["tile"]} if tile_bounds is not None else {}),
            },
        }
    except InvalidTarget:
        return _failure("target_missing")
    except InvalidDestination:
        failure = _failure("invalid_destination")
        try:
            current = SCENE.snapshot()
        except SceneUnavailable:
            return failure
        if current.workspace.get("session_locked") is True:
            return failure
        failure["correction_allowed"] = True
        failure["destination_contract"] = {
            "units": "grid_edges",
            "grids": current.tile_grids,
            "bounds": "0 <= left < right <= columns; 0 <= top < bottom <= rows",
        }
        return failure
    except SceneTargetNotFound:
        return _failure("target_missing")
    except SceneTargetAmbiguous:
        return _failure("target_ambiguous")
    except SceneTargetStale:
        return _failure(
            "stale_scene", delivery="uncertain" if dispatched else "not_dispatched"
        )
    except SceneUnavailable:
        return _failure(
            "scene_unavailable", delivery="uncertain" if dispatched else "not_dispatched"
        )
    except ShellCommandUnavailable:
        return _failure("shell_scene_command_unavailable")
    except EffectNotObserved:
        return _failure("effect_not_observed", delivery="uncertain")
