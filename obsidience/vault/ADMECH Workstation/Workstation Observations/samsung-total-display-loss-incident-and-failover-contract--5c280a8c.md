---
type: knowledge
title: Samsung total display-loss incident
obsidience:
  approved_at: '2026-09-10T06:42:05'
  provenance: proposed by Alexandria (task Tasks/link)
---

On 2026-08-03 the workstation entered repeated 15-minute automatic idle
suspends because KDE PowerDevil had no explicit desktop policy. The fourth
cycle deadlocked the NVIDIA suspend writer in `nvidia_modeset` behind KWin's
render thread, leaving both NVIDIA display paths unusable.

The retired isolated-display recovery then failed because the HDMI helper
rejected its stale-disconnected state, DP-4 wake attempts could block, and the
old topology lacked a direct AMD USB-C input fallback.

Automatic idle suspend and system sleep remain disabled until an explicitly
coordinated NVIDIA validation, and the obsolete DisplayLink resume integration
remains disabled. The current unified Hyprland session no longer has isolated
DP-4 or USB-C input owners, the old failover helpers, or a KWin recovery path.
If total display loss recurs, inspect the current Hyprland output and DPMS state
and preserve the unified topology instead of invoking archived bridge or
isolated-workspace procedures.

## Relationships

- `related_to` [Unified display topology](/ADMECH%20Workstation/Workstation%20Observations/display-topology-and-isolation-strategy--a8755cfa.md) — The current topology supersedes the incident's isolated-display failover assumptions.
- `affects` [Samsung display configuration](/ADMECH%20Workstation/Workstation%20Observations/samsung-display-vrr-and-edid-configuration--96ccfd7b.md) — The incident is evidence for keeping sleep and display recovery changes coordinated and reversible.
- `related_to` [Samsung VRR blackout and NVIDIA 610 regression](/ADMECH%20Workstation/Workstation%20Observations/incident-samsung-vrr-blackscreen-and-nvidia-610-regression--bcacd849.md) — These are separate historical Samsung failure modes with different triggers.
- `related_to` [Validated 144 Hz Samsung fallback](/ADMECH%20Workstation/Workstation%20Observations/workstation-observation-if-vrr-dsc-blackouts-return-use-the-validated-14--c05b5d51.md) — That 144 Hz fallback targets VRR or DSC blackouts, a different Samsung failure mode from this total display loss, where both NVIDIA paths are unusable and recovery preserves the unified topology.
