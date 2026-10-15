# Sources and provenance

## Local primary evidence

The design was based on the running Obsidience installation, its single native pane registry, QML component implementations, current palette/reader, shell README, DESIGN contract, application/toolkit ownership and read-only runtime/service checks on 2026-10-15. Private audit material is at `obsidience/state/theme-audit/2026-10-15`. It is not included in the public theme package.

The approved black-and-gold visual concept and textured wallpaper were supplied by the owner in the design conversation. They establish a visual preference, not a license to redistribute third-party wallpaper or logos. The theme's static SVG wallpaper, UI geometry, palette, CSS, JavaScript, documentation and illustrative vector diagrams were newly authored. They contain no downloaded font files or copied upstream implementation.

## Public primary references

- KDE: <https://kde.org/plasma-desktop/>
- GNOME visual overview: <https://help.gnome.org/gnome-help/shell-introduction.html>
- GNOME notifications: <https://help.gnome.org/gnome-help/shell-notifications.html>
- GNOME displays: <https://help.gnome.org/gnome-help/prefs-display.html>
- GNOME help index: <https://help.gnome.org/gnome-help/>
- Quickshell service-family reference: <https://quickshell.org/docs/v0.2.0/types/Quickshell.Services.SystemTray/>. Version mismatch is explicit; verify the installed runtime before coding.
- XDG ScreenCast portal: <https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.ScreenCast.html>
- WCAG 2.2: <https://www.w3.org/TR/WCAG22/>
- WCAG contrast: <https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html>
- Omarchy theme operation reference: <https://github.com/omacom/omarchy/blob/8a787b6a8bec830b04543bf14c760ee0a10591f6/bin/omarchy-theme-set>

Accessed 2026-10-15. These references inform capability boundaries and reuse decisions; none of their code was imported. No new dependency is adopted into the production runtime by this package, so the existing upstream artifact ledger does not require an imported-code entry for these references.

## Sample-data policy

Preview content is explicitly illustrative. It does not claim that depicted tasks ran, packages changed, devices were connected, media played or permissions were granted. Sample Article text, filenames and process rows are not extracted private records. The four Agent display names and the six Article kinds reflect the inspected architecture, but activity/status samples do not represent live agent state.

The atlas makes no network or system requests, uses no account integration, stores no credentials and sends no clipboard or conversation data. Its source may be opened offline. Password-shaped illustrations are disabled text fields, never usable authentication inputs.
