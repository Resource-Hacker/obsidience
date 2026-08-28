---
kind: knowledge
title: TFT next-best-play policy
---

When the owner asks Executive to play, buy, pick, or choose the next best TFT character, unit, champion, card, augment, or offered option, Executive performs exactly one current decision. It binds the exact TFT emulator window, identifies the current choice surface and only the visible legal options, and uses visible board, bench, trait, economy, level, stage, and round evidence without inventing hidden state.

The recommendation must use a direct current-set/current-patch TFTactics.gg page relevant to the choice and verify the set and patch against an official Riot source. If the page is stale, unavailable, mismatched, or the visible choice type remains ambiguous, Executive stops without acting. After research it recaptures the TFT window because all earlier elements are stale, resolves one current element, dispatches exactly one foreground click, and verifies that the selected option left the offer and appeared in the expected accepted state.

One request never authorizes a second purchase, reroll, sale, item equip, reposition, or continuous play. An acknowledged or uncertain click is never replayed.

## Relationships

- `depends_on` [[ADMECH Workstation/Software/Games/Teamfight Tactics/tft-launch-via-rtx-4080-android-avd--3e5726a8|TFT launch via RTX 4080 Android AVD]] — A live TFT decision requires the established managed RTX 4080 Android emulator launch route.
- `related_to` [[Agents/Executive/Observations/game-interaction-authority-and-interests--463cc7c8|Game interaction authority and interests]] — The policy applies the owner’s standing game-interaction authority to one bounded TFT choice.
