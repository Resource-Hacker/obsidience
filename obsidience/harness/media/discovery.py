"""One-request metadata and source discovery; all candidates are activation-bound."""
from __future__ import annotations

import asyncio
import json
import re
import secrets
import time
import unicodedata
from urllib.parse import quote, urlsplit

import httpx

from .config import MediaUnavailable, load_config

_IMDB = re.compile(r'tt[0-9]{7,10}')
_MAX_BODY = 2 * 1024 * 1024
_MAX_RESULTS = 12
_MAX_CALLS = 8
_RESOLUTION = re.compile(r'(?<![0-9])(2160p|4k|uhd|1080p|720p|480p)(?![0-9])', re.I)
_SEEDERS = re.compile(r'👤\s*([0-9][0-9,]*)')
_SIZE = re.compile(r'💾\s*([0-9]+(?:\.[0-9]+)?)\s*(GB|MB)', re.I)


def _config() -> tuple[dict, dict]:
    try:
        root = load_config()
    except MediaUnavailable:
        raise
    acquisition = root.get('acquisition')
    discovery = root.get('discovery')
    if (not root.get('enabled') or not isinstance(acquisition, dict)
            or not isinstance(discovery, dict)):
        raise MediaUnavailable('media_acquisition_unavailable')
    if acquisition.get('enabled') is not True or discovery.get('enabled') is not True:
        raise MediaUnavailable('media_acquisition_disabled')
    _https_origin(discovery.get('catalogue_url'), 'v3-cinemeta.strem.io')
    provider = discovery.get('provider', 'torrentio')
    if provider not in ('torrentio', 'prowlarr'):
        raise MediaUnavailable('media_discovery_config_invalid')
    _https_origin(discovery.get('torrentio_url'), 'torrentio.strem.fun')
    resolution = discovery.get('max_resolution')
    languages = discovery.get('prefer_languages')
    if (type(resolution) is not int or not 480 <= resolution <= 2160
            or not isinstance(languages, list) or len(languages) > 8
            or any(not isinstance(x, str) or not re.fullmatch(r'[a-z]{2,5}', x) for x in languages)):
        raise MediaUnavailable('media_discovery_config_invalid')
    return acquisition, discovery


def _https_origin(value: object, host: str) -> str:
    if not isinstance(value, str) or len(value) > 256:
        raise MediaUnavailable('media_discovery_config_invalid')
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != 'https' or parsed.hostname != host or parsed.port is not None
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in ('', '/') or parsed.query or parsed.fragment):
            raise ValueError
    except ValueError:
        raise MediaUnavailable('media_discovery_config_invalid') from None
    return f'https://{host}'


def providers() -> dict:
    """Read configuration only; never probes a provider or exposes endpoints."""
    try:
        acquisition, discovery = _config()
    except MediaUnavailable as error:
        return {'enabled': False, 'providers': [], 'readiness': str(error)}
    names = ['cinemeta', discovery.get('provider', 'torrentio')] if discovery.get('enabled') else []
    if acquisition.get('enabled'):
        names.append('torbox' if load_config().get('debrid', {}).get('enabled') else 'tiramisu')
    return {'enabled': bool(names), 'providers': names}


