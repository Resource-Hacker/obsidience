# Obsidian Gold / 0.1.0

**Matte cassette futurism for the Obsidience Linux shell.** Black and charcoal instrument surfaces, restrained warm brass, legible neutral text, narrow architectural seams and quiet orbital geometry. No LCARS imitation, glass dashboard, room render or fictional ship operating system.

## Start here

Open **[preview/index.html](preview/index.html)** in a browser. It is a working offline design atlas, not a live desktop controller. The surface selector contains **53 designs**. Navigation, filters, density, state selection, visual toggles and implementation notes are interactive. All displayed records are illustrative; action buttons cannot change the system. The atlas makes no network requests and accepts no credentials.

[Contact sheets](designs/README.md) · [Pane map](docs/02-PANE-MAP.md) · [Desktop gap analysis](docs/03-KDE-GNOME-GAPS.md) · [Implementation sequence](docs/04-IMPLEMENTATION-ROADMAP.md)

## What is real, and what is staged

The local package, HTML/CSS/SVG designs, semantic tokens, compatible native palette and exported images are real artifacts. The corresponding application behaviors remain owned by the existing runtime. The theme has **not** been applied to the live palette, and missing desktop services have **not** been implemented by these mockups. Existing pane designs are distinguished from proposed extensions and external-toolkit integrations throughout the atlas.

The package retains the native palette schema and `name: Obsidience` required by the present validator. The friendly name and package ID live in `theme.json`. Do not rename the internal native identity to bypass the existing validation contract.

## Package contents

- `palette.json`: inactive preset for the exact current ShellTheme contract.
- `tokens.json`, `exports/tokens.css`: semantic visual definitions for the complete design.
- `assets/`: original static wallpaper and texture. No bundled fonts.
- `preview/`: offline atlas source; no npm build, CDN or backend.
- `designs/`: local PNG render for each design, screen-index.json, contact sheets. Generated PNG/JPEG outputs stay local and are ignored by Git; the source and exporter reproduce them.
- `docs/`: ownership map, gap assessment, implementation order, acceptance and provenance.
- `exports/`: optional color-only terminal/toolkit exports. These are not installed automatically.
- `references/`: ignored local reference area. Owner reference imagery is not a public asset license.

## Render the designs again

From the repository root:

```sh
python3 obsidience/shell/theme/obsidian-gold/export_designs.py
```

The artwork exporter uses a temporary headless Chromium-compatible browser profile and Python `websockets`. It does not use the active browser profile, open a desktop window, restart Obsidience or access model devices. Choose `--only chat reader appearance` for a subset. This is an artwork export utility, not a test suite.

## Activation boundary

Do not simply replace the live palette and declare the shell themed. The current frame consumes ShellTheme, but many native interiors still contain hard-coded cyan; Qt controls, web content, terminal ANSI colors, browser policy and compositor borders have separate projection seams. Complete the migration in `docs/05-THEME-INTEGRATION.md`, then use a reviewed atomic activation and rollback procedure. No activation script is included because that would imply coverage the current native implementation does not have.

Native proof: the unchanged Hardware pane successfully consumed the staged gold palette in an isolated offscreen preview. That private proof is recorded in the inspection/verification documents; the active desktop palette remains unchanged.

## Local launcher entry

A normal desktop application entry named **Obsidience Themes** is registered locally at `~/.local/share/applications/obsidience-themes.desktop`. It opens the offline atlas through the existing default browser and launcher ecosystem. It is not a new shell service or native Settings section. Removing that one entry removes the launcher shortcut; the package remains intact.
