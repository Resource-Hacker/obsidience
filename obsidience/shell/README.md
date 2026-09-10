# Obsidience Shell

Obsidience Shell is the visible desktop and interaction layer. Hyprland owns
composition, outputs, windows, input routing, VRR, fullscreen behavior, and
XWayland. Quickshell owns the Obsidience stage, launcher, panes, and shell API.
WebKitGTK renders the one canonical Three.js knowledge graph behind them.

```text
Linux + systemd + PipeWire + NetworkManager
                    |
                Hyprland
                    |
       adapter/hyprland + Shell API
                    |
     one Quickshell host + one graph host
                    |
      panes, providers, and AI surfaces
```

The shell is not another agent, scheduler, graph authority, or package manager.
It projects typed state from the Harness and delegates privileged operations to
the existing Linux services that already own them.

## One UI implementation

The Hyprland session has one native implementation:

- `qml/shell.qml` is the one shell host;
- `qml/workspace/PaneWorkspace.qml` is the one global module registry, docking
  owner, and persisted-placement owner;
- `qml/workspace/` supplies one shared internal pane frame, one Quickshell
  `FloatingWindow` per undocked module, the launcher, and the 10-pixel grid
  definition;
- `qml/panes/` supplies Chat, Library, Tasks, Reviews, Reader, Knowledge,
  Source, Models, Hardware, Camera, Settings, Feeds, Applications, Terminal, and
  Displays;
- `surfaces/knowledge/host.py` presents the canonical React/Three.js graph;
- `theme/palette.json` remains the visual authority;
- the native Terminal remains one QMLTermWidget view of the persistent
  `obsidience-ui` tmux session.

Hardware is the native Obsidience monitoring pane. It uses the existing module
placement and the canonical `ShellApi.theme`. Summary combines system meters,
CPU and memory history, top processes, and compact resource readings. Performance
selects one CPU, memory, GPU, drive, or network device from a labeled sidebar;
Processes provides the detailed process table. The Harness's read-only
`/api/hardware/monitor` endpoint combines the existing hardware sensors with
psutil's CPU, memory, disk, network, and process counters. One on-demand cache
coalesces callers; no sampler thread or monitoring service runs while the pane
is closed. Charts retain only bounded presentation history, and unavailable or
reset measurements remain gaps rather than zeroes. The process view is read-only.
Sampling uses public psutil iteration and oneshot reads with process-identity
checks. A bounded census limits work; CPU scheduling delays do not truncate a
healthy census. Network summary totals cover physical interfaces; loopback and
virtual interfaces remain available in device details. Unsupported optional GPU
sensors are omitted instead of being presented as failed readings.

Model residency, Realtime devices, camera choice, and Pocket voice remain under
**Settings → AI & Voice**. Their existing hardware/media APIs remain
authoritative, and opening Settings never changes their values. Input,
Workspace, and Connections retain their existing settings sections. Installed
software remains in Applications. TMOG informed the separation of monitoring
views. Its application source is private; the public repository is an issue
tracker. The pane uses the maintained psutil dependency and Qt Quick components,
with no TMOG executable, branding, skin, or source dependency.

There is no Hyprland edition of the panes, no second graph renderer, no
Electron wrapper, and no compositor logic inside a pane. The archived Electron
implementation remains only on `archive/electron-20260828`.

Reader stays the only Article and Source document viewer. Knowledge and Source
can dock left or right, stack top or bottom, collapse to a rail, or detach as
ordinary native toplevels. While docked, each explorer renders only inside
Reader's dock tree and has no standalone toplevel; detaching creates and maps
exactly one `FloatingWindow`. A graph node opens the Reader through the bounded
`obsidience.shell.v1` loopback command contract.

## Native pane contract

Every undocked module is a real Wayland `xdg_toplevel`, not an item in a shared
canvas. There is no QML focus ring or QML stacking authority. Each module
toplevel's initial app ID is exactly `io.obsidience.shell`, and its immutable
initial title is exactly `obsidience-pane:<pane_id>`.
Hyprland and the window adapter classify a module only when both initial fields
match; a later display-title change never changes identity. Its
`FloatingWindow.screen` expresses Surface intent, and Hyprland maps and places
the native pane.

