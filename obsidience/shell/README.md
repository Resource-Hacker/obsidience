# Obsidience Shell

This Module is the native shell boundary beneath the existing Obsidience UI.
It is built to replace `plasmashell`; KWin remains the unmodified compositor.
The first development slice owns a Samsung-only Wayland background Surface and
an exclusive top panel, then displays bounded read-only KWin workspace and
active-window state.

The current Electron/React interface remains unchanged on the isolated USB-C
display. It is an ordinary application window, not a layer-shell surface. A
future renderer-host slice can join the native shell only after that boundary
is independently verified.

Obsidience is the default login session and `plasmashell` remains disabled so
there is only one shell owner. KWin and running applications survive a shell
restart; the independent terminal is the recovery path.

`Surface` is Obsidience's stable presentation endpoint, not a graph kind and
not a raw Wayland object. Samsung, USB-C, and DP-4 remain separate display
server clients. Every pane carries the same Surface-aware placement state; a
future boundary drag transfers pane ownership and UI state to the destination
render host instead of trying to move one native X11 window into Wayland. The
same shell host owns this placement update; no extra coordinator service is
introduced.

KWin-specific observation and commands stay behind the Shell adapter. The host,
renderers, panes, widgets, and extensions consume stable Obsidience state and do
not call KDE-private interfaces directly. No empty adapter/package hierarchy is
created before a real second implementation exists.

No external project's visual design, assets, widgets, renderer, configuration,
or IPC runtime are imported. The pinned Noctalia source contributes only the
read-only KWin observation pattern documented in `REUSE_MANIFEST.json`.
