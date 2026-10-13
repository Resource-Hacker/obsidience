"""The PC route: the workstation's own player, whose picture the registered TV only displays.

A headless compositor on this workstation runs one idle mpv (obsidience-tv-player.service) that
Sunshine streams to Moonlight on the TV, so a channel starts in about a second instead of a Fire
OS app's 20-50 s. The TV tuner (obsidience-tv-tuner.service, obsidience/tv/host/tuner.py) is the
only owner of that player and of what it shows: it resolves a channel, feeds the player, skips
advertisement breaks behind a break card and keeps running across Harness restarts. This module
is its client. Each call opens one connection to the tuner's socket and closes it before
returning. A request is sent once: a lost or late reply is an error for the caller to report,
never a reason to send it again. Volume stays with the TV. The tuner reports titles and channel
ids only, never a stream address.

Protocol: newline-delimited JSON, one reply {ok, state} or {ok: false, error} per request.
"""
from __future__ import annotations

import json
import os
import secrets
import socket
import time

SOCKET = os.path.join(os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}', 'obsidience-tv', 'tuner.sock')
# The tuner is local and answers within milliseconds; every call but play ends within this.
TIMEOUT = 2.5
# Measured 2026-10-12: a channel shows its first picture 0.5-1.5 s after the request, and about
# 3 s when the tuner first opens a fresh session with Pluto.
START_LIMIT = 12.0
_LINE_LIMIT = 1024 * 1024


def _ask(request, limit=TIMEOUT, cancel=None):
    """One request on one connection, sent once: the tuner's state after it.

    OSError when the tuner does not answer in time, ValueError when it refuses the request.
    """
    if cancel is not None and cancel.is_set():
        raise InterruptedError('TV command cancelled before dispatch')
    deadline = time.monotonic() + limit
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:  # Cleanup paired with the acquisition.
        sock.settimeout(TIMEOUT)
        sock.connect(SOCKET)
        if cancel is not None and cancel.is_set():
            raise InterruptedError('TV command cancelled before dispatch')
        sock.sendall((json.dumps(request) + '\n').encode())
        buffer = b''
        while b'\n' not in buffer:
            if cancel is not None and cancel.is_set():
                raise InterruptedError('TV command cancelled')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('The TV tuner did not answer')
            sock.settimeout(min(remaining, .1))
            try:
                chunk = sock.recv(65536)
            except TimeoutError:
                continue
            if not chunk:
                raise ConnectionError('The TV tuner closed its connection')
            buffer += chunk
            if len(buffer) > _LINE_LIMIT:
                raise ValueError('TV tuner message exceeded its bound')
    reply = json.loads(buffer.split(b'\n', 1)[0])
    if not isinstance(reply, dict) or not reply.get('ok') or not isinstance(reply.get('state'), dict):
        raise ValueError('The TV tuner refused: ' + str(reply.get('error') if isinstance(reply, dict) else '')[:100])
    return reply['state']


def state():
    """What the player shows now, or None when the tuner or its player does not answer.

    playback is idle (nothing loaded), loading (no picture yet), playing, break (a channel's
    advertisement break: the tuner plays none of it and shows a break card until the programme
    returns by itself), paused or failed (with reason); title is the one play gave it; video is
    [width, height] once a picture shows; since is when playback last changed (epoch seconds).
    Local files use playing_verified plus an exact sanitized source and generation.
    Finite EOF returns idle with its terminal ended receipt; it is never reopened.
    """
    try:
        tuner = _ask({'op': 'state'})
    except (OSError, ValueError):
        return None
    return tuner if tuner.get('player') else None


def available():
    """Whether the tuner and its player answer (one read)."""
    return state() is not None


def play(source, title, cancel=None, limit=START_LIMIT):
    """Play one source in place of whatever plays; True once the player shows it.

    source is {'provider': 'pluto', 'channel': <the guide's 24-digit channel id>} or {'url': <https
    address>}. The request is sent once, with the title to report for it. True means its first
    picture shows, or, for a channel tuned in during its advertisement break, the break card that
    stays until the programme returns. False means the tuner took it but showed nothing within the
    limit, or gave the source up (state then says failed and why): the caller reports playback as
    unverified. True proves that this source started, not what its picture shows.
    """
    tuner = _ask({'op': 'play', **source, 'title': title, 'wait': limit}, limit + TIMEOUT, cancel)
    return tuner.get('playback') in ('playing', 'break') and tuner.get('title') == title


def play_local(source: dict, title: str, cancel=None, limit: float = START_LIMIT) -> dict:
    """Dispatch one admitted catalogue source once and return its complete readback.

    Only ``playing_verified`` with matching source identity and a fresh generation
    establishes playback. Loading, failed, or a terminal EOF receipt is returned
    explicitly; the caller must not replace that result with title matching or
    retry an uncertain dispatch. Paths are request-only and never returned.
    """
    fields = ('provider', 'root_id', 'relative_path', 'revision', 'catalogue_instance',
              'item_id', 'media_source_id', 'source_revision')
    if (not isinstance(source, dict) or set(source) not in (set(fields), set(fields) | {'title'})
            or source.get('provider') != 'local' or source.get('title', title) != title):
        raise ValueError('local playback takes one exact catalogue source')
    expected = {key: source[key] for key in fields if key != 'relative_path'}
    request_generation = secrets.token_hex(16)
    tuner = _ask({'op': 'play', **source, 'title': title, 'wait': limit,
                  'generation': request_generation}, limit + TIMEOUT, cancel)
    actual = tuner.get('source')
    # A short finite file can end before the bounded request returns. Its receipt
    # identifies that EOF, without pretending it remains on the screen.
    if actual is None and isinstance(tuner.get('ended'), dict):
        actual = tuner['ended'].get('source')
    if actual != expected:
        raise ValueError('The TV tuner did not confirm the requested local source')
    generation = tuner.get('generation') or (tuner.get('ended') or {}).get('generation')
    if generation != request_generation:
        raise ValueError('The TV tuner did not confirm the playback generation')
    if tuner.get('playback') == 'playing_verified' and tuner.get('verification') != 'verified':
        raise ValueError('The TV tuner did not verify local playback')
    return tuner


def stop_local(generation: str, source: dict, cancel=None) -> dict:
    """Stop only the exact observed local generation; never a replacement source."""
    # The tuner waits once for the matching unload and its idle readback.
    tuner = _ask({'op': 'stop', 'generation': generation, 'source': source},
                 limit=4 * TIMEOUT, cancel=cancel)
    ended = tuner.get('ended')
    if (tuner.get('playback') != 'idle' or not isinstance(ended, dict)
            or ended.get('generation') != generation or ended.get('source') != source
            or ended.get('outcome') != 'stopped'):
        raise ValueError('The TV tuner did not confirm the exact local stop')
    return tuner


def pause(paused=True):
    """Set the pause flag once; True when the player's own readback shows it."""
    return (_ask({'op': 'pause' if paused else 'resume'}).get('playback') == 'paused') is paused


def resume():
    return pause(False)


def stop():
    """End playback and return to the idle player; True when it reads back idle."""
    return _ask({'op': 'stop'}).get('playback') == 'idle'
