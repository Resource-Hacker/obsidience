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
  {"op": "pause"}  {"op": "resume"}  {"op": "stop"}  {"op": "state"}
play replaces whatever plays and answers once the new play left `loading` (its first picture, a
break it was tuned into, or failed), or after `wait` seconds (0 when absent). state: playback
idle | loading | playing | break | paused | failed, title, video [width, height] once a picture
shows, since (epoch seconds of the last playback change), player (whether the player answers),
provider and channel for a channel, reason for failed.

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


class _Fault(Exception):
    """Why one attempt to play a channel ended, in words that never hold an address."""


class Player:
    """mpv's JSON IPC: one connection, opened when a command needs it, one command in flight.

    Replies and events arrive on a reader thread. An event handler must never send a command: it
    runs on that thread, which would then wait for a reply only it can read.
    """
    OBSERVED = ('pause', 'paused-for-cache', 'width', 'height')

    def __init__(self, path, on_event):
        self.path, self.on_event = path, on_event
        self._sending = threading.Lock()
        self._replies = queue.SimpleQueue()
        self._sock = None
        self._ident = 0

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

    def _connect(self):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.settimeout(TIMEOUT)
            sock.connect(self.path)
            sock.settimeout(None)
        except OSError:
            sock.close()
            raise
        self._sock = sock
        threading.Thread(target=self._read, args=(sock,), name='player-ipc', daemon=True).start()
        for ident, name in enumerate(self.OBSERVED, 1):
            self._ask(('observe_property', ident, name))

    def _ask(self, command):
        sock = self._sock
        if sock is None:
            raise ConnectionError('The player closed its connection')
        self._ident += 1
        sock.sendall((json.dumps({'command': command, 'request_id': self._ident}) + '\n').encode())
        deadline = time.monotonic() + TIMEOUT
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

    def _read(self, sock):
        buffer = b''
        try:
            while chunk := sock.recv(65536):
                *lines, buffer = (buffer + chunk).split(b'\n')
                if len(buffer) > _LINE_LIMIT:
                    break
                for line in lines:
                    message = json.loads(line)
                    if 'event' in message:
                        self.on_event(message)
                    else:
                        self._replies.put((sock, message))
        except (OSError, ValueError):
            pass
        finally:
            if self._sock is sock:
                self._sock = None
            sock.close()  # Cleanup paired with the connection; observed properties and overlays end with it.
            self._replies.put((sock, None))
            self.on_event({'event': 'disconnected'})

    def close(self):
        sock = self._sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)  # The reader thread closes it.
            except OSError:
                pass


