"""Shared public music discovery and an owned best-audio byte source.

Only canonical public track identities cross the playback boundary. yt-dlp keeps
expiring delivery URLs inside its child process; neither the Agent nor receipts
receive them. The destination owns the streaming child and its lifetime.
"""
from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import re
import signal
import stat
import sys
from pathlib import Path

from .config import MediaUnavailable

VIDEO_ID = re.compile(r'[A-Za-z0-9_-]{11}')
TRACK_ID = re.compile(r'[0-9]{1,20}')


class _Quiet:
    code = 'source_unavailable'

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
                ('source_timeout', ('timed out', 'timeout'))):
            if any(fragment in text for fragment in fragments):
                self.code = code
                break


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


def _search(query: str) -> list[dict]:
    from yt_dlp import YoutubeDL
    versions = re.compile(r'\b(cover|remix|bootleg|karaoke|instrumental|extended|rework|sped|slowed|mashup|nightcore|tribute|live|acoustic)\b', re.I)
    requested_versions = {word.casefold() for word in versions.findall(query)}
    rows = []
    with YoutubeDL({**_options(), 'extract_flat': 'in_playlist', 'playlistend': 5}) as client:
        result = client.extract_info('ytsearch5:' + query + ' official audio', download=False)
        for entry in (result or {}).get('entries') or []:
            video = entry.get('id', '')
            title = _text(entry.get('title'))
            if (not isinstance(video, str) or not VIDEO_ID.fullmatch(video) or not title
                    or {word.casefold() for word in versions.findall(title)} - requested_versions):
                continue
            duration = entry.get('duration')
            if type(duration) in (int, float) and not 45 < duration < 86400:
                continue
            rows.append({'provider': 'youtube', 'video_id': video, 'title': title,
                         'artist': _text(entry.get('uploader') or entry.get('channel'), 80),
                         'verified_channel': entry.get('channel_is_verified') is True,
                         'duration_seconds': round(duration) if type(duration) in (int, float) else None})
    # Provider metadata is not acoustic verification. Prefer verified channels,
    # keep the exact video identity, and never substitute another music service.
    return sorted(rows, key=lambda row: (not row['verified_channel'],
                  not bool(re.search(r'\bofficial audio\b', row['title'], re.I))))[:3]


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
    from yt_dlp.utils import DownloadError
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
    with contextlib.ExitStack() as cleanup:
        no_external = cleanup.enter_context(TemporaryDirectory(dir='.', prefix='native-'))
        options = {**_options(), 'format': 'bestaudio/best', 'outtmpl': '-',
                   'ffmpeg_location': no_external,
                   'match_filter': full_track, 'logtostderr': True}
        client = cleanup.enter_context(YoutubeDL(options))
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
            client = cleanup.enter_context(YoutubeDL({**options, 'cookiefile': cookies}))
            _LOGGER.code = 'source_unavailable'
            info = client.extract_info(url, download=False)
        if (not isinstance(info, dict) or info.get('_type', 'video') != 'video'
                or info.get('id') != identity or not isinstance(info.get('url'), str)):
            raise ValueError('source_unavailable')
        # Native extraction has already merged the selected bestaudio/best
        # format into this resolved result. Download it exactly once. Errors
        # from here onward never enter the authentication fallback above.
        client.process_info(info)
        if info.get('__pending_error'):
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
    except Exception as error:
        # Upstream exceptions may contain signed delivery URLs: never log them.
        print(json.dumps({'code': _LOGGER.code, 'error_class': type(error).__name__[:64],
                          'errno': error.errno if isinstance(error, OSError) else None}),
              file=sys.stderr)
        sys.exit(1)
