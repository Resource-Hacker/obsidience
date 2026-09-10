---
type: knowledge
tags:
- agent-observation
- obs-websites
title: Microsoft Edge browser profile
---

At the 2026-09-04 audit, Microsoft Edge had one local Chromium profile
directory named `Default` and no sibling `Profile *` directory. The registered
application name is `microsoft_edge`, which resolves to
`microsoft-edge.desktop` through the managed launcher.

The directory name does not establish an account identity, browsing purpose,
sync state, bookmarks, history, saved credentials, or private activity. Do not
inspect, store, or infer those details from the profile layout.

## Relationships

- `uses` [Application launch and window management](/ADMECH%20Workstation/Workstation%20Observations/agent-launch-and-gui-application-management--339f2788.md) — Microsoft Edge uses the one registered graphical application route.
- `related_to` [Reddit mechanics and automation surface](/Websites/Reddit/reddit-mechanics-and-automation-surface--5d4da873.md) — Reddit interaction may occur in the existing browser profile without exposing or inferring its private account state.
