"""Pause one current Edge MPRIS media session; never toggle or start playback."""
from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess
import threading
import time
import unicodedata

_PATH = '/org/mpris/MediaPlayer2'
_PLAYER = 'org.mpris.MediaPlayer2.Player'
_DBUS = ('org.freedesktop.DBus', '/org/freedesktop/DBus', 'org.freedesktop.DBus')
_EDGE_EXE = '/opt/microsoft/msedge/msedge'
_LOCK = threading.Lock()


class MediaFailure(Exception):
    pass


def _check(cancel, deadline):
    if cancel is not None and cancel.is_set():
        raise MediaFailure('cancelled')
    if time.monotonic() >= deadline:
        raise MediaFailure('media_timeout')


def _call(arguments, cancel, deadline):
    _check(cancel, deadline)
    # busctl owns this one call only. Unique destinations cannot silently switch
    # to a replacement browser; no shell or caller-selected interface is used.
    try:
        with subprocess.Popen(['/usr/bin/busctl', '--user', '--json=short',
                               '--timeout=1s', *arguments],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE) as child:
            try:
                while True:
                    _check(cancel, deadline)
                    try:
                        stdout, _ = child.communicate(timeout=.05)
                        break
                    except subprocess.TimeoutExpired:
                        continue
            except BaseException:
                child.kill()
                child.communicate()
                raise
    except OSError as error:
        raise MediaFailure('media_bus_unavailable') from error
    if child.returncode != 0:
        raise MediaFailure('media_bus_call_failed')
    if len(stdout) > 65536:
        raise MediaFailure('media_reply_too_large')
    if not stdout.strip():
        return None
    try:
        data = json.loads(stdout)['data']
        return data[0] if isinstance(data, list) and len(data) == 1 else data
    except (KeyError, TypeError, ValueError) as error:
        raise MediaFailure('invalid_media_reply') from error


def _bus(method, value, cancel, deadline):
    return _call(['call', *_DBUS, method, 's', value], cancel, deadline)


def _properties(owner, interface, cancel, deadline):
    values = _call(['call', owner, _PATH, 'org.freedesktop.DBus.Properties',
                    'GetAll', 's', interface], cancel, deadline)
    if not isinstance(values, dict):
        raise MediaFailure('invalid_media_properties')
    return {key: value['data'] for key, value in values.items()
            if isinstance(value, dict) and 'data' in value}


def _process(pid):
    if type(pid) is not int or pid < 1:
        raise MediaFailure('invalid_media_pid')
    try:
        folder = Path('/proc') / str(pid)
        if str((folder / 'exe').resolve(strict=True)) != _EDGE_EXE:
            raise MediaFailure('unsupported_media_process')
        start = (folder / 'stat').read_text().rsplit(')', 1)[1].split()[19]
        return start
    except (OSError, IndexError) as error:
        raise MediaFailure('media_process_unavailable') from error


def _snapshot(name, cancel, deadline):
    owner = _bus('GetNameOwner', name, cancel, deadline)
    if not isinstance(owner, str) or not re.fullmatch(r':\d+\.\d+', owner):
        raise MediaFailure('invalid_media_owner')
    pid = _bus('GetConnectionUnixProcessID', owner, cancel, deadline)
    start = _process(pid)
    properties = _properties(owner, _PLAYER, cancel, deadline)
    metadata = properties.get('Metadata')
    if not isinstance(metadata, dict):
        raise MediaFailure('media_metadata_unavailable')
    track_value = metadata.get('mpris:trackid')
    title_value = metadata.get('xesam:title', {'data': ''})
    if not isinstance(track_value, dict) or not isinstance(title_value, dict):
        raise MediaFailure('invalid_media_metadata')
    track = track_value.get('data')
    title = title_value.get('data', '')
    state = properties.get('PlaybackStatus')
    if (not isinstance(track, str) or not track.startswith('/')
            or track.endswith('/NoTrack') or not isinstance(title, str)
            or state not in {'Playing', 'Paused', 'Stopped'}):
        raise MediaFailure('invalid_media_identity')
    if _bus('GetNameOwner', name, cancel, deadline) != owner or _process(pid) != start:
        raise MediaFailure('media_identity_changed')
    return {'player': name, 'owner': owner, 'pid': pid, 'process_start': start,
            'track_id': track, 'title': title[:512], 'state': state,
            'can_pause': properties.get('CanPause') is True,
            'can_control': properties.get('CanControl') is True}


