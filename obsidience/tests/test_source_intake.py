from __future__ import annotations

import threading
from pathlib import Path

import pytest
from watchdog.events import FileCreatedEvent

from obsidience.harness import config
from obsidience.harness.execution import scheduler
from obsidience.harness.knowledge import index, intake, source


@pytest.fixture
def incoming(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(config.CONFIG, "db_path", tmp_path / "index.sqlite3")
    monkeypatch.setattr(config.CONFIG, "vault_dir", tmp_path / "vault")
    ledger = index.Index()
    monkeypatch.setattr(index, "INDEX", ledger)
    dispatched = []
    observed = threading.Event()

    def enqueue(event, params, **kwargs):
        dispatched.append((event, params))
        observed.set()
        return []

    monkeypatch.setattr(scheduler, "enqueue_named_event", enqueue)
    observer = intake.SourceIntake()
    observer.root.mkdir(parents=True)
    yield observer, ledger, dispatched, observed
    if observer.observer.is_alive():
        observer.stop()
    ledger.db.close()


def test_close_write_ingests_once_and_preserves_original(incoming):
    watcher, ledger, events, heard = incoming
    watcher.start()
    assert all((config.CONFIG.source_dir / lane).is_dir() for lane in ("incoming", "raw", "inbox"))
    assert ledger.sources() == [] and events == []
    document = watcher.root / "finding.txt"
    with document.open("w") as stream:
        stream.write("Accepted only after the producer closes its file.")
        stream.flush()
        assert not heard.wait(0.1)
    assert heard.wait(3)
    watcher.stop()
    rows = ledger.sources()
    assert len(rows) == len(events) == 1
    assert events[0][0] == "source.added"
    assert rows[0]["source_ref"] == document.as_uri()
    assert document.read_text() == "Accepted only after the producer closes its file."
    assert rows[0]["captured_at"].endswith("Z")


def test_external_atomic_rename_is_ingested(incoming, tmp_path):
    watcher, ledger, events, heard = incoming
    document = tmp_path / "outside.md"
    document.write_text("An atomically delivered research document.")
    watcher.start()
    document.rename(watcher.root / "arrived.md")
    assert heard.wait(3)
    watcher.stop()
    assert len(ledger.sources()) == len(events) == 1


def test_moved_directory_reconciles_existing_descendants(incoming, tmp_path):
    watcher, ledger, events, heard = incoming
    folder = tmp_path / "bundle"
    folder.mkdir()
    (folder / "finding.txt").write_text("Evidence arrived with its containing directory.")
    watcher.start()
    folder.rename(watcher.root / "bundle")
    assert heard.wait(3)
    watcher.stop()
    assert len(ledger.sources()) == len(events) == 1


def test_restart_reconciles_offline_arrivals_without_duplicate_event(incoming):
    watcher, ledger, events, heard = incoming
    (watcher.root / "offline.txt").write_text("Written while the harness was offline.")
    watcher.start()
    assert heard.wait(3)
    watcher.stop()
    next_watcher = intake.SourceIntake()
    try:
        next_watcher.start()
    finally:
        next_watcher.stop()
    assert len(ledger.sources()) == len(events) == 1


def test_ordinary_create_never_captures_partial_file(incoming):
    watcher, ledger, events, heard = incoming
    document = watcher.root / "unfinished.txt"
    document.write_text("This file is not declared complete.")
    watcher.dispatch(FileCreatedEvent(str(document)))
    assert ledger.sources() == []


@pytest.mark.parametrize("filename,material", [
    (".hidden.txt", b"secret"), ("unfinished.tmp.txt", b"partial"),
    ("unsupported.pdf", b"document"), ("binary.txt", b"binary\0data"),
    ("invalid.txt", b"\xff"), ("large.txt", b"x" * 500_001),
])
def test_skips_ineligible_inputs(incoming, filename, material):
    watcher, ledger, events, heard = incoming
    document = watcher.root / filename
    document.write_bytes(material)
    watcher.capture(document)
    assert ledger.sources() == []


def test_symlinks_and_hidden_subtrees_are_skipped(incoming, tmp_path):
    watcher, ledger, events, heard = incoming
    outside = tmp_path / "private.txt"
    outside.write_text("Do not follow links to other Source trees.")
    (watcher.root / "link.txt").symlink_to(outside)
    hidden = watcher.root / ".private"
    hidden.mkdir()
    (hidden / "finding.txt").write_text("Not an arrival.")
    watcher.reconcile(watcher.root)
    assert ledger.sources() == []


def test_unstable_read_is_not_ingested(incoming, monkeypatch):
    watcher, ledger, events, heard = incoming
    document = watcher.root / "changing.txt"
    document.write_text("Original completed text.")
    original_lstat = Path.lstat

    def changed_lstat(path, *args, **kwargs):
        if path == document:
            document.write_text("Different text arrived during the read.")
        return original_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "lstat", changed_lstat)
    watcher.capture(document)
    assert ledger.sources() == []


def test_ingestion_failure_is_logged_without_killing_observer(incoming, monkeypatch, caplog):
    watcher, ledger, events, heard = incoming
    document = watcher.root / "finding.txt"
    document.write_text("An ordinary completed document.")

    def failed(**kwargs):
        raise RuntimeError("Source ledger temporarily unavailable")

    monkeypatch.setattr(intake, "ingest_source", failed)
    watcher.capture(document)
    assert "RuntimeError" in caplog.text
    assert ledger.sources() == []
