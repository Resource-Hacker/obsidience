---
kind: knowledge
title: Samsung total display-loss incident and failover contract
---

On 2026-08-03 the workstation entered repeated 15-minute automatic idle suspends because KDE PowerDevil had no explicit desktop policy. The fourth cycle deadlocked the NVIDIA suspend writer in `nvidia_modeset` behind KWin’s render thread, leaving both NVIDIA display paths unusable.

Recovery then failed for three independent reasons: the HDMI helper rejected the exact stale-disconnected state it needed to repair, DP-4 wake attempts could block for roughly 95 seconds, and there was no direct AMD USB-C input fallback.

The durable contract is: automatic idle suspend is disabled for every power profile; all system sleep capabilities remain disabled at the logind/systemd boundary until an explicitly coordinated NVIDIA/KWin validation; a DDC-attested Samsung may be force-reprobed from disconnected with a real off-then-detect transition; failover preserves a current isolated owner, otherwise tries healthy DP-4 then independent AMD USB-C with killable bounded helpers; and the obsolete DisplayLink resume integration remains disabled.

## Relationships

- `related_to` [[ADMECH Workstation/Hardware/Displays/display-topology-and-isolation-strategy--a8755cfa|Display Topology and Isolation Strategy]] — The incident and repaired failover traverse the Samsung, DP-4, and AMD USB-C paths in the established topology.
- `related_to` [[ADMECH Workstation/Hardware/Displays/DP-4 Display/dp-4-workspace-and-service-management--c6db7c16|DP-4 Workspace and Service Management]] — DP-4 is the first isolated fallback when its independently verified workspace is healthy.
- `related_to` [[ADMECH Workstation/Workstation Observations/workstation-observation-if-vrr-dsc-blackouts-return-use-the-validated-14--c05b5d51|Workstation observation: If VRR/DSC blackouts return, use the validated 144 Hz fallback rather than sacrificing HDR or image quality]] — The validated Samsung fallback remains separate from the bounded cross-display input failover.
