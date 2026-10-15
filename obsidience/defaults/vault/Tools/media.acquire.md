---
type: tool
title: media.acquire
description: Register one owner-selected movie or exact episode source with the configured provider, once, without starting playback.
obsidience:
  binding: capability:media.acquire
  source: obsidience/harness/capabilities/media/acquire.py
  owner_maintained: true
---

## Runtime

`register` takes one run-bound `candidate_id` returned by
`media.library` `candidates`. It is available only to the Executive and only
when the optional acquisition and discovery configuration is enabled. The
candidate must belong to this activation and match its selected Cinemeta title,
provider, installation identity, configuration fingerprint and owner-only
Tiramisu Unix socket. When TorBox is enabled, its separate provider configuration
and cached file hash/path/size binding must also remain current. This source
cannot fall back to Tiramisu or uncached transfer if TorBox becomes unavailable.

This is an acquisition effect. Use one exact candidate only for an explicit
acquisition or playback request under the accepted source-selection policy.
A search or best-rank recommendation by itself is not authorization. TorBox
requires paid access and rechecks the complete cached file plan before one
cached-only registration. A movie has one video; a series pack identifies every
video as the same series with no overlaps or unexplained gaps inside each included
season range. The scope and all-file count are explicit. The accepted owner
policy permits a cached season or complete-series pack containing the requested
episode when a narrower eligible source is unavailable. Registration does not
expand the episode or season requested for playback.
It does not start playback or prove Jellyfin indexed the resulting media.

Each candidate and source identity can be attempted once per activation. The
adapter checks for the exact hash/type/episode before dispatch, sends one
registration request and never retries a possibly delivered request. On an
uncertain response it performs only bounded read-only reconciliation. Report
`delivery: uncertain` or any reconciliation failure as unresolved; do not
repeat the registration. A known registration, Jellyfin catalogue readiness,
and verified first playback are distinct outcomes.

The registration owner may add the exact native TorBox movie/TV library tag,
preserving existing tags, then refresh its WebDAV visibility and one configured
Jellyfin library. A preconfigured empty TV collection may receive only its
approved deferred root after the first real episode exists. Every metadata/path
write has bounded native readback; pending catalogue visibility never triggers
another registration.

This Tool cannot search titles, choose a candidate, configure Tiramisu or account
settings, expose credentials or sockets, request arbitrary library scans, return
paths, or control a player. The configured discovery provider is used as-is. Provider denial,
missing source data, ambiguous episodes, stale candidates, missing mount or
socket, and configuration changes fail explicitly. No autonomous watchlist,
scheduled sync, or quality upgrade may be inferred from this Tool.
