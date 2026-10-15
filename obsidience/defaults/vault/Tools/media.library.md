---
type: tool
title: media.library
description: Inspect the media catalogue and configured discovery/acquisition readiness, find exact movie or episode sources, read saved resume position, and bind an exact playable source without starting playback.
obsidience:
  binding: capability:media.library
  source: obsidience/harness/capabilities/media/library.py
  owner_maintained: true
---

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
started. With TorBox enabled, only currently cached single-video releases whose
actual file matches the full movie/year or exact episode are returned. Cache
provider and availability are shown explicitly, and registration rechecks the
private provider/hash/file/path/size binding. A cache miss does not trigger an
uncached transfer, season-pack import or P2P fallback.

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
resume command. To continue an item, select and open its exact source, then use
the generation-bound `tv.control` VOD seek to the returned position if the
player reports the source seekable.

An explicit request to obtain a discovered source may be followed by
`media.acquire` for exactly one selected candidate. A search, a "find" request,
or ranking alone does not authorize registration.

This optional integration is disabled by default. Missing credentials, changed
instance, unavailable roots and changed files fail explicitly. This Tool cannot
configure providers, register candidates, scan libraries, return filesystem
paths, transcode, start a player, or grant another Tool. A provider registration
receipt is not a Jellyfin catalogue entry: discovery, registration, Jellyfin
catalogue readiness, and verified first playback are separate states. FUSE
virtual roots are not admitted by the ordinary local-file source adapter unless
the specific mount integration is separately verified. The code-owned schema
and accepted Skill grants remain authoritative.
