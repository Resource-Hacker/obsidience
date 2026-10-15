"""A named movie or series for a playback destination: the owner's Media server first.

Owner decisions 2026-10-15: "put <show or movie> on" plays from the Jellyfin
library; a series with no episode named plays its next unwatched episode (S1E1
when never watched); a title absent from the library is registered through the
media server under the accepted best-source policy and then played. This module
only resolves: it returns an activation-scoped selection (m...) or season plan
(s...) for the destination's existing open/open_season contract, or a final
not-dispatched/pending result. It never starts playback and never guesses
between choices.

Registration is a real external effect, so it happens only for a request that is
clearly one named title (deterministic rules, no model call):
- a request made only of generic content words ("music", "some music", "a movie") is not
  a title, even when a film has that name: it keeps play's Pluto/YouTube chooser, and the
  owner names such a film with its year ("Music 2021");
- a request that ends in a content noun ("a superhero movie") describes rather than
  names: unless it is exactly a library title it never registers, even when the
  catalogue holds a title of that name ("Superhero Movie"); its rows become choices;
- an exact library title plays; a library series whose name contains the request but
  is not it ("Star Trek" or "Voyager" -> Star Trek: Voyager) never lets a catalogue
  title of that name register: the owner chooses between them. Only a series whose name
  begins with a request of two or more words plays, when it is the only such library
  title and the metadata catalogue has no title of exactly that name;
- an absent title needs exactly one exact metadata-catalogue title (any other
  number returns choices), and a source the media server already holds for it is
  refreshed (media.acquire refresh), never registered a second time;
- the registration is this turn's media.acquire capability call (its own grant,
  scope check, receipt and attempt keys). The whole call ends by DEADLINE_SECONDS with a
  truthful pending result; a registration starts only with _REGISTER_RESERVE left, which
  covers its bounded path (TorBox account, inventory and cache reads, then a create of at
  most 35 s). The deadline only signals the registration's cancel event once TorBox has
  confirmed it; the bounded steps already running (organize verification, the 12 s TorBox
  file refresh) finish first, so the call ends within about ten seconds of the deadline
  (about 85 s) at worst. The reads before a registration are not cut by the deadline; they
  only make it refuse when less than _REGISTER_RESERVE is left.
"""
from __future__ import annotations

import asyncio
import re
import threading
import time
import unicodedata

from ...media import discovery, service
from ...media import season as seasons
from ...media.config import MediaUnavailable, load_config
from .library import bind

WAIT_SECONDS = 30.0
DEADLINE_SECONDS = 75.0  # The whole play-with-acquisition resolution; a voice turn waits for it.
_REGISTER_RESERVE = 50.0  # A registration starts only with this much of the deadline left.
_TRANSIENT = {None, 'catalogue_source_pending', 'catalogue_readback_unavailable',
              'catalogue_refresh_uncertain', 'catalogue_readback_limit'}
_SPEC = (re.compile(r'\bs(\d{1,2})\s*e(\d{1,3})\b', re.I),
         re.compile(r'\b(\d{1,2})x(\d{2,3})\b', re.I),
         re.compile(r'\bseason\s+(\d{1,2})(?:\s*,?\s*(?:episode|ep)\s+(\d{1,3}))?\b', re.I))
# Words that name a kind of content rather than a title. A request made only of these and
# filler is generic: it never resolves to (or registers) a catalogue title such as "Music" (2021).
GENERIC = frozenset({
    'music', 'song', 'songs', 'tune', 'tunes', 'something', 'anything', 'movie', 'movies', 'film', 'films',
    'show', 'shows', 'series', 'episode', 'episodes', 'cartoon', 'cartoons', 'anime', 'sports', 'sport',
    'game', 'games', 'tv', 'television', 'video', 'videos', 'clip', 'clips', 'news', 'weather', 'channel',
    'channels', 'live', 'stream', 'livestream', 'radio', 'podcast', 'podcasts', 'documentary',
    'documentaries', 'comedy', 'kids', 'stuff', 'content', 'background', 'noise'})
