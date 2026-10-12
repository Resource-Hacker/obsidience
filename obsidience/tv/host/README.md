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
| `obsidience-tv-player.service` | `mpv --idle` in that compositor; JSON IPC at `$XDG_RUNTIME_DIR/obsidience-tv-player.sock` |
| `obsidience-tv-sunshine.service` | Sunshine (NVENC HEVC on the RTX 4080), connected only to that compositor and that audio server |

The session publishes its Wayland socket name in `$XDG_RUNTIME_DIR/obsidience-tv/wayland`;
the player and Sunshine wait for it. Stopping the session stops both.

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

One IPC command: `{"command": ["loadfile", URL, "replace"]}`; `playback-restart`
means the stream started, not that the picture is the intended one.

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
- FFmpeg's HLS reader (mpv's) cannot play Pluto across an ad break: Pluto serves video
  and audio as separate playlists and marks the break with `#EXT-X-DISCONTINUITY`, which
  FFmpeg skips; it then reads one playlist only and the player starves (no recovery in a
  15-minute reproduction). streamlink's Pluto plugin muxes the two, drops the ad
  segments and resumes at the next content frame (measured: 174 s pause, clean resume).
  Feed mpv through a FIFO: over streamlink's HTTP server mpv times out during the break.

## Checking smoothness

Measure on the TV, not on the workstation: `dumpsys SurfaceFlinger --latency
"SurfaceView - com.limelight/com.limelight.Game#0"` lists presented frames (every
interval should be one refresh), and Moonlight's logcat shows discarded audio.
