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
# Ordinary live commands answer within milliseconds; local VOD reads have a
# separate bounded deadline below.
TIMEOUT = 2.5
# Measured 2026-10-12: a channel shows its first picture 0.5-1.5 s after the request, and about
# 3 s when the tuner first opens a fresh session with Pluto.
START_LIMIT = 12.0
# A target command plus fresh readback may take up to the tuner's five-second
# bound. This transport margin does not authorize another target command.
VOD_LIMIT = 8.0
SEEK_TOLERANCE = 0.5
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
        tuner = _ask({'op': 'state'}, limit=VOD_LIMIT)
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


def play_local(source: dict, title: str, cancel=None, limit: float = START_LIMIT,
               start_seconds: float | None = None, queue: list[dict] | None = None) -> dict:
    """Dispatch one admitted catalogue source once and return its complete readback.

    Only ``playing_verified`` with matching source identity and a fresh generation
    establishes playback. Loading, failed, or a terminal EOF receipt is returned
    explicitly; the caller must not replace that result with title matching or
    retry an uncertain dispatch. Paths are request-only and never returned.

    Optional start_seconds comes from stored catalogue progress and travels in
    this same play request. First-picture position readback must be within five
    seconds of it, with a finite file duration and a target before EOF. Omitting
    it starts at zero; no correction seek or second load follows a timeout.

    Optional queue contains at most 99 remaining exact catalogue bindings including
    their canonical titles. The tuner owns this finite sequence after the request
    returns, revalidates each entry and advances only on verified natural EOF.
    This response verifies the first entry only, never future episode playback.
    """
    fields = ('provider', 'root_id', 'relative_path', 'revision', 'catalogue_instance',
              'item_id', 'media_source_id', 'source_revision')
    if (not isinstance(source, dict) or set(source) not in (set(fields), set(fields) | {'title'})
            or source.get('provider') != 'local' or source.get('title', title) != title):
        raise ValueError('local playback takes one exact catalogue source')
    if start_seconds is not None and (type(start_seconds) not in (int, float)
            or not 0 <= start_seconds <= 1_000_000_000):
        raise ValueError('local start takes a finite nonnegative saved position')
    if queue is not None:
        if (not isinstance(queue, list) or len(queue) > 99
                or any(not isinstance(entry, dict) or set(entry) != set(fields) | {'title'}
                       or entry.get('provider') != 'local' for entry in queue)):
            raise ValueError('local queue takes at most 99 remaining exact catalogue sources')
    expected = {key: source[key] for key in fields if key != 'relative_path'}
    request_generation = secrets.token_hex(16)
    options = {'start_seconds': start_seconds} if start_seconds is not None else {}
    if queue is not None:
        options['queue'] = queue
    tuner = _ask({'op': 'play', **source, 'title': title, 'wait': limit,
                  'generation': request_generation, **options}, limit + TIMEOUT + VOD_LIMIT, cancel)
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
    if queue is not None:
        accepted = tuner.get('queue')
        if (not isinstance(accepted, dict) or accepted.get('origin_generation') != request_generation
                or accepted.get('count') != len(queue) + 1 or accepted.get('index') != 0
                or accepted.get('state') not in ('waiting', 'resolving', 'completed', 'failed')):
            raise ValueError('The TV tuner did not confirm the finite local queue')
    if tuner.get('playback') == 'playing_verified' and tuner.get('verification') != 'verified':
        raise ValueError('The TV tuner did not verify local playback')
    if start_seconds is not None and tuner.get('playback') == 'playing_verified':
        start = tuner.get('start')
        if (not isinstance(start, dict) or start.get('verified') is not True
                or start.get('requested') != start_seconds or type(start.get('position')) not in (int, float)
                or abs(start['position'] - start_seconds) > 5):
            raise ValueError('The TV tuner did not verify the saved start position')
    return tuner


def stop_local(generation: str, source: dict, cancel=None) -> dict:
    """Stop only the exact observed local generation; never a replacement source."""
    # The tuner waits once for the matching unload and its idle readback.
    tuner = _ask({'op': 'stop', 'generation': generation, 'source': source},
                 limit=15.0, cancel=cancel)
    ended = tuner.get('ended')
    if (tuner.get('playback') != 'idle' or not isinstance(ended, dict)
            or ended.get('generation') != generation or ended.get('source') != source
            or ended.get('outcome') != 'stopped'):
        raise ValueError('The TV tuner did not confirm the exact local stop')
    return tuner