_GENERIC_FILLER = frozenset({'the', 'a', 'an', 'some', 'any', 'on', 'to', 'me', 'us', 'for', 'of', 'please',
                             'put', 'play', 'watch', 'good', 'new', 'random', 'that', 'this', 'with', 'and'})
# Nouns that end a description ("a superhero movie") rather than a title.
_KIND_NOUNS = frozenset({'movie', 'movies', 'film', 'films', 'show', 'shows', 'series', 'cartoon', 'cartoons',
                         'documentary', 'documentaries', 'episode', 'episodes'})


def tokens(text: str) -> list[str]:
    """Whole words of a title, without bracketed release tags or a leading article."""
    text = unicodedata.normalize('NFKC', text).casefold().replace('&', ' and ')
    words = re.findall(r'[^\W_]+', re.sub(r'\([^)]*\)|\[[^\]]*\]', ' ', text))
    return words[1:] if len(words) > 1 and words[0] in ('the', 'a', 'an') else words


def spec(query: str) -> tuple[str, int | None, int | None]:
    """(title, season, episode) from a request such as "Voyager season 2 episode 3"."""
    text = query.strip()
    bare = re.sub(r'\s+on\s+(?:the\s+)?(?:tv|television)\s*$', '', text, flags=re.I)
    if bare != text:  # The whole phrase "put Star Trek on the TV": its verb is not part of the title.
        bare = re.sub(r'^(?:please\s+)?(?:put|play|watch)\s+(?:on\s+)?(?=\S)', '', bare, flags=re.I)
    text = bare
    for pattern in _SPEC:
        match = pattern.search(text)
        if match:
            season, episode = int(match[1]), int(match[2]) if match[2] else None
            title = (text[:match.start()] + ' ' + text[match.end():]).strip(' ,-:')
            if title and 1 <= season <= 99 and (episode is None or 1 <= episode <= 999):
                return title, season, episode
    return text, None, None


def _words(query: str) -> list[str]:
    return re.findall(r'[^\W_]+', unicodedata.normalize('NFKC', spec(query)[0]).casefold())


def generic(query: str) -> bool:
    """Whether a request names only a kind of content ("put some music on", "cartoons")."""
    return not set(_words(query)) - _GENERIC_FILLER - GENERIC


def described(query: str) -> bool:
    """Whether a request ends in a content noun ("a superhero movie"): a description, not a title."""
    words = _words(query)
    return bool(words) and words[-1] in _KIND_NOUNS