def _run(context: dict) -> str:
    run_id = context.get('run_id')
    if not isinstance(run_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', run_id):
        raise MediaUnavailable('media_activation_unavailable')
    cancel = context.get('_capability_cancel_event')
    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError
    return run_id


def _text(value: object, maximum: int = 180) -> str | None:
    if not isinstance(value, str):
        return None
    value = ' '.join(value.split())[:maximum]
    if (not value or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or any(token in value for token in ('://', '/', '\\', '<', '>'))):
        return None
    return value


async def _json_get_once(url: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=2.0),
                                     follow_redirects=False, trust_env=False,
                                     limits=httpx.Limits(max_connections=1)) as client:
            async with client.stream('GET', url, headers={'Accept': 'application/json',
                                                          'Accept-Encoding': 'identity'}) as response:
                if response.status_code != 200:
                    if response.status_code == 403:
                        raise MediaUnavailable('discovery_provider_forbidden')
                    raise MediaUnavailable('discovery_provider_unavailable')
                if (response.headers.get('content-type', '').split(';')[0].strip()
                        != 'application/json'
                        or response.headers.get('content-encoding', 'identity') != 'identity'):
                    raise MediaUnavailable('discovery_invalid_response')
                length = response.headers.get('content-length')
                if length and (not length.isdigit() or int(length) > _MAX_BODY):
                    raise MediaUnavailable('discovery_response_limit')
                body = bytearray()
                async for chunk in response.aiter_bytes(65536):
                    body.extend(chunk)
                    if len(body) > _MAX_BODY or time.monotonic() > deadline:
                        raise MediaUnavailable('discovery_response_limit')
        value = json.loads(body)
        if not isinstance(value, dict):
            raise MediaUnavailable('discovery_invalid_response')
        return value
    except asyncio.CancelledError:
        raise
    except MediaUnavailable:
        raise
    except (httpx.HTTPError, ValueError, UnicodeError):
        raise MediaUnavailable('discovery_provider_unavailable') from None


async def _json_get(url: str, timeout: float = 6.0, cancel=None) -> dict:
    if cancel is None:
        try:
            async with asyncio.timeout(timeout):
                return await _json_get_once(url, timeout)
        except TimeoutError:
            raise MediaUnavailable('discovery_provider_unavailable') from None
    if cancel.is_set():
        raise asyncio.CancelledError
    request = asyncio.create_task(_json_get_once(url, timeout))
    deadline = time.monotonic() + timeout + 1
    try:
        while not request.done():
            if cancel.is_set():
                request.cancel()
                try:
                    await request
                except asyncio.CancelledError:
                    pass
                raise asyncio.CancelledError
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                request.cancel()
                try:
                    await request
                except asyncio.CancelledError:
                    pass
                raise MediaUnavailable('discovery_provider_unavailable')
            await asyncio.wait((request,), timeout=min(.05, remaining))
        return request.result()
    except asyncio.CancelledError:
        if not request.done():
            request.cancel()
            try:
                await request
            except asyncio.CancelledError:
                pass
        raise


async def search(query: str, content_type: str, context: dict) -> dict:
    """Search names or look up exact IMDb IDs; return sanitized metadata candidates."""
    run_id = _run(context)
    if (not isinstance(query, str) or not 1 <= len(query.strip()) <= 160
            or any(ord(c) < 32 or ord(c) == 127 for c in query)
            or content_type not in ('movie', 'series')):
        raise MediaUnavailable('media_search_arguments_invalid')
    calls = context.setdefault('_media_discovery_calls', 0)
    if type(calls) is not int or calls >= _MAX_CALLS:
        raise MediaUnavailable('media_discovery_call_limit')
    context['_media_discovery_calls'] = calls + 1
    _, config = _config()
    from .tiramisu import Tiramisu
    binding = Tiramisu().binding()
    if load_config().get('debrid', {}).get('enabled'):
        from .torbox import TorBoxAPI
        binding.update(TorBoxAPI().binding())
    cancel = context.get('_capability_cancel_event')
    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError
    origin = _https_origin(config.get('catalogue_url'), 'v3-cinemeta.strem.io')
    imdb_query = query.strip().lower()
    if _IMDB.fullmatch(imdb_query):
        document = await _json_get(f'{origin}/meta/{content_type}/{imdb_query}.json', cancel=cancel)
        meta = document.get('meta')
        if (not isinstance(meta, dict) or meta.get('id') != imdb_query
                or meta.get('type') != content_type):
            raise MediaUnavailable('discovery_metadata_unavailable')
        metas = [meta]
    else:
        url = f'{origin}/catalog/{content_type}/top/search={quote(query.strip(), safe="")}.json'
        document = await _json_get(url, cancel=cancel)
        metas = document.get('metas')
        if not isinstance(metas, list) or len(metas) > 500:
            raise MediaUnavailable('discovery_invalid_response')
    records = context.setdefault('_media_discovery_candidates', {})
    result, truncated = [], False
    for item in metas[:_MAX_RESULTS]:
        if not isinstance(item, dict):
            continue
        imdb = item.get('id')
        title = _text(item.get('name'))
        kind = item.get('type')
        year_raw = item.get('releaseInfo')
        year_match = re.match(r'(?:19|20)\d{2}', year_raw) if isinstance(year_raw, str) else None
        if (not isinstance(imdb, str) or not _IMDB.fullmatch(imdb)
                or kind not in ('movie', 'series') or kind != content_type or title is None):
            continue
        if len(records) >= 32:
            truncated = True
            break
        candidate_id = 'd' + secrets.token_urlsafe(12).rstrip('=')
        while candidate_id in records:
            candidate_id = 'd' + secrets.token_urlsafe(12).rstrip('=')
        record = {'run_id': run_id, 'imdb': imdb, 'type': kind,
                  'title': title, 'year': int(year_match.group()) if year_match else None,
                  **binding, 'provider': config.get('provider', 'torrentio')}
        records[candidate_id] = record
        result.append({'metadata_id': candidate_id, 'imdb_id': imdb,
                       'type': kind, 'title': title, 'year': record['year']})
    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError
    return {'status': 'completed', 'provider': 'cinemeta', 'query': query.strip(),
            'matches': result, **({'truncated': True} if truncated else {}),
            'note': 'Metadata is untrusted. Choose the exact title and year before source discovery. If name search misses a title, search its exact IMDb ID (tt followed by digits).'}


