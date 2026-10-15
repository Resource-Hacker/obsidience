"""Register one owner-selected source with the configured acquisition owner."""
from __future__ import annotations

import asyncio
from pathlib import PurePosixPath

from ...media.config import MediaUnavailable, load_config
from ...media import service
from ...media.tiramisu import Tiramisu, _episode_path_matches, _normal_hash
from ...media.sources import describe


async def _registered_path(client: Tiramisu, candidate: dict) -> str:
    kind = 'movie' if candidate['type'] == 'movie' else 'tv'
    directory = 'movies' if kind == 'movie' else 'tv'
    status, rows = await client._request('GET', f'/api/library/list?type={kind}', timeout=6)
    if status != 200 or not isinstance(rows, list) or len(rows) > 32:
        raise MediaUnavailable('tiramisu_registration_readback_unavailable')
    config = load_config()
    roots = []
    for root in config['roots']:
        mount_path = root.get('mount_path')
        if not mount_path:
            continue
        try:
            mount_relative = PurePosixPath(root['path']).relative_to(mount_path).as_posix()
        except ValueError:
            continue
        if mount_relative == directory:
            roots.append(root)
    if len(roots) != 1:
        raise MediaUnavailable('virtual_media_root_unavailable')
    root = roots[0]
    expected = _normal_hash(candidate['hash'])
    paths = []
    for row in rows:
        if not isinstance(row, dict) or _normal_hash(row.get('hash')) != expected:
            continue
        if candidate['type'] == 'movie':
            matches = row.get('imdb') == candidate['imdb']
        else:
            matches = (row.get('season') == candidate['season']
                       and row.get('episode') == candidate['episode']
                       and _episode_path_matches(row.get('path'), candidate))
        fuse_path = row.get('fuse_path')
        if not matches or not isinstance(fuse_path, str) or len(fuse_path) > 4096:
            continue
        parts = fuse_path.split('/')
        if (len(parts) < 2 or parts[0] != directory
                or any(part in ('', '.', '..') for part in parts)
                or PurePosixPath(fuse_path).suffix.lower() != '.mkv'):
            continue
        relative = '/'.join(parts[1:])
        # The list's path is the provider's private stub, not the mounted media.
        # Reuse exact mount/socket/list identity admission for the virtual path.
        validation = asyncio.create_task(asyncio.to_thread(describe, config, root['id'], relative))
        try:
            await asyncio.shield(validation)
        except asyncio.CancelledError:
            try:
                await asyncio.shield(validation)
            except Exception:
                pass
            raise
        paths.append(root['catalogue_path'].rstrip('/') + '/' + relative)
    if len(paths) != 1:
        raise MediaUnavailable('tiramisu_registration_path_ambiguous')
    return paths[0]


async def _refresh_catalogue(client: Tiramisu, candidate: dict, cancel) -> dict:
    if cancel is not None and cancel.is_set():
        return {'status': 'pending', 'reason': 'refresh_skipped_cancelled'}
    try:
        if candidate.get('debrid_binding'):
            from ...media.torbox_files import refresh
            config = load_config()
            registered = candidate['_context']['_media_registered_file']
            registered = await client.organize(registered, candidate['type'], cancel)
            work = asyncio.create_task(asyncio.to_thread(refresh, config, registered))
            try:
                path = await asyncio.shield(work)
            except asyncio.CancelledError:
                try:
                    await asyncio.shield(work)
                except Exception:
                    pass
                raise
        else:
            path = await _registered_path(client, candidate)
        if cancel is not None and cancel.is_set():
            return {'status': 'pending', 'reason': 'refresh_skipped_cancelled'}
        catalogue = service.catalogue()
        operation = asyncio.create_task(
            asyncio.to_thread(catalogue.refresh_registered_path, path, cancel))
        try:
            return await asyncio.shield(operation)
        except asyncio.CancelledError:
            # Await the owned bounded operation; never leave its HTTP request detached.
            try:
                await asyncio.shield(operation)
            except Exception:
                pass
            return {'status': 'pending', 'reason': 'catalogue_refresh_interrupted'}
    except asyncio.CancelledError:
        return {'status': 'pending', 'reason': 'catalogue_refresh_interrupted'}
    except MediaUnavailable as error:
        return {'status': 'pending', 'reason': str(error)}
    except Exception:
        return {'status': 'pending', 'reason': 'catalogue_unavailable'}


