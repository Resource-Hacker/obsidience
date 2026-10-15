"""A named movie or series for a playback destination: the owner's Media server first.

Owner decisions 2026-10-15: "put <show or movie> on" plays from the Jellyfin
library; a series with no episode named plays its next unwatched episode (S1E1
when never watched); a title absent from the library is registered through the
media server under the accepted best-source policy and then played. This module
only resolves: it returns an activation-scoped selection (m...) or season plan
(s...) for the destination's existing open/open_season contract, or a final
not-dispatched/pending result. It never starts playback and never guesses
between choices. Registration reuses media.acquire's own adapter and invariants.
"""
from __future__ import annotations

import asyncio
import re
import time
import unicodedata

from ...media import discovery, service
from ...media import season as seasons
from ...media.config import MediaUnavailable
from .library import bind

WAIT_SECONDS = 30.0
_TRANSIENT = {None, 'catalogue_source_pending', 'catalogue_readback_unavailable',
              'catalogue_refresh_uncertain', 'catalogue_readback_limit'}
_SPEC = (re.compile(r'\bs(\d{1,2})\s*e(\d{1,3})\b', re.I),
         re.compile(r'\b(\d{1,2})x(\d{2,3})\b', re.I),
         re.compile(r'\bseason\s+(\d{1,2})(?:\s*,?\s*(?:episode|ep)\s+(\d{1,3}))?\b', re.I))


def tokens(text: str) -> list[str]:
    """Whole words of a title, without bracketed release tags or a leading article."""
    text = unicodedata.normalize('NFKC', text).casefold().replace('&', ' and ')
    words = re.findall(r'[^\W_]+', re.sub(r'\([^)]*\)|\[[^\]]*\]', ' ', text))
    return words[1:] if len(words) > 1 and words[0] in ('the', 'a', 'an') else words


def spec(query: str) -> tuple[str, int | None, int | None]:
    """(title, season, episode) from a request such as "Voyager season 2 episode 3"."""
    text = re.sub(r'\s+on\s+(?:the\s+)?(?:tv|television)\s*$', '', query.strip(), flags=re.I)
    for pattern in _SPEC:
        match = pattern.search(text)
        if match:
            season, episode = int(match[1]), int(match[2]) if match[2] else None
            title = (text[:match.start()] + ' ' + text[match.end():]).strip(' ,-:')
            if title and 1 <= season <= 99 and (episode is None or 1 <= episode <= 999):
                return title, season, episode
    return text, None, None


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


def _leads(title: str, partial: list[dict]) -> bool:
    """Every partial hit is a Series whose name begins with the words: "Star Trek" names
    the library's Star Trek series. A partial Movie hit (a sequel, a longer title) never does."""
    words = tokens(title)
    return bool(partial) and all(row['type'] == 'Series' and tokens(row['title'])[:len(words)] == words
                                 for row in partial)


async def _search(title: str, kind: str, context: dict) -> list[dict]:
    """Exact metadata-catalogue titles, searched once per run (the discovery call budget is shared)."""
    pages = context.setdefault('_tv_title_searches', {})
    key = (tuple(tokens(title)), kind)
    if key not in pages:
        pages[key] = (await discovery.search(title, kind, context))['matches']
    return match_titles(title, pages[key])[0]


def named(query: str, context: dict, *, catalogue: bool) -> bool:
    """Whether the request's title is exactly a library title or, with catalogue, a metadata-
    catalogue title ("Live and Let Die", "News of the World"); read-only. A source that cannot
    be read answers False, so the request keeps its live/web wording."""
    title = spec(query)[0]
    try:
        if match_titles(title, service.catalogue().titles())[0]:
            return True
        if not catalogue:
            return False

        async def lookup():
            return any([await _search(title, kind, context) for kind in ('movie', 'series')])
        return asyncio.run(lookup())
    except (asyncio.CancelledError, MediaUnavailable, OSError, ValueError):
        return False


def next_unwatched(progress: list[dict]) -> dict | None:
    """The first unplayed episode in series order (S1E1 when nothing was watched)."""
    return next((row for row in progress if not row['played']), None)


def _final(failure: str, *, correction: bool = True, **fields) -> dict:
    result = {'status': 'failed', 'delivery': 'not_dispatched', 'effect_applied': False,
              'route': 'library', 'failure': failure, **fields}
    if correction:
        result['correction_allowed'] = True
    else:
        result['must_not_replay'] = True
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


def _rows(rows: list[dict], context: dict) -> list[dict]:
    choices = []
    for row in rows[:8]:
        choice = {'type': row['type'].lower(), 'title': row['title'], 'year': row['year']}
        if row['type'] == 'Movie':
            choice['ids'] = _ids(((row['item_id'], source) for source in row['sources']), context)
        choices.append(choice)
    return choices


def _choices(title: str, rows: list[dict], context: dict) -> dict:
    return _final(f'More than one library title matches "{title}"; nothing was played.', choices=_rows(rows, context),
                  note='Ask the owner which one. A movie choice opens with tv.control open and its id; '
                       'a series plays with play and its exact title followed by its year.')


def _movie(row: dict, context: dict, extra: dict | None = None) -> dict:
    ids = _ids(((row['item_id'], source) for source in row['sources']), context)
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
    onward = False  # Every catalogued episode is watched: continue from the last one watched.
    if season is None:
        progress = await asyncio.to_thread(service.catalogue().series_progress, row['item_id'])
        upcoming = next_unwatched(progress)
        onward = upcoming is None and bool(progress)
        season = upcoming['season'] if upcoming else progress[-1]['season'] if progress else 1
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


