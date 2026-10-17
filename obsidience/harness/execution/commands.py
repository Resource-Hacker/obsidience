"""Literal single-command recognition; the capability core still owns effects."""
from __future__ import annotations

from functools import lru_cache
import re
import unicodedata

from hassil import Intents, recognize_all

from ..capabilities.lights.set import TARGETS


@lru_cache(maxsize=1)
def _clock_intents():
    return Intents.from_dict({
        'language': 'en',
        'intents': {'LocalTime': {'data': [{'sentences': [
            '[please] what time is it [now|right now] [please]',
            '[please] (what is|what\'s) the [current|local] time [please]',
            '[please] (tell me|can you tell me) (the [current|local] time|what time it is) [please]',
        ]}]}},
    })


def _clock_command(text):
    # This finite informational grammar may end in a question mark. Do not
    # loosen punctuation or clause checks for commands that change devices.
    text = text.rstrip('?')
    if not re.fullmatch(r"[a-z' ]+", text):
        return None
    if not any(recognize_all(text, _clock_intents())):
        return None
    from ..conversation.context_bindings import local_clock
    return {'name': 'task.complete', 'args': {
        'status': 'completed', 'summary': f"It is {local_clock()['time']}."}}


@lru_cache(maxsize=1)
def _light_intents():
    values = []
    for target in TARGETS:
        aliases = ({'lights', 'all lights', 'all the lights', 'room lights', 'all room lights'}
                   if target == 'all' else {target, target.replace('_', ' ')})
        aliases |= {'the ' + alias for alias in aliases if not alias.startswith(('all ', 'the '))}
        values.extend({'in': alias, 'out': target} for alias in sorted(aliases))
    return Intents.from_dict({
        'language': 'en',
        'lists': {'target': {'values': values}, 'state': {'values': ['on', 'off']}},
        'intents': {'LightPower': {'data': [{'sentences': [
            '[please] {target} {state} [please]',
            '[please] (turn|switch) {state} {target} [please]',
            '[please] (turn|switch) {target} {state} [please]',
        ]}]}},
    })


@lru_cache(maxsize=1)
def _media_intents():
    return Intents.from_dict({
        'language': 'en',
        'lists': {
            'media': {'values': ['music', 'audio', 'video', 'playback', 'youtube',
                                 'youtube video', 'jazz', 'jazz music']},
        },
        'intents': {
            'PauseMedia': {'data': [{'sentences': [
                '[please] (pause|stop) [the] {media} [please]',
                '[please] stop playing [please]',
            ]}]},
            'PausePlayingMedia': {'data': [{'sentences': [
                '[please] (stop|pause) playing [the] {media} [please]',
            ]}]},
        },
    })


def _media_command(text):
    # Only complete phrases in the finite grammar enter this lane. Other titles
    # and any extra clauses require ordinary generation. Named media filters
    # fresh metadata only; it never chooses a bus or method.
    choices = set()
    for result in recognize_all(text, _media_intents()):
        entity = result.entities.get('media')
        query = str(entity.value) if entity else ''
        if query in {'music', 'audio', 'video', 'playback'}:
            query = ''
        elif query == 'youtube video':
            query = 'youtube'
        elif query == 'jazz music':
            query = 'jazz'
        choices.add(query)
    if len(choices) != 1:
        return None
    return {'name': 'media.pause', 'args': {'query': choices.pop()}}


@lru_cache(maxsize=1)
def _discord_media_intents():
    target = '[it|that|[the] (music|audio|playback|song)]'
    return Intents.from_dict({
        'language': 'en',
        'intents': {
            **{name: {'data': [{'sentences': [f'[please] ({verbs}) {target} [please]']}]}
               for name, verbs in (('DiscordPause', 'pause'), ('DiscordResume', 'resume|unpause'),
                                   ('DiscordStop', 'stop|stop playing'))},
            'DiscordContinue': {'data': [{'sentences': [
                '[please] (keep|continue) playing [[the] music] [please]',
            ]}]},
        },
    })


