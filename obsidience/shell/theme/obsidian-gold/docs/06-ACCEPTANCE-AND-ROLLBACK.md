# Native acceptance and rollback

This is a manual release checklist for the future native integration. It is not an automated test suite and is not evidence that unimplemented desktop controls already work.

## Preservation checks before applying

Record the current selected palette hash, native source revision, supported theme projections and current lock state. Preserve the previous palette in the existing private state/evidence area. Check active tasks, speech, terminal/Codex sessions and current display modes without dumping credentials or private content. Do not take or publish camera/chat screenshots unnecessarily.

## Visual and interaction checks

Review all sixteen pane identities and all Settings sections at their native minimum sizes. Check primary/secondary text, focus, selection, disabled/pending/error/empty/offline/stale states, scrollbars, menus, tooltips and dialogs. Move focus using only the keyboard; no mouse-only destructive operation. At 200% text scale, labels and actions remain accessible through reflow or internal scrolling. Test 1× and 2× scale on the actual outputs, not just browser emulation.

The graph must retain positions, selected IDs, hierarchy and picking through a theme change. No physics reheat, duplicate viewer or new GPU owner. Terminal sessions and running processes must continue unchanged; ANSI code/output remains readable. Reader editing and Reviews preserve exact revision guards. Camera preview remains video-only and never alters another camera consumer.

## Model-independent desktop checks

With the Executive unavailable, verify launcher, native window activation, recovery terminal, sound/network settings, notification center, device status and session actions. A loading model must not block the desktop. Unknown telemetry stays unavailable; an unsuccessful operation must not appear healthy simply because its button animation ended.

## Permission-sensitive checks

Verify a real graphical polkit flow with an authorized benign action and explicit user confirmation, without capturing credentials. Verify file-dialog sandbox grants and screen-share source selection/stop/revoke. Verify clipboard opt-in/retention/lock privacy. Verify notification lock-screen redaction. The atlas's disabled password illustrations provide no security assurance.

Check the actual native secure locker on all outputs, recovery/failure paths and correct PAM boundary before any lock styling is released. Never raw-restart the host while locked. Login greeter changes require separate session-entry review.

## Display/performance checks

Record unchanged output modes, HDR, VRR, luminance, GPU placement and pointer profile. Test a supported display-setting transaction with automatic revert and a recovery path. A theme must never trigger such a transaction itself. Compare idle CPU/GPU/memory and interaction latency; no new renderer, poller, background shader or animation loop. Preserve the installation's existing idle/suspend policy.

## Atomic activation and rollback

Validate a complete next palette before touching the active file. Apply one selected generation through the existing owner and supported projections. Persist the previous state and report each projection's actual outcome. If a required projection fails, roll back the selected generation or expose a partial result with a direct restore action; do not claim global success. Restoring a theme must not restore stale device/placement/model settings, because those were never theme state.

Use `obsidience/shell/session/restart-shell` only if an approved native code migration requires it and the existing lock guard permits it. Pure palette changes should use the existing watcher where supported. No restart was performed for this design-package delivery.

## Release evidence

Keep native screenshots, observations and validation transcripts under existing private `state`/`evidence` conventions. Avoid committing live conversations, terminal content, camera frames, account data or raw machine secrets. The theme repository should contain original design assets and documentation, not private operational captures.
