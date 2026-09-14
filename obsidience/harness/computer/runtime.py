"""One model-selected image point through the current Shell command owner."""
from __future__ import annotations

import secrets
import time
from dataclasses import asdict, fields, replace
from typing import Any

from obsidience.harness.capabilities.window.command import (
    COMMAND_SCHEMA, EffectNotObserved, ShellCommandUnavailable, _send_command, activate,
)
from obsidience.harness.host.scene import SCENE, SceneTarget
from .applications import canonical_application_id
from .capture import ScreenCapture, _png_size, capture_screen
from .grounding import process_start_time

MAX_IMAGE_AGE_NS = 10_000_000_000
MAX_STATE_ACTIONS = 3


class ComputerError(ValueError):
    pass


def _text(value: object, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or any(ord(c) < 32 for c in value):
        raise ComputerError(f"{field} must contain 1-{limit} characters.")
    return " ".join(value.split())


def _check_cancel(context: dict) -> None:
    event = context.get("_capability_cancel_event")
    if event is not None and event.is_set():
        raise ComputerError("The action was cancelled before input delivery.")


def _validate(target, start_time: int, context: dict):
    _check_cancel(context)
    scene = SCENE.snapshot()
    if scene.workspace.get("session_locked") is True:
        raise ComputerError("The desktop is locked.")
    current = SCENE.validate(target)
    if not current.surface_awake or current.window.minimized or not current.window.visible_on_workspace:
        raise ComputerError("The selected target is not visible on an awake Surface.")
    if process_start_time(current.window.pid) != start_time:
        raise ComputerError("The target process changed.")
    return current


def act_computer(args: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    # Only the executor can supply the observation paired with the immediately
    # preceding model input. Consume it even if argument validation fails.
    lease = context.pop("_computer_observation_lease", None)
    scope = args.get("scope", context.get("params", {}).get("computer_scope"))
    if scope not in {"input", "state"}:
        raise ComputerError("scope must be input for a requested click or state for an application result.")
    previous_scope = context.setdefault("_computer_act_scope", scope)
    if scope != previous_scope:
        raise ComputerError("The action scope cannot change after the first attempt.")
    state_scope = scope == "state"
    attempts = context.get("_computer_act_attempts", 0)
    if attempts and (not state_scope or not context.get("_computer_act_step_observed")):
        raise ComputerError("This Task cannot send another action after consumed or unverified input; do not replay it.")
    if attempts >= (MAX_STATE_ACTIONS if state_scope else 1):
        raise ComputerError("This Task reached its bounded computer action limit.")
    context["_computer_act_attempts"] = attempts + 1
    context["_computer_act_step_observed"] = False
    if set(args) - {"scope", "application", "action", "target", "point", "postcondition"} or args.get("action", "click") != "click":
        raise ComputerError("computer.act accepts one click with scope, application, target, image point and optional postcondition.")
    application = _text(args.get("application"), "application", 256)
    application = canonical_application_id(application) or application
    label = _text(args.get("target"), "target", 128)
    postcondition = _text(args.get("postcondition", label), "postcondition", 500)
    point = args.get("point")
    if (not isinstance(point, dict) or set(point) != {"x", "y"}
            or any(type(point[axis]) is not int or not 0 <= point[axis] <= 999 for axis in ("x", "y"))):
        raise ComputerError("point requires integer x and y in 0-999 on the immediately observed image.")
    if not isinstance(lease, dict):
        raise ComputerError("A fresh computer.observe image must immediately precede this action.")
    target, capture, start = (lease.get(key) for key in ("target", "capture", "process_start_time"))
    if (not isinstance(target, SceneTarget) or not isinstance(capture, ScreenCapture)
            or target.window.window_kind != "application" or type(start) is not int or start <= 0):
        raise ComputerError("The private observation lease is invalid.")
    if (capture.target_kind != "toplevel" or capture.target != target.window.stable_id
            or not isinstance(capture.image_png, bytes)
            or _png_size(capture.image_png) != (capture.width, capture.height)):
        raise ComputerError("The image does not match the observed target.")
    if not 0 <= time.time_ns() - capture.captured_at_unix_ns <= MAX_IMAGE_AGE_NS:
        raise ComputerError("The observed image expired before this action.")
    if attempts and capture.captured_at_unix_ns <= context.get("_computer_act_post_capture_ns", 0):
        raise ComputerError("A new observation after the previous action is required for the next step.")
    _check_cancel(context)
    resolved = SCENE.resolve_semantic("application", application, "")
    if resolved != target:
        # A resized window needs a new image and a new model-selected point.
        # This edge precedes activation and input, so one fresh observation is
        # safe; the old point is never dispatched or replayed.
        same_window = replace(target.window, local_rect=resolved.window.local_rect)
        if (attempts == 0 and not context.get("_computer_geometry_refreshes")
                and resolved.window.local_rect != target.window.local_rect
                and resolved == replace(target, window=same_window,
                                        surface_revision=resolved.surface_revision)):
            _validate(resolved, start, context)
            context["_computer_geometry_refreshes"] = 1
            context["_computer_act_attempts"] = 0
            return {
                "status": "failed", "delivery": "not_dispatched", "must_not_replay": True,
                "correction_allowed": True,
                "failure": {"code": "geometry_changed_before_input",
                            "message": "The same window moved or resized before any input. Observe it again and choose a new point from that fresh image once; never reuse the old point."},
            }
        changed = [field.name for field in fields(target)
                   if getattr(target, field.name) != getattr(resolved, field.name)]
        if "window" in changed:
            changed.remove("window")
            changed.extend("window." + field.name for field in fields(target.window)
                           if getattr(target.window, field.name) != getattr(resolved.window, field.name))
        raise ComputerError("The requested application no longer matches the observed target: "
                            + ", ".join(changed) + ".")
    _validate(target, start, context)
    if not target.active:
        # Foreground delivery uses the existing exact activation command owner.
        focused = activate({"target": {"kind": "application", "name": application}})
        if focused.get("status") != "completed":
            raise ComputerError("The exact application could not be activated; no click was sent.")
        previous = target
        target = SCENE.resolve_semantic("application", application, "")
        if (target.generation != previous.generation or target.window.window_id != previous.window.window_id
                or target.surface_id != previous.surface_id or target.window != previous.window):
            raise ComputerError("The application changed during foreground activation.")
    target = _validate(target, start, context)
    witness = {
        "stable_id": target.window.stable_id, "pid": target.window.pid,
        "process_start_time": start, "local_rect": asdict(target.window.local_rect),
        "image_width": capture.width, "image_height": capture.height,
        "x": point["x"] * capture.width / 1000,
        "y": point["y"] * capture.height / 1000,
        "captured_at_unix_ns": capture.captured_at_unix_ns,
        "label": label,
    }
    public_target = {"kind": "application", "name": application, "surface": target.surface_id}
    result = {
        "status": "failed", "target": public_target, "must_not_replay": True,
        "requested_postcondition": postcondition, "semantic_postcondition_verified": False,
    }
    try:
        receipt = _send_command({
            "schema": COMMAND_SCHEMA, "type": "window.click", "token": "click." + secrets.token_hex(16),
            "surface_id": target.surface_id, "window_id": target.window.window_id,
            "expected_revision": target.surface_revision, "witness": witness,
        }, "window.click.result", timeout=6.0, cancel_event=context.get("_capability_cancel_event"))
    except ShellCommandUnavailable:
        return result | {"delivery": "not_dispatched", "failure": "The Shell command connection is unavailable."}
    except EffectNotObserved:
        return result | {"delivery": "uncertain", "failure": "The click receipt was lost or cancelled; do not repeat it."}
    if receipt.get("success") is not True or receipt.get("delivery") != "acknowledged":
        return result | {
            "delivery": receipt.get("delivery", "uncertain"),
            "failure": str(receipt.get("reason", "Input delivery was not acknowledged."))[:200],
        }
    result["delivery"] = "acknowledged"
    result["effect"] = {"kind": "click", "label": label, "verified": True,
                        "targeting": "model_vision", "semantic_target_verified": False}
    try:
        # An acknowledged click may legitimately change title, focus or layout.
        # Rebind observation only to that same process/window, then validate the
        # new capture lease. This result never grants an action lease: another
        # state step still requires a separate, later computer.observe image.
        post_target = SCENE.resolve_semantic("application", application, target.surface_id)
        if (post_target.generation != target.generation
                or post_target.surface_id != target.surface_id
                or any(getattr(post_target.window, key) != getattr(target.window, key)
                       for key in ("window_id", "stable_id", "pid", "app_id", "window_kind"))):
            raise ComputerError("The clicked application identity changed.")
        _validate(post_target, start, context)
        post = capture_screen(stable_id=post_target.window.stable_id)
        _validate(post_target, start, context)
        if post.captured_at_unix_ns <= capture.captured_at_unix_ns:
            raise ComputerError("The post-action capture is not fresh.")
    except Exception:
        return result | {"failure": "The click was delivered, but a fresh exact post-observation is unavailable."}
    context["_computer_act_step_observed"] = True
    context["_computer_act_post_capture_ns"] = post.captured_at_unix_ns
    return result | {
        "status": "completed", "verified_scope": "click",
        "observation": {
            "status": "observed", "target": public_target, "query": postcondition,
            "visual_evidence": {"attached": True, "media_type": "image/png", "freshness": "validated_after_capture"},
            "action_authorized": False,
        },
        "interpretation": (
            "One click at your selected image point was delivered. The target label is your description, not independent recognition. "
            + ("Evaluate the fresh attached image before claiming the requested application state."
               if state_scope else
               "This Task requests input only. If you selected the intended control, complete the click Task successfully and describe the fresh post-image separately. An unchanged screen does not make acknowledged input fail; signing in or starting a match is not this Task's goal.")
        ),
        "_private_image_png": post.image_png,
    }
