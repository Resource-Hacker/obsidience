---
approved_at: '2026-09-01T21:03:27'
kind: knowledge
provenance: proposed by Alexandria (task Tasks/link)
tags:
- incident
- hardware
- driver
title: 'Incident: Samsung VRR Blackscreen and NVIDIA 610 Regression'
---

Symptom: Blackscreen on VRR fullscreen WoW. Root Cause: NVIDIA 610 driver scanout/flip path regression. Fix: Rollback to NVIDIA 595.58.03 + Kernel 6.18.20. EDID: g95sc-hdmi-240-144.bin. KWIN_DRM_NO_DIRECT_SCANOUT=1 required. Do not test 12-bpc or VRR Always.

## Relationships

- `affects` [[ADMECH Workstation/Hardware/Displays/Samsung Odyssey OLED G9/samsung-display-vrr-and-edid-configuration--96ccfd7b|Samsung Display VRR and EDID Configuration]] — NVIDIA driver regression causing blackscreen on VRR fullscreen WoW is a direct issue with the Samsung Display VRR and EDID configuration.
- `related_to` [[ADMECH Workstation/Hardware/Input/input-mapping-and-mouse-configuration--5579dfc0|Input Mapping and Mouse Configuration]] — WoW mouselook issues on VRR require specific KWin DRM settings, which interact with mouse input mapping and scaling calibration.
- `related_to` [[ADMECH Workstation/Workstation Observations/Incident/samsung-total-display-loss-incident-and-failover-contract--5c280a8c|Samsung total display-loss incident and failover contract]] — This is a separate Samsung display failure mode from the suspend-driven total display-loss incident, whose failover contract remains the recovery boundary for the primary Samsung display.
