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

The Hyprland session reuses the existing native implementation unchanged:

- `qml/shell.qml` is the one shell host;
- `qml/workspace/` supplies the shared pane frame, placement, drag, resize,
  focus, docking, launcher, and 10-pixel grid behavior;
- `qml/panes/` supplies Chat, Library, Tasks, Reviews, Reader, Knowledge,
  Source, Models, Hardware, Camera, Settings, Applications, Terminal, and
  Displays;
- `surfaces/knowledge/host.py` presents the canonical React/Three.js graph;
- `theme/palette.json` remains the visual authority;
- the native Terminal remains one QMLTermWidget view of the persistent
  `obsidience-ui` tmux session.

There is no Hyprland edition of the panes, no second graph renderer, no
Electron wrapper, and no compositor logic inside a pane. The archived Electron
implementation remains only on `archive/electron-20260828`.

Reader stays the only Article and Source document viewer. Knowledge and Source
can dock left or right, stack top or bottom, collapse to a rail, or detach as
ordinary panes. A graph node opens the Reader through the bounded
`obsidience.shell.v1` loopback command contract.

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
Shell API, panes, graph, and Harness remain compositor-neutral. The eventual
window provider will translate Hyprland state into the existing bounded window
model rather than adding compositor calls to the bar or panes.

## Live development session

`Obsidience` is the UWSM desktop session. Its services are:

- `obsidience-shell-session.target`;
- `obsidience-shell-host.service`;
- `obsidience-shell-knowledge.service`;
- `obsidience-shell-notifications.service`.

The live session, Harness, Vault, UI, and Source projection all use the one
canonical project at `/home/wissenschafter/Projects/obsidience` and the shared
`obsidience-shell` state. One Quickshell process creates a pane canvas and bar
on each Hyprland output. Hyprland is an adapter boundary, not a second product
or runtime namespace.

greetd launches this session as the default. KWin, Plasma Shell, Plasma Login
Manager, KScreenLocker, and SDDM are removed from the live installation. The
session deliberately initializes its private lock byte as unlocked; it is a
development desktop, not a secure lock implementation. Secure locking, a
native Polkit UI, HDR, fullscreen VRR, and Samsung WoW behavior remain explicit
acceptance gates.

## Surface contract

A Surface is an Obsidience presentation endpoint, not an Article kind or raw
Wayland object. Every pane retains one generic record:

```text
pane_id + surface_id + local_rect + open + z_order
```

The three-Surface data model maps Samsung `HDMI-A-1`, USB-C `DP-8`, and logical
DP-4 `HDMI-A-2` into one Hyprland layout. No pane-specific process or display
bridge is permitted. Native pointer, clipboard, focus, and application movement
belong to Hyprland; pointer pane dragging stays local to one Surface and keyboard
pane transfer remains one atomic placement revision.

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
behavior. Secure locking, HDR, fullscreen VRR, and WoW are separate physical
gates.

Obsidience borrows only architecture lessons and reviewed plumbing from
upstream projects. Omarchy's single warm Quickshell host and modular package
boundary are reference patterns; its visual design, scripts, Hyprland config,
IPC, and package authority are not imported.
