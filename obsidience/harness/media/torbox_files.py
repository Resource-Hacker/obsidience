"""Exact TorBox account-file admission through its native read-only WebDAV mount."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time
from urllib.parse import quote, unquote, urlsplit
import xml.etree.ElementTree as ET

import httpx

from .config import MediaUnavailable
from .sources import _mount, _parts


def ready_mount(root: dict) -> dict:
    marker = Path(f'/run/user/{os.getuid()}/obsidience-media-torbox/ready.json')
    try:
        fd = os.open(marker, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError
            value = json.loads(os.read(fd, 8193))
        finally:
            os.close(fd)
        mount = _mount(root)
        if value['mount'] != mount or type(value['pid']) is not int:
            raise ValueError
        process = Path(f'/proc/{value["pid"]}')
        if process.stat().st_uid != os.getuid() or (process / 'exe').resolve() != Path('/usr/bin/rclone'):
            raise ValueError
        if (process / 'stat').read_text().rsplit(')', 1)[1].split()[19] != value['start']:
            raise ValueError
        return value
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        raise MediaUnavailable('torbox_mount_not_ready') from None


def _dav_client(config: dict) -> httpx.Client:
    from .jellyfin import _token
    return httpx.Client(trust_env=False, follow_redirects=False, timeout=5,
                        limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
                        auth=('torbox', _token(config['debrid']['credential'])))


def _dav(config: dict, method: str, relative: str, *, refresh=False,
         client: httpx.Client | None = None, deadline: float | None = None) -> bytes:
    if client is None:
        with _dav_client(config) as owned:
            return _dav(config, method, relative, refresh=refresh, client=owned, deadline=deadline)
    _parts(relative) if relative else None
    url = 'https://webdav.torbox.app/' + quote(relative, safe='/')
    if refresh:
        url = 'https://webdav.torbox.app/refresh'
    headers = {'Accept-Encoding': 'identity', 'Depth': '1'}
    content = ('<?xml version="1.0"?><d:propfind xmlns:d="DAV:"><d:prop>'
               '<d:resourcetype/><d:getcontentlength/><d:getetag/>'
               '</d:prop></d:propfind>') if method == 'PROPFIND' else None
    deadline = min(time.monotonic() + 6, deadline) if deadline is not None else time.monotonic() + 6
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise MediaUnavailable('torbox_webdav_limit')
    try:
        with client.stream(method, url, headers=headers, content=content,
                           timeout=min(5, remaining)) as reply:
            if reply.status_code not in ((200, 204, 303) if refresh else (207,)):
                raise MediaUnavailable('torbox_webdav_unavailable')
            if refresh and reply.status_code == 303:
                target = urlsplit(reply.headers.get('location', ''))
                if (target.scheme not in ('', 'https') or target.netloc not in ('', 'webdav.torbox.app')
                        or target.path != '/' or target.query or target.fragment):
                    raise MediaUnavailable('torbox_refresh_unverified')
                return b''
            body = bytearray()
            for chunk in reply.iter_raw():
                body.extend(chunk)
                if len(body) > 512 * 1024 or time.monotonic() > deadline:
                    raise MediaUnavailable('torbox_webdav_limit')
            return bytes(body)
    except (httpx.HTTPError, OSError):
        raise MediaUnavailable('torbox_webdav_unavailable') from None


def dav_files(config: dict, directory: str, *, client: httpx.Client | None = None,
              deadline: float | None = None) -> list[dict]:
    """One bounded directory, never a recursive account walk or an arbitrary URL."""
    try:
        material = _dav(config, 'PROPFIND', directory, client=client, deadline=deadline)
        if b'<!DOCTYPE' in material or b'<!ENTITY' in material:
            raise ValueError
        document = ET.fromstring(material)
        rows = document.findall('{DAV:}response')
        if len(rows) > 1024:
            raise ValueError
        result = []
        for row in rows:
            href = row.findtext('{DAV:}href')
            prop = row.find('{DAV:}propstat/{DAV:}prop')
            if not href or prop is None:
                continue
            uri = urlsplit(href)
            if uri.scheme or uri.netloc or uri.query or uri.fragment:
                raise ValueError
            path = unquote(uri.path).strip('/')
            if not path or path == directory:
                continue
            _parts(path)
            if ('' if str(PurePosixPath(path).parent) == '.' else str(PurePosixPath(path).parent)) != directory:
                raise ValueError
            collection = prop.find('{DAV:}resourcetype/{DAV:}collection') is not None
            raw_size = prop.findtext('{DAV:}getcontentlength', '0')
            result.append({'path': path, 'directory': collection,
                           'size': int(raw_size)})
        return result
    except (ValueError, ET.ParseError):
        raise MediaUnavailable('torbox_webdav_invalid_listing') from None


def account_file_path(config: dict, registered: dict, *, client: httpx.Client | None = None,
                      deadline: float | None = None) -> str:
    """Resolve a provider file to WebDAV only by exact native name/path and size."""
    deadline = time.monotonic() + 12 if deadline is None else deadline
    if client is None:
        # The native DAV server sets a load-balancer affinity cookie. One exact
        # ancestor walk must use the same backend rather than mix its snapshots.
        with _dav_client(config) as owned:
            return account_file_path(config, registered, client=owned, deadline=deadline)
    # Verify native paths against this account's current WebDAV listing.
    # No fuzzy filename match and no fallback to another edition.
    path = registered['path']
    _parts(path)
    name = registered.get('name', '')
    _parts(name)
    tag = registered['tag']
    if tag not in ('obsidience movies', 'obsidience tv'):
        raise MediaUnavailable('torbox_library_tag_unverified')
    candidates = {path, name + '/' + path, name + '/' + PurePosixPath(path).name}
    if '/' in path:
        candidates.add(name + '/' + path.split('/', 1)[1])
    candidates = {tag + '/' + p for p in candidates}
    matches = []
    parents = {str(PurePosixPath(p).parent) for p in candidates}
    # Follow only exact candidate ancestors (bounded depth), never recurse over
    # the account or treat an unlisted nested directory as an admitted path.
    listings = {tag: dav_files(config, tag, client=client, deadline=deadline)}
    for parent in sorted(parents):
        parts = PurePosixPath(parent).parts
        if len(parts) > 8:
            raise MediaUnavailable('torbox_webdav_path_limit')
        current = tag
        for part in parts[1:]:
            child = current + '/' + part
            if child not in listings:
                if not any(row['directory'] and row['path'] == child for row in listings[current]):
                    break
                if len(listings) >= 16 or time.monotonic() > deadline:
                    raise MediaUnavailable('torbox_webdav_path_limit')
                listings[child] = dav_files(config, child, client=client, deadline=deadline)
            current = child
        else:
            for row in listings[current]:
                if not row['directory'] and row['path'] in candidates and row['size'] == registered['size']:
                    matches.append(row['path'])
    if time.monotonic() > deadline:
        raise MediaUnavailable('torbox_webdav_path_limit')
    matches = list(set(matches))
    if len(matches) != 1:
        raise MediaUnavailable('torbox_webdav_file_unverified')
    return matches[0]


def refresh(config: dict, registered: dict) -> str:
    """One registration owner refreshes native WebDAV, mount metadata and catalogue."""
    roots = [r for r in config['roots'] if r.get('provider') == 'torbox'
             and r['path'] == r['mount_path'] + '/' + registered['tag']]
    if len(roots) != 1:
        raise MediaUnavailable('torbox_root_unavailable')
    root = roots[0]
    identity = ready_mount(root)
    # Refresh and readback must retain the provider's backend affinity.
    deadline = time.monotonic() + 12
    with _dav_client(config) as client:
        _dav(config, 'GET', '', refresh=True, client=client, deadline=deadline)
        relative = account_file_path(config, registered, client=client, deadline=deadline)
    runtime = Path(f'/run/user/{os.getuid()}/obsidience-media-torbox')
    try:
        with httpx.Client(transport=httpx.HTTPTransport(uds=str(runtime / 'control.sock')),
                          timeout=3, trust_env=False) as client:
            response = client.post('http://localhost/vfs/forget', json={})
            if response.status_code != 200:
                raise MediaUnavailable('torbox_mount_refresh_failed')
    except httpx.HTTPError:
        raise MediaUnavailable('torbox_mount_refresh_failed') from None
    if ready_mount(root) != identity:
        raise MediaUnavailable('torbox_mount_changed')
    return root['catalogue_path'] + '/' + relative[len(registered['tag']) + 1:]


def describe(config: dict, root: dict, relative: str) -> tuple[str, dict]:
    from .torbox import TorBoxAPI, _select, _episode_span, _selection_plan
    _parts(relative)
    if PurePosixPath(relative).suffix.lower() not in ('.mkv', '.mp4', '.m4v', '.webm'):
        raise MediaUnavailable('unsupported_virtual_media')
    mount = ready_mount(root)
    tag = str(PurePosixPath(root['path']).relative_to(root['mount_path']))
    if tag not in ('obsidience movies', 'obsidience tv'):
        raise MediaUnavailable('torbox_root_unavailable')
    client = TorBoxAPI(config)
    rows = asyncio.run(client.mylist())
    found = []
    for row in rows:
        if not row['download_finished'] or not row['download_present'] or tag not in row['tags']:
            continue
        # Provider-owned registration name carries exact metadata identity. It is
        # checked with every actual video filename, never trusted as a path.
        match = re.fullmatch(r'(.+) \((\d{4})\) \[imdbid-(tt\d{7,10})\]', row['name'])
        if not match:
            continue
        for file in row['files']:
            if PurePosixPath(file['path']).suffix.lower() not in ('.mkv', '.mp4', '.m4v', '.webm'):
                continue
            # Skip unrelated files before parsing the complete series plan.
            native = {file['path'], row['name'] + '/' + file['path'],
                      row['name'] + '/' + PurePosixPath(file['path']).name}
            if '/' in file['path']:
                native.add(row['name'] + '/' + file['path'].split('/', 1)[1])
            if relative not in native:
                continue
            candidate = {'title': match[1], 'year': int(match[2]),
                         'type': 'series' if tag == 'obsidience tv' else 'movie'}
            span = _episode_span(file['path'], candidate) if candidate['type'] == 'series' else None
            if candidate['type'] == 'series' and span is None:
                continue
            candidate.update({'season': span[0] if span else None,
                              'episode': span[1] if span else None})
            selected = _select(candidate, row['files'])
            if selected != file:
                continue
            registered = {'hash': row['hash'], 'torrent_id': row['torrent_id'],
                          'name': row['name'], 'tag': tag, **file}
            if account_file_path(config, registered) == tag + '/' + relative:
                found.append({**registered, 'imdb': match[3], 'season': candidate['season'],
                              'episode': candidate['episode'], 'episode_end': span[2] if span else None,
                              'plan': _selection_plan(candidate, row['files']), 'fuse_path': relative})
    if len(found) != 1 or ready_mount(root) != mount:
        raise MediaUnavailable('torbox_source_identity_unverified')
    identity = {'mount': mount['mount'], 'provider': {**client.binding(), 'mount_owner': mount},
                'file': found[0]}
    revision = hashlib.sha256(json.dumps([root, relative, identity], sort_keys=True,
                                         separators=(',', ':')).encode()).hexdigest()
    return revision, identity
