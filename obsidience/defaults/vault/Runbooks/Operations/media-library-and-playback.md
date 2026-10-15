---
type: runbook
title: Media library and playback
obsidience:
  for_agent: '[[Agents/Executive/Executive]]'
  skills:
    - '[[Skills/media.library]]'
    - '[[Skills/media.acquire]]'
    - '[[Skills/tv.control]]'
---

Jellyfin owns the catalogue, delivery and saved per-user resume position.
Browsing and resume lookup work without the TV. Tiramisu is an optional
on-demand acquisition provider behind its owner-only Unix socket; Prowlarr's
public TorrentsCSV indexer is one configured discovery route. When TorBox is
enabled it owns new cached-only acquisition, while Tiramisu retains source search
and existing media. Movies require one exact video; episode sources may be
validated season or series packs whose complete file scope is shown. The accepted
owner policy allows a cached complete-series pack for the requested episode when
a narrower eligible source is unavailable. No uncached transfer or P2P fallback
is substituted. The TV
is an optional playback destination. Explicit season playback can create one
finite tuner-owned sequence; watchlist sync and periodic upgrades stay disabled.

Named-title playback (owner, 2026-10-15): "put <movie or show> on the TV" is one
`tv.control play` with the title as query and no app. It plays from Jellyfin
first; a series with no episode named continues at its next unwatched episode
(S1E1 if never watched; a missing episode is next, never skipped). An absent
title or episode is acquired by steps 1-3 inside that call: exactly one exact
catalogue title, the unique recommended source, and one `media.acquire` call
with its own receipt; a source the media server already holds is refreshed
instead. The result is playback, `choices` (nothing sent; ask the owner) or a
pending registration (effect applied, never repeated). An exact title wins; a
different or longer library title is only ever a choice, and a library series
containing the words (Star Trek: Voyager for "Voyager") keeps a catalogue title of
that name from being registered: the owner chooses. Generic requests
(music, cartoons, a movie) and explicit live, channel, news, weather, YouTube or
Pluto requests use the live/web route. The steps below remain the procedure for
explicit browse, source-search, selection and season requests.

1. For a library request, use `media.library browse`; page with `next_offset` and
   identify the exact movie edition or series/season/episode. Resolve ambiguity
   before effects. For a source-search request, use `search`, choose the exact
   Cinemeta title/year, then `candidates` with the exact season/episode when
   applicable. Ranking is advisory. A tied top rank or ambiguous edition/episode
   needs owner choice.
   For a season request, resolve its exact series then call `season`, normally
   with `mode: next_unwatched`; use `first` only for a requested restart. Read
   its selected episode and sequence boundary. If that episode is missing,
   discover its exact numbers. Reject unmarked combined pilots and missing
   numbering rather than skipping episodes. A pack registers all its files:
   show the complete scope, prefer a narrower eligible source, and keep playback
   within the requested episode or season even if a complete-series pack is registered.
2. Browse-only and source-search requests end without registration. For an
   explicit play request, the owner's accepted preference permits obtaining one
   unique recommended exact source if no local item exists. Ask about an ambiguous
   title, edition, episode or top-ranked tie. Register the chosen candidate once
   with `media.acquire`; uncertain delivery is never resent.
3. Registration has one catalogue-refresh owner. Inspect its catalogue state:
   registered, catalogue pending, and catalogue ready are distinct. Only use the
   exact returned item/source or a freshly selected exact catalogue record. A
   failed mount or pending scan is a visible blocker, never a fallback pathname.
   The same owner may add the exact TorBox library tag, preserving existing tags,
   and reconcile mounted visibility. For the first actual episode it may attach
   only the approved deferred root to its uniquely named empty TV collection,
   verify that path, then refresh that collection. It creates no dummy media or
   new collection. Pending metadata/catalogue readback does not repeat registration.
   Select that exact source again and use `media.acquire refresh` (the Media pane's
   Refresh registered source command) to reconcile an existing TorBox registration.
   It cannot create a torrent. Report any remaining visibility blocker literally.
4. For an explicit playback request, select the exact Jellyfin item/source or
   use a fresh `tv.control find` with `app: library`, ensure the registered TV
   is on, then `tv.control open` that exact current-turn id. Admission is
   repeated before dispatch. Only verified source, generation, and TV route
   establish playback. Loading, pending or uncertain delivery must not trigger
   another open.
   For a season request, read a fresh season plan after acquisition and use
   `open_season` with its id. It plays only the contiguous already-catalogued
   sources returned by that plan, at most 100 files. The first receipt attests
   only the first file. Later natural EOF transitions are tuner-owned and
   revalidate each source; a missing item ends the queue rather than triggering
   more acquisition. Ordinary `open` never enables this sequence.
5. To continue from saved progress, open the exact selected source with
   `resume: true`. The playback owner obtains fresh Jellyfin progress and uses it
   in the one load command; it verifies the position within five seconds. Do not
   follow open with an additional resume seek. For other controls first read VOD
   state, then bind pause, unpause, absolute seek, track or stop to its exact
   generation and source. No uncertain effect is replayed. Stop never deletes media.
   Each queued file gets a new generation. Refresh state before later controls;
   `stop` cancels the observed season queue even between files, with exact queue
   identity checked by the tuner before any stop effect.

Existing live TV keeps the same `tv.control` route. A missing library item by itself does not authorize effects. An explicit play
request uses only the accepted source-selection policy; purchases, another
provider or another player remain separate requests.
Acquisition uses one selected candidate and the configured provider only.
Persistent media-byte caching stays off with a bounded RAM working set; the
storage guard remains an independent precondition. This reference procedure
grants nothing; each Skill must be explicitly accepted on the invoking Agent.
New conversational work needs no Media Agent, Task or new folder hierarchy.