def _identity(snapshot):
    return tuple(snapshot[key] for key in
                 ('player', 'owner', 'pid', 'process_start', 'track_id'))


def _normalize(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def _select(query, cancel, deadline):
    names = _call(['call', *_DBUS, 'ListNames'], cancel, deadline)
    if not isinstance(names, list):
        raise MediaFailure('invalid_media_players')
    names = [name for name in names if isinstance(name, str)
             and re.fullmatch(r'org\.mpris\.MediaPlayer2\.edge\.instance\d+', name)]
    if len(names) > 16:
        raise MediaFailure('too_many_media_players')
    # Any uninspectable eligible player blocks selection; it might be a second
    # matching target. Do not silently skip failures and choose another browser.
    candidates = [_snapshot(name, cancel, deadline) for name in names]
    if query:
        candidates = [row for row in candidates if query in _normalize(row['title'])]
    else:
        playing = [row for row in candidates if row['state'] == 'Playing']
        candidates = playing or candidates
    if not candidates:
        raise MediaFailure('media_target_unavailable')
    if len(candidates) != 1:
        raise MediaFailure('media_target_ambiguous')
    return candidates[0]


def execute(args: dict, context: dict) -> dict:
    result = {'status': 'failed', 'delivery': 'not_dispatched',
              'effect_applied': False, 'must_not_replay': True}
    if (not isinstance(args, dict) or set(args) - {'query'}
            or not isinstance(args.get('query', ''), str)
            or len(args.get('query', '')) > 128
            or any(unicodedata.category(c).startswith('C') for c in args.get('query', ''))):
        return {**result, 'failure': {'code': 'invalid_media_arguments'}}
    if (context.get('_agent_ref') != 'Agents/Executive/Executive'
            or context.get('task') != 'Agents/Executive/Executive'):
        return {**result, 'failure': {'code': 'media_scope_denied'}}
    cancel = context.get('_capability_cancel_event')
    deadline = time.monotonic() + 5
    acquired = False
    try:
        while not acquired:
            _check(cancel, deadline)
            acquired = _LOCK.acquire(timeout=.05)
        if context.get('_media_pause_dispatched'):
            raise MediaFailure('media_already_attempted')
        before = _select(_normalize(args.get('query', '')), cancel, deadline)
        result['target'] = before
        current = _snapshot(before['player'], cancel, deadline)
        if _identity(current) != _identity(before):
            raise MediaFailure('media_identity_changed')
        if current['state'] in {'Paused', 'Stopped'}:
            return {**result, 'status': 'completed', 'delivery': 'verified',
                    'state': current['state'], 'no_change': True, 'verified_at': time.time()}
        if not current['can_pause'] or not current['can_control']:
            raise MediaFailure('media_pause_unavailable')
        key = _identity(current)
        _check(cancel, deadline)
        context['_media_pause_dispatched'] = True
        # Mark possible dispatch before starting the transport. No effect retry.
        result.update(delivery='uncertain', effect_applied=None)
        _call(['call', current['owner'], _PATH, _PLAYER, 'Pause'], cancel, deadline)
        result['delivery'] = 'acknowledged'
        # A method return is not successful playback verification. Obtain fresh
        # state, same bus-owner/PID/start and same track after the one Pause.
        while True:
            after = _snapshot(before['player'], cancel, deadline)
            if _identity(after) != key:
                raise MediaFailure('media_identity_changed')
            result['state'] = after['state']
            if after['state'] in {'Paused', 'Stopped'}:
                return {**result, 'status': 'completed', 'delivery': 'verified',
                        'effect_applied': True, 'verified_at': time.time()}
            _check(cancel, deadline)
            if cancel is not None:
                cancel.wait(.05)
            else:
                threading.Event().wait(.05)
    except MediaFailure as error:
        result['failure'] = {'code': str(error)}
        return result
    finally:
        if acquired:
            _LOCK.release()
