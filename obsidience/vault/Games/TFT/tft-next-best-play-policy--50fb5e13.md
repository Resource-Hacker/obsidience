---
type: knowledge
title: TFT next-best-play policy
obsidience:
  approved_at: '2026-09-09T19:44:41'
  provenance: proposed by Alexandria (task Tasks/link)
---

When the owner asks Executive to play, buy, pick, or choose the next best TFT
character, unit, champion, card, augment, or offered option, Executive performs
exactly one current decision. `computer.observe` binds the exact TFT application
window and identifies the current choice surface and visible legal options. Use
only visible board, bench, trait, economy, level, stage, and round evidence;
never invent hidden state.

The recommendation must use a direct current-set and current-patch TFTactics.gg
page relevant to the choice and verify the set and patch against an official
Riot source. If the page is stale, unavailable, mismatched, or the visible
choice type remains ambiguous, Executive stops without acting. After research, obtain a fresh `computer.observe` image of the same TFT application.
In the immediately next response, `computer.act` uses that exact image to dispatch one
click, and must return a post-observation showing the selected option in the
expected accepted state.

One request never authorizes a second purchase, reroll, sale, item equip, reposition, or continuous play. An acknowledged or uncertain click is never replayed.

## Relationships

- `depends_on` [TFT managed Waydroid launch](/ADMECH%20Workstation/Workstation%20Observations/tft-launch-via-rtx-4080-android-avd--3e5726a8.md) — A live TFT decision requires the established managed Waydroid/Gamescope launch route.
- `related_to` [Game interaction authority and interests](/Agents/Executive/Observations/Preferences/games.md) — The policy applies the owner’s standing game-interaction authority to one bounded TFT choice.
- `related_to` [Current games library](/Games/Game%20Observations/current-games-library--6770993b.md) — The policy's one-click decision surface is the TFT application reached through the `teamfight_tactics` route registered in the current games library.
