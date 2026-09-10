---
type: knowledge
tags:
- software
- games
- world-of-warcraft
- movement
- mouselook
- input
- launch-policy
title: World of Warcraft launch policy
obsidience:
  approved_at: '2026-09-10T07:07:44'
  provenance: proposed by Alexandria (task Tasks/link)
---

Use the registered `world_of_warcraft` application for an unqualified request
to open or launch World of Warcraft. It resolves to
`wow-retail-wow-drive-smooth-motion.desktop` and the established Retail Smooth
Motion wrapper. Use `battle_net` only when the owner explicitly asks for an
update, login, or repair. Call `application.launch` once; dispatch is not
readiness, and a second dispatch is never a readiness probe.

The desktop entry is the boundary for the complete launcher chain. It selects
the known-good D3D12 and Proton profile, targets the Samsung native geometry,
starts the configured movement and mouselook helpers, and cleans up its scoped
helpers after exit. Its guard distinguishes a live game from a launch warming
up and from stale wrapper residue; the exit watchdog unwinds the helper chain.
Do not launch `Wow.exe` directly, start a partial helper stack, stop a live game
to recover Battle.net, or use a terminal command as a second launch route.

Readiness requires the live World of Warcraft window and required helpers;
verify NVIDIA Present Smooth Motion when that profile is part of the claim.
When readiness is missing or ambiguous, report `starting` or failure from the
current evidence instead of guessing a wait duration or replaying the launch.

Preserve the owner's movement contract: raw mouse behavior, locked mouselook
with the right-click peek, Caps Lock mapped through keyd to the in-game
mouselook-release action, helper-created-device exclusions, and the intentional
NumPad mappings for supported extra buttons. Ctrl remains an ordinary in-game
action modifier; compositor shortcuts must not capture the helper's private
F-key signals. In-window action uses `computer.act` with one fresh semantic
target, one click, and a verified postcondition. It never gives Executive a
raw compositor, xdotool, or parallel input path as desktop authority.

## Relationships

- `related_to` [Game interaction authority and interests](/Agents/Executive/Observations/Preferences/games.md) — The launch contract and the verified movement/input suite give Executive the actuation substrate for game interaction under standing owner authority.
- `uses` [Application launch and window management](/ADMECH%20Workstation/Workstation%20Observations/agent-launch-and-gui-application-management--339f2788.md) — World of Warcraft uses the one registered launch route and requires current window evidence before a readiness claim.
- `related_to` [Input mapping and mouse configuration](/ADMECH%20Workstation/Workstation%20Observations/input-mapping-and-mouse-configuration--5579dfc0.md) — The helper chain consumes the active physical profile, keyd exclusions, Caps Lock mapping, and optional G502 NumPad mapping.
- `runs_on` [Samsung display configuration](/ADMECH%20Workstation/Workstation%20Observations/samsung-display-vrr-and-edid-configuration--96ccfd7b.md) — The normal profile targets the primary high-refresh gaming Surface.
- `related_to` [Samsung VRR blackout and NVIDIA 610 regression](/ADMECH%20Workstation/Workstation%20Observations/incident-samsung-vrr-blackscreen-and-nvidia-610-regression--bcacd849.md) — A fullscreen engagement of World of Warcraft previously engaged VRR on this Samsung high-refresh path and produced the documented blackout.
- `related_to` [Primary World of Warcraft profile](/Games/WoW/primary-world-of-warcraft-profile--f2cc8948.md) — The registered Retail route is the launch path for the owner's primary Squancher profile.
