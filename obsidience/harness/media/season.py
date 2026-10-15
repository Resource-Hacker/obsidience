"""Read-only, exact season plans; Jellyfin remains the sole watch-state owner."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import re
import secrets
import time

from . import discovery, service
from .config import MediaUnavailable, load_config

_MAX_EPISODES = 256


def episode_roster(document: dict, imdb: str, season: int) -> list[dict]:
    """Validate Cinemeta's complete numbered season; never infer from names.

    Includes future episodes with their release timestamps so callers can reject
    their acquisition. Titles are presentation only; each identity is the exact
    series IMDb id plus its paired season and episode.
    """
    if (not isinstance(imdb, str) or not discovery._IMDB.fullmatch(imdb)
            or type(season) is not int or not 1 <= season <= 99):
        raise MediaUnavailable('media_season_arguments_invalid')
    meta = document.get('meta') if isinstance(document, dict) else None
    videos = meta.get('videos') if isinstance(meta, dict) else None
    if (not isinstance(meta, dict) or meta.get('id') != imdb
            or meta.get('type') != 'series' or not isinstance(videos, list)
            or len(videos) > 10000):
        raise MediaUnavailable('discovery_episode_unavailable')
    rows, numbers = [], set()
    for video in videos:
        if not isinstance(video, dict) or video.get('season') != season:
            continue
        episode = video.get('episode')
        released = video.get('released')
        if (type(video.get('season')) is not int or type(episode) is not int
                or not 1 <= episode <= 999 or episode in numbers
                or video.get('id') != f'{imdb}:{season}:{episode}'
                or not isinstance(released, str)
                or not re.fullmatch(r'(?:19|20)\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z', released)):
            raise MediaUnavailable('discovery_season_identity_unverified')
        try:
            datetime.fromisoformat(released.replace('Z', '+00:00'))
        except ValueError:
            raise MediaUnavailable('discovery_season_identity_unverified') from None
        tvdb = video.get('tvdb_id')
        if tvdb is not None and (type(tvdb) is not int or not 1 <= tvdb <= 10**10):
            raise MediaUnavailable('discovery_season_identity_unverified')
        numbers.add(episode)
        rows.append({'episode_id': video['id'], 'season': season, 'episode': episode,
                     'title': (discovery._text(video.get('title'))
                               or discovery._text(video.get('name'))
                               or f'Season {season} Episode {episode}'),
                     'released': released, 'tvdb_id': str(tvdb) if tvdb is not None else None})
    if (not rows or len(rows) > _MAX_EPISODES
            or numbers != set(range(1, max(numbers) + 1))):
        raise MediaUnavailable('discovery_season_incomplete_or_unavailable')
    return sorted(rows, key=lambda row: row['episode'])


def _merge(roster: list[dict], state: list[dict], mode: str) -> tuple[list[dict], dict | None]:
    """Coalesce native combined files without inventing per-part watch state."""
    by_episode = {row['episode']: row for row in roster}
    native = {}
    for row in state:
        first = row['episode']
        span = range(first, row['episode_end'] + 1)
        if any(number not in by_episode for number in span):
            raise MediaUnavailable('catalogue_episode_numbering_conflict')
        tvdb = by_episode[first]['tvdb_id']
        if tvdb is not None and row['tvdb_id'] is not None and tvdb != row['tvdb_id']:
            raise MediaUnavailable('catalogue_episode_numbering_conflict')
        for number in span:
            native[number] = row
    now = datetime.now(timezone.utc)
    rows, future_seen = [], False
    for item in roster:
        future = datetime.fromisoformat(item['released'].replace('Z', '+00:00')) > now
        if future_seen and not future:
            raise MediaUnavailable('discovery_season_release_order_unverified')
        future_seen |= future
        number = item['episode']
        current = native.get(number)
        if current is not None and number != current['episode']:
            continue
        end = current['episode_end'] if current else number
        if any(datetime.fromisoformat(by_episode[n]['released'].replace('Z', '+00:00')) > now
               for n in range(number, end + 1)):
            continue
        rows.append({key: value for key, value in item.items() if key != 'tvdb_id'} | {
            'episode_end': end, 'played': current['played'] if current else False,
            'resume_position': current['resume_position'] if current else 0.0,
            'catalogue': current['catalogue'] if current else []})
    selected = next((row for row in rows if mode == 'first' or not row['played']), None)
    return rows, selected


async def plan(metadata_id: str, season: int, mode: str, context: dict) -> dict:
    """Resolve one owner-selected series and explicit season without effects."""
    run_id = discovery._run(context)
    if (not isinstance(metadata_id, str) or type(season) is not int
            or not 1 <= season <= 99 or mode not in ('first', 'next_unwatched')):
        raise MediaUnavailable('media_season_arguments_invalid')
    metadata = context.get('_media_discovery_candidates', {}).get(metadata_id)
    if (not isinstance(metadata, dict) or metadata.get('run_id') != run_id
            or metadata.get('type') != 'series'
            or not isinstance(metadata.get('imdb'), str)
            or not discovery._IMDB.fullmatch(metadata['imdb'])):
        raise MediaUnavailable('media_metadata_selection_stale')
    calls = context.setdefault('_media_season_calls', 0)
    if type(calls) is not int or calls >= 4:
        raise MediaUnavailable('media_season_search_limit')
    context['_media_season_calls'] = calls + 1
    config = load_config()
    client = service.catalogue()
    from .tiramisu import Tiramisu
    transport = Tiramisu()
    transport.validate_binding(metadata)
    cached = None
    if config.get('debrid', {}).get('enabled'):
        from .torbox import TorBoxAPI
        cached = TorBoxAPI()
        cached.validate_binding(metadata)
    _, discovery_config = discovery._config()
    origin = discovery._https_origin(discovery_config['catalogue_url'], 'v3-cinemeta.strem.io')
    document = await discovery._json_get(f'{origin}/meta/series/{metadata["imdb"]}.json',
                                          cancel=context.get('_capability_cancel_event'))
    roster = episode_roster(document, metadata['imdb'], season)
    # Cancellation owns this blocking read through completion so the catalogue
    # client cannot be closed/replaced under a detached worker.
    reading = asyncio.create_task(asyncio.to_thread(client.season_state, metadata['imdb'], season))
    try:
        state = await asyncio.shield(reading)
    except asyncio.CancelledError:
        try:
            await asyncio.shield(reading)
        except Exception:
            pass
        raise
    # Reads may span a config replacement or cancellation; discard the whole plan.
    discovery._run(context)
    if load_config() != config or service.catalogue() is not client:
        raise MediaUnavailable('media_season_configuration_changed')
    transport.validate_binding(metadata)
    if cached is not None:
        cached.validate_binding(metadata)
    rows, selected = _merge(roster, state, mode)
    if not rows:
        raise MediaUnavailable('media_season_not_yet_released')
    released_count = sum(row['episode_end'] - row['episode'] + 1 for row in rows)
    selection = 'selected' if selected else ('caught_up' if released_count < len(roster) else 'season_complete')
    plan_id, sequence, stop_reason = None, [], None
    if selected is not None:
        for row in rows[rows.index(selected):]:
            if not row['catalogue']:
                stop_reason = 'catalogue_episode_missing'
                break
            if len(row['catalogue']) != 1:
                stop_reason = 'catalogue_source_ambiguous'
                break
            if len(sequence) >= 100:
                stop_reason = 'media_season_queue_limit'
                break
            sequence.append({**row['catalogue'][0],
                             'season': season, 'episode': row['episode'],
                             'episode_end': row['episode_end'], 'title': row['title']})
        if sequence:
            plans = context.setdefault('_media_seasons', {})
            if len(plans) >= 4:
                raise MediaUnavailable('media_season_plan_limit')
            plan_id = 's' + secrets.token_hex(3)
            while plan_id in plans:
                plan_id = 's' + secrets.token_hex(3)
            plans[plan_id] = {'run_id': run_id, 'metadata': dict(metadata),
                              'config': config, 'imdb': metadata['imdb'],
                              'season': season, 'mode': mode, 'entries': sequence,
                              'state': state, 'created_monotonic': time.monotonic(),
                              'stop_reason': stop_reason}
    sequence_info = {'count': len(sequence), 'stop_reason': stop_reason,
                     'scope': 'remaining_in_explicit_season'}
    if plan_id is not None:
        sequence_info['id'] = plan_id
    return {'status': 'completed', 'selection': selection,
            'metadata_id': metadata_id, 'imdb_id': metadata['imdb'],
            'title': discovery._text(metadata.get('title')) or 'Series',
            'season': season, 'mode': mode, 'episodes': rows, 'selected': selected,
            'episode_count': len(roster), 'released_episode_count': released_count,
            'unreleased_episode_count': len(roster) - released_count,
            'persistence': 'jellyfin_read_back', 'sequence': sequence_info,
            **({'id': plan_id} if plan_id else {}),
            'note': 'Read-only plan. Select exact catalogue item/source for playback; if absent, '
                    'discover this metadata_id with the selected season/episode and register one '
                    'exact source. Combined episodes share native file progress. Never skip a '
                    'missing episode, infer a position within a combined file, or advance to another season.'}


def resolve(plan_id: str, context: dict) -> dict:
    """Revalidate one activation plan into existing source bindings, GET/stat only.

    The caller owns playback dispatch. No path or source descriptor returned
    here may be projected into model-visible results.
    """
    run_id = discovery._run(context)
    if not isinstance(plan_id, str) or not re.fullmatch(r's[0-9a-f]{6}', plan_id):
        raise MediaUnavailable('media_season_selection_stale')
    record = context.get('_media_seasons', {}).get(plan_id)
    if (not isinstance(record, dict) or record.get('run_id') != run_id
            or time.monotonic() - record['created_monotonic'] > 120):
        raise MediaUnavailable('media_season_selection_stale')
    if load_config() != record['config']:
        raise MediaUnavailable('media_season_configuration_changed')
    from .tiramisu import Tiramisu
    transport = Tiramisu()
    transport.validate_binding(record['metadata'])
    cached = None
    if record['config'].get('debrid', {}).get('enabled'):
        from .torbox import TorBoxAPI
        cached = TorBoxAPI()
        cached.validate_binding(record['metadata'])
    client = service.catalogue()
    state = client.season_state(record['imdb'], record['season'])
    if state != record['state']:
        raise MediaUnavailable('media_season_progress_or_sources_changed')
    bindings = []
    for entry in record['entries']:
        discovery._run(context)
        if time.monotonic() - record['created_monotonic'] > 120:
            raise MediaUnavailable('media_season_selection_stale')
        bindings.append(client.select(entry['item_id'], entry['media_source_id'],
                        expected_episode={'imdb': record['imdb'], 'season': record['season'],
                                          'episode': entry['episode'], 'episode_end': entry['episode_end']}))
    discovery._run(context)
    # Provider/file admission can take time. Recheck native watch state and
    # edition choices after all bindings resolve before using the resume value.
    current_state = client.season_state(record['imdb'], record['season'])
    discovery._run(context)
    if current_state != state:
        raise MediaUnavailable('media_season_progress_or_sources_changed')
    if load_config() != record['config'] or service.catalogue() is not client:
        raise MediaUnavailable('media_season_configuration_changed')
    if time.monotonic() - record['created_monotonic'] > 120:
        raise MediaUnavailable('media_season_selection_stale')
    transport.validate_binding(record['metadata'])
    if cached is not None:
        cached.validate_binding(record['metadata'])
    return {'bindings': bindings, 'entries': list(record['entries']),
            'resume_position': next(row['resume_position'] for row in state
                                    if row['episode'] == record['entries'][0]['episode']),
            'mode': record['mode'], 'stop_reason': record['stop_reason']}
