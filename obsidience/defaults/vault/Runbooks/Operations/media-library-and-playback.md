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
and existing media. Only exact single-video releases are eligible; no uncached
transfer, season-pack import or P2P fallback is substituted. The TV is an
optional playback destination. This Runbook does not enable autonomous
watchlist sync, periodic upgrades or next-episode playback.

1. For a library request, use `media.library browse`; page with `next_offset` and
   identify the exact movie edition or series/season/episode. Resolve ambiguity
   before effects. For a source-search request, use `search`, choose the exact
   Cinemeta title/year, then `candidates` with the exact season/episode when
   applicable. Ranking is advisory. A tied top rank or ambiguous edition/episode
   needs owner choice.
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
4. For an explicit playback request, select the exact Jellyfin item/source or
   use a fresh `tv.control find` with `app: library`, ensure the registered TV
   is on, then `tv.control open` that exact current-turn id. Admission is
   repeated before dispatch. Only verified source, generation, and TV route
   establish playback. Loading, pending or uncertain delivery must not trigger
   another open.
5. To continue from saved progress, open the exact selected source with
   `resume: true`. The playback owner obtains fresh Jellyfin progress and uses it
   in the one load command; it verifies the position within five seconds. Do not
   follow open with an additional resume seek. For other controls first read VOD
   state, then bind pause, unpause, absolute seek, track or stop to its exact
   generation and source. No uncertain effect is replayed. Stop never deletes media.

Existing live TV keeps the same `tv.control` route. A missing library item by itself does not authorize effects. An explicit play
request uses only the accepted source-selection policy; purchases, another
provider or another player remain separate requests.
Acquisition uses one selected candidate and the configured provider only.
Persistent media-byte caching stays off with a bounded RAM working set; the
storage guard remains an independent precondition. This reference procedure
grants nothing; each Skill must be explicitly accepted on the invoking Agent.
New conversational work needs no Media Agent, Task or new folder hierarchy.
