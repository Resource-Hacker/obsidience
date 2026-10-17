"""Shared public music discovery and an owned best-audio byte source.

Only canonical public track identities cross the playback boundary. yt-dlp keeps
expiring delivery URLs inside its child process; neither the Agent nor receipts
receive them. The destination owns the streaming child and its lifetime.
"""
from __future__ import annotations

import asyncio
import contextlib
from difflib import SequenceMatcher
import io
import json
import math
import os
import re
import signal
import stat
import sys
import time
import unicodedata
from pathlib import Path

from .config import MediaUnavailable

VIDEO_ID = re.compile(r'[A-Za-z0-9_-]{11}')
TRACK_ID = re.compile(r'[0-9]{1,20}')


class _Quiet:
    code = 'source_unavailable'
    phase = 'metadata'
    downloaded_bytes = 0
    expected_bytes = None

    def debug(self, *_args): pass
    def warning(self, *_args): pass
    def error(self, message):
        # Classify in memory only: upstream text can contain signed URLs.
        text = str(message).lower()
        for code, fragments in (
                ('source_http_429', ('http error 429', 'too many requests')),
                ('source_http_403', ('http error 403', 'forbidden')),
                ('source_auth_required', ('sign in', 'not a bot')),
                ('source_challenge_failed', ('challenge', 'signature', 'javascript')),
                ('source_format_unavailable', ('requested format', 'no video formats')),
                ('source_timeout', ('timed out', 'timeout')),
                ('source_short_read', ('more expected', 'incomplete read', 'incompleteread')),
                ('source_connection_lost', ('connection reset', 'reset by peer', 'remote end closed')),
                ('source_write_failed', ('unable to write', 'broken pipe'))):
            if any(fragment in text for fragment in fragments):
                self.code = code
                break
        if re.search(r'downloaded \d+ bytes, expected \d+ bytes', text):
            self.code = 'source_short_read'

    def progress(self, status):
        self.phase = 'download'
        for field, key in (('downloaded_bytes', 'downloaded_bytes'), ('expected_bytes', 'total_bytes')):
            value = status.get(key)
            if type(value) is int and 0 <= value <= 2**53 - 1:
                setattr(self, field, value)


_LOGGER = _Quiet()


def _options() -> dict:
    return {'quiet': True, 'no_warnings': True, 'noprogress': True, 'logger': _LOGGER,
            'cachedir': False, 'socket_timeout': 5, 'retries': 0, 'fragment_retries': 0,
            'extractor_retries': 0, 'noplaylist': True, 'remote_components': set(),
            'js_runtimes': {'node': {'path': '/usr/bin/node'}},
            'external_downloader': {'default': 'native'},
            'skip_unavailable_fragments': False}


def _text(value: object, limit: int = 160) -> str:
    return ' '.join(str(value or '').split())[:limit].replace('<', '').replace('>', '')


def _rank_artists(query: str, rows: list[dict]) -> list[dict]:
    """Whole-channel name relevance, never an automatic recording match."""
    def words(text):
        return re.findall(r'[^\W_]+', unicodedata.normalize('NFKC', text).casefold())

    query_words, scores = words(query), {}
    for row in rows:
        artist_words = words(row['artist'])
        artist = ' '.join(artist_words)
        if not artist or not row['verified_channel']:
            continue
        spans = [' '.join(query_words[i:i + len(artist_words)])
                 for i in range(len(query_words) - len(artist_words) + 1)]
        score = max((SequenceMatcher(None, artist, span).ratio() for span in spans), default=0)
        # Short names are too collision-prone for spelling hints. Exact names
        # still rank normally, and close names never enter exact autoplay.
        if score == 1 or len(artist) >= 6 and score >= .9:
            scores[artist] = score
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    close = (ranked[0][0] if ranked and ranked[0][1] < 1
             and (len(ranked) == 1 or ranked[0][1] - ranked[1][1] >= .08) else None)
    for row in rows:
        artist = ' '.join(words(row['artist']))
        if row['verified_channel'] and scores.get(artist) == 1:
            row['artist_match'] = 'exact'
        elif row['verified_channel'] and artist == close:
            row['artist_match'] = 'close'
    return sorted(rows, key=lambda row: (
        {'exact': 0, 'close': 1}.get(row.get('artist_match'), 2),
        not row['verified_channel'], not bool(re.search(r'\bofficial audio\b', row['title'], re.I))))


