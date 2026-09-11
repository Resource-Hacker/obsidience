"""System facts use the ordinary immutable Source ledger, without Task events."""

import inspect
import json
from types import SimpleNamespace

import pytest

from obsidience.harness import config
from obsidience.harness.capabilities.source import read
from obsidience.harness.execution import scheduler
from obsidience.harness.knowledge import source, vault


@pytest.fixture
def system_source(tmp_path, monkeypatch, isolated_task_ledger):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config.CONFIG, "vault_dir", tmp_path / "obsidience/vault")
    monkeypatch.setattr(vault, "iter_notes", lambda **_kwargs: [])
    events = []
    monkeypatch.setattr(scheduler, "enqueue_named_event", lambda *args, **kwargs: events.append(args) or [])
    return tmp_path, isolated_task_ledger, events


def test_system_source_exact_physical_path_citation_and_no_event(system_source):
    root, ledger, events = system_source
    result = source.capture_system_evidence("identity", {"hostname": "test-host"})
    assert result["created"] and result["immutable"]
    assert result["source_ref"] == "system://identity"
    assert result["source_type"] == "tool" and result["media_type"] == "application/json"
    assert result["path"] == f"system/identity/{result['captured_at'][:10]}/evidence--{result['id']}.md"
    assert result["source_path"] == "obsidience/evidence/" + result["path"]
    assert json.loads(result["content"]) == {
        "schema": "obsidience.system-evidence.v1", "category": "identity", "facts": {"hostname": "test-host"},
    }
    physical = root / result["source_path"]
    assert physical.read_bytes() == ledger.source(result["id"])["material"]
    assert physical == config.CONFIG.source_dir / result["path"]
    assert not (config.CONFIG.system_dir / "snapshots").exists()
    assert ledger.source(result["id"])["event_key"] is None
    assert result["source_event"] is None and ledger.pending_source_events() == [] and events == []
    assert source.get_source(result["citation"])["content"] == result["content"]
    assert result["content"] in read.execute({"source": result["citation"]}, {})


def test_canonical_dedup_preserves_capture_and_change_preserves_history(system_source):
    root, ledger, _ = system_source
    first = source.capture_system_evidence("network", {"b": 2, "a": [1]})
    path = root / first["source_path"]
    before = path.read_bytes(), path.stat().st_mtime_ns
    duplicate = source.capture_system_evidence("network", {"a": [1], "b": 2})
    assert not duplicate["created"]
    for field in ("id", "captured_at", "path", "content_sha256"):
        assert duplicate[field] == first[field]
    changed = source.capture_system_evidence("network", {"a": [], "b": 2})
    assert changed["id"] != first["id"] and len(ledger.sources()) == 2
    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_missing_or_changed_file_restores_attested_bytes(system_source, damage):
    root, ledger, events = system_source
    result = source.capture_system_evidence("compute", {"gpus": []})
    physical = root / result["source_path"]
    if damage == "missing":
        physical.unlink()
    else:
        physical.write_text("foreign edits")
    recovered = source.get_source(result["citation"])
    assert recovered["status"] == "restored"
    assert physical.read_bytes() == ledger.source(result["id"])["material"]
    assert events == []


def test_ledger_commit_survives_failed_physical_write(system_source, monkeypatch):
    root, ledger, events = system_source
    original = source._atomic_write
    def fail(*args):
        raise OSError("interrupted write")
    monkeypatch.setattr(source, "_atomic_write", fail)
    with pytest.raises(OSError, match="interrupted"):
        source.capture_system_evidence("storage", {"locations": []})
    assert len(ledger.sources()) == 1 and not ledger.pending_source_events()
    monkeypatch.setattr(source, "_atomic_write", original)
    listing = source.list_sources()
    assert listing["issues"] == [] and listing["sources"][0]["status"] == "restored"
    result = source.capture_system_evidence("storage", {"locations": []})
    assert not result["created"] and (root / result["source_path"]).is_file() and not events


@pytest.mark.parametrize("field,value", [
    ("material_sha256", "bad"), ("source_ref", "system://storage"),
    ("event_key", "source.added:forged"), ("path", "system/storage/2000-01-01/evidence--00000000-0000-0000-0000-000000000000.md"),
])
def test_system_ledger_metadata_is_attested_before_recovery(system_source, field, value):
    _, ledger, _ = system_source
    result = source.capture_system_evidence("identity", {"hostname": "host"})
    row = {**ledger.source(result["id"]), field: value}
    with pytest.raises(source.SourceError, match="attestation"):
        source._restore(row)


