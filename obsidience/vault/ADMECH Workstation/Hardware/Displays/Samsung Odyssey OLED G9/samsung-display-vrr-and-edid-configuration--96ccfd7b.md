---
approved_at: '2026-08-26T20:18:48'
kind: knowledge
provenance: proposed by Alexandria (task Tasks/merge)
tags:
- hardware
- display
- invariant
title: Samsung Display VRR and EDID Configuration
---

Target: 5120x1440 @ 239.999 Hz, HDR, VRR Automatic. Active EDID: g95sc-hdmi-240-144.bin (SHA256: b4f625...). NVIDIA 595 driver uses disable_hdmi_frl=0 hdmi_deepcolor=1. KWIN_DRM_NO_DIRECT_SCANOUT=1 is required for WoW mouselook. Do not use 12-bpc override. VRR policy is user-controlled; verify live policy but do not alter without request.

## Relationships

- `configures` [[ADMECH Workstation/Software/Games/World of Warcraft/world-of-warcraft-launch-policy--3e5e73cc|World of Warcraft launch policy]] — The required KWin direct-scanout setting and Samsung display configuration support the verified WoW mouselook behavior.
