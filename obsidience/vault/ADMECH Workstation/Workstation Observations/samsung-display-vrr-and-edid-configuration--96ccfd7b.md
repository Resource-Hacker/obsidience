---
type: knowledge
tags:
- hardware
- display
- invariant
title: Samsung display configuration
obsidience:
  approved_at: '2026-08-26T20:18:48'
  provenance: proposed by Alexandria (task Tasks/merge)
---

The Samsung Odyssey OLED G9 is the primary gaming Surface on RTX 4080 output
`HDMI-A-1`. The current Hyprland configuration selects `5120x1440 @ 240 Hz`,
10-bit output, HDR color management, a 225-nit SDR mapping, fullscreen-only VRR,
and disabled direct scanout. Live output state must still be checked before a
claim about the active mode, HDR, or VRR; do not change the owner's VRR policy
without an explicit request.

The selected EDID is `g95sc-hdmi-240-144.bin`, SHA-256
`b4f6250bc6f61fcb55a41aaa1db624cdee0022078829e564fc6832a1089d6635`.
NVIDIA 595 keeps HDMI FRL and deep color enabled through
`disable_hdmi_frl=0 hdmi_deepcolor=1`. Do not apply a 12-bpc override or use an
older KWin setting as a current Hyprland requirement.

## Relationships

- `part_of` [Unified display topology](/ADMECH%20Workstation/Workstation%20Observations/display-topology-and-isolation-strategy--a8755cfa.md) — The Samsung is the high-refresh gaming Surface in the current three-Surface compositor session.
- `related_to` [Gaming performance and visual-quality priorities](/ADMECH%20Workstation/Workstation%20Observations/gaming-performance-and-visual-quality-priorities--595700d3.md) — The mode and color targets implement the owner's preferred gaming presentation without weakening application settings.
- `related_to` [World of Warcraft launch policy](/ADMECH%20Workstation/Workstation%20Observations/world-of-warcraft-launch-policy--3e5e73cc.md) — World of Warcraft readiness includes the intended Samsung placement, while physical fullscreen VRR remains a separate acceptance check.