def recognize_discord_command(objective, allowed):
    """One complete literal control; the caller must bind the Discord principal."""
    if (not isinstance(objective, str) or len(objective) > 100
            or not {'discord.control', 'task.complete'}.issubset(allowed)):
        return None
    text = ' '.join(objective.casefold().split()).rstrip('.!')
    if not re.fullmatch(r'[a-z ]+', text):
        return None
    if text in {'no', 'nope', 'no thanks', 'no thank you'}:
        return {'name': 'task.complete', 'args': {'status': 'completed', 'summary': 'Okay.'},
                'declined_music': True}
    actions = {'DiscordPause': 'pause', 'DiscordResume': 'resume', 'DiscordStop': 'stop',
               'DiscordContinue': 'continue'}
    choices = {actions[result.intent.name] for result in recognize_all(text, _discord_media_intents())}
    if len(choices) != 1:
        return None
    action = choices.pop()
    return ({'operation': 'discord_continue'} if action == 'continue' else
            {'name': 'discord.control', 'args': {'action': action}})


@lru_cache(maxsize=1)
def _discord_music_intents():
    return Intents.from_dict({
        'language': 'en',
        'lists': {'music_title': {'wildcard': True}, 'music_artist': {'wildcard': True}},
        'intents': {'DiscordMusic': {'data': [{'sentences': [
            '[please] play {music_title} by {music_artist} [please]',
        ]}]}},
    })


def recognize_discord_music(objective, allowed, *, voice=False):
    """Explicit music slots; selection still requires fresh exact metadata."""
    if (not isinstance(objective, str) or len(objective) > 240
            or not {'media.library', 'discord.control', 'task.complete'}.issubset(allowed)):
        return None
    text = ' '.join(objective.split()).rstrip('.!')
    # Observed spoken "play" -> "plate" error. Only an addressed voice
    # activation may use this correction, and only exact fresh music identity
    # can authorize its playback. Keep the actual transcript unchanged.
    corrected = voice and re.match(r'^(?:please )?plate ', text, re.I) is not None
    if corrected:
        text = re.sub(r'^(please )?plate ', lambda match: (match[1] or '') + 'play ', text, flags=re.I)
    choices = {(str(result.entities['music_title'].value).strip(),
                str(result.entities['music_artist'].value).strip())
               for result in recognize_all(text, _discord_music_intents())}
    if not choices:
        plain = re.fullmatch(r'(?:please )?play (?:some )?(.+?)(?: please)?', text, re.I)
        if plain and 0 < len(query := plain[1].strip()) <= 115:
            # ASR spells this artist's spoken name as the ordinary homophone.
            # This exact voice-only alias still requires fresh verified artist
            # metadata; it never changes a title or admits general fuzzy matches.
            if voice and query.casefold() == 'the weekend':
                query = 'The Weeknd'
            return {'query': query, **({'requires_exact': True} if corrected else {})}
        return None
    if len(choices) != 1:
        return None
    title, artist = choices.pop()
    if not title or not artist or len(title + artist) > 115:
        return None
    if voice and artist.casefold() == 'the weekend':
        artist = 'The Weeknd'
    return {'title': title, 'artist': artist, **({'requires_exact': True} if corrected else {})}


def _music_identity(value):
    return ' '.join(re.findall(r'[^\W_]+', unicodedata.normalize('NFKC', value).casefold()))


_MUSIC_GENRES = frozenset({
    'synthwave', 'synth wave', 'retrowave', 'vaporwave', 'lofi', 'lo fi',
    'jazz', 'ambient', 'classical', 'techno', 'trance', 'house', 'disco',
    'hip hop', 'hiphop', 'rock', 'pop', 'country', 'reggae', 'drum and bass',
})


