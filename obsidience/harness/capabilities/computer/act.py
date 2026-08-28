"""Adapter for ``computer.act``."""

from __future__ import annotations

import json


def execute(args: dict, context: dict) -> str:
    from obsidience.harness.computer.runtime import ComputerError, act_computer

    try:
        result = act_computer(args or {}, context or {})
    except (ComputerError, OSError, TimeoutError, json.JSONDecodeError) as exc:
        return f"Computer use rejected: {exc}."
    return json.dumps(result, sort_keys=True)
