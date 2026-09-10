"""Observe one exact Shell-scene target without changing focus."""

from __future__ import annotations

from typing import Any

from obsidience.harness.computer.capture import (
    ScreenCaptureError,
    capture_screen,
)
from obsidience.harness.computer.grounding import GroundingError, process_start_time
from obsidience.harness.host.scene import (
    SCENE,
    SURFACE_IDS,
    SceneSnapshot,
    SceneTarget,
    SceneTargetAmbiguous,
    SceneTargetNotFound,
    SceneTargetStale,
    SceneUnavailable,
)


PRIVATE_IMAGE_FIELD = "_private_image_png"
PRIVATE_OBSERVATION_FIELD = "_private_observation_lease"
_TARGET_KINDS = {"focused", "application", "pane"}


class _ObserveFailure(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _text(value: object, field: str, maximum: int) -> str:
    text = " ".join(str(value or "").split())
    if not text or len(text) > maximum:
        raise _ObserveFailure(
            "observation_failed", f"{field} must contain 1-{maximum} characters."
        )
    return text


def _request(args: dict[str, Any]) -> tuple[str, str, str, str]:
    if set(args) != {"target", "query"} or not isinstance(args["target"], dict):
        raise _ObserveFailure(
            "observation_failed", "computer.observe requires target and query."
        )
    target = args["target"]
    if set(target) - {"kind", "name", "surface"}:
        raise _ObserveFailure(
            "observation_failed", "computer.observe received an unknown target field."
        )
    kind = target.get("kind")
    if kind not in _TARGET_KINDS:
        raise _ObserveFailure(
            "observation_failed", "target kind must be focused, application, or pane."
        )
    surface = target.get("surface", "")
    if surface and surface not in SURFACE_IDS:
        raise _ObserveFailure("observation_failed", "target Surface is unknown.")
    if not isinstance(surface, str):
        raise _ObserveFailure("observation_failed", "target Surface is invalid.")

    if kind == "focused":
        if "name" in target:
            raise _ObserveFailure(
                "observation_failed", "a focused target must omit name."
            )
        name = ""
    else:
        name = target.get("name")
        limit = 256 if kind == "application" else 48
        if (
            not isinstance(name, str) or not name or len(name) > limit
            or any(ord(character) < 32 for character in name)
        ):
            raise _ObserveFailure(
                "observation_failed", f"target name must contain 1-{limit} characters."
            )
    return kind, name, surface, _text(args.get("query"), "query", 500)


def _resolve(
    scene: SceneSnapshot, kind: str, name: str, surface_id: str
) -> SceneTarget:
    try:
        target = SCENE.resolve_semantic(kind, name, surface_id)
    except SceneTargetNotFound as exc:
        raise _ObserveFailure("target_missing", "No current Shell target matched.") from exc
    except SceneTargetAmbiguous as exc:
        raise _ObserveFailure(
            "target_ambiguous", "The semantic target matched multiple Shell windows."
        ) from exc
    except SceneUnavailable as exc:
        raise _ObserveFailure("stale_scene", "The Shell scene changed.") from exc

    window = target.window
    if not window.stable_id:
        raise _ObserveFailure(
            "capture_unavailable", "The selected target has no capture identity."
        )
    surface = next(item for item in scene.surfaces if item.surface_id == target.surface_id)
    if (
        target.generation != scene.generation
        or target.surface_revision != surface.revision
        or window not in surface.windows
    ):
        raise _ObserveFailure(
            "stale_scene", "The Shell scene changed during target resolution."
        )
    return target


def _observe(args: dict[str, Any]) -> dict[str, object]:
    kind, name, surface_id, query = _request(args)
    try:
        scene = SCENE.snapshot()
    except SceneUnavailable as exc:
        raise _ObserveFailure(
            "scene_unavailable", "The current Shell scene is unavailable."
        ) from exc
    if scene.workspace.get("session_locked") is True:
        raise _ObserveFailure(
            "scene_unavailable", "The current Shell scene is locked."
        )

    target = _resolve(scene, kind, name, surface_id)
    if not target.surface_awake:
        raise _ObserveFailure(
            "target_not_visible", "The selected target's Surface is asleep."
        )
    start_time = None
    if target.window.window_kind == "application":
        try:
            start_time = process_start_time(target.window.pid)
            if type(start_time) is not int or start_time <= 0:
                raise GroundingError("Invalid process identity.")
        except GroundingError as exc:
            raise _ObserveFailure(
                "stale_scene", "The selected target process is unavailable."
            ) from exc
    try:
        capture = capture_screen(stable_id=target.window.stable_id)
    except ScreenCaptureError as exc:
        raise _ObserveFailure(
            "capture_unavailable", "The selected target could not be captured."
        ) from exc

    try:
        SCENE.validate(target)
        after = SCENE.snapshot()
        if start_time is not None and process_start_time(target.window.pid) != start_time:
            raise SceneTargetStale("The target process changed while it was captured.")
    except (SceneTargetStale, SceneUnavailable, GroundingError) as exc:
        raise _ObserveFailure(
            "stale_scene", "The Shell scene changed while it was captured."
        ) from exc
    if (
        after.workspace != scene.workspace
        or after.workspace.get("session_locked") is True
    ):
        raise _ObserveFailure(
            "stale_scene", "The Shell scene changed while it was captured."
        )

    public = {
        "status": "observed",
        "target": {
            "kind": target.window.semantic_kind,
            "name": target.window.semantic_name,
            "surface": target.surface_id,
        },
        "title": target.window.title[:200],
        "focused": target.active,
        "query": query,
        "visual_evidence": {
            "attached": True,
            "media_type": "image/png",
            "freshness": "validated_after_capture",
        },
        "action_authorized": False,
    }
    result = {"observation": public, PRIVATE_IMAGE_FIELD: capture.image_png}
    if start_time is not None:
        # The executor owns this single-use image lease. A late capture thread
        # must never write action state into its caller's mutable context.
        result[PRIVATE_OBSERVATION_FIELD] = {
            "target": target, "capture": capture, "process_start_time": start_time,
        }
    return result


def _failure(error: _ObserveFailure) -> dict[str, object]:
    return {
        "observation": {
            "status": "unavailable",
            "failure": {
                "code": error.code,
                "message": str(error),
                "retryable": error.code in {
                    "scene_unavailable",
                    "stale_scene",
                    "capture_unavailable",
                },
            },
            "action_authorized": False,
        }
    }


def execute(args: dict, context: dict) -> dict[str, object]:
    del context
    try:
        return _observe(args or {})
    except _ObserveFailure as error:
        return _failure(error)
    except Exception:
        return _failure(
            _ObserveFailure("observation_failed", "Screen observation failed.")
        )
