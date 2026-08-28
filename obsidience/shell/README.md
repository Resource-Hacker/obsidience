# Obsidience Shell

This Module is the native shell boundary beneath the existing Obsidience UI.
It replaces `plasmashell`; KWin remains the unmodified compositor. Upstream
Quickshell is the sole native renderer. The first native slice owns one exact
Samsung Wayland Stage matching the current Obsidience visual language.

The Electron/React interface remains unchanged on the isolated USB-C display
while panes are ported. It is an ordinary development application, not the
shell host. Its complete pre-native state is preserved by Git branch
`archive/electron-20260828` and tag `electron-v0-dev-20260828`.

Each display server has one long-running native Surface render host. Samsung
uses `shell.qml`; isolated X11 Surfaces use the small `surface.qml` entrypoint.
Both consume the same PaneFrame and placement components, so a pane changes
one shell-owned placement record instead of pretending a native window can be
reparented across display servers. Each real feature owns a direct folder
matching its function; the initial native slice has `surfaces/stage/`, its
reusable `components/identity/`, and the shared `workspace/` pane components.
Panels, overlays,
notifications, the launcher, lock screen, providers, widgets and community
packages are added only when a working implementation exists. A future package
registry will use one versioned manifest contract for first-party and reviewed
community packages, while shared providers are instantiated once by the host
and injected through the typed Obsidience Shell API.

`qml/api/ShellApi.qml` is instantiated exactly once by the host and injected
into the Stage. Its first real contract is deliberately tiny: API
version plus the exact KWin output that may receive shell surfaces. Compositor
events and bounded commands join that same object only after the separate KWin
adapter transport is live.

This follows the useful host/package boundary in Omarchy's experimental
`quattro/shell` architecture without importing its visual design, Hyprland
integration, shell scripts, configuration authority or unsandboxed package
policy. Community code will not replace the adapter, Shell API, lock presenter,
approval presenter or other trusted infrastructure. Obsidience's graph and
harness remain the semantic authority.

Obsidience is the default login session and `plasmashell` remains disabled so
there is only one shell owner. KWin and running applications survive a shell
restart; the independent terminal is the recovery path.

`Surface` is Obsidience's stable presentation endpoint, not a graph kind and
not a raw Wayland object. Samsung, USB-C, and DP-4 remain separate display
server clients with independent render loops and performance budgets. Every
pane carries the same Surface-aware placement state; a boundary drag transfers
one logical pane and its UI state to the destination render host instead of
trying to move one native X11 window into Wayland. The Surface hosts share one
atomic shell-state projection; no coordinator daemon, harness coupling, or
KWin mutation is introduced.

KWin-specific observation and commands stay behind `adapter/kwin`. The
renderer, panes, widgets, and extensions consume stable Obsidience state and do
not call KDE-private interfaces directly. The retired Python/GTK host exists
only in the preserved Electron checkpoint, not in native-shell source.

No external project's visual design, assets, widgets, renderer, configuration,
or IPC runtime are imported. The pinned Noctalia source contributes only the
read-only KWin observation pattern documented in `REUSE_MANIFEST.json`.
