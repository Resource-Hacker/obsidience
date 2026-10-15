# Desktop completeness: Obsidience vs KDE / GNOME

## Method and limits

This is a capability and ownership assessment, not a claim that the two desktop suites have identical features. The comparison uses current official KDE/Plasma and GNOME help pages, the local pane registry and implementation files, and read-only installed/running service observations on 2026-10-15. A service being installed does not prove its graphical flow works. A missing Obsidience pane does not prove the system capability is absent.

KDE’s desktop overview identifies its launcher, tray, notifications, KRunner, Discover and settings. GNOME documents overview/search, system menu, notifications, calendar and settings. General files, printing, software stores and account settings also involve desktop applications and services, not only the compositor or shell process. KDE-style clipboard history and generic tray extensions are not assumed to be stock GNOME equivalents.

## Gap matrix

| Capability | KDE / GNOME baseline | Local evidence | Gap classification | Obsidience destination / dependency |
|---|---|---|---|---|
| Window management and workspaces | Both provide native focus, window navigation and workspace UI | Existing Hyprland, native pane registry, Surface layout and tiling adapter | Core exists; integrated overview and coherent presentation incomplete | Existing compositor Scene → transient overview; no second manager |
| Launcher and search | Plasma launcher/KRunner; GNOME overview/search | ApplicationLauncher, Applications and bottom pane/app shelf exist | Extend to grouped provider search and shortcut help | Existing launcher, bounded explicit providers |
| Desktop overview | Both expose current applications/context | Stage, graph and native panes exist | Coherent workspace composition design needed | Stage/PaneWorkspace projection, no new runtime |
| Quick settings | Plasma tray/system controls; GNOME system menu | Network/audio/device services installed; no unified native drawer found | Missing presentation | Compact shell drawer with typed service adapters |
| System tray | Plasma uses status-notifier tray; GNOME differs and may require extensions | No native StatusNotifierItem surface found | Missing KDE-style optional integration | Quickshell SNI presentation, not a nested desktop shell |
| Notifications | Both provide actionable notifications/history and focus controls | mako owns `org.freedesktop.Notifications` and service is active | Basic delivery exists; native history/settings surface missing | Extend sole mako owner via supported projection or explicit planned handoff |
| General file management | Dolphin / GNOME Files | Dolphin installed; Source is a provenance explorer | External appearance/launch integration, not absent filesystem capability | Theme/launch Dolphin; keep Source and Reader roles unchanged |
| File chooser | Desktop portals and toolkit dialogs | GTK, Hyprland and main portals active | Verify appearance, sandbox behavior and complete open/save UX | Existing FileChooser backend; no custom sandbox bypass |
| Package installation | Discover / GNOME Software and package services | Applications already uses PackageKit install/search/remove | Existing; design and auth acceptance required | Existing Applications owner |
| Update management | Software applications expose transactions/restart guidance | No complete update/history/restart surface found in inspected Applications UI | Proposed extension | Existing PackageKit adapter; full Arch transaction, no partial upgrades |
| Sound | Both provide output/input and app/stream controls | PipeWire + WirePlumber active; AI & Voice selects speech devices | Missing system mixer/MPRIS presentation | Settings Sound; preserve Realtime speech owner |
| Network / VPN | Both provide network profile/radio controls | NetworkManager installed | Missing native control surface; connection workflow unverified | NetworkManager typed adapter + trusted secret agent |
| Bluetooth | Both provide discovery/pairing/device control | BlueZ installed | Missing native presentation; pairing workflow unverified | BlueZ / supported agent lifecycle |
| Displays | Both provide arrangements, modes and scale controls | Existing multi-output compositor adapter and protected HDR/VRR configuration | Missing safe control presentation | Same adapter, timed keep/revert, no theme-driven output mutations |
| Input / shortcuts | Both provide configuration and discoverable shortcuts | Input settings projection and native bindings exist | Inspection exists; full editor/collision UX incomplete | Extend existing Input section and adapter |
| Appearance / themes | Plasma themes; GNOME appearance/preferences | One palette file and ShellTheme exist; many hard-coded pane colors | Missing coherent token coverage and native selector | Obsidience Themes under `shell/theme`; one Settings Appearance section |
| Accessibility | Both offer accessibility settings and assistive integrations | No native accessibility settings surface found | Missing presentation; native semantics/AT-SPI acceptance required | Native Qt semantics plus maintained assistive tools |
| Locking | Both provide secure native session lock | Existing Quickshell WlSessionLock + PAM, running owner reports unlocked | Secure owner exists; restyle carefully | Existing lock files only; opaque secure coverage, no WebEngine credentials |
| Login | Both use a separate display manager/greeter | Existing greetd session entry | Separate greeter design, not a replacement requirement | Supported greeter, preserved session start contract |
| Privileged authentication | Both integrate polkit authentication agents | Expected hyprpolkitagent package absent; no matching live agent process observed | Graphical auth acceptance gap, not proof polkit daemon is absent | Verify registered agent; use supported native agent before adding privileged UX |
| Secrets / accounts | Credential services and account settings | KWallet installed and activatable; Secret Service availability not verified | Integration/acceptance gap, not absence of secret storage | Native credential provider status and explicit account flows |
| Power / idle | Power menus and supported platform profiles | Existing secure idle/session helpers; power-profiles-daemon and UPower installed | Unified settings/action presentation missing | Existing logind/idle/profile owners; preserve installation policy |
| Screenshots / screen sharing | Desktop capture and portal consent | Existing portal backends active; grim installed | Integrated picker/indicator/revocation presentation missing or unverified | Existing capture/ScreenCast owners, bounded sessions |
| Clipboard history | Plasma Klipper; GNOME often extension/application | wl-clipboard/basic copy-paste exist; cliphist absent | Optional history missing, not basic clipboard | One opt-in provider, bounded retention, privacy/lock rules |
| Calendar and clock | Desktop clock/calendar UI; event providers separate | No coherent native calendar surface in registry | Missing presentation / optional event provider | Offline calendar, explicit sources, no fabricated agenda |
| Removable media | Device notifications/mount/eject flows | UDisks2 installed; Hardware monitors storage | Control presentation missing | Exact device identity, supported UDisks2 operations |
| Printers | Maintained printer settings and CUPS ecosystem | `cups` package not found at inspection | Backend unavailable plus missing presentation | Show unavailable; offer deliberate maintained integration, not automatic install |
| Defaults / locale | Desktop defaults, formats, time and associations | No equivalent complete native section found | Missing presentation | XDG MIME defaults and supported locale/time services |
| Startup applications | Desktop/user-session startup controls | systemd-managed shell/service lifecycle and native external apps exist | Management presentation missing | Inspect existing unit/XDG owners; protect required session services |
| Knowledge graph / Agents / Tasks | No direct stock equivalent | Rich native architecture already exists | Obsidience-specific strength, not a KDE parity gap | Improve presentation without duplicating ownership |

