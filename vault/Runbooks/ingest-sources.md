---
title: ingest-sources
kind: runbook
skills: ["[[Skills/reading-the-vault]]", "[[Skills/proposing-changes]]"]
---
Ingest new raw sources into the Knowledge layer (llm-wiki pattern).

1. `vault.list` Sources; `vault.read` [[Knowledge/index]] to see what is
   already integrated.
2. For each source not yet reflected in the index (skip Sources/README):
   `vault.read` it fully, then `vault.propose` (create) one distilled
   Knowledge note — synthesis in your own words, citing the source as a
   [[wikilink]]. One source may also justify updates to related existing
   notes; propose those separately.
3. `vault.propose` (update) [[Knowledge/index]] adding one catalog line per
   new note.
4. Nothing new to ingest is a valid completed result.
