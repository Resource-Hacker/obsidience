"""Explicit, read-only connection tests. Never captures API data into Source."""

from urllib.parse import urljoin, urlsplit
import threading
import time

import feedparser
import httpx

from ..web.runtime import MAX_REDIRECTS, _public_url
from ..web.feeds import download_feed
from .credentials import origin


def check_connection(connection: dict, headers: dict[str, str], cancel_event: threading.Event | None = None) -> None:
    url = _public_url(connection["url"])
    if headers and urlsplit(url).scheme != "https":
        raise ValueError("Authenticated connections require HTTPS")
    if connection["kind"] == "rss":
        parsed_url = urlsplit(url)
        response = download_feed(url, headers=headers, cancel_event=cancel_event,
                                 expected_origin=(parsed_url.scheme, parsed_url.hostname,
                                     parsed_url.port or (443 if parsed_url.scheme == "https" else 80)))
        parsed = feedparser.parse(response["material"])
        if not parsed.version or parsed.bozo:
            raise ValueError("The endpoint did not return a readable RSS or Atom feed")
        return
    deadline = time.monotonic() + 45
    with httpx.Client(trust_env=False, follow_redirects=False,
                      timeout=httpx.Timeout(15, connect=8)) as client:
        for attempt in range(MAX_REDIRECTS + 1):
            if time.monotonic() > deadline or (cancel_event is not None and cancel_event.is_set()):
                raise ValueError("Connection check ended before the endpoint responded")
            with client.stream("GET", url, headers={
                "User-Agent": "Obsidience/Connections", **headers,
            }) as response:
                if response.is_redirect:
                    if attempt == MAX_REDIRECTS:
                        raise ValueError("The endpoint redirected too many times")
                    target = _public_url(urljoin(url, response.headers.get("location", "")),
                                         previous_scheme=urlsplit(url).scheme)
                    if headers and origin(target) != origin(url):
                        raise ValueError("An authenticated redirect to another provider was refused")
                    url = target
                    continue
                if not 200 <= response.status_code < 300:
                    raise ValueError(f"The endpoint returned HTTP {response.status_code}")
                # An API check only attests HTTP access at the configured URL.
                # Do not read account details or turn connectivity into data ingestion.
                return