def _release_fields(stream: dict) -> tuple[str, int | None, int | None, int | None, str | None]:
    raw_name = _text(stream.get('name'), 120) or ''
    raw_title = _text(stream.get('title'), 240) or ''
    text = ' '.join((raw_name, raw_title))
    match = _RESOLUTION.search(text)
    resolution = (2160 if match and match.group(1).lower() in ('4k', 'uhd') else
                  int(match.group(1)[:-1]) if match and match.group(1).lower().endswith('p') else None)
    seed_match = _SEEDERS.search(text)
    seeders = int(seed_match.group(1).replace(',', '')) if seed_match else None
    size_match = _SIZE.search(text)
    size = None
    if size_match:
        try:
            size = int(float(size_match.group(1)) * (1024 ** (3 if size_match.group(2).upper() == 'GB' else 2)))
            if size < 0 or size > 10**15:
                size = None
        except (ValueError, OverflowError):
            size = None
    # Supported providers put the release on the first line and mutable swarm
    # statistics below it. Those statistics rank candidates, but must never be
    # part of the selected source's identity or a later read will invalidate it.
    title = stream.get('title')
    lines = title.splitlines() if isinstance(title, str) else []
    release = (_text(lines[0], 240) if lines else None) or raw_name
    return release, resolution, seeders, size, text


def _release_matches_identity(text: str, metadata: dict, *, require_year: bool = False) -> bool:
    """Match the full leading release title, never a sequel's title substring."""
    def tokens(value: str) -> list[str]:
        normalized = unicodedata.normalize('NFKC', value).casefold()
        return re.findall(r'[^\W_]+', normalized, flags=re.UNICODE)

    wanted = tokens(metadata['title'])
    actual = tokens(text)
    if not wanted or actual[:len(wanted)] != wanted:
        return False
    suffix = actual[len(wanted):]
    # A year, episode or resolution starts release metadata. Unknown words may
    # extend the title (Into Darkness, Beyond, etc.); they are not discarded.
    boundary = r'(?:19|20)\d{2}|s\d{1,2}(?:e\d{1,2})?|\d{1,2}x\d{2}|(?:2160|1080|720|480)p|4k|uhd'
    if suffix and not re.fullmatch(boundary, suffix[0]):
        return False
    year = metadata.get('year')
    release_years = {int(value) for value in suffix if re.fullmatch(r'(?:19|20)\d{2}', value)}
    if year is not None and release_years and release_years != {year}:
        return False
    if require_year and (year is None or release_years != {year}):
        return False
    return True