def exact_discord_music(request, candidates):
    """Select one exact official recording at the best presentation rank.

    Only a leading verified channel artist, credited collaborators and finite
    presentation decorations are removed. Live/remix/remaster/cover/version
    words remain part of identity.
    """
    query_only = 'query' in request
    wanted_artist = _music_identity(request['query'] if query_only else request['artist'])
    wanted_title = _music_identity(request['query'] if query_only else request['title'])
    genre = re.sub(r' music$', '', wanted_title)
    if query_only and not request.get('requires_exact') and genre in _MUSIC_GENRES:
        # A literal genre asks for a relevant recording, not one exact artist.
        # Use fresh search order only when the title explicitly names that genre.
        aliases = {genre}
        if genre in {'synthwave', 'synth wave', 'lofi', 'lo fi', 'hiphop', 'hip hop'}:
            aliases |= {word for word in _MUSIC_GENRES if word.replace(' ', '') == genre.replace(' ', '')}
        for row in candidates:
            if (isinstance(row, dict) and row.get('provider') == 'youtube'
                    and isinstance(row.get('title'), str) and isinstance(row.get('artist'), str)
                    and isinstance(row.get('id'), str)
                    and type(row.get('duration_seconds')) in {int, float}
                    and 45 <= row['duration_seconds'] <= 86400
                    and any(f' {word} ' in f' {_music_identity(row["title"])} ' for word in aliases)):
                return row
    valid = []
    for row in candidates:
        if (not isinstance(row, dict) or row.get('provider') != 'youtube'
                or row.get('verified_channel') is not True
                or not isinstance(row.get('artist'), str) or not isinstance(row.get('title'), str)
                or not isinstance(row.get('id'), str)
                or not query_only and _music_identity(row['artist']) != wanted_artist):
            continue
        valid.append(row)
    if query_only and not request.get('requires_exact'):
        # Any recording by this exact verified artist satisfies an artist-only
        # request. Preserve the provider's relevance order; never infer aliases.
        artists = [row for row in valid if _music_identity(row['artist']) == wanted_artist]
        if artists:
            return artists[0]
    matches = []
    for row in valid:
        title, rank, label = row['title'], 1, ''
        decoration = re.fullmatch(r'(.+?)\s*[\(\[](official audio|official music video|official video|(?:official )?lyric video)[\)\]]',
                                  title, re.I)
        if decoration:
            title = decoration[1]
            label = decoration[2].casefold()
            rank = 0 if label == 'official audio' else 2 if 'lyric' in label else 3
        artist = _music_identity(row['artist'])
        credits = re.fullmatch(r'(.+?)\s+[-–—]\s+(.+)', title)
        artist_credited = False
        if credits:
            # Official artist uploads often credit collaborators before the
            # title, e.g. "Artist, Guest - Song". An unrelated verified lyric
            # channel must not gain the performer's identity from that text.
            credited = re.split(r'\s*(?:,|&|\b(?:and|with|feat\.?|ft\.?)\b)\s*', credits[1], maxsplit=1, flags=re.I)[0]
            if _music_identity(credited) == artist:
                title = credits[2]
                artist_credited = True
        if 'lyric' in label and query_only and not artist_credited:
            continue
        identity = _music_identity(title)
        if identity.startswith(artist + ' '):
            identity = identity[len(artist) + 1:]
        if identity == wanted_title:
            matches.append((rank, row))
    if not matches:
        return None
    # A title without an artist must resolve to one artist/recording identity
    # before presentation ranking; two artists with the same song need judgment.
    if query_only and len({_music_identity(row['artist']) for _, row in matches}) != 1:
        return None
    rank = min(value for value, _ in matches)
    best = {row['id']: row for value, row in matches if value == rank}
    return next(iter(best.values())) if len(best) == 1 else None


# Each literal TV media phrase maps to one target state the TV reads back.
_TV_ACTIONS = {'TVPause': 'pause', 'TVPlay': 'resume', 'TVMute': 'mute', 'TVUnmute': 'unmute'}


@lru_cache(maxsize=1)
def _tv_intents():
    tv = '[the] (tv|television)'
    return Intents.from_dict({
        'language': 'en',
        'lists': {'state': {'values': ['on', 'off']}, 'direction': {'values': ['up', 'down']},
                  # Digits or words: "15", "fifteen", "twenty five".
                  'level': {'range': {'from': 0, 'to': 100}}},
        'intents': {
            'TVLevel': {'data': [{'sentences': [
                f'[please] [set|turn] {tv} volume [to] {{level}} [please]',
                f'[please] [set|turn] [the] volume [to] {{level}} on {tv} [please]',
            ]}]},
            'TVPower': {'data': [{'sentences': [
                '[please] [the] (tv|television) {state} [please]',
                '[please] (turn|switch) {state} [the] (tv|television) [please]',
                '[please] (turn|switch) [the] (tv|television) {state} [please]',
            ]}]},
            'TVPause': {'data': [{'sentences': [f'[please] pause {tv} [please]']}]},
            'TVPlay': {'data': [{'sentences': [f'[please] (play|resume|unpause) {tv} [please]']}]},
            'TVMute': {'data': [{'sentences': [f'[please] mute {tv} [please]']}]},
            'TVUnmute': {'data': [{'sentences': [f'[please] unmute {tv} [please]']}]},
            'TVVolume': {'data': [{'sentences': [
                f'[please] [turn] {tv} volume {{direction}} [please]',
                f'[please] turn {tv} {{direction}} [please]',
                f'[please] turn {{direction}} {tv} [volume] [please]',
                f'[please] [turn] [the] volume {{direction}} on {tv} [please]',
                f'[please] turn {{direction}} [the] volume on {tv} [please]',
            ]}]},
        },
    })


