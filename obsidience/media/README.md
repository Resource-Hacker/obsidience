# Obsidience Media

Jellyfin owns the catalogue, native client delivery and per-user resume. Obsidience
adds discovery, explicit acquisition, a native Media pane and ordinary capability
receipts. The television is one optional destination; media bytes never pass
through the model or the Harness. Local libraries and native Jellyfin Live TV are
independent of the TV compositor, Sunshine and Moonlight route.

## Owners and configuration

The optional integration defaults disabled. Private `obsidience/state/media.json`
selects one authenticated Jellyfin instance/user, encrypted credential name,
non-overlapping catalogue/player root mappings and optional acquisition/discovery.
No credential value belongs in this file, the repository, command arguments or logs.
The Harness owns its API clients in the existing lifespan; the tuner owns playback
and progress reporting independently of Harness uptime.

The installed provider versions, source revisions, licenses, digests and local
patches are recorded in `artifacts.lock.json`. The Jellyfin Quadlet publishes
loopback 8096, mounts media read-only and uses private application data/cache.
Native clients need authenticated reachability; LAN/public access is not implied
by installation. No GPU is assigned to catalogue/scanning. Jellyfin may remux
native streams, while video/audio transcoding remains installation policy.

For private LAN clients, retain the loopback default and add an installation-only
Quadlet drop-in publishing the exact LAN address. Scope the firewall to that
interface, address and local subnet; keep remote access and UPnP disabled. Configure
Jellyfin's local subnets explicitly, including the exact rootless-network host
address if Podman's host mapping requires it. An address assigned by DHCP may
change; update the private binding then, rather than opening every interface.
Use Jellyfin's native password login or Quick Connect for each client. Credentials
stay encrypted or in the client's authenticated session, never in a playback URL.

Tiramisu is an optional virtual-file provider with owner-only control/engine Unix
sockets. Its integration exposes health, bounded search/list and one source add;
configuration, delete, scheduler, telemetry and dashboard endpoints are not exposed.
It remains the source-search bridge and owner of existing torrent-backed media
when TorBox supplies new acquisitions.
Prowlarr supplies configured indexers and requires authentication, including on
loopback. The adapter currently supports its public TorrentsCSV indexer. Cinemeta
supplies movie/series identity and exact episode metadata; exact IMDb queries work
when its name search omits a short film. Ranking applies only to returned eligible
sources. No provider can promise every title or universal best quality.
Release identity excludes the provider's mutable seeder and size display lines;
those statistics affect ranking only. A cached source additionally binds its
provider configuration, exact torrent hash, file path and byte size; changing
that binding invalidates the selection.

The private Tiramisu service uses bounded RAM caches with persistent media-byte
caching disabled. There is no complete-offline guarantee. Watchlists, periodic
sync, automatic upgrades, autonomous playback and another LLM remain disabled.
Peer networking does not grant control-API access or change router/VPN/firewall policy.

## Connecting a debrid account

Tiramisu is a direct BitTorrent provider, not a debrid client. A TorBox account
connection is established with `obsidience/media/connect-torbox`. This installation
helper uses TorBox's official device login: follow its verification URL and enter
the displayed code in your own browser. It never asks for a password or API key in
the terminal, buys a subscription, registers media or changes the active provider.
It waits only for the provider's bounded authorization window; Ctrl+C cancels it.

The returned token is encrypted with user-scoped `systemd-creds` as
`~/.config/credentials/obsidience-media-torbox.cred`; an existing credential is never
overwritten. `obsidience/media/connect-torbox --status` reads only connection/plan
status into a sanitized report. Account authorization alone does not establish
paid access, cache coverage, mounted file readiness or playback acceptance.

The installed TorBox adapter uses the existing `media.library` and `media.acquire`
capability owners. Private configuration enables `debrid` with provider `torbox`,
an encrypted credential name, instance identity and approved mount path. A paid
account is required for registration. Discovery returns only cached releases
whose actual single video file matches the exact movie/year or season/episode.
Registration rechecks cache and account state, then submits one cached-only
request. Uncached sources, multi-video releases and season packs are excluded.
Enabling TorBox preserves the selected provider binding; an unavailable or
changed provider fails explicitly without falling back to uncached transfer or
local BitTorrent.

