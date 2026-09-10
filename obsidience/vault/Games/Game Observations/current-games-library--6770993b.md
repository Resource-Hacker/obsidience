---
type: knowledge
tags:
- agent-observation
- obs-games
title: Current games library
obsidience:
  approved_at: '2026-09-10T05:47:31'
  provenance: proposed by Alexandria (task Tasks/link)
---

The current registered game routes are `battle_net` for
`battlenet-wow-drive.desktop`, `world_of_warcraft` for the Retail Smooth Motion
entry `wow-retail-wow-drive-smooth-motion.desktop`, and `teamfight_tactics` for
the Waydroid/Gamescope entry `tft-waydroid.desktop`. Launch each route once
through `application.launch`; an accepted dispatch is not proof of a ready game
window.

## Relationships

- `related_to` [Game interaction preferences](/Agents/Executive/Observations/Preferences/games.md) — The registered routes are the applications named by the owner's game-assistance preferences.
- `related_to` [World of Warcraft launch policy](/ADMECH%20Workstation/Workstation%20Observations/world-of-warcraft-launch-policy--3e5e73cc.md) — The World of Warcraft entry uses the established Retail Smooth Motion launch contract.
- `related_to` [TFT launch through Waydroid and Gamescope](/ADMECH%20Workstation/Workstation%20Observations/tft-launch-via-rtx-4080-android-avd--3e5726a8.md) — The Teamfight Tactics entry uses the managed Waydroid/Gamescope route.
- `related_to` [Primary World of Warcraft profile](/Games/WoW/primary-world-of-warcraft-profile--f2cc8948.md) — Squancher is the owner context reached through the registered World of Warcraft route.
- `related_to` [World of Warcraft gameplay](/Games/WoW/WoW.md) — The registered `world_of_warcraft` route is the current launch path to that game's recorded gameplay context.
- `related_to` [Teamfight Tactics gameplay](/Games/TFT/TFT.md) — The registered `teamfight_tactics` route is the current launch path to that game's recorded gameplay context.
- `related_to` [Games](/Games/Games.md) — The registered routes are the launch-identity registry for the games whose player and gameplay context the Games branch documents, and that branch explicitly keeps launch plumbing out of itself.
