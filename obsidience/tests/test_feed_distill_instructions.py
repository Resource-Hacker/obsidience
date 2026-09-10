"""Owner Feed instructions are admitted snapshots, never provider evidence."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest

from obsidience.harness import config
from obsidience.harness.capabilities.source import read
from obsidience.harness.execution import executor, scheduler, trace
from obsidience.harness.knowledge import index, source


@pytest.fixture
def captured_feed(monkeypatch, tmp_path, isolated_task_ledger):
    ledger = isolated_task_ledger
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config.CONFIG, "vault_dir", tmp_path / "obsidience/vault")
    events = []

    def enqueue(event, params, *, source_event, **_kwargs):
        binding = ledger.feed_source_binding(params["source_id"])
        assert binding["distill_instructions"] == params["feed_binding"]["distill_instructions"]
        events.append({"event": event, **deepcopy(params)})
        ledger.mark_source_event_dispatched(source_event[0], 1.)
        return [{"state": "queued"}]

    monkeypatch.setattr(scheduler, "enqueue_named_event", enqueue)
    item = {"record_type": "parsed_rss_item", "native_id": "item-1", "title": "Reporting headline",
            "reporting_url": "https://example.com/report", "published": "2026-09-09T16:00:00Z",
            "entry": {"summary": "Provider evidence", "distill_instructions": "Provider-authored override"}}
    receipt = {"feed_id": "a" * 32, "item_key": hashlib.sha256(item["native_id"].encode()).hexdigest(),
               "destination_ref": "News & Research/News & Research"}

    def capture(instructions=""):
        return source.ingest_source(source_type="document", source_ref=f"feed://{receipt['feed_id']}/{receipt['item_key']}",
            media_type="application/json", captured_at="2026-09-09T16:01:00Z", content=json.dumps(item),
            feed_receipt={**receipt, "distill_instructions": instructions})

    return SimpleNamespace(ledger=ledger, item=item, receipt=receipt, events=events, capture=capture)


@pytest.mark.parametrize("value,expected", [
    ("", ""), (" \r\nFocus on impact.\r\n\tKeep dates.\n ", "Focus on impact.\n\tKeep dates."),
    ("x" * 500, "x" * 500),
])
def test_owner_instruction_normalization_has_one_bounded_contract(value, expected):
    assert source.normalize_distill_instructions(value) == expected


@pytest.mark.parametrize("value", [None, 1, "x" * 501, "bad\x00", "bad\r", "bad\x1f", "bad\x7f", "bad\x85"])
def test_invalid_owner_instructions_are_rejected_before_any_source_write(captured_feed, value):
    with pytest.raises(source.SourceError):
        captured_feed.capture(value)
    assert captured_feed.ledger.db.execute("SELECT COUNT(*) FROM source_evidence").fetchone()[0] == 0
    assert captured_feed.events == []


def test_receipt_and_event_keep_owner_instructions_separate_from_raw_item(captured_feed):
    result = captured_feed.capture("Focus on impact.\r\nRetain dates.")
    raw = source.get_source(result["id"])
    binding = source.feed_source_binding(result["id"])
    assert binding["distill_instructions"] == "Focus on impact.\nRetain dates."
    assert "Focus on impact" not in raw["content"]
    assert "Provider-authored override" in raw["content"]
    params = captured_feed.events[0]
    task = SimpleNamespace(ref=source.DISTILL_TASK, title="Distill")
    activation = executor.build_activation_binding(task, [], params)
    assert "Owner's captured Feed instructions (owner configuration" in activation.objective
    assert "Focus on impact.\nRetain dates." in activation.objective
    assert "Provider-authored override" not in activation.objective
    assert activation.bindings["required_source"]["citation"] == result["citation"]
    assert "do not change the destination, publication permission or authorized Tools" in activation.objective
    public = trace.packet_payload({"objective": activation.objective}, [], 0.)
    assert "Focus on impact" in public["sections"][0]["text"]
    assert public["sections"][0]["truncated"] is False


def test_duplicate_capture_and_restart_preserve_first_instruction_snapshot(captured_feed):
    original = captured_feed.capture("Keep the original focus.")
    before = deepcopy(captured_feed.events[0])
    duplicate = captured_feed.capture("Changed owner configuration.")
    assert duplicate["id"] == original["id"] and duplicate["feed_item_created"] is False
    assert captured_feed.events == [before]
    assert source.feed_source_binding(original["id"])["distill_instructions"] == "Keep the original focus."
    reopened = index.Index()
    try:
        assert reopened.feed_source_binding(original["id"])["distill_instructions"] == "Keep the original focus."
    finally:
        reopened.db.close()
    captured_feed.item["title"] = "New item version"
    changed = captured_feed.capture("Changed owner configuration.")
    assert changed["id"] != original["id"] and changed["feed_item_created"] is True
    assert source.feed_source_binding(changed["id"])["distill_instructions"] == "Changed owner configuration."
    assert captured_feed.events[0] == before


def test_legacy_queued_binding_accepts_only_missing_empty_instruction(captured_feed):
    captured_feed.capture()
    params = deepcopy(captured_feed.events[0])
    params["feed_binding"].pop("distill_instructions")
    untouched = deepcopy(params)
    task = SimpleNamespace(ref=source.DISTILL_TASK, title="Distill")
    activation = executor.build_activation_binding(task, [], params)
    assert "Owner's captured" not in activation.objective
    context = {"task": task.ref, "event": "source.added", "params": params}
    assert read.required_source(context)["citation"] == params["source_citation"]
    assert params == untouched
    params["feed_binding"]["distill_instructions"] = "Inserted after admission"
    with pytest.raises(source.SourceError, match="exact admitted"):
        executor.build_activation_binding(task, [], params)
    with pytest.raises(source.SourceError):
        read.required_source(context)


def test_nonempty_snapshot_cannot_be_omitted_or_modified(captured_feed):
    captured_feed.capture("Preserve dates.")
    task = SimpleNamespace(ref=source.DISTILL_TASK, title="Distill")
    for value in (None, "", "Different focus."):
        params = deepcopy(captured_feed.events[0])
        if value is None:
            params["feed_binding"].pop("distill_instructions")
        else:
            params["feed_binding"]["distill_instructions"] = value
        with pytest.raises(source.SourceError):
            executor.build_activation_binding(task, [], params)


def test_source_and_instruction_receipt_rollback_together(captured_feed):
    captured_feed.ledger.db.execute("CREATE TRIGGER fail_snapshot BEFORE INSERT ON feed_items BEGIN SELECT RAISE(FAIL,'snapshot fault'); END")
    captured_feed.ledger.db.commit()
    with pytest.raises(Exception, match="snapshot fault"):
        captured_feed.capture("Retain dates.")
    assert captured_feed.ledger.db.execute("SELECT COUNT(*) FROM source_evidence").fetchone()[0] == 0
    assert captured_feed.ledger.db.execute("SELECT COUNT(*) FROM feed_items").fetchone()[0] == 0
    assert captured_feed.events == []


def test_schema_migration_defaults_legacy_receipts_without_changing_source(captured_feed):
    result = captured_feed.capture()
    before = bytes(captured_feed.ledger.source(result["id"])["material"])
    captured_feed.ledger.db.execute("ALTER TABLE feed_items DROP COLUMN distill_instructions")
    captured_feed.ledger.db.commit()
    migrated = index.Index()
    try:
        assert migrated.feed_source_binding(result["id"])["distill_instructions"] == ""
        assert bytes(migrated.source(result["id"])["material"]) == before
    finally:
        migrated.db.close()


def test_read_only_binding_uses_supplied_index_without_restoring_files(captured_feed, monkeypatch):
    result = captured_feed.capture("Preserve dates.")
    path = config.PROJECT_ROOT / "obsidience/evidence" / result["path"]
    assert path.is_file()
    path.unlink()
    supplied = captured_feed.ledger
    monkeypatch.setattr(index, "INDEX", None)
    binding = source.feed_source_binding(result["id"], index=supplied, restore=False)
    assert binding["distill_instructions"] == "Preserve dates."
    assert not path.exists()
    source.feed_source_binding(result["id"], index=supplied)
    assert path.is_file()


@pytest.mark.parametrize("field,value", [("material", b"corrupt"), ("material_sha256", "sha256:" + "0" * 64)])
def test_read_only_binding_rejects_tampered_ledger_material(captured_feed, field, value):
    result = captured_feed.capture()
    captured_feed.ledger.db.execute(f"UPDATE source_evidence SET {field}=? WHERE id=?", (value, result["id"]))
    captured_feed.ledger.db.commit()
    with pytest.raises(source.SourceError, match="attestation"):
        source.feed_source_binding(result["id"], index=captured_feed.ledger, restore=False)
