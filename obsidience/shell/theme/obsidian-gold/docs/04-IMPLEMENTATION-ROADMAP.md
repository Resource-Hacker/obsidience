# Implementation roadmap

## Phase 0: package and review (this delivery)

Place the first theme in `obsidience/shell/theme/obsidian-gold`, with an inactive compatible palette, semantic design tokens, original static assets, the offline atlas and per-pane ownership map. Do not mutate the active palette, compositor config, model slots or session units. Review the overall Desktop, Reader, Terminal, Graph and Appearance designs before broad native work.

Completion: the package opens offline, all registered native pane IDs are covered, 53 routes have matching designs, palette validates under the existing validator, and design-only actions are visibly inert. The generated verification report records actual checks and limits.

## Phase 1: one semantic paint system

Extend the existing ShellTheme owner deliberately to expose the semantic roles required by the theme. Keep the compatible native palette contract for existing consumers; if a schema extension is warranted, version and migrate it explicitly rather than allowing silent per-pane fallbacks. Inject one theme instance into shared controls and pane roots; do not create a FileView watcher in every pane.

Migrate shared `components/visual` first, then `PaneFrame`, module headers, launcher and surface chrome. The compositor retains outer borders and focus. Use theme-derived Qt control palettes for imported Basic controls so dialogs/media/settings do not fall back to unrelated toolkit colors. Preserve disabled, focus, pending and error states.

Then migrate pane groups: Reader/Knowledge/Source/Library; Tasks/Reviews/Chat; Hardware/Models; Applications/Media/Camera; Settings; Terminal and web viewers. Replace semantic hardcodes by role, not a global search-and-replace of every cyan RGB literal. Graph Article kinds and terminal syntax colors have different semantics from selection borders.

Completion: no stray cyan structural chrome, no unreadable disabled text, and current interactions/states remain intact. Verify native rendering at 1×/2× and 200% text, with low-motion settings and actual focus traversal.

## Phase 2: coherent native theme selection

Add **Appearance → Obsidience Themes** inside the existing Settings pane. Update both the visible sections list in `SettingsPane.qml` and the validated selection allowlist in `api/command/PaneCommands.qml`; otherwise the new section can render but cannot be reliably selected through the existing shell protocol. Keep one route owner and explicit failure replies.

Load the catalog as allowlisted data. A selectable package contains a compatible palette plus declarative assets/projections, never arbitrary startup scripts. Preview the changed surfaces and report unsupported integrations before activation. Validate the complete next state, retain the previous palette, replace the active palette atomically and project one selected generation into supported consumers. Keep rollback, including partial projection failure information. Do not silently restart apps or claim complete success while one toolkit remains on the old colors.

Completion: applying/restoring a theme does not move panes, rebuild graphs, detach terminal sessions, change model residency, alter device settings or bypass the secure-lock restart guard.

## Phase 3: daily desktop controls

Build the unified quick-settings drawer and Settings sections with narrow service adapters: NetworkManager, BlueZ, PipeWire/WirePlumber and existing power/idle state. Add SNI presentation where desired. Reuse the active mako notification owner for history/focus controls or design an explicit handoff; never start a second notification server. Surface provider absence and permission errors immediately.

Add safe output configuration through the **existing compositor adapter**, with exact output identity, supported-mode validation, temporary apply, visible countdown, accept/revert and automatic rollback. Keep accepted HDR/VRR/game policies untouched by theme selection.

Completion: launcher, network recovery, volume, session controls and notifications remain operational with all models unloaded and the Executive unavailable. Real backend writes return acknowledged/failed/uncertain results and are not automatically replayed when outcome is uncertain.

## Phase 4: desktop ecosystem consistency

Use installed Dolphin/native file tools for full filesystem behavior and keep Source/Reader specialized. Integrate portal file choosers, print and screen-sharing flows within supported toolkit limits. Extend the existing Applications/PackageKit owner for full transactions, progress/error/history/restart guidance. Verify graphical polkit and credential-provider behavior before exposing privileged mutations.

MPRIS player controls are a system presentation separate from Obsidience’s TV/media library owner. Clipboard history is an explicit optional provider with retention and lock privacy, not an automatic AI-memory stream. Calendar events require a real connected source. Account, locale, default app and startup controls present existing services and units rather than creating new global stores.

Completion: daily file, package, capture, sharing, credential and device workflows are usable and coherent; unavailable optional services stay honestly unavailable.

## Phase 5: secure surfaces and release acceptance

Restyle only the existing native locker and trusted auth surfaces. Preserve full opaque output coverage, PAM isolation, lock recovery and native failure handling. Treat login greeter styling as a separate session-entry integration. A convincing HTML password prompt is not an implementation.

Run the manual acceptance sequence in `06-ACCEPTANCE-AND-ROLLBACK.md` against the real native shell. Review compositor/display invariants and performance. Release `1.0.0` only when the documented native coverage is complete; the current `0.1.0` is a design-preview package.

## Implementation discipline

Every change lands in its current owner; proposed files are added only for an actual missing presentation or adapter. No parallel command bus, graph solver, scheduler, clipboard bridge, credential store, media server or window manager. No automated tests or fixtures are added by this plan without the owner requesting them. Use focused direct validation, native smoke checks and recorded evidence under the existing evidence/state conventions. Preserve unrelated work in the shared checkout; commit only the approved theme implementation changes.
