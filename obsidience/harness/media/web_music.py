"""Exact YouTube web downloads through the existing paid TorBox provider.

Only prepare() may register a web download. Search never calls this module.
Returned source URLs are private delivery material, not capability observations.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import PurePosixPath
import re
import sys
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .config import MediaUnavailable
from .jellyfin import _text, _token
from .torbox import TorBoxAPI, _API, _identifier

_VIDEO_ID = re.compile(r'[A-Za-z0-9_-]{11}')
_MEDIA = {'.mp4', '.m4v', '.mkv', '.webm', '.mp3', '.m4a', '.aac', '.flac',
          '.wav', '.ogg', '.oga', '.opus'}
_BODY_LIMIT = 65536


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _delivery_url(value):
    try:
        parsed = urlsplit(value) if isinstance(value, str) else None
        if (parsed is None or not 1 <= len(value) <= 8192
                or parsed.scheme != 'https' or not parsed.hostname
                or not parsed.hostname.endswith('.torbox.app')
                or parsed.username is not None or parsed.password is not None
                or parsed.port not in (None, 443) or parsed.fragment
                or any(ord(c) < 33 or 127 <= ord(c) <= 159 for c in value) or '\\' in value):
            raise ValueError
        return value
    except (ValueError, TypeError):
        raise MediaUnavailable('torbox_web_delivery_invalid') from None


def _json_call(endpoint: str, credential: str, *, form=None, params=None):
    """No HTTP logger, proxy, redirect, caller origin or exception text escapes.

    requestdl requires the account token in its query. Never replace this with
    ordinary logged HTTP calls, a subprocess, or a public permalink.
    """
    if endpoint not in ('/webdl/createwebdownload', '/webdl/requestdl'):
        raise MediaUnavailable('torbox_web_endpoint_invalid')
    token = _token(credential)
    query = dict(params or {})
    if endpoint == '/webdl/requestdl':
        query['token'] = token
    url = _API + endpoint + ('?' + urlencode(query) if query else '')
    data = urlencode(form).encode('ascii') if form is not None else None
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/json',
               'Accept-Encoding': 'identity', 'User-Agent': 'Obsidience-Media'}
    if data is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(Request(url, data=data, headers=headers), timeout=8) as response:
            if (response.status != 200
                    or response.headers.get_content_type() != 'application/json'
                    or response.headers.get('Content-Encoding', 'identity') != 'identity'):
                raise ValueError
            deadline, body = time.monotonic() + 8, bytearray()
            while True:
                # read1 returns after one underlying read, so trickle responses
                # cannot keep a read-to-EOF alive indefinitely.
                if time.monotonic() >= deadline:
                    raise ValueError
                chunk = response.read1(min(8192, _BODY_LIMIT + 1 - len(body)))
                body.extend(chunk)
                if len(body) > _BODY_LIMIT:
                    raise ValueError
                if not chunk:
                    break
        value = json.loads(body)
        if not isinstance(value, dict) or value.get('success') is not True:
            raise ValueError
        result = value.get('data')
        if endpoint == '/webdl/requestdl':
            _delivery_url(result)
            if token in result:
                raise ValueError
        return result
    except (OSError, ValueError, UnicodeError, TypeError):
        raise MediaUnavailable('torbox_web_request_unconfirmed') from None


async def _joined_call(endpoint, credential, **kwargs):
    # Always join the finite credential-bearing worker, including cancellation.
    pending = asyncio.create_task(asyncio.to_thread(_json_call, endpoint, credential, **kwargs))
    try:
        return await asyncio.shield(pending)
    except asyncio.CancelledError:
        try:
            await pending
        finally:
            raise


def _cancelled(cancel):
    if cancel is not None and cancel.is_set():
        raise asyncio.CancelledError


async def _inventory(api, canonical, cancel=None, web_id=None, timeout=12):
    params = {'limit': '128', 'offset': '0', 'bypass_cache': 'true'}
    if web_id is not None:
        params['id'] = str(_identifier(web_id))
    data = await api._request('GET', '/webdl/mylist', params=params, cancel=cancel, timeout=timeout)
    if web_id is not None and isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or len(data) > 128:
        raise MediaUnavailable('torbox_web_inventory_invalid')
    if web_id is None and len(data) == 128:
        raise MediaUnavailable('torbox_web_inventory_incomplete')
    matches = []
    for row in data:
        if not isinstance(row, dict):
            raise MediaUnavailable('torbox_web_inventory_invalid')
        if row.get('original_url') != canonical:
            if web_id is not None:
                raise MediaUnavailable('torbox_web_identity_changed')
            continue
        identifier = _identifier(row.get('id'))
        if web_id is not None and identifier != web_id:
            raise MediaUnavailable('torbox_web_identity_changed')
        matches.append(row)
    if len(matches) > 1:
        raise MediaUnavailable('torbox_web_source_ambiguous')
    return matches[0] if matches else None


def _ready_file(row):
    if row.get('error') or str(row.get('download_state', '')).lower() in {
            'failed', 'error', 'expired', 'missing', 'failed_processing'}:
        raise MediaUnavailable('torbox_web_source_failed')
    if row.get('download_present') is not True or row.get('download_finished') is not True:
        return None
    files = row.get('files')
    if not isinstance(files, list) or len(files) != 1 or not isinstance(files[0], dict):
        raise MediaUnavailable('torbox_web_file_ambiguous')
    file = files[0]
    name, size = file.get('name'), file.get('size')
    if (not isinstance(name, str) or not 1 <= len(name) <= 4096 or name.startswith('/')
            or '\\' in name or ':' in name or any(ord(c) < 32 or ord(c) == 127 for c in name)
            or any(part in ('', '.', '..') for part in name.split('/'))
            or PurePosixPath(name).suffix.lower() not in _MEDIA
            or type(size) is not int or not 0 < size <= 100 * 1024**3
            or file.get('zipped') is True or file.get('infected') is True):
        raise MediaUnavailable('torbox_web_file_invalid')
    return _identifier(file.get('id'))


async def prepare(candidate: dict, context: dict, cancel=None) -> dict:
    """Return private {source,title,item_id}, otherwise one sanitized receipt.

    Candidate carries provider='youtube', video_id, title, item_id='youtube:'+id
    and TorBoxAPI.binding() captured when that exact turn selection was made.
    Caller owns turn-selection authority; never accept model-supplied candidates.
    _media_web_outcome[item_id] records attempts before any registration dispatch.
    """
    video_id = candidate.get('video_id') if isinstance(candidate, dict) else None
    if (not isinstance(video_id, str) or not _VIDEO_ID.fullmatch(video_id)
            or candidate.get('provider') != 'youtube'
            or candidate.get('item_id') != 'youtube:' + video_id
            or _text(candidate.get('title')) is None):
        raise MediaUnavailable('torbox_web_selection_invalid')
    title, item_id = _text(candidate['title']), candidate['item_id']
    canonical = 'https://www.youtube.com/watch?v=' + video_id
    outcomes = context.setdefault('_media_web_outcome', {})
    if item_id in outcomes:
        return outcomes[item_id]
    dispatched = False

    def receipt(status, reason):
        result = {'status': status, 'title': title, 'item_id': item_id,
                  'delivery': 'provider_' + status if dispatched else 'not_dispatched',
                  'effect_applied': None if status == 'uncertain' else dispatched, 'must_not_replay': True,
                  'failure': reason, 'playback_started': False}
        outcomes[item_id] = result
        return result

    try:
        api = TorBoxAPI()
        api.validate_binding(candidate)
        _cancelled(cancel)
        if not (await api.account(cancel)).get('paid_active'):
            return receipt('failed', 'torbox_paid_account_required')
        row = await _inventory(api, canonical, cancel)
        if row is None:
            api.validate_binding(candidate)
            _cancelled(cancel)
            dispatched = True
            receipt('uncertain', 'torbox_web_registration_unconfirmed')
            try:
                created = await _joined_call('/webdl/createwebdownload', api.config['credential'],
                                             form={'link': canonical, 'as_queued': 'false',
                                                   'add_only_if_cached': 'false'})
                if not isinstance(created, dict):
                    raise MediaUnavailable('torbox_web_registration_unconfirmed')
                web_id = _identifier(created.get('webdownload_id'))
            except MediaUnavailable:
                # One read-only reconciliation; the uncertain write is never repeated.
                row = await _inventory(api, canonical, cancel)
                if row is None:
                    return receipt('uncertain', 'torbox_web_registration_unconfirmed')
                web_id = _identifier(row.get('id'))
            receipt('pending', 'torbox_web_preparing')
            # At most two fresh reads at the provider's five-second cadence.
            deadline = time.monotonic() + 12
            for attempt in range(2):
                if row is not None and _ready_file(row) is not None:
                    break
                wake_at = min(time.monotonic() + (5 if attempt else 0), deadline)
                while time.monotonic() < wake_at:
                    _cancelled(cancel)
                    await asyncio.sleep(max(0, min(.05, wake_at - time.monotonic())))
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                row = await _inventory(api, canonical, cancel, web_id, timeout=remaining)
        if row is None or _ready_file(row) is None:
            # An existing preparation is also not authorization to create another.
            return receipt('pending', 'torbox_web_preparing')
        _cancelled(cancel)
        api.validate_binding(candidate)
        url = await _joined_call('/webdl/requestdl', api.config['credential'],
                                 params={'web_id': _identifier(row['id']),
                                         'file_id': _ready_file(row), 'zip_link': 'false',
                                         'redirect': 'false'})
        _cancelled(cancel)
        api.validate_binding(candidate)
        result = {'source': {'provider': 'torbox_web', 'video_id': video_id, 'url': url},
                  'title': title, 'item_id': item_id}
        outcomes[item_id] = result
        return result
    except MediaUnavailable:
        return receipt('uncertain' if dispatched else 'failed', 'torbox_web_source_unavailable')
    except asyncio.CancelledError:
        receipt('uncertain' if dispatched else 'failed', 'torbox_web_preparation_cancelled')
        raise


def _stream():
    """Node-owned media child: private URL on stdin, media bytes on stdout.

    Node owns the deadline and process group. No account token is loaded here.
    This is neither a Harness HTTP endpoint nor an independently owned proxy.
    """
    try:
        material = sys.stdin.buffer.read(16385)
        if len(material) > 16384:
            raise ValueError
        value = json.loads(material)
        if not isinstance(value, dict) or set(value) != {'url'}:
            raise ValueError
        url = _delivery_url(value['url'])
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        request = Request(url, headers={'Accept-Encoding': 'identity',
                                       'User-Agent': 'Obsidience-Media'})
        with opener.open(request, timeout=8) as response:
            if (response.status != 200
                    or response.headers.get('Content-Encoding', 'identity') != 'identity'):
                raise ValueError
            while True:
                chunk = response.read1(65536)
                if not chunk:
                    break
                sys.stdout.buffer.write(chunk)
                sys.stdout.buffer.flush()
        return 0
    except (OSError, ValueError, UnicodeError, TypeError, MediaUnavailable):
        sys.stderr.write('Media provider stream unavailable\n')
        return 1


if __name__ == '__main__':
    if sys.argv[1:] != ['stream']:
        sys.stderr.write('Media provider command invalid\n')
        raise SystemExit(2)
    raise SystemExit(_stream())
