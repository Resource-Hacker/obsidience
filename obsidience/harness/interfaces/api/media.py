"""Independent catalogue views and authenticated native owner command ingress."""
from __future__ import annotations

import asyncio
import hmac
import hashlib
import secrets
import threading
import time
from copy import deepcopy
import json
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request

from ...conversation.runtime import RUNTIME
from ...execution.commands import owner_media_command
from ...knowledge.index import INDEX
from ...media import service
from ...media.config import MediaUnavailable, load_config
from ...tv import player
from obsidience.shell.command_token import read_token

router = APIRouter(prefix='/api/media', tags=['media'])

# Preview scopes have no Agent or Task identity and never cross into acquisition.
# A token preserves only the owner's chosen source fingerprint; the real activation
# repeats discovery through receipt-bound Tools before any registration.
_PREVIEW_SECONDS = 600
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


def _preview(kind: str, payload: dict) -> str:
    with _preview_lock:
        _prune_previews()
        while len(_previews) >= _PREVIEW_LIMIT:
            del _previews[next(iter(_previews))]
        token = secrets.token_hex(16)
        _previews[token] = {'kind': kind, 'payload': payload,
                            'expires': time.monotonic() + _PREVIEW_SECONDS, 'request_id': None}
        return token


def _preview_record(token: str, kind: str) -> dict:
    with _preview_lock:
        _prune_previews()
        record = _previews.get(token)
        if record is None or record['kind'] != kind:
            raise MediaUnavailable('Media preview expired; search and choose the source again')
        return record


def source_fingerprint(candidate: dict) -> str:
    """Stable private source identity; volatile seeder/ranking fields cannot choose it."""
    from ...media.tiramisu import _normal_hash
    identity = {key: candidate.get(key) for key in (
        'imdb', 'type', 'title', 'year', 'season', 'episode', 'first_air_date',
        'release_title', 'provider', 'instance_id', 'config_fingerprint', 'socket_identity',
        'debrid_binding', 'debrid_file', 'debrid_plan', 'season_episodes', 'series_episodes')}
    identity['hash'] = _normal_hash(candidate.get('hash'))
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


@router.get('/search')
async def search(query: str, content_type: str = 'movie'):
    from ...media import discovery
    # This is a read-only preview namespace, not an admitted execution or fabricated Agent.
    context = {'run_id': 'preview-' + secrets.token_hex(16)}
    try:
        result = await discovery.search(query, content_type, context)
        matches = []
        for row in result['matches']:
            payload = {'query': result['query'], 'type': row['type'], 'imdb_id': row['imdb_id'],
                       'title': row['title'], 'year': row['year'], 'context': context,
                       'metadata_id': row['metadata_id'], 'sources': {}}
            token = _preview('metadata', payload)
            matches.append({key: row[key] for key in ('imdb_id', 'type', 'title', 'year')} | {
                'metadata_token': token})
        return {'available': True, 'matches': matches, 'expires_seconds': _PREVIEW_SECONDS}
    except MediaUnavailable as error:
        return {'available': False, 'matches': [], 'reason': str(error)}


@router.get('/sources')
async def sources(metadata_token: str, season: int | None = None, episode: int | None = None):
    from ...media import discovery
    try:
        metadata = _preview_record(metadata_token, 'metadata')['payload']
        key = (season, episode)
        if key in metadata['sources']:
            return metadata['sources'][key]
        context = metadata['context']
        result = await discovery.candidates(metadata['metadata_id'], season=season,
                                             episode=episode, context=context)
        output = []
        for row in result['candidates']:
            private = context['_media_acquisition_candidates'][row['candidate_id']]
            proof = {key: metadata[key] for key in ('query', 'type', 'imdb_id', 'title', 'year')}
            proof.update(season=season, episode=episode, fingerprint=source_fingerprint(private))
            token = _preview('source', proof)
            safe = {key: row[key] for key in ('title', 'resolution', 'seeders', 'size_bytes',
                    'preferred_language_match', 'hdr', 'remux', 'recommended')}
            safe.update(cached=row.get('cached', False), cache_provider=row.get('cache_provider'),
                        preview_token=token, release_label=discovery._text(private['release_title']) or 'Selected release',
                        imdb_id=metadata['imdb_id'], type=metadata['type'], season=season, episode=episode)
            # This is a projection of the exact private plan bound by the token.
            # Paths/native IDs remain private; the owner sees the full registration scope.
            safe.update({key: deepcopy(row[key]) for key in (
                'acquisition_scope', 'registered_files', 'pack_episodes', 'episode_plan', 'season_numbers',
                'selected_size_bytes') if key in row})
            if metadata['type'] == 'series' and row.get('cached'):
                safe.update(file_season=row.get('season'), file_episode=row.get('episode'),
                            file_episode_end=row.get('episode_end'))
            output.append(safe)
        response = {'available': True, 'candidates': output,
                    'ambiguous_best_tie': result.get('ambiguous_best_tie', False),
                    'expires_seconds': _PREVIEW_SECONDS}
        metadata['sources'][key] = response
        return response
    except MediaUnavailable as error:
        return {'available': False, 'candidates': [], 'reason': str(error)}



