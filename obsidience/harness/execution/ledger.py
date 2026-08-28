"""Small execution-ledger helpers; run state itself lives in SQLite."""

from __future__ import annotations

import hashlib

from ..knowledge.vault import Note


def runbook_hash(runbook: Note) -> str:
    """Hash the exact Runbook revision used by a leaf Task session."""
    from ..config import CONFIG

    return hashlib.sha256((CONFIG.vault_dir / runbook.path).read_bytes()).hexdigest()


def runbook_tree_hash(runbooks: list[Note]) -> str:
    """Attest an ordered recursive Runbook tree while preserving leaf hashes."""
    if len(runbooks) == 1:
        return runbook_hash(runbooks[0])
    from ..config import CONFIG

    digest = hashlib.sha256()
    for runbook in runbooks:
        digest.update(runbook.ref.encode())
        digest.update(b"\0")
        digest.update((CONFIG.vault_dir / runbook.path).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
