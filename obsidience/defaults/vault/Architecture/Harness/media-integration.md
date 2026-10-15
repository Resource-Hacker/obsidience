---
type: knowledge
title: Media integration
---

Obsidience Media is one independent catalogue and delivery service. Jellyfin
owns movie and episode records, item/source identities, playback delivery and
per-user saved resume. Browsing and saved-position lookup do not require a
television. Desktop presentation and any configured native clients use the same
Jellyfin instance; clients consume the catalogue and do not own it. The Harness
owns accepted capability bindings, conversation and receipts, never a second
media database.

Cinemeta supplies bounded title/IMDb metadata discovery. The configured source
provider supplies release candidates; Prowlarr's public TorrentsCSV indexer is
the supported self-hostable route when configured. Release metadata and hashes
remain untrusted. Ranking can recommend a unique best match but cannot resolve
an edition or episode ambiguity. The local Tiramisu provider is reached only
through its owner-only Unix socket. When configured, TorBox supplies cached-only
acquisition while Tiramisu retains source search and existing media. Cached
candidates bind provider configuration, torrent hash, exact file path and byte
size. Movies require one exact video; season and series packs require every
video to match the same series with unique contiguous coverage inside each
included season range. Explicit
combined-file spans remain one native file and one progress record. The whole
registration plan is bound and shown before acquisition. An accepted owner
policy may permit a cached complete-series pack for a requested episode while
limiting playback to the requested season. Uncached transfer and P2P fallback
are not substituted.
The configured provider accepts one run-bound registration after an authorized
acquisition request; it does not autonomously sync a watchlist, replace releases,
schedule upgrades or play media. Provider or
registration success is separate from Jellyfin catalogue readiness and
verified playback.

The TV is an optional playback destination, not a media authority. A configured
native Jellyfin client consumes server delivery; it does not register media or
control acquisition. The existing workstation TV route remains a separate
adapter: its tuner is the sole controller of its mpv, while its compositor,
audio server, Sunshine and Moonlight retain display and transport ownership.
Media bytes never pass through the model or a Harness streaming proxy. The
local TV adapter accepts only exact, revalidated catalogue sources and does not
transcode them.

Private installation configuration maps approved roots; exact file identities,
source revisions and playback generations prevent path or title substitutions.
The tuner verifies its playlist entry and playback event, and TV control
verifies the shown route. Local VOD state, pause/resume, absolute seek, stop and
track selection require the current generation plus exact source identity and
fresh readback; uncertain effects are never repeated. Jellyfin saved resume is
read from that same catalogue and persisted by the playback progress adapter.
Physical picture and sound acceptance is separate. File EOF ends once; the
live-channel reconnect policy never restarts a film. An explicit season command
may bind up to 100 already-catalogued sources as one finite queue. The existing
tuner alone advances on verified natural EOF, revalidates each exact source,
and cancels on stop, source replacement or player dependency loss. Its first
receipt verifies only the first source; later generations remain separately
observed playback. No acquisition runs at EOF and no second scheduler is added.

Acquisition streaming must keep persistent media-byte caching disabled and use
an explicitly bounded in-memory working set. Registration alone does not add a
Jellyfin item. The shared FUSE mount and library discovery must each be ready
before an acquired item is considered catalogue-ready. A separate constrained virtual-source admission checks the actual mount identity,
provider release/file mapping and generation, then probes only the selected file
in an isolated bounded process. A blocked probe retains its ownership until it
exits; no replacement probe is spawned. Catalogue startup waits for that mount,
and mount-owner loss stops the affected catalogue instead of scanning an empty
directory. Existing tuner playback of ordinary local files remains independent.
Never report an acquired title as playable based only on a registration reply.

TorBox bytes arrive through its native read-only WebDAV interface and an
unmodified upstream rclone mount with a 128 MiB RAM buffer budget. The account's
native movie/TV tags separate approved roots; existing tags are preserved. One
metadata update is followed by bounded readback and can remain pending. A deferred
TV root attaches only to its preconfigured, uniquely named empty `tvshows`
collection once the first real episode creates the provider directory. Exact
collection/path readback precedes targeted refresh. Provider mount loss stops the
dependent Jellyfin service, and ordinary unmount waits for readers to drain.
Credentials and generated download URLs remain private to provider transports.

The optional integrations default disabled. Disabling them rejects new source
searches or registrations; existing playback and the ordinary TV route remain
independent of acquisition availability. Scheduled sync, watchlist ingestion,
automatic upgrades and unrequested next-episode playback are not enabled. No
second catalogue, scheduler, Agent, TV player or Article type is introduced.
Movie records and playback progress are not wiki Articles.

See [Golden ontology](/Architecture/Harness/action-ontology.md) and
[Media library and playback](/Runbooks/Operations/media-library-and-playback.md).