async def candidates(metadata_id: str, *, season: int | None = None,
                     episode: int | None = None, context: dict) -> dict:
    """Rank eligible releases from the configured provider for selected metadata."""
    run_id = _run(context)
    metadata = context.get('_media_discovery_candidates', {}).get(metadata_id)
    if not isinstance(metadata, dict) or metadata.get('run_id') != run_id:
        raise MediaUnavailable('media_metadata_selection_stale')
    if metadata['type'] == 'series':
        if (type(season) is not int or type(episode) is not int
                or not 1 <= season <= 99 or not 1 <= episode <= 99):
            raise MediaUnavailable('media_episode_required')
    elif season is not None or episode is not None:
        raise MediaUnavailable('media_episode_not_applicable')
    calls = context.setdefault('_media_torrentio_calls', set())
    key = (metadata_id, season, episode)
    if key in calls:
        raise MediaUnavailable('media_source_search_already_run')
    if len(calls) >= 8:
        raise MediaUnavailable('media_source_search_limit')
    calls.add(key)
    _, config = _config()
    provider = config.get('provider', 'torrentio')
    from .tiramisu import Tiramisu
    transport = Tiramisu()
    transport.validate_binding(metadata)
    cached_provider = None
    if metadata.get('debrid_binding') or load_config().get('debrid', {}).get('enabled'):
        from .torbox import TorBoxAPI
        cached_provider = TorBoxAPI()
        cached_provider.validate_binding(metadata)
    origin = _https_origin(config.get('torrentio_url'), 'torrentio.strem.fun')
    episode_title = None
    first_air_date = None
    season_episodes = None
    series_episodes = None
    if metadata['type'] == 'series':
        detail_origin = _https_origin(config.get('catalogue_url'), 'v3-cinemeta.strem.io')
        details = await _json_get(f'{detail_origin}/meta/series/{metadata["imdb"]}.json',
                                  cancel=context.get('_capability_cancel_event'))
        meta = details.get('meta')
        videos = meta.get('videos') if isinstance(meta, dict) else None
        if (not isinstance(meta, dict) or meta.get('id') != metadata['imdb']
                or meta.get('type') != 'series' or not isinstance(videos, list)
                or len(videos) > 10000):
            raise MediaUnavailable('discovery_episode_unavailable')
        exact = [video for video in videos if isinstance(video, dict)
                 and video.get('season') == season and video.get('episode') == episode
                 and video.get('id') == f'{metadata["imdb"]}:{season}:{episode}']
        if len(exact) != 1:
            raise MediaUnavailable('discovery_episode_unavailable')
        from .season import episode_roster
        season_episodes = episode_roster(details, metadata['imdb'], season)
        series_episodes = list(season_episodes)
        # Validate every included season before a native series-pack tag can
        # expose it. An invalid unrelated season need not hide a valid source;
        # its missing roster ensures a pack containing it is refused.
        if cached_provider is not None:
            other_seasons = {video['season'] for video in videos if isinstance(video, dict)
                             and type(video.get('season')) is int
                             and 1 <= video['season'] <= 99 and video['season'] != season}
            for number in sorted(other_seasons):
                try:
                    series_episodes.extend(episode_roster(details, metadata['imdb'], number))
                except MediaUnavailable:
                    continue
            series_episodes.sort(key=lambda row: (row['season'], row['episode']))
        released = exact[0].get('released')
        if (not isinstance(released, str)
                or not re.fullmatch(r'(?:19|20)\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z', released)):
            raise MediaUnavailable('discovery_episode_unavailable')
        first_air_date = released
        episode_title = _text(exact[0].get('title')) or f'Season {season} Episode {episode}'
    if provider == 'torrentio':
        if metadata['type'] == 'movie':
            path = f'/stream/movie/{metadata["imdb"]}.json'
        else:
            path = f'/stream/series/{metadata["imdb"]}:{season}:{episode}.json'
        document = await _json_get(origin + path,
                                   cancel=context.get('_capability_cancel_event'))
        streams = document.get('streams')
        if not isinstance(streams, list) or len(streams) > 500:
            raise MediaUnavailable('discovery_invalid_response')
    else:
        streams = await transport.search(metadata, season=season, episode=episode,
                                          cancel=context.get('_capability_cancel_event'))
    _, config = _config()
    maximum = config['max_resolution']
    languages = config['prefer_languages']
    chosen: dict[str, dict] = context.setdefault('_media_acquisition_candidates', {})
    scored = []
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        info_hash = stream.get('infoHash')
        if (not isinstance(info_hash, str)
                or not re.fullmatch(r'(?:[a-fA-F0-9]{40}|[A-Za-z2-7]{32})', info_hash)):
            continue
        release, resolution, seeders, size, text = _release_fields(stream)
        if not release or resolution is not None and resolution > maximum:
            continue
        if not _release_matches_identity(release, metadata,
                                         require_year=provider == 'prowlarr' and metadata['type'] == 'movie'):
            continue
        lower = text.lower()
        aliases = {'en': ('en', 'eng', 'english'), 'es': ('es', 'spa', 'spanish'),
                   'fr': ('fr', 'fre', 'fra', 'french')}
        language_match = any(re.search(rf'(?<![a-z]){re.escape(alias)}(?![a-z])', lower)
                             for code in languages for alias in aliases.get(code, (code,)))
        if metadata['type'] == 'series':
            episode_patterns = (rf'(?<![a-z0-9])s{season:02d}\s*e{episode:02d}(?![0-9])',
                                rf'(?<![a-z0-9]){season}\s*x\s*{episode:02d}(?![0-9])')
            # A season release may contain the exact requested episode. Only the
            # cache file plan can establish that; release labels alone cannot.
            season_pack = cached_provider is not None and re.search(
                rf'(?<![a-z0-9])s0*{season}(?=e[0-9]|[^a-z0-9]|$)', lower, re.I)
            if not season_pack and not any(re.search(pattern, lower, re.I) for pattern in episode_patterns):
                continue
        hdr = bool(re.search(r'(?<![a-z])(?:hdr10\+?|dolby[ ._-]?vision|dv)(?![a-z])', lower))
        remux = 'remux' in lower
        quality = (resolution or 0, int(hdr), int(remux))
        rank = (int(language_match), *quality, seeders if seeders is not None else -1,
                size if size is not None else -1)
        scored.append((rank, stream, info_hash, release, resolution, seeders, size,
                       language_match, hdr, remux))
    if not scored:
        return {'status': 'completed', 'provider': provider, 'title': metadata['title'],
                'type': metadata['type'], 'season': season, 'episode': episode,
                'candidates': [], 'message': 'No eligible sources returned for this exact title and episode.'}
    scored.sort(key=lambda x: (x[0], x[3].casefold(), x[2].lower()), reverse=True)
    best_rank = scored[0][0]
    tied = sum(row[0] == best_rank for row in scored) > 1
    top = scored[0]
    adequate_quality = top[4] is not None and top[5] is not None and top[5] > 0
    credible_identity = provider == 'torrentio' or _release_matches_identity(top[3], metadata, require_year=True)
    recommend = not tied and adequate_quality and credible_identity
    output = []
    pending = {}
    for rank, stream, info_hash, release, resolution, seeders, size, language, hdr, remux in scored[:32 if cached_provider else 8]:
        candidate_id = 'a' + secrets.token_urlsafe(14).rstrip('=')
        while candidate_id in chosen or candidate_id in pending:
            candidate_id = 'a' + secrets.token_urlsafe(14).rstrip('=')
        private = {'run_id': run_id, 'metadata_id': metadata_id, 'hash': info_hash.lower(),
                   'release_title': release, 'title': metadata['title'], 'type': metadata['type'],
                   'imdb': metadata['imdb'], 'year': metadata['year'], 'first_air_date': first_air_date,
                   'episode_title': episode_title, 'season': season, 'episode': episode,
                   'season_episodes': season_episodes, 'series_episodes': series_episodes,
                   'resolution': resolution, 'seeders': seeders, 'size': size,
                   'language_match': language, 'hdr': hdr, 'remux': remux,
                   'quality_score': max(0, rank[1] * 100 + rank[2] * 20 + rank[3] * 10)}
        private.update(transport.binding())
        private['provider'] = provider
        pending[candidate_id] = private
        output.append({'candidate_id': candidate_id, 'title': metadata['title'],
                       'resolution': resolution,
                       'seeders': seeders, 'size_bytes': size,
                       'preferred_language_match': language, 'hdr': hdr, 'remux': remux,
                       'recommended': False})
    if cached_provider and output:
        matches = await cached_provider.cache_matches(
            [pending[row['candidate_id']] for row in output], context.get('_capability_cancel_event'))
        from .tiramisu import _normal_hash
        cached_output = []
        for row in output:
            private = pending[row['candidate_id']]
            match = matches.get(_normal_hash(private['hash']))
            if match:
                private.update(match)
                row['cached'] = True
                row['cache_provider'] = 'torbox'
                plan = private['debrid_plan']
                from .torbox import _plan_scope
                row.update(_plan_scope(plan))
                row['episode_plan'] = [{key: file[key] for key in ('season', 'episode', 'episode_end')}
                                       for file in plan] if private['type'] == 'series' else []
                if private['type'] == 'series':
                    selected = next(file for file in plan if file['path'] == private['debrid_file']['path'])
                    row.update({key: selected[key] for key in ('season', 'episode', 'episode_end')})
                    row['pack_episodes'] = sum(file['episode_end'] - file['episode'] + 1 for file in plan)
                # Pack byte size describes the release, not the selected physical file.
                row['selected_size_bytes'] = private['debrid_file']['size']
                cached_output.append(row)
            else:
                del pending[row['candidate_id']]
        # Prefer the narrowest eligible registration scope, then retain the
        # provider quality ordering within that scope. Wider choices stay visible.
        scope_order = {'single_file': 0, 'season_pack': 1, 'series_pack': 2}
        cached_output.sort(key=lambda row: scope_order[row['acquisition_scope']])
        output = cached_output[:8]
        # Recommendations cover only this bounded set of currently cached plans.
        recommend = bool(output) and output[0]['resolution'] is not None
        tied = (len(output) > 1
                and output[0]['acquisition_scope'] == output[1]['acquisition_scope']
                and all(output[0][key] == output[1][key]
                for key in ('resolution', 'preferred_language_match', 'hdr', 'remux', 'size_bytes')))
        recommend = recommend and not tied
    if len(chosen) + len(output) > 32:
        raise MediaUnavailable('media_acquisition_candidate_limit')
    chosen.update({row['candidate_id']: pending[row['candidate_id']] for row in output})
    if output:
        output[0]['recommended'] = recommend
    return {'status': 'completed', 'provider': provider, 'title': metadata['title'],
            'type': metadata['type'], 'season': season, 'episode': episode,
            'candidates': output, 'ambiguous_best_tie': tied or (not adequate_quality and not cached_provider),
            'cache_provider': 'torbox' if cached_provider else None,
            'note': ('TorBox returns only cached exact file plans; season and series packs register every verified included file. Scope, included seasons and episode counts are explicit; playback remains a separate selection. The selected file may explicitly contain a contiguous episode range. Cache is rechecked before new registration. ' if cached_provider else '') + 'Recommendation prefers the narrowest eligible registration scope, then preferred language, resolution, HDR/remux, seeders and size within the bounded returned results. Release labels and availability are unverified; downloaded content has not been inspected. Choose one candidate_id to register exactly once; discovery has not acquired media.'}
