---
type: knowledge
tags:
- agent-observation
- obs-games
title: Current games library
obsidience:
  approved_at: '2026-09-09T06:38:13'
  provenance: proposed by Alexandria (task Tasks/link)
---

The current registered game routes are `battle_net` for
`battlenet-wow-drive.desktop`, `world_of_warcraft` for the Retail Smooth Motion
entry `wow-retail-wow-drive-smooth-motion.desktop`, and `teamfight_tactics` for
the RTX 4080 Android AVD entry `tft-mobile-waydroid.desktop`. The TFT desktop
ID is legacy naming and does not mean Waydroid is used. Launch each route once
through `application.launch`; an accepted dispatch is not proof of a ready game
window.

## Relationships

- `related_to` [Game interaction preferences](/Agents/Executive/Observations/Preferences/games.md) — The registered routes are the applications named by the owner's game-assistance preferences.
- `related_to` [World of Warcraft launch policy](/ADMECH%20Workstation/Software/Games/World%20of%20Warcraft/world-of-warcraft-launch-policy--3e5e73cc.md) — The World of Warcraft entry uses the established Retail Smooth Motion launch contract.
- `related_to` [TFT launch via RTX 4080 Android AVD](/ADMECH%20Workstation/Software/Games/Teamfight%20Tactics/tft-launch-via-rtx-4080-android-avd--3e5726a8.md) — The Teamfight Tactics entry uses the managed Android AVD route.
- `related_to` [Primary World of Warcraft profile](/Games/WoW/primary-world-of-warcraft-profile--f2cc8948.md) — Squancher is the owner context reached through the registered World of Warcraft route.
- `related_to` [World of Warcraft gameplay](/Games/WoW/WoW.md) — The registered `world_of_warcraft` route is the current launch path to that game's recorded gameplay context.
- `related_to` [Teamfight Tactics gameplay](/Games/TFT/TFT.md) — The registered `teamfight_tactics` route is the current launch path to that game's recorded gameplay context.
