"""Publisher preview reads the collection prefix without acquiring Sources."""

import asyncio
import json
import threading
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from obsidience.harness.connections import runtime
from obsidience.harness.connections.credentials import CredentialError
from obsidience.harness.interfaces.api import connections
from obsidience.harness.knowledge import source
from obsidience.harness.web import feeds
from obsidience.harness.web.runtime import validate_fetch_url


def item(number, *, link=None, description="Provider description", content=""):
    return (f"<item><guid>{number}</guid><title><![CDATA[<b>Story {number}</b>]]></title>"
            f"<link>{link or 'https://publisher.example/story/' + str(number)}</link>"
            f"<description><![CDATA[{description}]]></description>"
            f"<pubDate>Wed, 09 Sep 2026 {int(number) % 24:02d}:00:00 GMT</pubDate>"
            f"{content}</item>")


def rss(*items):
    return ("<rss version='2.0' xmlns:content='http://purl.org/rss/1.0/modules/content/'>"
            "<channel><title><![CDATA[<b>Publisher news</b>]]></title>"
            "<description><![CDATA[<p>World &amp; science</p>]]></description>"
            + "".join(items) + "</channel></rss>").encode()


@pytest.fixture
def preview(tmp_path, monkeypatch, isolated_task_ledger):
    path = tmp_path / "connections.json"
    path.write_text(json.dumps({"schema": runtime.SCHEMA, "revision": 4,
        "connections": [{"id": "publisher", "name": "Publisher", "kind": "rss",
            "url": "https://publisher.example/rss", "enabled": False, "auth_mode": "none"}],
        "feeds": []}))
    manager = runtime.ConnectionsManager(path, isolated_task_ledger)
    state = SimpleNamespace(manager=manager, index=isolated_task_ledger,
        payload={"revision": 4, "connection_id": "publisher", "url": "https://publisher.example/world", "item_limit": 2},
        material=rss(item(1), item(2), item(3)), requests=[])
    def download(url, **kwargs):
        state.requests.append((url, kwargs))
        assert not manager._lock._is_owned(), "provider request held the definitions lock"
        return {"url": url, "status": 200, "material": state.material, "etag": "unused"}
    monkeypatch.setattr(runtime, "download_feed", download)
    monkeypatch.setattr(source, "ingest_source", lambda **_kwargs: pytest.fail("Preview captured a Source"))
    app = FastAPI()
    app.include_router(connections.router)
    app.state.connections = manager
    app.state.connection_credentials = None
    state.client = TestClient(app)
    return state


def test_preview_preserves_publisher_order_full_count_and_has_no_durable_effect(preview):
    preview.material = rss(item(9), item(1), item(9), *(item(n) for n in range(2, 42) if n != 9))
    definitions = preview.manager.path.read_bytes()
    ledger = "\n".join(preview.index.db.iterdump())
    changes = preview.index.db.total_changes
    result = preview.client.post("/api/feeds/preview", json=preview.payload)
    assert result.status_code == 200, result.text
    result = result.json()
    assert result["feed_title"] == "Publisher news"
    assert result["feed_description"] == "World & science"
    assert result["feed_format"] == "rss20"
    assert result["available_count"] == 41 and not result["count_limited"]
    assert len(result["entries"]) == 30
    assert [row["title"] for row in result["entries"][:3]] == ["Story 9", "Story 1", "Story 2"]
    assert [row["position"] for row in result["entries"]] == list(range(1, 31))
    assert [row["selected"] for row in result["entries"]] == [True] * 2 + [False] * 28
    assert result["entries"][0]["published"] == "2026-09-09T09:00:00Z"
    assert result["url"] == preview.payload["url"] and result["revision"] == 4
    assert result["checked_at"].endswith("Z")
    request = preview.requests[0][1]
    assert request["expected_origin"] == ("https", "publisher.example", 443)
    assert request["headers"] == {} and not request.get("etag") and not request.get("last_modified")
    assert definitions == preview.manager.path.read_bytes()
    assert "\n".join(preview.index.db.iterdump()) == ledger
    assert preview.index.db.total_changes == changes
    assert preview.manager._checks == {} and preview.manager._workers == set()
    assert preview.manager._preview_cancel is None


