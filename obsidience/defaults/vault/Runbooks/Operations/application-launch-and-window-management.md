---
type: runbook
title: Application launch and window management
obsidience:
  for_agent: '[[Agents/Executive/Executive]]'
  skills:
  - '[[Skills/application.launch]]'
  - '[[Skills/computer.observe]]'
  - '[[Skills/window.activate]]'
  - '[[Skills/window.place]]'
  - '[[Skills/computer.act]]'
---

## Purpose and prerequisites

Use this procedure for the current owner-authorized workstation outcome.
Executive conversation remains Agent-owned and uses its direct Skills. Reading
this reference does not activate a Task, add Tools or imply another action.

## Ordered actions and verification

1. Resolve the requested operation and one current target. A visual question
   alone does not request launch, focus, placement or input.
2. For launch, follow [Using application.launch](/Skills/application.launch.md)
   and call `application.launch` once with the registered application. Its
   bounded readiness result establishes ready, failed or unverified; never
   repeat an uncertain dispatch.
3. For current contents, follow [Using computer.observe](/Skills/computer.observe.md)
   and call `computer.observe` on the exact target. Historical images are not
   current evidence.
4. For requested focus or placement, use [window.activate](/Skills/window.activate.md)
   or [window.place](/Skills/window.place.md) once and inspect its verified scene.
   These effects own their fresh target checks and need no extra screenshot.
5. For requested in-window input, follow [Using computer.act](/Skills/computer.act.md)
   only after a fresh `computer.observe`. Stop after failure or uncertain delivery;
   never replay a click. Application-state completion requires fresh evidence
   of that state rather than only acknowledged input.
6. Finish with the verified result or concrete blocker. STOP and foreground
   cancellation end work. Browser readiness does not prove that a requested
   page loaded or media began playing.

## Reference

The [Shell scene](/Architecture/Shell/hyprland-shell-scene.md) supplies exact
semantic application and pane identities. The registered application catalog
owns launch routes. Preserve the existing managed launcher and single desktop
input owner; do not substitute terminal background processes or raw input paths.
