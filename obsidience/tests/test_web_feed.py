from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
import pytest

from obsidience.harness.web import feeds
from obsidience.harness.web.feeds import canonical_url
from obsidience.harness.web.runtime import WebError

_HTTPX_CLIENT = httpx.Client


def _public_url(value: object, *, previous_scheme: str | None = None) -> str:
    parsed = urlsplit(str(value))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise WebError("url must be public")
    if previous_scheme == "https" and parsed.scheme != "https":
        raise WebError("HTTPS redirects may not downgrade to HTTP")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def _client(monkeypatch, handler) -> None:
    monkeypatch.setattr(
        feeds.httpx,
        "Client",
        lambda **kwargs: _HTTPX_CLIENT(
            **kwargs,
            transport=httpx.MockTransport(handler),
        ),
    )
    monkeypatch.setattr(feeds, "_public_url", _public_url)


def test_feed_captures_exact_xml_and_returns_canonical_bounded_entries(monkeypatch):
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>World &amp; News</title>
<item><title>First &lt;story&gt;</title>
<link>https://news.example/story?utm_source=rss&amp;b=2&amp;a=1#top</link>
<pubDate>Tue, 03 Sep 2024 10:00:00 -0400</pubDate>
<description><![CDATA[<p>Hello <b>world</b>.</p><script>bad()</script>]]></description></item>
<item><title>Duplicate</title>
<link>https://news.example/story?a=1&amp;b=2&amp;fbclid=duplicate</link></item>
<item><title>No public link</title><link>file:///tmp/story</link></item>
</channel></rss>
"""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/feed":
            return httpx.Response(302, headers={"location": "/world.xml"})
        return httpx.Response(
            200,
            headers={"content-type": "application/rss+xml; charset=utf-8"},
            content=xml.encode(),
        )

    _client(monkeypatch, handler)
    captured = {}

    def ingest(**kwargs):
        captured.update(kwargs)
        return {
            "citation": "source://00000000-0000-0000-0000-000000000001",
            "content_sha256": "sha256:feed",
            "created": True,
        }

    monkeypatch.setattr(feeds, "ingest_source", ingest)
    result = feeds.fetch_feed(
        "https://publisher.example/feed#fragment",
        activation_key="source.added:research:run:Tasks/research/news",
    )

    assert captured["content"] == xml
    assert captured["source_ref"] == "https://publisher.example/world.xml"
    assert captured["media_type"] == "application/rss+xml"
    assert captured["activation_key"] == "source.added:research:run:Tasks/research/news"
    assert result["citation"].startswith("source://")
    assert result["feed_title"] == "World & News"
    assert result["entries"] == [
        {
            "title": "First",
            "url": "https://news.example/story?a=1&b=2",
            "published": "2024-09-03T14:00:00Z",
            "summary": "Hello world.",
        }
    ]
    assert "<" not in result["entries"][0]["summary"]


def test_atom_limit_is_clamped_and_updated_dates_are_utc(monkeypatch):
    entries = "".join(
        (
            f"<entry><title>Story {index}</title>"
            f"<link href='https://news.example/{index}?utm_medium=feed'/>"
            "<updated>2024-09-04T01:02:03+02:00</updated>"
            "<summary type='html'>&lt;p&gt;Short summary&lt;/p&gt;</summary></entry>"
        )
        for index in range(35)
    )
    xml = (
        "<?xml version='1.0' encoding='utf-8'?>"
        "<feed xmlns='http://www.w3.org/2005/Atom'><title>Atom</title>"
        f"{entries}</feed>"
    )

    _client(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            headers={"content-type": "application/atom+xml"},
            content=xml.encode(),
        ),
    )
    monkeypatch.setattr(
        feeds,
        "ingest_source",
        lambda **kwargs: {
            "citation": "source://00000000-0000-0000-0000-000000000002",
            "content_sha256": "sha256:atom",
            "created": False,
        },
    )

    result = feeds.fetch_feed("https://publisher.example/atom", limit=99)

    assert len(result["entries"]) == 30
    assert result["entries"][0] == {
        "title": "Story 0",
        "url": "https://news.example/0",
        "published": "2024-09-03T23:02:03Z",
        "summary": "Short summary",
    }


@pytest.mark.parametrize(
    ("content_type", "content", "message"),
    [
        ("text/html", b"<html></html>", "unsupported web feed content type"),
        ("application/xml", b"\xff", "not strict UTF-8"),
        ("application/xml", b"<document/>", "not an RSS or Atom feed"),
        (
            "application/rss+xml",
            b"<rss version='2.0'><channel><item></rss>",
            "XML is malformed",
        ),
        (
            "application/rss+xml",
            b"<rss version='2.0'><channel><title>Empty</title></channel></rss>",
            "contains no entries",
        ),
    ],
)
def test_feed_rejects_non_feed_material(monkeypatch, content_type, content, message):
    _client(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            headers={"content-type": content_type},
            content=content,
        ),
    )
    monkeypatch.setattr(
        feeds,
        "ingest_source",
        lambda **kwargs: pytest.fail("rejected material must not reach Source"),
    )

    with pytest.raises(WebError, match=message):
        feeds.fetch_feed("https://publisher.example/feed")


def test_feed_preserves_web_redirect_and_response_size_guards(monkeypatch):
    _client(
        monkeypatch,
        lambda request: httpx.Response(302, headers={"location": "http://other.example/feed"}),
    )
    with pytest.raises(WebError, match="may not downgrade"):
        feeds.fetch_feed("https://publisher.example/feed")

    monkeypatch.setattr(feeds, "MAX_RESPONSE_BYTES", 8)
    _client(
        monkeypatch,
        lambda request: httpx.Response(
            200,
            headers={"content-type": "application/rss+xml"},
            content=b"123456789",
        ),
    )
    with pytest.raises(WebError, match="2 MB acquisition bound"):
        feeds.fetch_feed("https://publisher.example/feed")


def test_feed_adapter_reuses_research_activation_and_labels_entries_as_leads(monkeypatch):
    from obsidience.harness.capabilities.web import feed
    from obsidience.harness.knowledge import source

    seen = {}

    def fetch(url, limit, *, activation_key):
        seen.update(url=url, limit=limit, activation_key=activation_key)
        return {
            "url": url,
            "feed_title": "Publisher World",
            "citation": "source://00000000-0000-0000-0000-000000000003",
            "content_sha256": "sha256:rss",
            "created": True,
            "entries": [
                {
                    "title": "Story",
                    "url": "https://news.example/story",
                    "published": "2024-09-04T01:02:03Z",
                    "summary": "Lead text",
                }
            ],
        }

    monkeypatch.setattr(feeds, "fetch_feed", fetch)
    monkeypatch.setattr(source, "research_activation_key", lambda context: "source.added:key")

    output = feed.execute(
        {"url": "https://publisher.example/feed", "limit": 7},
        {"task": "Tasks/research/news"},
    )

    assert seen == {
        "url": "https://publisher.example/feed",
        "limit": 7,
        "activation_key": "source.added:key",
    }
    assert "entries remain discovery leads, not story evidence" in output
    assert "source://00000000-0000-0000-0000-000000000003" in output


def test_web_feed_articles_match_registered_capability():
    root = Path(__file__).parents[1] / "vault"
    tool = (root / "Tools/web.feed.md").read_text()
    skill = (root / "Skills/web.feed.md").read_text()

    assert "binding: capability:web.feed" in tool
    assert "source: obsidience/harness/capabilities/web/feed.py" in tool
    assert "tool: '[[Tools/web.feed]]'" in skill
    assert "story evidence" in tool


@pytest.mark.parametrize("host", ["bbc.co.uk", "www.bbc.co.uk", "feeds.bbc.co.uk", "bbc.com", "www.bbc.com"])
def test_bbc_identity_removes_only_its_attested_distribution_parameters(host):
    assert canonical_url(f"https://{host}/news/articles/report?at_campaign=rss&at_medium=RSS&edition=asia&maca=keep") == (
        f"https://{host}/news/articles/report?edition=asia&maca=keep")


@pytest.mark.parametrize("host", ["dw.com", "www.dw.com", "rss.dw.com"])
def test_dw_identity_removes_only_its_attested_distribution_parameter(host):
    assert canonical_url(f"https://{host}/en/report/a-123?maca=rss-en&lang=en&at_campaign=keep") == (
        f"https://{host}/en/report/a-123?at_campaign=keep&lang=en")


@pytest.mark.parametrize("host", ["news.example", "notbbc.com", "bbc.co.uk.example", "dw.com.example", "notdw.com"])
def test_unknown_publishers_keep_those_query_semantics(host):
    query = "at_campaign=report&at_medium=full&maca=version"
    assert canonical_url(f"https://{host}/article?{query}") == f"https://{host}/article?{query}"

