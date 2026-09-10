from __future__ import annotations

import httpx
import pytest

from obsidience.harness.capabilities.web import fetch
from obsidience.harness.knowledge.vault import resolver
from obsidience.harness.web import runtime


def _result(content: str, *, created: bool = True) -> dict:
    return {
        "url": "https://example.com/report",
        "content": content,
        "citation": "source://11111111-1111-4111-8111-111111111111",
        "content_sha256": "sha256:" + "a" * 64,
        "created": created,
    }


def test_fetch_returns_bounded_source_page_with_explicit_unread_tail() -> None:
    content = "A" * fetch.MAX_FETCH_PREVIEW_CHARS + "UNREAD"

    rendered = fetch._render_result(_result(content))

    assert "Fetched and captured https://example.com/report" in rendered
    assert "source://11111111-1111-4111-8111-111111111111" in rendered
    assert "sha256:" + "a" * 64 in rendered
    assert (
        f"Characters 0-{fetch.MAX_FETCH_PREVIEW_CHARS} of {len(content)}. "
        "Unread tail: 6 characters."
    ) in rendered
    assert "Use facts visible in this page with its citation" in rendered
    assert "only when a needed claim or detail is absent" in rendered
    assert "the unread tail is optional and has not been inspected" in rendered
    assert f"offset {fetch.MAX_FETCH_PREVIEW_CHARS}" in rendered
    assert rendered.endswith("A" * fetch.MAX_FETCH_PREVIEW_CHARS)
    assert "UNREAD" not in rendered
    assert "before relying on" not in rendered


def test_fetch_returns_complete_short_source_page() -> None:
    rendered = fetch._render_result(_result("Complete evidence.", created=False))

    assert "Fetched and verified https://example.com/report" in rendered
    assert "Characters 0-18 of 18. End of Source." in rendered
    assert rendered.endswith("Complete evidence.")
    assert "Unread tail" not in rendered


def test_fetch_captures_complete_extraction_before_returning_first_page(monkeypatch) -> None:
    body = "Evidence " * 1_000
    response_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                text=f"<html><title>Report</title><main>{body}</main></html>",
                request=request,
            )
        )
    )
    captured: dict = {}

    monkeypatch.setattr(runtime, "_public_url", lambda value, **_kwargs: str(value))
    monkeypatch.setattr(runtime.httpx, "Client", lambda **_kwargs: response_client)

    def ingest_source(**kwargs):
        captured.update(kwargs)
        return {
            "citation": "source://11111111-1111-4111-8111-111111111111",
            "content_sha256": "sha256:" + "a" * 64,
            "created": True,
        }

    monkeypatch.setattr(runtime, "ingest_source", ingest_source)

    result = runtime.fetch_web("https://example.com/report", activation_key="run:test")
    rendered = fetch._render_result(result)

    assert captured["content"] == result["content"]
    assert captured["content"].endswith(body.strip())
    assert len(captured["content"]) > fetch.MAX_FETCH_PREVIEW_CHARS
    assert captured["activation_key"] == "run:test"
    assert body.strip() not in rendered
    assert "Unread tail:" in rendered


def test_html_extraction_preserves_structure_and_resolves_links() -> None:
    response = httpx.Response(
        200,
        headers={"content-type": "text/html; charset=utf-8"},
        request=httpx.Request("GET", "https://example.com/docs/current/index.html"),
    )
    content, media_type = runtime._decode_response(response, b"""
        <html><head><title>Research reference</title></head><body>
        <h1>Research reference</h1><h2>Parameters</h2>
        <ul><li>Keep <strong>exact</strong> names</li><li>Read the source</li></ul>
        <table><thead><tr><th>Field</th><th>Type</th></tr></thead>
        <tbody><tr><td>count</td><td>integer</td></tr></tbody></table>
        <pre><code>SELECT count(*)\nFROM events_;</code></pre>
        <p><a href="../schema?q=field&amp;lang=en#count">Schema</a> and
        <a href="//reference.example.net/table_(v2)">Reference</a>.</p>
        <script>SECRET_SCRIPT</script><style>SECRET_STYLE</style>
        <svg><text>SECRET_SVG</text></svg><template>SECRET_TEMPLATE</template>
        <img src="https://example.com/tracking.png" alt="Diagram description">
        </body></html>
    """)

    assert media_type == "text/markdown"
    assert content.count("# Research reference") == 1
    assert "## Parameters" in content
    assert "- Keep **exact** names" in content
    assert "| Field | Type |" in content
    assert "| count | integer |" in content
    assert "```\nSELECT count(*)\nFROM events_;\n```" in content
    assert "[Schema](https://example.com/docs/schema?q=field&lang=en#count)" in content
    assert "[Reference](https://reference.example.net/table_%28v2%29)" in content
    assert "Diagram description" in content
    assert "tracking.png" not in content
    assert "SECRET_" not in content