def _authorize(token: str | None):
    try:
        expected = read_token()
    except OSError:
        raise HTTPException(503, 'Native owner ingress is unavailable') from None
    if token is None or not hmac.compare_digest(token, expected):
        raise HTTPException(403, 'Native owner authentication required')


def _catalogue(query: str, offset: int, limit: int) -> dict:
    try:
        return {'available': True, **service.catalogue().browse(query, offset, limit)}
    except MediaUnavailable as error:
        return {'available': False, 'reason': str(error), 'items': [], 'next_offset': None}


@router.get('/catalogue')
async def catalogue(query: str = '', offset: int = 0, limit: int = 20):
    return await asyncio.to_thread(_catalogue, query, offset, limit)


@router.get('/selection')
async def selection(item_id: str, media_source_id: str):
    try:
        binding = await asyncio.to_thread(lambda: service.catalogue().select(item_id, media_source_id))
        return {key: binding[key] for key in ('item_id', 'media_source_id', 'source_revision', 'title')}
    except MediaUnavailable as error:
        raise HTTPException(409, str(error)) from None


def _resume(item_id: str) -> dict:
    try:
        progress = service.catalogue().resume(item_id)
        return {'available': True, **{key: progress[key] for key in
                ('item_id', 'position', 'played', 'persistence')}}
    except MediaUnavailable as error:
        return {'available': False, 'reason': str(error), 'persistence': 'unavailable'}


@router.get('/resume')
async def resume(item_id: str = Query(min_length=32, max_length=36)):
    return await asyncio.to_thread(_resume, item_id)


def _status():
    try:
        config = load_config()
    except MediaUnavailable as error:
        return {'available': False, 'reason': str(error), 'tv': None}
    # This read neither powers a TV nor creates its player.
    return {'available': bool(config.get('enabled')), 'server_available': bool(config.get('catalogue')),
            'tv': player.state()}


@router.get('/status')
async def status():
    from ...capabilities.media.acquire import status as acquisition_status
    result = await asyncio.to_thread(_status)
    result['acquisition'] = await acquisition_status()
    return result


@router.post('/commands', status_code=202)
async def command(request: Request, x_obsidience_owner: str | None = Header(default=None)):
    _authorize(x_obsidience_owner)
    content_length = request.headers.get('content-length')
    if content_length and (not content_length.isdecimal() or int(content_length) > 4096):
        raise HTTPException(413, 'Media command exceeds its bound')
    material = bytearray()
    async for part in request.stream():
        material.extend(part)
        if len(material) > 4096:
            raise HTTPException(413, 'Media command exceeds its bound')
    try:
        value = owner_media_command(json.loads(material))
        turn = await RUNTIME.submit('', owner_command=value, source='text', wait=False,
                                    memory_writeback=False)
    except (ValueError, UnicodeError) as error:
        raise HTTPException(409, str(error)) from None
    except RuntimeError as error:
        raise HTTPException(409, str(error)) from None
    return {'request_id': value['request_id'], 'turn_id': turn['id'],
            'status': 'admitted', 'duplicate': turn.get('duplicate', False)}


@router.get('/commands/{request_id}')
def command_receipt(request_id: str, x_obsidience_owner: str | None = Header(default=None)):
    _authorize(x_obsidience_owner)
    try:
        request_id = str(UUID(request_id))
    except ValueError:
        raise HTTPException(400, 'Invalid request UUID') from None
    turn = INDEX.owner_command_request(request_id)
    if turn is None:
        raise HTTPException(404, 'Media request was not admitted')
    return {'request_id': request_id, 'turn_id': turn['id'],
            'settled': turn['command_status'] != 'admitted',
            'run_id': turn['command_run_id'], 'summary': turn['command_summary'],
            'state': turn['command_status']}