The account's native `obsidience movies` and `obsidience tv` tags separate the two
approved libraries while preserving existing account tags. A metadata update is
sent once and reconciled by bounded readback; registration may be verified while
tagging, mounted visibility or catalogue discovery remains pending. TorBox's
native WebDAV supplies bytes through unmodified packaged rclone. Credentials and
generated download URLs never enter titles, QML, receipts or conversation context.

## Mount and catalogue lifecycle

Each virtual root adds `mount_path` to its ordinary `id`, `path` and
`catalogue_path` mapping. Tiramisu roots admit only the actual `fuse.tiramisu`
mount and `tiramisu` source. TorBox roots declare `provider: torbox` and admit
only the `fuse.rclone` mount with source `obsidience-torbox`, its exact live owner
and mount identity. Both require an exact provider release/file mapping and
source revision. A directory alone is not readiness. The service readiness check
finishes before dependent catalogue startup.

`obsidience-media-torbox.service` owns the native read-only WebDAV mount. Its RAM
buffer allocation is capped at 128 MiB; persistent media-byte caching is off and
there is no offline guarantee. The mount uses no model or GPU. One shared mount
serves the two approved tag roots. Native WebDAV refresh calls the exact `/refresh`
endpoint and accepts its 303 response to the root without following the redirect.

For a rootless Jellyfin container that reads an owner-only FUSE mount, map the host
owner to container UID/GID zero with `UserNS=keep-id:uid=0,gid=0` and `User=0:0` in
the installation's private Quadlet drop-in. The process remains rootless on the
host, capabilities are dropped, and `allow_other` stays disabled. Bind the mount
read-only and set `BindsTo`, `After` and `PartOf` for each configured provider
service. This installation deliberately suspends Jellyfin if that mount owner fails, including
local catalogue browsing, instead of risking an empty-library scan. Already-playing
ordinary local files remain under the tuner and continue independently.

Disable media-directory writes, NFO saving, realtime monitoring, periodic library
scans, chapter/trickplay extraction and other expensive analysis on virtual libraries.
Initial setup must establish Jellyfin's physical-folder records for the configured
roots. After verifying mount readiness, idle clients and a bounded inventory of all
configured roots, run one native `POST /Library/Refresh` and read back those bindings.
A collection with no physical folders cannot discover files through a targeted
refresh. This initialization is installation work, never an automatic fallback
or a per-acquisition whole-library refresh.

TorBox's TV tag directory appears only after the first explicitly acquired
episode. Precreate the empty `Cached TV` collection with type `tvshows` and set
its approved TorBox root's optional `library_name` to that exact collection name.
On that first real episode, the registration owner may attach only the configured
root through `POST /Library/VirtualFolders/Paths` with `refreshLibrary=false`.
The collection must be uniquely named and empty. Fresh native readback must verify
the same collection and sole approved location before targeted refresh; populated,
ambiguous or changed collections fail explicitly. No dummy media, synthetic tag,
new collection or whole-library refresh is created by acquisition. The movie
root is attached to its configured `Cached Movies` library during installation.

One registration owner queues `Items/{folder-id}/Refresh` for the exact configured
virtual library, using metadata Default and image None. In the pinned server this
queues folder ValidateChildren, including the initial stream probe. It does not
refresh unrelated libraries. Tiramisu admission caps virtual registration at 32
records per type; TorBox account reconciliation admits a complete bounded inventory
of fewer than 128 records. One exact-path readback distinguishes ready
from pending; registration success does not claim catalogue or playback success.

Tiramisu rejects new opens on shutdown and waits for existing readers/pumps before
ordinary unmount. The TorBox owner closes admission and waits for ordinary unmount
and its live readers to drain. No lazy unmount, forced reader eviction or replacement
worker is used. Guarded deployment refuses active/unknown Jellyfin sessions and
provider reads.
A failed dependency stops new work; it never creates a second catalogue.

## Capabilities and presentation