class Play:
    """One thing the tuner was asked to play, and what was acquired for it."""

    def __init__(self, number, title, provider=None, channel=None, url=None):
        self.number, self.title, self.provider, self.channel, self.url = number, title, provider, channel, url
        # For the journal: a title and a channel id, never an address.
        self.name = f'{title!r} ({provider} {channel})' if channel else f'{title!r} (address)'
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
    """End a break view at once (its whole process group) and reap it.

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
        self.finished = (None, None)  # The entry it ended last, and why.
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
                    'loading' if play.phase == 'loading' or starved else 'playing')
        if playback != self.playback:
            log.info('%s: %s -> %s', play.name if play is not None else 'player', self.playback, playback)
            self.playback, self.since = playback, time.time()
        self.lock.notify_all()

    def state(self):
        reached = self.player.reach()
        with self.lock:
            self._refresh()
            play = self.play
            size = [self.properties.get('width'), self.properties.get('height')]
            state = {'playback': self.playback, 'title': play.title if play is not None else '',
                     'video': size if play is not None and play.phase == 'playing'
                     and all(isinstance(side, int) for side in size) else None,
                     'since': round(self.since, 1), 'player': reached}
            if play is not None and play.channel:
                state.update(provider=play.provider, channel=play.channel)
            if play is not None and play.phase == 'failed':
                state['reason'] = play.reason
            return state

    def _event(self, event):
        """The player's events, on its reader thread: state only, never a command."""
        name = event.get('event')
        with self.lock:
            play = self.play
            if name == 'property-change':
                self.properties[event.get('name')] = event.get('data')
            elif name == 'start-file':
                self.entry = event.get('playlist_entry_id')
            elif name == 'playback-restart':
                # The replaced file's events come first; only this play's own picture counts.
                if play is not None and play.phase == 'loading' and play.entry is not None and play.entry == self.entry:
                    play.phase, play.picture = 'playing', time.monotonic()
                    log.info('%s: picture %.1f s after the request', play.name, play.picture - play.requested)
            elif name == 'end-file':
                self.finished = (event.get('playlist_entry_id'), event.get('reason'))
                self._finish()
            elif name == 'disconnected':
                self.properties.clear()
                self.entry = None
                if play is not None and play.url:
                    play.phase, play.reason = 'failed', 'the player closed its connection'
            else:
                return
            self._refresh()

    def _finish(self):
        """An address the player finished or gave up ends its play (lock held).

        A channel's own thread sees its stream end. The player can end a file before the play
        knows its entry, so both the event and the loaded entry come through here.
        """
        play, (entry, reason) = self.play, self.finished
        if play is not None and play.url and play.entry is not None and play.entry == entry:
            if reason == 'eof':
                self.play = None
            elif reason == 'error':
                play.phase, play.reason = 'failed', 'the player could not play this address'

    def _present(self):
        """Draw the break card while a break lasts, its clock once a second, and remove it afterwards.

        The break view, when one is configured, runs for exactly as long: started once when the
        break begins and ended with it. Its window covers the card once it has a picture.
        """
        shown, breaking, view = None, False, None
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
                if (card is not None) != breaking:
                    breaking = card is not None
                    if view is not None:
                        _end(view)
                        view = None
                    if breaking and self.break_view:
                        try:
                            view = subprocess.Popen([self.break_view, play.title], stdin=subprocess.DEVNULL,
                                                    start_new_session=True)
                        except OSError as error:
                            log.warning('break view did not start (%s)', type(error).__name__)
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
        if op == 'play':
            title, wait = message.get('title'), message.get('wait', 0)
            if not isinstance(title, str) or not title.strip() or len(title) > 160:
                raise ValueError('play takes a title of 1-160 characters')
            if isinstance(wait, bool) or not isinstance(wait, (int, float)) or not 0 <= wait <= 60:
                raise ValueError('wait takes 0-60 seconds')
            if 'url' in message:
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
                self.player.command('set_property', 'pause', op == 'pause')
                paused = self.player.command('get_property', 'pause')
            with self.lock:
                self.properties['pause'] = paused  # The player's own readback; its event confirms it.
                self._refresh()
        elif op == 'stop':
            self._replace(None)
        elif op != 'state':
            raise ValueError('op is play, pause, resume, stop or state')
        return self.state()

    def _start(self, title, source, wait):
        with self.lock:
            self.plays += 1
            play = Play(self.plays, title, **source)
        log.info('%s: play', play.name)
        self._replace(play)
        with self.lock:
            self.lock.wait_for(lambda: self.play is not play or self.playback != 'loading', timeout=wait)

    def _replace(self, play, wait=False):
        """Make play (or nothing) the current play and release everything the previous one held.

        Closing a stream waits for its downloads in flight (0.4-3 s measured), so the previous
        play is released beside the new one's start; wait makes the caller see it through.
        """
        with self.control:
            with self.lock:
                old, self.play = self.play, play
                self._refresh()
            if old is not None:
                old.cancelled.set()
            refused = None
            try:
                if play is None or play.channel:
                    # Nothing of the previous play stays on screen while a channel tunes in.
                    self.player.command('stop')
                if play is not None and play.url:
                    self._load(play, play.url)
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

    @staticmethod
    def _release(old):
        old.close_stream()
        if old.thread is not None:
            old.thread.join(30)  # Its own cleanup follows the closed stream.
            if old.thread.is_alive():
                log.warning('%s: still releasing', old.name)

    def _load(self, play, path):
        """Tell the player to load this play's file in place of whatever it shows (control held)."""
        options = {**_FAST_START, 'force-media-title': play.title}
        if play.channel:
            options.update(_CUSHION)
        self.player.command('set_property', 'pause', False)
        entry = (self.player.command('loadfile', path, 'replace', -1, options) or {}).get('playlist_entry_id')
        with self.lock:
            play.entry = entry
            self._finish()
            self._refresh()

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
        self.presenter.join(10)  # It ends its break view.
        try:
            self._replace(None, wait=True)
        except (OSError, ValueError):
            pass
        self.player.close()


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
            except ValueError as error:
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
                        help='a program run for as long as each commercial break lasts, with the title as its '
                             'argument, and killed when the break ends; it may show something in the TV '
                             'session in place of the break card')
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
