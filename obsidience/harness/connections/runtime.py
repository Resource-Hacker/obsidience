"""One connection registry and RSS intake lane; existing Tasks own all research."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager, suppress
from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from urllib.parse import parse_qsl, urlsplit
import uuid

import httpx
from lxml import html as lxml_html

from ..config import CONFIG
from ..knowledge import source
from ..web.feeds import MAX_ENTRY_TITLE_CHARS, download_feed, parse_feed_items, parse_feed_preview
from ..web.runtime import validate_fetch_url
from . import destinations

SCHEMA = "obsidience.connections.v1"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
_CONNECTION_FIELDS = {"id", "name", "kind", "url", "enabled", "auth_mode"}
_FEED_FIELDS = {"id", "connection_id", "name", "url", "enabled", "interval_minutes", "item_limit",
                "destination_ref", "max_active_articles", "distill_instructions"}
_DEFINITIONS_LOCK = threading.RLock()
_SECRET_QUERY = {"token", "access_token", "api_key", "apikey", "key", "password", "secret", "auth", "authorization"}


class ConnectionsError(ValueError):
    pass


class RevisionConflict(ConnectionsError):
    pass


class _PollCancelled(Exception):
    pass


def _text(value, field, maximum=200):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ConnectionsError(f"{field} must be nonempty text within {maximum} characters")
    return value.strip()


def _url(value):
    try:
        url = validate_fetch_url(value)
    except ValueError as exc:
        raise ConnectionsError(str(exc)) from exc
    if any(key.lower() in _SECRET_QUERY for key, _ in parse_qsl(urlsplit(url).query)):
        raise ConnectionsError("Store authentication in the connection credential, never its URL")
    return url


def _origin(url):
    parsed = urlsplit(url)
    return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)


def _fingerprint(connection, feed):
    return hashlib.sha256(json.dumps([connection, feed], sort_keys=True).encode()).hexdigest()


def _plain_content(value):
    """Display provider HTML as inert text without loading any external resource."""
    text = str(value or "")
    if not text:
        return ""
    try:
        tree = lxml_html.fragment_fromstring(text, create_parent="div", parser=lxml_html.HTMLParser(no_network=True))
    except (ValueError, lxml_html.etree.ParserError):
        return text
    for element in tree.xpath(".//script | .//style | .//iframe | .//object | .//embed"):
        element.drop_tree()
    for element in tree.iter("p", "div", "br", "li", "h1", "h2", "h3", "blockquote"):
        element.tail = "\n" + (element.tail or "")
    return "\n".join(line.strip() for line in tree.text_content().splitlines() if line.strip())


class ConnectionsManager:
    def __init__(self, path: Path | None = None, index=None, *, auth_headers=None, credential_ready=None):
        if index is None:
            from ..knowledge.index import INDEX
            index = INDEX
        self.path = Path(path) if path is not None else CONFIG.runtime_dir / "connections.json"
        self.index = index
        self.auth_headers = auth_headers
        self.credential_ready = credential_ready
        self._lock = _DEFINITIONS_LOCK
        self._wake = asyncio.Event()
        self._loop = None
        self._task = None
        self._checks = {}
        self._workers = set()
        self._worker_cancel = None
        self._preview_cancel = None
        self._stopping = False
        self._runtime_error = ""

    def _read(self):
        if not self.path.exists():
            return {"schema": SCHEMA, "revision": 0, "connections": [], "feeds": []}
        if self.path.stat().st_size > 1_000_000:
            raise ConnectionsError("Connection definitions exceed their size bound")
        try:
            doc = json.loads(self.path.read_text())
        except (OSError, ValueError) as exc:
            raise ConnectionsError("Connection definitions could not be read") from exc
        if (not isinstance(doc, dict) or set(doc) != {"schema", "revision", "connections", "feeds"}
                or doc["schema"] != SCHEMA or type(doc["revision"]) is not int or doc["revision"] < 0):
            raise ConnectionsError("Connection definitions have an invalid schema or revision")
        self._validate(doc)
        return doc

    def _validate(self, doc):
        for key, fields, limit in (("connections", _CONNECTION_FIELDS, 64), ("feeds", _FEED_FIELDS, 128)):
            rows = doc.get(key)
            if not isinstance(rows, list) or len(rows) > limit:
                raise ConnectionsError(f"{key} exceeds its definition bound")
            seen = set()
            for row in rows:
                if key == "feeds" and isinstance(row, dict):
                    row.setdefault("destination_ref", "")
                    row.setdefault("max_active_articles", 10)
                    row.setdefault("distill_instructions", "")
                if not isinstance(row, dict) or set(row) != fields:
                    raise ConnectionsError(f"{key} contains unknown or missing fields")
                identifier = row["id"]
                if not isinstance(identifier, str) or not _ID.fullmatch(identifier) or identifier in seen:
                    raise ConnectionsError(f"{key} requires unique stable IDs")
                seen.add(identifier)
                row["name"] = _text(row["name"], "name")
                row["url"] = _url(row["url"])
                if type(row["enabled"]) is not bool:
                    raise ConnectionsError("enabled must be boolean")
        connections = {row["id"]: row for row in doc["connections"]}
        for row in connections.values():
            if (not isinstance(row["kind"], str) or not isinstance(row["auth_mode"], str)
                    or row["kind"] not in {"rss", "http_api"} or row["auth_mode"] not in {"none", "bearer", "bot"}):
                raise ConnectionsError("Unsupported connection kind or authentication mode")
        for row in doc["feeds"]:
            if not isinstance(row["destination_ref"], str) or len(row["destination_ref"]) > 300:
                raise ConnectionsError("destination_ref must be an exact existing Knowledge node reference")
            try:
                row["distill_instructions"] = source.normalize_distill_instructions(row["distill_instructions"])
            except source.SourceError as exc:
                raise ConnectionsError(str(exc)) from exc
            connection = connections.get(row["connection_id"]) if isinstance(row["connection_id"], str) else None
            if connection is None or connection["kind"] != "rss":
                raise ConnectionsError("A Feed requires an existing RSS connection")
            if _origin(connection["url"]) != _origin(row["url"]):
                raise ConnectionsError("Feed URL must use the exact connection origin")
            for name, low, high in (("interval_minutes", 5, 1440), ("item_limit", 1, 30),
                                    ("max_active_articles", 1, 1000)):
                if type(row[name]) is not int or not low <= row[name] <= high:
                    raise ConnectionsError(f"{name} must be an integer from {low} to {high}")

    @contextmanager
    def revision_guard(self, expected_revision):
        with self._lock:
            doc = self._read()
            if type(expected_revision) is not int or expected_revision != doc["revision"]:
                raise RevisionConflict("Connection definitions changed; refresh before saving")
            yield doc

    def _write(self, doc):
        self._validate(doc)
        doc["revision"] += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".connections-", dir=self.path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w") as stream:
                json.dump(doc, stream, ensure_ascii=False, sort_keys=True, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            with suppress(FileNotFoundError):
                os.unlink(temporary)
        for cancel in self._checks.values():
            cancel.set()
        self._notify()

    def _notify(self):
        if self._loop is not None and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._wake.set)

    def connection(self, connection_id, *, expected_revision=None):
        with self._lock:
            doc = self._read()
            if expected_revision is not None and expected_revision != doc["revision"]:
                raise RevisionConflict("Connection definitions changed; refresh before continuing")
            return deepcopy(self._find(doc["connections"], connection_id, "Connection"))

    @staticmethod
    def _find(rows, identifier, label):
        for row in rows:
            if row["id"] == identifier:
                return row
        raise ConnectionsError(f"{label} was not found")

    def _save(self, key, payload, expected_revision):
        fields = _CONNECTION_FIELDS if key == "connections" else _FEED_FIELDS
        if not isinstance(payload, dict) or set(payload) - fields:
            raise ConnectionsError("Unknown definition fields")
        with self.revision_guard(expected_revision) as doc:
            identifier = payload.get("id")
            access_changed = False
            if identifier:
                row = self._find(doc[key], identifier, "Connection" if key == "connections" else "Feed")
                access_changed = key == "connections" and any(
                    name in payload and payload[name] != row[name] for name in ("url", "kind", "auth_mode"))
                row.update(payload)
            else:
                row = {"id": uuid.uuid4().hex, "enabled": True, **payload}
                row["id"] = row["id"] or uuid.uuid4().hex
                if key == "connections":
                    row.setdefault("auth_mode", "none")
                else:
                    row.setdefault("interval_minutes", 30)
                    row.setdefault("item_limit", 10)
                doc[key].append(row)
            if key == "feeds":
                self._validate(doc)
                try:
                    if identifier and set(payload) <= {"id", "enabled"} and payload.get("enabled") is False:
                        self._write(doc)
                    else:
                        with destinations.bind_destination(row["destination_ref"]) as (_node, changed):
                            self._write(doc)
                        if changed:
                            self.index.sync()
                except ValueError as exc:
                    raise ConnectionsError(str(exc)) from exc
            else:
                self._write(doc)
            if access_changed:
                self.index.update_connection_runtime(identifier, last_checked=None,
                                                     status="unchecked", last_error="")
            return self.snapshot()

    def save_connection(self, payload, *, expected_revision):
        return self._save("connections", payload, expected_revision)

    def save_feed(self, payload, *, expected_revision):
        snapshot = self._save("feeds", payload, expected_revision)
        # An explicit policy save also handles quiet Feeds. The collector only
        # captures Sources; the existing Review owner applies retirement.
        feed_id = payload.get("id")
        if (feed_id and not (set(payload) <= {"id", "enabled"} and payload.get("enabled") is False)
                and set(payload) & {"max_active_articles", "destination_ref", "enabled"}):
            from ..knowledge.curation import reconcile_feed_retention

            result = reconcile_feed_retention(feed_id, definition_guard=lambda: self.feed_guard(feed_id))
            snapshot = self.snapshot()
            snapshot["retention_result"] = result
        return snapshot

    @contextmanager
    def feed_guard(self, feed_id, expected_ref=None):
        with self._lock:
            yield self.destination_binding(feed_id, expected_ref)

    def destination_binding(self, feed_id, expected_ref=None):
        with self._lock:
            doc = self._read()
            feed = self._find(doc["feeds"], feed_id, "Feed")
            if expected_ref is not None and feed["destination_ref"] != expected_ref:
                raise ConnectionsError("The Feed destination changed after capture; this occurrence cannot publish to the old node")
            try:
                node = destinations.destination(feed["destination_ref"])
            except ValueError as exc:
                raise ConnectionsError(str(exc)) from exc
            return {"feed_id": feed_id, "destination_ref": node["ref"],
                    "destination_title": node["title"], "auto_curate": node["auto_curate"],
                    "auto_curate_supported": True, "max_active_articles": feed["max_active_articles"]}

    def credentials_changed(self, connection_id, *, expected_revision):
        """Invalidate response validators when the private authentication changes."""
        with self.revision_guard(expected_revision) as doc:
            self._find(doc["connections"], connection_id, "Connection")
            for feed in doc["feeds"]:
                if feed["connection_id"] == connection_id:
                    self.index.update_feed_runtime(feed["id"], definition_fingerprint="",
                        etag="", last_modified="", next_check=0, last_error="")
            self.index.update_connection_runtime(connection_id, last_checked=None,
                                                 status="unchecked", last_error="")
            self._write(doc)
            return self.snapshot()

    def delete_connection(self, connection_id, *, expected_revision):
        with self.revision_guard(expected_revision) as doc:
            self._find(doc["connections"], connection_id, "Connection")
            if any(feed["connection_id"] == connection_id for feed in doc["feeds"]):
                raise ConnectionsError("Remove this connection's Feeds before deleting it")
            doc["connections"] = [row for row in doc["connections"] if row["id"] != connection_id]
            self._write(doc)
            return self.snapshot()

    def delete_feed(self, feed_id, *, expected_revision):
        with self.revision_guard(expected_revision) as doc:
            self._find(doc["feeds"], feed_id, "Feed")
            doc["feeds"] = [row for row in doc["feeds"] if row["id"] != feed_id]
            self._write(doc)
            return self.snapshot()

    def record_connection_check(self, connection_id, revision, status, error=""):
        with self._lock:
            doc = self._read()
            if doc["revision"] != revision:
                return self.snapshot()
            self._find(doc["connections"], connection_id, "Connection")
            self.index.update_connection_runtime(connection_id, last_checked=time.time(),
                                                 status=str(status)[:80], last_error=str(error)[:300])
            return self.snapshot()

    def snapshot(self):
        with self._lock:
            doc = self._read()
            for connection in doc["connections"]:
                connection.update(self.index.connection_runtime(connection["id"]))
                connection["credential_ready"] = connection["auth_mode"] == "none" or bool(
                    self.credential_ready and self.credential_ready(connection["id"]))
                connection["credential_set"] = connection["auth_mode"] != "none" and connection["credential_ready"]
            enabled = {row["id"]: row["enabled"] for row in doc["connections"]}
            nodes = destinations.destinations()
            nodes_by_ref = {node["ref"]: dict(node) for node in nodes}
            from ..knowledge.curation import feed_retention_states

            retention = feed_retention_states(
                {feed["id"]: feed["max_active_articles"] for feed in doc["feeds"]}, index=self.index)
            for feed in doc["feeds"]:
                state = self.index.feed_runtime(feed["id"])
                feed.update({key: state.get(key) for key in (
                    "last_checked", "next_check", "last_error", "last_item_count", "last_new_count")})
                feed.update(self.index.feed_item_summary(feed["id"]))
                feed.update(retention[feed["id"]])
                feed["running"] = feed["id"] in self._checks
                feed["active"] = feed["enabled"] and enabled[feed["connection_id"]]
                node = nodes_by_ref.get(feed["destination_ref"])
                if node:
                    feed.update(destination_title=node["title"], auto_curate=node["auto_curate"],
                                auto_curate_supported=True, destination_error="")
                else:
                    feed.update(destination_title="", auto_curate=False, auto_curate_supported=False,
                                destination_error="Select an existing Knowledge node before collecting")
            return {**doc, "destination_nodes": nodes, "last_error": self._runtime_error}

    def _item_projection(self, row, definitions, *, full=False):
        material = bytes(row["material"])
        if "sha256:" + hashlib.sha256(material).hexdigest() != row["material_sha256"]:
            raise ConnectionsError("Feed Source material failed attestation")
        try:
            raw = source.parse_raw_source(material)
            item = json.loads(raw.content)
            if (raw.source_id != row["id"] or raw.content_sha256 != row["content_sha256"]
                    or raw.source_ref != f"feed://{row['feed_id']}/{row['item_key']}"
                    or item.get("record_type") != "parsed_rss_item"
                    or not isinstance(item.get("entry"), dict)
                    or item.get("provenance", {}).get("feed_id") != row["feed_id"]):
                raise ValueError("Feed Source identity mismatch")
        except (source.SourceError, ValueError, AttributeError) as exc:
            raise ConnectionsError("Feed Source is not a valid captured item") from exc
        feed = next((feed for feed in definitions["feeds"] if feed["id"] == row["feed_id"]), None)
        entry = item["entry"]
        summary = _plain_content(entry.get("summary") or entry.get("description"))
        contents = entry.get("content")
        content = "\n\n".join(_plain_content(part.get("value")) for part in contents
                              if isinstance(part, dict)) if isinstance(contents, list) else ""
        content = content or summary
        projected = {
            "source_id": raw.source_id, "source_path": "obsidience/evidence/" + row["path"],
            "feed_id": row["feed_id"], "connection_id": item["provenance"]["connection_id"],
            "feed_name": feed["name"] if feed else "Removed Feed",
            "title": _plain_content(item.get("title"))[:MAX_ENTRY_TITLE_CHARS], "published": item.get("published"),
            "captured_at": raw.captured_at, "summary": re.sub(r"\s+", " ", summary or content)[:400],
            "reporting_url": item.get("reporting_url", ""),
        }
        if full:
            projected.update(content_text=content, provenance=deepcopy(item["provenance"]),
                             source_ref=raw.source_ref, native_id=item["native_id"],
                             record_type="parsed_rss_item")
        return projected

    def items(self, feed_id=None, limit=100):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ConnectionsError("Item limit must be an integer from 1 to 100")
        with self._lock:
            definitions = self._read()
        rows = self.index.feed_item_sources(feed_id=feed_id, limit=limit)
        items = [self._item_projection(row, definitions) for row in rows]
        items.sort(key=lambda item: (
            -datetime.fromisoformat(item["published"] or item["captured_at"]).timestamp(), item["source_id"]))
        return {"items": items, "limit": limit}

    def item(self, source_id):
        with self._lock:
            definitions = self._read()
        rows = self.index.feed_item_sources(source_id=source_id, limit=1)
        if not rows:
            raise ConnectionsError("Feed item was not found")
        return self._item_projection(rows[0], definitions, full=True)

    def preview_feed(self, payload, *, expected_revision, cancel_event=None):
        """Read publisher contents for a draft, without collection or persistence."""
        if set(payload) != {"connection_id", "url", "item_limit"}:
            raise ConnectionsError("Preview requires only connection_id, url and item_limit")
        item_limit = payload["item_limit"]
        if type(item_limit) is not int or not 1 <= item_limit <= 30:
            raise ConnectionsError("item_limit must be an integer from 1 to 30")
        url = _url(payload["url"])
        cancelled = cancel_event if cancel_event is not None else threading.Event()
        try:
            with self.revision_guard(expected_revision) as doc:
                if self._stopping or cancelled.is_set():
                    raise ConnectionsError("Feed preview was cancelled")
                if self._preview_cancel is not None:
                    raise ConnectionsError("A Feed preview is already loading")
                connection = self._find(doc["connections"], payload["connection_id"], "Connection")
                if connection["kind"] != "rss":
                    raise ConnectionsError("Feed preview requires an RSS connection")
                if _origin(url) != _origin(connection["url"]):
                    raise ConnectionsError("Feed URL must use the exact connection origin")
                headers = {}
                if connection["auth_mode"] != "none":
                    if self.auth_headers is None:
                        raise ConnectionsError("Connection credentials are not configured")
                    try:
                        headers = self.auth_headers(connection["id"], connection["auth_mode"])
                    except (ValueError, OSError) as exc:
                        raise ConnectionsError("The connection credential is unavailable; check its access settings") from exc
                definition_fingerprint = _fingerprint(doc, {})
                self._preview_cancel = cancelled
            # The existing downloader owns public-address validation, exact
            # redirect origin, finite deadlines and the 2 MB response bound.
            # No conditional validators: preview must inspect current contents.
            try:
                response = download_feed(url, headers=headers, cancel_event=cancelled,
                                         expected_origin=_origin(connection["url"]))
                result = parse_feed_preview(response["material"], response["url"], item_limit)
            except (ValueError, httpx.HTTPError, OSError) as exc:
                # Provider failures may include credential material, URLs or
                # arbitrary response headers. Only fixed failure prose escapes.
                raise ConnectionsError("The publisher feed could not be loaded; check its URL and access settings") from exc
            entries = []
            for position, item in enumerate(result["entries"], 1):
                entry = item["entry"]
                summary = _plain_content(entry.get("summary") or entry.get("description"))
                parts = entry.get("content")
                content = "\n\n".join(_plain_content(part.get("value")) for part in parts
                                      if isinstance(part, dict)) if isinstance(parts, list) else ""
                entries.append({"position": position, "title": _plain_content(item["title"])[:MAX_ENTRY_TITLE_CHARS],
                                "published": item["published"], "reporting_url": item["reporting_url"],
                                "summary": re.sub(r"\s+", " ", summary or content)[:400],
                                "has_summary": bool(summary), "has_content": bool(content),
                                "selected": position <= item_limit})
            with self.revision_guard(expected_revision) as current:
                if _fingerprint(current, {}) != definition_fingerprint:
                    raise RevisionConflict("Connection definitions changed; refresh before previewing")
                if self._stopping or cancelled.is_set():
                    raise ConnectionsError("Feed preview was cancelled")
                return {"revision": expected_revision, "connection_id": connection["id"], "url": url,
                        "feed_title": _plain_content(result["feed_title"])[:MAX_ENTRY_TITLE_CHARS],
                        "feed_description": _plain_content(result["feed_description"])[:1000],
                        "feed_format": result["feed_format"], "available_count": result["available_count"],
                        "count_limited": result["count_limited"], "entry_error": result["entry_error"],
                        "item_limit": item_limit, "entries": entries,
                        "checked_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")}
        finally:
            with self._lock:
                if self._preview_cancel is cancelled:
                    self._preview_cancel = None

    def _current(self, feed_id, revision, cancelled, *, allow_paused=False):
        if self._stopping or cancelled.is_set():
            raise _PollCancelled
        doc = self._read()
        if doc["revision"] != revision:
            raise _PollCancelled
        feed = self._find(doc["feeds"], feed_id, "Feed")
        connection = self._find(doc["connections"], feed["connection_id"], "Connection")
        if not connection["enabled"] or not feed["enabled"] and not allow_paused:
            raise _PollCancelled
        return connection, feed

    def _poll_feed(self, feed_id, revision, cancelled, *, allow_paused=False):
        fingerprint, same = "", False
        try:
            with self._lock:
                connection, feed = self._current(feed_id, revision, cancelled, allow_paused=allow_paused)
                fingerprint = _fingerprint(connection, feed)
                previous = self.index.feed_runtime(feed_id)
                same = previous.get("definition_fingerprint") == fingerprint
                self.destination_binding(feed_id)
                headers = {}
                if connection["auth_mode"] != "none":
                    if self.auth_headers is None:
                        raise ConnectionsError("Connection credentials are not configured")
                    # The adapter resolves credentials against this same current
                    # provider definition, before an endpoint edit can replace it.
                    headers = self.auth_headers(connection["id"], connection["auth_mode"])
            response = download_feed(feed["url"], headers=headers,
                                     etag=previous.get("etag", "") if same else "",
                                     last_modified=previous.get("last_modified", "") if same else "",
                                     cancel_event=cancelled, expected_origin=_origin(connection["url"]))
            items = [] if response["status"] == 304 else parse_feed_items(
                response["material"], response["url"], feed["item_limit"])
            records = []
            for item in items:
                key = hashlib.sha256(item["native_id"].encode()).hexdigest()
                content = json.dumps({**item, "provenance": {
                    "connection_id": connection["id"], "feed_id": feed_id, "feed_url": feed["url"],
                }}, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
                if len(content.encode("utf-8")) > source.MAX_SOURCE_CHARS:
                    raise ConnectionsError("A complete feed item exceeds the Source size bound")
                records.append((key, content))
            added = 0
            for key, content in records:
                # Definition changes and capture share this boundary: disabling
                # returns only after an already-started capture has settled.
                with self._lock:
                    self._current(feed_id, revision, cancelled, allow_paused=allow_paused)
                    captured = source.ingest_source(
                        source_type="document", source_ref=f"feed://{feed_id}/{key}",
                        media_type="application/json", content=content,
                        captured_at=datetime.now(UTC).isoformat(),
                        feed_receipt={"feed_id": feed_id, "item_key": key,
                                      "destination_ref": self.destination_binding(feed_id)["destination_ref"],
                                      "distill_instructions": feed["distill_instructions"]},
                    )
                    added += bool(captured["feed_item_created"])
            with self._lock:
                self._current(feed_id, revision, cancelled, allow_paused=allow_paused)
                fields = {"definition_fingerprint": fingerprint, "last_checked": time.time(),
                          "next_check": time.time() + feed["interval_minutes"] * 60,
                          "last_error": "", "last_item_count": len(items), "last_new_count": added}
                if response["status"] != 304:
                    fields.update(etag=response.get("etag", ""), last_modified=response.get("last_modified", ""))
                self.index.update_feed_runtime(feed_id, **fields)
        except _PollCancelled:
            return
        except Exception as exc:
            with self._lock:
                try:
                    _connection, feed = self._current(feed_id, revision, cancelled, allow_paused=allow_paused)
                except (_PollCancelled, ConnectionsError):
                    return
                # Transport exceptions can contain authenticated request URLs
                # or headers. Publish the error class, never their raw repr.
                message = str(exc) if isinstance(exc, ConnectionsError) else f"Feed check failed ({type(exc).__name__})"
                fields = {"definition_fingerprint": fingerprint, "last_checked": time.time(),
                          "next_check": time.time() + feed["interval_minutes"] * 60, "last_error": message[:300]}
                if not same:
                    fields.update(etag="", last_modified="")
                self.index.update_feed_runtime(feed_id, **fields)

    def _check_feed(self, feed_id, cancelled, manual):
        try:
            with self._lock:
                doc = self._read()
                if self._stopping or cancelled.is_set():
                    return
                try:
                    self._current(feed_id, doc["revision"], cancelled, allow_paused=manual)
                except _PollCancelled as exc:
                    raise ConnectionsError("Enable the connection and Feed before checking") from exc
                self._checks[feed_id] = cancelled
            self._poll_feed(feed_id, doc["revision"], cancelled, allow_paused=manual)
        finally:
            with self._lock:
                if self._checks.get(feed_id) is cancelled:
                    self._checks.pop(feed_id)
            self._notify()
        return self.snapshot()

    async def check_feed(self, feed_id, *, manual=True):
        # Async admission never waits on the registry lock: Source capture or a
        # private credential update may hold it in another worker thread.
        if self._stopping:
            raise ConnectionsError("Connections intake is stopping")
        if any(not worker.done() for worker in self._workers):
            raise ConnectionsError("A Feed is already being checked")
        cancelled = threading.Event()
        self._worker_cancel = cancelled
        worker = asyncio.create_task(asyncio.to_thread(self._check_feed, feed_id, cancelled, manual))
        self._workers.add(worker)

        def finished(done):
            self._workers.discard(done)
            if self._worker_cancel is cancelled:
                self._worker_cancel = None
            self._notify()

        worker.add_done_callback(finished)
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancelled.set()
            with suppress(asyncio.TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(asyncio.shield(worker), 2)
            raise

    async def start(self):
        if self._task is not None and not self._task.done():
            return
        self._stopping = False
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.create_task(self._run(), name="obsidience-connections-intake")

    async def stop(self):
        deadline = time.monotonic() + 3
        self._stopping = True
        if self._worker_cancel is not None:
            self._worker_cancel.set()
        if self._preview_cancel is not None:
            self._preview_cancel.set()
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError, asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(task), 3)
        if self._workers:
            await asyncio.wait(tuple(self._workers), timeout=max(0, deadline - time.monotonic()))
        self._loop = None

    def _due_feeds(self):
        with self._lock:
            doc = self._read()
            connections = {row["id"]: row for row in doc["connections"]}
            due = []
            for feed in doc["feeds"] if not self._checks else ():
                connection = connections[feed["connection_id"]]
                if not feed["enabled"] or not connection["enabled"]:
                    continue
                state = self.index.feed_runtime(feed["id"])
                when = state.get("next_check", 0) if state.get("definition_fingerprint") == _fingerprint(connection, feed) else 0
                due.append((when or 0, feed["id"]))
            return due

    async def _run(self):
        while True:
            self._wake.clear()
            try:
                due = [] if any(not worker.done() for worker in self._workers) else await asyncio.to_thread(self._due_feeds)
                self._runtime_error = ""
                if due:
                    when, feed_id = min(due)
                    if when <= time.time():
                        await self.check_feed(feed_id, manual=False)
                        continue
                    delay = max(0, when - time.time())
                else:
                    delay = None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._runtime_error = f"Connections intake failed ({type(exc).__name__})"
                delay = 60
            with suppress(asyncio.TimeoutError):
                await asyncio.wait_for(self._wake.wait(), delay)


@contextmanager
def feed_destination_guard(feed_id, expected_ref=None):
    """Publication uses the same definition lock as owner Feed edits."""
    with ConnectionsManager().feed_guard(feed_id, expected_ref) as binding:
        yield binding
