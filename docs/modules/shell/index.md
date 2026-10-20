# Shell

The Shell is Obsidience's desktop integration and presentation boundary in
`obsidience/shell/`, with the shared web graph code in `obsidience/ui/`.
**Hyprland** owns composition, outputs, windows, input routing, VRR, fullscreen
and XWayland. **One Quickshell host** owns the native shell controls and panes.
A separate Quickshell/QtWebEngine **graph stage** displays the canonical
Three.js graphs on the selected Surfaces.

```text
Linux services (systemd, PipeWire, NetworkManager)
                    |
                Hyprland
                    |
       adapter/hyprland + Shell API
                    |
     one Quickshell host + one graph host
                    |
      panes, providers and AI surfaces
```

The Shell is not another Agent, scheduler, graph authority or package manager.
It projects typed state from the Harness and delegates privileged operations to
the Linux services that already own them. A failing pane, model or graph never
ends the session; basic desktop functions work without models, and an
independent terminal is the recovery path.

## Panes

`qml/shell.qml` is the one shell host and `qml/workspace/PaneWorkspace.qml` the
one module registry, docking owner and placement owner. The panes in
`qml/panes/` are named by what they do: Chat, Library, Tasks, Reviews, Reader,
Knowledge, Graph, Source, Models, Hardware, Camera, Settings, Media,
Applications, Terminal and others. One pane per function: no duplicate pane,
graph or Reader.

- **Chat** owns the conversation, the voice mode controls and the live
  transcript.
- **Reader** is the single Article and Source viewer (native Qt Quick), with
  Knowledge and Source explorers that dock left, right, top or bottom, collapse
  to a rail or detach.
- **Reviews** holds staged proposals and persistent health notifications.
- **Graph** hosts the Knowledge, Memory and Code views
  ([Graph UI](graph-ui.md)).
- **Settings** is one sectioned pane; **AI & Voice** owns model residency and
  device and voice choices, never system defaults.
- **Hardware** is a read-only monitor that samples only while visible.
- **Terminal** is a native view of a persistent tmux session.

## Native windows

Every undocked module is a real Wayland toplevel identified by its initial app
id `io.obsidience.shell` and title `obsidience-pane:<pane_id>`; external
applications stay native clients, never embedded or mirrored.

Hyprland's `lua:obsidience` layout is the sole focus, z-order, chrome,
move/resize, `Alt+Tab` and tiling authority, and focus is click-driven. Each
Surface has one tile grid (Settings → Workspace):

| Shortcut | Action |
| --- | --- |
| ++meta++ + arrow keys | Resize the active tile |
| ++ctrl+meta++ + arrow keys | Translate the active tile |
| ++meta+shift++ + arrow keys | Move the active pane to the nearest mapped Surface |
| ++meta+esc++ | Close the active pane |

## Surfaces

A **Surface** is an Obsidience presentation endpoint for one physical display
workspace, not an Article, Tool or Wayland object. Each pane keeps one
persisted placement record (`pane_id + surface_id + local_rect + open +
tile_bounds`). `~/.config/obsidience-shell/surface-layout.json`, seeded from
`obsidience/shell/defaults/initial-surface-layout.json`, maps each Surface to a
monitor by its Hyprland description, with a connector name only as a fallback;
the compositor configuration, the window adapter and the layout shortcuts all
resolve monitors this way. The setting `graph_surface_id` selects the Surface
that shows the Executive graph.

## Session, lock and commands

- **Session.** greetd starts one UWSM Hyprland session; the
  `obsidience-shell-session.target` wants the host, graph stage, window
  adapter, notifications and the Harness service. Unit sources are in
  `obsidience/shell/systemd/`.
- **Lock.** The Quickshell host is the sole locker: one `WlSessionLock` and one
  PAM context (policy `/etc/pam.d/obsidience`, installed from
  `lock/pam.d/obsidience`). The graph Surface may show the paused graph as
  decoration that never sees credentials. `hypridle` requests the lock and
  display power-off; there is no suspend.
- **Commands.** Graph pages and panes send typed commands such as
  `pane.present` and `pane.select` over the loopback `obsidience.shell.v1`
  WebSocket with the host's per-start token; the server validates an allowlist.
  Only `adapter/hyprland` talks to Hyprland.
- **Development reloads.** Automatic QML reload is off. Apply Shell changes
  with `obsidience/shell/session/restart-shell`, which refuses while the session
  is locked and leaves the resident graph alive.

## Edge Cast client

`obsidience/browser/edge/` holds the Edge Cast browser extension, its native
messaging host and its theme policy.

The full contract, including the package policy and the live acceptance
checklist, is in the
[Shell README](https://github.com/Resource-Hacker/obsidience/blob/main/obsidience/shell/README.md).