`media.library` is a bounded read capability: browse, select, saved resume, health,
metadata search and source candidates. `media.acquire` registers one exact opaque
activation-bound candidate. Each has one real execute entrypoint, code-owned schema
and exact Tool/Skill binding. Accepted Executive grants remain required; repository
schemas and default Articles alone confer no authority.

The Media pane pages library records, shows detail and current TV state, previews
source discovery and submits deterministic owner commands. Commands authenticate
through the existing native owner token, enter the Executive activation/receipt
owner and need no model classification. A request UUID binds the complete command;
reusing it observes the original result rather than dispatching again. An active
conversation refuses a new button command. Hidden/stale reads are cancelled.
Button receipts remain durable without creating per-title Hindsight memories.
After registration the pane reports catalogue ready or pending and refreshes its
Library once. It never repeats registration to check availability. A selected
source can open its exact native Jellyfin item page independently of the TV;
the command revalidates item/source/revision and reports navigation, leaving
playback and saved progress to that client. TV playback remains a separate choice.

The accepted playback preference may obtain a unique recommended source for an
exact requested title/episode missing locally. Ambiguous franchises, editions,
episodes and ties require selection. Browse/search alone never registers anything.
Acquisition is not purchase authority, automatic season monitoring or autoplay.

## Playback and resume

The existing tuner is the only controller of its mpv. Sources carry catalogue
instance, item, media source, root, source revision, file/provider revision and
playback generation. Local admission holds a no-follow descriptor chain inside
approved roots and rejects external-reference containers. Virtual admission uses
one bounded subprocess for actual FUSE reads, retaining blocked-worker ownership;
read-only source description does not open the media. Only admitted MP4/M4V or
Matroska/WebM payloads are accepted, with their demuxer constrained explicitly.

First-picture and exact playlist/source evidence establish player start; the TV
adapter separately verifies the intended PC route. Loading/unverified is not a
retry instruction. Pause, unpause, absolute seek, track selection and stop bind the
current source generation and use fresh readback. Seek tolerance is half a second;
saved-resume start tolerance is five seconds. File EOF ends once, without live
channel reconnection or next-episode autoplay.

`open` with `resume:true` rereads Jellyfin's stored position and uses it in the one
load command. It never adds a corrective second play/seek. The tuner reports bounded
authenticated start/progress/stop events and reads stored user progress back before
claiming persistence. Reporting failures leave playback running and explicitly
degrade resume. Reports do not queue for later replay; observed changes by another
client stop this reporter. Jellyfin provides no atomic compare-and-set, so a race
between progress read and write remains possible. Physical picture, sound, pane
interaction and remote acceptance require the owner; a successful build is not that
acceptance. The existing remote keyboard lifetime and Android route are preserved.

## Deployment, Review and rollback

Compile affected Python, inspect the native pane with its current QML validator and
use bounded real functional checks. Do not create tests or fixtures. Commit only
this feature and deploy with `obsidience/scripts/deploy`; it preserves active TV,
Android, catalogue clients and virtual readers. It never restarts the compositor,
locker or remote keyboard. Private credential/config changes use the same deploy
with the exact affected `--restart` owner.
When unrelated owners have pending changes, `--only <owner>` narrows that deploy
while preserving the selected owner's safeguards. Scoped receipts do not advance
the full-deployment checkpoint or enter its rollback history; a later full deploy
still handles the other owners. Restore a scoped owner's matching configuration
or source backup explicitly instead of treating a partial deployment as global.

Stage Tool/Skill, procedure and Executive-grant Articles through the existing
Article/Review API. Do not copy defaults into the live Vault or manufacture approval
metadata. Review must accept the new capability before its normal ingress can run it.

Disable new integration operations first for rollback. Restore the previous code,
provider generation and private configuration at an idle boundary with the guarded
deployer. Preserve acquired content and prior provider generations. Take provider
backups through supported APIs, SQLite's backup API, or a quiesced complete snapshot;
never copy an active database file alone or delete WAL sidecars. Code rollback cannot
reverse a provider database migration. Remove a virtual catalogue bind/dependency
only while the catalogue is stopped; drain owned readers before stopping its provider.
