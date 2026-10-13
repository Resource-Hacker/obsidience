# Obsidience Media

Obsidience Media is a media server integration. Jellyfin owns the catalogue,
metadata, item identity and per-user progress. The native Media pane and other
clients are presentation and playback destinations for that one server. A TV
is optional: catalogue reads have no TV dependency. The existing TV tuner is
the first implemented destination adapter, not the product's root owner.

The first slice adds bounded movie/episode queries, exact source selection,
local-file admission, and a TV open/stop protocol. It does not yet supply the
native Media pane, tuner progress reporting, seek/track controls, acquisition,
virtual mounts, remote client access or a migration away from Android.
Existing live TV remains with its current tuner; the catalogue does not yet
import its guide. Those are separate delivery gates, not enabled placeholders.

## Server and private configuration

`obsidience-media-jellyfin.container` is a rootless Podman Quadlet for the pinned
official image in `artifacts.lock.json`. Install it in the owner's
`~/.config/containers/systemd/` after the installation storage preflight and
catalogue inventory. It publishes only workstation loopback port 8096, mounts
`~/Media/Obsidience/Movies` and `~/Media/Obsidience/TV` read-only, and keeps
private application data/cache outside the source tree. It has no TV, Harness,
GPU, compositor or desktop service dependency. It does not expose LAN access;
additional clients need separately configured authenticated reachability.

Use supported Jellyfin startup/user/library APIs for installation. Keep NFO
saving, media-directory writes, realtime monitoring, chapter/trickplay extraction
and periodic scans disabled for initially admitted roots. Use one deliberate
initial scan of the dedicated local roots. `Items/{id}/Refresh` in the pinned
server does not recursively discover new files; a safe targeted rescan for a
future virtual root is not established. Do not enable Tiramisu or another
rescan owner on that assumption.

The Harness and tuner read ignored `obsidience/state/media.json` (or the private
`OBSIDIENCE_MEDIA_CONFIG` path). Missing configuration defaults to disabled.
Its shape is:

```json
{
  "enabled": false,
  "catalogue": {
    "url": "http://127.0.0.1:8096",
    "instance_id": "SERVER_ID_FROM_THIS_INSTALLATION",
    "user_id": "USER_UUID_FROM_THIS_INSTALLATION",
    "credential": "obsidience-media-jellyfin"
  },
  "roots": [
    {"id": "movies", "catalogue_path": "/media/movies", "path": "/absolute/approved/Movies"}
  ]
}
```

Authenticate the intended Jellyfin user/device and encrypt the returned session
token with `systemd-creds --user` under `~/.config/credentials/`. The Harness
unit loads that exact credential name with `LoadCredentialEncrypted`; no token
belongs in JSON, source, unit text, arguments or logs. The adapter uses the
server's authenticated `MediaBrowser` authorization header with a stable device
identity. Credential loading alone grants no Obsidience capability.

`media.library` has one Tool/Skill pair. Stage it and any Executive Skill grant
through the existing Article/Review authority; never copy defaults over the live
Vault or fabricate accepted metadata. Keep `enabled:false` until the intended
bindings, client lifecycle and first destination verification are ready.
Configuration changes require the normal guarded Harness deploy; the running
client rejects a changed configuration until it acquires a new snapshot.

## Exact local playback

`media.library browse` returns bounded records and explicit source choices.
`select` binds one item/source for the current activation. For the TV destination,
`tv.control find` with `app:library` also creates current-turn choices, and
`open` accepts that exact opaque id. It re-resolves the source before dispatch.
The catalogue adapter never starts a player or streams media bytes.

Admission is intentionally narrow in this slice: regular local MP4/M4V or
Matroska/WebM files, approved non-overlapping roots, no symlinks/traversal or
network/FUSE filesystems. The file revision includes its root mapping, held
ancestor identities and file metadata. MP4 reference containers are rejected.
The tuner opens by its retained file descriptor, forces the admitted demuxer,
disables external references/automatic companion files, and keeps that reader
until the matching mpv unload. This is an exact-source boundary, not a claim
that arbitrary codecs or hostile media parsers have been audited.

A play request carries catalogue instance, item, source, root, source revision,
file revision and an unpredictable request generation. `playing_verified`
requires that entry's first playback event and exact playlist readback. The TV
adapter separately verifies the PC route is shown. `loading` after a bounded
wait is pending, not a retry instruction. `stop` requires the observed source
and generation and verifies unload plus idle readback. EOF ends once. Local
pause/resume are unavailable until their identity-bound VOD implementation.

The tuner owns the playback lifetime. Harness/catalogue shutdown does not stop
an already playing local file. Disabling integration rejects new selections and
opens but leaves ordinary TV routes and stopping the current file available.
No resume persistence is claimed from this first slice.

## Deployment and rollback

Commit only the intended change, then use `obsidience/scripts/deploy --dry-run`
and the guarded deploy. Tuner/player changes require fresh idle tuner and
Android evidence before any owner restarts; active or unknown playback defers
the deployment. The compositor, remote keyboard and locker are not restarted.
Provider unit changes affect only the installed catalogue service.

Keep the previous image, configuration and application data. Disable integration
first to stop new operations. Revert code through the existing guarded deploy
at an idle playback boundary. This does not remove media or undo acquisitions.
Stopping the catalogue is independent of stopping the TV or Harness. Before a
server upgrade, use a Jellyfin-supported backup or stop the server and snapshot
its complete private data; never copy an active SQLite database alone or delete
WAL files. A code/image rollback does not reverse a database migration. Restore
the matching data backup with the server stopped if a downgrade requires it.