@pytest.mark.parametrize("href", [
    "javascript:alert(1)",
    "data:text/html,hello",
    "file:///etc/passwd",
    "mailto:person@example.com",
    "https://user:secret@example.com/private",
    "https://example.com:bad/path",
    "https://[broken/path",
    "#same-page-section",
    "https://example.com/" + "a" * 2_000,
])
def test_html_extraction_drops_unusable_link_targets_but_keeps_labels(href: str) -> None:
    response = httpx.Response(
        200,
        headers={"content-type": "text/html"},
        request=httpx.Request("GET", "https://example.com/report"),
    )

    content, _ = runtime._decode_response(response, f'<p><a href="{href}">Label</a></p>'.encode())

    assert content == "Label"


@pytest.mark.parametrize("content_type,expected_type", [
    ("application/json", "application/json"),
    ("text/plain", "text/plain"),
    ("text/markdown", "text/plain"),
])
def test_non_html_extraction_retains_literal_source(content_type: str, expected_type: str) -> None:
    response = httpx.Response(200, headers={"content-type": content_type})
    material = b'Literal <code> and [reference](../source)'

    content, media_type = runtime._decode_response(response, material)

    assert content == material.decode()
    assert media_type == expected_type


def test_html_links_are_captured_against_final_redirect_url_without_following_them(monkeypatch) -> None:
    requested: list[str] = []
    captured: dict = {}

    def serve(request):
        requested.append(str(request.url))
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "/docs/index.html"}, request=request)
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            text='<p><a href="schema.html">Read schema</a></p>',
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(serve))
    monkeypatch.setattr(runtime, "_public_url", lambda value, **_kwargs: str(value))
    monkeypatch.setattr(runtime.httpx, "Client", lambda **_kwargs: client)

    def capture(**kwargs):
        captured.update(kwargs)
        return {"citation": "source://test", "content_sha256": "sha256:test", "created": True}

    monkeypatch.setattr(runtime, "ingest_source", capture)

    result = runtime.fetch_web("https://example.com/start", activation_key="run:test")

    assert requested == ["https://example.com/start", "https://example.com/docs/index.html"]
    assert captured["content"] == "[Read schema](https://example.com/docs/schema.html)"
    assert captured["source_ref"] == "https://example.com/docs/index.html"
    assert captured["activation_key"] == "run:test"
    assert result["content"] == captured["content"]


def test_html_extraction_retains_existing_character_bound(monkeypatch) -> None:
    monkeypatch.setattr(runtime, "MAX_FETCH_CHARS", 40)
    response = httpx.Response(
        200,
        headers={"content-type": "text/html"},
        request=httpx.Request("GET", "https://example.com/report"),
    )

    content, _ = runtime._decode_response(response, ("<p>" + "Evidence " * 100 + "</p>").encode())

    assert len(content) == 40


def test_deeply_nested_html_returns_a_bounded_extraction_failure() -> None:
    response = httpx.Response(
        200,
        headers={"content-type": "text/html"},
        request=httpx.Request("GET", "https://example.com/report"),
    )
    material = b"<div>" * 1_000 + b"Text" + b"</div>" * 1_000

    with pytest.raises(runtime.WebError, match="HTML nesting exceeds"):
        runtime._decode_response(response, material)


@pytest.mark.parametrize("failure", ["private_redirect", "response_bound"])
def test_fetch_safety_failure_never_captures_source(monkeypatch, failure: str) -> None:
    requested: list[str] = []

    def serve(request):
        requested.append(str(request.url))
        if failure == "private_redirect":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/private"}, request=request)
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"A" * 17, request=request)

    def resolve(host, port, **kwargs):
        address = "127.0.0.1" if host == "127.0.0.1" else "93.184.216.34"
        return [(runtime.socket.AF_INET, runtime.socket.SOCK_STREAM, 6, "", (address, port))]

    client = httpx.Client(transport=httpx.MockTransport(serve))
    monkeypatch.setattr(runtime.httpx, "Client", lambda **_kwargs: client)
    monkeypatch.setattr(runtime.socket, "getaddrinfo", resolve)
    monkeypatch.setattr(runtime, "MAX_RESPONSE_BYTES", 16)
    monkeypatch.setattr(runtime, "ingest_source", lambda **_kwargs: pytest.fail("Unsafe Source capture"))

    message = "non-public address" if failure == "private_redirect" else "acquisition bound"
    with pytest.raises(runtime.WebError, match=message):
        runtime.fetch_web("http://example.com/start")

    assert requested == ["http://example.com/start"]


