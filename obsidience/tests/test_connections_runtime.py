"""Connections feed real immutable Sources using isolated runtime and network fixtures."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace as NS

import httpx
import pytest

from obsidience.harness import config
from obsidience.harness.connections import runtime
from obsidience.harness.execution import scheduler
from obsidience.harness.knowledge import source
from obsidience.harness.web import feeds
from obsidience.harness.web.runtime import validate_fetch_url


def xml(*, title="Story", summary="Full description", second=False):
    extra = "<item><guid>two</guid><title>Second</title><link>https://publisher.example/two</link></item>" if second else ""
    return (f"<rss version='2.0'><channel><title>Feed</title><item><guid>one</guid>"
            f"<title>{title}</title><link>https://publisher.example/story</link>"
            f"<description><![CDATA[<p>{summary}</p>]]></description>"
            f"<pubDate>Wed, 09 Sep 2026 10:00:00 GMT</pubDate></item>{extra}</channel></rss>").encode()


@pytest.fixture
def setup(tmp_path, monkeypatch, isolated_task_ledger):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config.CONFIG, "vault_dir", tmp_path / "obsidience/vault")
    sync = isolated_task_ledger.sync
    monkeypatch.setattr(isolated_task_ledger, "sync", lambda: sync(embed=False))
    monkeypatch.setattr(feeds, "_public_url", lambda value, **_kwargs: validate_fetch_url(value))
    events = []

    def enqueue(event, params, **_kwargs):
        events.append((event, deepcopy(params)))
        # This fixture substitutes only Task admission; Source persistence is real.
        isolated_task_ledger.mark_source_event_dispatched(params["source_id"], time.time())
        return [{"task": "Tasks/research/distill", "state": "started"}]

    monkeypatch.setattr(scheduler, "enqueue_named_event", enqueue)
    from obsidience.harness.knowledge.vault import write_note
    write_note("Knowledge/World/World.md", {"kind": "knowledge", "title": "World", "auto_curate": True}, "Existing destination.")
    manager = runtime.ConnectionsManager(tmp_path / "connections.json", isolated_task_ledger)
    snapshot = manager.save_connection({"name": "Publisher", "kind": "rss",
        "url": "https://publisher.example/feed"}, expected_revision=0)
    connection_id = snapshot["connections"][0]["id"]
    snapshot = manager.save_feed({"name": "World", "connection_id": connection_id,
        "url": "https://publisher.example/world", "enabled": False, "destination_ref": "Knowledge/World/World"}, expected_revision=1)
    requests = []
    state = NS(manager=manager, index=isolated_task_ledger, events=events, requests=requests,
               connection_id=connection_id, feed_id=snapshot["feeds"][0]["id"], material=xml())

    def download(url, **kwargs):
        requests.append((url, kwargs))
        return {"status": 200, "url": url, "material": state.material,
                "etag": '"edition"', "last_modified": "Wed, 09 Sep 2026 10:00:00 GMT"}

    state.download = download
    monkeypatch.setattr(runtime, "download_feed", download)
    return state


def test_empty_registry_is_unseeded_and_creates_only_after_owner_save(tmp_path, isolated_task_ledger):
    path = tmp_path / "connections.json"
    manager = runtime.ConnectionsManager(path, isolated_task_ledger)
    snapshot = manager.snapshot()
    assert snapshot["schema"] == runtime.SCHEMA and snapshot["revision"] == 0
    assert snapshot["connections"] == snapshot["feeds"] == []
    assert not path.exists()


def test_revision_and_dependency_guards_preserve_saved_definitions(setup):
    manager = setup.manager
    before = manager.path.read_bytes()
    with pytest.raises(runtime.RevisionConflict):
        manager.save_feed({"id": setup.feed_id, "name": "Stale"}, expected_revision=1)
    with pytest.raises(runtime.ConnectionsError, match="Feeds"):
        manager.delete_connection(setup.connection_id, expected_revision=2)
    assert manager.path.read_bytes() == before
    snapshot = manager.delete_feed(setup.feed_id, expected_revision=2)
    assert snapshot["feeds"] == []
    snapshot = manager.delete_connection(setup.connection_id, expected_revision=3)
    assert snapshot["connections"] == [] and snapshot["revision"] == 4
    assert manager.path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("changes", [
    {"url": "https://other.example/world"}, {"url": "http://publisher.example/world"},
    {"interval_minutes": 4}, {"interval_minutes": True}, {"item_limit": 31},
    {"max_active_articles": 0}, {"max_active_articles": 1001}, {"max_active_articles": True},
    {"distill_instructions": "x" * 501}, {"distill_instructions": "text\x00hidden"},
    {"distill_instructions": []},
    {"enabled": 1}, {"token": "PRIVATE"},
])
def test_invalid_feed_edits_are_rejected_without_changing_revision(setup, changes):
    with pytest.raises(runtime.ConnectionsError):
        setup.manager.save_feed({"id": setup.feed_id, **changes}, expected_revision=2)
    assert setup.manager.snapshot()["revision"] == 2


def test_api_descriptors_cannot_silently_acquire_rss_feed_authority(setup):
    with pytest.raises(runtime.ConnectionsError, match="RSS"):
        setup.manager.save_connection({"id": setup.connection_id, "kind": "http_api"}, expected_revision=2)
    with pytest.raises(runtime.ConnectionsError, match="credential"):
        setup.manager.save_connection({"id": setup.connection_id, "url": "https://publisher.example/?token=PRIVATE"}, expected_revision=2)
    with pytest.raises(runtime.ConnectionsError):
        setup.manager.save_connection({"id": setup.connection_id, "url": "https://user:PRIVATE@publisher.example/"}, expected_revision=2)


def test_old_feed_definitions_receive_defaults_without_read_mutation(setup):
    path = setup.manager.path
    saved = json.loads(path.read_text())
    for name in ("max_active_articles", "distill_instructions"):
        saved["feeds"][0].pop(name, None)
    path.write_text(json.dumps(saved))
    before = path.read_bytes()
    feed = setup.manager.snapshot()["feeds"][0]
    assert feed["max_active_articles"] == 10
    assert feed["distill_instructions"] == ""
    assert feed["active_article_count"] == 0
    assert feed["retention_status"] == "within_limit"
    assert path.read_bytes() == before


def test_instruction_edits_bind_only_new_item_versions(setup):
    manager = setup.manager
    first_config = manager.save_feed({"id": setup.feed_id,
        "distill_instructions": "Focus on the scientific result.\r\nInclude qualifications."}, expected_revision=2)
    expected = "Focus on the scientific result.\nInclude qualifications."
    assert first_config["feeds"][0]["distill_instructions"] == expected
    captured = asyncio.run(manager.check_feed(setup.feed_id))["feeds"][0]
    first_binding = setup.index.feed_source_binding(captured["last_source_id"])
    first_material = source.get_source(captured["last_source_id"])["content_sha256"]
    assert first_binding["distill_instructions"] == expected
    manager.save_feed({"id": setup.feed_id, "distill_instructions": "Explain the local impact."}, expected_revision=3)
    repeated = asyncio.run(manager.check_feed(setup.feed_id))["feeds"][0]
    assert repeated["last_new_count"] == 0
    assert setup.index.feed_source_binding(captured["last_source_id"]) == first_binding
    assert source.get_source(captured["last_source_id"])["content_sha256"] == first_material
    assert len(setup.events) == 1
    setup.material = xml(title="A new item version")
    changed = asyncio.run(manager.check_feed(setup.feed_id))["feeds"][0]
    assert setup.index.feed_source_binding(changed["last_source_id"])["distill_instructions"] == "Explain the local impact."
    assert len(setup.events) == 2


def test_policy_save_reconciles_quiet_feed_through_review_owner_only(setup, monkeypatch):
    from obsidience.harness.knowledge import curation

    calls = []
    def reconcile(feed_id, *, definition_guard):
        with definition_guard() as binding:
            calls.append(binding)
        return {"archived_count": 0, "retention_status": "within_limit"}

    monkeypatch.setattr(curation, "reconcile_feed_retention", reconcile)
    result = setup.manager.save_feed({"id": setup.feed_id, "max_active_articles": 4}, expected_revision=2)
    assert len(calls) == 1 and calls[0]["max_active_articles"] == 4
    assert calls[0]["auto_curate"] is True
    assert result["retention_result"]["archived_count"] == 0
    assert setup.requests == setup.events == []
    setup.manager.snapshot()
    setup.manager.save_feed({"id": setup.feed_id, "distill_instructions": "Keep it concise."}, expected_revision=3)
    setup.manager.save_feed({"id": setup.feed_id, "enabled": False}, expected_revision=4)
    assert len(calls) == 1


def test_snapshot_checks_credential_existence_without_decryption_and_allows_reentry(setup):
    manager = setup.manager
    calls = []
    manager.auth_headers = lambda *_args: pytest.fail("snapshot decrypted a credential")
    manager.credential_ready = lambda identifier: calls.append(manager.connection(identifier)["id"]) or True
    snapshot = manager.save_connection({"id": setup.connection_id, "auth_mode": "bearer"}, expected_revision=2)
    assert snapshot["connections"][0]["credential_ready"] is True
    assert snapshot["connections"][0]["credential_set"] is True
    assert calls == [setup.connection_id]
    manager.record_connection_check(setup.connection_id, 2, "ready", "stale")
    assert manager.snapshot()["connections"][0]["status"] == "unchecked"
    manager.record_connection_check(setup.connection_id, 3, "ready")
    assert manager.snapshot()["connections"][0]["status"] == "ready"


def test_complete_item_capture_dedupes_retries_and_preserves_updated_versions(setup):
    manager = setup.manager
    summary = "Long source paragraph. " * 70
    setup.material = xml(summary=summary)
    first = asyncio.run(manager.check_feed(setup.feed_id))
    feed = first["feeds"][0]
    assert feed["enabled"] is False  # explicit one-shot check leaves scheduling paused
    assert feed["item_count"] == feed["source_count"] == 1
    assert feed["last_new_count"] == 1 and feed["last_error"] == ""
    document = source.get_source(feed["last_source_id"])
    entry = json.loads(document["content"])
    assert entry["record_type"] == "parsed_rss_item"
    assert entry["entry"]["summary"] == f"<p>{summary}</p>"
    assert entry["reporting_url"] == "https://publisher.example/story"
    assert document["source_ref"].startswith("feed://" + setup.feed_id + "/")
    assert document["source_type"] == "document"
    assert feed["last_source_path"].endswith(document["path"])
    second = asyncio.run(manager.check_feed(setup.feed_id))["feeds"][0]
    assert second["source_count"] == 1 and second["last_new_count"] == 0
    assert setup.requests[-1][1]["etag"] == '"edition"'
    setup.material = xml(title="Updated report", summary=summary)
    third = asyncio.run(manager.check_feed(setup.feed_id))["feeds"][0]
    assert third["item_count"] == 1 and third["source_count"] == 2
    assert third["last_source_id"] != feed["last_source_id"]
    assert source.get_source(feed["last_source_id"])["content"] == document["content"]
    assert [event for event, _ in setup.events] == ["source.added", "source.added"]


def test_reappearing_known_version_becomes_current_without_new_source_or_dispatch(setup):
    first = asyncio.run(setup.manager.check_feed(setup.feed_id))["feeds"][0]
    setup.material = xml(title="Second version")
    second = asyncio.run(setup.manager.check_feed(setup.feed_id))["feeds"][0]
    assert second["last_source_id"] != first["last_source_id"]
    setup.material = xml()
    reverted = asyncio.run(setup.manager.check_feed(setup.feed_id))["feeds"][0]
    assert reverted["last_source_id"] == first["last_source_id"]
    assert reverted["item_count"] == 1 and reverted["source_count"] == 2
    assert reverted["last_new_count"] == 0
    current = setup.manager.items()["items"]
    assert len(current) == 1 and current[0]["source_id"] == first["last_source_id"]
    assert setup.manager.item(current[0]["source_id"])["title"] == "Story"
    assert len(setup.index.sources()) == len(setup.events) == 2


def test_feed_receipt_migration_retains_existing_sources(setup):
    asyncio.run(setup.manager.check_feed(setup.feed_id))
    with setup.index.lock, setup.index.db:
        setup.index.db.execute("ALTER TABLE feed_items DROP COLUMN last_seen_at")
    setup.index._migrate()
    assert setup.manager.items()["items"][0]["title"] == "Story"
    asyncio.run(setup.manager.check_feed(setup.feed_id))
    assert setup.manager.snapshot()["feeds"][0]["source_count"] == 1
    assert len(setup.events) == 1


def test_feed_receipt_failure_rolls_back_source_and_retries_one_atomic_capture(setup):
    with setup.index.lock, setup.index.db:
        setup.index.db.execute("CREATE TEMP TRIGGER fail_feed_receipt BEFORE INSERT ON feed_items "
                               "BEGIN SELECT RAISE(ABORT, 'injected receipt failure'); END")
    failed = asyncio.run(setup.manager.check_feed(setup.feed_id))["feeds"][0]
    assert failed["last_error"] and failed["source_count"] == 0
    assert setup.index.feed_runtime(setup.feed_id).get("etag", "") == ""
    assert setup.index.sources() == [] and setup.events == []
    with setup.index.lock, setup.index.db:
        setup.index.db.execute("DROP TRIGGER fail_feed_receipt")
    restored = runtime.ConnectionsManager(setup.manager.path, setup.index)
    success = asyncio.run(restored.check_feed(setup.feed_id))["feeds"][0]
    assert success["source_count"] == 1 and success["last_error"] == ""
    assert len(setup.index.sources()) == len(setup.events) == 1


def test_credential_change_invalidates_http_checkpoint_without_losing_sources(setup):
    asyncio.run(setup.manager.check_feed(setup.feed_id))
    setup.manager.record_connection_check(setup.connection_id, 2, "ready")
    changed = setup.manager.credentials_changed(setup.connection_id, expected_revision=2)
    assert changed["revision"] == 3
    assert changed["connections"][0]["status"] == "unchecked"
    assert changed["feeds"][0]["source_count"] == 1
    state = setup.index.feed_runtime(setup.feed_id)
    assert state["etag"] == state["last_modified"] == state["definition_fingerprint"] == ""
    assert state["next_check"] == 0
    asyncio.run(setup.manager.check_feed(setup.feed_id))
    assert setup.requests[-1][1]["etag"] == setup.requests[-1][1]["last_modified"] == ""
    assert len(setup.index.sources()) == len(setup.events) == 1


def test_not_modified_response_preserves_source_receipt_and_checkpoint(setup, monkeypatch):
    asyncio.run(setup.manager.check_feed(setup.feed_id))
    before = setup.manager.snapshot()["feeds"][0]
    monkeypatch.setattr(runtime, "download_feed", lambda *_args, **_kwargs: {"status": 304})
    after = asyncio.run(setup.manager.check_feed(setup.feed_id))["feeds"][0]
    assert after["last_source_id"] == before["last_source_id"]
    assert after["source_count"] == 1 and after["last_new_count"] == 0
    assert setup.index.feed_runtime(setup.feed_id)["etag"] == '"edition"'
    assert len(setup.events) == 1


def test_partial_batch_cannot_advance_http_checkpoint(setup, monkeypatch):
    setup.material = xml(second=True)
    original = source.ingest_source
    attempts = 0

    def fail_second(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 2:
            raise RuntimeError("second capture unavailable")
        return original(**kwargs)

    monkeypatch.setattr(source, "ingest_source", fail_second)
    first = asyncio.run(setup.manager.check_feed(setup.feed_id))["feeds"][0]
    assert first["source_count"] == 1 and first["last_error"]
    assert setup.index.feed_runtime(setup.feed_id).get("etag", "") == ""
    second = asyncio.run(setup.manager.check_feed(setup.feed_id))["feeds"][0]
    assert second["source_count"] == 2 and second["last_error"] == ""
    assert len(setup.events) == 2


@pytest.mark.parametrize("change", ["pause", "disable_connection", "delete", "cancel", "stop"])
def test_inflight_revision_or_cancellation_cannot_capture_after_boundary(setup, monkeypatch, change):
    setup.manager.save_feed({"id": setup.feed_id, "enabled": True}, expected_revision=2)
    reached, release = threading.Event(), threading.Event()

    def blocked(*args, **kwargs):
        reached.set()
        assert release.wait(8)
        return setup.download(*args, **kwargs)

    monkeypatch.setattr(runtime, "download_feed", blocked)

    async def exercise():
        task = asyncio.create_task(setup.manager.check_feed(setup.feed_id))
        try:
            assert await asyncio.to_thread(reached.wait, 2)
            if change == "pause":
                setup.manager.save_feed({"id": setup.feed_id, "enabled": False}, expected_revision=3)
            elif change == "disable_connection":
                setup.manager.save_connection({"id": setup.connection_id, "enabled": False}, expected_revision=3)
            elif change == "delete":
                setup.manager.delete_feed(setup.feed_id, expected_revision=3)
            elif change == "cancel":
                task.cancel()
                await asyncio.sleep(0)
            else:
                await setup.manager.stop()
        finally:
            release.set()
        if change == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await task

    asyncio.run(exercise())
    assert setup.index.sources() == [] and setup.events == []


def test_failed_background_fetch_waits_for_its_deadline_instead_of_busy_looping(setup, monkeypatch):
    setup.manager.save_feed({"id": setup.feed_id, "enabled": True}, expected_revision=2)
    calls = []

    def unavailable(*_args, **_kwargs):
        calls.append(True)
        raise httpx.HTTPError("PRIVATE request Authorization: Bearer PRIVATE")

    monkeypatch.setattr(runtime, "download_feed", unavailable)

    async def exercise():
        await setup.manager.start()
        for _ in range(100):
            if setup.index.feed_runtime(setup.feed_id).get("last_checked"):
                break
            await asyncio.sleep(0.005)
        await asyncio.sleep(0.02)
        await setup.manager.stop()

    asyncio.run(exercise())
    assert calls == [True]
    feed = setup.manager.snapshot()["feeds"][0]
    assert feed["next_check"] > feed["last_checked"] + 299
    assert feed["last_error"] == "Feed check failed (HTTPError)"
    assert "PRIVATE" not in json.dumps(setup.manager.snapshot())


def test_feed_http_validators_and_credentials_never_follow_cross_origin_redirect(monkeypatch):
    requests = []
    client = httpx.Client

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "https://elsewhere.example/rss"})

    monkeypatch.setattr(feeds, "_public_url", lambda value, **_kwargs: validate_fetch_url(value))
    monkeypatch.setattr(feeds.httpx, "Client", lambda **kwargs: client(**kwargs, transport=httpx.MockTransport(handler)))
    with pytest.raises(ValueError, match="origin"):
        feeds.download_feed("https://publisher.example/rss", headers={"Authorization": "Bearer PRIVATE"},
                            etag='"edition"', expected_origin=("https", "publisher.example", 443))
    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == "Bearer PRIVATE"
    assert requests[0].headers["If-None-Match"] == '"edition"'


def test_cancelled_caller_keeps_collector_admission_until_worker_finishes(setup, monkeypatch):
    reached, release = threading.Event(), threading.Event()

    def blocked(*args, **kwargs):
        reached.set()
        assert release.wait(8)
        return setup.download(*args, **kwargs)

    monkeypatch.setattr(runtime, "download_feed", blocked)

    async def exercise():
        task = asyncio.create_task(setup.manager.check_feed(setup.feed_id))
        try:
            assert await asyncio.to_thread(reached.wait, 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            with pytest.raises(runtime.ConnectionsError, match="already being checked"):
                await setup.manager.check_feed(setup.feed_id)
        finally:
            release.set()
            if setup.manager._workers:
                await asyncio.gather(*setup.manager._workers)
        assert setup.manager._checks == {}

    asyncio.run(exercise())
    assert len(setup.requests) == 1 and setup.index.sources() == []


def test_registry_lock_contention_does_not_block_harness_event_loop(setup):
    held, release = threading.Event(), threading.Event()

    def hold():
        with setup.manager._lock:
            held.set()
            assert release.wait(3)

    holder = threading.Thread(target=hold)
    holder.start()
    assert held.wait(2)

    async def exercise():
        task = asyncio.create_task(setup.manager.check_feed(setup.feed_id))
        try:
            await asyncio.sleep(0.02)
            assert not task.done() and not setup.requests
        finally:
            release.set()
        await task

    try:
        asyncio.run(exercise())
    finally:
        release.set()
        holder.join(3)
    assert len(setup.requests) == 1


def test_changed_endpoint_clears_health_but_rename_preserves_it(setup):
    manager = setup.manager
    manager.record_connection_check(setup.connection_id, 2, "ready")
    renamed = manager.save_connection({"id": setup.connection_id, "name": "Renamed"}, expected_revision=2)
    assert renamed["connections"][0]["status"] == "ready"
    changed = manager.save_connection({"id": setup.connection_id, "url": "https://publisher.example/other"}, expected_revision=3)
    assert changed["connections"][0]["status"] == "unchecked"
    assert changed["connections"][0]["last_checked"] is None


def test_item_reader_lists_latest_versions_and_reads_full_inert_provider_content(setup, monkeypatch):
    manager = setup.manager
    summary = "<p>First paragraph.</p><script>PRIVATE SCRIPT</script><p>" + "Long detail. " * 80 + "</p>"
    setup.material = xml(summary=summary, second=True)
    asyncio.run(manager.check_feed(setup.feed_id))
    first = next(row for row in manager.items()["items"] if row["title"] == "Story")
    setup.material = xml(title="Revised headline", summary=summary, second=True)
    asyncio.run(manager.check_feed(setup.feed_id))
    before_sources = len(setup.index.sources())
    monkeypatch.setattr(runtime, "download_feed", lambda *_args, **_kwargs: pytest.fail("Reader fetched network content"))
    monkeypatch.setattr(source, "ingest_source", lambda **_kwargs: pytest.fail("Reader captured a Source"))
    listing = manager.items(setup.feed_id)
    assert listing["limit"] == 100 and len(listing["items"]) == 2
    latest = next(row for row in listing["items"] if row["title"] == "Revised headline")
    assert latest["source_id"] != first["source_id"]
    assert latest["feed_name"] == "World" and latest["connection_id"] == setup.connection_id
    assert len(latest["summary"]) == 400 and "<" not in latest["summary"]
    assert "PRIVATE SCRIPT" not in latest["summary"]
    detail = manager.item(latest["source_id"])
    assert len(detail["content_text"]) > 900 and "PRIVATE SCRIPT" not in detail["content_text"]
    assert "<p>" not in detail["content_text"]
    assert detail["provenance"]["feed_id"] == setup.feed_id
    assert detail["source_path"].startswith("obsidience/evidence/raw/")
    assert detail["reporting_url"] == "https://publisher.example/story"
    assert manager.item(first["source_id"])["title"] == "Story"
    assert len(manager.items(limit=1)["items"]) == 1
    assert len(setup.index.sources()) == before_sources
    assert "material" not in detail and "event_key" not in detail


def test_item_reader_rejects_non_feed_source_and_changed_material(setup):
    unrelated = source.ingest_source(source_type="document", source_ref="document://other",
        media_type="text/plain", content="Other raw document", captured_at="2026-09-09T10:00:00Z")
    with pytest.raises(runtime.ConnectionsError, match="not found"):
        setup.manager.item(unrelated["id"])
    captured = asyncio.run(setup.manager.check_feed(setup.feed_id))["feeds"][0]["last_source_id"]
    with setup.index.lock, setup.index.db:
        setup.index.db.execute("UPDATE source_evidence SET material=? WHERE id=?", (b"corrupt", captured))
    with pytest.raises(runtime.ConnectionsError, match="attestation"):
        setup.manager.item(captured)


def test_parsed_item_metadata_does_not_resolve_reporting_hosts(monkeypatch):
    monkeypatch.setattr(feeds, "_public_url", lambda *_args: pytest.fail("Metadata caused DNS resolution"))
    entries = feeds.parse_feed_items(xml(), "https://publisher.example/feed", 10)
    assert entries[0]["reporting_url"] == "https://publisher.example/story"


def test_item_reader_caps_display_title_and_preserves_complete_raw_title(setup):
    title = "Long title " * 100
    setup.material = xml(title=title)
    feed = asyncio.run(setup.manager.check_feed(setup.feed_id))["feeds"][0]
    display = setup.manager.items()["items"][0]
    assert len(display["title"]) == feeds.MAX_ENTRY_TITLE_CHARS
    raw = json.loads(source.get_source(feed["last_source_id"])["content"])
    assert raw["title"] == title.strip()


def test_reader_orders_publication_dates_instead_of_reverse_poll_order(setup):
    setup.material = xml(second=True).replace(
        b"Wed, 09 Sep 2026 10:00:00 GMT", b"Thu, 10 Sep 2026 10:00:00 GMT").replace(
        b"<title>Second</title>", b"<title>Second</title><pubDate>Wed, 09 Sep 2026 10:00:00 GMT</pubDate>")
    asyncio.run(setup.manager.check_feed(setup.feed_id))
    assert [item["title"] for item in setup.manager.items()["items"]] == ["Story", "Second"]


def test_unavailable_destination_records_a_deadline_without_repeated_attempts(setup, monkeypatch):
    setup.manager.save_feed({"id": setup.feed_id, "enabled": True}, expected_revision=2)
    (config.CONFIG.vault_dir / "Knowledge/World/World.md").unlink()
    calls = []
    original = setup.manager.destination_binding
    def inspect(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)
    monkeypatch.setattr(setup.manager, "destination_binding", inspect)
    async def exercise():
        await setup.manager.start()
        for _ in range(100):
            if setup.index.feed_runtime(setup.feed_id).get("last_checked"):
                break
            await asyncio.sleep(0.005)
        await asyncio.sleep(0.02)
        await setup.manager.stop()
    asyncio.run(exercise())
    assert calls == [True] and setup.requests == []
    state = setup.index.feed_runtime(setup.feed_id)
    assert state["next_check"] > state["last_checked"] + 299
    assert "Knowledge" in state["last_error"]


def test_pause_succeeds_when_saved_destination_has_disappeared(setup):
    setup.manager.save_feed({"id": setup.feed_id, "enabled": True}, expected_revision=2)
    (config.CONFIG.vault_dir / "Knowledge/World/World.md").unlink()
    snapshot = setup.manager.save_feed({"id": setup.feed_id, "enabled": False}, expected_revision=3)
    assert snapshot["feeds"][0]["enabled"] is False
    assert snapshot["feeds"][0]["destination_error"]
    assert setup.manager._due_feeds() == []
