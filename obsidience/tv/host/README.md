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
| `obsidience-tv-session.service` | A headless sway compositor with one 1920x1080@60 output on the AMD iGPU |
| `obsidience-tv-player.service` | `mpv --idle` in that compositor; JSON IPC at `$XDG_RUNTIME_DIR/obsidience-tv-player.sock` |
| `obsidience-tv-sunshine.service` | Sunshine, connected only to that compositor and that audio server |

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
- The player times frames to the compositor (`--video-sync=display-resample`).
  With audio-clock timing the TV panel skipped a refresh every second or so.
- Everything runs on the AMD iGPU and CPU; no NVIDIA card is used.

## Playing something

One IPC command: `{"command": ["loadfile", URL, "replace"]}`; `playback-restart`
means the stream started, not that the picture is the intended one.

## Television side

Moonlight 12.2 (`com.limelight`), paired with this host. Settings chosen for
television: 1080p, 60 FPS, about 29 Mbps, frame pacing "Prefer smoothest video",
connection warnings off. `am start -n com.limelight/.ShortcutTrampoline --es UUID
<host uniqueid> --es Name Obsidience` opens the host's app list; one select starts
"Obsidience TV". Firewall: the TV's address only, tcp 47984, 47989, 48010 and
udp 47998-48000, 48002, 48010.

## Checking smoothness

Measure on the TV, not on the workstation: `dumpsys SurfaceFlinger --latency
"SurfaceView - com.limelight/com.limelight.Game#0"` lists presented frames (every
interval should be one refresh), and Moonlight's logcat shows discarded audio.
