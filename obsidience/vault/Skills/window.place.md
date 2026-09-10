---
type: skill
title: Using window.place
obsidience:
  tool: '[[Tools/window.place]]'
---

Use `window.place` to move one existing native application or module pane to one
declared Surface and optional workspace tile.

- Pass exactly `{"target": {"kind": "application|pane", "name": str,
  "surface": "samsung|usb-c|dp-4" optional}, "destination": {"surface":
  "samsung|usb-c|dp-4", "tile": {"left": int, "top": int, "right": int,
  "bottom": int} optional}}`. Take `kind` and `name` from the current Shell
  Scene or reuse an observation's exact target object. For `application`, use
  the canonical application ID, such as `teamfight_tactics`, or exact current
  `app_id` (1-256 printable characters); existing registry aliases also resolve.
  For `pane`, use exact `pane_id` (1-48 printable characters). Never substitute
  a display title, fuzzy name, or `kind: focused`. Add the current Surface only
  to disambiguate that identifier. No match or multiple matches fails closed.
  Take current columns/rows from the Shell Scene's `tile_grids`.
  Tile edges are integer grid coordinates, never display pixels,
  fractions, or percentages. For an 8-column by 2-row grid, the full-height
  leftmost column is `{"left":0,"top":0,"right":1,"bottom":2}`;
  use `right:4` for the left half. Adapt to the live grid. Bounds must be integers
  satisfying `0 <= left < right <= columns` and
  `0 <= top < bottom <= rows` in the destination's current grid.
- Success returns `status: completed`, the exact target and destination,
  `must_not_replay: true`, `effect_applied`, and fresh `observed.surface` and
  active state. `previous.surface` records the prior Surface, not prior tile
  bounds. `effect_applied:false` means placement already matched: say it was
  already there, rather than claiming a move.
- A tile placement also returns `observed.tile` matching `destination.tile`,
  attested once by the existing compositor layout owner. A matching Surface
  without that exact tile evidence does not complete a tile request.
- Only the fresh returned destination verifies placement. A Surface-only
  destination preserves logical size except where it cannot fit and does not
  imply focus. Call directly once; no prerequisite observation or activation,
  and no extra screenshot to verify the already-attested placement.
- A local `invalid_destination` with `delivery:not_dispatched` and
  `correction_allowed:true` made no Shell request. Read its current
  `destination_contract` and permit at most one different, corrected call.
  `must_not_replay:true` still forbids repeating the original malformed call.
- Stop on `scene_unavailable`, `target_missing`, `target_ambiguous`,
  `invalid_destination`, `stale_scene`, `effect_not_observed`, or
  `shell_scene_command_unavailable`. Every failure is non-retryable for this
  attempt, except that explicit pre-dispatch correction. `delivery:uncertain`
  and `effect_applied:null` mean an effect may have occurred; do not claim it
  did nothing and never replay it.