def test_preview_projects_html_as_inert_bounded_text_without_remote_assets(preview):
    preview.material = rss(item(1, description="<p>Hello <strong>world</strong></p>"
        "<script>secret script</script><style>hidden style</style><iframe>hidden frame</iframe>"
        "<img src='https://tracker.example/pixel'>" + "x" * 500,
        content="<content:encoded><![CDATA[<p>Full text</p>]]></content:encoded>"), item(2, description=""))
    response = preview.client.post("/api/feeds/preview", json=preview.payload)
    assert response.status_code == 200, response.text
    first, second = response.json()["entries"]
    assert first["title"] == "Story 1" and first["summary"].startswith("Hello world")
    assert len(first["summary"]) == 400
    assert first["has_summary"] and first["has_content"]
    assert not second["has_summary"] and not second["has_content"]
    assert all(text not in response.text for text in ("tracker.example", "secret script", "hidden style", "hidden frame", "<p>"))
    assert len(preview.requests) == 1


def test_empty_atom_is_a_valid_preview_and_feedparser_runs_once(preview, monkeypatch):
    preview.material = b'<feed xmlns="http://www.w3.org/2005/Atom"><title>Science</title><subtitle>New findings</subtitle></feed>'
    parse = feeds.feedparser.parse
    calls = []
    def parse_once(*args, **kwargs):
        calls.append(1)
        return parse(*args, **kwargs)
    monkeypatch.setattr(feeds.feedparser, "parse", parse_once)
    result = preview.client.post("/api/feeds/preview", json=preview.payload).json()
    assert result["entries"] == [] and result["available_count"] == 0
    assert result["feed_title"] == "Science" and result["feed_description"] == "New findings"
    assert result["feed_format"] == "atom10" and not result["count_limited"]
    assert calls == [1]


@pytest.mark.parametrize("count,limited", [(1000, False), (1001, True)])
def test_preview_count_bound_is_truthful(preview, count, limited):
    preview.material = rss(*(item(n) for n in range(count)))
    result = preview.client.post("/api/feeds/preview", json=preview.payload).json()
    assert result["available_count"] == 1000 and result["count_limited"] is limited
    assert len(result["entries"]) == 30 and result["entry_error"] == ""


def test_invalid_unselected_tail_does_not_hide_collectable_prefix(preview):
    preview.material = rss(item(1), item(2, link="javascript:alert(1)"))
    result = preview.client.post("/api/feeds/preview", json={**preview.payload, "item_limit": 1})
    assert result.status_code == 200, result.text
    result = result.json()
    assert len(result["entries"]) == result["available_count"] == 1
    assert result["count_limited"] and "next publisher item is invalid" in result["entry_error"]
    assert preview.client.post("/api/feeds/preview", json=preview.payload).status_code == 400


@pytest.mark.parametrize("same_revision", [False, True])
def test_late_preview_rejects_revision_and_fingerprint_changes(preview, monkeypatch, same_revision):
    def changed(url, **kwargs):
        doc = json.loads(preview.manager.path.read_text())
        doc["connections"][0]["name"] = "Changed while previewing"
        if not same_revision:
            doc["revision"] += 1
        preview.manager.path.write_text(json.dumps(doc))
        return {"url": url, "material": preview.material}
    monkeypatch.setattr(runtime, "download_feed", changed)
    result = preview.client.post("/api/feeds/preview", json=preview.payload)
    assert result.status_code == 409 and "changed" in result.text
    assert preview.manager._preview_cancel is None


