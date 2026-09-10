"""Connection configuration and encrypted access never bypass Source ownership."""

from pathlib import Path
import subprocess

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from obsidience.harness.connections import check
from obsidience.harness.connections.credentials import CredentialError, CredentialStore
from obsidience.harness.connections.runtime import ConnectionsManager
from obsidience.harness.interfaces.api import connections


@pytest.fixture
def client(tmp_path, monkeypatch, isolated_task_ledger):
    monkeypatch.setattr(connections.CONFIG, "vault_dir", tmp_path / "vault")
    sync = isolated_task_ledger.sync
    monkeypatch.setattr(isolated_task_ledger, "sync", lambda: sync(embed=False))
    from obsidience.harness.knowledge.vault import write_note
    write_note("News & Research/News & Research.md", {"kind": "knowledge", "title": "News & Research"}, "Existing news node.")
    app = FastAPI()
    app.include_router(connections.router)
    app.state.connections = ConnectionsManager(tmp_path / "connections.json", isolated_task_ledger)
    app.state.connection_credentials = CredentialStore(tmp_path / "credentials")
    return TestClient(app)


def create_connection(client, **fields):
    snapshot = client.get("/api/connections").json()
    response = client.post("/api/connections", json={
        "revision": snapshot["revision"], "kind": "rss", "name": "News",
        "url": "https://example.com/rss", "enabled": True, "auth_mode": "none", **fields,
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_api_only_connection_without_feed_and_stale_edit(client):
    doc = create_connection(client, kind="http_api")
    assert doc["feeds"] == []
    response = client.patch("/api/connections/" + doc["created_id"], json={"revision": 0, "name": "stale"})
    assert response.status_code == 409
    response = client.patch("/api/connections/" + doc["created_id"], json={"revision": doc["revision"], "name": "Current"})
    assert response.status_code == 200
    assert response.json()["connections"][0]["name"] == "Current"
    assert client.post("/api/feeds", json={
        "revision": response.json()["revision"], "connection_id": doc["created_id"],
        "name": "Not an RSS adapter", "url": "https://example.com/rss", "enabled": False,
    }).status_code == 400


def test_feed_lifecycle_rejects_orphans_and_keeps_paused(client):
    doc = create_connection(client)
    connection_id = doc["created_id"]
    response = client.post("/api/feeds", json={
        "revision": doc["revision"], "connection_id": connection_id, "name": "Headlines",
        "url": "https://example.com/headlines.xml", "enabled": False, "destination_ref": "News & Research/News & Research",
        "interval_minutes": 30, "item_limit": 1,
    })
    assert response.status_code == 200
    doc = response.json()
    feed_id = doc["created_id"]
    assert not doc["feeds"][0]["active"]
    assert client.delete(f"/api/connections/{connection_id}?revision={doc['revision']}").status_code == 400
    response = client.patch(f"/api/feeds/{feed_id}", json={"revision": doc["revision"], "name": "Top story"})
    assert response.status_code == 200
    doc = response.json()
    assert not doc["feeds"][0]["enabled"]
    doc = client.delete(f"/api/feeds/{feed_id}?revision={doc['revision']}").json()
    doc = client.delete(f"/api/connections/{connection_id}?revision={doc['revision']}").json()
    assert doc["connections"] == doc["feeds"] == []


def test_new_feed_selects_existing_node_and_defaults_unset_policy_to_automatic(client):
    from obsidience.harness.knowledge.vault import load_note, write_note

    doc = create_connection(client)
    response = client.post("/api/feeds", json={"revision": doc["revision"],
        "connection_id": doc["created_id"], "name": "Top story", "url": "https://example.com/rss",
        "destination_ref": "News & Research/News & Research"})
    assert response.status_code == 200, response.text
    feed = response.json()["feeds"][0]
    assert feed["enabled"] and feed["auto_curate"]
    assert feed["destination_ref"] == "News & Research/News & Research"
    assert not (connections.CONFIG.vault_dir / "Feeds").exists()
    note = load_note(feed["destination_ref"] + ".md")
    assert note.kind == "knowledge" and note.meta["auto_curate"] is True
    before = client.app.state.connections.path.read_bytes()
    write_note(note.path, {**note.meta, "auto_curate": False}, note.body)
    changed = client.get("/api/connections").json()["feeds"][0]
    assert changed["auto_curate"] is False and changed["auto_curate_supported"]
    assert client.app.state.connections.path.read_bytes() == before


def test_feed_policy_roundtrip_exposes_distinct_capture_retention_and_instruction_fields(client):
    doc = create_connection(client)
    response = client.post("/api/feeds", json={"revision": doc["revision"],
        "connection_id": doc["created_id"], "name": "Briefing", "url": "https://example.com/rss",
        "destination_ref": "News & Research/News & Research", "item_limit": 3,
        "max_active_articles": 12, "distill_instructions": "Focus on findings.\r\nKeep caveats."})
    assert response.status_code == 200, response.text
    doc = response.json()
    feed = doc["feeds"][0]
    assert feed["item_limit"] == 3 and feed["max_active_articles"] == 12
    assert feed["distill_instructions"] == "Focus on findings.\nKeep caveats."
    assert feed["active_article_count"] == 0 and feed["retention_status"] == "within_limit"
    response = client.patch("/api/feeds/" + feed["id"], json={"revision": doc["revision"],
        "distill_instructions": ""})
    assert response.status_code == 200 and response.json()["feeds"][0]["distill_instructions"] == ""
    current = response.json()["revision"]
    for injected in ({"auto_curate": True}, {"active_article_count": 0}, {"retention_status": "within_limit"},
                     {"distill_instructions": "x" * 501}, {"max_active_articles": 0}):
        invalid = client.patch("/api/feeds/" + feed["id"], json={"revision": current, **injected})
        assert invalid.status_code == 400
    assert client.get("/api/connections").json()["revision"] == current


@pytest.mark.parametrize("inherited", [False, True])
def test_multiple_feeds_can_share_node_without_overriding_disabled_policy(client, inherited):
    from obsidience.harness.knowledge.vault import write_note, load_note

    doc = create_connection(client)
    ref = "Knowledge/Science/Science"
    write_note("Knowledge/Knowledge.md", {"kind": "knowledge", "title": "Knowledge", "auto_curate": False}, "Knowledge.")
    write_note(ref + ".md", {"kind": "knowledge", "title": "Science", **({} if inherited else {"auto_curate": False})}, "Science.")
    before = (connections.CONFIG.vault_dir / (ref + ".md")).read_bytes()
    payload = {"revision": doc["revision"], "connection_id": doc["created_id"],
               "name": "Science feed", "url": "https://example.com/science", "destination_ref": ref}
    response = client.post("/api/feeds", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["feeds"][0]["auto_curate"] is False
    payload.update(revision=response.json()["revision"], name="Another feed")
    response = client.post("/api/feeds", json=payload)
    assert response.status_code == 200, response.text
    assert len(response.json()["feeds"]) == 2
    assert (connections.CONFIG.vault_dir / (ref + ".md")).read_bytes() == before
    assert next(node for node in response.json()["destination_nodes"] if node["ref"] == ref)["available"]


@pytest.mark.parametrize("ref", ["", "Tasks/ingest", "Invented/Invented", "Knowledge/../Tasks/ingest", "https://example.com/rss"])
def test_feed_destination_requires_an_exact_existing_knowledge_container(client, ref):
    doc = create_connection(client)
    response = client.post("/api/feeds", json={"revision": doc["revision"],
        "connection_id": doc["created_id"], "name": "World", "url": "https://example.com/rss", "destination_ref": ref})
    assert response.status_code == 400
    assert not client.get("/api/connections").json()["feeds"]


def test_failed_feed_save_restores_the_existing_node_policy(client, monkeypatch):
    doc = create_connection(client)
    manager = client.app.state.connections
    before = manager.path.read_bytes()
    node = connections.CONFIG.vault_dir / "News & Research/News & Research.md"
    node_before = node.read_bytes()
    def fail(_doc):
        raise OSError("simulated configuration write failure")
    monkeypatch.setattr(manager, "_write", fail)
    with pytest.raises(OSError):
        manager.save_feed({"connection_id": doc["created_id"], "name": "World", "url": "https://example.com/rss",
                           "destination_ref": "News & Research/News & Research"}, expected_revision=doc["revision"])
    assert manager.path.read_bytes() == before and node.read_bytes() == node_before


def test_browser_origin_cannot_change_provider_or_write_secret(client):
    doc = create_connection(client, kind="http_api", auth_mode="bearer")
    identifier = doc["created_id"]
    headers = {"Origin": "https://third-party.example"}
    assert client.patch(f"/api/connections/{identifier}", headers=headers, json={
        "revision": doc["revision"], "url": "https://third-party.example/steal",
    }).status_code == 403
    assert client.put(f"/api/connections/{identifier}/credential", headers=headers, json={
        "revision": doc["revision"], "secret": "never-stored",
    }).status_code == 403


def test_credential_failure_cannot_leave_old_account_validators(client, monkeypatch, isolated_task_ledger):
    doc = create_connection(client, auth_mode="bearer")
    identifier = doc["created_id"]
    doc = client.post("/api/feeds", json={
        "revision": doc["revision"], "connection_id": identifier, "name": "Private feed",
        "url": "https://example.com/private.xml", "enabled": False, "destination_ref": "News & Research/News & Research",
    }).json()
    feed_id = doc["created_id"]
    isolated_task_ledger.update_feed_runtime(feed_id, etag='"old-account"', definition_fingerprint="old", next_check=9999999999)
    def fail(*args):
        assert not isolated_task_ledger.feed_runtime(feed_id).get("etag")
        raise CredentialError("Encrypted store unavailable")
    monkeypatch.setattr(client.app.state.connection_credentials, "save", fail)
    response = client.put(f"/api/connections/{identifier}/credential", json={"revision": doc["revision"], "secret": "test-only"})
    assert response.status_code == 400
    assert client.get("/api/connections").json()["revision"] > doc["revision"]


def test_check_does_not_ingest_and_discards_account_details(client, monkeypatch, isolated_task_ledger):
    doc = create_connection(client, kind="http_api")
    calls = []
    monkeypatch.setattr(connections, "check_connection", lambda conn, headers, cancel: calls.append(conn["id"]))
    response = client.post(f"/api/connections/{doc['created_id']}/check")
    assert response.status_code == 200
    assert calls == [doc["created_id"]]
    assert response.json()["connections"][0]["status"] == "ready"
    assert isolated_task_ledger.db.execute("SELECT COUNT(*) FROM source_evidence").fetchone()[0] == 0


def test_credential_ciphertext_is_origin_bound_and_plaintext_never_in_argv(tmp_path, monkeypatch):
    commands = []
    def fake_run(argv, **kwargs):
        commands.append(argv)
        if "encrypt" in argv:
            assert kwargs["input"] == b"private-test-token"
            Path(argv[-1]).write_bytes(b"encrypted-opaque-test-data")
            return subprocess.CompletedProcess(argv, 0, b"", b"")
        return subprocess.CompletedProcess(argv, 0, b"private-test-token", b"")
    monkeypatch.setattr(subprocess, "run", fake_run)
    directory = tmp_path / "credentials"
    store = CredentialStore(directory)
    store.save("connection", "https://example.com/api", "private-test-token")
    assert store.configured("connection", "https://example.com/other")
    assert not store.configured("connection", "https://attacker.example/api")
    assert store.headers("connection", "https://example.com", "bot") == {"Authorization": "Bot private-test-token"}
    with pytest.raises(CredentialError):
        store.headers("connection", "https://attacker.example/api", "bot")
    assert "private-test-token" not in str(commands)
    assert all(b"private-test-token" not in p.read_bytes() for p in directory.iterdir())
    store.delete_connection("connection")
    assert not list(directory.iterdir())


def test_authenticated_check_refuses_cross_origin_redirect_before_delivery(monkeypatch):
    observed = []
    def handler(request):
        observed.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://another.example/capture"})
    real_client = httpx.Client
    monkeypatch.setattr(check.httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr(check, "_public_url", lambda url, **kw: url)
    with pytest.raises(ValueError, match="authenticated redirect"):
        check.check_connection({"kind": "http_api", "url": "https://example.com/api"}, {"Authorization": "Bearer token"})
    assert observed == ["https://example.com/api"]


def test_api_can_pause_a_feed_with_a_missing_destination(client):
    doc = create_connection(client)
    response = client.post("/api/feeds", json={"revision": doc["revision"], "connection_id": doc["created_id"],
        "name": "World", "url": "https://example.com/rss", "destination_ref": "News & Research/News & Research"})
    assert response.status_code == 200
    saved = response.json()
    (connections.CONFIG.vault_dir / "News & Research/News & Research.md").unlink()
    response = client.patch("/api/feeds/" + saved["created_id"], json={"revision": saved["revision"], "enabled": False})
    assert response.status_code == 200, response.text
    assert response.json()["feeds"][0]["enabled"] is False


def test_unreadable_article_does_not_hide_valid_destination_choices(client):
    folder = connections.CONFIG.vault_dir / "Unrelated"
    folder.mkdir()
    (folder / "Unrelated.md").write_text("---\ntitle: broken\n")
    response = client.get("/api/connections")
    assert response.status_code == 200
    assert [node["ref"] for node in response.json()["destination_nodes"]] == ["News & Research/News & Research"]
