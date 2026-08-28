"""Adapter for ``application.launch``."""

from __future__ import annotations

import json
import subprocess

from obsidience.harness.computer.applications import APPLICATIONS


def _visible_application_window(spec: dict) -> dict | None:
    """Return one current compositor witness, or no witness if observation is unavailable."""
    command = "/var/lib/ai/opt/computer-use-linux-0.4.2/computer-use-linux"
    try:
        result = subprocess.run(
            [command, "windows"], capture_output=True, text=True, timeout=8, check=False,
        )
        payload = json.loads(result.stdout) if result.returncode == 0 else {}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    needles = tuple(str(value).casefold() for value in spec["window_needles"])
    for window in payload.get("windows", []):
        haystack = " ".join(
            str(window.get(field, "")) for field in ("title", "app_id", "wm_class")
        ).casefold()
        if any(needle in haystack for needle in needles):
            return {
                "title": str(window.get("title", ""))[:240],
                "app_id": str(window.get("app_id", ""))[:120],
                "pid": window.get("pid"),
                "window_id": window.get("window_id"),
            }
    return None


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

    witness = _visible_application_window(spec)
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

    witness = _visible_application_window(spec)
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
