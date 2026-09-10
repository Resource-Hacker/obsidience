"""Capability seam for ``window.activate``."""

from __future__ import annotations

import json

from .command import activate


def execute(args: dict, context: dict) -> str:
    del context
    return json.dumps(activate(args or {}), sort_keys=True)
