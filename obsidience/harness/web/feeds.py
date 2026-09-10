"""Bounded RSS and Atom acquisition with immutable Source capture."""

from __future__ import annotations

import calendar
import json
import re
import threading
import time
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import feedparser
import httpx

from ..knowledge.source import ingest_source
from .runtime import (
    MAX_REDIRECTS,
    MAX_RESPONSE_BYTES,
    WebError,
    _public_url,
    _ReadableHTML,
    _check_cancelled,
    validate_fetch_url,
)

MAX_FEED_ENTRIES = 30
MAX_ENTRY_TITLE_CHARS = 300
MAX_ENTRY_SUMMARY_CHARS = 400
_FEED_MEDIA_TYPES = {
    "application/atom+xml",
    "application/rss+xml",
    "application/xml",
    "text/xml",
}
_TRACKING_QUERY_KEYS = {
    "dclid",
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "msclkid",
}
def _plain_text(value: object, maximum: int) -> str:
    parser = _ReadableHTML()
    parser.feed(str(value or ""))
    parser.close()
    return re.sub(r"\s+", " ", parser.markdown()).strip()[:maximum]


def canonical_url(value: object) -> str:
    """Normalize one already-validated URL without network I/O."""
    parsed = urlsplit(str(value))
    publisher = (parsed.hostname or "").lower()
    publisher_tracking = set()
    if any(publisher == host or publisher.endswith("." + host) for host in ("bbc.co.uk", "bbc.com")):
        publisher_tracking = {"at_campaign", "at_medium"}
    elif publisher == "dw.com" or publisher.endswith(".dw.com"):
        publisher_tracking = {"maca"}
    query = urlencode(
        sorted(
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_")
            and key.lower() not in _TRACKING_QUERY_KEYS
            and key.lower() not in publisher_tracking
        ),
        doseq=True,
    )
    host = parsed.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    port = parsed.port
    if port and not (
        (parsed.scheme == "http" and port == 80)
        or (parsed.scheme == "https" and port == 443)
    ):
        host = f"{host}:{port}"
    return urlunsplit((parsed.scheme.lower(), host.lower(), parsed.path or "/", query, ""))