def test_source_reader_exact_backlinks_and_get_never_collects(system_source, monkeypatch):
    root, _, events = system_source
    result = source.capture_system_evidence("devices", {"cameras": []})
    note = SimpleNamespace(ref="ADMECH Workstation/Workstation Observations/Devices", path="ADMECH Workstation/Workstation Observations/Devices.md",
                           body="Observed hardware.", meta={"sources": [{"resource": result["citation"]}]})
    monkeypatch.setattr(vault, "iter_notes", lambda: [note])
    physical = root / result["source_path"]
    before = physical.read_bytes(), physical.stat().st_mtime_ns
    listing = source.list_source_files(scope="obsidience/evidence/system")
    assert listing["coverage"]["complete"] and listing["issues"] == []
    assert len(listing["files"]) == 1
    row = listing["files"][0]
    assert row["key"] == row["path"] == result["source_path"]
    assert row["source_id"] == result["id"]
    assert row["articles"] == [note.ref] and row["storage"] == "blob" and row["read_only"]
    assert source.get_source_file(row["key"])["content"] == physical.read_text()
    assert source.list_sources()["issues"] == []
    assert (physical.read_bytes(), physical.stat().st_mtime_ns) == before and not events
    physical.with_name("unregistered.md").write_text("Untrusted file")
    assert source.list_sources()["issues"][0]["status"] == "unregistered"


@pytest.mark.parametrize("category,facts", [("other", {}), ("identity", []), ("identity", {"x": float("nan")}), ("identity", {"x": object()})])
def test_invalid_system_facts_never_commit(system_source, category, facts):
    _, ledger, events = system_source
    with pytest.raises(source.SourceError):
        source.capture_system_evidence(category, facts)
    assert not ledger.sources() and not events


def test_system_symlink_rejected_before_ledger_commit(system_source):
    root, ledger, _ = system_source
    outside = root / "outside"
    outside.mkdir()
    config.CONFIG.source_dir.mkdir(parents=True)
    (config.CONFIG.source_dir / "system").symlink_to(outside, target_is_directory=True)
    with pytest.raises(source.SourceError, match="symlink"):
        source.capture_system_evidence("runtime", {})
    assert not ledger.sources() and list(outside.iterdir()) == []


def test_source_reader_rejects_tampered_system_bytes_without_repair(system_source):
    root, ledger, events = system_source
    result = source.capture_system_evidence("identity", {"hostname": "host"})
    physical = root / result["source_path"]
    physical.write_text("Altered physical capture")
    before = physical.read_bytes(), physical.stat().st_mtime_ns
    with pytest.raises(source.SourceError, match="Immutable System evidence mismatch"):
        source.get_source_file(result["source_path"])
    listing = source.list_source_files(scope="obsidience/evidence/system")
    assert listing["files"][0]["integrity"] == "mismatch"
    assert "source_id" not in listing["files"][0]
    assert listing["files"][0]["articles"] == []
    assert listing["issues"][0]["status"] == "integrity_mismatch"
    assert (physical.read_bytes(), physical.stat().st_mtime_ns) == before and not events
    source.capture_system_evidence("identity", {"hostname": "host"})
    assert physical.read_bytes() == ledger.source(result["id"])["material"]
    assert source.get_source_file(result["source_path"])["source_id"] == result["id"]


@pytest.mark.parametrize("damage", ["tampered", "unregistered"])
def test_one_bad_snapshot_does_not_hide_other_sources_or_forge_backlinks(system_source, monkeypatch, damage):
    root, _, events = system_source
    good = source.capture_system_evidence("identity", {"hostname": "host"})
    bad = source.capture_system_evidence("network", {"interfaces": []})
    physical = root / bad["source_path"]
    if damage == "tampered":
        physical.write_bytes(physical.read_bytes().replace(b'"interfaces":[]', b'"interfaces":["forged"]'))
    else:
        physical = physical.with_name("unregistered.md")
        physical.write_bytes((root / bad["source_path"]).read_bytes())
    bad_key = physical.relative_to(root).as_posix()
    note = SimpleNamespace(ref="Knowledge/system", path="Knowledge/system.md", body="", meta={
        "sources": [{"resource": good["citation"]}, {"resource": bad["citation"]}, {"resource": bad_key}]})
    monkeypatch.setattr(vault, "iter_notes", lambda: [note])
    before = physical.read_bytes(), physical.stat().st_mtime_ns
    listing = source.list_source_files(scope="obsidience/evidence/system")
    rows = {row["key"]: row for row in listing["files"]}
    assert rows[good["source_path"]]["source_id"] == good["id"]
    assert rows[good["source_path"]]["articles"] == [note.ref]
    assert rows[bad_key]["integrity"] == "mismatch" and rows[bad_key]["read_only"]
    assert rows[bad_key]["articles"] == [] and "source_id" not in rows[bad_key]
    assert any(issue["path"] == bad_key and issue["status"] == "integrity_mismatch" for issue in listing["issues"])
    with pytest.raises(source.SourceError, match="Immutable System evidence mismatch"):
        source.get_source_file(bad_key)
    assert (physical.read_bytes(), physical.stat().st_mtime_ns) == before and not events


def test_ordinary_ingest_cannot_suppress_events_or_select_system_lane(system_source):
    _, ledger, events = system_source
    assert "lane" not in inspect.signature(source.ingest_source).parameters
    assert "emit_event" not in inspect.signature(source.ingest_source).parameters
    result = source.ingest_source(source_type="tool", source_ref="system://identity", media_type="application/json",
                                  captured_at=None, content='{"hostname":"untrusted"}')
    assert result["path"].startswith("raw/") and len(events) == 1
    assert result["source_path"] == "obsidience/evidence/" + result["path"]
    assert ledger.source(result["id"])["event_key"].startswith("source.added:")

pytestmark = pytest.mark.usefixtures("authorized_reader_scope")
