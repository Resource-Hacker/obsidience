"""Shared public music discovery and an owned best-audio byte source.

Only canonical public track identities cross the playback boundary. yt-dlp keeps
expiring delivery URLs inside its child process; neither the Agent nor receipts
receive them. The destination owns the streaming child and its lifetime.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import signal
import sys
from pathlib import Path

from .config import MediaUnavailable

VIDEO_ID = re.compile(r'[A-Za-z0-9_-]{11}')
TRACK_ID = re.compile(r'[0-9]{1,20}')


class _Quiet:
    def debug(self, *_args): pass
    def warning(self, *_args): pass
    def error(self, *_args): pass


def _options() -> dict:
    return {'quiet': True, 'no_warnings': True, 'noprogress': True, 'logger': _Quiet(),
            'cachedir': False, 'socket_timeout': 5, 'retries': 0, 'fragment_retries': 0,
            'extractor_retries': 0, 'noplaylist': True, 'remote_components': set(),
            'js_runtimes': {'node': {'path': '/usr/bin/node'}},
            'external_downloader': {'default': 'native'},
            'skip_unavailable_fragments': False}


def _text(value: object, limit: int = 160) -> str:
    return ' '.join(str(value or '').split())[:limit].replace('<', '').replace('>', '')


def _search(query: str) -> list[dict]:
    from yt_dlp import YoutubeDL
    rows = []
    with YoutubeDL({**_options(), 'extract_flat': 'in_playlist', 'playlistend': 20}) as client:
        try:
            result = client.extract_info('scsearch20:' + query, download=False)
        except Exception:
            result = {}
        for entry in (result or {}).get('entries') or []:
            track = entry.get('id', '')
            duration = entry.get('duration')
            title, description = _text(entry.get('title')), _text(entry.get('description'), 240)
            if (not isinstance(track, str) or not TRACK_ID.fullmatch(track)
                    or type(duration) not in (int, float) or not 45 < duration < 86400
                    or 'preview' in title.casefold()
                    or 'cover' in (title + ' ' + description).casefold() and 'cover' not in query.casefold()):
                continue
            rows.append({'provider': 'soundcloud', 'track_id': track, 'title': title,
                         'artist': _text(entry.get('uploader'), 80), 'description': description,
                         'duration_seconds': round(duration)})
    versions = re.compile(r'\b(remix|extended|rework|sped|slowed|mashup)\b', re.I)
    direct = sorted((row for row in rows if row['provider'] == 'soundcloud'), key=lambda row: (
        bool(versions.search(row['title'])) and not bool(versions.search(query)),
        not query.casefold().startswith(row['artist'].casefold())))[:4]
    # Flat search can list premium-only tracks. Resolve a few current choices
    # before offering them; a preview or DRM failure is never a playable result.
    def available(row):
        try:
            with YoutubeDL({**_options(), 'format': 'bestaudio/best'}) as probe:
                info = probe.extract_info('https://api.soundcloud.com/tracks/' + row['track_id'], download=False)
            if (str(info.get('id')) != row['track_id'] or info.get('has_drm')
                    or type(info.get('duration')) not in (int, float) or info['duration'] <= 45
                    or info.get('acodec') in (None, 'none')):
                return None
            return {**row, 'duration_seconds': round(info['duration']), 'codec': info['acodec'],
                    'bitrate_kbps': info.get('abr'), 'availability': 'stream_resolved'}
        except Exception:
            return None
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=3) as pool:
        direct = [row for row in pool.map(available, direct) if row is not None][:3]
    if direct:
        return direct
    with YoutubeDL({**_options(), 'extract_flat': 'in_playlist', 'playlistend': 3}) as client:
        try:
            result = client.extract_info('ytsearch3:' + query + ' official music', download=False)
        except Exception:
            if not rows:
                raise
            result = {}
        for entry in (result or {}).get('entries') or []:
            video = entry.get('id', '')
            if not isinstance(video, str) or not VIDEO_ID.fullmatch(video):
                continue
            duration = entry.get('duration')
            rows.append({'provider': 'youtube', 'video_id': video, 'title': _text(entry.get('title')),
                         'artist': _text(entry.get('uploader') or entry.get('channel'), 80),
                         'verified_channel': entry.get('channel_is_verified') is True,
                         'duration_seconds': round(duration) if type(duration) in (int, float) and 0 <= duration < 86400 else None})
    video = sorted((row for row in rows if row['provider'] == 'youtube'),
                   key=lambda row: not row['verified_channel'])[:3]
    return direct + video


async def search(query: str) -> list[dict]:
    if not isinstance(query, str) or not query.strip() or len(query) > 120 or any(ord(c) < 32 for c in query):
        raise ValueError('Music search needs 1 to 120 characters')
    root = Path(__file__).resolve().parents[2]
    child = await asyncio.create_subprocess_exec(
        sys.executable, '-m', 'harness.media.online_music', 'search', query.strip(),
        cwd=root, env={'PATH': os.defpath, 'LANG': 'C.UTF-8', 'PYTHONPATH': str(root)},
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
    try:
        async with asyncio.timeout(12):
            material, _ = await child.communicate()
        if child.returncode or len(material) > 16384:
            raise MediaUnavailable('online_music_search_unavailable')
        rows = json.loads(material)
        if not isinstance(rows, list) or len(rows) > 6:
            raise MediaUnavailable('online_music_search_unavailable')
        return rows
    except (TimeoutError, ValueError):
        raise MediaUnavailable('online_music_search_unavailable') from None
    finally:
        if child.returncode is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        await child.wait()


def revalidate(candidate: dict) -> dict:
    if not isinstance(candidate, dict):
        raise MediaUnavailable('music_selection_invalid')
    provider = candidate.get('provider')
    field, pattern = ('video_id', VIDEO_ID) if provider == 'youtube' else ('track_id', TRACK_ID)
    keys = {'provider', field, 'title', 'item_id'}
    if (provider not in ('youtube', 'soundcloud') or set(candidate) not in (keys, keys | {'debrid_binding'})
            or not isinstance(candidate.get(field), str) or not pattern.fullmatch(candidate[field])
            or candidate['item_id'] != provider + ':' + candidate[field]
            or not isinstance(candidate['title'], str) or not candidate['title'] or len(candidate['title']) > 160):
        raise MediaUnavailable('music_selection_invalid')
    return dict(candidate)


def _stream(provider: str, identity: str) -> None:
    from yt_dlp import YoutubeDL
    from tempfile import TemporaryDirectory
    if provider == 'youtube' and VIDEO_ID.fullmatch(identity):
        url = 'https://www.youtube.com/watch?v=' + identity
    elif provider == 'soundcloud' and TRACK_ID.fullmatch(identity):
        url = 'https://api.soundcloud.com/tracks/' + identity
    else:
        raise ValueError('invalid_music_source')
    def full_track(info, *, incomplete=False):
        if not incomplete and info.get('is_live'):
            return 'Live source is unavailable on this music route'
        if provider == 'soundcloud' and not incomplete and (
                not isinstance(info.get('duration'), (int, float)) or info['duration'] <= 45):
            return 'Full audio is unavailable'
        return None
    # Native HLS can otherwise fall back to FFmpeg and expose its signed URL
    # in argv. Give upstream an explicitly empty executable directory. Only
    # Node's independent /usr/bin/ffmpeg decoder receives our pipe bytes.
    with TemporaryDirectory(prefix='obsidience-music-native-') as no_external:
        with YoutubeDL({**_options(), 'format': 'bestaudio/best', 'outtmpl': '-',
                        'ffmpeg_location': no_external,
                        'match_filter': full_track, 'logtostderr': True}) as client:
            if client.download([url]):
                raise ValueError('source_unavailable')


if __name__ == '__main__':
    try:
        if len(sys.argv) not in (3, 4):
            raise ValueError('invalid_operation')
        if sys.argv[1] == 'search' and len(sys.argv) == 3:
            print(json.dumps(_search(sys.argv[2]), ensure_ascii=True))
        elif sys.argv[1] == 'stream' and len(sys.argv) == 4:
            _stream(sys.argv[2], sys.argv[3])
        else:
            raise ValueError('invalid_operation')
    except Exception:
        # Upstream exceptions may contain signed delivery URLs: never log them.
        print('music_source_unavailable', file=sys.stderr)
        sys.exit(1)