@pytest.mark.parametrize("change", [
    {"revision": True}, {"revision": -1}, {"item_limit": True}, {"item_limit": 0}, {"item_limit": 31},
    {"connection_id": "missing"}, {"url": "https://other.example/rss"}, {"url": "http://publisher.example/rss"},
    {"url": "https://user:secret@publisher.example/rss"}, {"url": "https://publisher.example/rss?token=secret"},
    {"headers": {"Authorization": "Bearer secret"}},
])
def test_invalid_preview_inputs_never_contact_provider(preview, change):
    response = preview.client.post("/api/feeds/preview", json={**preview.payload, **change})
    assert response.status_code == 400 and preview.requests == []


def test_preview_rejects_external_browser_origin_and_api_connections(preview):
    assert preview.client.post("/api/feeds/preview", json=preview.payload,
        headers={"Origin": "https://attacker.example"}).status_code == 403
    doc = json.loads(preview.manager.path.read_text())
    doc["connections"][0]["kind"] = "http_api"
    preview.manager.path.write_text(json.dumps(doc))
    assert preview.client.post("/api/feeds/preview", json=preview.payload).status_code == 400
    assert preview.requests == []


def test_credential_and_transport_errors_cannot_expose_request_secrets(preview, monkeypatch):
    doc = json.loads(preview.manager.path.read_text())
    doc["connections"][0]["auth_mode"] = "bearer"
    preview.manager.path.write_text(json.dumps(doc))
    def bad_credential(*_args):
        raise CredentialError("private credential failure: PRIVATE-TOKEN")
    preview.manager.auth_headers = bad_credential
    result = preview.client.post("/api/feeds/preview", json=preview.payload)
    assert result.status_code == 400 and "PRIVATE-TOKEN" not in result.text
    assert preview.requests == []
    preview.manager.auth_headers = lambda *_args: {"Authorization": "Bearer PRIVATE-TOKEN"}
    def bad_network(url, **kwargs):
        raise httpx.ReadTimeout("PRIVATE-TOKEN " + url)
    monkeypatch.setattr(runtime, "download_feed", bad_network)
    result = preview.client.post("/api/feeds/preview", json=preview.payload)
    assert result.status_code == 400 and "PRIVATE-TOKEN" not in result.text and "publisher.example" not in result.text


def test_authenticated_preview_cannot_follow_cross_origin_redirect(preview, monkeypatch):
    doc = json.loads(preview.manager.path.read_text())
    doc["connections"][0]["auth_mode"] = "bearer"
    preview.manager.path.write_text(json.dumps(doc))
    preview.manager.auth_headers = lambda *_args: {"Authorization": "Bearer PRIVATE-TOKEN"}
    observed = []
    def handler(request):
        observed.append((str(request.url), request.headers.get("authorization")))
        return httpx.Response(302, headers={"location": "https://attacker.example/steal"})
    client = httpx.Client
    monkeypatch.setattr(feeds.httpx, "Client", lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(feeds, "_public_url", lambda value, **kwargs: validate_fetch_url(value))
    monkeypatch.setattr(runtime, "download_feed", feeds.download_feed)
    result = preview.client.post("/api/feeds/preview", json=preview.payload)
    assert result.status_code == 400 and "PRIVATE-TOKEN" not in result.text
    assert observed == [(preview.payload["url"], "Bearer PRIVATE-TOKEN")]


def test_preview_cancellation_and_single_flight_do_not_mutate_collection(preview, monkeypatch):
    cancelled = threading.Event()
    fields = {key: value for key, value in preview.payload.items() if key != "revision"}
    def cancel(url, **kwargs):
        with pytest.raises(runtime.ConnectionsError, match="already loading"):
            preview.manager.preview_feed(fields, expected_revision=4)
        cancelled.set()
        return {"url": url, "material": preview.material}
    monkeypatch.setattr(runtime, "download_feed", cancel)
    with pytest.raises(runtime.ConnectionsError, match="cancelled"):
        preview.manager.preview_feed(fields, expected_revision=4, cancel_event=cancelled)
    assert preview.manager._preview_cancel is None and not preview.manager._checks
    held = threading.Event()
    preview.manager._preview_cancel = held
    asyncio.run(preview.manager.stop())
    assert held.is_set()
