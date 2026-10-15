"""Explicit cached-only TorBox acquisition; no scheduler, database or byte proxy.

Contract: https://api.torbox.app/openapi.json (2026-10-14), torrents
checkcached/mylist/createtorrent. Official Postman documents seed=3 as no seeding.
The acquisition owner retains activation/receipt ownership and refreshes Jellyfin.
"""
from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timezone
import hashlib
import json
from pathlib import PurePosixPath
import re
import unicodedata
from typing import TypedDict

import httpx

from .config import MediaUnavailable, load_config
from .jellyfin import _token
from .tiramisu import _normal_hash

_API = 'https://api.torbox.app/v1/api'
_BODY_LIMIT = 2 * 1024 * 1024
_VIDEO = {'.mkv', '.mp4', '.m4v', '.webm'}
_CONTAINERS = _VIDEO | {'.avi', '.mov', '.ts', '.m2ts', '.mpg', '.mpeg', '.wmv', '.vob', '.iso',
                         '.flv', '.divx', '.ogm', '.ogv', '.3gp', '.mts', '.strm'}
_SIDECARS = {'.srt', '.sub', '.idx', '.ass', '.ssa', '.vtt', '.nfo', '.txt',
             '.jpg', '.jpeg', '.png', '.webp', '.xml', '.sfv', '.md', '.torrent'}


class TorBoxFile(TypedDict):
    file_id: int
    path: str
    size: int


class BoundFile(TorBoxFile):
    hash: str


class TorBoxTorrent(TypedDict):
    torrent_id: int
    hash: str
    name: str
    download_present: bool
    download_finished: bool
    files: list[TorBoxFile]


def _debrid(config: dict) -> dict:
    value = config.get('debrid')
    if (config.get('enabled') is not True or not isinstance(value, dict)
            or set(value) != {'enabled', 'provider', 'credential', 'instance_id', 'mount_path'}
            or value.get('enabled') is not True or value.get('provider') != 'torbox'
            or value.get('credential') != 'obsidience-media-torbox'
            or not isinstance(value.get('instance_id'), str)
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value['instance_id'])
            or not isinstance(value.get('mount_path'), str)
            or not value['mount_path'].startswith('/') or len(value['mount_path']) > 4096
            or '\\' in value['mount_path']
            or any(ord(c) < 32 or ord(c) == 127 for c in value['mount_path'])
            or any(p in ('', '.', '..') for p in value['mount_path'].split('/')[1:])):
        raise MediaUnavailable('torbox_config_unavailable')
    return dict(value)


