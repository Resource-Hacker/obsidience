---
approved_at: '2026-08-28T13:48:09'
kind: knowledge
provenance: proposed by Codex (task codex:knowledge-handoff)
tags:
- software
- input
- invariant
title: Input Mapping and Mouse Configuration
---

## Automatic physical mouse profiles

Enabled `admech-mouse-profile.service` is the single event-driven selector for the supported physical gaming mice. It identifies exact USB vendor/product/input-name triples through read-only sysfs and atomically publishes the active profile to `~/.config/admech-mouse-profile/active.env`; DP-4, USB-C, KWin, and the base WoW launcher consume that selection.

- Logitech G502 X Plus: `046d:c095`, 25,600 hardware DPI, KWin flat acceleration `-0.96875`, DP-4 relative scale `0.03125`, USB-C relative scale `0.0625`.
- Mad Catz M.M.O. 7+: `0738:0c19`, 26,000 hardware DPI, KWin flat acceleration `-0.9692307692307692`, DP-4 relative scale `0.03076923076923077`, USB-C relative scale `0.06153846153846154`.
- Original Saitek Cyborg M.M.O.7: `06a3:0cd0`, 6,400-DPI top stage, KWin flat acceleration `-0.875`, DP-4 relative scale `0.125`, USB-C relative scale `0.25`.

Each profile produces 800-DPI effective sensitivity on the Samsung and equivalent physical motion across the isolated displays. The USB-C scale includes its established two-times geometry compensation. If more than one supported mouse is present, the most recently attached wins; unplugging it falls back to the remaining supported mouse, while zero supported mice preserves the last profile.

The original `06a3:0cd0` M.M.O.7 exposes only its standard mouse input endpoint with no declared writable HID feature report. Its 6,400-DPI maximum must therefore be selected with the physical DPI rocker and is indicated by all four DPI bars. The selector records `physical_top_stage_four_bars` and leaves the tuner result unset instead of claiming software verification.

## WoW and key mapping

The WoW launcher sources the selected exact anchored mouse-name expression from the same active environment. Do not hardcode a single mouse in wrappers or Gamescope profiles. The G502-specific extra-button mapper remains exact-device filtered; the original M.M.O.7 profile does not attach to that mapper or rewrite its extra buttons.

Caps Lock remains mapped to Up through keyd for mouselook. Helper-created virtual devices remain excluded from keyd to avoid the prior keyd crash. Preserve raw mouse behavior and the intentional NumPad mapping for supported extra buttons. M33kAuras and Plater retain their local Retail API fixes.

## Isolated-display bridge cursor control

On the dual-screen AMD Xorg topology, USB-C is `:2.0` and DP-4 is `:2.1`. Since 2026-08-28, `dp4-edge-bridge.service` runs the single-owner Obsidience router at `/home/wissenschafter/Projects/obsidience/obsidience/shell/input/router.py`; `usb-monitor-edge-bridge.service` is its compatibility alias. One evdev grab and one Python-Xlib XTest connection span both isolated screens. A DP-4 to USB-C transition retains ownership and held input state, while only a mapped return to Samsung releases evdev.

KWin sends exact edge and local-pointer coordinates through `org.wissenschafter.DP4Bridge.EnterMapped`; the accepted Surface layout is the geometry and adjacency authority. The D-Bus adapter must retain its `dbus.service.BusName` by passing it to `SurfaceBridge`. Discarding that object leaves the service process running only on a unique bus name and makes every KWin edge call unreachable.

The router owns one persistent native `libX11`/`libXfixes` connection per isolated X screen to hide the inactive cursor and show only the active Surface cursor. Python-Xlib remains responsible for XTest input but must not issue XFixes cursor hide or show on this topology: its window method produced an asynchronous `BadRRCrtcError` and restarted the router on entry. Cursor visibility changes must remain idempotent.

Each command FIFO has exactly one intended reader. Never inspect `dp4-edge-bridge.cmd`, `usb-monitor-edge-bridge.cmd`, or `edge-main-cursor.cmd` with `cat`, `head`, or another reader because it can steal a handoff or Samsung-return command. Inspect the corresponding state file and use `fuser` to verify FIFO ownership.

## Verified activation

On 2026-08-26 the original M.M.O.7 profile selected automatically, KWin reported flat acceleration `-0.875`, both isolated-display bridge services loaded the exact mouse and their profile scales, and a DP-4 to USB-C to Samsung traversal grabbed the exact physical endpoint on both isolated screens before returning with both bridges inactive and the handoff guard clear.

On 2026-08-28 live single-owner acceptance confirmed the well-known D-Bus name, the loaded KWin native-edge adapter, Samsung bottom-edge mapping into both DP-4 and USB-C, DP-4 to USB-C to DP-4 switching without releasing evdev, both Samsung returns, the same router PID, and zero service restarts. The focused D-Bus and cursor regressions passed inside the complete 126-test project suite; vault validation, Python compilation, UI typecheck, production build, API health, and the live USB-C interface also passed.

## Relationships

- `related_to` [[ADMECH Workstation/Software/Desktop and Windowing/agent-launch-and-gui-application-management--339f2788|Agent Launch and GUI Application Management]] — Input mapping and mouse configuration calibrations are necessary for proper GUI application management and side display usage.
