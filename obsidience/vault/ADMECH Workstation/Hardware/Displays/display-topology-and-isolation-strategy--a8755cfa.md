---
kind: knowledge
tags:
- hardware
- display
- invariant
title: Display topology and isolation strategy
---

The primary Samsung Odyssey OLED G9 runs at native 5120x1440 up to 240 Hz on
the RTX 4080 SUPER and is the only physical display owned by KDE/KWin. DP-4
remains isolated at 3840x1100 on the RTX 4000 Ada through Xorg `:1`. The USB-C
display remains isolated at 3840x2400 on the AMD iGPU through Xorg `:2` and
currently hosts the Obsidience development UI.

The physically connected AMD HDMI/JetKVM sink remains output-off. It must not
mirror, clone, extend, resize, or host the USB-C workspace without a new
explicit topology decision.

DP-4 and USB-C use portal-free, event-driven, self-healing input and clipboard bridges. Do not reincorporate either isolated display into KWin.

## Relationships

- `related_to` [[ADMECH Workstation/Workstation Observations/Incident/incident-samsung-vrr-blackscreen-and-nvidia-610-regression--bcacd849|Incident: Samsung VRR Blackscreen and NVIDIA 610 Regression]] — The topology defines the Samsung path affected by the NVIDIA/VRR incident.
- `related_to` [[ADMECH Workstation/Hardware/Displays/DP-4 Display/dp-4-workspace-and-service-management--c6db7c16|DP-4 Workspace and Service Management]] — DP-4 is the isolated RTX 4000/Xorg workspace described by the workspace contract.
- `related_to` [[ADMECH Workstation/Hardware/Displays/Samsung Odyssey OLED G9/samsung-display-vrr-and-edid-configuration--96ccfd7b|Samsung Display VRR and EDID Configuration]] — The topology includes the primary Samsung display configuration.
