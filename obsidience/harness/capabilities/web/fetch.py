"""Adapter for ``web.fetch``."""

from __future__ import annotations

import httpx


def execute(args: dict, context: dict) -> str:
    from obsidience.harness.web.runtime import WebError, fetch_web

    params = context.get("params") if isinstance(context.get("params"), dict) else {}
    activation_key = (
        str(params.get("activation_key"))
        if context.get("event") == "source.added"
        and str(params.get("activation_key", "")).startswith("source.added:")
        else None
    )
    try:
        result = fetch_web((args or {}).get("url", ""), activation_key=activation_key)
    except (WebError, httpx.HTTPError) as exc:
        return f"Web fetch failed: {exc}"
    return (
        f"Fetched and {'captured' if result['created'] else 'verified'} {result['url']} as "
        f"{result['citation']} ({result['content_sha256']}).\n\n"
        f"{result['content'][:12_000]}"
    )
