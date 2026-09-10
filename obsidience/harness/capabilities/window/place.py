"""Capability seam for ``window.place``."""

from __future__ import annotations

import json

from .command import place


def execute(args: dict, context: dict) -> str:
    del context
    return json.dumps(place(args or {}), sort_keys=True)
