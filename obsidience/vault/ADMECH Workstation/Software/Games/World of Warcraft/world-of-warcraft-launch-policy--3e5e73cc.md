---
approved_at: '2026-08-26T20:18:46'
kind: knowledge
provenance: proposed by Alexandria (task Tasks/merge)
tags:
- software
- games
- world-of-warcraft
- movement
- mouselook
- input
- launch-policy
title: World of Warcraft launch policy
---

Use the registered world_of_warcraft application for an unqualified request to open or launch World of Warcraft. It resolves to wow-retail-wow-drive-smooth-motion.desktop and the established Retail Smooth Motion launcher. Use battle_net only when the user explicitly asks for Battle.net for an update, login, or repair. Dispatch is not readiness: claim success only after the World of Warcraft window and every required helper are live, and verify NVIDIA Present Smooth Motion when applicable.

The movement suite is part of the launch contract, not an optional follow-up. The normal launcher starts and supervises the external WoW input helper, the Wine AutoHotkey mouselook/recenter helper, and the G502 keypad mapper. It also selects the known-good D3D12/Proton profile, forces the G502 WoW onboard profile, ensures keyd is active without reloading it on every launch, enables Num Lock, suppresses duplicate XWayland extra-button events, places WoW at the Samsung native 5120x1440 geometry, and removes scoped helpers when the game exits. Do not launch Wow.exe directly and do not start an incomplete subset of the helper chain.

Mouselook normally remains locked with the cursor hidden. Holding right click opens the cursor-freelook peek and reticle for mouseover interaction; releasing it closes the peek, returns to locked mouselook, and recenters at the 2560,720 aim point. Caps Lock is mapped by keyd to Up, and Up is bound to SQMS_INVERTMOUSELOOK: holding it temporarily releases mouselook and releasing it relocks and recenters the cursor at the 2560,720 aim point. The SquancherMouselookSuite owns the safe WoW-side state, reticle, native peek actions, mouselook overrides, target range indicator, and deferred relock behavior. BUTTON1 may target-scan while mouselooking; BUTTON2 remains NULL in the mouselook override so right click can perform the peek contract.

The G502 X Plus keypad mapper is active only for the focused WoW window and grabs the keyboard HID interface so each extra button produces one intended NumPad action without a duplicate native mouse-button event. Forward, Back, Task, Side, and Extra map to NumPad1 through NumPad5; unnamed G502 codes 280 through 287 map to NumPad6 through NumPadPlus; horizontal wheel maps to NumPad1/NumPad2. Preserve NumPad bindings because the keyboard has no physical numpad; never replace them with F-key bindings. Mouse button code 281 is the pet-move action: the mapper asks the window-targeted AHK helper to open the pet-move targeting action, center the aim, click once, and restore the previous peek/mouselook state. This helper action is part of the user-authorized game-control stack and may perform its configured targeting and input sequence.

Ctrl must behave as a normal WoW action modifier without breaking movement or escaping into KWin. SquancherRetailCompat enforces CTRL-S as MOVEBACKWARD and CTRL-SPACE as JUMP on login or UI reload and saves the active character binding set. KWin intentionally leaves Ctrl+F7 and Ctrl+F9 unassigned while retaining Meta+F7 and Meta+F9, because the external right-click helper emits private F6/F7 peek signals and F8/F9 combined-click signals; a physically held Ctrl otherwise turns those signals into KWin Present Windows shortcuts. Do not restore those Ctrl KWin aliases. Ctrl remains available in WoW for mouse/NumPad action chords exactly like Shift.

Preserve raw mouse behavior, the G502 NumPad mapping, keyd exclusions for helper-created devices 2333:6666 and 0001:0001, and the established helper ownership. Do not add xdotool, a second input mapper, or an always-running virtual pointer. ydotoold starts only when an enabled helper feature actually needs it. Executive is authorized to use this complete movement and input stack, plus the sole CUA backend, for keyboard, pointer, camera, movement, combat or rotation, UI, and requested unattended game-world experiments without a separate approval prompt. Preserve fresh exact-target binding, stale-result rejection, postcondition verification, and STOP.

## Relationships

- `related_to` [[Agents/Executive/Observations/game-interaction-authority-and-interests--463cc7c8|Game interaction authority and interests]] — The launch contract and the verified movement/input suite give Executive the actuation substrate for game interaction under standing owner authority.
