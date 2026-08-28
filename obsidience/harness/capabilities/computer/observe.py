"""Adapter for ``computer.observe``."""

from __future__ import annotations

import json


def execute(args: dict, context: dict) -> str:
    del context
    from obsidience.harness.computer.runtime import ComputerError, observe_computer

    try:
        result = observe_computer(args or {})
    except (ComputerError, OSError, TimeoutError, json.JSONDecodeError) as exc:
        return f"Computer use rejected: {exc}."
    return json.dumps(result, sort_keys=True)
