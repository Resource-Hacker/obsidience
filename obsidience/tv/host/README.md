# TV host

The television shows a session hosted on the workstation: content plays here and
the Fire TV only displays it through Moonlight. Fire OS is the display client, not
the place where channels load.

## Services (user units, installed as copies in `~/.config/systemd/user`)

| Unit | Owns |
| --- | --- |
| `obsidience-tv-audio.service` | A private PipeWire server (`$XDG_RUNTIME_DIR/obsidience-tv`), configured only by `audio/` |
| `obsidience-tv-audio-policy.service` | WirePlumber for that server, policy only, state in the runtime directory |
| `obsidience-tv-audio-pulse.service` | Its PulseAudio endpoint (Sunshine captures through it) and the idle sink `obsidience_tv` |
| `obsidience-tv-session.service` | A headless sway compositor with one 3840x2160@60 output, rendered on the RTX 4080 |
| `obsidience-tv-player.service` | `mpv --idle` in that compositor; JSON IPC at `$XDG_RUNTIME_DIR/obsidience-tv-player.sock`, used by the tuner only |
| `obsidience-tv-tuner.service` | `tuner.py` (system Python with streamlink): the one owner of the player's IPC socket and of what plays; control socket `$XDG_RUNTIME_DIR/obsidience-tv/tuner.sock` |
| `obsidience-tv-sunshine.service` | Sunshine (NVENC HEVC on the RTX 4080), connected only to that compositor and that audio server |

The session publishes its Wayland socket name in `$XDG_RUNTIME_DIR/obsidience-tv/wayland`;
the player and Sunshine wait for it. Stopping the session stops both, and the tuner with
them. The tuner is not part of the Harness: a channel keeps playing while the Harness
restarts.

## Boundaries

- Sunshine never sees the desktop: it is a client of the TV compositor only, and its
  keyboard, mouse and controller input are disabled, so the TV remote cannot reach
  the workstation.
- Sunshine switches the default sink of the audio server it talks to whenever a
  stream starts. That server is the private one, so desktop audio is untouched.
- The private audio server must not load the desktop's `~/.config/pipewire` drop-ins:
  their 43 ms minimum fragment made Sunshine send sound in bursts, which Moonlight
  discards ("Too much pending audio data"). `audio/` sets one Opus frame (5 ms) per
  cycle. PipeWire falls back to `~/.config` when the directory named by
  `XDG_CONFIG_HOME` has no `pipewire/<name>.conf.d`, so both directories exist here.
- 4K (2026-10-12): the session renders and encodes on the RTX 4080; the model GPU is
  never used. Four pins keep it there: the compositor's render node
  (`WLR_RENDER_DRM_DEVICE`, sway needs `--unsupported-gpu`), the player's Vulkan device
  UUID, Sunshine's `CUDA_VISIBLE_DEVICES` UUID and Sunshine's `adapter_name`. Without
  `adapter_name` Sunshine allocates its capture buffers on another card and every
  capture fails ("Frame capture failed"; the compositor logs "DMA-BUF format is
  external-only", or with the Vulkan renderer "can't be used with modifier LINEAR").
  The iGPU cannot carry 4K: its encoder was at about 35% from the side-panel screen
  recorders plus 17% for a 1080p60 stream. Rollback to the iGPU at 1080p: commit 6cb3438.
- Player frame timing is chosen by measurement on the TV panel. On the RTX 4080
  audio-clock timing (`--video-sync=audio`) skipped no refreshes where display-synced
  timing skipped 0.1-0.4%; on the iGPU compositor it was the other way round.
- Sunshine creates kernel input devices (libvirtualhid keyboard, mice, touchscreen, pen)
  even with input disabled. `72-obsidience-tv-seat.rules` (installed in
  `/etc/udev/rules.d`) parks them on seat `seat-obsidience-tv`, `/etc/keyd/default.conf`
  excludes `1209:0002`, and the desktop's `hyprland.lua` disables them by name.
  `input-check` proves the isolation (exit 0) and fails closed. The TV remote does not
  reach the workstation; a remote path is designed but not built (it bypasses Sunshine).

## Playing something

Ask the tuner, never the player: one JSON line per request on `tuner.sock`, one JSON
line back (`{"ok": true, "state": {...}}`). The Harness does this through
`obsidience/harness/capabilities/tv/player.py`; by hand:

    printf '%s\n' '{"op":"play","provider":"pluto","channel":"640a68880e884c0009979cc2","title":"FOX Weather","wait":12}' \
      | socat - UNIX-CONNECT:$XDG_RUNTIME_DIR/obsidience-tv/tuner.sock

- `play` with `provider` `pluto` and `channel` (the 24-digit `_id` of Pluto's public
  guide `api.pluto.tv/v2/channels`; the slug finds no streams) or with `url` (a plain
  https stream, handed to the player as it is), plus `title`. It replaces whatever
  plays and answers once the first picture shows (or the break card of a channel tuned
  in during its break, or `failed`), or after `wait` seconds.
- `pause`, `resume`, `stop`, `state`.
- State `playback`: `idle`, `loading`, `playing`, `break`, `paused` or `failed` (with a
  `reason`); also `title`, `video` size, `since`, and `provider`/`channel` for a channel.
  `playing` means the stream shows a picture, not that the picture is the intended one.

A channel is resolved by streamlink's Pluto plugin inside the tuner (one warm session:
measured 0.5-1.0 s from request to first picture, now and then 1.5-3.5 s when Pluto
answers slowly or the session is fresh), muxed by its ffmpeg and written into a FIFO
(`stream-N.fifo` beside the socket) that the player reads. A new play stops the previous
picture at once and releases the previous stream beside its own start.

