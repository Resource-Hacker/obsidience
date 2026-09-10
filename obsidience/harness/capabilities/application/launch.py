"""Adapter for ``application.launch``."""

from __future__ import annotations

import json
import subprocess

from obsidience.harness.computer.applications import APPLICATIONS
from obsidience.harness.host.scene import (
    SCENE,
    SceneTargetAmbiguous,
    SceneTargetNotFound,
    SceneUnavailable,
    _semantic_title,
)


def _visible_application_window(application: str) -> dict | None:
    """Return one exact bounded Shell witness, never the first ambiguous match."""
    try:
        target = SCENE.resolve_semantic("application", application)
    except (SceneUnavailable, SceneTargetNotFound, SceneTargetAmbiguous):
        return None
    return {
        "title": _semantic_title(target.window.title),
        "app_id": target.window.app_id,
        "surface": target.surface_id,
        "focused": target.active,
        "visible": target.surface_awake and target.window.visible_on_workspace and not target.window.minimized,
    }


def _unit_is_active(unit: str | None) -> bool:
    if not unit:
        return False
    try:
        return subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", unit],
            timeout=5,
            check=False,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _launch_application(args: dict) -> dict:
    application = str(args.get("application", "")).strip().lower()
    if set(args) - {"application"}:
        raise ValueError("application.launch accepts only the application field")
    spec = APPLICATIONS.get(application)
    if not spec:
        raise ValueError(
            "application must be one of: " + ", ".join(sorted(APPLICATIONS))
        )

    witness = _visible_application_window(application)
    if witness:
        return {
            "application": application,
            "label": spec["label"],
            "state": "ready",
            "ready": True,
            "dispatched": False,
            "window": witness,
            "assistant_status": f"{spec['label']} is already open.",
        }
    if _unit_is_active(spec.get("unit")):
        return {
            "application": application,
            "label": spec["label"],
            "state": "starting",
            "ready": False,
            "dispatched": False,
            "unit": spec.get("unit"),
            "assistant_status": (
                f"{spec['label']} is already starting; readiness is not verified yet."
            ),
        }

    result = subprocess.run(
        ["/home/wissenschafter/bin/agent-launch-gui", spec["desktop_id"]],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "managed launcher failed").strip()[:500]
        return {
            "application": application,
            "label": spec["label"],
            "state": "failed",
            "ready": False,
            "dispatched": False,
            "error": detail,
            "assistant_status": f"I could not start {spec['label']}: {detail}",
        }

    witness = _visible_application_window(application)
    ready = witness is not None
    return {
        "application": application,
        "label": spec["label"],
        "desktop_id": spec["desktop_id"],
        "state": "ready" if ready else "starting",
        "ready": ready,
        "dispatched": True,
        "window": witness,
        "assistant_status": (
            f"{spec['label']} is open."
            if ready
            else f"{spec['label']} is starting; readiness is not verified yet."
        ),
    }


def execute(args: dict, context: dict) -> str:
    del context
    try:
        return json.dumps(_launch_application(args or {}), sort_keys=True)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return f"Application launch rejected: {exc}."
