"""Adapter for ``web.fetch``; one URL or one bounded batch of independent URLs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json

import httpx


MAX_FETCH_PREVIEW_CHARS = 6_000
MAX_FETCH_BATCH_URLS = 10
MAX_FETCH_BATCH_WORKERS = 4
MAX_FETCH_BATCH_OUTPUT_CHARS = 60_000


def _render_result(result: dict, *, preview_chars: int = MAX_FETCH_PREVIEW_CHARS) -> str:
    content = str(result["content"])
    citation = str(result["citation"])
    end = min(preview_chars, len(content))
    if end < len(content):
        remaining = len(content) - end
        page_status = (
            f"Unread tail: {remaining} characters. Use facts visible in this page with its "
            f"citation. Read more with source.read using source {citation} and offset {end} "
            "only when a needed claim or detail is absent; the unread tail is optional and "
            "has not been inspected."
        )
    else:
        page_status = "End of Source."
    return (
        f"Fetched and {'captured' if result['created'] else 'verified'} {result['url']} as "
        f"{citation} ({result['content_sha256']}).\n\n"
        f"Characters 0-{end} of {len(content)}. {page_status}\n\n"
        f"{content[:end]}"
    )


def _render_batch(urls: list[str], results: list[dict | str]) -> str:
    def render(preview_chars: int) -> str:
        return json.dumps({"results": [
            {"url": url, "ok": isinstance(result, dict), "result": (
                _render_result(result, preview_chars=preview_chars)
                if isinstance(result, dict) else result
            )}
            for url, result in zip(urls, results, strict=True)
        ]}, ensure_ascii=False, separators=(",", ":"))

    rendered = render(MAX_FETCH_PREVIEW_CHARS)
    if len(rendered) <= MAX_FETCH_BATCH_OUTPUT_CHARS:
        return rendered
    # Bound the encoded envelope as well as each actual Source range. JSON
    # escaping and URLs consume budget too; never truncate serialized metadata
    # or report a range containing evidence that was not actually returned.
    low, high = 0, MAX_FETCH_PREVIEW_CHARS
    rendered = render(0)
    while low < high:
        middle = (low + high + 1) // 2
        candidate = render(middle)
        if len(candidate) <= MAX_FETCH_BATCH_OUTPUT_CHARS:
            low, rendered = middle, candidate
        else:
            high = middle - 1
    return rendered


def _arguments(args: object) -> tuple[list[str], bool]:
    from obsidience.harness.web.runtime import WebError, validate_fetch_url

    if not isinstance(args, dict) or set(args) not in ({"url"}, {"urls"}):
        raise WebError("pass exactly one of url or urls")
    batch = "urls" in args
    values = args["urls"] if batch else [args["url"]]
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_FETCH_BATCH_URLS:
        raise WebError("urls must contain between 1 and 10 public URLs")
    urls = [validate_fetch_url(value) for value in values]
    if len(set(urls)) != len(urls):
        raise WebError("urls must be unique; fragments do not identify a separate page")
    return urls, batch


def execute(args: dict, context: dict) -> str:
    from obsidience.harness.web.runtime import WebError, fetch_web
    from obsidience.harness.knowledge.source import SourceError, research_activation_key

    try:
        urls, batch = _arguments(args)
    except WebError as exc:
        return f"Web fetch failed: {exc}"
    activation_key = research_activation_key(context)
    cancel_event = context.get("_capability_cancel_event")

    def acquire(url: str) -> dict | str:
        try:
            return fetch_web(url, activation_key=activation_key, cancel_event=cancel_event)
        except (WebError, SourceError, httpx.HTTPError) as exc:
            return f"Web fetch failed for {url}: {str(exc)[:256]}"

    if not batch:
        result = acquire(urls[0])
        return result if isinstance(result, str) else _render_result(result)

    # The context manager joins every worker before the Tool returns. STOP is
    # passed through the existing capability event to queued and active fetches;
    # no detached worker or additional acquisition owner outlives this batch.
    with ThreadPoolExecutor(max_workers=min(MAX_FETCH_BATCH_WORKERS, len(urls))) as pool:
        results = list(pool.map(acquire, urls))
    return _render_batch(urls, results)
