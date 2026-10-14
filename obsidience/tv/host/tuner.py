#!/usr/bin/python3
"""The TV tuner: the one owner of the TV player's IPC socket and of what that player shows.

A Pluto live channel is resolved by streamlink's Pluto plugin, used as a library in this one warm
process: it opens Pluto's web session, muxes the separate video and audio playlists with ffmpeg and
drops the advertisement segments. The muxed stream reaches the player (obsidience-tv-player.service,
an idle mpv) through a FIFO, on which a break is only a pause in the data; a plain https stream is
handed to the player as it is. While the plugin drops advertisements and the player has no
programme left to show, a break card covers the last frame (or the empty screen of a channel tuned
in during its break); no advertisement is ever played.

Control: newline-delimited JSON on the unix socket tuner.sock in $XDG_RUNTIME_DIR/obsidience-tv, one
reply per request, {"ok": true, "state": {...}} or {"ok": false, "error": "..."}.
  {"op": "play", "provider": "pluto", "channel": "<24 hex digits>", "title": "...", "wait": seconds}
  {"op": "play", "url": "https://...", "title": "...", "wait": seconds}
  {"op": "play", "provider": "local", <exact private catalogue source>, "title": "...", "wait": seconds}
  {"op": "pause"}  {"op": "resume"}  {"op": "stop"}  {"op": "state"}
play replaces whatever plays and answers once the new play left `loading` (its first picture, a
break it was tuned into, or failed), or after `wait` seconds (0 when absent). state: playback
idle | loading | playing | break | paused | failed, title, video [width, height] once a picture
shows, since (epoch seconds of the last playback change), player (whether the player answers),
provider and channel for a channel, reason for failed.
Local playback is loading until exact playlist identity and first-picture evidence agree,
then playing_verified. Its source DTO omits filesystem paths and includes an unpredictable
generation; finite EOF returns idle with an ended receipt, never a live-channel retry.

A stream address carries a session token: none is logged or returned, only titles and channel ids.
"""
from __future__ import annotations

import argparse
import errno
import glob
import json
import logging
import os
import queue
import re
import select
import signal
import socket
import socketserver
import subprocess
import sys
import threading
import time

from streamlink import Streamlink

# The tuner uses the same private source admission contract as the Harness, without
# importing its runtime or owning a second catalogue client.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from harness.media.config import MediaUnavailable, load_config
from harness.media.progress import PlaybackProgress
from harness.media.sources import admit

log = logging.getLogger('tuner')

RUNTIME = os.environ.get('XDG_RUNTIME_DIR') or f'/run/user/{os.getuid()}'
# The page address streamlink resolves, per provider, for a channel id. Pluto's plugin needs the
# id: the slug form of the address finds no streams (measured 2026-10-12).
PROVIDERS = {'pluto': 'https://pluto.tv/us/live-tv/{}'}
CHANNEL = re.compile(r'[0-9a-f]{24}')
# The player is local and answers within milliseconds.
TIMEOUT = 2.0
# How often ad filtering is read from the stream and the break card's clock is redrawn.
TICK = 0.25
# A stream that ends is opened once more with a fresh session. That second chance returns only
# after a stream has shown its picture for this long, so a channel that cannot play never loops.
HEALTHY = 60.0
# A channel tuned in at the tail of a break drops a segment or two before its programme starts:
# no break card for less than this.
TUNE_IN = 1.0
# The player opens a FIFO within milliseconds of loadfile.
FIFO_LIMIT = 5.0
# Per-file options measured to start a live stream sooner: a short stream probe.
_FAST_START = {'demuxer-lavf-analyzeduration': '0.4', 'demuxer-lavf-probesize': '400000'}
# After a break a channel restarts at its live edge and its segments (5-6 s on Pluto) arrive one
# at a time. Resuming on the first, as mpv does by default (1 s buffered), left under a second of
# margin and playback stalled twice in the next minute (measured). Eight seconds takes two. The
# first picture waits for the same margin: a channel tuned in during a break starts as thin.
_CUSHION = {'cache-pause-wait': '8', 'cache-pause-initial': 'yes'}
_LINE_LIMIT = 1024 * 1024
# Exact local seeks accept a fresh settled position within half a second. No
# keyframe fallback or second seek follows an unverified/uncertain outcome.
SEEK_TOLERANCE = 0.5
VOD_LIMIT = 5.0
# Initial resume readback is taken after the first picture. Five seconds allows
# normal decode/startup advancement; it never authorizes a correction seek.
START_TOLERANCE = 5.0
START_LIMIT = 30.0  # An owned resume verifier waits this long for its first picture.


class _Fault(Exception):
    """Why one attempt to play a channel ended, in words that never hold an address."""


class Player:
    """mpv's JSON IPC: one connection, opened when a command needs it, one command in flight.

    Replies and events arrive on a reader thread. An event handler must never send a command: it
    runs on that thread, which would then wait for a reply only it can read.
    """
    OBSERVED = ('pause', 'paused-for-cache', 'width', 'height', 'time-pos', 'duration')

    def __init__(self, path, on_event):
        self.path, self.on_event = path, on_event
        self._sending = threading.Lock()
        self._replies = queue.SimpleQueue()
        self._sock = None
        self._ident = 0
        self.generation = 0

    def reach(self):
        """Whether the player answers, connecting when needed."""
        try:
            self.command('get_property', 'idle-active')
            return True
        except (OSError, ValueError):
            return False

    def command(self, *command):
        """One command, sent once: its reply's data. OSError when the player does not answer,
        ValueError when it refuses the command."""
        with self._sending:
            if self._sock is None:
                self._connect()
            return self._ask(command)

    def bound_command(self, generation, *command, timeout=TIMEOUT):
        """One command on the already-bound connection, never reconnecting."""
        with self._sending:
            if self._sock is None or self.generation != generation:
                raise ConnectionError('The local player connection changed')
            result = self._ask(command, timeout)
            if self._sock is None or self.generation != generation:
                raise ConnectionError('The local player connection changed')
            return result

    def _connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(TIMEOUT)
            sock.connect(self.path)
            sock.settimeout(None)
        except OSError:
            sock.close()
            raise
        self.generation += 1
        self._sock = sock
        self.on_event({'event': 'connected'}, self.generation)
        threading.Thread(target=self._read, args=(sock, self.generation), name='player-ipc', daemon=True).start()
        for ident, name in enumerate(self.OBSERVED, 1):
            self._ask(('observe_property', ident, name))

    def _ask(self, command, timeout=TIMEOUT):
        sock = self._sock
        if sock is None:
            raise ConnectionError('The player closed its connection')
        self._ident += 1
        deadline = time.monotonic() + timeout
        data = memoryview((json.dumps({'command': command, 'request_id': self._ident}) + '\n').encode())
        try:
            while data:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('The player did not accept the command')
                try:
                    sent = sock.send(data, socket.MSG_DONTWAIT)
                    if sent == 0:
                        raise ConnectionError('The player closed its connection')
                    data = data[sent:]
                except BlockingIOError:
                    if not select.select([], [sock], [], remaining)[1]:
                        raise TimeoutError('The player did not accept the command')
        except (OSError, ValueError):
            # A partial JSON write cannot precede another command on this stream.
            # End this connection; the uncertain command is never resent.
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            raise
        while True:
            try:
                origin, reply = self._replies.get(timeout=max(0.0, deadline - time.monotonic()))
            except queue.Empty:
                raise TimeoutError('The player did not answer') from None
            if origin is not sock:
                continue  # Left over from an earlier connection.
            if reply is None:
                raise ConnectionError('The player closed its connection')
            if reply.get('request_id') == self._ident:
                break
        if reply.get('error') != 'success':
            raise ValueError(f"The player refused {command[0]}: {str(reply.get('error'))[:100]}")
        return reply.get('data')

    def _read(self, sock, generation):
        buffer = b''
        try:
            while chunk := sock.recv(65536):
                *lines, buffer = (buffer + chunk).split(b'\n')
                if len(buffer) > _LINE_LIMIT:
                    break
                for line in lines:
                    message = json.loads(line)
                    if 'event' in message:
                        self.on_event(message, generation)
                    else:
                        self._replies.put((sock, message))
        except (OSError, ValueError):
            pass
        finally:
            if self._sock is sock:
                self._sock = None
            sock.close()  # Cleanup paired with the connection; observed properties and overlays end with it.
            self._replies.put((sock, None))
            self.on_event({'event': 'disconnected'}, generation)

    def close(self):
        sock = self._sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)  # The reader thread closes it.
            except OSError:
                pass