def _search(query: str, *, count: int = 5, limit: int = 3) -> list[dict]:
    from yt_dlp import YoutubeDL
    versions = re.compile(r'\b(cover|remix|bootleg|karaoke|instrumental|extended|rework|sped|slowed|mashup|nightcore|tribute|live|acoustic)\b', re.I)
    requested_versions = {word.casefold() for word in versions.findall(query)}
    rows = []
    with YoutubeDL({**_options(), 'extract_flat': 'in_playlist', 'playlistend': count}) as client:
        result = client.extract_info(f'ytsearch{count}:' + query + ' official audio', download=False)
        for entry in (result or {}).get('entries') or []:
            if (entry.get('is_live') is True or entry.get('live_status') in {'is_live', 'is_upcoming'}
                    or count == 20 and entry.get('live_status') == 'post_live'):
                continue  # This byte-source route admits finite recordings only.
            video = entry.get('id', '')
            title = _text(entry.get('title'))
            if (not isinstance(video, str) or not VIDEO_ID.fullmatch(video) or not title
                    or {word.casefold() for word in versions.findall(title)} - requested_versions):
                continue
            duration = entry.get('duration')
            # Flat YouTube search sometimes omits live_status even for radio.
            # Admit a bounded recording only when its duration is known; an
            # unknown duration is not proof of live content or playability.
            if type(duration) not in (int, float) or not math.isfinite(duration) or not 45 < duration < 86400:
                continue
            rows.append({'provider': 'youtube', 'video_id': video, 'title': title,
                         'artist': _text(entry.get('uploader') or entry.get('channel'), 80),
                         'verified_channel': entry.get('channel_is_verified') is True,
                         'duration_seconds': round(duration)})
    # Provider metadata is not acoustic verification. A relevant whole artist
    # name outranks presentation labels on another artist's recording.
    return _rank_artists(query, rows)[:limit]


async def search(query: str) -> list[dict]:
    return await _search_process(query)


async def _search_process(query: str, *, continuous: bool = False) -> list[dict]:
    if not isinstance(query, str) or not query.strip() or len(query) > 120 or any(ord(c) < 32 for c in query):
        raise ValueError('Music search needs 1 to 120 characters')
    root = Path(__file__).resolve().parents[2]
    child = None
    spawning = asyncio.create_task(asyncio.create_subprocess_exec(
        sys.executable, '-m', 'harness.media.online_music',
        'search-next' if continuous else 'search', query.strip(),
        cwd=root, env={'PATH': os.defpath, 'LANG': 'C.UTF-8', 'PYTHONPATH': str(root)},
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, start_new_session=True))
    try:
        # A disconnect during process creation must still leave an owned child
        # to kill/reap; shielding creation does not shield the search itself.
        child = await asyncio.shield(spawning)
        async with asyncio.timeout(9.5 if continuous else 12):
            material, _ = await child.communicate()
        if child.returncode or len(material) > 16384:
            raise MediaUnavailable('online_music_search_unavailable')
        rows = json.loads(material)
        if not isinstance(rows, list) or len(rows) > (20 if continuous else 6):
            raise MediaUnavailable('online_music_search_unavailable')
        return rows
    except (TimeoutError, ValueError):
        raise MediaUnavailable('online_music_search_unavailable') from None
    finally:
        if child is None:
            with contextlib.suppress(OSError):
                child = await spawning
        if child is not None and child.returncode is None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if child is not None:
            await child.wait()


