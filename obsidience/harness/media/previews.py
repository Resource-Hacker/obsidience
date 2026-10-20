"""Owner media previews: short-lived tokens for one search match or one chosen source.

Preview scopes have no Agent or Task identity and never cross into acquisition.
A token preserves only the owner's chosen source fingerprint; the real activation
repeats discovery through receipt-bound Tools before any registration.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import threading
import time
from copy import deepcopy

from .config import MediaUnavailable

PREVIEW_SECONDS = 600
_PREVIEW_LIMIT = 32
_previews: dict[str, dict] = {}
_preview_lock = threading.Lock()


def clear_previews() -> None:
    with _preview_lock:
        _previews.clear()


def _prune_previews() -> None:
    now = time.monotonic()
    for token in list(_previews):
        if _previews[token]['expires'] <= now:
            del _previews[token]


def issue_preview(kind: str, payload: dict) -> str:
    with _preview_lock:
        _prune_previews()
        while len(_previews) >= _PREVIEW_LIMIT:
            del _previews[next(iter(_previews))]
        token = secrets.token_hex(16)
        _previews[token] = {'kind': kind, 'payload': payload,
                            'expires': time.monotonic() + PREVIEW_SECONDS, 'request_id': None}
        return token


def preview_record(token: str, kind: str) -> dict:
    with _preview_lock:
        _prune_previews()
        record = _previews.get(token)
        if record is None or record['kind'] != kind:
            raise MediaUnavailable('Media preview expired; search and choose the source again')
        return record


def source_fingerprint(candidate: dict) -> str:
    """Stable private source identity; volatile seeder/ranking fields cannot choose it."""
    from .tiramisu import normal_hash
    identity = {key: candidate.get(key) for key in (
        'imdb', 'type', 'title', 'year', 'season', 'episode', 'first_air_date',
        'release_title', 'provider', 'instance_id', 'config_fingerprint', 'socket_identity',
        'debrid_binding', 'debrid_file', 'debrid_plan', 'season_episodes', 'series_episodes')}
    identity['hash'] = normal_hash(candidate.get('hash'))
    if not identity['hash']:
        raise MediaUnavailable('Invalid discovery source identity')
    return hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def claim_source_preview(token: str, request_id: str) -> dict:
    """Consume one source choice for one admitted owner activation; never a run candidate."""
    with _preview_lock:
        _prune_previews()
        record = _previews.get(token)
        if record is None or record['kind'] != 'source':
            raise MediaUnavailable('Media preview expired; search and choose the source again')
        if record['request_id'] is not None:
            raise MediaUnavailable('This source choice was already attempted; use its existing receipt')
        record['request_id'] = request_id
        return deepcopy(record['payload'])
