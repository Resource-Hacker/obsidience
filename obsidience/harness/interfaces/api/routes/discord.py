"""Authenticated Discord ingress into the bot's own ADK conversation owner."""
from __future__ import annotations

import asyncio
import contextlib
import hmac
import re

from fastapi import APIRouter, Header, HTTPException, Request

from ....discord import client
from ....discord.config import SNOWFLAKE, ingress_secret, load_config

router = APIRouter(prefix='/api/discord', tags=['discord'])
_conversations = None
_unavailable = None
_NEXT_FIELDS = {'generation', 'guild_id', 'channel_id', 'member_id', 'request_id',
                'continuous_id', 'query', 'artist', 'current', 'recent'}


async def start() -> None:
    global _conversations, _unavailable
    # Optional integration failure cannot take down desktop conversation.
    try:
        config = load_config()
        if not config['enabled']:
            return
        ingress_secret()
    except (OSError, ValueError):
        _unavailable = 'configuration_or_credential_unavailable'
        return
    from ....discord.conversation import DiscordConversations
    owner = DiscordConversations()
    try:
        await owner.start()
    except Exception:
        _unavailable = 'conversation_start_failed'
        return
    _conversations = owner
    _unavailable = None


async def close() -> None:
    global _conversations
    owner, _conversations = _conversations, None
    if owner is not None:
        await owner.close()


def authorize(authorization: str | None) -> dict:
    try:
        config = load_config()
        expected = ingress_secret()
    except (OSError, ValueError):
        raise HTTPException(503, 'Discord integration is unavailable') from None
    if (not config['enabled'] or authorization is None
            or not hmac.compare_digest(authorization, 'Bearer ' + expected)):
        raise HTTPException(403, 'Discord ingress authentication required')
    return config


async def payload(request: Request, config: dict, *, fields: set[str] | None = None) -> dict:
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 16384:
            raise HTTPException(413, 'Discord request is too large')
    try:
        import json
        value = json.loads(raw)
    except ValueError:
        raise HTTPException(400, 'Invalid Discord request') from None
    if not isinstance(value, dict) or set(value) - (fields if fields is not None else {
        'guild_id', 'channel_id', 'member_id', 'request_id', 'text', 'source',
        'generation', 'display_name', 'memory_writeback',
    }):
        raise HTTPException(400, 'Invalid Discord request fields')
    if (value.get('guild_id') != config['guild_id']
            or any(not isinstance(value.get(k), str) or not SNOWFLAKE.fullmatch(value[k])
                   for k in ('channel_id', 'member_id'))
            or (config.get('allowed_channel_ids') and value['channel_id'] not in config['allowed_channel_ids'])):
        raise HTTPException(403, 'Discord request is outside the configured server or channels')
    if not isinstance(value.get('request_id'), str) or not 1 <= len(value['request_id']) <= 128:
        raise HTTPException(400, 'A bounded Discord request identity is required')
    if 'memory_writeback' in value and type(value['memory_writeback']) is not bool:
        raise HTTPException(400, 'memory_writeback must be boolean')
    return value


def _next_payload(value: dict) -> None:
    def text(item, limit, *, empty=False):
        return (isinstance(item, str) and (empty or bool(item.strip()))
                and len(item) <= limit and not any(ord(c) < 32 or ord(c) == 127 for c in item))
    if (set(value) != _NEXT_FIELDS
            or any(not text(value.get(k), 128) for k in ('generation', 'continuous_id', 'request_id'))
            or not text(value.get('query'), 120, empty=True)
            or not text(value.get('artist'), 80, empty=True)):
        raise HTTPException(400, 'Invalid next music request')
    current = value['current']
    if current is not None:
        if (not isinstance(current, dict) or set(current) != {'playback_request_id', 'source', 'title', 'artist'}
                or not text(current.get('playback_request_id'), 128)
                or not text(current.get('title'), 160, empty=True)
                or not text(current.get('artist'), 80, empty=True)):
            raise HTTPException(400, 'Invalid current music identity')
        source = current['source']
        if source is not None and (not isinstance(source, dict) or set(source) != {'provider', 'video_id'}
                or source.get('provider') != 'youtube' or not isinstance(source.get('video_id'), str)
                or not re.fullmatch(r'[A-Za-z0-9_-]{11}', source['video_id'])):
            raise HTTPException(400, 'Invalid current music source')
    if not (value['query'].strip() or value['artist'].strip()
            or current and (current['title'].strip() or current['artist'].strip())):
        raise HTTPException(400, 'A bounded music seed is required')
    recent = value['recent']
    if (not isinstance(recent, list) or len(recent) > 20
            or any(not isinstance(identity, str) or not re.fullmatch(
                r'(?:youtube:[A-Za-z0-9_-]{11}|soundcloud:[0-9]{1,20})', identity) for identity in recent)):
        raise HTTPException(400, 'Invalid recent music identities')


