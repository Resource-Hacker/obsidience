"""Discord member moderation bound to one admitted speaker and activation."""
from __future__ import annotations

import asyncio
import time
import uuid

from ...discord import client
from ...discord.config import AGENT_REF, SNOWFLAKE, load_config


def rejected(reason: str, *, correction: bool = True) -> dict:
    return {'status': 'failed', 'delivery': 'not_dispatched', 'effect_applied': False,
            'failure': reason, 'correction_allowed': correction}


async def execute(args: dict, context: dict) -> dict:
    fields = {'members': {'query'}, 'kick': {'id', 'reason'}}
    if (not isinstance(args, dict) or args.get('action') not in fields
            or set(args) != {'action'} | fields[args['action']]):
        raise ValueError('Invalid discord.admin arguments')
    action = args['action']
    for key, limit in (('query', 100), ('id', 64), ('reason', 256)):
        if key in args and (not isinstance(args[key], str) or len(args[key]) > limit
                            or any(ord(char) < 32 for char in args[key])):
            raise ValueError('Discord administration requires bounded text arguments')
    principal = context.get('_discord')
    if context.get('_agent_ref') != AGENT_REF or not isinstance(principal, dict):
        return rejected('Administration requires the admitted Discord Agent speaker; no Executive bypass')
    try:
        config = load_config()
    except (OSError, ValueError):
        return rejected('Discord configuration is unavailable')
    if not config['enabled'] or principal.get('guild_id') != config['guild_id']:
        return rejected('The admitted Discord server is unavailable')
    if (not all(SNOWFLAKE.fullmatch(str(principal.get(key, '')))
                for key in ('guild_id', 'channel_id', 'member_id'))
            or not isinstance(principal.get('request_id'), str) or not principal['request_id']):
        return rejected('An exact admitted Discord request is required')
    cancel = context.get('_capability_cancel_event')
    if cancel is not None and cancel.is_set():
        return rejected('Discord administration was cancelled')
    payload = {'command': 'admin_' + action, 'guild_id': principal['guild_id'],
               'member_id': principal['member_id'], 'channel_id': principal['channel_id'],
               'origin_request_id': principal['request_id']}
    if action == 'members':
        payload['query'] = args['query'].strip()
    else:
        if '_discord_admin_attempt' in context:
            return {**context['_discord_admin_attempt'], 'must_not_replay': True,
                    'correction_allowed': False}
        selection = context.get('_discord_admin_candidates', {}).get(args['id'])
        if selection is None or time.monotonic() >= selection['expires_at']:
            return rejected('Discover the exact member with discord.admin members in this activation first')
        payload.update(request_id=uuid.uuid4().hex, target_member_id=selection['member_id'],
                       reason=args['reason'].strip())
        # Latch before entering transport, even if cancellation or a lost reply
        # leaves delivery unknown. No alternate target or new ID can replay it.
        context['_discord_admin_attempt'] = {
            'status': 'failed', 'delivery': 'uncertain', 'effect_applied': None,
            'must_not_replay': True, 'correction_allowed': False,
            'failure': 'This activation already attempted a server kick; outcome is uncertain'}
    pending = asyncio.create_task(client.command(payload, timeout=20 if action == 'kick' else 10))
    try:
        result = await asyncio.shield(pending)
    except asyncio.CancelledError:
        # This command has no repeat/cancel effect. Drain its one native request
        # so teardown cannot discard an in-flight kick or dispatch a replacement.
        settled = await asyncio.gather(pending, return_exceptions=True)
        if action == 'kick' and isinstance(settled[0], dict):
            context['_discord_admin_attempt'] = _kick_receipt(settled[0], payload['target_member_id'])
        raise
    if action == 'kick':
        receipt = _kick_receipt(result, payload['target_member_id'])
        context['_discord_admin_attempt'] = receipt
        return receipt
    if result.get('ok') is not True:
        return {**result, 'status': 'failed', 'effect_applied': False,
                'failure': result.get('failure') or result.get('error') or 'Member discovery is unavailable'}
    if result.get('origin_request_id') != principal['request_id'] or result.get('channel_id') != principal['channel_id']:
        return rejected('Discord member discovery binding changed')
    members = result.get('members')
    if not isinstance(members, list) or len(members) > 10:
        return rejected('Discord member discovery returned an invalid selection')
    candidates = {}
    public = []
    for member in members:
        if not isinstance(member, dict) or not SNOWFLAKE.fullmatch(str(member.get('member_id', ''))):
            return rejected('Discord member discovery returned an invalid member')
        identifier = uuid.uuid4().hex
        candidates[identifier] = {'member_id': member['member_id'], 'expires_at': time.monotonic() + 60}
        public.append({'id': identifier, **{key: member[key] for key in (
            'display_name', 'username', 'roles', 'roles_truncated', 'administrator',
            'current_voice_channel_id', 'in_bot_voice', 'kickable') if key in member}})
    # Replacing the discovery set invalidates all prior opaque selections.
    context['_discord_admin_candidates'] = candidates
    return {'status': 'completed', 'members': public, 'labels_untrusted': True,
            'selection_expires_in_seconds': 60,
            **({'speaker': result['speaker'], 'speaker_context_advisory': True}
               if isinstance(result.get('speaker'), dict) else {})}


def _kick_receipt(result: dict, target_member_id: str) -> dict:
    confirmed = (result.get('ok') is True and result.get('kicked') is True
                 and result.get('target_member_id') == target_member_id
                 and result.get('delivery') == 'confirmed' and result.get('effect_applied') is True)
    return {**result, 'status': 'completed' if confirmed else 'failed',
            'correction_allowed': False,
            **({'verification': 'The exact selected member is absent from the server after one kick.'}
               if confirmed else {'must_not_replay': True,
                   'failure': result.get('failure') or result.get('error') or 'Server removal was not confirmed'})}
