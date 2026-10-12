"""The PC route: the workstation's own player, whose picture the registered TV only displays.

A headless compositor on this workstation runs one idle mpv (obsidience-tv-player.service)
that Sunshine streams to Moonlight on the TV, so a channel starts in a few seconds instead
of a Fire OS app's 20-50 s. This module is the only owner of mpv's JSON IPC socket. Each
call opens one connection and closes it before returning. A command is sent once: a lost or
late reply is an error for the caller to report, never a reason to send it again. Volume
stays with the TV. A stream address can carry a session token, so this module never logs or
returns one: the only title it reports is the one play was given.

Protocol: newline-delimited JSON. {command, request_id} gets one reply {error, data,
request_id}; {event, ...} lines arrive in between.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
import socket
import tempfile
import time

SOCKET = os.path.join(os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}', 'obsidience-tv-player.sock')
# The player is local and answers within milliseconds; every call but play ends within this.
TIMEOUT = 0.5
# Measured 2026-10-12: a reduced live HLS playlist shows its first picture 0.9-2.7 s after
# loadfile, a full master with five variants 4.4-6.2 s (once more than 10 s).
START_LIMIT = 12.0
# Per-file options measured to start live HLS sooner: a short stream probe.
_FAST_START = {'demuxer-lavf-analyzeduration': '0.4', 'demuxer-lavf-probesize': '400000'}
# FFmpeg lets a playlist read from a file open only file, crypto and data addresses; this
# per-file option also admits the https entries of a playlist this module wrote itself.
_PLAYLIST_FILE = {'demuxer-lavf-o-append': 'protocol_whitelist=file,crypto,data,https,tls,tcp'}
_LINE_LIMIT = 1024 * 1024


class _Link:
    """One connection: commands with their replies, and the events read in between."""

    def __init__(self, sock):
        self.sock, self.buffer, self.events, self.ident = sock, b'', [], 0
        self.deadline = time.monotonic() + TIMEOUT

    def read(self, deadline):
        """The next message; TimeoutError past the deadline, ConnectionError when the player closed."""
        while b'\n' not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('The PC player did not answer')
            self.sock.settimeout(remaining)
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError('The PC player closed its connection')
            self.buffer += chunk
            if len(self.buffer) > _LINE_LIMIT:
                raise ValueError('PC player message exceeded its bound')
        line, self.buffer = self.buffer.split(b'\n', 1)
        message = json.loads(line)
        return message if isinstance(message, dict) else {}

    def command(self, *command):
        """One command, sent once: its reply's data, or ValueError when the player refuses it."""
        self.ident += 1
        self.sock.settimeout(TIMEOUT)
        self.sock.sendall((json.dumps({'command': command, 'request_id': self.ident}) + '\n').encode())
        while True:
            message = self.read(self.deadline)
            if 'error' in message and message.get('request_id') == self.ident:
                break
            self.events.append(message)
        if message['error'] != 'success':
            raise ValueError(f"The PC player refused {command[0]}: {str(message['error'])[:100]}")
        return message.get('data')

    def get(self, name):
        """A property, or None while the player has none (no video size before a frame is decoded)."""
        try:
            return self.command('get_property', name)
        except ValueError:
            return None


@contextmanager
def _open():
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.settimeout(TIMEOUT)
        sock.connect(SOCKET)
        yield _Link(sock)
    finally:
        sock.close()  # Cleanup paired with the acquisition.


def available():
    """Whether the player's socket exists and answers (one read)."""
    try:
        with _open() as link:
            link.command('get_property', 'idle-active')
        return True
    except (OSError, ValueError):
        return False


def state():
    """What the player shows now, or None when it does not answer.

    playback is idle (nothing loaded), loading (no picture yet), playing or paused; title is the
    one play gave it ('' for a file loaded any other way, whose own title would be its address);
    video is [width, height] once a frame was decoded.
    """
    try:
        with _open() as link:
            if link.command('get_property', 'idle-active'):
                return {'playback': 'idle', 'title': '', 'video': None}
            playback = ('paused' if link.command('get_property', 'pause') else
                        'loading' if link.command('get_property', 'core-idle') else 'playing')
            size = [link.get('width'), link.get('height')]
            return {'playback': playback, 'title': str(link.get('force-media-title') or '')[:160],
                    'video': size if all(isinstance(side, int) for side in size) else None}
    except (OSError, ValueError):
        return None


def play(source, title, cancel=None, limit=START_LIMIT):
    """Load one stream in place of whatever plays; True once the player shows its first picture.

    source is an https address, or the text of an HLS playlist. The player reads a playlist from
    a private file beside its socket, which exists only during this call (it is read once, when
    the stream opens). loadfile is sent once, with the title to report for it. False means the
    player accepted it but showed no picture within the limit, or gave the stream up: the caller
    reports playback as unverified. True proves that this stream started, not what its picture shows.
    """
    if source.startswith('#EXTM3U'):
        with tempfile.NamedTemporaryFile('w', prefix='obsidience-tv-', suffix='.m3u8',
                                         dir=os.path.dirname(SOCKET)) as playlist:
            playlist.write(source)
            playlist.flush()
            return _load(playlist.name, {**_FAST_START, **_PLAYLIST_FILE}, title, cancel, limit)
    if not source.startswith('https://'):
        raise ValueError('The PC player loads https streams only')
    return _load(source, _FAST_START, title, cancel, limit)


def _load(path, options, title, cancel, limit):
    with _open() as link:
        entry = (link.command('loadfile', path, 'replace', -1, {**options, 'force-media-title': title})
                 or {}).get('playlist_entry_id')
        deadline, started = time.monotonic() + limit, False
        while True:
            if cancel is not None and cancel.is_set():
                raise InterruptedError('TV command cancelled')
            try:
                event = link.events.pop(0) if link.events else link.read(min(deadline, time.monotonic() + .1))
            except TimeoutError:
                if time.monotonic() >= deadline:
                    return False
                continue
            name = event.get('event')
            # The replaced file's events come first; only this entry's own picture counts.
            if name == 'start-file' and event.get('playlist_entry_id') == entry:
                started = True
            elif started and name == 'playback-restart':
                return True
            elif started and name == 'end-file':
                return False


def pause(paused=True):
    """Set the pause flag once; True when the player's own readback shows it."""
    with _open() as link:
        link.command('set_property', 'pause', paused)
        return link.command('get_property', 'pause') is paused


def resume():
    return pause(False)


def stop():
    """End playback and return to the idle player; True when it reads back idle."""
    with _open() as link:
        link.command('stop')
        return link.command('get_property', 'idle-active') is True
