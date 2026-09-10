"""Finished files in Source incoming enter the existing immutable Source lane."""

from __future__ import annotations

import logging
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers.inotify import InotifyObserver

from ..config import CONFIG
from .source import SOURCE_LANE_EVENTS, ingest_source

log = logging.getLogger(__name__)
MAX_INTAKE_BYTES = 500_000
MEDIA_TYPES = {
    ".txt": "text/plain", ".md": "text/markdown", ".json": "application/json",
    ".xml": "application/xml", ".rss": "application/rss+xml",
    ".atom": "application/atom+xml", ".html": "text/html", ".csv": "text/csv",
}
TEMP_SUFFIXES = {".tmp", ".part", ".partial", ".swp", ".crdownload"}


class SourceIntake(FileSystemEventHandler):
    """One in-process inotify observer; Source owns deduplication and events."""

    def __init__(self) -> None:
        self.root = (CONFIG.source_dir / "incoming").absolute()
        self.observer = InotifyObserver(generate_full_events=True)

    def start(self) -> None:
        # The Source explorer exposes these real intake folders even before
        # their first document arrives. Creating folders admits no work.
        for lane in SOURCE_LANE_EVENTS:
            directory = CONFIG.source_dir / lane
            directory.mkdir(parents=True, exist_ok=True)
            if directory.is_symlink():
                raise ValueError("Source evidence must use real directories")
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink():
            raise ValueError("Source incoming must be a real directory")
        self.observer.schedule(self, str(self.root), recursive=True)
        self.observer.start()
        # Watching first closes the gap between offline reconciliation and live arrivals.
        self.reconcile(self.root)

    def stop(self) -> None:
        self.observer.stop()
        self.observer.join(timeout=5)

    def _allowed(self, path: Path) -> bool:
        try:
            relative = path.relative_to(self.root)
        except ValueError:
            return False
        return bool(relative.parts) and all(
            not part.startswith(".") and not part.endswith("~")
            for part in relative.parts
        ) and not any(parent.is_symlink() for parent in (path, *path.parents))

    def reconcile(self, directory: Path) -> None:
        if directory != self.root and not self._allowed(directory):
            return
        for current, dirs, files in os.walk(directory, followlinks=False):
            base = Path(current)
            dirs[:] = [name for name in dirs if self._allowed(base / name)]
            for name in files:
                self.capture(base / name)

    def capture(self, path: Path) -> None:
        if not self._allowed(path) or path.suffix.lower() not in MEDIA_TYPES:
            return
        if any(suffix.lower() in TEMP_SUFFIXES for suffix in path.suffixes):
            return
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_INTAKE_BYTES:
                    return
                material = stream.read(MAX_INTAKE_BYTES + 1)
                after = os.fstat(stream.fileno())
            current = path.lstat()
            def signature(value):
                return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)
            if signature(before) != signature(after) or signature(before) != signature(current):
                return
            if len(material) != before.st_size or not self._allowed(path):
                return
            content = material.decode("utf-8")
            if any(ord(char) < 32 and char not in "\t\r\n" for char in content) or not content.strip():
                return
            ingest_source(
                source_type="document", source_ref=path.as_uri(),
                media_type=MEDIA_TYPES[path.suffix.lower()], content=content,
                captured_at=datetime.fromtimestamp(before.st_mtime, UTC).isoformat(),
            )
        except Exception as exc:  # One bad arrival must not stop the observer.
            log.warning("Source incoming %r: %s", path.name[:120], type(exc).__name__)

    def on_closed(self, event) -> None:
        if not event.is_directory:
            self.capture(Path(event.src_path))

    def on_moved(self, event) -> None:
        if event.dest_path:
            target = Path(event.dest_path)
            self.reconcile(target) if event.is_directory else self.capture(target)
