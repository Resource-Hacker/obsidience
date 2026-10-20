"""The one client of the local SearXNG metasearch instance.

SearXNG runs unmodified as a loopback container
(``harness/systemd/obsidience-searxng.container``, ``[web] searxng_url``).
``web.search`` (``runtime.py``, with its DDGS fallback) and the TV's YouTube
listing consume ``search``; nothing else talks to SearXNG.
"""
from __future__ import annotations

import httpx

from ..config import CONFIG


def url() -> str:
    """The configured instance (``[web] searxng_url``), or "" when SearXNG is not configured."""
    return str((CONFIG.extras.get("web") or {}).get("searxng_url", "")).rstrip("/")


def search(query: str, **params):
    """The ``results`` value of one JSON search of the configured instance (its engines run in parallel).

    ``params`` add SearXNG search parameters such as ``engines`` or ``language``.
    Callers check ``url()`` first and validate the rows; transport and HTTP
    failures raise httpx errors, a malformed body ValueError or AttributeError.
    """
    response = httpx.get(
        url() + "/search", params={"q": query, "format": "json", "safesearch": 1, **params},
        # Loopback client identity for SearXNG's bot detection log.
        headers={"X-Real-IP": "127.0.0.1"}, timeout=httpx.Timeout(8.0, connect=1.0),
    )
    response.raise_for_status()
    return response.json().get("results")
