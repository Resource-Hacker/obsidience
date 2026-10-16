"""Agent-scoped Discord control; Media retains source admission authority."""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid

from ...discord import client
from ...discord.config import AGENT_REF, SNOWFLAKE, load_config
from ...media import service, sources
from ...media.config import MediaUnavailable


def rejected(reason: str) -> dict:
    return {'status': 'failed', 'delivery': 'not_dispatched', 'effect_applied': False,
            'failure': reason, 'correction_allowed': True}


async def execute(args: dict, context: dict) -> dict:
    if not isinstance(args, dict):
        raise ValueError('Discord arguments must be an object')
    action = args.get('action')
    fields = {'status': set(), 'channels': set(), 'join': {'channel_id'},
              'leave': set(), 'say': {'text'}, 'play': {'id', 'media_kind'},
              'pause': set(), 'resume': set(), 'stop': set()}
    if action not in fields or set(args) != {'action'} | fields[action]:
        raise ValueError('Invalid discord.control arguments')
    try:
        config = load_config()
    except (OSError, ValueError):
        return rejected('Discord configuration is unavailable')
    if not config['enabled']:
        return rejected('Discord integration is disabled')
    agent = context.get('_agent_ref')
    principal = context.get('_discord')
    if agent == AGENT_REF:
        if (not isinstance(principal, dict) or principal.get('guild_id') != config['guild_id']
                or not SNOWFLAKE.fullmatch(str(principal.get('member_id', '')))):
            return rejected('An admitted Discord member request is required')
    elif agent != 'Agents/Executive/Executive' or principal is not None:
        return rejected('Discord control requires its granted Agent identity')
    cancel = context.get('_capability_cancel_event')
    if cancel is not None and cancel.is_set():
        return rejected('Discord control was cancelled')
    payload = {'command': action, 'guild_id': config['guild_id']}
    if principal:
        # The transport rechecks current membership and channel permissions.
        # Neither the model nor message content can select another principal.
        payload['member_id'] = principal['member_id']
    if action == 'join':
        if not isinstance(args['channel_id'], str) or not SNOWFLAKE.fullmatch(args['channel_id']):
            raise ValueError('A current Discord voice channel id is required')
        payload['channel_id'] = args['channel_id']
    elif action == 'say':
        if principal:
            return rejected('Reply with the requested words as your normal answer; the Discord transport owns delivery')
        if not isinstance(args['text'], str) or not args['text'].strip() or len(args['text']) > 4000:
            raise ValueError('Discord speech must contain 1 to 4000 characters')
        payload['text'] = args['text']
    readonly = action in {'status', 'channels'}
    if not readonly:
        payload['request_id'] = uuid.uuid4().hex
        if principal and action == 'stop':
            payload['origin_request_id'] = principal['request_id']
    attempts = context.setdefault('_discord_control_attempts', {})
    attempt_key = json.dumps(args, sort_keys=True)
    if not readonly and attempt_key in attempts:
        return attempts[attempt_key]
    admitted = None
    try:
        if action == 'play':
            if args['media_kind'] != 'audio':
                return rejected('This Discord transport supports audio playback only')
            candidate = context.get('_media_candidates', {}).get(args['id'])
            if candidate is None:
                return rejected('Select the exact music or catalogue item in this turn before playback')
            if candidate.get('provider') in ('youtube', 'soundcloud'):
                from ...media import online_music
                from ...media.config import load_config as media_config
                current = online_music.revalidate(candidate)
                media = media_config()
                music = media.get('music') or {}
                if not media.get('enabled') or not music.get('enabled'):
                    return rejected('Online music is disabled')
                if current['provider'] == 'youtube' and music['delivery'] == 'torbox':
                    from ...media.web_music import prepare
                    # This provider can create an exact web source. Record the
                    # attempt before dispatch, including cancellation/uncertainty.
                    attempts[attempt_key] = {'status': 'failed', 'delivery': 'uncertain',
                                            'must_not_replay': True, 'failure': 'Music preparation was already attempted'}
                    prepared = await prepare(current, context, cancel)
                    if 'source' not in prepared:
                        attempts[attempt_key] = prepared
                        return prepared
                    payload['source'] = prepared['source']
                else:
                    if 'debrid_binding' in current:
                        return rejected('Music delivery configuration changed; select the track again')
                    field = 'video_id' if current['provider'] == 'youtube' else 'track_id'
                    payload['source'] = {'provider': current['provider'], field: current[field]}
            else:
                catalogue = service.catalogue()
                current = await asyncio.to_thread(catalogue.revalidate, candidate)
                descriptor = {key: current[key] for key in ('provider', 'root_id', 'relative_path', 'revision')}
                # Admission owns an FD; cancellation waits for bounded cleanup.
                pending = asyncio.create_task(asyncio.to_thread(sources.admit, catalogue.config, descriptor))
                try:
                    admitted = await asyncio.shield(pending)
                except asyncio.CancelledError:
                    try:
                        (await pending).close()
                    finally:
                        raise
                admitted.validate()
                payload['path'] = f'/proc/{os.getpid()}/fd/{admitted.fd}'
                info = os.fstat(admitted.fd)
                payload['file_identity'] = {key: str(value) for key, value in (
                    ('dev', info.st_dev), ('ino', info.st_ino), ('size', info.st_size), ('mtime_ns', info.st_mtime_ns))}
            if cancel is not None and cancel.is_set():
                if candidate.get('provider') in ('youtube', 'soundcloud'):
                    # A provider preparation may already exist; never mislabel
                    # this interrupted play as a safely repeatable non-effect.
                    attempts[attempt_key] = {'status': 'cancelled', 'delivery': 'not_dispatched',
                                            'must_not_replay': True}
                    raise asyncio.CancelledError
                else:
                    return rejected('Discord media playback was cancelled')
            payload['expires_at_ms'] = int(time.time() * 1000) + 14000
        if not readonly:
            attempts[attempt_key] = {'status': 'failed', 'delivery': 'uncertain',
                                    'must_not_replay': True, 'failure': 'This Discord action was already attempted'}
        pending = asyncio.create_task(client.command(payload, timeout=22 if action == 'join' else 15))
        try:
            result = await asyncio.shield(pending)
        except asyncio.CancelledError:
            # Finish the bounded handoff before releasing its descriptor. Cancel
            # only this playback, never whichever newer item happens to be live.
            await pending
            if action == 'play':
                await client.command({'command': 'cancel_media', 'request_id': uuid.uuid4().hex,
                                      'playback_request_id': payload['request_id']}, timeout=3)
            raise
        if not result.get('ok'):
            if action == 'play' and result.get('delivery') in {'uncertain', 'not_confirmed'}:
                await client.command({'command': 'cancel_media', 'request_id': uuid.uuid4().hex,
                                      'playback_request_id': payload['request_id']}, timeout=3)
            receipt = {**result, 'status': 'failed', 'must_not_replay': not readonly,
                       'failure': result.get('failure') or result.get('error') or 'Discord command was not confirmed'}
            if not readonly:
                attempts[attempt_key] = receipt
            return receipt
        receipt = {**result, 'status': 'completed'}
        if action == 'play':
            receipt.update(title=current['title'], item_id=current['item_id'],
                           media_kind='audio_only', video_supported=False,
                           verification='Audio entered the Discord player; this does not verify a listener heard it.')
        elif action == 'say':
            receipt['verification'] = 'Speech was requested; audible completion is not yet verified.'
        if not readonly:
            attempts[attempt_key] = receipt
        return receipt
    except MediaUnavailable:
        if action == 'play' and attempt_key in attempts:
            return attempts[attempt_key]
        return rejected('The exact selected media source is unavailable or changed')
    finally:
        if admitted is not None:
            admitted.close()
