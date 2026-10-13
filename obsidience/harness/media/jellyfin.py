"""Read-only Jellyfin catalogue adapter; playback always goes through the tuner.

API reference: jellyfin/jellyfin ca0f16eb7c195f720a1493ed469a27c4657db0c6
ItemsController GET Items (userId, ids, fields); SystemController Info/Public.
UserLibrary item-detail GET intentionally unused: it refreshes metadata on demand.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import time
from pathlib import PurePosixPath
from uuid import UUID

import httpx

from .config import MediaUnavailable, validate_config
from .sources import describe

_MAX_BODY = 2 * 1024 * 1024
_SOURCE_ID = re.compile(r'[A-Za-z0-9_-]{1,128}')


def _invalid_constant(_value: str):
    raise ValueError('invalid_json_constant')


def _id(value: object) -> str:
    try:
        return UUID(value).hex
    except (TypeError, ValueError, AttributeError):
        raise MediaUnavailable('invalid_catalogue_item') from None


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    # Public titles cannot expose paths, URLs, markup or control characters.
    clean = ' '.join(value.split())[:160]
    if (not clean or any(ord(c) < 32 or ord(c) == 127 for c in clean)
            or '://' in clean or '/' in clean or '\\' in clean
            or '<' in clean or '>' in clean):
        return None
    return clean


def _number(value: object) -> int | None:
    return value if type(value) is int and 0 <= value <= 100000 else None


def _token(name: str) -> str:
    directory = os.environ.get('CREDENTIALS_DIRECTORY')
    if not directory:
        raise MediaUnavailable('media_credential_unavailable')
    fd = -1
    try:
        fd = os.open(os.path.join(directory, name), os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
            raise MediaUnavailable('media_credential_unavailable')
        value = os.read(fd, 4097).decode('ascii').strip()
        if not value or len(value) > 4096 or not re.fullmatch(r'[A-Za-z0-9._~-]+', value):
            raise MediaUnavailable('media_credential_unavailable')
        return value
    except (OSError, UnicodeError):
        raise MediaUnavailable('media_credential_unavailable') from None
    finally:
        if fd >= 0:
            os.close(fd)


class JellyfinCatalogue:
    """Harness owns start/close; config remains a private validated snapshot."""

    def __init__(self, config: dict):
        self.config = validate_config(config)
        self.client: httpx.Client | None = None

    def start(self) -> None:
        if self.client is None:
            self.client = httpx.Client(timeout=httpx.Timeout(3.0, connect=1.0),
                                       follow_redirects=False, trust_env=False,
                                       limits=httpx.Limits(max_connections=2, max_keepalive_connections=1))

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None

    def _catalogue(self) -> dict:
        if not self.config['enabled']:
            raise MediaUnavailable('media_disabled')
        if 'catalogue' not in self.config:
            raise MediaUnavailable('catalogue_not_configured')
        if self.client is None:
            raise MediaUnavailable('catalogue_unavailable')
        return self.config['catalogue']

    def _get(self, endpoint: str, params: dict | None = None) -> dict:
        catalogue = self._catalogue()
        started = time.monotonic()
        try:
            headers = {'Accept': 'application/json', 'Accept-Encoding': 'identity'}
            if endpoint != '/System/Info/Public':
                headers['Authorization'] = ('MediaBrowser Client="Obsidience Media", Device="Workstation", '
                                            'DeviceId="obsidience-media", Version="1", Token="'
                                            + _token(catalogue['credential']) + '"')
            with self.client.stream('GET', catalogue['url'] + endpoint,
                                    params=params, headers=headers) as response:
                if response.status_code != 200:
                    raise MediaUnavailable('catalogue_request_failed')
                if response.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
                    raise MediaUnavailable('invalid_catalogue_response')
                if response.headers.get('content-encoding', 'identity') != 'identity':
                    raise MediaUnavailable('invalid_catalogue_response')
                material = bytearray()
                for chunk in response.iter_bytes(65536):
                    material.extend(chunk)
                    if len(material) > _MAX_BODY or time.monotonic() - started > 5:
                        raise MediaUnavailable('catalogue_response_limit')
                result = json.loads(material, parse_constant=_invalid_constant)
                if not isinstance(result, dict):
                    raise MediaUnavailable('invalid_catalogue_response')
                return result
        except (httpx.HTTPError, ValueError, UnicodeError):
            raise MediaUnavailable('catalogue_unavailable') from None

    def _pin(self) -> dict:
        catalogue = self._catalogue()
        info = self._get('/System/Info/Public')
        if info.get('Id') != catalogue['instance_id']:
            raise MediaUnavailable('catalogue_instance_changed')
        return catalogue

    def _query(self, **params) -> dict:
        catalogue = self._catalogue()
        return self._get('/Items', {'userId': catalogue['user_id'],
                                   'includeItemTypes': 'Movie,Episode', 'recursive': 'true',
                                   'fields': 'Path,MediaSources', 'enableImages': 'false',
                                   'enableUserData': 'false', 'sortBy': 'SortName',
                                   'sortOrder': 'Ascending', **params})

    def _item(self, item_id: str) -> dict:
        page = self._query(ids=_id(item_id), limit=2)
        items = page.get('Items')
        if not isinstance(items, list) or len(items) != 1:
            raise MediaUnavailable('catalogue_item_unavailable')
        item = items[0]
        if (not isinstance(item, dict) or _id(item.get('Id')) != _id(item_id)
                or item.get('Type') not in ('Movie', 'Episode') or item.get('IsFolder') is True):
            raise MediaUnavailable('catalogue_item_unavailable')
        return item

    def _local(self, source: dict) -> tuple[str, str]:
        if (source.get('Protocol') != 'File' or source.get('Type') != 'Default'
                or source.get('RequiresOpening') or source.get('RequiresClosing')
                or source.get('RequiresLooping') or source.get('IsRemote')
                or source.get('VideoType', 'VideoFile') != 'VideoFile'):
            raise MediaUnavailable('unsupported_catalogue_source')
        path = source.get('Path')
        if (not isinstance(path, str) or len(path) > 4096 or not path.startswith('/')
                or '\\' in path or any(ord(c) < 32 for c in path)
                or any(p in ('', '.', '..') for p in path.split('/')[1:])):
            raise MediaUnavailable('unsupported_catalogue_source')
        matches = [r for r in self.config['roots'] if path.startswith(r['catalogue_path'] + '/')]
        if len(matches) != 1:
            raise MediaUnavailable('catalogue_source_not_mapped')
        root = matches[0]
        relative = path[len(root['catalogue_path']) + 1:]
        if PurePosixPath(relative).suffix.lower() not in ('.mp4', '.m4v', '.mkv', '.webm'):
            raise MediaUnavailable('unsupported_catalogue_source')
        return root['id'], relative

    def _source(self, item: dict, source_id: str) -> dict:
        if not isinstance(source_id, str) or not _SOURCE_ID.fullmatch(source_id):
            raise MediaUnavailable('invalid_catalogue_source')
        sources = item.get('MediaSources')
        if not isinstance(sources, list) or len(sources) > 32:
            raise MediaUnavailable('catalogue_source_unavailable')
        matches = [s for s in sources if isinstance(s, dict) and s.get('Id') == source_id]
        if len(matches) != 1:
            raise MediaUnavailable('catalogue_source_unavailable')
        self._local(matches[0])
        return matches[0]

    @staticmethod
    def _revision(item: dict, source: dict, local: dict) -> str:
        # Bind the complete selected source metadata and the exact mapping/file identity.
        material = {'item_id': _id(item.get('Id')), 'item_type': item['Type'],
                    'source': source, 'local': local}
        return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(',', ':'),
                                         allow_nan=False).encode()).hexdigest()

    def browse(self, query: str = '', offset: int = 0, limit: int = 20) -> dict:
        if (not isinstance(query, str) or len(query) > 200 or any(ord(c) < 32 for c in query)
                or type(offset) is not int or not 0 <= offset <= 100000
                or type(limit) is not int or not 1 <= limit <= 20):
            raise MediaUnavailable('invalid_catalogue_query')
        self._pin()
        page = self._query(searchTerm=query, startIndex=offset, limit=limit)
        items = page.get('Items')
        total = page.get('TotalRecordCount')
        if (not isinstance(items, list) or len(items) > limit
                or type(total) is not int or not 0 <= total <= 10000000):
            raise MediaUnavailable('invalid_catalogue_response')
        rows = []
        for item in items:
            if not isinstance(item, dict) or item.get('Type') not in ('Movie', 'Episode'):
                continue
            title = _text(item.get('Name'))
            if not title:
                continue
            try:
                item_id = _id(item.get('Id'))
            except MediaUnavailable:
                continue
            sources = item.get('MediaSources')
            if not isinstance(sources, list):
                continue
            if len(sources) > 4:
                raise MediaUnavailable('catalogue_source_choice_limit')
            for source in sources:
                if not isinstance(source, dict):
                    continue
                source_id = source.get('Id')
                if not isinstance(source_id, str) or not _SOURCE_ID.fullmatch(source_id):
                    continue
                try:
                    self._source(item, source_id)
                except MediaUnavailable:
                    continue
                rows.append({'item_id': item_id, 'media_source_id': source_id,
                             'type': item['Type'], 'title': title,
                             'year': _number(item.get('ProductionYear')),
                             'series': _text(item.get('SeriesName')),
                             'season': _number(item.get('ParentIndexNumber')),
                             'episode': _number(item.get('IndexNumber'))})
        next_offset = offset + len(items)
        return {'items': rows, 'offset': offset, 'limit': limit, 'total': total,
                'next_offset': next_offset if items and next_offset < total else None}

    def select(self, item_id: str, media_source_id: str) -> dict:
        catalogue = self._pin()
        item = self._item(item_id)
        source = self._source(item, media_source_id)
        root, relative = self._local(source)
        local = describe(self.config, root, relative)
        return {**local, 'catalogue_instance': catalogue['instance_id'],
                'item_id': _id(item_id), 'media_source_id': media_source_id,
                'source_revision': self._revision(item, source, local),
                'title': _text(item.get('Name')) or 'Media'}

    def revalidate(self, binding: dict) -> dict:
        if (not isinstance(binding, dict)
                or set(binding) != {'provider', 'root_id', 'relative_path', 'revision',
                                    'catalogue_instance', 'item_id', 'media_source_id', 'source_revision', 'title'}):
            raise MediaUnavailable('invalid_catalogue_binding')
        if binding['catalogue_instance'] != self._catalogue()['instance_id']:
            raise MediaUnavailable('catalogue_instance_changed')
        current = self.select(binding['item_id'], binding['media_source_id'])
        if current != binding:
            raise MediaUnavailable('catalogue_source_changed')
        return current
