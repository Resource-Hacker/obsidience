---
type: knowledge
title: Media
sources:
- resource: docs/modules/media.md
- resource: obsidience/media/README.md
- resource: obsidience/harness/media/service.py
- resource: obsidience/harness/capabilities/media/library.py
- resource: obsidience/harness/capabilities/media/acquire.py
- resource: obsidience/tv/host/tuner.py
---

Media is the independent catalogue, discovery, exact-source acquisition,
content playback/delivery and progress product. Jellyfin owns catalogue records,
native delivery and per-user watch/resume state. Harness adapters provide bounded
reads, current-activation source bindings, explicit acquisition and ordinary
receipts without another media database. The native pane consumes those owners.

[Home](/Architecture/Home/Home.md) owns lights and physical TV identity, power,
volume and remote input. Media consumes the TV as an optional device through the
existing workstation delivery route in `obsidience/tv/host/`; native Jellyfin
clients and local catalogue operations need no TV. Existing `tv.control` composes
content and device operations without creating another playback authority.

[media.library](/Tools/media.library.md) separates catalogue reads, metadata
search, source candidates, selection, season plans and saved resume.
[media.acquire](/Tools/media.acquire.md) registers or reconciles one exact
activation-bound source under the accepted provider policy. Browsing is read-only;
provider registration, mounted visibility, catalogue readiness and verified
playback are separate outcomes. Ambiguity requires selection and uncertain
effects must not be replayed.

The tuner alone owns its player and optional finite same-season sequence. Each
source is revalidated and receives a playback generation. Progress remains in
Jellyfin; reporting failure degrades resume without stopping otherwise healthy
local-file playback. Media bytes pass through providers, mounts and players,
never a model or Harness streaming proxy. Source availability cannot silently
choose a different edition, provider or player.

See [Media integration](/Architecture/Harness/media-integration.md) for provider,
mount, source-admission and progress details, and
[Media library and playback](/Runbooks/Operations/media-library-and-playback.md)
for the existing procedure. Optional integrations default disabled; exact
Tool/Skill grants and private configuration remain installation decisions.
