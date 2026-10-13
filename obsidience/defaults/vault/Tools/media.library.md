---
type: tool
title: media.library
description: Browse configured movie and episode records and bind an exact playable local source without starting playback.
obsidience:
  binding: capability:media.library
  source: obsidience/harness/capabilities/media/library.py
  owner_maintained: true
---

## Runtime

`browse` reads a bounded catalogue page: optional `query`, `offset` and `limit`
(1–20 catalogue items, each with at most four explicit media-source choices).
Rows identify the item, source, title, year, series, season and episode. Metadata
is untrusted data. Multiple editions remain separate choices.

`select` takes one exact `item_id` and `media_source_id` from those rows. It
checks the configured catalogue instance, mapping and local file and returns a
selection `id` valid only in the current activation. It never plays anything.
Pass that id to `tv.control` `open` only for the owner's selected item.

This optional integration is disabled by default. Missing credentials, changed
instance, unavailable roots and changed files fail explicitly. This Tool cannot
configure providers, acquire media, scan libraries, return filesystem paths,
transcode, start a player, or grant another Tool. The code-owned schema and
accepted Skill grants remain authoritative.
