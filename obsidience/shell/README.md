# Obsidience Shell

This Module is the native shell boundary beneath the existing Obsidience UI.
It replaces `plasmashell`; KWin remains the unmodified compositor. Upstream
Quickshell is the shell host and native Qt Quick pane renderer. The bounded
WebKitGTK host renders only the canonical Three.js graph. The first native
slice owns one exact Samsung Wayland Stage matching the current Obsidience
visual language.

The Electron application is disabled on the `native-shell` branch. Its complete
pre-native state is preserved by Git branch `archive/electron-20260828` and tag
`electron-v0-dev-20260828`; it is not a concurrent shell or pane owner.

Each display server has one long-running native Surface render host. Samsung
uses `shell.qml`; isolated X11 Surfaces use the small `surface.qml` entrypoint.
Both consume the same PaneFrame and placement components, so a pane changes
one shell-owned placement record instead of pretending a native window can be
reparented across display servers. Each real feature owns a direct folder
matching its function; the initial native slice has `surfaces/stage/`, its
reusable `components/identity/`, and the shared `workspace/` pane components.

The knowledge desktop is a Shell component, never a pane or separate Module.
One global `graph_surface_id` in the existing Surface layout selects Samsung,
USB-C, or DP-4. The selected host alone presents the existing `GraphBackdrop`
bundle from the harness's loopback origin. The graph therefore keeps one active Three.js renderer,
one `d3-force-3d` simulation, the existing shaders, satellites, labels,
selection, camera controls, settings and ordered retrieval activity path; it
does not have a second QML graph implementation or require Electron. The
transparent Qt Quick Stage remains above it only for shell identity chrome and
has an empty input mask. Graph Settings owns one immediate-persist Display
selector; it is global and intentionally does not yet route individual Agents.

A graph node click sends its exact Article reference through one bounded
`pane.present` command on the loopback `obsidience.shell.v1` WebSocket. The
primary `shell.qml` host is the only `ShellCommandServer` owner. It validates
the generic command envelope, permits exact Reader Article or Source targets,
updates the Reader's ordinary `PanePlacement`, and broadcasts one typed
`pane.state` event. Both `shell.qml` and `surface.qml` own one full-Surface
`PaneCanvas`. Every registered pane is an ordinary sibling item inside that
canvas, and the shared placement record makes each pane visible on exactly one
Surface. The canvas's native input mask is only the union of its open pane
rectangles, so the desktop between panes remains click-through. Reader consumes
the selection, reads an exact Article from `/api/articles/{ref}` or exact Source
bytes from `/api/source-files/{key}`, and renders the document in one
translucent Qt Quick pane. The knowledge WebKit
surface remains graph-only. There is deliberately no `?surface=reader` route,
Reader web wrapper, Electron IPC path, or coordinator daemon.

Knowledge and Source are native explorer Modules around that single Reader,
matching the archived Electron composition and palette: Knowledge is cyan on
`#020a12`, Reader remains the centered document surface, and Source is violet
on `#08050f`. One primary-owned `PaneDockLayout` persists their left/right,
top/bottom order and collapsed state. Docked explorers follow Reader to its
Surface and split a shared side evenly; detaching restores each explorer's
ordinary `PanePlacement`. The four docking targets live inside Reader, so this
adds no window bridge, renderer, process, or second Article/Source viewer.

The native Terminal pane uses the installed `QMLTermWidget` emulator for its
Local Console and the existing bounded trace WebSocket for its Action Trace.
Its fixed wrapper attaches to the existing `obsidience-ui` linked tmux session
as the tmux sizing owner. The fixed readable font and viewport follow the pane,
and tmux uses the largest attached client so the grid reflows across the full
pane without letterboxing. DP-4 is a passive mirror and does not constrain the
native Terminal's dimensions. Transferring or closing the pane replaces only
that view; the user tmux service keeps the live Codex process persistent.
The retired Electron terminal, PTY bridge, xterm renderer, and their packages
are removed from the native-shell branch so they cannot attach a second client.

`PaneWorkspace.qml` is the single pane registry used by every Surface host. It
contains Chat, Library, Tasks, Reviews, Reader, Knowledge, Source, Models,
Hardware, Camera, Settings, Terminal, and Displays. Each pane has the same
generic frame, placement, resize, close, focus, and keyboard cross-Surface
transfer behavior. `PaneItem` and `PaneFrame` are the sole floating-pane
interaction path; individual pane Modules contain no outer drag code. One
`SurfaceLayout` usable-bounds rule keeps every title-bar handle below shell
chrome during drag, reopen, and Surface transfer. The same record owns one
global logical-pixel pane grid: 10 px by default, applied to floating-pane
position and size before minimum and boundary clamps. Settings uses a
Reader-like section rail; Graph relays typed preview/save/test commands to the
canonical Three.js graph store, while Workspace changes the shared pane grid.
Neither creates a second settings database or standalone bar item.