@router.post('/next')
async def next_music(request: Request, authorization: str | None = Header(default=None)):
    """Select once from native Media; Node retains all mode, membership and playback ownership."""
    from ....media import online_music
    from ....media.config import MediaUnavailable
    config = authorize(authorization)
    lookup = watcher = None
    try:
        # Leave room for the transport's 14-second HTTP budget. Native search has
        # a 9.5-second child budget and always kills/reaps it on cancellation.
        async with asyncio.timeout(11.5):
            value = await payload(request, config, fields=_NEXT_FIELDS)
            _next_payload(value)
            state = await client.command({'command': 'status', 'guild_id': value['guild_id'],
                'member_id': value['member_id'], 'request_id': value['request_id']}, timeout=1.5)
            mode = state.get('continuous')
            if (state.get('ok') is not True or state.get('ready') is not True or state.get('voice') != 'ready'
                    or any(state.get(k) != value[k] for k in ('generation', 'guild_id', 'channel_id'))
                    or not isinstance(mode, dict) or mode.get('enabled') is not True
                    or mode.get('paused') is not False or mode.get('id') != value['continuous_id']
                    or any(mode.get(k) != value[k] for k in ('member_id', 'query', 'artist'))):
                raise HTTPException(409, 'Continuous music ownership is not current')
            lookup = asyncio.create_task(online_music.select_next(
                value['query'], value['artist'], current=value['current'], recent=value['recent']))

            async def watch_disconnect():
                while not lookup.done():
                    if await request.is_disconnected():
                        lookup.cancel()
                        return
                    await asyncio.sleep(.1)

            watcher = asyncio.create_task(watch_disconnect())
            return await lookup
    except (OSError, ValueError, TimeoutError, MediaUnavailable):
        raise HTTPException(409, 'Next music selection is unavailable') from None
    finally:
        if watcher is not None:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
        if lookup is not None:
            if not lookup.done():
                lookup.cancel()
            with contextlib.suppress(asyncio.CancelledError, MediaUnavailable, OSError, ValueError):
                await lookup


@router.get('/status')
async def status():
    try:
        enabled = load_config()['enabled']
    except (OSError, ValueError):
        enabled = False
    return {'enabled': enabled, 'conversation_ready': _conversations is not None,
            'unavailable': _unavailable,
            'active_turns': _conversations.status()['active_turns'] if _conversations else 0,
            'agent_ref': 'Agents/Discord/Discord', 'name': 'Obsidience Discord Bot',
            'transport': await client.command({'command': 'status'}, timeout=2) if enabled else None}


@router.post('/turns')
async def turns(request: Request, authorization: str | None = Header(default=None)):
    config = authorize(authorization)
    value = await payload(request, config)
    if _conversations is None:
        raise HTTPException(503, 'Discord conversations are not ready')
    if value.get('source', 'text') not in ('text', 'voice'):
        raise HTTPException(400, 'Invalid Discord input transport')
    try:
        return await _conversations.submit(
            value.get('text', ''), guild_id=value['guild_id'], channel_id=value['channel_id'],
            member_id=value['member_id'], request_id=value['request_id'],
            source=value.get('source', 'text'), display_name=value.get('display_name', ''),
            memory_writeback=value.get('memory_writeback') is not False)
    except ValueError:
        raise HTTPException(400, 'Discord turn could not be admitted') from None
    except RuntimeError:
        raise HTTPException(409, 'Discord conversation is unavailable or already active') from None


@router.post('/cancel')
async def cancel(request: Request, authorization: str | None = Header(default=None)):
    config = authorize(authorization)
    value = await payload(request, config)
    if _conversations is not None:
        await _conversations.cancel(guild_id=value['guild_id'], channel_id=value['channel_id'],
                                    member_id=value['member_id'], request_id=value['request_id'])
    return {'status': 'cancelled'}
