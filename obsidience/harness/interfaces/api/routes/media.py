"""Independent catalogue views and authenticated native owner command ingress."""
from __future__ import annotations

import asyncio
import hmac
import secrets
from copy import deepcopy
import json
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request

from ....conversation.runtime import RUNTIME
from ....execution.commands import owner_media_command
from ....knowledge.index import INDEX
from ....media import service
from ....media.config import MediaUnavailable, load_config
from ....media.previews import PREVIEW_SECONDS, issue_preview, preview_record, source_fingerprint
from ....tv import player
from obsidience.shell.command_token import read_token

router = APIRouter(prefix='/api/media', tags=['media'])


@router.get('/search')
async def search(query: str, content_type: str = 'movie'):
    from ....media import discovery
    # This is a read-only preview namespace, not an admitted execution or fabricated Agent.
    context = {'run_id': 'preview-' + secrets.token_hex(16)}
    try:
        result = await discovery.search(query, content_type, context)
        matches = []
        for row in result['matches']:
            payload = {'query': result['query'], 'type': row['type'], 'imdb_id': row['imdb_id'],
                       'title': row['title'], 'year': row['year'], 'context': context,
                       'metadata_id': row['metadata_id'], 'sources': {}}
            token = issue_preview('metadata', payload)
            matches.append({key: row[key] for key in ('imdb_id', 'type', 'title', 'year')} | {
                'metadata_token': token})
        return {'available': True, 'matches': matches, 'expires_seconds': PREVIEW_SECONDS}
    except MediaUnavailable as error:
        return {'available': False, 'matches': [], 'reason': str(error)}


@router.get('/sources')
async def sources(metadata_token: str, season: int | None = None, episode: int | None = None):
    from ....media import discovery
    try:
        metadata = preview_record(metadata_token, 'metadata')['payload']
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
            token = issue_preview('source', proof)
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
                    'expires_seconds': PREVIEW_SECONDS}
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
    from ....capabilities.media.acquire import status as acquisition_status
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
