"""Authenticated Discord ingress into the bot's own ADK conversation owner."""
from __future__ import annotations

import hmac

from fastapi import APIRouter, Header, HTTPException, Request

from ....discord import client
from ....discord.config import SNOWFLAKE, ingress_secret, load_config

router = APIRouter(prefix='/api/discord', tags=['discord'])
_conversations = None
_unavailable = None


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


async def payload(request: Request, config: dict) -> dict:
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
    if not isinstance(value, dict) or set(value) - {
        'guild_id', 'channel_id', 'member_id', 'request_id', 'text', 'source',
        'generation', 'display_name', 'memory_writeback',
    }:
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
