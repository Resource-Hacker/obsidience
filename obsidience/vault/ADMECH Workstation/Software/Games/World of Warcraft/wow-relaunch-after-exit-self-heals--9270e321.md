---
kind: knowledge
title: WoW relaunch after exit self-heals
---

Fixed 2026-07-30 after the 2026-07-29 silent relaunch failure. Exiting WoW in-game used to wedge the launch chain (proton waited on the wine session that the AHK center helper kept alive), and the launcher guard mistook the leftover wrappers for a running game, silently swallowing every relaunch. Three layers now protect relaunch: a game-exit watchdog in launch-wow-retail.sh unwinds the chain when the game process disappears; the smooth-motion menu guard distinguishes a live Wow.exe from wrappers (younger than three minutes means a launch is warming up, older stale wrappers are cleaned up before launching); and the jarvis-app-launch server applies the same semantics. Behavior guidance: a launch_application dispatch that reports starting normally produces a window within about a minute; do not dispatch twice while a launch is warming up; report failure only if no window appears after ample wait.

## Relationships

- `extends` [[ADMECH Workstation/Software/Games/World of Warcraft/world-of-warcraft-launch-policy--3e5e73cc|World of Warcraft launch policy]] — Adds relaunch-after-exit self-healing behavior to the established launch policy.
- `related_to` [[Agents/Executive/Observations/end-to-end-action-and-verification-preference--dd0825ab|End-to-end action and verification preference]] — The relaunch procedure follows the end-to-end verification preference by distinguishing launch dispatch from verified window readiness.