async def select_next(query: str, artist: str, *, current: dict | None, recent: list[str]) -> dict:
    """One fresh public catalogue lookup; the transport owns the continuous mode and playback."""
    from .config import load_config
    config = load_config()
    music = config.get('music') or {}
    if not config.get('enabled') or not music.get('enabled') or music.get('delivery') != 'direct':
        raise MediaUnavailable('online_music_direct_delivery_unavailable')
    query, artist = query.strip(), artist.strip()
    seed = query or artist
    if not seed and current:
        seed = (current['artist'].strip() or current['title'].strip())[:120]
    if not seed:
        raise MediaUnavailable('online_music_seed_unavailable')
    excluded = set(recent)
    if current and current['source']:
        excluded.add('youtube:' + current['source']['video_id'])
    wanted_artist = ' '.join(re.findall(r'[^\W_]+', unicodedata.normalize('NFKC', artist).casefold()))
    for row in await _search_process(seed, continuous=True):
        if ('youtube:' + row.get('video_id', '')) in excluded:
            continue
        observed_artist = ' '.join(re.findall(
            r'[^\W_]+', unicodedata.normalize('NFKC', row.get('artist', '')).casefold()))
        if artist and (not wanted_artist or row.get('verified_channel') is not True
                       or observed_artist != wanted_artist):
            continue
        binding = revalidate({'provider': row.get('provider'), 'video_id': row.get('video_id'),
                              'title': row.get('title'), 'item_id': 'youtube:' + row.get('video_id', '')})
        return {'status': 'completed',
                'source': {'provider': binding['provider'], 'video_id': binding['video_id']},
                'title': binding['title'], 'artist': _text(row.get('artist'), 80)}
    raise MediaUnavailable('online_music_next_unavailable')


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


