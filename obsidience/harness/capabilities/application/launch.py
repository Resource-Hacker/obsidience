"""Dispatch one registered application and observe readiness without replay."""
from __future__ import annotations

import json
import subprocess
import time

from obsidience.harness.computer.applications import APPLICATIONS
from obsidience.harness.host.scene import (
    SCENE, SceneTargetAmbiguous, SceneTargetNotFound, SceneUnavailable,
    SceneLocked, _semantic_title,
)

READINESS_TIMEOUT_SECONDS = 10.0


def _witness(target) -> dict:
    return {
        "title": _semantic_title(target.window.title),
        "app_id": target.window.app_id,
        "surface": target.surface_id,
        "focused": target.active,
        "visible": target.surface_awake and target.window.visible_on_workspace and not target.window.minimized,
    }


def _visible_application_window(application: str) -> dict | None:
    try:
        return _witness(SCENE.resolve_semantic("application", application))
    except (SceneUnavailable, SceneTargetNotFound, SceneTargetAmbiguous):
        return None


def _unit_is_active(unit: str | None) -> bool:
    if not unit:
        return False
    try:
        return subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", unit],
            timeout=5, check=False,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _await_readiness(result: dict, context: dict) -> dict:
    """Read the existing scene's events; this function never dispatches."""
    if result.get("ready") is True:
        return result
    deadline = time.monotonic() + READINESS_TIMEOUT_SECONDS
    cancel = context.get("_capability_cancel_event")
    token = SCENE.change_token()
    while True:
        if cancel is not None and cancel.is_set():
            return {**result, "wait_status": "cancelled", "must_not_replay": True}
        try:
            witness = _witness(SCENE.resolve_semantic("application", result["application"]))
            return {**result, "state": "ready", "ready": True, "window": witness,
                    "wait_status": "observed", "assistant_status": f"{result['label']} is open."}
        except (SceneLocked, SceneTargetAmbiguous) as exc:
            return {**result, "wait_status": "locked" if isinstance(exc, SceneLocked) else "ambiguous",
                    "must_not_replay": True}
        except (SceneUnavailable, SceneTargetNotFound):
            pass
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {**result, "wait_status": "timeout", "must_not_replay": True}
        # Scene changes wake immediately; the maximum wait bounds cancellation.
        token = SCENE.wait_for_change(token, min(remaining, 0.1))


def _launch_application(args: dict, context: dict | None = None) -> dict:
    context = context or {}
    cancel = context.get("_capability_cancel_event")
    if cancel is not None and cancel.is_set():
        raise ValueError("Launch cancelled before dispatch")
    application = str(args.get("application", "")).strip().lower()
    if set(args) - {"application"}:
        raise ValueError("application.launch accepts only the application field")
    spec = APPLICATIONS.get(application)
    if not spec:
        raise ValueError("application must be one of: " + ", ".join(sorted(APPLICATIONS)))
    witness = _visible_application_window(application)
    if witness:
        return {"application": application, "label": spec["label"], "state": "ready",
                "ready": True, "dispatched": False, "window": witness,
                "assistant_status": f"{spec['label']} is already open."}
    if _unit_is_active(spec.get("unit")):
        return _await_readiness({"application": application, "label": spec["label"],
            "state": "starting", "ready": False, "dispatched": False, "unit": spec.get("unit"),
            "assistant_status": f"{spec['label']} is already starting; readiness is not verified yet."}, context)

    # Ambiguity and session locking are not evidence that an application is absent.
    try:
        SCENE.resolve_semantic("application", application)
    except SceneLocked as exc:
        raise ValueError("The desktop is locked; nothing was dispatched") from exc
    except SceneTargetAmbiguous as exc:
        raise ValueError("Application target is ambiguous; nothing was dispatched") from exc
    except (SceneUnavailable, SceneTargetNotFound):
        pass
    else:
        return _await_readiness({"application": application, "label": spec["label"],
            "state": "starting", "ready": False, "dispatched": False}, context)
    if cancel is not None and cancel.is_set():
        raise ValueError("Launch cancelled before dispatch")
    result = subprocess.run(
        ["/home/wissenschafter/bin/agent-launch-gui", spec["desktop_id"]],
        capture_output=True, text=True, timeout=30, check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "managed launcher failed").strip()[:500]
        return {"application": application, "label": spec["label"], "state": "failed",
                "ready": False, "dispatched": False, "error": detail,
                "assistant_status": f"I could not start {spec['label']}: {detail}"}
    return _await_readiness({"application": application, "label": spec["label"],
        "desktop_id": spec["desktop_id"], "state": "starting", "ready": False,
        "dispatched": True, "window": None,
        "assistant_status": f"{spec['label']} is starting; readiness is not verified yet."}, context)


def execute(args: dict, context: dict) -> str:
    try:
        return json.dumps(_launch_application(args or {}, context), sort_keys=True)
    except subprocess.TimeoutExpired:
        return json.dumps({"state": "starting", "ready": False, "delivery": "uncertain",
            "wait_status": "launcher_timeout", "must_not_replay": True,
            "error": "Launcher outcome is uncertain; do not repeat the dispatch."})
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return f"Application launch rejected: {exc}."