def _article_html(*, href: str = '/evidence/report_(v2)') -> bytes:
    return f'''<html><head><title>Flood barrier opens</title>
      <meta name="author" content="Reporter Name">
      <meta property="article:published_time" content="2026-09-06T10:15:00Z">
      <meta property="og:type" content="article"></head><body>
      <nav>{'<a href="/section">NAVIGATION_SENTINEL</a> ' * 60}</nav>
      <article><h1>Flood barrier opens</h1>
      <p>A new flood barrier opened in Rotterdam on Sunday after engineers
      completed its final safety inspection. The city said the gates protect
      homes along the lower river and can close when heavy rain raises the
      water level. Officials described this opening as the first stage of a
      longer project, with further work still subject to funding.</p>
      <p>The <a href="{href}">engineering report</a> describes the operating
      limits and monitoring programme. Residents will receive advance notice
      of the next scheduled test, according to the published statement.</p>
      </article><footer>FOOTER_SENTINEL Privacy and subscriptions</footer>
      </body></html>'''.encode()


def test_article_extraction_starts_with_evidence_and_retains_attribution_and_links() -> None:
    response = httpx.Response(200, headers={"content-type": "text/html"},
                              request=httpx.Request("GET", "https://example.com/news/story"))
    content, media = runtime._decode_response(response, _article_html())

    assert media == "text/markdown"
    assert "Reporter Name" in content
    assert "2026-09-06" in content
    assert "subject to funding" in content
    assert "[engineering report](https://example.com/evidence/report_%28v2%29)" in content
    assert "NAVIGATION_SENTINEL" not in content
    assert "FOOTER_SENTINEL" not in content
    assert content.index("A new flood barrier") < 1_000


@pytest.mark.parametrize("href", ["javascript:alert(1)", "https://user:secret@example.com/report",
                                  "https://example.com:bad/report", "file:///etc/passwd"])
def test_article_extraction_uses_same_safe_outgoing_link_rules(href: str) -> None:
    response = httpx.Response(200, headers={"content-type": "text/html"},
                              request=httpx.Request("GET", "https://example.com/news/story"))
    content, _ = runtime._decode_response(response, _article_html(href=href))
    assert "engineering report" in content
    assert href not in content
    assert "[engineering report]" not in content


def test_sparse_marked_article_falls_back_without_losing_its_short_body() -> None:
    response = httpx.Response(200, headers={"content-type": "text/html"},
                              request=httpx.Request("GET", "https://example.com/short"))
    content, _ = runtime._decode_response(response, b'<article><p>Short notice.</p></article>')
    assert content == "Short notice."


@pytest.mark.parametrize("args", [
    {}, {"url": "https://example.com", "urls": ["https://example.net"]},
    {"urls": []}, {"urls": "https://example.com"},
    {"urls": ["https://example.com"] * 11},
    {"urls": ["https://example.com", 9]},
    {"urls": ["https://example.com", "file:///tmp/evidence"]},
    {"urls": ["https://example.com", "https://user:secret@example.net"]},
    {"urls": ["https://example.com/story#a", "https://example.com/story#b"]},
    {"url": "https://[malformed/path"}, {"url": "https://example.com:invalid/path"},
    {"url": "https://example.com", "ignored": True},
])
def test_batch_validates_every_argument_before_starting_any_fetch(monkeypatch, args: dict) -> None:
    monkeypatch.setattr(runtime, "fetch_web", lambda *_args, **_kwargs: pytest.fail("dispatched fetch"))
    assert fetch.execute(args, {}).startswith("Web fetch failed:")


def test_batch_fetch_has_bounded_concurrency_ordered_results_and_partial_failures(monkeypatch) -> None:
    import json
    import threading

    entered = threading.Barrier(4)
    lock = threading.Lock()
    active = maximum = 0
    cancel_event = threading.Event()
    seen: list[tuple] = []

    def acquire(url, *, activation_key, cancel_event):
        nonlocal active, maximum
        index = int(url.rsplit('/', 1)[-1])
        with lock:
            active += 1
            maximum = max(maximum, active)
            seen.append((url, activation_key, cancel_event))
        try:
            if index < 4:
                entered.wait(timeout=3)
            if index == 2:
                raise runtime.WebError("HTTP 503 unavailable")
            return {**_result(f"Article {index}"), "url": url}
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(runtime, "fetch_web", acquire)
    urls = [f"https://example.com/{index}" for index in range(10)]
    response = json.loads(fetch.execute({"urls": urls}, {"_capability_cancel_event": cancel_event}))
    results = response["results"]

    assert [item["url"] for item in results] == urls
    assert [item["ok"] for item in results] == [index != 2 for index in range(10)]
    assert "503" in results[2]["result"]
    assert results[3]["result"].startswith("Fetched and captured")
    assert results[3]["result"].endswith("Article 3")
    assert maximum == 4
    assert active == 0
    assert all(row[2] is cancel_event for row in seen)