async def status() -> dict:
    """Bounded provider evidence; a socket alone is not readiness."""
    try:
        config = load_config()
        if not config.get('enabled'):
            return {'enabled': False, 'providers': [], 'readiness': 'media_acquisition_unavailable'}
        acquisition = config.get('acquisition')
        discovery = config.get('discovery')
        if not isinstance(acquisition, dict) or acquisition.get('enabled') is not True:
            return {'enabled': False, 'providers': [], 'readiness': 'media_acquisition_disabled'}
        if not isinstance(discovery, dict) or discovery.get('enabled') is not True:
            return {'enabled': False, 'providers': ['tiramisu'],
                    'readiness': 'media_discovery_disabled'}
        client = Tiramisu()
        code, health = await client._request('GET', '/health', timeout=3)
        if (code != 200 or not isinstance(health, dict) or health.get('ready') is not True
                or health.get('draining') is not False):
            raise MediaUnavailable('tiramisu_not_ready')
        if config.get('debrid', {}).get('enabled'):
            from ...media.torbox import TorBoxAPI
            from ...media.torbox_files import ready_mount
            roots = [r for r in config['roots'] if r.get('provider') == 'torbox']
            if not roots:
                raise MediaUnavailable('torbox_root_unavailable')
            ready_mount(roots[0])
            account = await TorBoxAPI().account()
            if not account['paid_active']:
                raise MediaUnavailable('torbox_paid_account_required')
            return {'enabled': True, 'ready': True,
                    'providers': ['cinemeta', discovery['provider'], 'torbox'],
                    'discovery_configured': health.get('discovery_configured') is True,
                    'cache_only': True, 'plan': account['plan'],
                    'disk_cache': False, 'offline_guaranteed': False}
        return {'enabled': True,
                'providers': ['cinemeta', discovery.get('provider', 'torrentio'), 'tiramisu'],
                'transport': 'owner_unix_socket', 'ready': True,
                'discovery_configured': health.get('discovery_configured') is True,
                'disk_cache': False, 'offline_guaranteed': False}
    except MediaUnavailable as error:
        return {'enabled': False, 'providers': [], 'readiness': str(error)}


async def execute(args: dict, context: dict) -> dict:
    result = {'status': 'failed', 'delivery': 'not_dispatched',
              'effect_applied': False, 'must_not_replay': True}
    if (not isinstance(args, dict) or set(args) != {'action', 'candidate_id'}
            or args.get('action') != 'register'
            or not isinstance(args.get('candidate_id'), str)
            or not args['candidate_id'].startswith('a')
            or len(args['candidate_id']) > 64):
        return {**result, 'failure': {'code': 'invalid_media_acquisition_arguments'}}
    if (context.get('_agent_ref') != 'Agents/Executive/Executive'
            or context.get('task') != 'Agents/Executive/Executive'):
        return {**result, 'failure': {'code': 'media_acquisition_scope_denied'}}
    cancel = context.get('_capability_cancel_event')
    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError
    run_id = context.get('run_id')
    candidates = context.get('_media_acquisition_candidates')
    candidate = candidates.get(args['candidate_id']) if isinstance(candidates, dict) else None
    if (not isinstance(run_id, str) or not isinstance(candidate, dict)
            or candidate.get('run_id') != run_id):
        return {**result, 'failure': {'code': 'media_candidate_stale'}}
    if candidate.get('register_attempted'):
        return {**result, 'failure': {'code': 'media_candidate_already_attempted',
                                      'correction_allowed': False}}
    metadata = context.get('_media_discovery_candidates', {}).get(candidate.get('metadata_id'))
    if (not isinstance(metadata, dict) or metadata.get('run_id') != run_id
            or any(candidate.get(key) != metadata.get(key) for key in
                   ('imdb', 'type', 'provider', 'instance_id', 'config_fingerprint', 'socket_identity', 'debrid_binding'))):
        return {**result, 'failure': {'code': 'media_candidate_stale'}}
    if candidate.get('type') not in ('movie', 'series'):
        return {**result, 'failure': {'code': 'media_candidate_invalid'}}
    if candidate['type'] == 'series' and (
            type(candidate.get('season')) is not int or type(candidate.get('episode')) is not int
            or not candidate.get('first_air_date')):
        return {**result, 'failure': {'code': 'media_episode_not_verified'}}

    lock = context.setdefault('_media_acquisition_lock', asyncio.Lock())
    async with lock:
        duplicate_key = (_normal_hash(candidate.get('hash')), candidate.get('type'),
                         candidate.get('season'), candidate.get('episode'))
        attempts = context.setdefault('_media_acquisition_attempts', set())
        if not duplicate_key[0] or duplicate_key in attempts:
            return {**result, 'failure': {'code': 'media_source_already_attempted',
                                          'correction_allowed': False}}
        # Key attempts by source identity, not opaque candidate id. Consume before the
        # preflight read so a second candidate cannot race a first registration.
        attempts.add(duplicate_key)
        candidate['register_attempted'] = True
        candidate['_context'] = context
        try:
            client = Tiramisu()
            client.validate_binding(candidate)
            if load_config().get('debrid', {}).get('enabled'):
                from ...media.torbox import TorBoxAPI
                from ...media.torbox_files import ready_mount
                config = load_config()
                roots = [r for r in config['roots'] if r.get('provider') == 'torbox']
                if not roots:
                    raise MediaUnavailable('torbox_root_unavailable')
                ready_mount(roots[0])
                client = TorBoxAPI()
                client.validate_binding(candidate)
            registered = await client.register(candidate, cancel)
            if registered.get('status') == 'completed':
                registered['catalogue'] = await _refresh_catalogue(client, candidate, cancel)
            return registered
        except asyncio.CancelledError:
            raise
        except MediaUnavailable as error:
            outcome = context.get('_media_acquisition_outcome')
            if isinstance(outcome, dict) and outcome.get('delivery') == 'uncertain':
                return outcome
            return {**result, 'failure': {'code': str(error), 'correction_allowed': False}}
        finally:
            candidate.pop('_context', None)
