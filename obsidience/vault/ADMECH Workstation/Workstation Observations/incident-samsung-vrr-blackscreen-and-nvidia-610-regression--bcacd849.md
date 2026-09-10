---
type: knowledge
tags:
- incident
- hardware
- driver
title: Samsung VRR blackout and NVIDIA 610 regression
obsidience:
  approved_at: '2026-09-01T21:03:27'
  provenance: proposed by Alexandria (task Tasks/link)
---

This historical incident produced a physical Samsung blackout when fullscreen
World of Warcraft engaged VRR on the high-refresh DSC path. Comparative tests
narrowed the fault to the NVIDIA 610 display stack; they did not prove one
source line. Returning to NVIDIA 595.58.03 with the validated Samsung EDID
removed the related scanout artifact and remains the measured driver baseline.

The current desktop is Hyprland, so the former KWin direct-scanout environment
variable is not a live requirement. Keep the selected
`g95sc-hdmi-240-144.bin` EDID, do not apply a 12-bpc override, and do not change
the owner's VRR policy without a fresh coordinated test. Use the validated
144 Hz mode as the immediate fallback if the blackout pattern returns.

## Relationships

- `affects` [Samsung display configuration](/ADMECH%20Workstation/Workstation%20Observations/samsung-display-vrr-and-edid-configuration--96ccfd7b.md) — The incident constrains future changes to the Samsung high-refresh and VRR path.
- `related_to` [Validated 144 Hz Samsung fallback](/ADMECH%20Workstation/Workstation%20Observations/workstation-observation-if-vrr-dsc-blackouts-return-use-the-validated-14--c05b5d51.md) — The tested 144 Hz mode is the immediate bounded fallback for recurrence.
- `related_to` [Samsung total display-loss incident](/ADMECH%20Workstation/Workstation%20Observations/samsung-total-display-loss-incident-and-failover-contract--5c280a8c.md) — The suspend deadlock was a distinct historical failure mode and does not establish the VRR cause.