def _fingerprint(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _identifier(value: object) -> int:
    if type(value) is not int or not 0 <= value <= 2**63 - 1:
        raise MediaUnavailable('torbox_invalid_response')
    return value


def _files(rows: object) -> list[TorBoxFile]:
    if not isinstance(rows, list) or len(rows) > 1024:
        raise MediaUnavailable('torbox_invalid_files')
    result: list[TorBoxFile] = []
    ids: set[int] = set()
    paths: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise MediaUnavailable('torbox_invalid_files')
        path, size = row.get('name'), row.get('size')
        identifier = _identifier(row.get('id'))
        if (not isinstance(path, str) or not 1 <= len(path) <= 4096
                or path.startswith('/') or '\\' in path or ':' in path
                or any(ord(c) < 32 or ord(c) == 127 for c in path)
                or any(p in ('', '.', '..') for p in path.split('/'))
                or type(size) is not int or not 0 <= size <= 2**50
                or row.get('zipped') is True or row.get('infected') is True
                or identifier in ids or path in paths):
            raise MediaUnavailable('torbox_invalid_files')
        ids.add(identifier)
        paths.add(path)
        result.append({'file_id': identifier, 'path': path, 'size': size})
    return result


def _words(value: str) -> str:
    return re.sub(r'[\W_]+', ' ', unicodedata.normalize('NFKC', value).casefold()).strip()


def _episode_span(path: str, candidate: dict) -> tuple[int, int, int] | None:
    """Only explicit contiguous filename episode identities; never infer a pilot split."""
    stem = PurePosixPath(path).stem
    marker = re.search(r'(?<![a-z0-9])s([0-9]{1,3})e([0-9]{1,3})'
                       r'((?:-?e[0-9]{1,3})+|-[0-9]{1,3})?(?![a-z0-9])', stem, re.I)
    if not marker:
        return None
    prefixes = {_words(candidate['title'])}
    year = candidate.get('year')
    if type(year) is int and 1880 <= year <= 2200:
        prefixes.add(_words(candidate['title']) + ' ' + str(year))
    suffix = stem[marker.end():]
    if (_words(stem[:marker.start()]) not in prefixes
            or re.match(r'[-_ ]+[0-9]{1,3}(?![a-z0-9])', suffix, re.I)
            or re.search(r'(?<![a-z0-9])(?:e[0-9]+|s[0-9]+e[0-9]+)', suffix, re.I)
            or re.search(r'(?<![a-z0-9])(?:sample|trailer|extras?|featurette)(?![a-z0-9])', suffix, re.I)):
        return None
    first = int(marker[2])
    extension = marker[3] or ''
    numbers = [int(value) for value in re.findall(r'[0-9]+', extension)]
    last = numbers[-1] if numbers else first
    is_range = re.fullmatch(r'-e?[0-9]+', extension, re.I) is not None
    if (first < 1 or not first <= last <= first + 7
            or numbers and (last <= first or not is_range
                            and numbers != list(range(first + 1, last + 1)))):
        return None
    return int(marker[1]), first, last


def _selection_plan(candidate: dict, files: list[TorBoxFile]) -> list[dict] | None:
    """Every exposed video must be identified before tagging a whole native torrent."""
    title = candidate.get('title')
    if not isinstance(title, str) or not 1 <= len(title) <= 180:
        raise MediaUnavailable('torbox_candidate_invalid')
    videos = [file for file in files if PurePosixPath(file['path']).suffix.lower() in _CONTAINERS]
    if not videos or any(file['size'] <= 0 or PurePosixPath(file['path']).suffix.lower()
                         not in _VIDEO for file in videos):
        return None
    if candidate.get('type') == 'movie':
        year = candidate.get('year')
        if type(year) is not int or not 1880 <= year <= 2200:
            raise MediaUnavailable('torbox_movie_year_required')
        expected = _words(title) + ' ' + str(year)
        words = _words(PurePosixPath(videos[0]['path']).stem)
        return [dict(videos[0])] if len(videos) == 1 and (
            words == expected or words.startswith(expected + ' ')) else None
    if candidate.get('type') != 'series':
        raise MediaUnavailable('torbox_candidate_invalid')
    season, episode = candidate.get('season'), candidate.get('episode')
    if (type(season) is not int or not 0 <= season <= 999
            or type(episode) is not int or not 1 <= episode <= 999):
        raise MediaUnavailable('torbox_episode_identity_required')
    # Native tags expose the whole directory. Unknown/archived/redirect media
    # cannot bypass the complete video plan merely through an unlisted suffix.
    if any(PurePosixPath(file['path']).suffix.lower() not in _VIDEO | _SIDECARS for file in files):
        return None
    roster = candidate.get('series_episodes', candidate.get('season_episodes'))
    known = ({(row['season'], row['episode']) for row in roster
              if datetime.fromisoformat(row['released'].replace('Z', '+00:00'))
              <= datetime.now(timezone.utc)} if isinstance(roster, list) else None)
    plan, seen = [], {}
    for file in videos:
        span = _episode_span(file['path'], candidate)
        if span is None or not 1 <= span[0] <= 99:
            return None
        episodes = set(range(span[1], span[2] + 1))
        occupied = seen.setdefault(span[0], set())
        if (occupied & episodes or known is not None
                and not {(span[0], number) for number in episodes} <= known):
            return None
        occupied.update(episodes)
        plan.append({**file, 'season': span[0], 'episode': span[1], 'episode_end': span[2]})
    # A hole inside a pack can hide an implicitly combined episode (for example
    # E01 followed by E03). Never relabel that first file or guess the missing span.
    if (episode not in seen.get(season, set())
            or any(numbers != set(range(min(numbers), max(numbers) + 1))
                   for numbers in seen.values())):
        return None
    return sorted(plan, key=lambda row: (row['season'], row['episode'], row['path']))


def _select(candidate: dict, files: list[TorBoxFile]) -> TorBoxFile | None:
    plan = _selection_plan(candidate, files)
    if not plan:
        return None
    matching = [row for row in plan if candidate['type'] == 'movie'
                or row['season'] == candidate['season']
                and row['episode'] <= candidate['episode'] <= row['episode_end']]
    return ({key: matching[0][key] for key in ('file_id', 'path', 'size')}
            if len(matching) == 1 else None)


def _plan_scope(plan: list[dict]) -> dict:
    seasons = sorted({file['season'] for file in plan if 'season' in file})
    return {'acquisition_scope': ('series_pack' if len(seasons) > 1 else
                                  'season_pack' if len(plan) > 1 else 'single_file'),
            'season_numbers': seasons, 'registered_files': len(plan),
            'pack_episodes': sum(file['episode_end'] - file['episode'] + 1
                                 for file in plan if 'episode' in file)}


def _plan_paths(plan: list[dict]) -> list[dict]:
    # Cache IDs and account IDs have different namespaces. Paths, sizes and the
    # full episode plan must remain identical across that one explicit rebinding.
    return [{key: value for key, value in row.items() if key != 'file_id'} for row in plan]


def _invalid_constant(_value: str):
    raise ValueError('invalid_json_constant')


def _registration_name(candidate: dict) -> str:
    name = re.sub(r'[^\w .()\[\]-]', '', unicodedata.normalize('NFKC', candidate['title']))
    name = ' '.join(name.split()).strip(' .')[:160]
    if not name:
        raise MediaUnavailable('torbox_candidate_invalid')
    year = candidate.get('year')
    name += f' ({year})' if type(year) is int and 1880 <= year <= 2200 else ''
    name += f' [imdbid-{candidate["imdb"]}]'
    return name


class TorBoxAPI:
    """Fixed-origin requests; credentials load only for an actual provider call."""

    def __init__(self, config: dict | None = None):
        self.config = _debrid(load_config() if config is None else config)
        self.fingerprint = _fingerprint(self.config)

    def binding(self) -> dict:
        return {'debrid_binding': {'provider': 'torbox', 'instance_id': self.config['instance_id'],
                                   'config_fingerprint': self.fingerprint}}

    def validate_binding(self, candidate: dict) -> None:
        current = _debrid(load_config())
        if (_fingerprint(current) != self.fingerprint
                or candidate.get('debrid_binding') != self.binding()['debrid_binding']):
            raise MediaUnavailable('torbox_candidate_binding_changed')

    async def _request_once(self, method: str, endpoint: str, *, params=None, form=None, payload=None) -> object:
        headers = {'Authorization': 'Bearer ' + _token(self.config['credential']),
                   'Accept': 'application/json', 'Accept-Encoding': 'identity'}
        # Explicit multipart matches createtorrent's published requestBody schema.
        multipart = {key: (None, str(value)) for key, value in form.items()} if form else None
        async with httpx.AsyncClient(timeout=httpx.Timeout(8, connect=3), trust_env=False,
                                     follow_redirects=False,
                                     transport=httpx.AsyncHTTPTransport(retries=0),
                                     limits=httpx.Limits(max_connections=1)) as client:
            async with client.stream(method, _API + endpoint, params=params, files=multipart, json=payload,
                                     headers=headers) as response:
                if (not 200 <= response.status_code < 300
                        or response.headers.get('content-type', '').split(';')[0].strip() != 'application/json'
                        or response.headers.get('content-encoding', 'identity') != 'identity'):
                    raise MediaUnavailable('torbox_request_unavailable')
                length = response.headers.get('content-length')
                if length and (not length.isdigit() or int(length) > _BODY_LIMIT):
                    raise MediaUnavailable('torbox_response_limit')
                body = bytearray()
                async for chunk in response.aiter_raw():
                    body.extend(chunk)
                    if len(body) > _BODY_LIMIT:
                        raise MediaUnavailable('torbox_response_limit')
        value = json.loads(body, parse_constant=_invalid_constant)
        if not isinstance(value, dict) or value.get('success') is not True:
            raise MediaUnavailable('torbox_request_unavailable')
        return value.get('data')

    async def _request(self, method: str, endpoint: str, *, params=None, form=None, payload=None,
                       cancel=None, timeout: float = 12) -> object:
        if cancel is not None and cancel.is_set():
            raise asyncio.CancelledError
        task = asyncio.create_task(self._request_once(method, endpoint, params=params, form=form, payload=payload))
        try:
            async with asyncio.timeout(timeout):
                while not task.done():
                    if cancel is not None and cancel.is_set():
                        raise asyncio.CancelledError
                    await asyncio.wait((task,), timeout=.05)
                return task.result()
        except (TimeoutError, httpx.HTTPError, ValueError, UnicodeError, OSError):
            raise MediaUnavailable('torbox_request_uncertain') from None
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await task

    async def account(self, cancel=None) -> dict:
        data = await self._request('GET', '/user/me', params={'settings': 'false'}, cancel=cancel)
        if not isinstance(data, dict):
            raise MediaUnavailable('torbox_invalid_response')
        plan, expires = data.get('plan'), data.get('premium_expires_at')
        expiry = None
        if isinstance(expires, str) and len(expires) <= 64:
            with suppress(ValueError):
                parsed = datetime.fromisoformat(expires.replace('Z', '+00:00'))
                if parsed.tzinfo is not None:
                    expiry = parsed
        paid = (type(plan) is int and plan in (1, 2, 3) and expiry is not None
                and expiry > datetime.now(timezone.utc))
        return {'provider': 'torbox', 'connected': True, 'paid_active': paid,
                'plan': {0: 'free', 1: 'essential', 2: 'pro', 3: 'standard'}.get(
                    plan if type(plan) is int else None, 'unknown')}

    async def check_cached(self, hashes: list[str], cancel=None) -> dict[str, list[TorBoxFile]]:
        if (not isinstance(hashes, list) or not 1 <= len(hashes) <= 32
                or any(not _normal_hash(value) for value in hashes)):
            raise MediaUnavailable('torbox_hash_limit_or_invalid')
        normalized = list(dict.fromkeys(_normal_hash(value) for value in hashes))
        params = [('hash', value) for value in normalized] + [('format', 'object'), ('list_files', 'true')]
        data = await self._request('GET', '/torrents/checkcached', params=params, cancel=cancel)
        if not isinstance(data, dict) or len(data) > 32:
            raise MediaUnavailable('torbox_invalid_response')
        result = {}
        for key, row in data.items():
            info_hash = _normal_hash(key)
            if (info_hash not in normalized or not isinstance(row, dict)
                    or _normal_hash(row.get('hash')) != info_hash):
                raise MediaUnavailable('torbox_invalid_cache_identity')
            result[info_hash] = _files(row.get('files'))
        return result

    async def cache_matches(self, candidates: list[dict], cancel=None) -> dict[str, dict]:
        """Read-only discovery projection: merge a result into its private candidate."""
        if not isinstance(candidates, list) or not 1 <= len(candidates) <= 32:
            raise MediaUnavailable('torbox_candidate_limit')
        if any(not isinstance(candidate, dict) for candidate in candidates):
            raise MediaUnavailable('torbox_candidate_invalid')
        cached = await self.check_cached([candidate.get('hash') for candidate in candidates], cancel)
        result = {}
        for candidate in candidates:
            info_hash = _normal_hash(candidate.get('hash'))
            file = _select(candidate, cached.get(info_hash, []))
            if file is not None:
                result[info_hash] = {**self.binding(), 'debrid_file': {'hash': info_hash, **file},
                                     'debrid_plan': _selection_plan(candidate, cached[info_hash])}
        return result

    async def mylist(self, *, limit: int = 128, torrent_id: int | None = None,
                     cancel=None) -> list[TorBoxTorrent]:
        if type(limit) is not int or not 1 <= limit <= 128:
            raise MediaUnavailable('torbox_inventory_limit')
        params = {'limit': str(limit), 'offset': '0', 'bypass_cache': 'true'}
        if torrent_id is not None:
            params['id'] = str(_identifier(torrent_id))
        data = await self._request('GET', '/torrents/mylist', params=params, cancel=cancel)
        if torrent_id is not None and isinstance(data, dict):
            data = [data]
        if not isinstance(data, list) or len(data) > limit:
            raise MediaUnavailable('torbox_invalid_inventory')
        if torrent_id is None and len(data) == limit:
            # A truncated inventory cannot establish absence before a mutation.
            raise MediaUnavailable('torbox_inventory_limit')
        result: list[TorBoxTorrent] = []
        for row in data:
            if not isinstance(row, dict) or not _normal_hash(row.get('hash')):
                raise MediaUnavailable('torbox_invalid_inventory')
            identifier = _identifier(row.get('id'))
            name = row.get('name')
            if (not isinstance(name, str) or not 1 <= len(name) <= 512
                    or torrent_id is not None and identifier != torrent_id):
                raise MediaUnavailable('torbox_invalid_inventory')
            tags = row.get('tags') or []
            if (not isinstance(tags, list) or len(tags) > 32
                    or any(not isinstance(tag, str) or not 1 <= len(tag) <= 128 for tag in tags)):
                raise MediaUnavailable('torbox_invalid_tags')
            result.append({'torrent_id': identifier, 'hash': _normal_hash(row['hash']), 'name': name,
                           'tags': tags,
                           'download_present': row.get('download_present') is True,
                           'download_finished': row.get('download_finished') is True,
                           'files': _files(row.get('files'))})
        return result

    async def _list_exact(self, candidate: dict, cancel=None,
                          torrent_id: int | None = None) -> tuple[TorBoxTorrent, TorBoxFile] | None:
        bound = candidate['debrid_file']
        rows = await self.mylist(torrent_id=torrent_id, cancel=cancel)
        matching_hash = [row for row in rows if row['hash'] == _normal_hash(candidate['hash'])]
        if len(matching_hash) > 1:
            raise MediaUnavailable('torbox_ambiguous_inventory')
        if not matching_hash:
            return None
        row = matching_hash[0]
        if not row['download_present'] or not row['download_finished']:
            raise MediaUnavailable('torbox_existing_not_ready')
        selected = _select(candidate, row['files'])
        plan = _selection_plan(candidate, row['files'])
        expected_plan = candidate.get('debrid_plan')
        if (selected is None or selected['path'] != bound['path'] or selected['size'] != bound['size']
                or not isinstance(expected_plan, list) or not plan
                or _plan_paths(plan) != _plan_paths(expected_plan)):
            raise MediaUnavailable('torbox_file_identity_changed')
        # Account file IDs may differ from checkcached; the live ID is admitted here.
        return row, selected

    def _result(self, candidate: dict, match: tuple[TorBoxTorrent, TorBoxFile], *,
                effect: bool | None, existing: bool, reconciled: bool = False) -> dict:
        torrent, file = match
        candidate['_context']['_media_registered_file'] = {
            'hash': torrent['hash'], 'torrent_id': torrent['torrent_id'],
            'name': torrent['name'], 'tags': torrent['tags'], **file,
            'plan': _selection_plan(candidate, torrent['files'])}
        return {'status': 'completed', 'delivery': 'verified', 'effect_applied': effect,
                'provider': 'torbox', 'type': 'movie' if candidate['type'] == 'movie' else 'tv',
                'title': candidate['title'], **_plan_scope(candidate['debrid_plan']),
                'season': candidate.get('season'), 'episode': candidate.get('episode'),
                'episode_plan': [{key: value for key, value in file.items()
                                  if key in ('season', 'episode', 'episode_end')}
                                 for file in candidate['debrid_plan']],
                'already_present': existing,
                'reconciled': reconciled, 'must_not_replay': True}

    async def organize(self, registered: dict, candidate: dict, cancel=None) -> dict:
        """Tag only this exact registered torrent for the matching native library."""
        tag = 'obsidience movies' if candidate['type'] == 'movie' else 'obsidience tv'
        name = _registration_name(candidate)
        rows = await self.mylist(torrent_id=registered['torrent_id'], cancel=cancel)
        if len(rows) != 1 or rows[0]['hash'] != registered['hash']:
            raise MediaUnavailable('torbox_registration_changed')
        selected = _select(candidate, rows[0]['files'])
        plan = _selection_plan(candidate, rows[0]['files'])
        if (not selected or any(selected[key] != registered[key] for key in ('file_id', 'path', 'size'))
                or not plan or plan != registered.get('plan')):
            raise MediaUnavailable('torbox_file_identity_changed')
        tags = rows[0]['tags']
        other = 'obsidience tv' if tag == 'obsidience movies' else 'obsidience movies'
        if other in tags:
            raise MediaUnavailable('torbox_conflicting_library_tag')
        if tag not in tags or rows[0]['name'] != name:
            try:
                await self._request('PUT', '/torrents/edittorrent',
                    payload={'torrent_id': registered['torrent_id'], 'name': name,
                             'tags': tags if tag in tags else tags + [tag]}, cancel=cancel)
            except MediaUnavailable:
                pass  # An uncertain metadata write is reconciled, never resent.
            for attempt in range(11):
                rows = await self.mylist(torrent_id=registered['torrent_id'], cancel=cancel)
                if (len(rows) == 1 and rows[0]['hash'] == registered['hash']
                        and tag in rows[0]['tags'] and other not in rows[0]['tags']
                        and rows[0]['name'] == name
                        and rows[0]['download_present'] and rows[0]['download_finished']
                        and _selection_plan(candidate, rows[0]['files']) == plan):
                    break
                if attempt == 10:
                    raise MediaUnavailable('torbox_library_tag_unverified')
                await asyncio.sleep(.5)
        return {**registered, 'name': name, 'tag': tag}

    async def register(self, candidate: dict, cancel=None) -> dict:
        """One cached-only POST; one read-only reconciliation; no write retries."""
        self.validate_binding(candidate)
        context = candidate.get('_context')
        bound = candidate.get('debrid_file')
        if (not isinstance(context, dict) or not isinstance(bound, dict)
                or set(bound) != {'hash', 'file_id', 'path', 'size'}
                or not _normal_hash(candidate.get('hash'))
                or bound.get('hash') != _normal_hash(candidate['hash'])
                or not isinstance(candidate.get('debrid_plan'), list)
                or not candidate['debrid_plan']
                or candidate.get('type') == 'series' and not isinstance(candidate.get('series_episodes'), list)):
            raise MediaUnavailable('torbox_candidate_binding_invalid')
        # This marker is present before any dispatch and owns all post-write outcomes.
        context['_media_acquisition_outcome'] = {
            'status': 'interrupted', 'delivery': 'not_dispatched',
            'effect_applied': False, 'must_not_replay': True}
        if not (await self.account(cancel))['paid_active']:
            raise MediaUnavailable('torbox_paid_account_required')
        # Reconcile account registration before any new POST or cache-expiry failure.
        existing = await self._list_exact(candidate, cancel)
        if existing:
            result = self._result(candidate, existing, effect=False, existing=True)
            context['_media_acquisition_outcome'] = result
            return result
        cached = await self.cache_matches([candidate], cancel)
        fresh = cached.get(_normal_hash(candidate['hash']), {})
        if fresh.get('debrid_file') != bound or fresh.get('debrid_plan') != candidate.get('debrid_plan'):
            raise MediaUnavailable('torbox_cached_file_changed')
        imdb = candidate.get('imdb')
        if not isinstance(imdb, str) or not re.fullmatch(r'tt[0-9]{7,10}', imdb):
            raise MediaUnavailable('torbox_candidate_invalid')
        name = _registration_name(candidate)
        form = {'magnet': 'magnet:?xt=urn:btih:' + _normal_hash(candidate['hash']),
                'seed': '3', 'allow_zip': 'false', 'as_queued': 'false',
                'add_only_if_cached': 'true', 'name': name}
        torrent_id = None
        dispatched = False
        try:
            self.validate_binding(candidate)
            if cancel is not None and cancel.is_set():
                raise asyncio.CancelledError
            dispatched = True
            context['_media_acquisition_outcome'] = {
                'status': 'uncertain', 'delivery': 'uncertain',
                'effect_applied': None, 'must_not_replay': True}
            data = await self._request('POST', '/torrents/createtorrent', form=form,
                                       cancel=cancel, timeout=35)
            if not isinstance(data, dict) or _normal_hash(data.get('hash')) != _normal_hash(candidate['hash']):
                raise MediaUnavailable('torbox_registration_uncertain')
            torrent_id = _identifier(data.get('torrent_id'))
        except asyncio.CancelledError:
            context['_media_acquisition_outcome'] = {
                'status': 'interrupted', 'delivery': 'uncertain' if dispatched else 'not_dispatched',
                'effect_applied': None if dispatched else False, 'must_not_replay': True}
            raise
        except Exception:
            if not dispatched:
                raise
        # A successful POST also needs live file confirmation; there is exactly one GET.
        try:
            match = await self._list_exact(candidate, cancel, torrent_id)
            if match:
                result = self._result(candidate, match, effect=True if torrent_id is not None else None,
                                      existing=torrent_id is None, reconciled=torrent_id is None)
                context['_media_acquisition_outcome'] = result
                return result
        except asyncio.CancelledError:
            context['_media_acquisition_outcome'] = {
                'status': 'interrupted', 'delivery': 'uncertain',
                'effect_applied': None, 'must_not_replay': True}
            raise
        except Exception:
            pass
        result = {'status': 'uncertain', 'delivery': 'uncertain', 'effect_applied': None,
                  'provider': 'torbox', 'title': candidate['title'], 'must_not_replay': True,
                  'message': 'Registration could not be reconciled. Do not repeat this request.'}
        context['_media_acquisition_outcome'] = result
        return result
