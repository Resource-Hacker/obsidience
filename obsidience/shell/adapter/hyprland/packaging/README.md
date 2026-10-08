# Patch-bearing Hyprland package

Obsidience's overlapping tile layout depends on the three reviewed compositor
patches in `../patches`: front-to-back tiled hit testing, native Lua resize
callbacks, and keyboard refocus after clicking the desktop layer.

The stock `hyprland 0.56.2-3.1` update replaced the previously patched package
on 2026-09-17. A stock package with the same upstream version does not retain
these downstream changes. It can draw the focused tile in front while sending
a click in the overlap to a covered tile.

`PKGBUILD` preserves the existing Arch-derived recipe and patches but names the
result `hyprland-obsidience`. It provides `hyprland` and conflicts with the stock
package, so a normal repository upgrade cannot silently replace the patched
compositor. This is not a kernel, driver, or system-wide update pin. Do not add
`replaces=hyprland`, which would claim unrelated installations.

Build from this directory with the installed development dependencies:

```sh
BUILDDIR=/home/wissenschafter/.cache/obsidience-hyprland-build makepkg --syncdeps
```

The source archive and each patch have mandatory checksums. Package dependency
generation records the actual shared-library ABI; rebuild against current
libraries instead of reinstalling an old binary against incompatible libraries.
For a future upstream release, review and rebase all three patches (or verify
their upstream replacements), build, and validate native overlap clicks and
desktop-to-window keyboard focus before replacing this package. Do not bypass
an ABI dependency conflict with `--nodeps`.

Installation replaces the stock package through `pacman -U`; it does not replace
the already-running compositor. Save the current workspace and tmux session,
coordinate a graphical-session restart, then verify the running executable hash,
all three outputs, and actual pointer/keyboard behavior. A config reload is not
a binary deployment. Retain the preceding package for rollback.

This adds no pane activation handler, input daemon, focus watcher, or second
window owner. Hyprland remains the sole focus and stacking authority.
