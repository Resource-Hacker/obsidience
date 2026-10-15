# Optional color projections

These generated files are color-only assets. They are not installed, selected or activated by the atlas or exporter.

`tokens.css` supplies the offline atlas. `terminal-ansi.json` is the neutral sixteen-color terminal design. `kitty.conf` contains only Kitty color keys. `ObsidianGold.colorscheme` is a Konsole color-scheme projection. `ObsidianGold.colors` is an original KDE/Qt color-scheme projection using the installed toolkit's schema keys.

Native terminal and application integration must use the existing owners and installed toolkit support. Application-native controls can ignore external colors, especially in custom widgets or libadwaita applications; this is not a guarantee that every GTK/Qt application is themed. Browser policy already has a separate existing Obsidience adapter. Fonts, executable hooks, startup commands and plugins are intentionally absent.

Regenerate from the package's semantic colors with `python3 export_tokens.py`. Review ANSI contrast and syntax semantics in the real terminal before activation. The native compatible `palette.json` remains a separate explicitly reviewed mapping because it has its own exact runtime schema and alpha ordering.