Every Surface also instantiates one shared top bar in this exact order:
application launcher, Realtime controls, Surface-local running applications,
pane icons, and a minute-precision clock. The pane title, icon, and accent all
come from the one pane registry. The human launcher uses Quickshell's native
Desktop Entry API. A separate event-driven adapter observes KWin and the two
X11 roots, projects one bounded application list per Surface, and activates
only an exact current window ID at the current revision. The bar never polls
`wmctrl`, matches a title, or talks directly to a compositor.

Applications remain real KWin or Openbox windows rather than shell panes. One
data-only `theme/palette.json` is the presentation authority for shared pane
chrome and supported native application projections. `ShellTheme` watches that
palette directly, while the bounded one-shot theme adapter flattens the same
colors for KWin, both Openbox roots, and Edge's supported Chromium policy.
This follows Omarchy's palette-to-native-adapter method without importing
Hyprland or wrapping applications. Edge tabs and toolbar adopt the Obsidience
surface color; websites and application content remain application-owned.
The launcher and application-window adapter retain their existing dispatch,
observation, and exact-ID activation responsibilities and never mutate theme
state or window geometry.

The accepted native runtime packages are `quickshell 0.3.0-2.1`,
`gtk-layer-shell 0.10.1-1.1`, `webkit2gtk-4.1 2.52.4-1`, and
`python-gobject 3.56.3-1`, `python-dbus 1.4.0-2`,
`python-websockets 16.1.1-1.1`, `python-xlib 0.33-6`,
`qmltermwidget 2.0.0.git1-1.1`,
`qt6-webengine 6.11.1-2`, `qt6-websockets 6.11.1-1.1`, and
`kscreenlocker 6.6.5-1.1`.
`module.toml` declares the executable
entrypoints and these exact development dependencies; `REUSE_MANIFEST.json`
records their upstream provenance. The knowledge surface uses the existing
harness origin and does not start a second HTTP server or graph authority.

KScreenLocker and PAM remain the sole security and authentication authority.
The local `org.obsidience.lockgraph` Plasma Wallpaper renders the canonical
graph behind KDE's stock Samsung prompt when Samsung is selected. The same
private lock-state byte hides every pane and bar. On USB-C and DP-4, the
selected Surface receives one input-empty graph cover while the nonselected
Surface receives an opaque graph-free privacy cover. The root input router
stays closed until KDE reports successful unlock. USB-C and DP-4 never receive
a password field, and unlock never restores their prior input lease. Providers,
widgets and community packages are added
only when a working implementation exists. A future package
registry will use one versioned manifest contract for first-party and reviewed
community packages, while shared providers are instantiated once by the host
and injected through the typed Obsidience Shell API.

Each render host instantiates the same small `qml/api/ShellApi.qml` projection
and injects it into its Stage and panes. Its current contract is deliberately
tiny: API version, exact output identities, the shared semantic theme, and the
shared Surface layout. The
primary host alone instantiates `ShellCommandServer`; isolated render hosts
consume the same atomic `PanePlacement` files and never bind the command port.
Compositor events join the Shell API only after the separate KWin adapter
transport is live.

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
pane carries the same Surface-aware placement state. Pointer dragging clamps to
the current Surface's shared usable bounds. `Meta+Shift+Arrow` transfers one logical pane and its UI
state to the nearest mapped destination render host instead of trying to move
one native X11 window into Wayland. KWin owns the physical chord on Samsung and
uses the existing D-Bus adapter. The existing single-owner input router consumes
the exact chord on USB-C and DP-4 before XTest forwarding; both paths call the
same bounded shell command client. The Surface hosts share one atomic
shell-state projection; no Openbox shortcut, coordinator daemon, harness
coupling, or compositor-window mutation is introduced.

KWin-specific observation and commands stay behind `adapter/kwin`. The
renderer, panes, widgets, and extensions consume stable Obsidience state and do
not call KDE-private interfaces directly. The earlier general Python/GTK shell
host remains retired; the bounded knowledge host owns only the canonical web
graph's background layer surface.

No external project's visual design, assets, widgets, renderer, configuration,
or IPC runtime are imported. The pinned Noctalia source contributes only the
read-only KWin observation pattern documented in `REUSE_MANIFEST.json`.