def match_titles(query: str, rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """(exact, partial) rows for a title: exact (optionally with a trailing year), else
    the rows whose title contains the words contiguously. A partial row is a different
    title ("Toy Story" in "Toy Story 2"); only the caller may decide it stands for one.
    """
    wanted = tokens(query)
    if not wanted:
        return [], []
    variants = [(wanted, None)]
    if len(wanted) > 1 and re.fullmatch(r'(?:19|20)\d{2}', wanted[-1]):
        variants.append((wanted[:-1], int(wanted[-1])))
    for words, year in variants:
        exact = [row for row in rows if tokens(row['title']) == words
                 and (year is None or row['year'] == year)]
        if exact:
            return exact, []
    for words, year in variants:
        size = len(words)
        partial = [row for row in rows if (year is None or row['year'] == year) and any(
            tokens(row['title'])[i:i + size] == words for i in range(len(tokens(row['title'])) - size + 1))]
        if partial:
            return [], partial
    return [], []


async def _search(title: str, kind: str, context: dict) -> tuple[list[dict], list[dict]]:
    """(exact, near) metadata-catalogue titles, searched once per run (the discovery call budget
    is shared). near: the partial matches, else the catalogue's own results ("Oceans Eleven")."""
    pages = context.setdefault('_tv_title_searches', {})
    key = (tuple(tokens(title)), kind)
    if key not in pages:
        page = await discovery.search(title, kind, context)
        # A page cut by the activation's record cap may hide a second exact title: fail closed.
        pages[key] = None if page.get('truncated') else page['matches']
        if pages[key] is not None:
            # Same-named titles ranked past the result cap ("The Thing" 1982 and 2011) count too.
            unlisted = (context.get('_media_discovery_unlisted') or {}).get((kind, title.strip()), [])
            lower = match_titles(title, unlisted)[0]
            if len(lower) == 1 and not match_titles(title, pages[key])[0]:
                # The only exact title ranked lower: look it up by IMDb id for its candidate record.
                found = await discovery.search(lower[0]['imdb_id'], kind, context)
                lower = None if found.get('truncated') else found['matches']
            pages[key] = None if lower is None else pages[key] + lower
    if pages[key] is None:
        raise MediaUnavailable('media_discovery_record_limit')
    exact, partial = match_titles(title, pages[key])
    return exact, [] if exact else partial or pages[key]


async def _catalogue(title: str, season: int | None, context: dict) -> tuple[list[dict], list[dict]]:
    found, near = [], []
    for kind in ('series',) if season is not None else ('movie', 'series'):
        exact, others = await _search(title, kind, context)
        found += exact
        near += others
    return found, near


async def _catalogue_exact(title: str, season: int | None, context: dict) -> list[dict]:
    return (await _catalogue(title, season, context))[0]


def named(query: str, context: dict, *, catalogue: bool) -> bool | None:
    """Whether the request's title is exactly a library title or, with catalogue, a metadata-
    catalogue title ("Live and Let Die", "News of the World"); read-only. None: a source could
    not be read, so it is unknown. The caller then keeps the request on the Media server route,
    whose own reads report the outage: a named title never falls to a live or web pick."""
    title = spec(query)[0]
    try:
        library = bool(match_titles(title, service.catalogue().titles())[0])
    except (MediaUnavailable, OSError, ValueError):
        library = None
    if library or not catalogue:
        return library
    try:
        listed = bool(asyncio.run(_catalogue_exact(title, None, context)))
    except (asyncio.CancelledError, MediaUnavailable, OSError, ValueError):
        return None
    return True if listed else library


def continue_season(progress: list[dict]) -> int:
    """The season a series continues in: that of the last watched episode, S1 when none was.

    Its season plan lists missing episodes as unwatched, so a missing tail of that season
    comes before any later season (never skip gaps); a complete season continues in the next.
    """
    played = [row for row in progress if row['played']]
    return played[-1]['season'] if played else 1


def _final(failure: str, *, correction: bool = True, **fields) -> dict:
    result = {'status': 'failed', 'delivery': 'not_dispatched', 'effect_applied': False,
              'route': 'library', 'failure': failure, **fields}
    if correction:
        result['correction_allowed'] = True
    else:
        result['must_not_replay'] = True
    return result


def _applied(result: dict) -> dict:
    """After a registration nothing in this call may be repeated: every outcome carries the effect."""
    result = {**result, 'effect_applied': True, 'must_not_replay': True}
    result.pop('correction_allowed', None)
    return result


def _ids(pairs, context: dict) -> list[str]:
    """Activation-only selection ids for exact (item, source) pairs; a stale source is left out."""
    ids = []
    for item_id, source_id in pairs:
        try:
            ids.append(bind(item_id, source_id, context)['id'])
        except MediaUnavailable:
            continue
    return ids


def _sources(row: dict) -> list[str]:
    """A matched Movie row's admitted source ids, read on demand (the inventory carries none)."""
    if 'sources' not in row:
        row['sources'], row['source_limit'] = service.catalogue().movie_sources(row['item_id'])
    return row['sources']


def _rows(rows: list[dict], context: dict) -> list[dict]:
    choices = []
    for row in rows[:8]:
        choice = {'type': row['type'].lower(), 'title': row['title'], 'year': row['year'], 'in_library': True}
        if row['type'] == 'Movie':
            choice['ids'] = _ids(((row['item_id'], source) for source in _sources(row)), context)
        choices.append(choice)
    return choices


def _catalogue_rows(rows: list[dict]) -> list[dict]:
    return [{**{key: row[key] for key in ('type', 'title', 'year', 'imdb_id')}, 'in_library': False}
            for row in rows[:8]]


_CHOOSE = ('Ask the owner which one. A library movie opens with tv.control open and its id; '
           'any other choice plays with play and its exact title followed by its year.')


def _choices(title: str, rows: list[dict], context: dict) -> dict:
    return _final(f'More than one library title matches "{title}"; nothing was played.', choices=_rows(rows, context),
                  note=_CHOOSE)


def _movie(row: dict, context: dict, extra: dict | None = None) -> dict:
    ids = _ids(((row['item_id'], source) for source in _sources(row)), context)
    summary = {'kind': 'movie', 'title': row['title'], 'year': row['year'], **(extra or {})}
    if len(ids) == 1:
        return {'status': 'ready', 'id': ids[0], **summary}
    if row.get('source_limit'):
        return _final(f'"{row["title"]}" has more editions than play lists; nothing was played.', library=summary,
                      note='Use media.library browse to list its editions, then tv.control open the chosen id.')
    if not ids:
        return _final(f'"{row["title"]}" is in the library without a playable local source.', library=summary)
    return _final(f'"{row["title"]}" has {len(ids)} editions; nothing was played.', library=summary,
                  choices=ids, note='Ask the owner which edition, then tv.control open that id.')


async def _metadata_id(imdb: str, context: dict) -> str:
    page = await discovery.search(imdb, 'series', context)
    matches = [row for row in page['matches'] if row['imdb_id'] == imdb]
    if len(matches) != 1:
        raise MediaUnavailable('discovery_series_identity_unavailable')
    return matches[0]['metadata_id']


def _meta(metadata_id: str, row: dict) -> dict:
    return {'metadata_id': metadata_id, 'imdb_id': row['imdb'], 'type': 'series',
            'title': row['title'], 'year': row['year']}


async def _series(row: dict, season: int | None, episode: int | None, context: dict,
                  metadata_id: str | None = None, extra: dict | None = None) -> dict:
    summary = {'kind': 'season', 'title': row['title'], 'year': row['year'], **(extra or {})}
    if not row['imdb']:
        return _final(f'"{row["title"]}" has no verified IMDb identity in the library.', library=summary)
    onward = False  # Continuing a watched series: a complete season continues in the next one.
    if season is None:
        progress = await asyncio.to_thread(service.catalogue().series_progress, row['item_id'])
        season = continue_season(progress)
        onward = any(item['played'] for item in progress)
    metadata_id = metadata_id or await _metadata_id(row['imdb'], context)
    plan = await seasons.plan(metadata_id, season, 'first' if episode else 'next_unwatched', context)
    if onward and plan.get('selected') is None and plan.get('selection') == 'season_complete':
        # The episode after a watched season is the next season's first; the roster, not the
        # library, says whether it exists (it may still need acquisition).
        try:
            plan = await seasons.plan(metadata_id, season + 1, 'next_unwatched', context)
        except MediaUnavailable as error:
            if str(error) not in ('discovery_season_incomplete_or_unavailable', 'media_season_not_yet_released'):
                raise
            return _final(f'Every released episode of "{row["title"]}" is watched; nothing was played.',
                          library=summary, note='Ask which season or episode to watch again.')
        season += 1
    if episode is None:
        selected = plan.get('selected')
        if selected is None:
            return _final(f'Season {season} of "{row["title"]}" has no unwatched released episode.',
                          library=summary, note='Ask which season or episode to watch again.')
        summary.update(season=season, episode=selected['episode'], episode_title=selected['title'],
                       sequence=plan['sequence']['count'])
        if plan.get('id'):
            return {'status': 'ready', 'id': plan['id'], **summary}
        if plan['sequence']['stop_reason'] != 'catalogue_episode_missing':
            return _final('The next episode has no unique library source: ' + str(plan['sequence']['stop_reason']),
                          library=summary)
        return {'status': 'absent', 'meta': _meta(metadata_id, row), 'season': season,
                'episode': selected['episode'], 'summary': summary}
    rows = [item for item in plan['episodes'] if item['episode'] <= episode <= item['episode_end']]
    if not rows:
        return _final(f'Season {season} of "{row["title"]}" lists no released episode {episode}.', library=summary)
    summary.update(kind='episode', season=season, episode=episode, episode_title=rows[0]['title'])
    choices = rows[0]['catalogue']
    if not choices:
        return {'status': 'absent', 'meta': _meta(metadata_id, row), 'season': season, 'episode': episode,
                'summary': summary}
    ids = _ids(((choice['item_id'], choice['media_source_id']) for choice in choices), context)
    if len(ids) == 1:
        return {'status': 'ready', 'id': ids[0], **summary}
    return _final('That episode has more than one library edition; nothing was played.', library=summary,
                  choices=ids, note='Ask the owner which edition, then tv.control open that id.')


async def _held(rows: list[dict], context: dict) -> tuple[bool, dict | None]:
    """Read-only: whether the media server already holds a registration of this exact title
    (for a series, one containing this episode), and the candidate row of that exact source.

    TorBox names every registration with its IMDb id ([imdbid-tt...]) in the account
    inventory; Tiramisu lists its registered library. A truncated or unreadable inventory
    raises: absence must be established before any new registration.
    """
    from ...media.tiramisu import Tiramisu, _episode_path_identity, _normal_hash
    privates = context['_media_acquisition_candidates']
    first = privates[rows[0]['candidate_id']]
    cancel = context.get('_capability_cancel_event')
    held = set()
    if first.get('debrid_binding') or load_config().get('debrid', {}).get('enabled'):
        from ...media.torbox import TorBoxAPI, _select
        tag = f'[imdbid-{first["imdb"]}]'
        for torrent in await TorBoxAPI().mylist(cancel=cancel):
            if tag in torrent['name'] and (first['type'] == 'movie' or _select(first, torrent['files'])):
                held.add(torrent['hash'])
    else:
        kind = 'movie' if first['type'] == 'movie' else 'tv'
        status, body = await Tiramisu()._request('GET', f'/api/library/list?type={kind}', cancel=cancel, timeout=6)
        if status != 200 or not isinstance(body, list) or len(body) > 20000:
            raise MediaUnavailable('tiramisu_reconcile_unavailable')
        for row in body:
            if isinstance(row, dict) and (row.get('imdb') == first['imdb'] if kind == 'movie' else (
                    _episode_path_identity(row.get('path'), first, require_hash=False)
                    == (first['season'], first['episode']))):
                held.add(_normal_hash(row.get('hash')))
    held.discard('')
    matching = next((row for row in rows if _normal_hash(privates[row['candidate_id']]['hash']) in held), None)
    return bool(held), matching


async def _bounded(call, context: dict):
    """Run the registration with a cancel event of its own: the turn's cancellation reaches it
    at once; the overall deadline only once the registration stands (TorBox has confirmed it),
    so it ends the catalogue refresh as pending and never makes a registration uncertain."""
    parent = context.get('_capability_cancel_event')
    child = threading.Event()
    context.pop('_media_registered_file', None)
    context['_capability_cancel_event'] = child
    task = asyncio.ensure_future(call)
    try:
        while not task.done():
            if ((parent is not None and parent.is_set())
                    or (time.monotonic() >= context['_tv_title_deadline'] and '_media_registered_file' in context)):
                child.set()
            await asyncio.wait((task,), timeout=.1)
        return task.result()
    finally:
        context['_capability_cancel_event'] = parent


async def _register(metadata_id: str, season: int | None, episode: int | None, context: dict) -> dict:
    """One media.acquire call under the accepted best-source policy: refresh for a source the
    media server already holds, otherwise register the unique recommended source."""
    nested = context.get('_nested_capability')
    if nested is None:
        return _final('Not in the library; acquisition needs this turn\'s media.acquire call path, '
                      'so nothing was registered.')
    page = await discovery.candidates(metadata_id, season=season, episode=episode, context=context)
    rows = page.get('candidates') or []
    if not rows:
        return _final('Not in the library, and no eligible source was found; nothing was registered.')
    held, row = await _held(rows, context)
    if held and row is None:
        return {'status': 'held'}
    action = 'refresh' if row is not None and (context['_media_acquisition_candidates'][row['candidate_id']]
                                               .get('debrid_binding')) else 'register'
    if row is None:
        if rows[0].get('recommended') is not True:
            return _final('Not in the library, and no unique recommended source exists; nothing was registered.',
                          sources=rows, note='Ask the owner which source to register with media.acquire register.')
        row = rows[0]
    if context['_tv_title_deadline'] - time.monotonic() < _REGISTER_RESERVE:
        return _final('Not in the library, and finding a source took too long; nothing was registered.',
                      note='Say it could not be found in time; the owner may ask again.')
    context['_tv_title_registering'] = True  # Cleared only by a returned receipt or a refused admission.
    try:
        receipt = await _bounded(nested('media.acquire', {'action': action, 'candidate_id': row['candidate_id']}),
                                 context)
    except PermissionError as error:
        context.pop('_tv_title_registering', None)
        return _final(f'Not in the library; media.acquire was not admitted ({error}). Nothing was registered.')
    context.pop('_tv_title_registering', None)
    scope = {key: row.get(key) for key in ('acquisition_scope', 'resolution', 'pack_episodes') if key in row}
    if receipt.get('status') != 'completed' or receipt.get('delivery') != 'verified':
        # The same end as a failed media.acquire call (its core marks it): nothing is repeated.
        return _final(f'The media server {action} did not verify; do not repeat it.', correction=False,
                      delivery=receipt.get('delivery', 'uncertain'), effect_applied=receipt.get('effect_applied'),
                      registration=receipt)
    return {'status': 'registered', **scope, 'operation': action, 'already_present': receipt.get('already_present'),
            'catalogue': receipt.get('catalogue') or {}}


def _pending(summary: dict, acquired: dict | None, reason: str, note: str, effect: bool = True) -> dict:
    return {'status': 'completed', 'delivery': 'not_dispatched', 'effect_applied': effect,
            'must_not_replay': True, 'playback_started': False, 'route': 'library',
            'library': {**summary, **({'acquired': acquired} if acquired else {})},
            'catalogue': {'status': 'pending', 'reason': reason}, 'note': note}


async def _acquire(title: str, season: int | None, episode: int | None, context: dict,
                   meta: dict | None = None, explicit: bool | None = None) -> dict:
    """explicit: the owner named this episode (a single open); otherwise its season's sequence."""
    explicit = episode is not None if explicit is None else explicit
    if 'media.acquire' not in (context.get('_tool_receipt_articles') or {}):
        return _final(f'"{title}" is not in the media library, and acquisition is not granted to this Agent.')
    explicit_meta = meta is not None
    found, near = ([meta], []) if meta else await _catalogue(title, season, context)
    if not found:
        return _final(f'No movie or series is named exactly "{title}" in the library or the metadata catalogue; '
                      'nothing was registered.', **({'choices': _catalogue_rows(near)} if near else {}),
                      note='Ask the owner which title they meant' + (' (these are similarly named)' if near else '')
                           + '; play it with its exact title followed by its year. A live channel or web video '
                             'never stands in for a named title.')
    if len(found) > 1:
        return _final(f'"{title}" names more than one title; nothing was registered.',
                      choices=_catalogue_rows(found), note=_CHOOSE)
    if not explicit_meta and described(title):
        # "a superhero movie" is a description; a catalogue title of that name ("Superhero Movie")
        # is only a candidate, never registered without the owner naming it.
        return _final(f'"{title}" describes a kind of content rather than naming one title; nothing was '
                      'registered.', choices=_catalogue_rows(found), note=_CHOOSE)
    meta = found[0]
    if not explicit_meta:
        # The library may hold this exact title under a differently scraped name: play it, never register twice.
        owned = [row for row in await asyncio.to_thread(service.catalogue().titles)
                 if row['imdb'] == meta['imdb_id'] and row['type'].lower() == meta['type']]
        if len(owned) == 1:
            return await _play_row(owned[0], season, episode, context, meta['metadata_id'])
    if meta['type'] == 'series':
        season, episode = season or 1, episode or 1  # Never watched: S1E1.
    summary = {'kind': 'movie' if meta['type'] == 'movie' else 'episode', 'title': meta['title'],
               'year': meta['year'], **({'season': season, 'episode': episode} if season else {})}
    key = (meta['imdb_id'], season, episode)
    done = context.setdefault('_tv_title_registrations', {})
    if key not in done:
        outcome = await _register(meta['metadata_id'], season, episode, context)
        if outcome.get('status') == 'held':
            return _pending(summary, None, 'already_registered_not_listed', effect=False,
                            note=f'"{meta["title"]}" is already registered with the media server under a source '
                                 'this search no longer returns; nothing new was registered and nothing was sent '
                                 'to the TV. Say it is being added. Do not register it again or play a substitute. '
                                 'If a later request still finds it absent, say its existing registration needs the '
                                 "owner's attention on the media server (it is not visible in the library).")
        if outcome.get('status') != 'registered':
            return outcome
        done[key] = outcome
    registered = done[key]
    acquired = {key: value for key, value in registered.items() if key not in ('status', 'catalogue')}
    reason = registered['catalogue'].get('reason')
    deadline = min(time.monotonic() + (WAIT_SECONDS if registered['catalogue'].get('status') == 'ready'
                                       or reason in _TRANSIENT else 0), context['_tv_title_deadline'])
    while True:
        cancel = context.get('_capability_cancel_event')
        if cancel is not None and cancel.is_set():
            raise asyncio.CancelledError  # Ends the wait; the registration already stands.
        rows = await asyncio.to_thread(service.catalogue().titles)
        item_id = registered['catalogue'].get('item_id')
        if meta['type'] == 'movie':
            movies = [row for row in rows if row['type'] == 'Movie']
            # The library had no such title before this registration, so a new exact match is it.
            rows = ([row for row in movies if row['item_id'] == item_id] if item_id else
                    [row for row in movies if row['imdb'] == meta['imdb_id']]
                    or [row for row in movies if tokens(row['title']) == tokens(meta['title'])
                        and row['year'] in (None, meta['year'])])
            if len(rows) == 1 and await asyncio.to_thread(_sources, rows[0]):
                result = _movie(rows[0], context, {'acquired': acquired})
                return result if result['status'] == 'ready' else _applied(result)
        else:
            rows = [row for row in rows if row['type'] == 'Series' and row['imdb'] == meta['imdb_id']]
            if len(rows) == 1:
                progress = await asyncio.to_thread(service.catalogue().series_progress, rows[0]['item_id'])
                if any(row['season'] == season and row['episode'] <= episode <= row['episode_end']
                       for row in progress):
                    result = await _series(rows[0], season, episode if explicit else None, context,
                                           meta['metadata_id'], {'acquired': acquired})
                    if result['status'] == 'ready':
                        return result
                    if result['status'] == 'absent':
                        break  # Listed without its file: report pending, never register again.
                    return _applied(result)
        if time.monotonic() >= deadline:
            break
        await asyncio.sleep(2)
    return _pending(summary, acquired, reason or 'catalogue_not_listed',
                    note=f'"{meta["title"]}"' + (f' S{season}E{episode}' if season else '') + ' was not in the library. '
                         + ('Its existing registration was refreshed' if registered.get('operation') == 'refresh'
                            else 'One source was registered')
                         + ' with the media server, which has not listed it yet; nothing was sent to the TV. Say it '
                           'is being added and that asking for it again in a minute plays it (that also finishes '
                           'its setup if needed). Do not register it again or play a substitute.')


async def _prepare(query: str, context: dict) -> dict:
    title, season, episode = spec(query)
    if generic(title):
        return _final(f'"{title}" names a kind of content, not a movie or show; nothing was played.',
                      note='For music, videos or live channels call play again with app youtube or pluto; '
                           'a film of that name is played with its year ("Music 2021").')
    rows = await asyncio.to_thread(service.catalogue().titles)
    if season is not None:
        rows = [row for row in rows if row['type'] == 'Series']
    exact, partial = match_titles(title, rows)
    if len(exact) > 1:
        return _choices(title, exact, context)
    if exact:
        return await _play_row(exact[0], season, episode, context)
    words = tokens(title)
    if any(row['type'] == 'Series' for row in partial):
        # A library series containing the request ("Voyager" in Star Trek: Voyager) means the owner
        # may mean it: a catalogue title of that name is then only a choice, never registered. It
        # stands for the request only when its name begins with a request of two or more words, it is
        # the only such library title, and the catalogue has no title of exactly that name ("Star
        # Trek" is also a 2009 film). An unreadable catalogue leaves it a choice.
        try:
            listed, near = await _catalogue(title, season, context)
        except (MediaUnavailable, OSError, ValueError):
            listed, near = None, []
        if (listed == [] and len(words) >= 2 and len(partial) == 1
                and tokens(partial[0]['title'])[:len(words)] == words):
            return await _play_row(partial[0], season, episode, context)
        return _final(f'"{title}" is not exactly one library title; nothing was played.',
                      choices=_rows(partial, context) + _catalogue_rows(listed or near), note=_CHOOSE)
    # Not in the library under this name; a longer library title is never a substitute.
    result = await _acquire(title, season, episode, context)
    if partial and result.get('status') == 'failed' and result.get('effect_applied') is False:
        result = {**result, 'library_choices': _rows(partial, context),
                  'note': ' '.join(filter(None, (result.get('note'), 'The library holds only these different '
                                                 'titles; offer them, never play one as the requested title.')))}
    return result


async def _play_row(row: dict, season: int | None, episode: int | None, context: dict,
                    metadata_id: str | None = None) -> dict:
    if row['type'] == 'Movie':
        return _movie(row, context)
    result = await _series(row, season, episode, context, metadata_id)
    if result['status'] != 'absent':
        return result
    # The series is catalogued but this episode's file is not: acquire exactly that episode.
    return await _acquire(row['title'], result['season'], result['episode'], context, result['meta'],
                          explicit=episode is not None)


def prepare(query: str, context: dict) -> dict:
    """Resolve a named title (sync, for the destination's worker thread); status ready carries the id."""
    registered = len(context.get('_tv_title_registrations') or {})
    context.pop('_tv_title_registering', None)
    context['_tv_title_deadline'] = time.monotonic() + DEADLINE_SECONDS
    try:
        return asyncio.run(_prepare(query, context))
    except (asyncio.CancelledError, Exception) as error:
        reason = ('cancelled' if isinstance(error, asyncio.CancelledError)
                  else str(error) or type(error).__name__)
        if context.pop('_tv_title_registering', None):
            # Interrupted inside the registration: its outcome is unknown and must never be repeated.
            context['_media_acquire_failed'] = True
            return _final(f'The media server registration was interrupted ({reason}); whether it registered '
                          'is unknown. Nothing was sent to the TV; do not register it again.',
                          correction=False, delivery='uncertain', effect_applied=None)
        if len(context.get('_tv_title_registrations') or {}) != registered:
            return _final(f'Registered once with the media server, then: {reason}. Nothing was sent to the TV; '
                          'do not register it again.', correction=False, effect_applied=True)
        if isinstance(error, asyncio.CancelledError):
            return _final('cancelled', correction=False)
        if not isinstance(error, (MediaUnavailable, OSError, ValueError)):
            raise
        return _final(f'Media server: {reason}. Nothing was played; no live channel or web video replaces a named title.')