async def _register(metadata_id: str, season: int | None, episode: int | None, context: dict) -> dict:
    """One registration through media.acquire under the accepted best-source policy."""
    from .acquire import execute as acquire
    page = await discovery.candidates(metadata_id, season=season, episode=episode, context=context)
    rows = page.get('candidates') or []
    if not rows:
        return _final('Not in the library, and no eligible source was found; nothing was registered.')
    if rows[0].get('recommended') is not True:
        return _final('Not in the library, and no unique recommended source exists; nothing was registered.',
                      sources=rows, note='Ask the owner which source to register with media.acquire register.')
    context['_tv_title_registering'] = True  # Cleared only by a returned receipt.
    receipt = await acquire({'action': 'register', 'candidate_id': rows[0]['candidate_id']}, context)
    context.pop('_tv_title_registering', None)
    scope = {key: rows[0].get(key) for key in ('acquisition_scope', 'resolution', 'pack_episodes') if key in rows[0]}
    if receipt.get('status') != 'completed' or receipt.get('delivery') != 'verified':
        # The same end as a failed media.acquire call: effects stop and nothing is repeated.
        context['_media_acquire_failed'] = True
        return _final('The media server registration did not verify; do not repeat it.', correction=False,
                      delivery=receipt.get('delivery', 'uncertain'), effect_applied=receipt.get('effect_applied'),
                      registration=receipt)
    return {'status': 'registered', **scope, 'already_present': receipt.get('already_present'),
            'catalogue': receipt.get('catalogue') or {}}


async def _acquire(title: str, season: int | None, episode: int | None, context: dict,
                   meta: dict | None = None, explicit: bool | None = None) -> dict:
    """explicit: the owner named this episode (a single open); otherwise its season's sequence."""
    explicit = episode is not None if explicit is None else explicit
    if 'media.acquire' not in (context.get('_tool_receipt_articles') or {}):
        return _final(f'"{title}" is not in the media library, and acquisition is not granted to this Agent.')
    explicit_meta = meta is not None
    found = [meta] if meta else []
    for kind in () if meta else ('series',) if season is not None else ('movie', 'series'):
        found += await _search(title, kind, context)
    if not found:
        return _final(f'No movie or series named "{title}" is in the library or the metadata catalogue; '
                      'nothing was registered.',
                      note='If the owner meant a live channel or a web video, call play again with app pluto or youtube.')
    if len(found) > 1:
        return _final(f'"{title}" names more than one title; nothing was registered.',
                      choices=[{key: row[key] for key in ('type', 'title', 'year', 'imdb_id')} for row in found],
                      note='Ask the owner which one (year or type), then play its exact title with the year.')
    meta = found[0]
    if not explicit_meta:
        # The library may hold this exact title under a differently scraped name: play it, never register twice.
        owned = [row for row in await asyncio.to_thread(service.catalogue().titles)
                 if row['imdb'] == meta['imdb_id'] and row['type'].lower() == meta['type']]
        if len(owned) == 1:
            return await _play_row(owned[0], season, episode, context, meta['metadata_id'])
    if meta['type'] == 'series':
        season, episode = season or 1, episode or 1  # Never watched: S1E1.
    key = (meta['imdb_id'], season, episode)
    done = context.setdefault('_tv_title_registrations', {})
    if key not in done:
        outcome = await _register(meta['metadata_id'], season, episode, context)
        if outcome.get('status') != 'registered':
            return outcome
        done[key] = outcome
    registered = done[key]
    summary = {'kind': 'movie' if meta['type'] == 'movie' else 'episode', 'title': meta['title'],
               'year': meta['year'], **({'season': season, 'episode': episode} if season else {})}
    acquired = {key: value for key, value in registered.items() if key not in ('status', 'catalogue')}
    reason = registered['catalogue'].get('reason')
    deadline = time.monotonic() + (WAIT_SECONDS if registered['catalogue'].get('status') == 'ready'
                                   or reason in _TRANSIENT else 0)
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
            if len(rows) == 1 and rows[0]['sources']:
                result = _movie(rows[0], context, {'acquired': acquired})
                return result if result['status'] == 'ready' else {**result, 'effect_applied': True}
        else:
            rows = [row for row in rows if row['type'] == 'Series' and row['imdb'] == meta['imdb_id']]
            if len(rows) == 1:
                progress = await asyncio.to_thread(service.catalogue().series_progress, rows[0]['item_id'])
                if any(row['season'] == season and row['episode'] <= episode <= row['episode_end']
                       for row in progress):
                    result = await _series(rows[0], season, episode if explicit else None, context,
                                           meta['metadata_id'], {'acquired': acquired})
                    if result['status'] in ('ready', 'absent'):
                        if result['status'] == 'ready':
                            return result
                        break  # Listed without its file: report pending, never register again.
                    return {**result, 'effect_applied': True}
        if time.monotonic() >= deadline:
            break
        await asyncio.sleep(2)
    return {'status': 'completed', 'delivery': 'not_dispatched', 'effect_applied': True,
            'must_not_replay': True, 'playback_started': False, 'route': 'library',
            'library': {**summary, 'acquired': acquired},
            'catalogue': {'status': 'pending', 'reason': reason or 'catalogue_not_listed'},
            'note': f'"{meta["title"]}" was not in the library. One source was registered with the media server, '
                    'which has not listed it yet; nothing was sent to the TV. Say it is being added and can be '
                    'played shortly. Do not register it again or play a substitute.'}


async def _prepare(query: str, context: dict) -> dict:
    title, season, episode = spec(query)
    rows = await asyncio.to_thread(service.catalogue().titles)
    if season is not None:
        rows = [row for row in rows if row['type'] == 'Series']
    exact, partial = match_titles(title, rows)
    matches = exact or (partial if _leads(title, partial) else [])
    if len(matches) > 1:
        return _choices(title, matches, context)
    if matches:
        return await _play_row(matches[0], season, episode, context)
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
