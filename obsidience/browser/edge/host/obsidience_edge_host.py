#!/usr/bin/python3
"""Edge native messaging host org.obsidience.edge: one closed cast message to the TV.

Edge starts this host for the Obsidience Cast extension and speaks Chrome native messaging on
stdio: each message is a 32-bit native-endian length and that many bytes of UTF-8 JSON, both
ways, at most 1 MB. The only message is {"type": "cast", "url": str, "start": int?}. It becomes
one native owner command (operation cast) to the Harness's authenticated media ingress, under
the Shell's owner token, and the reply is {"ok", "state", "summary"} once its receipt settles.

No model is involved: the Harness maps the command to tv.control open. A command is sent once
under a fresh request id; a lost or late answer is reported, never resent. The token is read
for each command (the Shell rotates it when it starts) and never logged.
OBSIDIENCE_EDGE_HOST_HARNESS (http://127.0.0.1:PORT) points the host at another local Harness.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import struct
import sys
import time
import urllib.error
import urllib.request
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from obsidience.shell.command_token import read_token  # noqa: E402

LIMIT = 1024 * 1024
HARNESS = os.environ.get('OBSIDIENCE_EDGE_HOST_HARNESS', 'http://127.0.0.1:8765')
# The Harness confirms playback from the TV route's own readback; a cold TV can take this long.
SETTLE_SECONDS = 60.0
POLL_SECONDS = 0.5


def _read():
    """One message from Edge, or None at the end of input."""
    header = sys.stdin.buffer.read(4)
    if len(header) < 4:
        return None
    length = struct.unpack('=I', header)[0]
    if length > LIMIT:
        raise ValueError('message exceeds 1 MB')
    body = sys.stdin.buffer.read(length)
    if len(body) < length:
        return None
    return json.loads(body.decode('utf-8'))


def _write(message):
    body = json.dumps(message, separators=(',', ':')).encode('utf-8')
    if len(body) > LIMIT:
        raise ValueError('reply exceeds 1 MB')
    sys.stdout.buffer.write(struct.pack('=I', len(body)) + body)
    sys.stdout.buffer.flush()


def _reply(ok, state, summary):
    return {'ok': ok, 'state': state, 'summary': summary}


def _request(method, path, token, body=None):
    """(status, JSON object) from the Harness; OSError when it gave no HTTP answer."""
    request = urllib.request.Request(
        HARNESS + '/api/media' + path, method=method,
        data=None if body is None else json.dumps(body).encode('utf-8'),
        headers={'X-Obsidience-Owner': token, **({'Content-Type': 'application/json'} if body else {})})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status, raw = response.status, response.read(LIMIT)
    except urllib.error.HTTPError as error:
        status, raw = error.code, error.read(LIMIT)
    try:
        data = json.loads(raw.decode('utf-8'))
    except (UnicodeError, ValueError):
        data = {}
    return status, data if isinstance(data, dict) else {}


def cast(message):
    if (not isinstance(message, dict) or message.get('type') != 'cast'
            or set(message) not in ({'type', 'url'}, {'type', 'url', 'start'})
            or not isinstance(message['url'], str) or not 0 < len(message['url']) <= 300
            or 'start' in message and (type(message['start']) is not int
                                       or not 0 <= message['start'] <= 86400)):
        return _reply(False, 'rejected', 'Invalid cast message.')
    try:
        token = read_token()
    except OSError:
        return _reply(False, 'unavailable', 'The Obsidience Shell is not running, so the cast cannot be authorized.')
    request_id = str(uuid.uuid4())
    command = {'request_id': request_id, 'operation': 'cast', 'destination': 'tv', 'url': message['url'],
               **({'start': message['start']} if 'start' in message else {})}
    try:
        status, data = _request('POST', '/commands', token, command)
    except OSError as error:
        if isinstance(getattr(error, 'reason', error), ConnectionRefusedError):
            return _reply(False, 'unavailable', 'The Obsidience Harness is not running.')
        status, data = None, {}  # Perhaps sent, but no answer: only the receipt can tell; never resent.
    if status is not None and status != 202:
        detail = data.get('detail')
        return _reply(False, 'rejected', detail if isinstance(detail, str) and detail
                      else f'The Harness refused the cast (HTTP {status}).')
    deadline = time.monotonic() + SETTLE_SECONDS
    while True:
        try:
            status, data = _request('GET', '/commands/' + request_id, token)
        except OSError:
            status, data = None, {}
        if status == 200 and data.get('settled') is True:
            state = str(data.get('state') or 'failed')
            summary = data.get('summary')
            return _reply(state == 'completed', state, summary if isinstance(summary, str) and summary
                          else 'The cast settled without a summary.')
        if time.monotonic() >= deadline:
            return _reply(False, 'unsettled', 'No settled receipt yet: playback on the TV is unconfirmed. '
                          'The cast was not resent.')
        time.sleep(POLL_SECONDS)


def main():
    if not re.fullmatch(r'http://127\.0\.0\.1:\d{1,5}', HARNESS):
        print('obsidience-edge-host: OBSIDIENCE_EDGE_HOST_HARNESS must be http://127.0.0.1:PORT', file=sys.stderr)
        return 2
    while True:
        try:
            message = _read()
        except (ValueError, UnicodeError) as error:
            # A malformed frame leaves no reliable boundary for the next one.
            _write(_reply(False, 'rejected', f'Invalid native message: {error}.'))
            return 1
        if message is None:
            return 0
        _write(cast(message))


if __name__ == '__main__':
    sys.exit(main())