def _youtube_cookie_stream():
    """Optional systemd cookie credential; native parsing and updates stay in RAM."""
    from yt_dlp.cookies import YoutubeDLCookieJar
    filename = os.environ.get('OBSIDIENCE_YOUTUBE_COOKIES_CREDENTIAL')
    if not filename:
        return None
    if not Path(filename).is_absolute():
        raise ValueError('invalid_youtube_cookie_credential')
    try:
        fd = os.open(filename, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None  # The optional credential is not installed: remain anonymous.
    with os.fdopen(fd, 'r', encoding='utf-8') as credential:
        info = os.fstat(credential.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or not 0 < info.st_size <= 524288):
            raise ValueError('invalid_youtube_cookie_credential')
        material = credential.read(524289)
        if len(material.encode('utf-8')) > 524288:
            raise ValueError('invalid_youtube_cookie_credential')
    stream = io.StringIO(material)
    try:
        jar = YoutubeDLCookieJar()
        # Upstream malformed-cookie warnings can contain the original line.
        # Suppress those only while parsing this bounded private credential.
        with contextlib.redirect_stderr(io.StringIO()):
            jar.load(stream)
        for cookie in list(jar):
            domain = cookie.domain.lstrip('.').lower()
            if domain != 'youtube.com' and not domain.endswith('.youtube.com'):
                jar.clear(cookie.domain, cookie.path, cookie.name)
        if not len(jar):
            raise ValueError('invalid_youtube_cookie_credential')
        # Normalize through upstream before YoutubeDL loads it, so later loads
        # cannot repeat malformed-line warnings. Never save to the credential.
        stream.seek(0)
        jar.save(stream)
        stream.seek(0)
        return stream
    except BaseException:
        stream.close()
        raise


def _stream(provider: str, identity: str) -> None:
    from yt_dlp import YoutubeDL
    from yt_dlp.networking import Request
    from yt_dlp.networking.exceptions import HTTPError
    from yt_dlp.utils import DownloadError, parse_http_range
    from tempfile import TemporaryDirectory

    _LOGGER.phase, _LOGGER.downloaded_bytes, _LOGGER.expected_bytes = 'metadata', 0, None

    class StreamingYoutubeDL(YoutubeDL):
        stream_url = None

        def urlopen(self, request):
            # Native HTTP retries resume stdout by byte offset. Its ordinary
            # file fallback may instead restart from zero if Range is ignored;
            # a pipe cannot be rewound. Reject that fallback before any body is
            # read, while retaining upstream's bounded transport retries.
            streaming = self.stream_url is not None and getattr(request, 'url', request) == self.stream_url
            match = re.fullmatch(r'bytes=(\d+)-(\d*)', getattr(request, 'headers', {}).get('Range', ''))
            start = int(match[1]) if match else None
            end = int(match[2]) if match and match[2] else None

            def reject():
                _LOGGER.code = 'source_resume_range_invalid'
                raise DownloadError('Source cannot safely resume this audio stream')

            if streaming and _LOGGER.downloaded_bytes and (start is None or start < _LOGGER.downloaded_bytes):
                reject()
            try:
                response = super().urlopen(request)
            except HTTPError as error:
                if streaming and start and error.status == 416:
                    error.response.close()
                    reject()  # Native 416 recovery can reopen without Range.
                raise
            if streaming and start:
                actual_start, actual_end, total = parse_http_range(response.headers.get('Content-Range'))
                if (actual_start != start or end is not None and not (
                        actual_end == end or total is not None and total < end)):
                    response.close()
                    reject()
            return response

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
    with contextlib.ExitStack() as cleanup:
        no_external = cleanup.enter_context(TemporaryDirectory(dir='.', prefix='native-'))
        options = {**_options(), 'format': 'bestaudio/best', 'outtmpl': '-',
                   'ffmpeg_location': no_external,
                   'progress_hooks': [_LOGGER.progress],
                   'retries': 2 if provider == 'youtube' else 0,
                   'match_filter': full_track, 'logtostderr': True}
        client = cleanup.enter_context((StreamingYoutubeDL if provider == 'youtube' else YoutubeDL)(options))
        if provider != 'youtube':
            if client.download([url]):
                raise ValueError('source_unavailable')
            return
        # Public sources keep anonymous extraction's faster client selection.
        # Metadata-only extraction cannot have emitted media to stdout yet.
        _LOGGER.code = 'source_unavailable'
        try:
            info = client.extract_info(url, download=False)
        except DownloadError:
            if _LOGGER.code != 'source_auth_required':
                raise
            cookies = _youtube_cookie_stream()
            if cookies is None:
                raise
            cleanup.enter_context(cookies)
            client = cleanup.enter_context(StreamingYoutubeDL({**options, 'cookiefile': cookies}))
            _LOGGER.code = 'source_unavailable'
            info = client.extract_info(url, download=False)
        if (not isinstance(info, dict) or info.get('_type', 'video') != 'video'
                or info.get('id') != identity or not isinstance(info.get('url'), str)):
            raise ValueError('source_unavailable')
        # Native extraction has already merged the selected bestaudio/best
        # format into this resolved result. Download it exactly once. Errors
        # from here onward never enter the authentication fallback above.
        available_at = info.get('available_at')
        if type(available_at) in (int, float) and math.isfinite(available_at):
            # yt-dlp enforces this server-provided preroll wait. Tell the owner
            # its numeric duration before the native downloader sleeps; no URL,
            # account data or media bytes cross this diagnostic boundary.
            wait_ms = math.ceil(max(0, available_at - int(time.time())) * 1000)
            if wait_ms > 60000:
                _LOGGER.code = 'source_wait_exceeds_budget'
                raise ValueError('source_wait_exceeds_budget')
            if wait_ms:
                print(json.dumps({'event': 'source_wait', 'wait_ms': wait_ms}),
                      file=sys.stderr, flush=True)
        _LOGGER.phase = 'download'
        if info.get('protocol') in {'http', 'https'}:
            client.stream_url = Request(info['url']).url
        client.process_info(info)
        if info.get('__pending_error'):
            raise ValueError('source_unavailable')


if __name__ == '__main__':
    try:
        if len(sys.argv) not in (3, 4):
            raise ValueError('invalid_operation')
        if sys.argv[1] == 'search' and len(sys.argv) == 3:
            print(json.dumps(_search(sys.argv[2]), ensure_ascii=True))
        elif sys.argv[1] == 'search-next' and len(sys.argv) == 3:
            print(json.dumps(_search(sys.argv[2], count=20, limit=20), ensure_ascii=True))
        elif sys.argv[1] == 'stream' and len(sys.argv) == 4:
            _stream(sys.argv[2], sys.argv[3])
        else:
            raise ValueError('invalid_operation')
    except Exception as error:
        # Upstream exceptions may contain signed delivery URLs: never log them.
        print(json.dumps({'code': _LOGGER.code, 'error_class': type(error).__name__[:64],
                          'errno': error.errno if isinstance(error, OSError) else None,
                          'phase': _LOGGER.phase, 'downloaded_bytes': _LOGGER.downloaded_bytes,
                          'expected_bytes': _LOGGER.expected_bytes}),
              file=sys.stderr)
        sys.exit(1)
