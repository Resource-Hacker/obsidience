"""Bounded public-web acquisition for the researcher.

Search is discovery only. Fetch revalidates every redirect, extracts readable
text, and commits that exact tool output to the immutable Source authority
before returning it to the agent.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import signal
import socket
import subprocess
import sys
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from ..config import PROJECT_ROOT

WEB_WORKER_MODULE = "obsidience.harness.web.worker"
from ..knowledge.source import ingest_source

MAX_QUERY_CHARS = 300
MAX_RESULTS = 8
MAX_RESPONSE_BYTES = 2_000_000
MAX_FETCH_CHARS = 240_000
MAX_REDIRECTS = 5
_ALLOWED_CONTENT_TYPES = {
    "application/json",
    "application/ld+json",
    "application/xhtml+xml",
    "application/xml",
    "text/html",
    "text/markdown",
    "text/plain",
    "text/xml",
}
_BLOCK_TAGS = {
    "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt",
    "figcaption", "figure", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
    "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section", "table",
    "td", "th", "tr", "ul",
}
_SKIP_TAGS = {"canvas", "noscript", "script", "style", "svg", "template"}


class WebError(ValueError):
    """A web acquisition failed its bounded contract."""


class _ReadableHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        if tag == "title" and not self._skip_depth:
            self._in_title = True
        if tag in _BLOCK_TAGS and not self._skip_depth:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if tag in _BLOCK_TAGS and not self._skip_depth:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        self.parts.append(data)

    def markdown(self) -> str:
        title = re.sub(r"\s+", " ", " ".join(self.title_parts)).strip()
        lines: list[str] = []
        for raw in "".join(self.parts).splitlines():
            line = re.sub(r"[\t \f\v]+", " ", raw).strip()
            if line and (not lines or line != lines[-1]):
                lines.append(line)
        body = "\n\n".join(lines)
        return f"# {title}\n\n{body}" if title and not body.startswith(f"# {title}") else body


def _bounded_text(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise WebError(f"{field} must be a string")
    text = value.replace("\x00", "").strip()
    if not text:
        raise WebError(f"{field} must not be empty")
    if len(text) > maximum:
        raise WebError(f"{field} exceeds its bound")
    return text


def _public_url(value: object, *, previous_scheme: str | None = None) -> str:
    raw = _bounded_text(value, "url", 2_000)
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise WebError("url must be an absolute HTTP or HTTPS URL")
    if parsed.username or parsed.password:
        raise WebError("url credentials are not allowed")
    if previous_scheme == "https" and parsed.scheme != "https":
        raise WebError("HTTPS redirects may not downgrade to HTTP")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise WebError("url port is invalid") from exc
    try:
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise WebError(f"url host did not resolve: {parsed.hostname}") from exc
    if not addresses:
        raise WebError("url host did not resolve")
    for address in addresses:
        candidate = ipaddress.ip_address(address[4][0].split("%", 1)[0])
        if not candidate.is_global:
            raise WebError("url resolves to a non-public address")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def _search_worker(query: str, limit: int) -> list[dict]:
    request = json.dumps({"query": query, "limit": limit})
    env = {
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": str(PROJECT_ROOT),
    }
    process = subprocess.Popen(
        [sys.executable, "-m", WEB_WORKER_MODULE],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        start_new_session=True,
    )
    try:
        output, error = process.communicate(request, timeout=30)
    except subprocess.TimeoutExpired as exc:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise WebError("web search timed out") from exc
    if process.returncode != 0:
        raise WebError(f"web search failed: {(error or output).strip()[:300]}")
    try:
        envelope = json.loads(output)
    except json.JSONDecodeError as exc:
        raise WebError("web search returned an invalid response") from exc
    if not isinstance(envelope, dict) or not envelope.get("ok"):
        raise WebError(str(envelope.get("error") if isinstance(envelope, dict) else "web search failed"))
    rows = envelope.get("results")
    if not isinstance(rows, list):
        raise WebError("web search returned invalid results")
    return rows


def search_web(query: object, limit: object = 5) -> dict:
    normalized_query = _bounded_text(query, "query", MAX_QUERY_CHARS)
    try:
        safe_limit = max(1, min(int(limit), MAX_RESULTS))
    except (TypeError, ValueError) as exc:
        raise WebError("limit must be an integer") from exc
    results = []
    for raw in _search_worker(normalized_query, safe_limit):
        if not isinstance(raw, dict):
            continue
        try:
            url = _public_url(raw.get("href") or raw.get("url"))
        except WebError:
            continue
        results.append({
            "title": str(raw.get("title") or url)[:300],
            "url": url,
            "description": str(raw.get("body") or raw.get("description") or "")[:1_200],
        })
        if len(results) >= safe_limit:
            break
    if not results:
        raise WebError("web search returned no public results")
    return {"query": normalized_query, "results": results}


def _decode_response(response: httpx.Response, material: bytes) -> tuple[str, str]:
    media = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if media not in _ALLOWED_CONTENT_TYPES:
        raise WebError(f"unsupported web content type: {media or '(missing)'}")
    encoding = response.encoding or "utf-8"
    text = material.decode(encoding, errors="replace").replace("\x00", "").strip()
    if media in {"text/html", "application/xhtml+xml"}:
        parser = _ReadableHTML()
        parser.feed(text)
        parser.close()
        text = parser.markdown().strip()
        media_type = "text/markdown"
    elif media in {"application/json", "application/ld+json"}:
        media_type = "application/json"
    else:
        media_type = "text/plain"
    if not text:
        raise WebError("web page contained no readable text")
    return text[:MAX_FETCH_CHARS], media_type


def fetch_web(url: object, *, activation_key: str | None = None) -> dict:
    current = _public_url(url)
    with httpx.Client(
        follow_redirects=False,
        timeout=httpx.Timeout(20.0, connect=10.0),
        trust_env=False,
        headers={
            "Accept": "text/html, text/plain, text/markdown, application/json, application/xml;q=0.8",
            "User-Agent": "Obsidience-Research/0.1 (+local evidence capture)",
        },
    ) as client:
        for redirect_count in range(MAX_REDIRECTS + 1):
            with client.stream("GET", current) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location or redirect_count >= MAX_REDIRECTS:
                        raise WebError("web redirect limit exceeded")
                    current = _public_url(
                        urljoin(current, location), previous_scheme=urlsplit(current).scheme,
                    )
                    continue
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise WebError(f"web fetch returned HTTP {response.status_code}") from exc
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES:
                        raise WebError("web response exceeds the 2 MB acquisition bound")
                    chunks.append(chunk)
                content, media_type = _decode_response(response, b"".join(chunks))
                captured_at = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
                source = ingest_source(
                    source_type="tool",
                    source_ref=current,
                    media_type=media_type,
                    captured_at=captured_at,
                    content=content,
                    activation_key=activation_key,
                )
                return {
                    "url": current,
                    "status": response.status_code,
                    "content": content,
                    "citation": source["citation"],
                    "content_sha256": source["content_sha256"],
                    "created": source["created"],
                }
    raise WebError("web fetch failed")