def _tv_command(text):
    choices = set()
    for result in recognize_all(text, _tv_intents()):
        name = result.intent.name
        choices.add((('action', result.entities['state'].value),) if name == 'TVPower' else
                    (('action', 'volume'), ('level', int(result.entities['level'].value))) if name == 'TVLevel' else
                    (('action', 'volume_' + result.entities['direction'].value),)
                    if name == 'TVVolume' else (('action', _TV_ACTIONS[name]),))
    return {'name': 'tv.control', 'args': dict(choices.pop())} if len(choices) == 1 else None


def recognize_command(objective, allowed):
    """Return one complete registered call, or ordinary native generation.

    Light targets are literal. Named media is only a current metadata filter.
    Quoted, conditional, negated and compound requests fall through.
    """
    if not isinstance(objective, str) or len(objective) > 100:
        return None
    # A question mark can make a bare state phrase informational. Preserve it
    # so the native conversation decides; ASR terminal periods remain accepted.
    text = ' '.join(objective.casefold().split()).rstrip('.!')
    if 'task.complete' in allowed and (clock := _clock_command(text)) is not None:
        return clock
    # Digits and hyphens appear only in TV volume levels ("15", "twenty-five").
    if not re.fullmatch(r'[a-z0-9_ -]+', text):
        return None
    if 'tv.control' in allowed and (tv := _tv_command(text)) is not None:
        return tv
    if 'media.pause' in allowed and (media := _media_command(text)) is not None:
        return media
    if 'lights.set' not in allowed:
        return None
    choices = set()
    for result in recognize_all(text, _light_intents()):
        target = result.entities.get('target')
        state = result.entities.get('state')
        if (result.intent.name != 'LightPower' or target is None or state is None
                or target.value not in TARGETS or state.value not in ('on', 'off')):
            return None
        choices.add((target.value, state.value))
        if len(choices) > 1:
            return None
    if not choices:
        return None
    target, state = choices.pop()
    return {'name': 'lights.set', 'args': {'target': target, 'state': state}}


def _media_selection(selected: object) -> dict:
    from uuid import UUID
    if not isinstance(selected, dict) or set(selected) != {'item_id', 'media_source_id', 'source_revision'}:
        raise ValueError('Choose the exact selected catalogue source')
    try:
        item = UUID(selected['item_id']).hex
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Invalid catalogue item') from None
    if (not isinstance(selected['media_source_id'], str)
            or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', selected['media_source_id'])
            or not isinstance(selected['source_revision'], str)
            or not re.fullmatch(r'[0-9a-f]{64}', selected['source_revision'])):
        raise ValueError('Invalid catalogue source revision')
    return {**selected, 'item_id': item}


