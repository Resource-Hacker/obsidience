---
type: runbook
title: Media library and playback
obsidience:
  for_agent: '[[Agents/Executive/Executive]]'
  skills:
    - '[[Skills/media.library]]'
    - '[[Skills/tv.control]]'
---

The media server and catalogue are independent of the playback destination.
Browsing works without a TV. This procedure covers the first destination
adapter, the registered television, when the owner explicitly selects it.

1. Browse with `media.library` and identify the owner's exact edition or
   series/season/episode. Resolve ambiguity before any effect. A browse-only
   request ends here; it does not select a playback destination.
2. Select that exact item/source pair. A fresh `tv.control find` with
   `app: library` can also return current-turn selections.
3. For an explicit playback request, ensure the registered TV is on and use
   `tv.control open` with the selected id. Admission is repeated before dispatch.
4. Claim playback only from the returned verified source, generation and TV
   route. Loading, pending and uncertain delivery must not trigger another open.
5. Use `tv.control stop` to end the current local source by its observed
   generation. Stopping does not delete media.

Existing live TV keeps the same `tv.control` route. A missing library item does
not authorize torrent registration, purchases, another provider or another
player. No acquisition Tool or automatic-next policy is supplied by this slice.
This reference procedure grants nothing; each Skill must be explicitly accepted
on the invoking Agent. New conversational work needs no Media Agent or Task.
