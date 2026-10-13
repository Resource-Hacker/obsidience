"""Owner-local Tiramisu API transport over a single Unix-domain socket."""
from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import os
import re
import stat
import time
from contextlib import suppress
from pathlib import PurePosixPath
from urllib.parse import urlencode

import httpx

from .config import MediaUnavailable, load_config

_MAX_REPLY = 4 * 1024 * 1024
_INSTANCE = re.compile(r'[A-Za-z0-9_-]{1,128}')
_HEX_HASH = re.compile(r'[a-f0-9]{40}')


def _fingerprint(acquisition: dict, discovery: object) -> str:
    material = json.dumps({'acquisition': acquisition, 'discovery': discovery},
                          sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
    return hashlib.sha256(material).hexdigest()


def _show_folder_name(candidate: dict) -> str:
    show = re.sub(r'[<>:"/\\|?*\'"&]', '', candidate['title'])
    show = re.sub(r'\s+', '_', show)
    show = re.sub(r'_+', '_', show).strip('_').lstrip('.') or 'untitled'
    air_date = candidate.get('first_air_date')
    return f'{show} ({air_date[:4]})' if isinstance(air_date, str) and len(air_date) >= 4 else show


def _show_folder_names(candidate: dict) -> set[str]:
    current = _show_folder_name(candidate)
    base = re.sub(r' \((?:19|20)\d{2}\)$', '', current)
    return {current, base}


def _episode_path_identity(path: object, candidate: dict, *, require_hash: bool = True) -> tuple[int, int] | None:
    if not isinstance(path, str) or len(path) > 4096 or '\\' in path:
        return None
    parts = PurePosixPath(path).parts
    folder_indexes = [i for i, part in enumerate(parts)
                      if part in _show_folder_names(candidate)]
    if not folder_indexes:
        return None
    folder_index = folder_indexes[-1]
    if folder_index + 2 >= len(parts):
        return None
    filename = parts[folder_index + 2].lower()
    title = re.sub(r'[^a-z0-9]', '', candidate['title'].lower())
    match = re.fullmatch(r'(.+)_s([0-9]{2})e([0-9]{2})_([a-f0-9]{8})\.mkv', filename)
    if (not match or re.sub(r'[^a-z0-9]', '', match.group(1)) != title
            or parts[folder_index + 1] != f'Season.{int(match.group(2)):02d}'
            or require_hash and match.group(4) != _normal_hash(candidate['hash'])[:8]):
        return None
    return int(match.group(2)), int(match.group(3))


def _episode_path_matches(path: object, candidate: dict, *, require_hash: bool = True) -> bool:
    return _episode_path_identity(path, candidate, require_hash=require_hash) == (
        candidate['season'], candidate['episode'])


class Tiramisu:
    """No TCP fallback, redirects, retries, or caller-selected endpoint paths."""

    def __init__(self):
        try:
            config = load_config()
        except MediaUnavailable:
            raise
        acquisition = config.get('acquisition')
        discovery = config.get('discovery')
        if not config.get('enabled') or not isinstance(acquisition, dict):
            raise MediaUnavailable('media_acquisition_unavailable')
        if acquisition.get('enabled') is not True:
            raise MediaUnavailable('media_acquisition_disabled')
        self.socket_path = acquisition.get('socket')
        self.instance_id = acquisition.get('instance_id')
        if (not isinstance(self.socket_path, str) or not self.socket_path.startswith('/')
                or len(self.socket_path) > 4096
                or any(part in ('', '.', '..') for part in self.socket_path.split('/')[1:])
                or not isinstance(self.instance_id, str)
                or not _INSTANCE.fullmatch(self.instance_id)):
            raise MediaUnavailable('media_acquisition_config_invalid')
        try:
            info = os.lstat(self.socket_path)
        except OSError:
            raise MediaUnavailable('tiramisu_not_ready') from None
        if (not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077):
            raise MediaUnavailable('tiramisu_socket_not_owner_only')
        self.socket_identity = (info.st_dev, info.st_ino, info.st_uid, stat.S_IMODE(info.st_mode))
        self.config_fingerprint = _fingerprint(acquisition, discovery)

    def binding(self) -> dict:
        return {'instance_id': self.instance_id, 'config_fingerprint': self.config_fingerprint,
                'socket_identity': self.socket_identity}

    def validate_binding(self, candidate: dict) -> None:
        current = load_config()
        acquisition = current.get('acquisition')
        discovery = current.get('discovery')
        try:
            info = os.lstat(self.socket_path)
        except OSError:
            raise MediaUnavailable('tiramisu_socket_changed') from None
        live_identity = (info.st_dev, info.st_ino, info.st_uid, stat.S_IMODE(info.st_mode))
        if (candidate.get('instance_id') != self.instance_id
                or candidate.get('config_fingerprint') != self.config_fingerprint
                or candidate.get('socket_identity') != self.socket_identity
                or not isinstance(acquisition, dict)
                or not isinstance(discovery, dict)
                or current.get('enabled') is not True
                or acquisition.get('enabled') is not True
                or acquisition.get('socket') != self.socket_path
                or acquisition.get('instance_id') != self.instance_id
                or _fingerprint(acquisition, discovery) != self.config_fingerprint
                or candidate.get('provider') != discovery.get('provider', 'torrentio')
                or not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or live_identity != self.socket_identity):
            raise MediaUnavailable('media_candidate_binding_changed')

    async def _request_once(self, method: str, endpoint: str, payload: dict | None) -> tuple[int, object]:
        transport = httpx.AsyncHTTPTransport(uds=self.socket_path, retries=0)
        async with httpx.AsyncClient(transport=transport, base_url='http://localhost',
                                     timeout=None, follow_redirects=False, trust_env=False,
                                     limits=httpx.Limits(max_connections=1, max_keepalive_connections=0)) as client:
            request = client.build_request(method, endpoint, json=payload,
                                           headers={'Accept': 'application/json',
                                                    'Accept-Encoding': 'identity'})
            async with client.stream(request.method, request.url, headers=request.headers,
                                     content=request.content) as response:
                if response.headers.get('content-encoding', 'identity') != 'identity':
                    raise MediaUnavailable('tiramisu_invalid_response')
                length = response.headers.get('content-length')
                if length and (not length.isdigit() or int(length) > _MAX_REPLY):
                    raise MediaUnavailable('tiramisu_response_limit')
                body = bytearray()
                async for chunk in response.aiter_bytes(65536):
                    body.extend(chunk)
                    if len(body) > _MAX_REPLY:
                        raise MediaUnavailable('tiramisu_response_limit')
                if response.status_code < 200 or response.status_code >= 300:
                    return response.status_code, {}
                if response.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
                    raise MediaUnavailable('tiramisu_invalid_response')
                try:
                    value = json.loads(body)
                except (ValueError, UnicodeError):
                    raise MediaUnavailable('tiramisu_invalid_response') from None
                if not isinstance(value, (dict, list)):
                    raise MediaUnavailable('tiramisu_invalid_response')
                return response.status_code, value

    async def _request(self, method: str, endpoint: str, *, payload: dict | None = None,
                       cancel=None, timeout: float = 8.0) -> tuple[int, object]:
        if cancel is not None and cancel.is_set():
            raise asyncio.CancelledError
        task = asyncio.create_task(self._request_once(method, endpoint, payload))
        deadline = time.monotonic() + timeout
        try:
            while not task.done():
                if cancel is not None and cancel.is_set():
                    raise asyncio.CancelledError
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                await asyncio.wait((task,), timeout=min(.05, remaining))
            return task.result()
        except asyncio.CancelledError:
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
            raise
        except TimeoutError:
            if not task.done():
                task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await task
            raise MediaUnavailable('tiramisu_request_uncertain') from None
        except (httpx.HTTPError, OSError):
            raise MediaUnavailable('tiramisu_request_uncertain') from None

    async def _list_exact(self, candidate: dict, cancel=None) -> dict | None:
        content_type = 'movie' if candidate['type'] == 'movie' else 'tv'
        status, body = await self._request('GET', f'/api/library/list?type={content_type}',
                                           cancel=cancel, timeout=6)
        if status != 200 or not isinstance(body, list) or len(body) > 20000:
            raise MediaUnavailable('tiramisu_reconcile_unavailable')
        expected = _normal_hash(candidate['hash'])
        saw_hash = False
        for row in body:
            if not isinstance(row, dict):
                continue
            row_episode = (_episode_path_identity(row.get('path'), candidate, require_hash=False)
                           if candidate['type'] == 'series' else None)
            if (candidate['type'] == 'series' and row_episode == (candidate['season'], candidate['episode'])
                    and row.get('season') == candidate['season']
                    and row.get('episode') == candidate['episode']
                    and _normal_hash(row.get('hash')) != expected):
                raise MediaUnavailable('tiramisu_episode_replacement_prohibited')
            if _normal_hash(row.get('hash')) != expected:
                continue
            saw_hash = True
            if candidate['type'] == 'movie':
                if (row.get('imdb') == candidate['imdb']
                        and isinstance(row.get('path'), str)
                        and row['path'].lower().endswith('.mkv')):
                    return {'files': 1, 'already_present': True}
                raise MediaUnavailable('tiramisu_existing_identity_conflict')
            row_episode = _episode_path_identity(row.get('path'), candidate)
            if row_episode is None:
                raise MediaUnavailable('tiramisu_existing_identity_conflict')
            if (row_episode == (candidate['season'], candidate['episode'])
                    and row.get('season') == candidate['season']
                    and row.get('episode') == candidate['episode']):
                return {'files': 1, 'already_present': True}
        if len(body) >= 32:
            raise MediaUnavailable('tiramisu_catalogue_limit')
        if saw_hash and candidate['type'] == 'series':
            # Same torrent may already hold other episodes of the same series. The
            # caller may still register this distinct exact episode once.
            return None
        return None

    async def search(self, metadata: dict, *, season: int | None = None,
                     episode: int | None = None, cancel=None) -> list[dict]:
        """Use Tiramisu's explicitly read-only local Prowlarr route once."""
        self.validate_binding(metadata)
        params = {'imdb_id': metadata['imdb'],
                  'type': 'series' if metadata['type'] == 'series' else 'movie',
                  'title': metadata['title']}
        if metadata['year'] is not None:
            params['year'] = str(metadata['year'])
        if metadata['type'] == 'series':
            params['season'] = str(season)
        endpoint = '/api/prowlarr/search?' + urlencode(params)
        status, body = await self._request('GET', endpoint, cancel=cancel, timeout=35)
        if status in (404, 503):
            raise MediaUnavailable('prowlarr_search_not_enabled')
        if status != 200 or not isinstance(body, list) or len(body) > 500:
            raise MediaUnavailable('prowlarr_search_unavailable')
        streams = []
        for row in body:
            if not isinstance(row, dict):
                continue
            info_hash = row.get('infoHash')
            title = row.get('title')
            name = row.get('name')
            if (not isinstance(info_hash, str)
                    or not re.fullmatch(r'(?:[a-fA-F0-9]{40}|[A-Za-z2-7]{32})', info_hash)
                    or not isinstance(title, str) or not 1 <= len(title) <= 512
                    or not isinstance(name, str) or not 1 <= len(name) <= 256):
                continue
            streams.append({'infoHash': info_hash, 'title': title, 'name': name})
        if not streams:
            # Upstream deliberately returns [] both for no matches and when
            # Prowlarr is unconfigured; do not present that as a verified miss.
            raise MediaUnavailable('prowlarr_empty_or_unconfigured')
        return streams

    async def register(self, candidate: dict, cancel=None) -> dict:
        """Send one add request; uncertain completion is reconciled read-only."""
        self.validate_binding(candidate)
        if cancel is not None and cancel.is_set():
            raise asyncio.CancelledError
        existing = await self._list_exact(candidate, cancel)
        if existing:
            return {'status': 'completed', 'delivery': 'verified', 'effect_applied': False,
                    'type': 'movie' if candidate['type'] == 'movie' else 'tv',
                    'title': candidate['title'], 'registered_files': existing['files'],
                    'already_present': True, 'must_not_replay': True}
        payload = {
            'type': 'movie' if candidate['type'] == 'movie' else 'tv',
            'hash': _normal_hash(candidate['hash']),
            'title': candidate['title'],
            'release_title': candidate['release_title'],
            'metadata_wait': 20,
        }
        if candidate['type'] == 'movie':
            if candidate.get('year') is not None:
                payload['year'] = candidate['year']
            payload['imdb'] = candidate['imdb']
        else:
            payload.update({'season': candidate['season'], 'episode': candidate['episode'],
                            'first_air_date': candidate['first_air_date']})
        # No code path retries POST. Any post-dispatch failure reconciles by a GET.
        context = candidate['_context']
        context['_media_acquisition_outcome'] = {
            'status': 'interrupted', 'delivery': 'not_dispatched',
            'effect_applied': False, 'must_not_replay': True}
        dispatched = False
        try:
            if cancel is not None and cancel.is_set():
                raise asyncio.CancelledError
            self.validate_binding(candidate)
            dispatched = True
            context['_media_acquisition_outcome'] = {
                'status': 'uncertain', 'delivery': 'uncertain',
                'effect_applied': None, 'must_not_replay': True}
            status, body = await self._request('POST', '/api/library/add', payload=payload,
                                               cancel=cancel, timeout=35)
            if status in (200, 201) and isinstance(body, dict):
                files = body.get('files')
                added_hash = _normal_hash(body.get('hash'))
                added_type = body.get('type')
                if candidate['type'] == 'movie':
                    exact_file = any(isinstance(row, dict)
                                     and isinstance(row.get('path'), str)
                                     and row['path'].lower().endswith('.mkv')
                                     and type(row.get('file_index')) is int
                                     for row in files) if isinstance(files, list) else False
                else:
                    exact_file = any(isinstance(row, dict)
                                     and row.get('season') == candidate['season']
                                     and row.get('episode') == candidate['episode']
                                     and _episode_path_matches(row.get('path'), candidate)
                                     and type(row.get('file_index')) is int
                                     for row in files) if isinstance(files, list) else False
                if (added_hash == payload['hash'] and added_type == payload['type']
                        and body.get('title') == candidate['title']
                        and isinstance(files, list) and 0 < len(files) <= 256
                        and all(isinstance(row, dict) for row in files) and exact_file):
                    reconciled = await self._list_exact(candidate, cancel)
                    if not reconciled:
                        raise MediaUnavailable('tiramisu_registration_not_visible')
                    result = {'status': 'completed', 'delivery': 'verified',
                              'effect_applied': not bool(body.get('already_present')),
                              'type': payload['type'], 'title': candidate['title'],
                              'registered_files': len(files),
                              'already_present': bool(body.get('already_present')),
                              'must_not_replay': True}
                    context['_media_acquisition_outcome'] = result
                    return result
            raise MediaUnavailable('tiramisu_response_uncertain')
        except asyncio.CancelledError:
            if dispatched:
                context['_media_acquisition_outcome'] = {
                    'status': 'interrupted', 'delivery': 'uncertain',
                    'effect_applied': None, 'must_not_replay': True}
            raise
        except MediaUnavailable:
            if not dispatched:
                raise
        except Exception:
            if not dispatched:
                raise
        # Caller outcome may have been delivered even when the socket response was lost.
        # Reconcile only; never resend the write.
        try:
            if cancel is not None and cancel.is_set():
                raise asyncio.CancelledError
            reconciled = await self._list_exact(candidate, cancel)
            if reconciled:
                result = {'status': 'completed', 'delivery': 'verified',
                          'effect_applied': None, 'type': payload['type'],
                          'title': candidate['title'], 'registered_files': reconciled['files'],
                          'already_present': True, 'reconciled': True, 'must_not_replay': True}
                context['_media_acquisition_outcome'] = result
                return result
        except asyncio.CancelledError:
            context['_media_acquisition_outcome'] = {
                'status': 'interrupted', 'delivery': 'uncertain',
                'effect_applied': None, 'must_not_replay': True}
            raise
        except Exception:
            pass
        result = {'status': 'uncertain', 'delivery': 'uncertain',
                  'effect_applied': None, 'title': candidate['title'],
                  'must_not_replay': True,
                  'message': 'Registration outcome could not be reconciled. Do not repeat this request.'}
        context['_media_acquisition_outcome'] = result
        return result


def _normal_hash(value: object) -> str:
    if not isinstance(value, str):
        return ''
    text = value.strip().lower()
    if _HEX_HASH.fullmatch(text):
        return text
    if re.fullmatch(r'[a-z2-7]{32}', text, re.I):
        try:
            decoded = base64.b32decode(text.upper())
            if len(decoded) == 20:
                return decoded.hex()
        except (ValueError, binascii.Error):
            pass
    return ''


def socket_status() -> dict:
    """Read-only readiness check; does not connect or send an HTTP request."""
    try:
        client = Tiramisu()
        return {'enabled': True, 'providers': ['tiramisu'], 'transport': 'owner_unix_socket',
                'instance_id': client.instance_id, 'ready': True}
    except MediaUnavailable as error:
        return {'enabled': False, 'providers': [], 'ready': False, 'readiness': str(error)}
