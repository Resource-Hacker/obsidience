# Obsidience Themes

Theme packages live beside, not instead of, the existing palette authority.

**First package: [Obsidian Gold](obsidian-gold/README.md)**. Open [the offline design atlas](obsidian-gold/preview/index.html), or start with [the implementation map](obsidian-gold/docs/02-PANE-MAP.md).

`palette.json` remains the sole active native palette. `catalog.json` lists inactive, reviewable packages. A package's own `palette.json` is a preset, not a competing live authority. Do not point individual panes at different package files.

Obsidian Gold 0.1.0 provides an exact-schema compatible palette, semantic tokens, original assets, toolkit color exports, 53 inspectable designs, and a staged implementation plan. **It has not been activated in the running shell.** The catalog and Appearance screen are currently design-package assets, not a deployed theme selector.

No third-party theme code, shell commands, services, model changes or compositor configuration may be executed merely because a theme package is selected. Future package ingestion must validate allowlisted data and asset types. JavaScript in the offline atlas is preview tooling, never executable theme payload for the native shell.
