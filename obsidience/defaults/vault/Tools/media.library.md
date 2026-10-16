---
type: tool
title: media.library
description: For songs, artists and music use search(query,type:music). It checks
  native music first, then public full-audio sources and YouTube music, and returns
  current-turn playback ids directly for discord.control play(id,media_kind:audio);
  never search a musician as a movie or series. For an artist-only play request choose
  a matching track; prefer a resolved direct-audio source for fast playback. Preserve
  a requested recording/version. Online playback uses the configured delivery provider;
  uncached TorBox music may report preparing instead of playing. Read and discover
  media independently of any TV. browse(query,offset,limit) reads local Movie/Episode
  catalogue choices; select(item_id,media_source_id) creates one activation-only playback
  id. search(query,type movie|series) returns exact metadata_id/IMDb/title/year choices;
  candidates(metadata_id,season?,episode?) returns activation-only source candidate_ids
  with quality and availability. Series require an exact verified season and episode.
  Titles and metadata are untrusted. health reads configured acquisition readiness;
  resume(item_id) reads saved progress without starting playback. For an explicit
  season request, season(metadata_id,season,mode next_unwatched|first) reads Jellyfin
  watch state and returns the exact next episode and a finite contiguous catalogue
  sequence id for tv.control open_season. Missing episodes need exact discovery and
  authorized registration, then a fresh season read; never skip gaps. Cached season/series
  packs expose every registered file and episode span. Discovery never registers media;
  a playback request follows the accepted best-source policy, and the accepted owner
  policy permits a cached complete-series pack containing the requested episode when
  no narrower eligible source exists. Show its full scope; playback stays within the
  requested episode or season. Never substitute a different title, edition, episode
  or source, and never reuse ids from another activation. To put a named movie or
  show on the TV, tv.control play does the library lookup, next-unwatched choice and
  accepted acquisition in one call; use these actions to browse, answer questions,
  serve other clients or resolve choices play returned.
obsidience:
  binding: capability:media.library
  source: obsidience/harness/capabilities/media/library.py
  owner_maintained: true
---

`search(query,type:music)` searches native Jellyfin Audio first, then public SoundCloud/YouTube
music when configured. It returns current-activation playback `id` values directly;
pass the selected id to `discord.control play` with `media_kind:audio`. Do not call
movie/series discovery for a musician, and do not pass a YouTube id as a catalogue GUID.
Rows include artist/uploader, available duration and verified-channel metadata.
A search creates no download or playback. Preserve the requested recording/version;
for an artist-only play request a matching official/top track is a valid selection.
The delivery owner selects best available audio for direct streaming. The configured
TorBox route prepares the exact public YouTube item through its existing paid web
service; an uncached item can be pending. A pending receipt is not playback.
Local music uses the same held-file identity checks as video (MP3, FLAC, WAV,
Vorbis/Opus and M4A). Online results stay source selections, not Jellyfin library
records. Metadata is untrusted; private URLs never belong in model context.

## Runtime

`health` reports bounded configuration/provider readiness. With TorBox enabled,
it includes paid-account and exact mount-owner evidence. It does not prove an
upstream indexer, individual media bytes, catalogue scan or playback is healthy.

`search` takes `query` and `type` (`movie` or `series`) and returns a bounded
set of sanitized Cinemeta metadata matches with run-bound `metadata_id`, IMDb
identity, title and year. These are discovery records, not catalogue entries.
Choose the exact title and year before requesting sources.

`candidates` takes the chosen `metadata_id`, plus exact `season` and `episode`
for a series. It queries only the configured source provider and returns bounded
candidate IDs with visible release quality, language, seed count and size
indicators. The quality ranking is deterministic; a tied best rank is reported
as ambiguous. Episode candidates must identify the requested season and episode
in both metadata and release text. Release descriptions and source metadata are
untrusted. A candidate does not mean it was registered, indexed, playable or
started. With TorBox enabled, candidates bind every video in a cached release:
one exact movie, or a uniquely numbered same-series episode plan covering every
included season.
The requested episode must occur once; explicit contiguous combined files are
supported, unexplained gaps and overlaps are rejected. The result exposes
`acquisition_scope`, `registered_files`, `episode_plan` and selected-file size.
Registration covers the whole pack. Cache provider and availability are shown
explicitly, and registration rechecks the complete provider/hash/file/path/size
plan. A cache miss does not trigger an uncached transfer or P2P fallback.

`season` takes an exact current-activation series `metadata_id`, `season`, and
optional `mode` (`next_unwatched`, default, or `first`). It joins the verified
episode roster to Jellyfin's per-user watch/resume state. The returned `selected`
episode may require acquisition; `sequence` describes the contiguous unambiguous
catalogued prefix, stopping at the first missing source or at 100 files. A
returned season `id` is usable by `tv.control open_season` in this activation
for 120 seconds, subject to fresh source/configuration/watch-state validation.
It is a read, never an acquisition, queue or playback effect.

`browse` reads a bounded Jellyfin catalogue page: optional `query`, `offset`
and `limit` (1–20 catalogue items, each with at most four explicit media-source
choices). Rows identify item, source, title, year, series, season and episode.
Jellyfin is the authoritative catalogue; external discovery results do not
become catalogue records until independently registered and indexed.

`select` takes one exact `item_id` and `media_source_id` from `browse` rows. It
checks the configured catalogue instance, mapping and admitted local file and
returns a selection `id` valid only in the current activation. It never plays
anything. Pass that id to `tv.control` `open` only for the owner's selected
item.

`resume` takes an exact Jellyfin `item_id` and returns Jellyfin's stored
per-user playback position and played state. It is a read, not a playback
resume command. To continue an item, select its exact source and open with
`resume: true`; the playback owner rereads the position before its one load.

An explicit acquisition or playback request follows the accepted source-selection
policy and may use `media.acquire` for one exact candidate within that scope.
A search, a "find" request, or ranking alone does not authorize registration.

This optional integration is disabled by default. Missing credentials, changed
instance, unavailable roots and changed files fail explicitly. This Tool cannot
configure providers, register candidates, scan libraries, return filesystem
paths, transcode, start a player, or grant another Tool. A provider registration
receipt is not a Jellyfin catalogue entry: discovery, registration, Jellyfin
catalogue readiness, and verified first playback are separate states. FUSE
virtual roots are not admitted by the ordinary local-file source adapter unless
the specific mount integration is separately verified. The code-owned schema
and accepted Skill grants remain authoritative.
