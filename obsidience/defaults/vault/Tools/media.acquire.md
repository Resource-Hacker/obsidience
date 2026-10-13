---
type: tool
title: media.acquire
description: Register one owner-selected movie or exact episode source with the configured local Tiramisu instance, once, without starting playback.
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
Tiramisu Unix socket.

This is an acquisition effect. Call it only after the owner explicitly asks to
obtain the selected source and one exact candidate has been chosen. A search or
best-rank recommendation by itself is not authorization. It registers one
movie or one verified season/episode through Tiramisu. It does not start
playback, create a Jellyfin record, prove the FUSE mount is ready, or prove
Jellyfin indexed the resulting media.

Each candidate and source identity can be attempted once per activation. The
adapter checks for the exact hash/type/episode before dispatch, sends one
registration request and never retries a possibly delivered request. On an
uncertain response it performs only bounded read-only reconciliation. Report
`delivery: uncertain` or any reconciliation failure as unresolved; do not
repeat the registration. A known registration, Jellyfin catalogue readiness,
and verified first playback are distinct outcomes.

This Tool cannot search titles, choose a candidate, alter provider settings,
configure Tiramisu, expose its socket, scan Jellyfin, return paths, or control a
player. The configured discovery provider is used as-is. Provider denial,
missing source data, ambiguous episodes, stale candidates, missing mount or
socket, and configuration changes fail explicitly. No autonomous watchlist,
scheduled sync, or quality upgrade may be inferred from this Tool.
