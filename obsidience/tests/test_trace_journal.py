"""Public replay stays bounded and separate from authoritative Tool receipts."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from obsidience.harness.config import CONFIG
from obsidience.harness.knowledge.index import Index


def test_public_cursor_survives_reopen_and_retention(isolated_task_ledger, monkeypatch):
    ledger = isolated_task_ledger
    for number in range(7):
        assert ledger.append_trace({"id": str(number), "line": "visible"}, max_events=3) == number + 1
    assert ledger.trace_bounds() == {"oldest_seq": 5, "latest_seq": 7}
    assert [entry["seq"] for entry in ledger.trace_history(after_seq=5)] == [6, 7]
    monkeypatch.setattr(CONFIG, "db_path", Path(ledger.db_path))
    reopened = Index()
    try:
        assert reopened.trace_snapshot() == ledger.trace_snapshot()
        assert reopened.append_trace({"id": "new"}, max_events=3) == 8
        assert ledger.trace_bounds() == {"oldest_seq": 6, "latest_seq": 8}
    finally:
        reopened.db.close()


def test_retention_counts_encoded_unicode_bytes(isolated_task_ledger):
    ledger = isolated_task_ledger
    for number in range(10):
        ledger.append_trace({"id": str(number), "line": "🌌" * 10}, max_chars=400)
    rows = ledger.db.execute("SELECT entry,encoded_bytes FROM trace_events ORDER BY seq").fetchall()
    assert 1 <= len(rows) < 10
    assert all(len(payload.encode("utf-8")) == size for payload, size in rows)
    assert sum(size for _payload, size in rows) <= 400
    assert ledger.trace_bounds()["latest_seq"] == 10


def test_invalid_event_rolls_back_only_its_own_append(isolated_task_ledger):
    ledger = isolated_task_ledger
    ledger.append_trace({"id": "retained"})
    before = ledger.trace_snapshot()
    with pytest.raises(ValueError, match="byte budget"):
        ledger.append_trace({"id": "oversized", "line": "x" * 1000}, max_chars=100)
    with pytest.raises((TypeError, ValueError)):
        ledger.append_trace({"id": "opaque", "value": b"private bytes"})
    with pytest.raises(ValueError):
        ledger.append_trace({"id": "nan", "value": float("nan")})
    assert ledger.trace_snapshot() == before
    assert ledger.append_trace({"id": "next"}) == 2


def test_trace_cannot_commit_another_owner_transaction(isolated_task_ledger):
    ledger = isolated_task_ledger
    ledger.db.execute("INSERT INTO conversation_state VALUES('fixture','uncommitted')")
    with pytest.raises(ValueError, match="another owner transaction"):
        ledger.append_trace({"id": "unrelated"})
    assert ledger.db.in_transaction
    ledger.db.rollback()
    assert ledger.trace_history() == []


def test_concurrent_publishers_share_one_monotonic_bounded_journal(isolated_task_ledger):
    ledger = isolated_task_ledger
    with ThreadPoolExecutor(max_workers=4) as pool:
        seqs = list(pool.map(lambda number: ledger.append_trace({"id": str(number)}, max_events=30), range(90)))
    assert sorted(seqs) == list(range(1, 91))
    snapshot = ledger.trace_snapshot(after_seq=20)
    assert snapshot["oldest_seq"] == 61 and snapshot["latest_seq"] == 90
    assert [item["seq"] for item in snapshot["events"]] == list(range(61, 91))
    assert len({item["id"] for item in snapshot["events"]}) == 30