def _canonical_entry_url(value: object, feed_url: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise WebError("feed entry has no direct URL")
    return canonical_url(_public_url(urljoin(feed_url, raw)))


def _published_utc(entry: dict) -> str | None:
    for field in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = entry.get(field)
        if parsed is None:
            continue
        try:
            moment = datetime.fromtimestamp(calendar.timegm(parsed), UTC)
        except (OverflowError, TypeError, ValueError):
            continue
        return moment.isoformat(timespec="seconds").replace("+00:00", "Z")
    return None


def _entry_summary(entry: dict) -> str:
    value = entry.get("summary") or entry.get("description")
    if not value:
        content = entry.get("content")
        if isinstance(content, list) and content and isinstance(content[0], dict):
            value = content[0].get("value")
    return _plain_text(value, MAX_ENTRY_SUMMARY_CHARS)


def _parse_entries(material: bytes, feed_url: str, limit: int) -> tuple[str, list[dict]]:
    parsed = feedparser.parse(
        material,
        resolve_relative_uris=False,
        sanitize_html=False,
    )
    if parsed.get("bozo"):
        raise WebError("RSS or Atom feed XML is malformed")
    version = str(parsed.get("version") or "").lower()
    raw_entries = parsed.get("entries")
    if not (version.startswith("rss") or version.startswith("atom")):
        raise WebError("web document is not an RSS or Atom feed")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise WebError("RSS or Atom feed contains no entries")

    entries: list[dict] = []
    seen: set[str] = set()
    for raw in raw_entries:
        if not isinstance(raw, dict):
            continue
        try:
            url = _canonical_entry_url(raw.get("link"), feed_url)
        except (ValueError, WebError):
            continue
        if url in seen:
            continue
        seen.add(url)
        title = _plain_text(raw.get("title") or url, MAX_ENTRY_TITLE_CHARS)
        entries.append(
            {
                "title": title or url,
                "url": url,
                "published": _published_utc(raw),
                "summary": _entry_summary(raw),
            }
        )
        if len(entries) >= limit:
            break
    if not entries:
        raise WebError("RSS or Atom feed contains no public entry URLs")
    return _plain_text(parsed.get("feed", {}).get("title"), MAX_ENTRY_TITLE_CHARS), entries


def download_feed(url: object, *, headers: dict | None = None, etag: str = "",
                  last_modified: str = "", cancel_event: threading.Event | None = None,
                  expected_origin: tuple | None = None) -> dict:
    """Acquire a bounded feed response without choosing a Source capture unit."""
    _check_cancelled(cancel_event)
    current = _public_url(url)
    deadline = time.monotonic() + 45
    request_headers = {
        "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9",
        "User-Agent": "Obsidience-Research/0.1 (+local evidence capture)",
        **(headers or {}),
    }
    if etag:
        request_headers["If-None-Match"] = etag
    if last_modified:
        request_headers["If-Modified-Since"] = last_modified
    with httpx.Client(
        follow_redirects=False,
        timeout=httpx.Timeout(20.0, connect=10.0),
        trust_env=False,
        headers=request_headers,
    ) as client:
        for redirect_count in range(MAX_REDIRECTS + 1):
            _check_cancelled(cancel_event)
            parsed = urlsplit(current)
            origin = (parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
            if expected_origin is not None and origin != expected_origin:
                raise WebError("feed redirect must remain on the connection origin")
            if time.monotonic() > deadline:
                raise WebError("web feed acquisition deadline exceeded")
            with client.stream("GET", current) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location or redirect_count >= MAX_REDIRECTS:
                        raise WebError("web redirect limit exceeded")
                    current = _public_url(
                        urljoin(current, location),
                        previous_scheme=urlsplit(current).scheme,
                    )
                    continue
                if response.status_code == 304:
                    if not etag and not last_modified:
                        raise WebError("unexpected not-modified response")
                    return {"url": current, "status": 304}
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise WebError(f"web feed returned HTTP {response.status_code}") from exc

                media_type = (
                    response.headers.get("content-type", "")
                    .split(";", 1)[0]
                    .strip()
                    .lower()
                )
                if media_type not in _FEED_MEDIA_TYPES:
                    raise WebError(
                        f"unsupported web feed content type: {media_type or '(missing)'}"
                    )
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    _check_cancelled(cancel_event)
                    if time.monotonic() > deadline:
                        raise WebError("web feed acquisition deadline exceeded")
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise WebError("web response exceeds the 2 MB acquisition bound")
                    chunks.append(chunk)
                material = b"".join(chunks)
                try:
                    content = material.decode("utf-8", errors="strict")
                except UnicodeDecodeError as exc:
                    raise WebError("web feed is not strict UTF-8") from exc
                return {
                    "url": current, "status": 200, "material": material,
                    "content": content, "media_type": media_type,
                    "etag": response.headers.get("etag", "")[:2_000],
                    "last_modified": response.headers.get("last-modified", "")[:2_000],
                }
    raise WebError("web feed fetch failed")


def _parse_feed_document(material: bytes) -> dict:
    parsed = feedparser.parse(material, resolve_relative_uris=False, sanitize_html=False)
    version = str(parsed.get("version") or "").lower()
    if parsed.get("bozo") or not (version.startswith("rss") or version.startswith("atom")):
        raise WebError("RSS or Atom feed XML is malformed or unsupported")
    entries = parsed.get("entries")
    if not isinstance(entries, list):
        raise WebError("RSS or Atom feed entries are invalid")
    return parsed


def _feed_item_identity(raw: dict, feed_url: str) -> tuple[str, str]:
    if not isinstance(raw, dict):
        raise WebError("RSS or Atom item is invalid")
    # A reporting link is metadata here. Its eventual acquisition owns DNS
    # and public-address checks; parsing a feed must not resolve 30 hosts.
    url = canonical_url(validate_fetch_url(urljoin(feed_url, str(raw["link"])))) if raw.get("link") else ""
    native_id = str(raw.get("id") or raw.get("guid") or url)
    if not native_id:
        raise WebError("RSS or Atom item requires an ID or reporting URL")
    return native_id, url


def _feed_items(parsed: dict, feed_url: str, limit: int, *, allow_tail_after: int | None = None) -> list[dict]:
    version = str(parsed["version"]).lower()
    entries = parsed["entries"]
    result, seen = [], set()
    for raw in entries:
        try:
            native_id, url = _feed_item_identity(raw, feed_url)
        except WebError:
            if allow_tail_after is not None and len(result) >= allow_tail_after:
                break
            raise
        if native_id in seen:
            continue
        seen.add(native_id)
        # FeedParserDict and parsed date tuples have an ordinary JSON meaning.
        # Keep the complete parsed entry, including full content and summaries.
        entry = json.loads(json.dumps(raw, ensure_ascii=False, allow_nan=False))
        result.append({"record_type": "parsed_rss_item", "feed_format": version,
                       "native_id": native_id, "reporting_url": url,
                       "title": str(raw.get("title") or url or native_id),
                       "published": _published_utc(raw), "entry": entry})
        if len(result) >= limit:
            break
    return result


def parse_feed_items(material: bytes, feed_url: str, limit: int) -> list[dict]:
    """Keep complete parsed RSS/Atom items, distinct from discovery previews."""
    return _feed_items(_parse_feed_document(material), feed_url, limit)


def parse_feed_preview(material: bytes, feed_url: str, item_limit: int = MAX_FEED_ENTRIES) -> dict:
    """Inspect the same ordered collection prefix without creating a Source."""
    parsed = _parse_feed_document(material)
    items = _feed_items(parsed, feed_url, MAX_FEED_ENTRIES, allow_tail_after=item_limit)
    # Count identities without serializing unselected bodies. A malformed tail
    # cannot prevent previewing the same valid 30-item collection prefix.
    count_limit = 1000
    seen, count_limited, entry_error = set(), False, ""
    for raw in parsed["entries"]:
        try:
            native_id, _url = _feed_item_identity(raw, feed_url)
        except WebError:
            count_limited = True
            entry_error = (f"The preview stops after {len(seen)} valid items because the next publisher item is invalid. "
                           "Collecting beyond this point will fail until the publisher corrects it.")
            break
        seen.add(native_id)
        if len(seen) > count_limit:
            count_limited = True
            break
    metadata = parsed.get("feed", {})
    return {"feed_title": metadata.get("title", ""),
            "feed_description": metadata.get("subtitle") or metadata.get("description", ""),
            "feed_format": str(parsed["version"]).lower(),
            "available_count": min(len(seen), count_limit),
            "count_limited": count_limited, "entry_error": entry_error, "entries": items}


def fetch_feed(url: object, limit: object = 20, *, activation_key: str | None = None) -> dict:
    """Fetch one public feed, capture its exact UTF-8 XML, and return leads."""
    try:
        safe_limit = max(1, min(int(limit), MAX_FEED_ENTRIES))
    except (TypeError, ValueError) as exc:
        raise WebError("limit must be an integer") from exc
    response = download_feed(url)
    feed_title, entries = _parse_entries(response["material"], response["url"], safe_limit)
    captured_at = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    source = ingest_source(source_type="tool", source_ref=response["url"],
                           media_type=response["media_type"], captured_at=captured_at,
                           content=response["content"], activation_key=activation_key)
    return {"url": response["url"], "feed_title": feed_title,
            "citation": source["citation"], "content_sha256": source["content_sha256"],
            "created": source["created"], "entries": entries}
