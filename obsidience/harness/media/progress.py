"""Tuner-owned Jellyfin playback reports, with stored-user-data readback.

The native 12.2 Sessions/Playing endpoints derive user/device session from the
authenticated request. Start increments play count; progress/stop persist native
resume thresholds. No client database, HTTP retry, or stale outbox is created.
Jellyfin supplies no compare-and-swap for these writes: fingerprint checks detect
observed competing updates, but cannot eliminate a race between GET and POST.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time

import httpx

from .config import MediaUnavailable, load_config
from .jellyfin import catalogue_id, _token

INTERVAL = 15.0
_SEQUENCE = threading.Lock()  # One TV device session: old stop precedes the next start.
_DEVICE = 'obsidience-media-tv'
_MAX_BODY = 256 * 1024


def _invalid_constant(_value):
    raise ValueError('invalid_json_constant')


class PlaybackProgress:
    """One play owns this worker; acquisition, final snapshot and cleanup are explicit."""

    def __init__(self, config: dict, source: dict, generation: str, sample, current):
        self.config, self.source, self.generation = config, source, generation
        self.sample, self.current = sample, current
        self.lock = threading.Lock()
        self.finished = threading.Event()
        self.thread = None
        self.final = None
        self.started = False
        self.disabled = False
        self.saved = None
        self.status = {'status': 'pending', 'generation': generation}
        self._loop = None
        self._request_task = None

    def start(self):
        with self.lock:
            if self.thread is not None or self.disabled:
                return
            self.thread = threading.Thread(target=self._run, name='media-progress', daemon=True)
            self.thread.start()

    def snapshot(self) -> dict:
        with self.lock:
            return dict(self.status)

    def disable(self, reason='progress_unavailable'):
        with self.lock:
            self.disabled = True
            self.status = {**self.status, 'status': 'degraded', 'reason': reason}
            loop, task = self._loop, self._request_task
        self.finished.set()
        if loop is not None and task is not None:
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass  # The worker closed the loop beside this check.

    def finish(self, vod: dict | None, outcome: str):
        """Queue one exact final snapshot; the IPC callback never waits on HTTP."""
        with self.lock:
            if self.disabled or self.final is not None:
                return
            if self.thread is None:
                self.disabled = True
                self.status = {**self.status, 'status': 'degraded', 'reason': 'progress_not_started'}
            elif not isinstance(vod, dict) or type(vod.get('position')) not in (int, float):
                self.disabled = True
                self.status = {**self.status, 'status': 'degraded', 'reason': 'final_position_unavailable'}
            else:
                self.final = (dict(vod), outcome)
        self.finished.set()

    def close(self):
        # A shutdown without an observed final position must not invent completion.
        if not self.finished.is_set():
            self.disable('reporter_closed_without_final_position')
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join(12)
            if self.thread.is_alive():
                self.disable('progress_shutdown_deadline')
                self.thread.join()  # Drain cancelled I/O; never abandon a catalogue writer.

    def _request(self, client, method, endpoint, payload=None, params=None):
        with self.lock:
            if self.disabled:
                raise MediaUnavailable('progress_disabled')
        catalogue = self.config.get('catalogue') or {}
        if load_config() != self.config:
            raise MediaUnavailable('media_config_changed')
        headers = {'Accept': 'application/json', 'Accept-Encoding': 'identity',
                   'Authorization': ('MediaBrowser Client="Obsidience Media TV", Device="TV tuner", '
                                     f'DeviceId="{_DEVICE}", Version="1", Token="'
                                     + _token(catalogue['credential']) + '"')}
        async def request():
            # This covers connect, slow headers and every body byte. The native
            # async transport can cancel its socket I/O without abandoning work.
            async with asyncio.timeout(5):
                with self.lock:
                    if self.disabled:
                        raise MediaUnavailable('progress_disabled')
                async with client.stream(method, catalogue['url'] + endpoint, headers=headers,
                                         json=payload, params=params) as response:
                    if method == 'POST':
                        if response.status_code != 204:
                            raise MediaUnavailable('progress_write_unverified')
                        return None
                    if (response.status_code != 200
                            or response.headers.get('content-type', '').split(';')[0].strip() != 'application/json'
                            or response.headers.get('content-encoding', 'identity') != 'identity'):
                        raise MediaUnavailable('progress_read_unavailable')
                    material = bytearray()
                    async for chunk in response.aiter_bytes():
                        material.extend(chunk)
                        if len(material) > _MAX_BODY:
                            raise MediaUnavailable('progress_response_limit')
                    result = json.loads(material, parse_constant=_invalid_constant)
                    if not isinstance(result, dict):
                        raise MediaUnavailable('invalid_progress_response')
                    return result
        task = None
        try:
            with self.lock:
                if self.disabled:
                    raise MediaUnavailable('progress_disabled')
                task = self._request_task = self._loop.create_task(request())
            return self._loop.run_until_complete(task)
        except (httpx.HTTPError, ValueError, UnicodeError, TimeoutError, asyncio.CancelledError):
            raise MediaUnavailable('progress_transport_unverified') from None
        finally:
            with self.lock:
                if self._request_task is task:
                    self._request_task = None

    def _stored(self, client):
        page = self._request(client, 'GET', '/Items', params={
            'userId': self.config['catalogue']['user_id'], 'ids': catalogue_id(self.source['item_id']),
            'limit': 2, 'recursive': 'true', 'enableImages': 'false', 'enableUserData': 'true'})
        items = page.get('Items')
        if (not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict)
                or catalogue_id(items[0].get('Id')) != catalogue_id(self.source['item_id'])):
            raise MediaUnavailable('progress_item_unavailable')
        data = items[0].get('UserData')
        if not isinstance(data, dict):
            raise MediaUnavailable('progress_user_data_unavailable')
        ticks, played, count, date = (data.get('PlaybackPositionTicks'), data.get('Played'),
                                      data.get('PlayCount'), data.get('LastPlayedDate'))
        if (type(ticks) is not int or not 0 <= ticks <= 10_000_000_000_000_000
                or type(played) is not bool or type(count) is not int or not 0 <= count <= 2147483647
                or (date is not None and (not isinstance(date, str) or len(date) > 64))):
            raise MediaUnavailable('invalid_progress_user_data')
        return {'position_ticks': ticks, 'played': played, 'play_count': count, 'last_played': date}

    def _payload(self, vod, stopped=False):
        position = vod.get('position')
        if type(position) not in (int, float) or not 0 <= position <= 1_000_000_000:
            raise MediaUnavailable('progress_position_unavailable')
        payload = {'ItemId': catalogue_id(self.source['item_id']), 'MediaSourceId': self.source['media_source_id'],
                   'PlaySessionId': self.generation, 'PositionTicks': round(position * 10_000_000)}
        if not stopped:
            payload.update(PlayMethod='DirectPlay', CanSeek=vod.get('seekable') is True,
                           IsPaused=vod.get('paused') is True, IsMuted=False, RepeatMode='RepeatNone')
        return payload

    def _report(self, client, kind, vod):
        before = self._stored(client)
        if self.saved is not None and before != self.saved:
            raise MediaUnavailable('external_progress_changed')
        with self.lock:
            if self.disabled:
                raise MediaUnavailable('progress_disabled')
        if kind != 'stopped' and (self.finished.is_set() or not self.current()):
            raise MediaUnavailable('progress_generation_changed')
        payload = self._payload(vod, stopped=kind == 'stopped')
        endpoint = {'start': '/Sessions/Playing', 'progress': '/Sessions/Playing/Progress',
                    'stopped': '/Sessions/Playing/Stopped'}[kind]
        self._request(client, 'POST', endpoint, payload=payload)
        after = self._stored(client)
        expected_count = before['play_count'] + (1 if kind == 'start' else 0)
        if after['play_count'] != expected_count:
            raise MediaUnavailable('external_progress_changed')
        if (kind != 'start' and after['position_ticks'] != 0
                and abs(after['position_ticks'] - payload['PositionTicks']) > 5_000_000):
            raise MediaUnavailable('progress_write_unverified')
        self.saved = after
        with self.lock:
            if not self.disabled:
                self.status = {'status': 'active' if kind == 'start' else 'saved',
                               'generation': self.generation, 'saved_position': after['position_ticks'] / 10_000_000,
                               'played': after['played'], 'play_count': after['play_count'],
                               'observed_at': round(time.time(), 3)}

    def _run(self):
        acquired = False
        client = None
        try:
            while not self.finished.is_set():
                if _SEQUENCE.acquire(timeout=.2):
                    acquired = True
                    break
            if not acquired:
                if not self.disabled:
                    self.disable('progress_not_started')
                return
            with self.lock:
                self._loop = asyncio.new_event_loop()
            client = httpx.AsyncClient(timeout=httpx.Timeout(3, connect=1), follow_redirects=False,
                                       trust_env=False, limits=httpx.Limits(max_connections=1))
            catalogue = self.config.get('catalogue') or {}
            info = self._request(client, 'GET', '/System/Info/Public')
            user = self._request(client, 'GET', '/Users/Me')
            if info.get('Id') != catalogue.get('instance_id') or catalogue_id(user.get('Id')) != catalogue.get('user_id'):
                raise MediaUnavailable('progress_identity_changed')
            vod, deadline = None, time.monotonic() + 5
            while vod is None and not self.finished.is_set() and time.monotonic() < deadline:
                vod = self.sample()
                if vod is None:
                    self.finished.wait(.2)  # Bounded wait for the playback control lock, fresh reads only.
            if vod is None:
                raise MediaUnavailable('progress_initial_position_unavailable')
            self._report(client, 'start', vod)
            self.started = True
            while not self.finished.wait(INTERVAL):
                if not self.current():
                    raise MediaUnavailable('progress_generation_changed')
                vod = self.sample()
                if vod is not None:
                    self._report(client, 'progress', vod)
            with self.lock:
                final, disabled = self.final, self.disabled
            if not disabled and final is not None:
                vod, outcome = final
                if outcome not in ('stopped', 'ended'):
                    raise MediaUnavailable('progress_final_outcome_unverified')
                self._report(client, 'stopped', vod)
        except MediaUnavailable as error:
            self.disable(str(error))
        except Exception:
            self.disable('progress_unavailable')  # No response bodies, paths, tokens or tracebacks.
        finally:
            try:
                if self._loop is not None:
                    try:
                        if client is not None:
                            self._loop.run_until_complete(asyncio.wait_for(client.aclose(), 1))
                    except Exception:
                        self.disable('progress_cleanup_unverified')
                    finally:
                        self._loop.close()
            finally:
                if acquired:
                    _SEQUENCE.release()