class Play:
    """One thing the tuner was asked to play, and what was acquired for it."""

    def __init__(self, number, title, provider=None, channel=None, url=None, local=None, identity=None,
                 local_config=None, generation=None, start_seconds=None):
        self.number, self.title, self.provider, self.channel, self.url = number, title, provider, channel, url
        self.local, self.identity = local, identity
        self.local_config = local_config
        self.generation = generation if local is not None else None
        self.verified = False
        self.player_generation = None
        self.progress = None
        self.last_vod = None
        self.final_vod = None
        self.latest_position = None
        self.start_seconds = 0 if start_seconds is None else start_seconds
        self.start_verified = start_seconds is None
        self.start_readback = None
        self.start_thread = None
        # For the journal: a title and a channel id, never an address.
        self.name = (f'{title!r} ({provider} {channel})' if channel else
                     f'{title!r} (local media)' if local is not None else f'{title!r} (address)')
        self.requested = time.monotonic()
        self.cancelled = threading.Event()
        self.phase = 'loading'  # loading (no picture yet), playing or failed
        self.reason = ''
        self.entry = None       # The player's playlist entry of this play's file.
        self.picture = None     # When the current attempt showed its first picture (monotonic).
        self.filtering = None   # Since when the stream drops advertisement segments (monotonic).
        self.breaking = None    # Since when the break card shows (monotonic).
        self.readers = ()       # The stream's readers that report ad filtering, from the moment they open.
        self.thread = None
        self._closing = threading.Lock()
        self._stream = None

    def adopt(self, stream):
        """Take ownership of an opened stream; a play cancelled meanwhile closes it at once."""
        with self._closing:
            if not self.cancelled.is_set():
                self._stream = stream
                return
        _close(stream)
        raise _Fault('cancelled')

    def close_stream(self):
        """Close the stream (its downloads and its muxer) exactly once; a blocked read then returns.

        A stream that is still opening has only its readers: closing them ends its wait for data.
        """
        with self._closing:
            stream, self._stream = self._stream, None
            if stream is not None:
                _close(stream)
            else:
                for reader in self.readers:
                    _quietly(reader.close)

    def close_local(self):
        with self._closing:
            if self.local is not None:
                self.local.close()


def _close(stream):
    """Close a stream and reap its muxer, letting through the writers streamlink would wait for.

    A muxed stream hands each input to ffmpeg through a named pipe, and each writer first waits
    for ffmpeg to open its pipe. ffmpeg opens its second input only after it read the first, so a
    channel left during its advertisement break has a writer that would wait forever, and close()
    a minute for it (measured). A reading end held here lets that writer through; it is drained so
    that no writer blocks on a full pipe either.
    """
    ends = []
    for pipe in getattr(stream, 'pipes', ()):
        try:
            ends.append(os.open(pipe.path, os.O_RDONLY | os.O_NONBLOCK))
        except OSError:
            pass  # Already removed by its writer.
    closing = threading.Thread(target=_quietly, args=(stream.close,), name='stream-close')
    closing.start()
    while closing.is_alive():
        for end in ends:
            try:
                while os.read(end, 65536):
                    pass
            except OSError:
                pass  # Nothing to read now.
        closing.join(0.02)
    for end in ends:
        os.close(end)
    # streamlink kills its ffmpeg muxer without waiting for it; the wait reaps the process.
    process = getattr(stream, 'process', None)
    if process is not None:
        _quietly(process.wait, 5)


def _quietly(call, *arguments):
    try:
        call(*arguments)
    except Exception as error:  # Only the type: the text may hold an address.  # noqa: BLE001
        log.warning('%s: %s', getattr(call, '__qualname__', 'cleanup'), type(error).__name__)


