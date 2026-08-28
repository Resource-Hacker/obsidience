---
kind: knowledge
title: Linux kernel 6.19 upstream release context
---

Kernel.org published the Linux 6.19 source and changelog on February 9, 2026. The official 6.19 documentation includes the DRM color-pipeline API, which lets userspace discover and program driver-exposed color-operation chains such as LUTs and matrices. That interface is intended to support efficient hardware color transformations and HDR-capable display pipelines when drivers and compositors expose the necessary properties.

This article is upstream release context, not proof that any particular driver or compositor has enabled every 6.19 facility on this workstation. Live kernel, NVIDIA module, KWin, connector, HDR, and VRR state must always be inspected separately.

## Relationships

- `related_to` [[ADMECH Workstation/Hardware/Displays/Samsung Odyssey OLED G9/samsung-display-vrr-and-edid-configuration--96ccfd7b|Samsung Display VRR and EDID Configuration]] — The DRM color-pipeline API is relevant background for the workstation’s HDR display path.
