"""Release the active session lock through its sole native owner."""

from __future__ import annotations

import json
import subprocess

from ...config import CONFIG


def execute(args: dict, context: dict) -> str:
    if args:
        raise ValueError("session.unlock accepts an empty argument object")
    if (context.get("_agent_ref") != "Agents/Executive/Executive"
            or context.get("task") != "Agents/Executive/Executive"):
        raise PermissionError("Session unlock belongs to the Executive conversation")
    cancel = context.get("_capability_cancel_event")
    if cancel is not None and cancel.is_set():
        raise PermissionError("Session unlock was cancelled before dispatch")
    try:
        result = subprocess.run(
            [str(CONFIG.product_root / "shell/session/session-lock"), "unlock"],
            capture_output=True, text=True, timeout=12, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        uncertain = isinstance(exc, subprocess.TimeoutExpired)
        return json.dumps({"status": "failed", "failure": {"code": "lock_command_unavailable"},
            "effect_applied": None if uncertain else False,
            "delivery": "uncertain" if uncertain else "not_dispatched", "must_not_replay": True})
    try:
        response = json.loads(result.stdout)
        if (not isinstance(response, dict) or response.get("must_not_replay") is not True
                or (response.get("status") == "completed"
                    and (result.returncode != 0 or response.get("locked") is not False))):
            raise ValueError("Invalid native unlock receipt")
    except (ValueError, TypeError):
        response = {"status": "failed", "failure": {"code": "unlock_delivery_uncertain"},
            "effect_applied": None, "delivery": "uncertain", "must_not_replay": True}
    return json.dumps(response, sort_keys=True)
