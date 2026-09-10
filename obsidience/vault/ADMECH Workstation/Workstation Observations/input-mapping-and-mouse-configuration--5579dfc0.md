---
type: knowledge
tags:
- software
- input
- invariant
title: Input mapping and mouse configuration
obsidience:
  approved_at: '2026-08-28T13:48:09'
  provenance: proposed by Codex (task codex:knowledge-handoff)
---

## Automatic physical mouse profiles

Enabled `admech-mouse-profile.service` is the event-driven selector for the
supported physical gaming mice. It identifies exact USB vendor, product, and
input-name triples through read-only sysfs and atomically publishes the active
profile to `~/.config/admech-mouse-profile/active.env`. The World of Warcraft
launcher consumes the selected anchored device name.

- Logitech G502 X Plus: `046d:c095`, registered at 25,600 hardware DPI.
- Mad Catz M.M.O. 7+: `0738:0c19`, registered at 26,000 hardware DPI.
- Original Saitek Cyborg M.M.O.7: `06a3:0cd0`, 6,400-DPI physical top stage.

At the 2026-09-04 audit, the active physical device was the original M.M.O.7.
Hyprland applies the exact device rule `custom 1 0 0.125`, yielding
800-effective-DPI linear motion across the unified Surfaces. The selector still
publishes legacy DP-4 and USB-C scale fields for compatibility, but no active
display bridge consumes them. The G502 and M.M.O. 7+ profiles remain registered
owner profiles; their former KWin and isolated-Xorg scale values are not proof
of current Hyprland calibration, so revalidate a matching device rule before
claiming 800-effective behavior after switching mice.

If more than one supported mouse is present, the most recently attached wins;
unplugging it falls back to the remaining supported mouse, while zero supported
mice preserves the last profile.

The original `06a3:0cd0` M.M.O.7 exposes only its standard mouse input endpoint with no declared writable HID feature report. Its 6,400-DPI maximum must therefore be selected with the physical DPI rocker and is indicated by all four DPI bars. The selector records `physical_top_stage_four_bars` and leaves the tuner result unset instead of claiming software verification.

## WoW and key mapping

The WoW launcher sources the selected exact anchored mouse-name expression from the same active environment. Do not hardcode a single mouse in wrappers or Gamescope profiles. The G502-specific extra-button mapper remains exact-device filtered; the original M.M.O.7 profile does not attach to that mapper or rewrite its extra buttons.

Caps Lock remains mapped to Up through keyd for mouselook. Helper-created virtual devices remain excluded from keyd to avoid the prior keyd crash. Preserve raw mouse behavior and the intentional NumPad mapping for supported extra buttons. M33kAuras and Plater retain their local Retail API fixes.

## Relationships

- `related_to` [Unified display topology](/ADMECH%20Workstation/Workstation%20Observations/display-topology-and-isolation-strategy--a8755cfa.md) — One Hyprland pointer path now spans all three Surfaces without per-display scaling bridges.
- `configures` [World of Warcraft launch policy](/ADMECH%20Workstation/Workstation%20Observations/world-of-warcraft-launch-policy--3e5e73cc.md) — The launcher consumes the active physical profile and preserves the owner's keyd and extra-button mappings.
