"""Immutable evaluation-artifact store for AutoSaddler.

AutoSaddler v2 supplies the matched-case and immutable-candidate design reference
(MIT, 30e20ce004486c58e7ee97c66182a8d0d41ec90e). No upstream engine is imported.
These are internal evaluation artifacts, not external Source intake or Articles.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ...config import CONFIG

# Five complete decision captures (up to 160 KB each) plus frozen definitions.
MAX_ARTIFACT_BYTES = 1_024_000


def canonical_json(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def root() -> Path:
    return CONFIG.source_dir / "evaluations"


def _identity(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
        raise ValueError("Evaluation identity must be an exact SHA256")
    return value


def save(lane: str, document: dict) -> str:
    raw = canonical_json(document).encode()
    if len(raw) > MAX_ARTIFACT_BYTES:
        raise ValueError("Evaluation artifact exceeds its byte bound")
    identity = sha256(raw)
    directory = root() / lane
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (identity + ".json")
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("Evaluation artifacts cannot follow symlinks")
    # Atomic publication keeps a killed writer from leaving an admitted partial
    # artifact. Existing content identities are immutable and byte-attested.
    from ...knowledge.vault import _atomic_write
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError("Evaluation artifact identity conflicts")
    else:
        _atomic_write(path, raw.decode())
    return identity


def load(lane: str, identity: str) -> dict:
    path = root() / lane / (_identity(identity) + ".json")
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("Evaluation artifacts cannot follow symlinks")
    if path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise ValueError("Evaluation artifact exceeds its byte bound")
    raw = path.read_bytes()
    if sha256(raw) != identity:
        raise ValueError("Evaluation artifact bytes changed")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("Evaluation artifact must be an object")
    return result
