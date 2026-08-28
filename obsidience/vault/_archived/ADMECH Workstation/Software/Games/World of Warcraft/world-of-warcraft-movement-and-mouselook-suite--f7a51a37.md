---
kind: knowledge
tags:
- software
- games
- world-of-warcraft
- movement
- mouselook
- input
title: World of Warcraft movement and mouselook suite
---

This article is the authoritative movement and input companion to the World of Warcraft launch policy. The normal registered WoW launcher starts and supervises the external input helper, the Wine AutoHotkey mouselook and recenter helper, the G502 keypad mapper, keyd, Num Lock, duplicate-button suppression, native Samsung placement, and scoped helper cleanup. Never launch Wow.exe directly or start only part of this chain.

Mouselook is normally locked and the cursor hidden. Holding right click opens cursor-freelook peek and the reticle for mouseover interaction; releasing it closes the peek, restores locked mouselook, and recenters at the 2560,720 aim point. Caps Lock is mapped by keyd to Up. In WoW, Up is bound to SQMS_INVERTMOUSELOOK so holding it temporarily releases mouselook and releasing it relocks and recenters. SquancherMouselookSuite owns the safe WoW-side state, reticle, native peek actions, mouselook overrides, target range indicator, and deferred relock behavior. BUTTON1 may target-scan while mouselooking; BUTTON2 remains NULL in the mouselook override so right click can perform the peek contract.

The G502 X Plus keypad mapper is active only while the exact WoW window is focused. It grabs the keyboard HID interface so every extra button emits one intentional NumPad action without a duplicate native mouse-button event. Forward, Back, Task, Side, and Extra map to NumPad1 through NumPad5. Unnamed G502 codes 280 through 287 map to NumPad6 through NumPadPlus, and horizontal wheel maps to NumPad1 and NumPad2. Preserve these NumPad bindings because the keyboard has no physical numpad; never replace them with F-key bindings. Mouse button code 281 is the pet-move action: the mapper asks the window-targeted AHK helper to open pet-move targeting, center the aim, click once, and restore the prior peek or mouselook state.

Ctrl behaves like Shift as a normal action modifier. SquancherRetailCompat enforces CTRL-S as MOVEBACKWARD and CTRL-SPACE as JUMP at login or UI reload and saves the active character binding set. KWin leaves Ctrl+F7 and Ctrl+F9 unassigned while retaining Meta+F7 and Meta+F9 because the external right-click helper emits private F6/F7 peek signals and F8/F9 combined-click signals; holding physical Ctrl must not turn those helper signals into KWin Present Windows shortcuts. Do not restore the Ctrl aliases.

Preserve raw mouse behavior, keyd exclusions for helper-created devices 2333:6666 and 0001:0001, and the established ownership boundaries. Do not add xdotool, a second input mapper, or an always-running virtual pointer. ydotoold may start only when an enabled helper feature needs it. The helper action is part of the user-authorized game-control stack. Executive may use this movement and input suite, plus the sole CUA backend, for keyboard, pointer, camera, movement, combat or rotation, UI, and requested unattended game-world experiments without a separate approval prompt. Preserve fresh exact-target binding, stale-result rejection, postcondition verification, and STOP.

## Relationships

- `related_to` [[ADMECH Workstation/Software/Games/World of Warcraft/world-of-warcraft-launch-policy--3e5e73cc|World of Warcraft launch policy]] — The movement suite is started and verified as part of the established WoW launch contract.
- `related_to` [[Agents/Executive/Observations/game-interaction-authority-and-interests--463cc7c8|Game interaction authority and interests]] — The movement suite is the verified actuation substrate for Executive game interaction under standing owner authority.