Hyprland is the sole authority for focus, z-order, outer border/shadow/rounding,
interactive movement and resize, native tiling, and `Alt+Tab` traversal.
`input.follow_mouse = 0`, so moving the pointer across panes never steals focus.
Tile bounds are non-exclusive placement coordinates; overlapping native clients
remain stacked, and the visibly focused client receives pointer input throughout
their shared region.
Forward and reverse `Alt+Tab` use Hyprland's native cycle. Close, layout, and
Surface-transfer shortcuts each issue one token-bound native adapter request;
they never preflight or fall back through a QML action. `PaneFrame` supplies
internal module content and title-bar controls only. Its drag region requests
the same standard Wayland interactive move used by native application title
bars.

The module resize selectors use that same native Wayland resize path.
For a tiled client, the `lua:obsidience` layout moves the grabbed shared grid
cut rather than detaching the client from its tile. Adjacent tiles follow the
cut. Raw boxes meet at that cut while Hyprland's native 2/3 px inner insets
render the exact 5 logical px gap; this keeps the opening compositor-owned so
its standard resize cursor works for application and module panes alike. Outer
Surface edges remain fixed, and the persisted Tile behavior limit bounds only
manual movement to at most 25% expansion or contraction by default. OLED motion
is added independently after the manual cut and may pass that percentage while
still keeping every cell positive. Separate right-edge, bottom-edge, and 30 px corner
selectors make one- or two-axis adjustment explicit. They sit on the real
movable cut, flip to the interior edge for an outer tile, and disappear on a
full-span axis. Returning within 5 px of the regular pane size briefly draws
that restored boundary only on the axis being adjusted, so the default is easy
to find without creating another layout authority or changing compositor
geometry. The static-size cue stays hidden during Samsung OLED motion, and a
limit of 0 restores the regular grid and hides the inert tiled selectors.
Freeform panes keep their ordinary right, bottom, and corner selectors.

Tile behavior also exposes an optional Samsung-only OLED mode. Its persisted
defaults are off, 32 px of drift per shared seam, one nominal active hour from center to
either limit, and one neon rotation per three active hours. Every seam starts at
the manual center, then dephases through deterministic direction and ±10% pacing.
A pane can change by
up to twice the configured drift when its opposing seams diverge; the full
reflected path takes four times the center-to-limit setting. One shared
one-second Hyprland timer advances independently phased full-height vertical
seams and connected horizontal segments, writing client geometry only when a
rounded coordinate changes. Both panes sharing a seam consume the same
coordinate, preserving the exact gap. The same timer updates Hyprland's
native cyan border and 5 px inner-glow gradients at most once per active minute,
avoiding continuous 240 Hz angle animation. Geometry remains Samsung-only, while
the compositor-global native chrome deliberately stays identical on every
Surface and only eligible Samsung time advances its angle. Fullscreen, an unavailable Samsung
output, or no visible active Samsung workspace freezes both phases without
catch-up. OLED off restores the manual baseline and ordinary chrome. Motion
phase, glow angle, and seam offsets remain runtime-only. OLED presentation uses
only Hyprland's native pane border and inner glow; the Stage has no separate
outer-edge effect or animation. No pane-local animation, GIF decoder, service,
plugin, full-screen effect, or scheduler owns a second loop.