## Priorities

**P0: coherent and trustworthy operation.** Semantic token coverage; real native keyboard/focus/accessibility support; model-independent launcher and session controls; validated auth/lock boundaries; explicit unavailable/stale/uncertain states. Review graphical polkit before relying on package/network/account mutations.

**P1: ordinary daily desktop controls.** Quick settings, sound, network/Bluetooth, notifications, safe display configuration, default apps and file/dialog integration. Build on installed services and maintain one owner per capability.

**P2: completeness and polish.** Full update transactions, search providers, optional clipboard history, clock/calendar sources, removable media and printer/account/startup management, with platform availability visible.

This is not a recommendation to install KDE or GNOME alongside Obsidience. Reuse small maintained service/toolkit interfaces and leave the compositor, native session, Article system and existing providers intact.

## Primary sources

- [KDE Plasma desktop](https://kde.org/plasma-desktop/): launcher, tray, notifications, KRunner, Discover and settings baseline.
- [GNOME visual overview](https://help.gnome.org/gnome-help/shell-introduction.html): search/overview, system menu, calendar and session navigation.
- [GNOME notifications](https://help.gnome.org/gnome-help/shell-notifications.html): history, actions and focus controls.
- [GNOME display help](https://help.gnome.org/gnome-help/prefs-display.html): display/appearance and output-setting capability categories.
- [GNOME help index](https://help.gnome.org/gnome-help/): accessibility, hardware, files, networking and account/settings topics.
- [Quickshell service types](https://quickshell.org/docs/v0.2.0/types/Quickshell.Services.SystemTray/): reference for service integration families. Documentation version is not the installed runtime; verify the installed 0.3.2 API before implementation.
- [XDG ScreenCast portal](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.ScreenCast.html): consent/session and stream ownership.

Accessed 2026-10-15. Local capability observations are recorded separately in the inspection coverage document, not inferred from these public descriptions.