The plugin drops the advertisement segments, and the player plays the programme it still
holds (up to about eight seconds). Once it has run dry and the plugin reports
advertisements, the tuner draws a break card over the last frame (channel, "Commercial
break", elapsed time) and reports `break`; the plugin can see the first advertisement a
second or two after the player ran dry, which reads as `loading` until then. When the
programme returns the player first buffers eight seconds (`cache-pause-wait`; resuming on
the first segment stalled twice in the next minute), then plays, and the tuner removes the
card and reports `playing`. A first picture waits for the same margin (about 0.1 s on an
ordinary channel change). A channel tuned in during its break shows the card within a few
seconds, over the empty screen, and its picture when the break ends. A stream that ends
or fails is opened once more with a fresh session; if that fails too the state is
`failed` and nothing loops. The journal (`journalctl --user -u obsidience-tv-tuner`) names
titles and channel ids, state changes and when advertisements begin and end, never a
stream address.

Measured on the television, 2026-10-12 (FOX Weather, about three minutes of advertisements
every 12-17 minutes): the card showed 4.6 s after the advertisements began, the programme
returned 4.8 s after they ended, and in the following two minutes video and audio each
advanced 120.0 s with no stall. Through `tv.control` an idle player showed the channel
1.0 s after the tuner got the request (3.7 s for the whole typed request).

After a streamlink update, check what the tuner relies on beyond its public session,
plugin and stream calls: the Pluto plugin taking a channel id in the page address,
keeping its `app_version` per instance and accepting a new `url` on the same instance;
a muxed stream's `substreams`, each opened through its own `open()` (the tuner takes the
readers there) and reporting advertisements through `is_paused()`; and the muxer's
`pipes` (released on close, or a writer waits forever for an ffmpeg that is gone) and
`process` (reaped on close).

## Television side

Moonlight 12.2 (`com.limelight`), paired with this host. Settings chosen for
television: 4K, 60 FPS, 80 Mbps (about 63 Mbps of video), frame pacing "Prefer
smoothest video", connection warnings off. "Balanced" pacing was measured worse
(1.6% skipped refreshes against 0.5%). `am start -n com.limelight/.ShortcutTrampoline --es UUID
<host uniqueid> --es Name Obsidience` opens the host's app list; one select starts
"Obsidience TV"; with `--es AppName "Obsidience TV"` it starts the app directly. When
the host restarts, Moonlight shows "Connection Terminated" and must be started again.
Firewall: the TV's address only, tcp 47984, 47989, 48010 and
udp 47998-48000, 48002, 48010.

## Known limits (measured 2026-10-12)

- Sunshine sends 60 frames a second on average but unevenly (interval 3-38 ms, standard
  deviation about 5 ms; `sudo python3 framesniff.py IFACE SECONDS` reads its outgoing
  packets). Its Wayland capture polls: it asks for a frame on an exact 16.67 ms clock
  and each request completes only at the compositor's next buffer commit, 0.7-24 ms
  later (mean 11-13 ms at the 60 Hz mode, measured with `WAYLAND_DEBUG=1`); conversion
  and NVENC add 6.4 ms with a 2.8 ms spread. A 120 Hz output mode cuts the wait to about
  2 ms but then only commits with new content complete a capture, so the spacing stays
  uneven. With "smoothest" pacing the TV hides this except for a burst of skipped
  refreshes (about 8 s, 0.5% overall) roughly every 7 minutes, when the stream clock
  drifts past the TV's refresh. Not solved; an event-driven capture is the direction.
- wlroots' headless output re-arms a whole-millisecond frame timer after each commit, so
  a "60 Hz" output is not a 60.00 Hz clock (clients estimate 62-70 Hz).
- History, solved by the tuner: FFmpeg's HLS reader (mpv's) cannot play Pluto across an
  ad break. Pluto serves video and audio as separate playlists and marks the break with
  `#EXT-X-DISCONTINUITY`, which FFmpeg skips; it then reads one playlist only and the
  player starves (no recovery in a 15-minute reproduction). streamlink's Pluto plugin
  muxes the two, drops the ad segments and resumes at the next content frame. The player
  is fed through a FIFO because over streamlink's HTTP server mpv times out during the
  break. Pluto's v1 stitcher path and the guide's `stitched.urls` play a "no longer
  available on this device" slate.

## Checking smoothness

Measure on the TV, not on the workstation: `dumpsys SurfaceFlinger --latency
"SurfaceView - com.limelight/com.limelight.Game#0"` lists presented frames (every
interval should be one refresh), and Moonlight's logcat shows discarded audio.