def test_batch_output_bound_includes_json_escaping_urls_and_exact_returned_ranges(monkeypatch) -> None:
    import json
    import re

    content = ('Evidence "quoted"\n\t' + chr(1)) * 2_000
    urls = [f"https://example.com/{index}/" + 'q' * 1_850 for index in range(10)]
    monkeypatch.setattr(runtime, "fetch_web", lambda url, **_kwargs: {**_result(content), "url": url})
    output = fetch.execute({"urls": urls}, {})
    assert len(output) <= fetch.MAX_FETCH_BATCH_OUTPUT_CHARS
    entries = json.loads(output)["results"]
    assert len(entries) == 10
    for entry in entries:
        rendered = entry["result"]
        match = re.search(r'Characters 0-(\d+) of (\d+)\.', rendered)
        assert match is not None
        end, total = map(int, match.groups())
        assert 0 < end <= fetch.MAX_FETCH_PREVIEW_CHARS
        assert total == len(content)
        assert rendered.endswith(content[:end])
        assert f"offset {end}" in rendered


def test_single_fetch_retains_success_protocol_and_passes_cancellation(monkeypatch) -> None:
    import threading
    event = threading.Event()
    def acquire(url, **kwargs):
        assert kwargs["cancel_event"] is event
        return _result("Single evidence.")
    monkeypatch.setattr(runtime, "fetch_web", acquire)
    assert fetch.execute({"url": "https://example.com/report"}, {
        "_capability_cancel_event": event,
    }).startswith("Fetched and captured")


def test_fetch_cancelled_before_request_never_captures_source(monkeypatch) -> None:
    import threading
    event = threading.Event()
    event.set()
    monkeypatch.setattr(runtime, "_public_url", lambda *_args: pytest.fail("resolved URL after cancellation"))
    monkeypatch.setattr(runtime, "ingest_source", lambda **_kwargs: pytest.fail("captured after cancellation"))
    with pytest.raises(runtime.WebError, match="cancelled"):
        runtime.fetch_web("https://example.com/report", cancel_event=event)


def test_fetch_cancelled_during_extraction_never_commits_source(monkeypatch) -> None:
    import threading
    event = threading.Event()
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        200, headers={"content-type": "text/plain"}, text="Evidence", request=request,
    )))
    monkeypatch.setattr(runtime, "_public_url", lambda value, **_kwargs: str(value))
    monkeypatch.setattr(runtime.httpx, "Client", lambda **_kwargs: client)
    def decode(*args):
        event.set()
        return "Evidence", "text/plain"
    monkeypatch.setattr(runtime, "_decode_response", decode)
    monkeypatch.setattr(runtime, "ingest_source", lambda **_kwargs: pytest.fail("captured after cancellation"))
    with pytest.raises(runtime.WebError, match="cancelled"):
        runtime.fetch_web("https://example.com/report", cancel_event=event)


def test_batch_failure_envelope_remains_bounded_for_long_urls_and_escaped_errors(monkeypatch) -> None:
    import json
    urls = [f"https://example.com/{index}/" + 'q' * 1_850 for index in range(10)]
    def failed(*args, **kwargs):
        raise runtime.WebError(chr(1) * 1_000)
    monkeypatch.setattr(runtime, "fetch_web", failed)
    output = fetch.execute({"urls": urls}, {})
    assert len(output) <= fetch.MAX_FETCH_BATCH_OUTPUT_CHARS
    assert len(json.loads(output)["results"]) == 10
    assert all(not row["ok"] for row in json.loads(output)["results"])


def test_batch_cancel_event_prevents_queued_fetches_from_starting_network(monkeypatch) -> None:
    import json
    import threading
    event = threading.Event()
    event.set()
    monkeypatch.setattr(runtime, "_public_url", lambda *_args: pytest.fail("started network after STOP"))
    urls = [f"https://example.com/{index}" for index in range(10)]
    output = json.loads(fetch.execute({"urls": urls}, {"_capability_cancel_event": event}))
    assert [row["url"] for row in output["results"]] == urls
    assert all(not row["ok"] and "cancelled" in row["result"] for row in output["results"])
