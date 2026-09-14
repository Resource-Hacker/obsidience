"""Dispatch one registered application and observe readiness without replay."""
from __future__ import annotations

import json
import re
import subprocess
import time

from obsidience.harness.computer.applications import APPLICATIONS
from obsidience.harness.host.scene import (
    SCENE, SceneTargetAmbiguous, SceneTargetNotFound, SceneUnavailable,
    SceneLocked, _semantic_title,
)

READINESS_TIMEOUT_SECONDS = 10.0


def _managed_unit(stdout: str, desktop_id: str) -> str | None:
    """Accept only the exact receipt emitted by the managed desktop launcher."""
    prefix = re.escape(desktop_id.removesuffix(".desktop")[:80])
    matches = re.findall(rf"^Transient unit: (agent-gui-{prefix}-[0-9]+-[0-9]+\.service)$",
                         stdout, re.MULTILINE)
    return matches[0] if len(matches) == 1 else None


def _launch_lifetime(unit: str | None) -> str:
    if not unit:
        return "unknown"
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show", unit, "--property=LoadState,ActiveState"],
            capture_output=True, text=True, timeout=1, check=False,
        )
        fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        # --collect may already have removed this exact, previously accepted unit.
        if fields.get("LoadState") == "not-found" or fields.get("ActiveState") in {"inactive", "failed"}:
            return "ended"
        if result.returncode == 0 and fields.get("ActiveState") in {"active", "activating", "reloading"}:
            return "running"
    except (OSError, subprocess.SubprocessError):
        pass
    return "unknown"


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


def _await_readiness(result: dict, context: dict, *, launch_unit: str | None = None) -> dict:
    """Read the existing scene's events; this function never dispatches."""
    if result.get("ready") is True:
        return result
    deadline = time.monotonic() + READINESS_TIMEOUT_SECONDS
    cancel = context.get("_capability_cancel_event")
    token = SCENE.change_token()
    next_lifetime_check = 0.0
    lifetime = "unknown"
    while True:
        if cancel is not None and cancel.is_set():
            return {**result, "wait_status": "cancelled", "must_not_replay": True}
        try:
            witness = _witness(SCENE.resolve_semantic("application", result["application"]))
            return {**result, "state": "ready", "ready": True, "window": witness,
                    "wait_status": "observed", "assistant_status": f"{result['label']} is open."}
        except (SceneLocked, SceneTargetAmbiguous) as exc:
            return {**result, "state": "unverified", "wait_status": "locked" if isinstance(exc, SceneLocked) else "ambiguous",
                    "must_not_replay": True}
        except (SceneUnavailable, SceneTargetNotFound):
            pass
        now = time.monotonic()
        if launch_unit and now >= next_lifetime_check:
            lifetime = _launch_lifetime(launch_unit)
            next_lifetime_check = time.monotonic() + 0.5
            if lifetime == "ended":
                return {**result, "state": "failed", "launch_lifetime": lifetime,
                        "wait_status": "terminated_before_ready", "must_not_replay": True,
                        "assistant_status": f"The managed launch for {result['label']} ended before a ready window was observed. It is not verified open; do not describe it as still loading."}
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {**result, "state": "unverified", "launch_lifetime": lifetime,
                    "wait_status": "timeout", "must_not_replay": True,
                    "assistant_status": f"No ready {result['label']} window was observed before the deadline. Its loading state is unknown; do not claim it is still loading."}
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
        "assistant_status": f"{spec['label']} was dispatched; readiness is not verified yet."}, context,
        launch_unit=_managed_unit(result.stdout, spec["desktop_id"]))


def execute(args: dict, context: dict) -> str:
    try:
        return json.dumps(_launch_application(args or {}, context), sort_keys=True)
    except subprocess.TimeoutExpired:
        application = str((args or {}).get("application", "")).strip().lower()
        return json.dumps({"application": application, "state": "unverified", "ready": False, "delivery": "uncertain",
            "wait_status": "launcher_timeout", "must_not_replay": True,
            "error": "Launcher outcome is uncertain; do not repeat the dispatch."})
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return f"Application launch rejected: {exc}."
