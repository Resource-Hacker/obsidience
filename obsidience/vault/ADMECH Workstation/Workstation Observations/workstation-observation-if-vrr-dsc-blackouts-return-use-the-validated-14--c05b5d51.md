---
type: knowledge
tags:
- auto-distilled
- review-required
title: Validated 144 Hz Samsung fallback
obsidience:
  approved_at: '2026-09-10T05:23:39'
  provenance: proposed by Alexandria (task Tasks/link)
---

If Samsung VRR or DSC blackouts return, the validated native 5120x1440 at 144 Hz
mode is the immediate display fallback. Preserve HDR and image quality settings;
do not compensate by reducing World of Warcraft graphics settings.

## Relationships

- `mitigates` [Samsung VRR blackout and NVIDIA 610 regression](/ADMECH%20Workstation/Workstation%20Observations/incident-samsung-vrr-blackscreen-and-nvidia-610-regression--bcacd849.md) — The validated 144 Hz mode is the bounded fallback if that fullscreen failure pattern returns.
- `related_to` [Gaming performance and visual-quality priorities](/ADMECH%20Workstation/Workstation%20Observations/gaming-performance-and-visual-quality-priorities--595700d3.md) — The validated 144 Hz fallback preserves the user's HDR and image-quality priorities when VRR or DSC blackouts recur.
- `related_to` [Samsung display configuration](/ADMECH%20Workstation/Workstation%20Observations/samsung-display-vrr-and-edid-configuration--96ccfd7b.md) — The validated 144 Hz mode is the immediate fallback for the current 240 Hz Samsung display configuration if VRR or DSC blackouts return.
