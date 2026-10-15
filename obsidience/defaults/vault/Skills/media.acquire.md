---
type: skill
title: Using media.acquire
description: Register one exact source for an authorized acquisition or media playback request.
obsidience:
  tool: '[[Tools/media.acquire]]'
  owner_maintained: true
---

## Runtime

Use `media.library search` to resolve the owner's exact title and year, then
`candidates` for that title and, for a series, the exact season and episode.
Inspect the visible release, quality, cache and seed indicators. Use a unique best
rank only when its edition and episode are clear; ask the owner about a tie,
release ambiguity or uncertain episode. Never broaden an episode request into
a season pack or whole series.

Call `register` once when the owner explicitly chose a source, or requested playback
of an exact title/episode and the configured provider returned a unique recommended
source. The accepted owner preference permits obtaining that best eligible source
when it is missing from the local catalogue. A bare franchise name remains ambiguous. Do not register on a browse, search, source-check
or recommendation request. Candidate IDs are private to the current activation
and must never be reconstructed from a title, URL, path or source hash.

Treat the returned delivery state literally. An uncertain request is not
replayed; later read-only reconciliation may establish whether the provider
registered the exact source. Registration is not catalogue readiness: confirm
the exact item appears in Jellyfin before saying it is available. Playback requires an owner playback request, exact catalogue selection and
current verified player generation. Registration never auto-plays on its own. A missing shared FUSE mount or Jellyfin scan is a blocker, not a
reason to claim success or switch providers automatically.

When TorBox is enabled, acquire only its returned cached single-video candidate.
Missing cache, changed provider binding, multiple video files or a season pack
is a blocker. Never obtain an uncached source or fall back to local BitTorrent.
The one registration owner handles native library tagging, mount visibility and
the targeted catalogue refresh. Report tagging or catalogue state as pending
when readback cannot verify it; never repeat registration to repair visibility.