def stop_queue(origin_generation: str, cancel=None) -> dict:
    """Stop exactly one observed season intent, even while its next source resolves."""
    if (not isinstance(origin_generation, str) or len(origin_generation) != 32
            or any(char not in '0123456789abcdef' for char in origin_generation)):
        raise ValueError('local queue stop takes the exact origin generation')
    tuner = _ask({'op': 'stop-queue', 'origin_generation': origin_generation},
                 limit=45.0, cancel=cancel)
    receipt, queued = tuner.get('queue_stop'), tuner.get('queue')
    if (tuner.get('playback') != 'idle' or not isinstance(receipt, dict)
            or receipt.get('origin_generation') != origin_generation
            or receipt.get('verified') is not True or not isinstance(queued, dict)
            or queued.get('origin_generation') != origin_generation
            or queued.get('state') not in ('cancelled', 'failed', 'completed')):
        raise ValueError('The TV tuner did not verify the exact finite queue stop')
    return tuner


def _local_control(op: str, generation: str, source: dict, cancel=None, **arguments) -> dict:
    """One exact-source VOD request; uncertain delivery is never replayed."""
    tuner = _ask({'op': op, 'generation': generation, 'source': source, **arguments},
                 limit=VOD_LIMIT, cancel=cancel)
    if tuner.get('generation') != generation or tuner.get('source') != source:
        raise ValueError('The TV tuner did not confirm the exact local generation')
    if tuner.get('verification') != 'verified' or not isinstance(tuner.get('vod'), dict):
        raise ValueError('The TV tuner did not return fresh verified VOD state')
    if op != 'vod-state':
        control = tuner.get('control')
        if not isinstance(control, dict) or control.get('action') != op or control.get('verified') is not True:
            raise ValueError('The TV tuner did not verify the local VOD target')
    return tuner


def local_state(generation: str, source: dict, cancel=None) -> dict:
    """Fresh finite-file position/duration, seekability and embedded track choices."""
    return _local_control('vod-state', generation, source, cancel)


def pause_local(generation: str, source: dict, paused: bool = True, cancel=None) -> dict:
    """Set one exact local generation's pause target, without a toggle."""
    if type(paused) is not bool:
        raise ValueError('local pause takes a boolean target')
    result = _local_control('pause' if paused else 'resume', generation, source, cancel)
    if result['vod'].get('paused') is not paused:
        raise ValueError('The TV tuner did not confirm the local pause target')
    return result


def seek_local(generation: str, source: dict, position: float, cancel=None) -> dict:
    """One absolute exact seek, settled within 0.5 s of the requested position.

    A finite seekable file and a target strictly before EOF are required. A
    position already within tolerance is a verified no-op. No keyframe fallback,
    relative seek, loop, or repeat follows an unverified result.
    """
    if type(position) not in (int, float) or not 0 <= position <= 1_000_000_000:
        raise ValueError('local seek takes a finite nonnegative absolute position')
    result = _local_control('seek', generation, source, cancel, position=position)
    vod = result['vod']
    actual = vod.get('position')
    if (type(actual) not in (int, float) or vod.get('seeking') is not False
            or abs(actual - position) > SEEK_TOLERANCE):
        raise ValueError('The TV tuner did not confirm the exact local seek')
    return result


def select_track_local(generation: str, source: dict, kind: str, track_id: int | None,
                       cancel=None) -> dict:
    """Select a fresh embedded audio/subtitle id, or None to disable that kind."""
    if kind not in ('audio', 'subtitle') or (track_id is not None
            and (type(track_id) is not int or not 0 < track_id <= 2147483647)):
        raise ValueError('local track takes audio or subtitle and an exact id or null for off')
    result = _local_control('track', generation, source, cancel, kind=kind, track_id=track_id)
    if result['vod'].get(kind + '_track') != track_id:
        raise ValueError('The TV tuner did not confirm the exact local track')
    return result


def pause(paused=True):
    """Set the pause flag once; True when the player's own readback shows it."""
    return (_ask({'op': 'pause' if paused else 'resume'}).get('playback') == 'paused') is paused


def stop():
    """End playback and return to the idle player; True when it reads back idle."""
    return _ask({'op': 'stop'}).get('playback') == 'idle'
