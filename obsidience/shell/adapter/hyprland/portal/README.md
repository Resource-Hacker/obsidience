# Hyprland portal capture fixes

The ordinary desktop portal remains the screen-share provider. This package
recipe backports three merged upstream changes onto v1.4.1:

- [#424](https://github.com/hyprwm/xdg-desktop-portal-hyprland/pull/424): retain
  capture scheduling when a consumer temporarily exhausts its buffers.
- [#425](https://github.com/hyprwm/xdg-desktop-portal-hyprland/pull/425): preserve
  the new frame callback installed during format renegotiation.
- [#427](https://github.com/hyprwm/xdg-desktop-portal-hyprland/pull/427): advertise
  the actual DMA-BUF plane count and use DMA-specific buffer parameters.

The patch files are exact upstream commits. Their hashes, the source archive
hash, and the protocol revision are pinned in `PKGBUILD`; licensing and upstream
provenance are recorded in the shell's `REUSE_MANIFEST.json`.

Build using the normal Arch package tooling from this directory (`makepkg -s`).
Install the resulting package through pacman and restart only
`xdg-desktop-portal-hyprland.service` when existing screen shares can reconnect.
A portal restart ends existing portal capture sessions. Retain the preceding
package for rollback. Do not replace the compositor or restart the Harness to
load these changes.

Validate actual frame delivery, including through lock/unlock, at the existing
resolution and transport. A running PipeWire node or a share thumbnail is not
sufficient evidence. The first two patches alone left GPU-buffer capture stalled
on the validation workstation; all three were required for the accepted package.
Reevaluate these backports when the distribution ships a release containing them.
