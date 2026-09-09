---
type: knowledge
title: Workstation display incidents
obsidience:
  approved_at: '2026-09-09T06:47:07'
  provenance: proposed by Alexandria (task Tasks/link)
---

[Samsung VRR blackout and NVIDIA 610 regression](/ADMECH%20Workstation/Workstation%20Observations/Incident/incident-samsung-vrr-blackscreen-and-nvidia-610-regression--bcacd849.md) records the fullscreen high-refresh failure. [Samsung total display-loss incident](/ADMECH%20Workstation/Workstation%20Observations/Incident/samsung-total-display-loss-incident-and-failover-contract--5c280a8c.md) records the separate automatic-suspend deadlock and why its isolated-display failover is retired.

If the indexed Samsung VRR blackout pattern returns, the [Validated 144 Hz Samsung fallback](/ADMECH%20Workstation/Workstation%20Observations/workstation-observation-if-vrr-dsc-blackouts-return-use-the-validated-14--c05b5d51.md) is the immediate display recovery mode.

The resulting display policy is recorded in [Workstation displays](/ADMECH%20Workstation/Hardware/Displays/Displays.md), which preserves the unified one-compositor topology on that failure history rather than restoring archived isolated-display failover helpers.