The existing Quickshell host owns one `WlSessionLock` and one `PamContext`.
Every lock surface starts with the opaque `#02060c` background. Only the Surface
selected by `graph_surface_id` loads the existing knowledge URL with `lock=1`,
so it retains the canonical Three.js visuals and physics; the other Surfaces
show the shared Obsidience identity. The native QML prompt keeps the password
outside WebEngine and releases the lock only after PAM succeeds while the
compositor reports it secure. Authentication reads the root-owned
`/etc/pam.d/obsidience` policy installed from `lock/pam.d/obsidience`; the
user-writable project tree is never the live PAM policy boundary.
The graph view recovers a failed initial navigation from the host's existing
Harness connection signal. It permits one deferred reload per connected
interval, rechecks failures that finish after reconnection, and leaves working
pages alone. A failed page shows the opaque stage instead of Chromium's error
page. This uses Qt WebEngine's loading signals; it adds no connection or timer
and cannot change lock or PAM state. Omarchy Quattro commit
`e848f1df97bbbe23db42fc2b1fb04937d7a0eae0` was inspected for this lifecycle
comparison; no Omarchy code was imported.
Open pane windows, their loaded content, every Surface launcher, and the
ordinary selected Three.js scene stay resident beneath those secure surfaces.
The ordinary graph is hidden and paused rather than destroyed; lock/unlock does
not unmap and reconstruct the desktop clients it securely covers.
A transient monitor removal or geometry mismatch also preserves the resident
WebKit graph. Rebinding the same logical Surface shows its existing page without
HTTP navigation; changing the logical Surface still issues one bound request.

The selected Quickshell 0.3.1 runtime carries two narrow patches. The first
preserves `argv[0]` when creating the GUI application and selects shared Qt
graphics contexts before the first application object. The second is the exact
three-file functional backport from upstream commit `afb2c27`; it serializes
session-lock surface realization and prevents screen changes from reentering
that operation. The patches, upstream hashes, runtime hash, and deterministic
build recipe live under `adapter/quickshell` and in `REUSE_MANIFEST.json`; the
distro-owned executable remains untouched.

Hyprland keeps a secure `ext-session-lock` after its client dies. Obsidience
therefore enables Hyprland's supported `allow_session_lock_restore` option and
uses the small lifecycle helpers under `session/`: `restart-shell` refuses to
kill the live locker, while the host's startup hook detects and reclaims only a
stranded compositor lock. This is the bounded Omarchy Quattro pattern adapted
to the existing Obsidience service and plain lock IPC; it adds no daemon,
polling loop, second locker, or authentication path.

Official `hypridle` requests that lock after five genuinely idle minutes. At
ten idle minutes it applies untargeted Hyprland DPMS off to all displays, and
activity applies DPMS on to all displays. Those two protection listeners ignore
application idle inhibitors so a stale browser or video request cannot hold the
unattended session open; general hypridle behavior remains inhibitor-aware. It
does not suspend, change brightness, authenticate, or participate in pane
placement. The standard live config path points directly to
`idle/hypridle.conf`, so Source and runtime expose the same policy.

Horizontal manual cuts are stored per column. One top/bottom pane pair can move
without moving a separate pair beside it; a pane spanning several columns joins
only the segments required to keep that pane's edge straight.

The native window inventory retains module clients so the unified focus, close,
layout, transfer, and geometry paths can operate on them. Only the Applications
taskbar list filters rows carrying a `pane_id`, because the shell's pane buttons
already represent those windows.

## Compositor boundary

`adapter/hyprland/hyprland.lua` is the compositor configuration. It is
intentionally small:

- Samsung `HDMI-A-1` is admitted through the RTX 4080 at `5120x1440@240`,
  scale 1, 10-bit, and fullscreen-only VRR;
- USB-C `DP-8` and logical DP-4 `HDMI-A-2` are admitted through the AMD iGPU;
- the RTX 4080 stays the primary renderer and the RTX 4000 stays compute-only;
- direct scanout and tearing stay disabled for the first measured gaming
  acceptance;
- the classic M.M.O.7 uses one per-device flat 0.125 multiplier so its verified
  6400-DPI top stage is 800-effective-DPI on every output;
- Obsidience starts through one session target;
- `Super+Return` opens the independent terminal;
- `Super+Shift+Escape` exits to the greeter.

Only `adapter/hyprland` may consume Hyprland-specific events or commands. The
Shell API, panes, graph, and Harness remain compositor-neutral. The window
adapter translates Hyprland state into the bounded window model and accepts the
single validated native command path; the bar and panes never call Hyprland
directly.

