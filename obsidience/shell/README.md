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

- `qml/shell.qml` is the one primary shell host;
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

`adapter/hyprland/hyprland.lua` is the first Hyprland configuration. It is
intentionally small:

- only the Samsung `HDMI-A-1` is admitted through the RTX 4080 DRM device;
- mode is `5120x1440@240`, scale 1, 10-bit, fullscreen-only VRR;
- direct scanout and tearing stay disabled for the first measured gaming
  acceptance;
- Obsidience starts through one session target;
- `Super+Return` opens the independent terminal;
- `Super+Shift+Escape` exits to the greeter.

Only `adapter/hyprland` may consume Hyprland-specific events or commands. The
Shell API, panes, graph, and Harness remain compositor-neutral. The eventual
window provider will translate Hyprland state into the existing bounded window
model rather than adding compositor calls to the bar or panes.

## Live development session

`Obsidience (Hyprland)` is a separate UWSM session. Its services are:

- `obsidience-hyprland-session.target`;
- `obsidience-shell-hyprland-host.service`;
- `obsidience-shell-hyprland-knowledge.service`;
- `obsidience-shell-hyprland-notifications.service`.

The live session points at the `obsidience-hyprland` worktree and uses the
state namespace `obsidience-hyprland`. Primary-only mode places pane defaults
on Samsung so the existing
USB-C defaults do not make a one-output session appear empty.

greetd launches this session as the default. KWin, Plasma Shell, Plasma Login
Manager, KScreenLocker, and SDDM are removed from the live installation. The
session deliberately initializes its private lock byte as unlocked; it is a
development desktop, not a secure lock implementation. Secure locking, a
native Polkit UI, HDR, fullscreen VRR, and Samsung WoW behavior remain explicit
acceptance gates. USB-C and DP-4 remain temporary isolated Xorg Surfaces.

## Surface contract

A Surface is an Obsidience presentation endpoint, not an Article kind or raw
Wayland object. Every pane retains one generic record:

```text
pane_id + surface_id + local_rect + open + z_order
```

The existing three-Surface data model remains readable during migration.
Hyprland renders only Samsung; USB-C and DP-4 are introduced
only after the Samsung VRR/HDR/WoW baseline is measured. No pane-specific
display bridge is permitted. Pointer dragging stays local to one Surface and
keyboard transfer remains one atomic placement revision when multiple Surfaces
are active.

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
desktop-file-validate obsidience/shell/session/obsidience-hyprland.desktop
systemd-analyze --user verify obsidience/shell/systemd/*hyprland*
```

Live acceptance requires the exact Samsung geometry and GPU, one Hyprland
process, one shell host, one graph host, healthy Harness API, usable tmux
recovery, pane interaction, and launcher behavior. Secure locking, HDR,
fullscreen VRR, and WoW are separate physical gates.

Obsidience borrows only architecture lessons and reviewed plumbing from
upstream projects. Omarchy's single warm Quickshell host and modular package
boundary are reference patterns; its visual design, scripts, Hyprland config,
IPC, and package authority are not imported.
