"""Observe one exact Shell-scene target without changing focus."""

from __future__ import annotations

import re
import time
from dataclasses import replace
from typing import Any

from obsidience.harness.computer.applications import APPLICATIONS
from obsidience.harness.computer.capture import (
    ScreenCaptureError,
    capture_screen,
)
from obsidience.harness.computer.grounding import GroundingError, process_start_time
from obsidience.harness.host.scene import (
    HANDLE,
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
_TARGET_KINDS = {"focused", "attention", "application", "pane"}
# Until a navigation commits its document title, the browser window title is
# the bare URL (e.g. "youtube.com/results?search_query=..."). A capture then
# shows a blank page and costs a second observation round. A new tab is
# briefly "Untitled" before that URL appears.
PAGE_TITLE_WAIT_SECONDS = 5.0
_LOADING_TITLE = re.compile(
    r"(?:(?:https?://)?(?:[a-z0-9-]+\.)+[a-z]{2,}/\S*(?:\s|$)|Untitled(?: and \d+ more pages?)? - )",
    re.IGNORECASE)


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


def _request(args: dict[str, Any]) -> tuple[str, str, str, str, str]:
    # An omitted target is what the owner is looking at now.
    target = args.get("target", {"kind": "attention"})
    if "query" not in args or set(args) - {"target", "query"} or not isinstance(target, dict):
        raise _ObserveFailure(
            "observation_failed", "computer.observe requires query and an optional target."
        )
    if set(target) - {"kind", "name", "surface", "title", "handle"}:
        raise _ObserveFailure(
            "observation_failed", "computer.observe received an unknown target field."
        )
    query = _text(args.get("query"), "query", 500)
    if "handle" in target:
        handle = target["handle"]
        if set(target) != {"handle"} or not isinstance(handle, str) or HANDLE.fullmatch(handle) is None:
            raise _ObserveFailure(
                "observation_failed", "A handle target is exactly {handle: <w-number from the Scene>}."
            )
        return "handle", handle, "", query, ""
    kind = target.get("kind")
    if kind not in _TARGET_KINDS:
        raise _ObserveFailure(
            "observation_failed", "target kind must be attention, focused, application, or pane."
        )
    title = target.get("title", "")
    if "title" in target and (
        kind != "application" or not isinstance(title, str) or not title
        or len(title) > 200 or any(ord(char) < 32 for char in title)
    ):
        raise _ObserveFailure("observation_failed", "title must be an exact current application title from the Scene.")
    surface = target.get("surface", "")
    if surface and surface not in SURFACE_IDS:
        raise _ObserveFailure("observation_failed", "target Surface is unknown.")
    if not isinstance(surface, str):
        raise _ObserveFailure("observation_failed", "target Surface is invalid.")

    if kind in {"focused", "attention"}:
        if "name" in target:
            raise _ObserveFailure(
                "observation_failed", f"a {kind} target must omit name."
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
    return kind, name, surface, query, title


def _resolve(
    scene: SceneSnapshot, kind: str, name: str, surface_id: str, title: str = ""
) -> SceneTarget:
    try:
        target = SCENE.resolve_semantic(kind, name, surface_id, title=title, prefer_active=True)
    except SceneTargetNotFound as exc:
        raise _ObserveFailure(
            "target_missing",
            "That handle no longer exists; use a handle from the current Scene."
            if kind == "handle" else
            "No visible recently focused application window exists." if kind in {"focused", "attention"}
            else "No current Shell target matched.",
        ) from exc
    except SceneTargetAmbiguous as exc:
        candidates = getattr(exc, "candidates", [])
        raise _ObserveFailure(
            "target_ambiguous",
            "The target matched multiple Shell windows"
            + (": " + "; ".join(candidates) if candidates else "")
            + ". For what the owner is viewing now, omit the target; to read one of these"
            " windows, repeat with target {handle: <its handle>}.",
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


def _await_page_title(kind: str, name: str, surface_id: str, title: str, cancel=None) -> None:
    """Briefly let a browser commit its navigated page before capture."""
    if kind == "pane" or title:
        return
    deadline = time.monotonic() + PAGE_TITLE_WAIT_SECONDS
    token = SCENE.change_token()
    while cancel is None or not cancel.is_set():
        try:
            window = SCENE.resolve_semantic(kind, name, surface_id, prefer_active=True).window
        except (SceneTargetNotFound, SceneTargetAmbiguous, SceneUnavailable):
            return
        # Resolution also accepts aliases and app IDs; gate on the window found.
        if not APPLICATIONS.get(window.semantic_name, {}).get("accepts_web_url"):
            return
        remaining = deadline - time.monotonic()
        if not _LOADING_TITLE.match(window.title) or remaining <= 0:
            return
        # Title changes publish a new scene; the short wait bounds cancellation.
        token = SCENE.wait_for_change(token, min(remaining, 0.25))


def _observe(args: dict[str, Any], cancel=None) -> dict[str, object]:
    kind, name, surface_id, query, title = _request(args)
    _await_page_title(kind, name, surface_id, title, cancel)
    try:
        scene = SCENE.refresh(cancel_event=cancel)
    except SceneUnavailable as exc:
        raise _ObserveFailure(
            "scene_unavailable", "The current Shell scene is unavailable."
        ) from exc
    except SceneTargetStale as exc:
        # A Shell reconnect during refresh: retry once, as for other stale scenes.
        raise _ObserveFailure("stale_scene", "The Shell scene changed.") from exc
    if scene.workspace.get("session_locked") is True:
        raise _ObserveFailure(
            "scene_unavailable", "The current Shell scene is locked."
        )

    target = _resolve(scene, kind, name, surface_id, title)
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
        if exc.code == "capture_session_unavailable":
            raise _ObserveFailure(
                exc.code,
                "The Harness is not attached to the graphical session. "
                "Restart the Harness after desktop startup; retrying other windows will not help.",
            ) from exc
        raise _ObserveFailure(
            "capture_unavailable", "The selected target could not be captured."
        ) from exc

    try:
        SCENE.refresh(cancel_event=cancel)
        current = SCENE.resolve(window_id=target.window.window_id, surface_id=target.surface_id)
        # Another window can advance the Surface revision. Only rebind that
        # revision after every field of this exact captured target still matches.
        if current != replace(target, surface_revision=current.surface_revision):
            raise SceneTargetStale("The captured target changed.")
        target = current
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
                    # Its message lists the candidate handles.
                    "target_ambiguous",
                },
            },
            "action_authorized": False,
        }
    }


def execute(args: dict, context: dict) -> dict[str, object]:
    cancel = (context or {}).get("_capability_cancel_event")
    for attempt in range(2):
        if cancel is not None and cancel.is_set():
            return _failure(_ObserveFailure("cancelled", "Screen observation cancelled."))
        try:
            return _observe(args or {}, cancel)
        except _ObserveFailure as error:
            if error.code == "stale_scene" and attempt == 0:
                # Discard the stale image and resolve/capture/validate afresh.
                # This retries only observation; it never replays input.
                continue
            return _failure(error)
        except Exception:
            return _failure(
                _ObserveFailure("observation_failed", "Screen observation failed.")
            )
