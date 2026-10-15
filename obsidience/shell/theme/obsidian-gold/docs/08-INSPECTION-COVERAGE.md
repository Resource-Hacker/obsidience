# Inspection coverage and limits

Audit date: 2026-10-15. Source snapshot revision: `d0321327e5c66b028ad8dd7c53386da0295c2bb2`. The shared checkout may advance independently after this observation.

## What was inspected

All 16 native pane definitions and their source owners were inspected. Settings has four current sections. Graph Knowledge/Memory/Code uses one viewer and aliases, not three independently registered panes. Shared theme/frame/launcher, command route validation, shell lifecycle, model/device boundaries and palette consumers were also inspected.

Live output screenshots were used to inspect the running Graph and Terminal placement. The user had active applications and a video call, so the desktop was not rearranged and the camera was not activated for this audit. Private screenshots are kept in the ignored audit directory, never copied into the theme package.

A temporary CPU/software offscreen rendering of copied, unchanged native QML produced fifteen visual samples: Chat, Library, Tasks, Reviews, Reader, Knowledge, Source, Models, Hardware, Applications, Media and four Settings subviews. The snapshot had isolated config/state and contained no live shell command server or locker. It was terminated after rendering. It was not an installed second shell.

**Probe limits:** some captured panes lacked live selection/connection context. The Hardware probe initially resolved a theme binding against the wrong QML palette property and rendered incorrectly; that is an inspection-harness artifact, not evidence of a production white theme. Empty Reader/Library/Source and disconnected Chat/Graph-settings captures are not treated as proof that their live services fail. Camera and TFT were source-audited rather than activated interactively. No claim is made that every live pane was clicked end to end.

## Runtime observations

The canonical shell, graph presenter and local Harness were active. The lock owner reported unlocked. Native outputs included the wide primary display and two differently scaled auxiliary Surfaces. Installed or running service evidence included mako (also observed as the actual notification D-Bus owner), PipeWire, WirePlumber, NetworkManager, BlueZ, UDisks2, UPower, power-profiles-daemon and portal backends. Dolphin and KWallet were installed. KWallet D-Bus entries were activatable; a ready Secret Service was not assumed. Expected hyprpolkitagent and cliphist packages were absent; no matching live polkit-agent process was observed. The cups package was absent. No packages or services were changed.

## QML color migration inventory

Counts are textual RGB-literal occurrences, not unique colors, severity scores or proof of bugs. Semantic review is required before replacing a color.

| File | Lines | Color literal occurrences |
|---|---:|---:|
| `obsidience/shell/qml/panes/applications/ApplicationsPane.qml` | 476 | 35 |
| `obsidience/shell/qml/panes/camera/CameraPane.qml` | 408 | 14 |
| `obsidience/shell/qml/panes/chat/ChatPane.qml` | 574 | 34 |
| `obsidience/shell/qml/panes/graph/GraphViewerPane.qml` | 58 | 2 |
| `obsidience/shell/qml/panes/hardware/HardwarePane.qml` | 479 | 2 |
| `obsidience/shell/qml/panes/hardware/MonitorMeter.qml` | 29 | 0 |
| `obsidience/shell/qml/panes/hardware/MonitorPlot.qml` | 43 | 0 |
| `obsidience/shell/qml/panes/hardware/MonitorTrend.qml` | 77 | 2 |
| `obsidience/shell/qml/panes/knowledge/KnowledgePane.qml` | 742 | 26 |
| `obsidience/shell/qml/panes/library/LibraryPane.qml` | 680 | 48 |
| `obsidience/shell/qml/panes/media/MediaPane.qml` | 390 | 9 |
| `obsidience/shell/qml/panes/models/StatusPane.qml` | 898 | 75 |
| `obsidience/shell/qml/panes/reader/ReaderPane.qml` | 1119 | 77 |
| `obsidience/shell/qml/panes/reviews/ReviewsPane.qml` | 656 | 43 |
| `obsidience/shell/qml/panes/settings/SettingsPane.qml` | 169 | 11 |
| `obsidience/shell/qml/panes/settings/ai_voice/AiVoiceSettings.qml` | 268 | 9 |
| `obsidience/shell/qml/panes/settings/graph/GraphSettings.qml` | 917 | 55 |
| `obsidience/shell/qml/panes/settings/graph/GraphStylePortrait.qml` | 299 | 27 |
| `obsidience/shell/qml/panes/settings/input/InputSettings.qml` | 197 | 14 |
| `obsidience/shell/qml/panes/settings/workspace/WorkspaceSettings.qml` | 871 | 45 |
| `obsidience/shell/qml/panes/source/SourcePane.qml` | 882 | 45 |
| `obsidience/shell/qml/panes/tasks/TasksPane.qml` | 1229 | 57 |
| `obsidience/shell/qml/panes/terminal/TerminalPane.qml` | 491 | 33 |
| `obsidience/shell/qml/panes/tft/TftCompanionPane.qml` | 37 | 2 |

## Delivery changes

The live palette was retained. No existing QML pane, command protocol, session unit, compositor configuration, display setting, camera state, model slot or active terminal was changed by the design-package work. See the verification report for actual exported-route and palette checks.

## Additional native palette proof

The Hardware pane was subsequently rendered again from unchanged copied native QML with its theme property correctly bound and `OBSIDIENCE_THEME_PATH` pointing to the inactive Obsidian Gold preset. The offscreen CPU render loaded successfully and produced the expected black/brass native pane. The capture is private at `obsidience/state/theme-audit/2026-10-15/native-hardware-gold.png`. This proves this existing theme-injected pane can consume the preset; it does not prove every pane has been migrated.

The keep-awake policy was also verified: `hypridle.service` is **masked and inactive**. Saved five-minute lock / ten-minute DPMS settings are present but not active. The owner’s keep-awake and suspend/hibernate prohibitions were preserved. The Power design explicitly distinguishes saved configuration from enabled behavior.
