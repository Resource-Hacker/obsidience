"""Adapter for ``web.search``."""

from __future__ import annotations


def execute(args: dict, context: dict) -> str:
    del context
    from obsidience.harness.web.runtime import WebError, search_web

    args = args or {}
    try:
        result = search_web(args.get("query", ""), args.get("limit", 5))
    except WebError as exc:
        return f"Web search failed: {exc}"
    lines = [f"Web results for: {result['query']}"]
    for index, hit in enumerate(result["results"], 1):
        lines.extend((
            f"{index}. {hit['title']}",
            f"   URL: {hit['url']}",
            f"   {hit['description']}",
        ))
    return "\n".join(lines)
