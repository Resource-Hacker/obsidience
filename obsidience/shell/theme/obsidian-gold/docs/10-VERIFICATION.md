# Verification record / Obsidian Gold 0.1.0

Verification date: 2026-10-15. This records checks of the delivered design package, not acceptance of the unimplemented native desktop features.

| Check | Observed result |
|---|---|
| Native pane coverage | All 16 registered native pane IDs represented |
| Design routes | 53 distinct routes with owner, path, workflow and acceptance boundary |
| Primary artwork | 53 PNG exports, each 1920 × 1080 |
| Responsive artwork | 2 compact exports at 960 × 720; 2 strip exports at 1920 × 550 |
| Additional state artwork | Empty Tasks, unavailable Hardware, approval-required Reviews |
| Total local PNGs | 60 |
| Contact sheets | One all-designs sheet plus five grouped sheets |
| JavaScript syntax | Both atlas source files accepted by `node --check` |
| Python syntax | Both artwork/token exporters parsed successfully |
| Atlas route rendering | All 53 routes reached the explicit ready marker and exported through a temporary headless browser |
| Visual review | All five grouped contact sheets reviewed, plus full Desktop, Chat, Appearance, compact Appearance and unavailable Hardware |
| Native palette schema | Accepted by the installation's existing native/browser palette validator |
| Native consumption proof | Unchanged copied HardwarePane rendered correctly with the staged gold palette in an isolated offscreen process |
| Color contrast | Ten evaluated text/control token pairs passed their stated targets; see `09-CONTRAST.md` |
| Active palette | Unchanged, SHA-256 below |
| Production QML/session/compositor changes | None |
| Theme activation / package installs / model/device changes | None |
| Runtime shell restart | None |
| Keep-awake policy | hypridle remains masked and inactive; saved idle deadlines were not activated |

Active palette SHA-256:

```
4d1413a3f6bbd7fd57a5e636b0267994b8defcc79ae7e52fb946559062569d53
```

## Verification scope

The private native Hardware proof demonstrates that an existing theme-injected pane consumes the palette correctly. It does not establish that the remaining hard-coded pane interiors or external toolkits are already themed. Most new visuals are editable HTML/CSS/SVG designs that require the mapped native integration.

The atlas is deliberately offline and system-inert. Its source contains no fetch, WebSocket, credential input, system bridge or persistent storage. Buttons are visual demonstrations. Generic state selectors present reusable empty/unavailable/approval treatments; they do not simulate a live backend. Responsive exports demonstrate layout and scrolling, not full native screen-reader or multi-output acceptance.

The native inspection had limitations documented in `08-INSPECTION-COVERAGE.md`. Existing production Graph and Terminal surfaces were observed, fifteen offscreen native views were captured, and Camera/TFT were inspected in source rather than activated during the user's call. Private live screenshots and terminal/camera content are not distributed with the theme.

## Reproducibility and repository size

Generated PNG/JPEG artwork remains in the local folder and is ignored by Git. The atlas source, 53-route index, palette, declarative assets, color exports and documentation are versionable. `export_designs.py` reproduces the PNGs using a temporary browser profile without touching the active desktop browser. A temporary-profile cleanup race found during export was corrected to terminate only the exporter's own browser process group and tolerate late temporary-file cleanup.

No automated tests or fixtures were added. The recorded checks are direct validation and artwork inspection. Native release acceptance, secure authentication flows and backend service mutations still follow `06-ACCEPTANCE-AND-ROLLBACK.md`.