def _end(view):
    """End the idle/break view at once (its whole process group) and reap it.

    Killed, not asked: a view holds only a capture and a window, and the channel's picture
    returns the moment that window is gone (a player asked to quit kept it for a second).
    """
    try:
        os.killpg(view.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass  # Its group already ended.
    _quietly(view.wait, 3)


def _card(title, elapsed):
    """The break card as ASS events on mpv's 720-line canvas: a dark veil over the last frame, three lines."""
    minutes, seconds = divmod(int(elapsed), 60)
    title = re.sub(r'[\\{}\x00-\x1f]', ' ', title)  # A title is listing text, never ASS markup.
    return ('{\\an7\\pos(0,0)\\bord0\\shad0\\1c&H000000&\\1a&H18&\\p1}m 0 0 l 8000 0 8000 8000 0 8000{\\p0}\n'
            '{\\an5\\bord0\\shad0\\1c&HFFFFFF&\\fs60\\b1}' + title + '{\\b0\\fs18}\\N \\N'
            '{\\fs34}Commercial break\\N{\\fs26\\1c&HB0B0B0&}Resuming automatically  ·  '
            f'{minutes}:{seconds:02d}')


class Tuner:
    def __init__(self, directory, player, break_view=None):
        self.directory, self.break_view = directory, break_view
        self.player = Player(player, self._event)
        # The state below; notified on every change. Never held while the player is commanded:
        # the reader thread needs it for the events that precede a reply.
        self.lock = threading.Condition()
        # Held while the current play is replaced and whenever the player is told to load, stop or
        # pause, so only the current play ever reaches the player.
        self.control = threading.Lock()
        # One user at a time of the warm streamlink session and plugin.
        self.resolving = threading.Lock()
        self.plugins = {}
        self.play = None
        self.plays = 0
        self.properties = {}
        self.entry = None  # The playlist entry the player started last.
        self.restart_entry = None  # A first picture may precede the loadfile reply.
        self.finished = (None, None)  # The entry it ended last, and why.
        self.local_files = {}  # Keep admitted descriptors through matching unload events.
        self.reporters = set()  # Includes a finite file's final report after its descriptor closes.
        self.ended = None  # A bounded terminal receipt for the most recent finite local file.
        self.ended_progress = None
        self.playback, self.since = 'idle', time.time()
        self.closed = False
        self.presenter = threading.Thread(target=self._present, name='presenter', daemon=True)
        self.presenter.start()
        threading.Thread(target=self._warm, name='warm-up', daemon=True).start()

    # State

    def _refresh(self):
        """Derive playback from the play, the player's properties and the stream's ad filter (lock held)."""
        play, paused, now = self.play, self.properties.get('pause') is True, time.monotonic()
        starved = self.properties.get('paused-for-cache') is True
        if play is not None and play.phase != 'failed':
            # streamlink's own state: a reader is paused from the first advertisement segment it
            # drops until it writes programme again.
            filtering = any(reader.is_paused() for reader in play.readers)
            if filtering != (play.filtering is not None):
                play.filtering = now if filtering else None
                log.info('%s: advertisements %s', play.name, 'begin, dropping them' if filtering else 'over')
            # When advertisements begin the player still holds some seconds of programme, so the
            # break starts once nothing of it is left to show and ends when programme plays again.
            # A channel tuned in during its break has no picture yet: its break starts at once.
            showing = play.phase == 'playing' and not starved
            if play.breaking is None:
                if (filtering and not showing and not paused
                        and (play.phase == 'playing' or now - play.filtering >= TUNE_IN)):
                    play.breaking = now
            elif not filtering and showing:
                play.breaking = None
        playback = ('idle' if play is None else 'failed' if play.phase == 'failed' else
                    'paused' if paused and play.phase == 'playing' else
                    'break' if play.breaking is not None else
                    'loading' if play.phase == 'loading' or starved
                    or (play.local is not None and not play.start_verified) else
                    'playing_verified' if play.local is not None else 'playing')
        if playback != self.playback:
            log.info('%s: %s -> %s', play.name if play is not None else 'player', self.playback, playback)
            self.playback, self.since = playback, time.time()
        self.lock.notify_all()

    def _state(self, reached):
        """Current public metadata (lock held); never sends a player command."""
        self._refresh()
        play = self.play
        size = [self.properties.get('width'), self.properties.get('height')]
        state = {'playback': self.playback, 'title': play.title if play is not None else '',
                 'video': size if play is not None and play.phase == 'playing'
                 and all(isinstance(side, int) for side in size) else None,
                 'since': round(self.since, 1), 'player': reached}
        if play is not None and play.channel:
            state.update(provider=play.provider, channel=play.channel)
        if play is not None and play.local is not None:
            state.update(provider='local', generation=play.generation, source=play.identity,
                         verification='verified' if (play.verified and play.picture is not None
                         and play.start_verified
                         and play.phase == 'playing' and play.entry == self.entry
                         and play.player_generation == self.player.generation
                         and self.player._sock is not None) else 'unverified')
            if play.progress is not None:
                state['progress'] = play.progress.snapshot()
            if play.start_readback is not None:
                state['start'] = dict(play.start_readback)
        if self.ended is not None:
            state['ended'] = dict(self.ended)
            if self.ended_progress is not None:
                state['ended']['progress'] = self.ended_progress.snapshot()
        if play is not None and play.phase == 'failed':
            state['reason'] = play.reason
        return state

    def state(self):
        with self.control:
            reached = self.player.reach()
            with self.lock:
                play = self.play
                ready = (play is not None and play.local is not None
                         and play.phase == 'playing' and play.verified and play.start_verified)
            vod = None
            if reached and ready:
                try:
                    vod = self._read_vod(play, time.monotonic() + VOD_LIMIT)
                except (OSError, ValueError):
                    pass  # State stays available; missing fresh VOD evidence grants no control.
            with self.lock:
                state = self._state(reached)
                if self.play is play and vod is not None:
                    state['vod'] = vod
                return state

    def _check_local(self, play, ready=True):
        """Exact current source/entry/connection before and after each bounded read (lock held)."""
        if (play is None or self.play is not play or play.local is None or play.phase == 'failed'
                or play.entry is None or self.entry != play.entry
                or play.player_generation != self.player.generation or self.player._sock is None
                or (ready and (play.phase != 'playing' or not play.verified or play.picture is None))):
            raise ValueError('local playback is not the exact verified current source')

    def _vod_command(self, play, deadline, *command):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('The local VOD readback deadline expired')
        with self.lock:
            self._check_local(play)
        result = self.player.bound_command(play.player_generation, *command,
                                           timeout=min(TIMEOUT, remaining))
        with self.lock:
            self._check_local(play)
        return result

    def _vod_playlist(self, play, deadline):
        playlist = self._vod_command(play, deadline, 'get_property', 'playlist')
        path = f'/proc/{os.getpid()}/fd/{play.local.fd}'
        if (not isinstance(playlist, list) or len(playlist) != 1
                or not isinstance(playlist[0], dict) or playlist[0].get('id') != play.entry
                or playlist[0].get('filename') != path
                or not (playlist[0].get('current') is True or playlist[0].get('playing') is True)):
            raise ValueError('the exact local playlist entry could not be verified')

    def _read_vod(self, play, deadline):
        """Fresh finite-file readback between two exact playlist checks (control held)."""
        self._vod_playlist(play, deadline)
        values = {}
        for name in ('time-pos', 'duration', 'seekable', 'pause', 'seeking', 'track-list'):
            try:
                values[name] = self._vod_command(play, deadline, 'get_property', name)
            except ValueError as error:
                if name not in ('time-pos', 'duration') or 'property unavailable' not in str(error):
                    raise
                values[name] = None
        self._vod_playlist(play, deadline)
        for name in ('pause', 'seeking', 'seekable'):
            if type(values[name]) is not bool:
                raise ValueError('the local player did not return bounded VOD state')
        tracks = values['track-list']
        if not isinstance(tracks, list) or len(tracks) > 128:
            raise ValueError('the local track list is unavailable or exceeded its bound')
        projected = {'audio': [], 'subtitle': []}
        selected = {'audio': None, 'subtitle': None}
        for track in tracks:
            if not isinstance(track, dict) or track.get('type') not in ('audio', 'sub'):
                continue
            kind = 'audio' if track['type'] == 'audio' else 'subtitle'
            ident = track.get('id')
            if (type(ident) is not int or not 0 < ident <= 2147483647 or track.get('external') is True
                    or any(item['id'] == ident for item in projected[kind])):
                raise ValueError('the local track identity is unsupported')
            primary = track.get('selected') is True and track.get('main-selection', 0) == 0
            if primary:
                if selected[kind] is not None:
                    raise ValueError('the local track selection is ambiguous')
                selected[kind] = ident
            text = lambda key, bound: (re.sub(r'[\x00-\x1f\x7f]', ' ', track[key])[:bound]
                                       if isinstance(track.get(key), str) else '')
            projected[kind].append({'id': ident, 'title': text('title', 160),
                                    'language': text('lang', 32), 'selected': primary,
                                    'default': track.get('default') is True})
        def seconds(value):
            return (round(float(value), 3) if type(value) in (int, float)
                    and 0 <= value <= 1_000_000_000 else None)
        vod = {'position': seconds(values['time-pos']), 'duration': seconds(values['duration']),
               'seekable': values['seekable'], 'paused': values['pause'], 'seeking': values['seeking'],
               'audio_track': selected['audio'], 'subtitle_track': selected['subtitle'],
               'tracks': projected, 'observed_at': round(time.time(), 3)}
        with self.lock:
            self._check_local(play)
            play.last_vod = dict(vod)
            if vod['position'] is not None:
                play.latest_position = (vod['position'], time.monotonic())
            self.properties['pause'] = vod['paused']
            self._refresh()
        return vod

    def _progress_current(self, play):
        with self.lock:
            return (self.play is play and not play.cancelled.is_set() and play.phase == 'playing'
                    and play.verified and play.start_verified and play.player_generation == self.player.generation)

    def _sample_progress(self, play):
        # A control operation owns this lock first; the reporter never blocks it
        # and keeps no stale position waiting to be replayed afterwards.
        if not self.control.acquire(timeout=.2):
            return None
        try:
            with self.lock:
                self._check_local(play)
            return self._read_vod(play, time.monotonic() + VOD_LIMIT)
        finally:
            self.control.release()

    def _final_progress(self, play):
        """Final evidence only, never extrapolated from duration (lock held)."""
        if play.final_vod is not None:
            return dict(play.final_vod)
        latest = play.latest_position
        if latest is None or time.monotonic() - latest[1] > 2:
            return None
        return {**(play.last_vod or {}), 'position': latest[0], 'observed_at': round(time.time(), 3)}

    def _local_control(self, message):
        """One bound VOD target write, then reads only until its postcondition settles."""
        op = message.get('op')
        fields = {'op', 'generation', 'source'} | ({'position'} if op == 'seek' else
                                                 {'kind', 'track_id'} if op == 'track' else set())
        generation, source = message.get('generation'), message.get('source')
        if (set(message) != fields or not isinstance(generation, str)
                or not re.fullmatch(r'[0-9a-f]{32}', generation) or not isinstance(source, dict)):
            raise ValueError('local VOD takes the exact observed generation and source')
        if op == 'seek':
            position = message['position']
            if type(position) not in (int, float) or not 0 <= position <= 1_000_000_000:
                raise ValueError('local seek takes a finite nonnegative absolute position')
        elif op == 'track':
            kind, track_id = message['kind'], message['track_id']
            if kind not in ('audio', 'subtitle') or (track_id is not None
                    and (type(track_id) is not int or not 0 < track_id <= 2147483647)):
                raise ValueError('local track takes audio or subtitle and an exact id or null for off')
        deadline = time.monotonic() + VOD_LIMIT
        with self.control:
            with self.lock:
                play = self.play
                self._check_local(play)
                if not play.start_verified:
                    raise ValueError('the local saved start position is still unverified')
                if (play.generation, play.identity) != (generation, source):
                    raise ValueError('local playback changed before VOD control')
            vod = self._read_vod(play, deadline)
            if op == 'vod-state':
                with self.lock:
                    state = self._state(True)
                return {**state, 'vod': vod}
            if op in ('pause', 'resume'):
                target = op == 'pause'
                matches = lambda value: value['paused'] is target
                command = ('set_property', 'pause', target)
            elif op == 'seek':
                if (not vod['seekable'] or vod['duration'] is None or vod['duration'] <= 0
                        or position >= vod['duration']):
                    raise ValueError('local seek requires a seekable finite file and a position before EOF')
                matches = lambda value: (not value['seeking'] and value['position'] is not None
                                         and abs(value['position'] - position) <= SEEK_TOLERANCE)
                command = ('seek', position, 'absolute+exact')
            else:
                if track_id is not None and not any(t['id'] == track_id for t in vod['tracks'][kind]):
                    raise ValueError('the exact track is not in the current local file')
                matches = lambda value: value[kind + '_track'] == track_id
                command = ('set_property', 'aid' if kind == 'audio' else 'sid',
                           track_id if track_id is not None else 'no')
            changed = not matches(vod)
            if changed:
                play.local.validate()
                self._vod_playlist(play, deadline)
                self._vod_command(play, deadline, *command)  # Exactly one target write; no retries.
                while True:
                    vod = self._read_vod(play, deadline)
                    if matches(vod):
                        break
                    with self.lock:
                        self.lock.wait(min(.05, max(0, deadline - time.monotonic())))
            with self.lock:
                self._check_local(play)
                state = self._state(True)
            control = {'action': op, 'verified': True, 'changed': changed}
            if op == 'seek':
                control.update(position=position, tolerance=SEEK_TOLERANCE)
            return {**state, 'vod': vod, 'control': control}

    def _event(self, event, generation):
        """The player's events, on its reader thread: state only, never a command."""
        name = event.get('event')
        with self.lock:
            if generation != self.player.generation:
                return  # An obsolete connection cannot change the replacement's state.
            play = self.play
            if name == 'connected':
                self.properties.clear()
                self.entry, self.restart_entry, self.finished = None, None, (None, None)
                if play is not None and play.local is not None and play.phase != 'loading':
                    play.phase, play.reason = 'failed', 'the local player connection changed'
                    if play.progress is not None:
                        play.progress.disable('progress_player_connection_changed')
                for number, held in list(self.local_files.items()):
                    if held is not play or held.phase != 'loading':
                        held.close_local()
                        del self.local_files[number]
            elif name == 'property-change':
                self.properties[event.get('name')] = event.get('data')
                value = event.get('data')
                if (event.get('name') == 'time-pos' and type(value) in (int, float)
                        and 0 <= value <= 1_000_000_000 and play is not None and play.local is not None
                        and play.phase == 'playing' and play.verified and play.entry == self.entry
                        and play.player_generation == generation):
                    play.latest_position = (float(value), time.monotonic())
            elif name == 'start-file':
                self.entry = event.get('playlist_entry_id')
                self.restart_entry = None
            elif name == 'playback-restart':
                # The replaced file's events come first; only this play's own picture counts.
                self.restart_entry = self.entry
                self._picture()
            elif name == 'end-file':
                self.finished = (event.get('playlist_entry_id'), event.get('reason'))
                self._finish()
            elif name == 'disconnected':
                self.properties.clear()
                self.entry = None
                self.restart_entry = None
                for held in self.local_files.values():
                    held.close_local()
                self.local_files.clear()
                if play is not None and (play.url or play.local is not None):
                    play.phase, play.reason = 'failed', 'the player closed its connection'
                    if play.progress is not None:
                        play.progress.disable('progress_player_disconnected')
            else:
                return
            self._refresh()

    def _picture(self):
        """Admit a first picture only for the assigned entry (lock held)."""
        play = self.play
        if (play is not None and play.phase == 'loading' and play.entry is not None
                and play.entry == self.entry == self.restart_entry
                and (play.local is None or play.verified)):
            play.phase, play.picture = 'playing', time.monotonic()
            if play.progress is not None and play.start_verified:
                play.progress.start()  # Worker owns HTTP; this callback never waits for it.
            log.info('%s: picture %.1f s after the request', play.name, play.picture - play.requested)

    def _finish(self):
        """A finite source the player finished or gave up ends its play (lock held).

        A channel's own thread sees its stream end. The player can end a file before the play
        knows its entry, so both the event and the loaded entry come through here.
        """
        play, (entry, reason) = self.play, self.finished
        for number, held in list(self.local_files.items()):
            if held.entry is not None and held.entry == entry:
                if held.progress is not None:
                    if reason in ('stop', 'eof'):
                        held.progress.finish(self._final_progress(held), 'stopped' if reason == 'stop' else 'ended')
                    else:
                        held.progress.disable('progress_final_outcome_unverified')
                held.close_local()
                del self.local_files[number]
                if (self.ended is not None and self.ended.get('generation') == held.generation
                        and self.ended.get('outcome') == 'stopping'):
                    self.ended['outcome'] = 'stopped' if reason in ('stop', 'eof') else 'failed'
        if play is not None and play.local is not None and play.entry is not None and play.entry == entry:
            self.ended = {'generation': play.generation, 'source': play.identity,
                          'outcome': 'ended' if reason == 'eof' else 'failed'}
            self.ended_progress = play.progress
            if reason == 'eof':
                self.play = None
            else:
                play.phase, play.reason = 'failed', 'local media playback ended without verified completion'
            return
        if play is not None and play.url and play.entry is not None and play.entry == entry:
            if reason == 'eof':
                self.play = None
            elif reason == 'error':
                play.phase, play.reason = 'failed', 'the player could not play this address'

    def _present(self):
        """Show the existing graph mirror while idle or in a commercial break.

        One presenter owns the view. Loading, playing and paused content keep their
        own picture; stop and finite EOF return to the idle graph without loading media.
        The break card remains the fallback during advertisements.
        """
        shown, mode, view = None, None, None
        try:
            while True:
                with self.lock:
                    self.lock.wait(TICK)
                    if self.closed:
                        return
                    self._refresh()
                    play = self.play
                    card = (_card(play.title, time.monotonic() - play.breaking)
                            if play is not None and self.playback == 'break' else None)
                    wanted = 'break' if card is not None else 'idle' if play is None else None
                    title = play.title if play is not None else ''
                if wanted != mode:
                    mode = wanted
                    if view is not None:
                        _end(view)
                        view = None
                        try:
                            # The view's window took the full screen from the player's, and the
                            # compositor draws an ordinary window on every frame where it hands a
                            # fullscreen one straight to the output (measured: 17% of the GPU and a
                            # skipped frame a second on the television).
                            self.player.command('set_property', 'fullscreen', True)
                        except (OSError, ValueError):
                            pass
                    if mode is not None and self.break_view:
                        try:
                            view = subprocess.Popen([self.break_view, title, mode], stdin=subprocess.DEVNULL,
                                                    start_new_session=True)
                        except OSError as error:
                            log.warning('%s graph view did not start (%s)', mode, type(error).__name__)
                if card != shown:
                    try:
                        self.player.command('osd-overlay', 0, 'ass-events' if card else 'none', card or '')
                        shown = card
                    except (OSError, ValueError):
                        shown = None  # An overlay ends with the connection that drew it.
        finally:
            if view is not None:
                _end(view)  # Cleanup paired with its start, whatever ended the presenter.

    # Control

    def request(self, message):
        op = message.get('op')
        if op in ('vod-state', 'seek', 'track') or (op in ('pause', 'resume')
                and ('generation' in message or 'source' in message)):
            return self._local_control(message)
        if op == 'play':
            title, wait = message.get('title'), message.get('wait', 0)
            if not isinstance(title, str) or not title.strip() or len(title) > 160:
                raise ValueError('play takes a title of 1-160 characters')
            if isinstance(wait, bool) or not isinstance(wait, (int, float)) or not 0 <= wait <= 60:
                raise ValueError('wait takes 0-60 seconds')
            if message.get('provider') == 'local':
                local_fields = {'op', 'provider', 'root_id', 'relative_path', 'revision',
                                'catalogue_instance', 'item_id', 'media_source_id', 'source_revision',
                                'title', 'wait', 'generation', 'start_seconds'}
                if set(message) - local_fields:
                    raise ValueError('local media takes one exact source identity')
                generation = message.get('generation')
                if not isinstance(generation, str) or not re.fullmatch(r'[0-9a-f]{32}', generation):
                    raise ValueError('local media takes one exact request generation')
                start_seconds = message.get('start_seconds')
                if 'start_seconds' in message and (type(start_seconds) not in (int, float)
                        or not 0 <= start_seconds <= 1_000_000_000):
                    raise ValueError('local start takes a finite nonnegative saved position')
                descriptor = {key: message.get(key) for key in ('provider', 'root_id', 'relative_path', 'revision')}
                identity = {key: message.get(key) for key in
                            ('provider', 'root_id', 'revision', 'catalogue_instance', 'item_id',
                             'media_source_id', 'source_revision')}
                if any(not isinstance(identity[key], str) or not identity[key]
                       or len(identity[key]) > 256 or re.search(r'[\x00-\x1f]', identity[key])
                       for key in identity):
                    raise ValueError('local media takes exact bounded source identifiers')
                with self.lock:
                    if len(self.local_files) >= 8:
                        raise ValueError('local media has unresolved player unloads')
                config = load_config()
                if not config.get('enabled'):
                    raise ValueError('local media is disabled')
                if identity['catalogue_instance'] != (config.get('catalogue') or {}).get('instance_id'):
                    raise ValueError('local media catalogue identity changed')
                local = admit(config, descriptor)
                try:
                    self._start(title, {'provider': 'local', 'local': local, 'identity': identity,
                                        'local_config': config, 'generation': generation,
                                        'start_seconds': start_seconds}, wait)
                except Exception:
                    with self.lock:
                        adopted = any(held.local is local for held in self.local_files.values())
                    if not adopted:
                        local.close()
                    raise
                return self.state()
            if 'url' in message:
                if 'provider' in message or 'channel' in message:
                    raise ValueError('play takes one source')
                url = message['url']
                if (not isinstance(url, str) or not url.startswith('https://') or len(url) > 8000
                        or re.search(r'[\s\x00-\x1f"\'`\\<>]', url)):
                    raise ValueError('play takes an https address')
                source = {'url': url}
            else:
                provider, channel = message.get('provider'), message.get('channel')
                if provider not in PROVIDERS or not isinstance(channel, str) or not CHANNEL.fullmatch(channel):
                    raise ValueError('play takes a provider (pluto) and its 24-digit channel id, or an https address')
                source = {'provider': provider, 'channel': channel}
            self._start(title, source, wait)
        elif op in ('pause', 'resume'):
            with self.control:
                with self.lock:
                    if self.play is None or self.play.phase == 'failed':
                        raise ValueError('Nothing is playing')
                    if self.play.local is not None:
                        raise ValueError('local pause and resume require identity-bound VOD controls')
                self.player.command('set_property', 'pause', op == 'pause')
                paused = self.player.command('get_property', 'pause')
            with self.lock:
                self.properties['pause'] = paused  # The player's own readback; its event confirms it.
                self._refresh()
        elif op == 'stop':
            expected = None
            if 'generation' in message or 'source' in message:
                generation, source = message.get('generation'), message.get('source')
                if (set(message) != {'op', 'generation', 'source'}
                        or not isinstance(generation, str) or not re.fullmatch(r'[0-9a-f]{32}', generation)
                        or not isinstance(source, dict)):
                    raise ValueError('local stop takes the exact observed generation and source')
                expected = (generation, source)
            stopped_play = self._replace(None, expected=expected)
            if expected is not None:
                with self.lock:
                    confirmed = self.lock.wait_for(
                        lambda: self.ended is None or self.ended.get('generation') != expected[0]
                        or self.ended.get('outcome') != 'stopping', timeout=TIMEOUT)
                    stopped = (confirmed and self.ended is not None
                               and self.ended.get('generation') == expected[0]
                               and self.ended.get('outcome') == 'stopped')
                if (not stopped or self.player.bound_command(stopped_play.player_generation,
                        'get_property', 'idle-active') is not True):
                    raise ValueError('the player did not verify the exact local stop')
        elif op != 'state':
            raise ValueError('op is play, pause, resume, stop or state')
        return self.state()

    def _start(self, title, source, wait):
        with self.lock:
            self.plays += 1
            play = Play(self.plays, title, **source)
            if play.local is not None:
                play.progress = PlaybackProgress(play.local_config, play.identity, play.generation,
                                                 lambda: self._sample_progress(play),
                                                 lambda: self._progress_current(play))
        log.info('%s: play', play.name)
        self._replace(play)
        if play.local is not None and not play.start_verified:
            with self.lock:
                if self.play is play and not self.closed:
                    play.start_thread = threading.Thread(target=self._complete_start, args=(play,),
                                                         name=f'start-{play.number}')
                    play.start_thread.start()  # Play owns it; replacement/shutdown drains it.
        with self.lock:
            self.lock.wait_for(lambda: self.closed or self.play is not play
                               or self.playback != 'loading', timeout=wait)

    def _complete_start(self, play):
        """Continue this start after a short caller wait; never reload or seek."""
        with self.lock:
            self.lock.wait_for(lambda: self.closed or self.play is not play or play.cancelled.is_set()
                               or play.phase != 'loading', timeout=START_LIMIT)
            if self.closed or self.play is not play or play.cancelled.is_set() or play.phase == 'failed':
                return
            ready = play.phase == 'playing'
        if ready:
            self._verify_start(play)
            return
        with self.control:
            with self.lock:
                if self.closed or self.play is not play or play.cancelled.is_set():
                    return
                play.phase, play.reason = 'failed', 'the saved start did not show a first picture in time'
                self._refresh()
            try:
                self.player.bound_command(play.player_generation, 'stop')
            except (OSError, ValueError):
                pass  # One cleanup only; an uncertain start is never replayed.

    def _verify_start(self, play):
        """Fresh exact-generation proof on the owned start worker, never the IPC reader."""
        with self.control:
            with self.lock:
                if self.closed or self.play is not play or play.cancelled.is_set():
                    return
            try:
                deadline = time.monotonic() + VOD_LIMIT
                while True:
                    vod = self._read_vod(play, deadline)
                    if (vod['duration'] is None or not 0 <= play.start_seconds < vod['duration']
                            or (play.start_seconds > 0 and not vod['seekable'])):
                        raise ValueError('the saved start position could not be verified in this file')
                    if (vod['position'] is not None and not vod['seeking']
                            and abs(vod['position'] - play.start_seconds) <= START_TOLERANCE):
                        break
                    with self.lock:
                        self.lock.wait(min(.05, max(0, deadline - time.monotonic())))
                with self.lock:
                    self._check_local(play)
                    play.start_verified = True
                    play.start_readback = {'requested': play.start_seconds, 'position': vod['position'],
                                           'tolerance': START_TOLERANCE, 'verified': True,
                                           'observed_at': vod['observed_at']}
                    if play.progress is not None:
                        play.progress.start()
                    self._refresh()
            except (OSError, ValueError):
                with self.lock:
                    current = self.play is play
                    if current:
                        play.phase, play.reason = 'failed', 'the saved start position could not be verified'
                        self._refresh()
                if current:
                    try:
                        self.player.bound_command(play.player_generation, 'stop')
                    except (OSError, ValueError):
                        pass  # Uncertain cleanup is never replayed; there is no correction seek/load.

    def _replace(self, play, wait=False, expected=None):
        """Make play (or nothing) the current play and release everything the previous one held.

        Closing a stream waits for its downloads in flight (0.4-3 s measured), so the previous
        play is released beside the new one's start; wait makes the caller see it through.
        """
        with self.control:
            if play is not None and play.local is not None:
                # Last admission check happens before the existing picture is replaced.
                if load_config() != play.local_config:
                    raise MediaUnavailable('media_config_changed')
                play.local.validate()
            with self.lock:
                prior = self.play
                if expected is not None and (prior is None or (prior.generation, prior.identity) != expected):
                    raise ValueError('local playback changed before stop')
            if prior is not None and prior.local is not None and prior.progress is not None:
                try:
                    prior.final_vod = self._read_vod(prior, time.monotonic() + VOD_LIMIT)
                except (OSError, ValueError):
                    prior.progress.disable('final_position_unavailable')
            with self.lock:
                if expected is not None:
                    current = self.play
                    if (current is None or current.local is None
                            or (current.generation, current.identity) != expected):
                        raise ValueError('local playback changed before stop')
                    self._check_local(current, ready=False)
                if play is not None and self.closed:
                    # Admission can finish beside shutdown. Release its acquired
                    # fd without reconnecting to or loading the player.
                    play.close_local()
                    raise MediaUnavailable('tuner_closed')
                if play is not None and play.local is not None and len(self.local_files) >= 8:
                    raise ValueError('local media has unresolved player unloads')
                old, self.play = self.play, play
                self.ended = ({'generation': old.generation, 'source': old.identity,
                               'outcome': 'stopping' if expected is not None else 'stopped'}
                              if play is None and old is not None and old.local is not None else None)
                self.ended_progress = old.progress if self.ended is not None else None
                if play is not None and play.local is not None:
                    self.local_files[play.number] = play
                    self.reporters = {reporter for reporter in self.reporters
                                      if reporter.thread is not None and reporter.thread.is_alive()}
                    self.reporters.add(play.progress)
                self._refresh()
            if old is not None:
                old.cancelled.set()
            refused = None
            try:
                if play is None or play.channel:
                    # Nothing of the previous play stays on screen while a channel tunes in.
                    if expected is None:
                        self.player.command('stop')
                    else:
                        self.player.bound_command(old.player_generation, 'stop')
                if play is not None and play.url:
                    self._load(play, play.url)
                elif play is not None and play.local is not None:
                    self._load(play, f'/proc/{os.getpid()}/fd/{play.local.fd}')
                elif play is not None:
                    # The channel resolves while the previous play is released below.
                    play.thread = threading.Thread(target=self._run, args=(play,), name=f'play-{play.number}')
                    play.thread.start()
            except (OSError, ValueError) as error:
                refused = error
                if play is not None:
                    with self.lock:
                        play.phase, play.reason = 'failed', f'the player did not take it ({type(error).__name__})'
                        self._refresh()
        if old is not None:
            release = threading.Thread(target=self._release, args=(old,), name=f'release-{old.number}')
            release.start()
            if wait:
                release.join()
        if refused is not None and play is None:
            raise refused
        return old

    @staticmethod
    def _release(old):
        old.close_stream()
        if old.thread is not None:
            old.thread.join(30)  # Its own cleanup follows the closed stream.
            if old.thread.is_alive():
                log.warning('%s: still releasing', old.name)
        if old.start_thread is not None and old.start_thread is not threading.current_thread():
            old.start_thread.join()  # A replaced generation performs no further start effect.
        if old.progress is not None:
            old.progress.finished.wait(TIMEOUT)  # Matched unload may follow loadfile's acknowledgement.
            old.progress.close()

    def _load(self, play, path):
        """Tell the player to load this play's file in place of whatever it shows (control held)."""
        options = {**_FAST_START, 'force-media-title': play.title}
        if play.local is not None:
            options = {'force-media-title': play.title, 'demuxer': 'lavf',
                       'demuxer-lavf-format': play.local.format,
                       'demuxer-lavf-o': 'protocol_whitelist=file', 'access-references': 'no',
                       'autoload-files': 'no', 'sub-auto': 'no', 'audio-file-auto': 'no',
                       'cover-art-auto': 'no', 'loop-file': 'no', 'loop-playlist': 'no',
                       'resume-playback': 'no', 'start': str(play.start_seconds), 'aid': 'auto', 'sid': 'auto'}
        if play.channel:
            options.update(_CUSHION)
        self.player.command('set_property', 'pause', False)
        with self.lock:
            play.player_generation = self.player.generation
        entry = (self.player.command('loadfile', path, 'replace', -1, options) or {}).get('playlist_entry_id')
        with self.lock:
            play.entry = entry
            self._finish()
            self._picture()
            self._refresh()
        if play.local is not None:
            playlist = self.player.command('get_property', 'playlist')
            matches = (isinstance(entry, int) and not isinstance(entry, bool)
                       and isinstance(playlist, list) and len(playlist) == 1
                       and isinstance(playlist[0], dict)
                       and playlist[0].get('id') == entry and playlist[0].get('filename') == path)
            with self.lock:
                if self.play is not play or play.phase == 'failed':
                    return
                if not matches:
                    play.phase, play.reason = 'failed', 'the player did not verify the exact local media entry'
                else:
                    play.verified = True
                    self._picture()
                self._refresh()
            if not matches:
                self.player.command('stop')  # One bounded cleanup, never another load.

    # A channel

    def _plugin(self, provider, channel, fresh):
        """streamlink's plugin for the provider, pointed at one channel (resolving held).

        One session and one plugin instance stay warm between plays: the session keeps its
        connections, and Pluto's plugin keeps the web app version it looks up once per instance
        (2.3 s measured). The plugin opens a new Pluto web session for every channel it resolves.
        """
        address = PROVIDERS[provider].format(channel)
        plugin = None if fresh else self.plugins.get(provider)
        if plugin is None:
            session = Streamlink()
            _name, found, address = session.resolve_url_no_redirect(address)
            plugin = self.plugins[provider] = found(session, address)
        else:
            plugin.url = address
        return plugin

    def _warm(self):
        """Before the first play: the plugin's app-version lookup, so the first channel starts like the next."""
        try:
            with self.resolving:
                getattr(self._plugin('pluto', '0' * 24, True), 'app_version', None)
        except Exception as error:  # The first play then looks it up itself.  # noqa: BLE001
            log.info('warm-up skipped (%s)', type(error).__name__)

    def _run(self, play):
        fresh = False
        while True:
            reason = self._attempt(play, fresh)
            if play.cancelled.is_set():
                return
            healthy = play.picture is not None and time.monotonic() - play.picture >= HEALTHY
            if fresh and not healthy:
                break
            log.warning('%s: %s; opening it once more with a fresh session', play.name, reason)
            fresh = True
        with self.control:
            with self.lock:
                if play.cancelled.is_set():
                    return
                play.phase, play.reason = 'failed', reason
                self._refresh()
            log.error('%s: failed: %s', play.name, reason)
            try:
                self.player.command('stop')  # No frozen last frame of a stream that is gone.
            except (OSError, ValueError):
                pass

    def _attempt(self, play, fresh):
        """Open the channel once and feed it to the player until it ends; the words say why it ended."""
        path = os.path.join(self.directory, f'stream-{play.number}.fifo')
        out = None
        with self.lock:
            play.phase, play.entry, play.picture, play.readers = 'loading', None, None, ()
            play.filtering, play.breaking = None, None
            if fresh:
                play.requested = time.monotonic()  # The journal times a reopened stream from its own start.
            self._refresh()
        try:
            stream = self._open(play, fresh)
            os.mkfifo(path, 0o600)
            with self.control:
                if play.cancelled.is_set():
                    raise _Fault('cancelled')
                try:
                    self._load(play, path)
                except (OSError, ValueError) as error:
                    raise _Fault(f'the player did not take the stream ({type(error).__name__})') from None
            out = self._writer(play, path)
            ready = select.poll()
            ready.register(out, select.POLLOUT)
            while True:
                try:
                    data = stream.read(8192)
                except Exception as error:  # Only the type: the text may hold an address.  # noqa: BLE001
                    raise _Fault(f'the stream failed ({type(error).__name__})') from None
                if not data:
                    raise _Fault('the stream ended')
                view = memoryview(data)
                while view:
                    if play.cancelled.is_set():
                        raise _Fault('cancelled')
                    if ready.poll(200):  # Otherwise the player's cache is full: the stream keeps its own buffer.
                        try:
                            view = view[os.write(out, view):]
                        except BlockingIOError:
                            pass
                        except OSError:
                            raise _Fault('the player closed the stream') from None
        except _Fault as fault:
            return str(fault)
        except Exception as error:  # Only the type: the text may hold an address.  # noqa: BLE001
            return f'the tuner could not feed the player ({type(error).__name__})'
        finally:
            # Each acquisition's cleanup: the player's entry, the FIFO's writer, the stream with
            # its readers, muxer and threads, the FIFO itself.
            with self.lock:
                play.entry = None
            if out is not None:
                os.close(out)
            play.close_stream()
            with self.lock:
                play.readers = ()
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

    def _open(self, play, fresh):
        try:
            with self.resolving:
                if play.cancelled.is_set():
                    raise _Fault('cancelled')
                streams = self._plugin(play.provider, play.channel, fresh).streams()
            if 'best' not in streams:
                raise _Fault(f'{play.provider} has no stream for this channel')
            stream = streams['best']
            # A muxed stream opens one reader per substream (video, audio) and then waits for data
            # in all of them, which a channel tuned in during its advertisement break delivers
            # only when the break ends. Each reader is taken as it opens, so the break shows at
            # once and a replaced play can end that wait. A plain stream is its own reader.
            parts = getattr(stream, 'substreams', ())
            for part in parts:
                part.open = self._taking(play, part.open)
            stream = stream.open()
            if not parts:
                self._take(play, stream)
        except _Fault:
            raise
        except Exception as error:  # Only the type: the text may hold an address.  # noqa: BLE001
            raise _Fault(f'the channel did not open ({type(error).__name__})') from None
        play.adopt(stream)
        if not play.readers:
            log.warning('%s: this streamlink reports no ad filtering; a break will read as loading', play.name)
        log.info('%s: stream open %.1f s after the request', play.name, time.monotonic() - play.requested)
        return stream

    def _taking(self, play, opening):
        """A substream's open() that also hands the reader it returns to the play."""
        def opened():
            reader = opening()
            self._take(play, reader)
            return reader
        return opened

    def _take(self, play, reader):
        if callable(getattr(reader, 'is_paused', None)):
            with self.lock:
                play.readers += (reader,)
        if play.cancelled.is_set():
            _quietly(reader.close)  # Replaced while it opened: the wait for its first data ends here.

    def _writer(self, play, path):
        """The FIFO's writing end, once the player holds its reading end."""
        deadline = time.monotonic() + FIFO_LIMIT
        while True:
            try:
                return os.open(path, os.O_WRONLY | os.O_NONBLOCK)
            except OSError as error:
                if error.errno != errno.ENXIO:
                    raise _Fault(f'the stream could not reach the player ({type(error).__name__})') from None
            if play.cancelled.wait(0.01):
                raise _Fault('cancelled')
            if time.monotonic() >= deadline:
                raise _Fault('the player did not open the stream')

    def close(self):
        with self.lock:
            self.closed = True
            self.lock.notify_all()
        self.presenter.join(10)  # It ends its idle/break view.
        try:
            self._replace(None, wait=True)
        except (OSError, ValueError):
            pass
        self.player.close()
        with self.lock:
            for held in self.local_files.values():
                held.close_local()
            self.local_files.clear()
            reporters = tuple(self.reporters)
        for reporter in reporters:
            reporter.close()  # EOF may have cleared self.play while its final HTTP report still runs.
        with self.lock:
            self.reporters.clear()


class _NoAddresses(logging.Filter):
    """Stream addresses carry session tokens: none reaches the journal, whoever logs it."""

    def filter(self, record):
        record.msg, record.args = re.sub(r'[A-Za-z][A-Za-z0-9+.-]*://\S+', '<address>', record.getMessage()), None
        record.exc_info = record.exc_text = None
        return True


class _Connection(socketserver.StreamRequestHandler):
    def handle(self):
        while line := self.rfile.readline(_LINE_LIMIT):
            try:
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError('A request is one JSON object')
                reply = {'ok': True, 'state': self.server.tuner.request(message)}
            except (ValueError, MediaUnavailable) as error:
                reply = {'ok': False, 'error': str(error)[:200]}
            except OSError:
                reply = {'ok': False, 'error': 'The player does not answer'}
            try:
                self.wfile.write((json.dumps(reply) + '\n').encode())
            except OSError:
                return  # The caller left; what it asked for stands.


class _Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True

    def __init__(self, path, tuner):
        self.tuner = tuner
        super().__init__(path, _Connection)


def _claim(directory, path):
    """Refuse to run beside a live tuner; remove what a killed one left behind."""
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        probe.settimeout(TIMEOUT)
        probe.connect(path)
        sys.exit('Another tuner owns ' + path)
    except OSError:
        pass
    finally:
        probe.close()
    for stale in (path, *glob.glob(os.path.join(glob.escape(directory), 'stream-*.fifo'))):
        try:
            os.unlink(stale)
        except FileNotFoundError:
            pass


def main():
    parser = argparse.ArgumentParser(description='The TV tuner: owns the TV player and what it shows.')
    parser.add_argument('--directory', default=os.path.join(RUNTIME, 'obsidience-tv'),
                        help='where the control socket tuner.sock and the stream FIFOs live')
    parser.add_argument('--player', default=os.path.join(RUNTIME, 'obsidience-tv-player.sock'),
                        help="the player's JSON IPC socket")
    parser.add_argument('--break-view',
                        help='a program shown while idle or during commercial breaks, with title and '
                             'mode (idle/break) arguments; it ends when content loads or resumes')
    args = parser.parse_args()
    os.umask(0o077)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter('%(name)s: %(message)s'))
    handler.addFilter(_NoAddresses())
    for name, level in (('tuner', logging.INFO), ('streamlink', logging.WARNING)):
        logger = logging.getLogger(name)
        logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = False
    logging.getLogger().addHandler(logging.NullHandler())  # No other library writes to the journal.
    os.makedirs(args.directory, mode=0o700, exist_ok=True)
    path = os.path.join(args.directory, 'tuner.sock')
    _claim(args.directory, path)
    tuner = Tuner(args.directory, args.player, args.break_view)
    server = _Server(path, tuner)
    for number in (signal.SIGTERM, signal.SIGINT):
        signal.signal(number, lambda *_: threading.Thread(target=server.shutdown, daemon=True).start())
    log.info('ready')
    try:
        server.serve_forever()
    finally:
        server.server_close()
        os.unlink(path)
        tuner.close()
        log.info('stopped')


if __name__ == '__main__':
    main()
