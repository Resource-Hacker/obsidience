---
type: tool
title: window.place
obsidience:
  binding: capability:window.place
  source: obsidience/harness/capabilities/window/place.py
---

Place one existing native application or module pane on a declared Surface and
optional workspace tile. Arguments:
`{"target": {"kind": "application|pane", "name": str, "surface": "samsung|usb-c|dp-4" optional}, "destination": {"surface": "samsung|usb-c|dp-4", "tile": {"left": int, "top": int, "right": int, "bottom": int} optional}}`.

Use the current Shell Scene's concrete `kind: application|pane` and `name`,
or the exact target object returned by observation. For an application, `name`
is the canonical registered application ID, such as `teamfight_tactics`, or
exact current `app_id`, with 1-256 printable characters. Existing registry
aliases are accepted, not arbitrary window titles or fuzzy matches. For a
module pane, use exact `pane_id` with 1-48 printable characters. `focused` is
not a valid effect target kind. Target `surface` only disambiguates the same
identifier; no match or multiple matches fails closed. Tiles use integer grid-edge
coordinates, never pixels, fractions, percentages, or a display's resolution.
Read the destination's `columns` and `rows` from the current Shell Scene's
`tile_grids` (`tile_units: grid_edges`). Optional tile edges must satisfy
`0 <= left < right <= columns` and `0 <= top < bottom <= rows` in the current
destination grid. For example, on an 8-column by 2-row grid, the full-height
leftmost column is `{"left":0,"top":0,"right":1,"bottom":2}`; the left half
uses `right:4`. Do not assume those dimensions when the live grid differs.

Obsidience resolves one unique semantic target and the destination against the
newest Shell scene, privately pins the exact window and scene revision, issues
one placement request, and returns a fresh scene showing the resulting
destination with the normalized target identity. A tiled request additionally
requires one exact bounds verification from the existing compositor layout
owner; success includes matching `destination.tile` and `observed.tile`.
An accepted placement command or matching Surface alone cannot verify a tile.
No prerequisite observation
or activation is needed; the returned verified destination is sufficient
placement evidence. The result also supplies the prior `previous.surface`;
it does not invent previous tile bounds from pixel geometry. If
`effect_applied:false`, the target already matched the placement: report that
fact without claiming it moved. A Surface-only destination preserves the pane's logical size and
shrinks only a dimension that cannot fit. This Tool does not launch, activate,
click, or type and exposes no internal window identifier or pixel geometry.

Failures are typed as `scene_unavailable`, `target_missing`,
`target_ambiguous`, `invalid_destination`, `stale_scene`,
`effect_not_observed`, or `shell_scene_command_unavailable`. Failure or
uncertain delivery is never success. Failure `delivery` distinguishes
`not_dispatched`, explicit Shell `rejected`, and `uncertain`; the last reports
`effect_applied:null` because the effect may have occurred. Every result carries
`must_not_replay:true`: never repeat the same call. Only a locally rejected
`invalid_destination` with `delivery:not_dispatched` and
`correction_allowed:true` permits one new call with corrected arguments from
the returned `destination_contract`. Rejection or uncertainty after dispatch
does not permit correction or replay.