def owner_media_command(value: object) -> dict:
    """Closed native owner UI protocol. It grants no Tools or identity."""
    import math
    from uuid import UUID
    if not isinstance(value, dict):
        raise ValueError('Media command must be an object')
    try:
        request_id = str(UUID(value['request_id']))
    except (KeyError, ValueError, TypeError, AttributeError):
        raise ValueError('Media command requires one request UUID') from None
    operation = value.get('operation')
    if operation in ('acquire', 'refresh_source'):
        if (set(value) != {'request_id', 'operation', 'preview_token'}
                or not isinstance(value.get('preview_token'), str)
                or not re.fullmatch(r'[0-9a-f]{32}', value['preview_token'])):
            raise ValueError('Source operation requires one exact, unexpired source choice')
        return {'request_id': request_id, 'operation': operation, 'preview_token': value['preview_token']}
    if operation == 'play_season':
        if (set(value) != {'request_id', 'operation', 'destination', 'imdb_id', 'season', 'mode'}
                or value.get('destination') != 'tv'
                or not isinstance(value.get('imdb_id'), str)
                or not re.fullmatch(r'tt[0-9]{7,10}', value['imdb_id'])
                or type(value.get('season')) is not int or not 1 <= value['season'] <= 99
                or value.get('mode') not in ('first', 'next_unwatched')):
            raise ValueError('Season playback requires an exact series, season and playback mode')
        return {**value, 'request_id': request_id}
    if operation == 'server':
        if set(value) not in ({'request_id', 'operation'}, {'request_id', 'operation', 'selection'}):
            raise ValueError('Invalid media server command')
        return {'request_id': request_id, 'operation': operation, **(
            {'selection': _media_selection(value['selection'])} if 'selection' in value else {})}
    if operation == 'cast':
        # One YouTube video from the browser, by tv.control's own link rule; only its id is kept.
        from urllib.parse import urlsplit
        from ..capabilities.tv.control import youtube_id
        url = value.get('url')
        video = youtube_id(url) if isinstance(url, str) and len(url) <= 300 else None
        if (value.get('destination') != 'tv' or video is None
                or set(value) not in ({'request_id', 'operation', 'destination', 'url'},
                                      {'request_id', 'operation', 'destination', 'url', 'start'})):
            raise ValueError('Cast takes one YouTube video link for the registered TV')
        live = urlsplit(url).path.startswith('/live/')
        if 'start' in value and (type(value['start']) is not int or not 0 <= value['start'] <= 86400 or live):
            raise ValueError('Cast start must be whole seconds between 0 and 86400 of a video, not a live stream')
        return {'request_id': request_id, 'operation': operation, 'destination': 'tv',
                'url': ('https://www.youtube.com/live/' if live else 'https://www.youtube.com/watch?v=') + video,
                **({'start': value['start']} if 'start' in value else {})}
    if operation not in {'play', 'pause', 'resume', 'seek', 'stop'} or value.get('destination') != 'tv':
        raise ValueError('Choose the registered TV destination and one media operation')
    expected = {'request_id', 'operation', 'destination', 'selection'} if operation == 'play' else {
        'request_id', 'operation', 'destination', 'generation', 'source'} | ({'position'} if operation == 'seek' else set())
    if set(value) != expected and not (operation == 'play' and set(value) == expected | {'resume'}):
        raise ValueError('Invalid media command fields')
    result = {**value, 'request_id': request_id}
    if operation == 'play':
        if type(value.get('resume', False)) is not bool:
            raise ValueError('Saved resume must be a boolean')
        result['resume'] = value.get('resume', False)
        result['selection'] = _media_selection(value['selection'])
    else:
        source = value['source']
        fields = {'provider', 'root_id', 'revision', 'catalogue_instance', 'item_id', 'media_source_id', 'source_revision'}
        if (not isinstance(value['generation'], str) or not re.fullmatch(r'[0-9a-f]{32}', value['generation'])
                or not isinstance(source, dict) or set(source) != fields or source['provider'] != 'local'
                or any(not isinstance(v, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', v)
                       for v in source.values())
                or not re.fullmatch(r'[0-9a-f]{64}', source['revision'])
                or not re.fullmatch(r'[0-9a-f]{64}', source['source_revision'])):
            raise ValueError('Control requires the observed local generation and exact source')
        result['source'] = dict(source)
        if operation == 'seek' and (type(value['position']) not in (int, float)
                                   or not math.isfinite(value['position']) or not 0 <= value['position'] <= 86400):
            raise ValueError('Seek position must be between 0 and 86400 seconds')
    return result


def owner_media_text(command: dict) -> str:
    return ('Refresh catalogue visibility for the exact already registered source.' if command['operation'] == 'refresh_source' else
            f"Play season {command['season']} of series {command['imdb_id']} on the registered TV using {command['mode']}."
                if command['operation'] == 'play_season' else
            'Register the exact source selected in the Media pane in the library.' if command['operation'] == 'acquire' else
            'Open the selected library item in Jellyfin.' if command['operation'] == 'server' and command.get('selection') else
            'Open the configured media server.' if command['operation'] == 'server' else
            'Resume the selected library source from its saved position on the registered TV.'
                if command['operation'] == 'play' and command.get('resume') else
            'Play the selected library source on the registered TV.' if command['operation'] == 'play' else
            f"Play the YouTube video {command['url']} from the browser on the registered TV"
                + (f" from {command['start']} seconds." if command.get('start') else '.')
                if command['operation'] == 'cast' else
            f"{command['operation'].capitalize()} the observed library playback on the registered TV.")
