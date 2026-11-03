# Obsidience Home

Obsidience Home is the product boundary for **lights and physical home-device
control**, including the television. It owns device identity, commissioning,
state observation, power, volume, remote input and device-side lifecycle.
[Media](media.md) owns the catalogue, discovery, acquisition and content playback;
it consumes the TV as an optional Home device. A media library is useful with no
TV connected, and a light or TV power command needs no media catalogue.

Home uses the existing Harness capability and receipt owner. It introduces no
second Agent, scheduler, device database or desktop-input path. Integrations
remain optional and require private device registration and accepted Tool/Skill
grants; the starter Executive does not receive lighting authority automatically.

## Responsibility and current source layout

Home is a product boundary across the existing packages. There is currently no
`obsidience/home/` runtime package or universal home-automation broker. Existing
Tool names, imports, unit names and private configuration paths keep their
compatibility contracts.

| Concern | Owner | Current implementation |
| --- | --- | --- |
| Light commissioning, fabric, sessions and fresh state | Home lighting controller | `obsidience/lights/` |
| Light power, optional visualization and measurement adapters | Home, invoked through Harness capabilities | `obsidience/harness/capabilities/lights/` |
| TV identity, transport, power, volume, app state and remote keys | Home TV adapter | `obsidience/harness/tv/`, device operations in `harness/capabilities/tv/control.py`, `obsidience/tv/firetv-agent/` |
| Catalogue, source discovery, acquisition and saved progress | Media | `obsidience/media/`, `obsidience/harness/media/`, `harness/capabilities/media/` |
| Workstation content playback and TV delivery | Media playback adapter, consuming Home's TV | `obsidience/tv/host/`, related units in `obsidience/tv/systemd/` |
| TV-facing content and device commands | Existing composed interface | `tv.control`, which currently spans both boundaries |

The `tv/` directory contains both device integration and content delivery. The
[TV route](tv.md) documents that shared implementation. Its location does not
make the catalogue or tuner a physical-device authority. The boundary is
explicit here without moving running services or renaming their contracts.

## Lighting

One native Matter controller owns commissioned fixtures, native fabric data,
sessions and subscriptions. Commissioning is an explicit installation operation
using the protected local socket and a hidden pairing-code prompt. Discovery
returns candidates; it does not commission, retarget or authorize them.
Encrypted fabric state and its encrypted key credential must be backed up and
restored together. There is no WiZ transport fallback.

`lights.set` reads every selected fixture before a group change and binds each
write to its current native node and endpoint. An unavailable or uncommissioned
fixture blocks that selection before writes. An already satisfied state sends
nothing. Fresh readback establishes the reported native power state; a partial
or uncertain result retains its per-fixture outcomes and must not be replayed.
Command acknowledgement alone does not establish physical illumination.

`lights.visualize` is an explicit opt-in consumer of the same controller and
control lock. It temporarily changes colour and brightness from one currently
observed playback stream; ordinary light power control preempts and drains it.
The session owns its audio tap, delayed output route and restoration of prior
light appearance. Stream replacement or dependency loss ends the session and
releases owned resources. It changes no microphone or system-default routing.
A running session or a supplied timing profile is not proof of measured optical
alignment. Optical measurement and camera use require their own explicit request.

The controller supports native level and colour operations, but the ordinary
`lights.set` Tool exposes power. A controller method is not automatically a new
conversational Tool. See the
[lighting README](https://github.com/Resource-Hacker/obsidience/blob/main/obsidience/lights/README.md)
for the socket, private storage and commissioning contract.

## Physical TV control

The existing adapter controls one explicitly registered, identity-bound Android /
Fire TV target through upstream ADB and an optional sideloaded TV agent. Private
configuration pins its transport and model identity plus approved app aliases.
Discovery and changed network addresses cannot silently choose a replacement TV.
ADB authorization and device credentials stay outside the repository.

The TV device contract covers:

- Observing power, foreground app, native media-session state and volume before
  deciding whether an effect is needed.
- Setting power, volume or mute with fresh readback. A reachable transport or
  accepted wake command is not proof that the display woke; network standby can
  make wake unavailable.
- Launching a registered app and sending bounded remote navigation or text only
  to the current device state. Navigation is not playback evidence.
- Managing the device-side TV agent and the remote's connection to the dedicated
  workstation TV session. Remote input stays scoped to that session.

The current `tv.control` interface composes these physical operations with Media's
content operations. `on`, `off`, `volume`, `mute`, device observations and remote
keys belong to Home. Catalogue `open`, `open_season`, VOD controls, live-channel
selection and screen mirroring invoke the Media delivery route. Neither portion
may repeat an uncertain effect, purchase, change accounts or install applications
from a content-selection request.

## Media consuming a Home device

A request to watch a catalogue item resolves an exact source in Media first.
The existing TV adapter then verifies the registered device and intended display
route while the tuner owns its player. Device readiness, source readiness,
player start and physical picture/sound are different observations; a receipt
reports only those actually established. Failure to reach the TV cannot turn a
catalogue selection into a different source or destination.

Native Jellyfin clients consume Media directly. They do not require the
workstation TV session, Home TV adapter, Sunshine or Moonlight. Conversely,
lighting and physical TV control remain independent of provider discovery or
acquisition availability. Home does not infer lighting automation from playback,
presence or a camera image.

## Installation and lifecycle

Home has no aggregate installer or mandatory daemon. Install only the relevant
device controller and adapter, retain their private configuration and encryption
keys, commission or authorize the actual device, and grant the paired Skills
through ordinary Review. Register cleanup with resource acquisition; stop and
drain owned work before replacing a controller or transport. A timeout does not
prove that a physical device did nothing.

Use the guarded deployer for the affected existing owner. Preserve active media,
remote-keyboard lifetimes and the secure desktop; do not restart shared ADB,
replace an input path or reset a device to complete a documentation or catalogue
change. Installation-specific reachability and physical acceptance remain local
checks, not guarantees of this published architecture.