## Live development session

Automatic QML file reload is disabled with Quickshell's supported `watchFiles`
setting. Apply Shell changes through `session/restart-shell`, which refuses a
restart while the secure lock is active. Concurrent QML generations can lose
the command listener when the new server binds before the previous server
releases its port. An explicit guarded restart replaces the host once; no
listener retry loop or compositor restart is needed for ordinary QML changes.

`Obsidience` is the UWSM desktop session. Its services are:

- `obsidience-shell-session.target`;
- `obsidience-shell-host.service`;
- `obsidience-shell-knowledge.service`;
- `obsidience-shell-notifications.service`.

The graph presenter belongs to the Shell session. It requires the Shell host
and wants the Harness for startup, with ordering and the existing HTML readiness
check. Stopping or restarting the Harness must leave the resident graph alive:
its existing API and activity connections recover when the provider returns.
Keep the last accepted graph through that outage; a clean dependency stop must
not strand the presenter after a development restart.

The live session, Harness, Vault, UI, and Source projection all use the one
canonical project at `/home/wissenschafter/Projects/obsidience` and the shared
`obsidience-shell` state. One Quickshell process creates the stage and bar on
each Hyprland output plus the one global `PaneWorkspace`; that workspace maps
each open, undocked module as its own `FloatingWindow`. Hyprland is an adapter
boundary, not a second product or runtime namespace.

greetd launches this session as the default. KWin, Plasma Shell, Plasma Login
Manager, KScreenLocker, and SDDM are removed from the live installation. The
Quickshell session-lock path covers every Hyprland output and authenticates
through PAM; greetd remains responsible for fresh login. A native Polkit UI,
HDR, fullscreen VRR, and Samsung WoW behavior remain explicit acceptance gates.

## Surface contract

A Surface is an Obsidience presentation endpoint, not an Article kind or raw
Wayland object. Every module pane retains one generic persisted record:

```text
pane_id + surface_id + local_rect + open + optional tile_bounds
```

The three-Surface data model maps Samsung `HDMI-A-1`, USB-C `DP-8`, and logical
DP-4 `HDMI-A-2` into one Hyprland layout. No pane-specific process or display
bridge is permitted. Native pointer, clipboard, focus, movement, resize, and
stacking belong to Hyprland. `PanePlacement` keeps one canonical record beneath
the user's XDG state directory. A newly mapped open module receives one saved
semantic tile restore through the existing adapter before native observations
may update that record; failed or stale restoration leaves it untouched. Settled
compositor geometry is then runtime truth. Pointer dragging stays local to one
Surface; keyboard transfer is one native command followed by one mirrored
placement revision.

## Package policy

`system-packages.toml` is the names-only Arch package contract for this Module.
It is additive: a missing name means "not managed here," never "remove it."
The required groups describe the target Hyprland shell; protected groups mark
the current boot/graphics and gaming packages that no cleanup may prune. Exact
observed versions and upstream provenance
remain evidence in `REUSE_MANIFEST.json`, not rolling-release policy.

The package manifest is separate from the Applications pane and from any future
community shell-package format. It performs no installation, update, or
removal by itself.

## Verification

Before a live session change:

```sh
Hyprland --verify-config --config obsidience/shell/adapter/hyprland/hyprland.lua
desktop-file-validate obsidience/shell/session/obsidience.desktop
systemd-analyze --user verify obsidience/shell/systemd/*.service \
  obsidience/shell/systemd/*.target
```

Live acceptance requires all three exact output geometries and GPUs, one
Hyprland process, one shell host, one graph host, healthy Harness API, native
pointer traversal, usable tmux recovery, pane interaction, and launcher
behavior, all-Surface session-lock coverage, and a successful PAM unlock. HDR,
fullscreen VRR, and WoW are separate physical gates.

Obsidience borrows only architecture lessons and reviewed plumbing from
upstream projects. Omarchy's single warm Quickshell host and modular package
boundary are reference patterns; its visual design, scripts, Hyprland config,
IPC, and package authority are not imported.
