# Theme integration map

## Current contracts

`obsidience/shell/theme/palette.json` is the live authority. `qml/api/ShellTheme.qml` loads the selected path and watches the file. The currently accepted schema is `obsidience.shell-theme.v1`, with internal name `Obsidience`, twelve exact color keys and six metric keys. QML eight-digit colors are **#AARRGGBB**, not CSS #RRGGBBAA. The package's compatible preset keeps this contract. Semantic design tokens live in a separate package document pending a deliberate runtime migration.

The Edge policy adapter at `obsidience/browser/edge/theme_policy.py` validates the same exact native contract. Do not add package metadata inside the palette root; its validator rejects unknown keys. Friendly identity, version and activation status belong in `theme.json`/`catalog.json`.

## Source-by-source integration

| Surface | Current owner | Required work | Must not change |
|---|---|---|---|
| Native frame | `qml/workspace/PaneFrame.qml` | Use existing ShellTheme for internal chrome; adjust control roles/metrics only | Native move/resize, focus, title identity |
| Outer border / active window | `adapter/windows` and `adapter/hyprland` | Project selected generation into supported decoration seam | Compositor ownership, output policy, geometry |
| Launcher / shelf | `qml/workspace/ApplicationLauncher.qml`, `PaneLauncher.qml` | Shared controls, SNI/quicksettings entry points where added | Native application identity and activation protocol |
| Surface background | `qml/surfaces/wordmark/StageContent.qml` | Optional static matte/arc treatment in supported background layer | Canonical graph host, surface mapping, lock opacity |
| Shared controls | `qml/components/visual` | Semantic button, combo, icon, focus and Qt palette roles | Tool/operation dispatch and input ownership |
| Native pane interiors | `qml/panes/**` | Migrate local semantic hardcodes, reduce one-off delegates | Existing API paths, retries, state, writes and receipts |
| Hardware | `panes/hardware/HardwarePane.qml` | Already largely theme-injected; validate controls/charts | Bounded on-demand monitor, missing values |
| Graph | `panes/graph/GraphViewerPane.qml`, existing UI renderer source | Theme chrome/CSS and graph semantic role colors through current presenter | One renderer, physics, picking, IDs, frame transport |
| Terminal | `panes/terminal/TerminalPane.qml` + existing terminal renderer | Theme ANSI palette, selection, cursor and clipboard menu | tmux identity, output stream, active agent sessions |
| Media / TFT web views | Existing respective viewer/app owners | Same token export where supported; explicit unsupported coverage | Existing URL/navigation policies, recorder/player authority |
| Settings | `panes/settings/SettingsPane.qml` | Add Appearance section in one pane; unify control palette | Graph/Input/Workspace/AI & Voice section identities |
| Settings route validation | `qml/api/command/PaneCommands.qml` | Add explicit allowed appearance selection with normal error handling | Token validation, revision guards and owner dispatch |
| Browser chrome | `obsidience/browser/edge/theme_policy.py` | Use existing supported managed color projection | Policy authority, credentials, browser lifecycle |
| Qt / GTK dialogs | Installed toolkit settings and XDG portal backend | Color-scheme/dark preference projection within supported toolkit limits | Portal permissions, sandbox handles, native auth |
| Native lock | `qml/lock/` | Restrained text/control paint on the secure surface | Sole WlSessionLock/PAM lifecycle and opaque black coverage |
| Login / polkit | greetd + supported native greeter / system polkit agent | Separate audited native integration | No WebEngine credentials, no duplicated authentication authority |

## Semantic migration, not global replacement

A cyan value may mean a graph kind, a hover border, a microphone indicator, a terminal syntax token or a link. Classify each use before mapping it. The new brand brass is not a success indicator and cannot replace red error or green outcome semantics. Keep provider-specific graph types distinct without turning them into new Article kinds.

Source inspection found substantial hardcoding in Reader, Models, Tasks, Source, Library, Reviews and Settings. A one-file palette swap primarily affects already-wired chrome and Hardware; it does not prove full theming. The inspection inventory records per-file counts for scoping, not as a correctness metric.

## Declarative package security

The atlas contains JavaScript because it is an offline design tool, **not** because production themes may run code. The native package loader should accept only schema-validated palette/token data and allowlisted static assets. Reject path traversal, symlinks escaping the package, arbitrary scripts, startup hooks and untrusted font/plugin loading. Limit image dimensions/resource cost. Keep token files non-secret.

Omarchy was consulted as architectural reference only: `bin/omarchy-theme-set` at commit `8a787b6a8bec830b04543bf14c760ee0a10591f6`. Its staging, generation and failed-projection reporting illustrate why theme application is an operation with partial-failure handling. Its code, services, scripts and theme runtime were not copied or adopted. Obsidience keeps its existing visual authority and lifecycle.

## Alpha and generated exports

The compatible preset uses opaque native surfaces. `exports/tokens.css` uses six-digit opaque RGB for browser CSS. Terminal/toolkit exports are color-only and are not installed automatically. When a future export includes transparency, convert QML alpha ordering explicitly; never feed a nine-character QML string straight into CSS.

No user font files are bundled. The current `JetBrains Mono` choice is an installed-font reference with a fallback, not a copied font asset.
