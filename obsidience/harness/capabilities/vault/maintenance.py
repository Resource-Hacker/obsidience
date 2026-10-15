"""Adapter for ``vault.maintenance``."""

from __future__ import annotations

import json

from obsidience.harness.knowledge.maintenance import maintenance_candidates


def execute(args: dict, context: dict) -> str:
    del args
    if context.get("event") == "observations.memory.ready":
        return ("Maintenance rejected: this Curate activation is bound to one Hindsight mental-model page. "
                "Search and read ordinary Knowledge for that page, then recommend content "
                "or report an evidenced no-change result. "
                "General maintenance belongs to a manual or scheduled activation.")
    try:
        return json.dumps(maintenance_candidates(context), sort_keys=True)
    except PermissionError as exc:
        return str(exc)
