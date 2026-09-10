"""Capability seam for one current-shell grounded click."""
from __future__ import annotations

from obsidience.harness.computer.runtime import act_computer


def execute(args: dict, context: dict) -> dict:
    try:
        return act_computer(args or {}, context if context is not None else {})
    except Exception as exc:
        return {"status": "failed", "delivery": "not_dispatched", "must_not_replay": True,
                "failure": {"code": "click_precondition_failed", "message": str(exc)[:300]}}
