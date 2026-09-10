"""Adapter for ``web.feed``."""

from __future__ import annotations

import httpx


def execute(args: dict, context: dict) -> str:
    from obsidience.harness.knowledge.source import SourceError, research_activation_key
    from obsidience.harness.web.feeds import fetch_feed
    from obsidience.harness.web.runtime import WebError

    args = args or {}
    try:
        result = fetch_feed(
            args.get("url", ""),
            args.get("limit", 20),
            activation_key=research_activation_key(context),
        )
    except (SourceError, WebError, httpx.HTTPError) as exc:
        return f"Web feed failed: {exc}"

    state = "captured" if result["created"] else "verified"
    lines = [
        (
            f"Feed {state}: {result['url']} as {result['citation']} "
            f"({result['content_sha256']})."
        ),
        (
            "The citation attests this feed snapshot only; entries remain "
            "discovery leads, not story evidence."
        ),
    ]
    if result["feed_title"]:
        lines.append(f"Feed title: {result['feed_title']}")
    for index, entry in enumerate(result["entries"], 1):
        lines.append(f"{index}. {entry['title']}")
        lines.append(f"   URL: {entry['url']}")
        if entry["published"]:
            lines.append(f"   Published: {entry['published']}")
        if entry["summary"]:
            lines.append(f"   Summary: {entry['summary']}")
    return "\n".join(lines)
