---
approved_at: '2026-08-27T10:26:19'
kind: knowledge
provenance: proposed by Alexandria (task Tasks/link)
title: World of Warcraft launch stack
---

The complete chain for starting WoW Retail, top to bottom, and every place it can wedge.

DISPATCH: a voice request routes to launch_application(world_of_warcraft) on the jarvis-app-launch MCP server, which resolves wow-retail-wow-drive-smooth-motion.desktop and dispatches it in a transient systemd unit (jarvis-launch-world-of-warcraft-<nonce>.service, ExitType=cgroup). Before dispatching it checks whether a WoW window is already visible in KWin (already_running) or a launch is already warming up (already_starting).

LAUNCHER CHAIN: the desktop entry runs launch-wow-retail-smooth-motion-menu.sh (guards + environment: main display, NVIDIA Present Smooth Motion profile) → launch-wow-retail-smooth-motion.sh → launch-wow-retail.sh, which starts the helper suite — the wine AutoHotkey mouselook/recenter helper (inside the game's own wine session), the G502 keypad mapper (g502-wow-keypad.service, a SYSTEM unit), the xdotool window placer, and the game-exit watchdog — then blocks in umu-run Wow.exe -d3d12 inside a systemd scope named wow-retail-<pid>.scope. umu-run starts proton waitforexitandrun, which waits for the ENTIRE wine session to empty, not just Wow.exe.

WEDGE MODE 1 — GHOST WRAPPERS: after an in-game exit the wine-side wrappers (umu.exe — whose command line embeds the Wow.exe path — proton waitforexitandrun, and the launcher bash) can outlive the game because the AHK helper pins the wine session; proton never returns, the transient unit and the wow-retail scope stay running, and a naive process check mistakes the ghosts for a live game. These wrappers are NOT the game.

WEDGE MODE 2 — HUNG EXIT (2026-07-31): an in-game exit can leave Wow.exe itself ALIVE but WINDOWLESS, blocked in the kernel (ntsync) during wine shutdown, for hours. Any guard that keys only on the process existing then refuses every relaunch as already running or starting.

PROTECTIONS: (1) the launcher's exit watchdog unwinds the helper chain when the game process disappears, and since 2026-07-31 also TERM-then-KILLs a game process whose window has been gone for 30 seconds while the process lives on; (2) the menu guard distinguishes a live game, fresh wrappers (younger than 3 minutes = warming up), and stale wrappers (cleaned before launching); (3) the jarvis-app-launch server heals the windowless wedge itself — when the KWin window query PROVES no WoW window exists and every live Wow.exe is older than 5 minutes, it stops wow-retail-*.scope and stuck jarvis-launch units, verifies the game is gone, and dispatches fresh.

DIAGNOSIS: 'already starting; window not visible yet' repeating across several minutes means a wedge, not a slow start — a healthy cold start shows a window within about 2 minutes. A live Wow.exe with no WoW window in KWin is a hung exit, never a playable game. Manual recovery when self-heal fails: systemctl --user stop 'wow-retail-*.scope' 'jarvis-launch-world-of-warcraft-*.service', then relaunch. The keypad mapper grabs keyboard devices and must not outlive the session.

## Relationships

- `related_to` [[ADMECH Workstation/Software/Games/World of Warcraft/world-of-warcraft-launch-policy--3e5e73cc|World of Warcraft launch policy]] — The launch stack article explains the machinery behind the established WoW launch policy.
- `related_to` [[ADMECH Workstation/Software/Games/World of Warcraft/wow-relaunch-after-exit-self-heals--9270e321|WoW relaunch after exit self-heals]] — The stack article documents both wedge modes and the three-layer self-heal that the relaunch guidance relies on.
- `related_to` [[ADMECH Workstation/Hardware/Displays/Samsung Odyssey OLED G9/samsung-display-vrr-and-edid-configuration--96ccfd7b|Samsung Display VRR and EDID Configuration]] — The AutoHotkey mouselook helper that the launch stack starts depends on the KWin direct-scanout setting documented in the display configuration article.
