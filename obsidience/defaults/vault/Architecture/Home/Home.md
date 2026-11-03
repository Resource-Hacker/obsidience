---
type: knowledge
title: Home
sources:
- resource: docs/modules/home.md
- resource: obsidience/lights/README.md
- resource: obsidience/harness/capabilities/lights/set.py
- resource: obsidience/harness/tv/adb.py
- resource: obsidience/harness/capabilities/tv/control.py
---

Home owns lighting and physical home-device integration, including television
identity, commissioning, state, power, volume, remote input and device-side
lifecycle. [Media](/Architecture/Media/Media.md) owns catalogue, discovery,
acquisition and content playback; it consumes the TV as an optional device.
Native Jellyfin clients need no Home TV integration. Light power and physical
TV control need no media catalogue.

Existing packages implement this boundary without an aggregate `obsidience/home/`
runtime. `obsidience/lights/` owns the sole native Matter controller and encrypted
fabric state. Harness lighting capabilities consume its protected socket;
commissioning is explicit, writes bind current native node/endpoint identity,
and fresh readback is distinct from acknowledgement or physical illumination.
[lights.set](/Tools/lights.set.md) exposes power;
[lights.visualize](/Tools/lights.visualize.md) is separately opt-in and drains its
owned audio/light resources before restoration. No presence or playback event
automatically grants lighting authority.

`obsidience/harness/tv/` and `obsidience/tv/firetv-agent/` supply the existing
registered-TV transport and device agent. Private registration binds one exact
television; discovery cannot choose a new target. Power/volume, app state and
remote navigation use fresh device evidence. Wake acknowledgement does not prove
physical wake, and navigation does not prove playback.

[tv.control](/Tools/tv.control.md) currently composes Home device operations with
Media source selection and playback. The existing `obsidience/tv/host/` tuner,
player, compositor, streaming and audio route is Media delivery at its retained
compatibility path. This product boundary changes no Tool ID, service name,
private configuration or running ownership. There is no second controller,
Agent, scheduler or device store.

Exact Tool/Skill grants, cancellation, owned cleanup and no replay of uncertain
effects remain under the Harness capability owner. Public defaults neither
register devices nor assert their reachability or physical acceptance.
