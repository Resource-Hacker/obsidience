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
| `obsidience-tv-session.service` | A headless sway compositor with one output; its GPU and size come from the TV mode (below): 1920x1080@60 on the integrated GPU, or 3840x2160@60 on the RTX 4080 |
| `obsidience-tv-player.service` | `mpv --idle` in that compositor; JSON IPC at `$XDG_RUNTIME_DIR/obsidience-tv-player.sock`, used by the tuner only |
| `obsidience-tv-tuner.service` | `tuner.py` (system Python with streamlink): the one owner of the player's IPC socket and of what plays; control socket `$XDG_RUNTIME_DIR/obsidience-tv/tuner.sock` |
| `obsidience-tv-sunshine.service` | Sunshine (HEVC on the mode's GPU: VAAPI on the integrated GPU, or NVENC on the RTX 4080), connected only to that compositor and that audio server |
| `obsidience-tv-remote.service` | `remote.py` (system Python with pywayland): the television's remote keys, typed into that compositor through a virtual keyboard (section below). Not installed or enabled yet |
| `obsidience-tv-android.service` | Android TV in its own container (section below); its window is one more client of that compositor. Staged 2026-10-12, not installed or enabled yet |
| `obsidience-tv-mode@.service` | One run of `mode <1080p\|default>`, started by GameMode |

The session publishes its Wayland socket name in `$XDG_RUNTIME_DIR/obsidience-tv/wayland`;
the player and Sunshine wait for it. Stopping the session stops both, and the tuner with
them. The tuner is not part of the Harness: a channel keeps playing while the Harness
restarts.

## Modes

`mode 4k|1080p|default|reload|client|status` (this directory) is the one place that decides
which GPU carries the TV session.

| Mode | Session and encode | Stream | |
| --- | --- | --- | --- |
| `1080p` (default) | Integrated GPU, VAAPI | 1920x1080, about 15 Mbit/s | Nothing else competes for that GPU the way the desktop and games compete for the RTX 4080 |
| `4k` | RTX 4080, NVENC | 3840x2160, about 63 Mbit/s | Sharper; only as smooth as that card is free |

Why 1080p is the default (measured on the television, 2026-10-12): on the RTX 4080 the
stream is fine while the desktop is quiet (0.5% of refreshes skipped) and fell to 54 frames a
second, 10-11% skipped, while the desktop played a video in the browser; a test compositor
and encoder on that card had the same effect and once dropped the session. In the same
minutes the integrated GPU, itself fully busy with another test, held 59.7 frames a second
and 0.45% skipped. The integrated GPU cannot encode 3840x2160 at 60 frames a second (44
against 135 at 1920x1080, with the side-panel screen recorders running).

`modes/4k.env` and `modes/1080p.env` hold everything that differs (render node, sway
configuration, compositor renderer, the player's Vulkan device and frame timing, Sunshine's
encoder, Moonlight's resolution entry, the break view's capture size); `modes/default.env`
is a link to the default one. The session, player, tuner and Sunshine units read
`default.env` and then `$XDG_RUNTIME_DIR/obsidience-tv/mode.env`, a link that exists only
while the mode is not the default, so a reboot returns to the default. A switch sets or
removes that link, restarts the session (which restarts the other units of the session), asks
the tuner for the channel that was playing, and, when the television was showing the stream,
brings it back.

GameMode keeps a game off a shared card (owner, 2026-10-12: the TV drops to the integrated
GPU during gaming): `~/.config/gamemode.ini` starts `obsidience-tv-mode@1080p.service` when
the first game registers and `obsidience-tv-mode@default.service` when the last one exits
(both WoW launchers use GameMode). With 1080p as the default both do nothing; they matter
when the mode was set to `4k`. The commands return at once, so a game's start never waits.

The stream's size is whatever Moonlight asks for: its "Video resolution" setting, which
cannot be set from outside the app. So `mode` changes that setting on the television's
screen over ADB (host list, settings button, "Video resolution", the entry by name), reads
it back from the same list, and remembers the value in
`~/.local/state/obsidience-tv/moonlight-resolution` so that nothing is touched when it
already fits. Moonlight then chooses its default bit rate for that size. A television that
is off, unreachable or showing another app is left alone; `tv.control` runs `mode client`
before it next starts the stream. A stream started by hand in between asks for the old size.

A switch between modes takes 26-34 s on the television (about 10 s until the channel plays
again on the other GPU, the rest is Moonlight's setting and reconnect); `mode reload`, with
no change of size, about 15 s.

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
  reach the workstation: its keys reach the TV session only, by a path that bypasses
  Sunshine (next section).

## The remote

Moonlight sends the Fire TV remote as a gamepad (no Back, no Play/Pause), and Sunshine's input
stays disabled. The keys take another road, which creates no kernel input device:

1. The TV agent (`org.obsidience.tv`, version 2, `obsidience/tv/android`) asks Fire OS for key
   events only while a host client has asked for keys **and** Moonlight's stream activity
   (`com.limelight/.Game`) is in front. It then consumes a first press of Up, Down, Left, Right,
   Select, Back, Menu, Play/Pause, Rewind or Fast forward when the stream's own window has input
   focus (a Moonlight dialog keeps its keys), and pushes the press and the release to the clients
   that asked. Repeats are swallowed. Home is never consumed and leaves the stream; keys from the
   Harness's virtual remote pass through. Without a client, or once it is gone, the television
   handles its keys exactly as it does without the agent. An agent that has just started (an
   update, a television restart) learns that the stream is in front the next time the stream's
   window takes the focus.
2. `obsidience-tv-remote.service` runs `remote.py`, that client. It opens one stream to the
   agent's socket through the ADB server that is already running (the server's host protocol,
   `host:transport:<television>` then `localabstract:obsidience-tv`): no forward exists that
   could be left behind or removed by the Harness, and no `adb` command runs that could start a
   server inside the unit. It never connects ADB to the television; the Harness does.
3. While the agent grants keys, `remote.py` holds one `zwp_virtual_keyboard_v1` in the TV
   compositor with the stock keymap and sends each key as its evdev scancode (table in
   `remote.py`: arrows, Enter, Escape, Menu, Play/Pause, Rewind, Fast forward) to whatever
   window that compositor focuses. A connection that ends releases held keys and removes the
   keyboard. Key repeat is the receiving program's business.

It fails closed: `remote.py` reads the compositor's socket name from
`$XDG_RUNTIME_DIR/obsidience-tv/wayland`, connects by that path, and refuses (exit 78, not
restarted) unless the process behind the socket runs in `obsidience-tv-session.service` and
offers the virtual-keyboard global. The unit's environment names no compositor.

The player ignores every key (`--input-default-bindings=no` in its unit): mpv's defaults would
seek in a live stream, pause it or leave full screen. The break view already did the same.

Measured 2026-10-12 against a private compositor and a stand-in for the agent: from the agent's
push to the key at a client of the compositor 0.1 ms (median of 400 events, largest 0.5 ms);
ten keys arrive as scancodes 103, 108, 105, 106, 28, 1, 127, 164, 168 and 208;
`/proc/bus/input/devices` does not change. Not measured: the television's side (whether Fire OS
hands these keys to the agent, and the time across ADB over Wi-Fi). `remote.py --debug` logs each
key with the time it spent in the agent, on the way, and here.

Rollback: `systemctl --user disable --now obsidience-tv-remote` (the agent then takes no key);
remove the unit copy. Agent version 1 again: uninstall `org.obsidience.tv` (a lower version does
not install over a higher one), set `VERSION = 1` in `harness/capabilities/tv/agent.py` and let
the Harness install and enable it.

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

With `--break-view PROGRAM` (the unit passes `break-view` from this directory) the tuner runs
that program for as long as each break lasts, with the title as its argument, and kills it when
the programme returns. `break-view` shows the workstation screen that holds the Executive graph
(owner request, 2026-10-12): the screen recorder already used for screen replay captures desktop
output `DP-8` at 30 frames a second, encoded on the GPU that drives that output, and a second
mpv (`app_id` `obsidience-tv-break`) plays it in the TV session, where the window rule puts it
full screen above the channel's player until it exits; a caption names the channel and the
break. Nothing is rendered twice, and nothing runs between breaks. The card still shows first
(the view needs a second or two to its first picture) and stays when the graph stage
(`obsidience-shell-knowledge.service`) is not running. This is the one place where desktop
content reaches the TV: whatever `DP-8` shows is what a break shows. The view is killed rather
than asked to quit because a quitting player kept its window for a second.

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

## Android TV instance (staged 2026-10-12)

TV apps run on the workstation, not on Fire OS: an unmodified Waydroid 1.6.3 with the
WayDroid-ATV image (Android TV 16, LineageOS 23.0, build 20260403, no Google services) runs
inside the rootful Podman container `obsidience-tv-android`, built from `android/`
(`Containerfile`, `entrypoint.sh`). The container has its own binderfs, cgroup namespace,
bridge network and D-Bus, so it never meets the Waydroid TFT uses on the host. Its window
(`app_id` `Waydroid`) is a client of the TV compositor. It needs a workspace of its own
(`assign [app_id="Waydroid"] workspace android` in the sway configuration; not added yet):
sway keeps one fullscreen window per workspace and tiles the others, which would resize
Android's display. `swaymsg workspace android` then shows it and `workspace 1` the player.
Android stays awake while its workspace is hidden, so switching back shows it at once. A mode
switch restarts the session and this unit with it (Android is back in 11-13 s).

Everything it owns is under `~/.local/share/obsidience-tv-android`: `dl/` and `images/` (the
verified release archives and the two images, read-only in the container), `state/` (Waydroid
configuration and Android's data), `apps/` (verified APKs) and `containers/` (Podman's store
for this image). Podman is always called with `--root` that store, `--runroot
/run/obsidience-tv-android/storage --tmpdir /run/obsidience-tv-android/libpod`: the root
filesystem had no unallocated Btrfs space on 2026-10-12 and an image commit into the default
store failed there.

Rules:

- Never use the host's `waydroid` command for this instance (it always addresses TFT's), never
  `--cgroupns=host`, and never mount the host's `/dev`, `/run/dbus` or runtime directory.
  The LXC payload cgroup must be below the container's own scope
  (`machine.slice/libpod-<id>.scope/container/lxc.payload.waydroid`), never at the top of
  `/sys/fs/cgroup`, where TFT's compatibility hook looks.
- The entrypoint removes input, camera, sound, framebuffer and NVIDIA nodes from the container's
  private `/dev` before Waydroid lists devices, and keeps one render node, the integrated GPU's.
  Android therefore has no `/dev/uhid`: keys reach it by `adb shell input keyevent` or through
  the compositor, never through a virtual HID device.
- The Waydroid session runs as the owner of the compositor's socket. The image starts its
  composer as the session's user without capabilities and the socket is owner-only; a session
  run as root cannot open it ("Couldn't open Wayland display" in a restart loop).
- Android's display is the compositor's output: 3840x2160 at density 640 or 1920x1080 at
  density 320, chosen by the image. `persist.waydroid.width`/`height` pin a size but the
  window is then shown unscaled (a quarter of a 3840x2160 output).
- Loop devices are host-wide: a running Android holds about 42 of them for its APEX images
  (TFT's does the same), which is why the entrypoint makes 256 loop nodes.

Measured 2026-10-12 with private compositors configured like this session (launcher navigated
at 8 keys a second; frame statistics from `dumpsys gfxinfo`):

| Compositor | Android display | Frames over one refresh | Compositor CPU |
| --- | --- | --- | --- |
| RTX 4080, GLES2 (mode `4k`) | 3840x2160 | 30% (median frame 36 ms) | 27% of a core |
| RTX 4080, GLES2 | 1920x1080 pinned, shown unscaled | 0% (5 ms) | 14% |
| RTX 4080, Vulkan (`WLR_RENDERER=vulkan`) | 3840x2160 | 0% (5 ms) | 1% |
| Integrated GPU, GLES2 | 3840x2160 | 0% (5 ms) | 0.4% |
| Integrated GPU, GLES2, 1920x1080 output (mode `1080p`) | 1920x1080 | 0.1% (12 ms, with the live session also on that GPU) | 0.7% |

Android renders on the integrated GPU and hands the compositor LINEAR dmabufs; the RTX 4080
samples them without a copy (a test client sending 59 MB frames at 63 a second cost the
compositor 3% of a core from either GPU). With Android's own 3840x2160 frames the GLES2
compositor on the RTX 4080 spends its time inside the NVIDIA driver and Android misses
refreshes; the cause is not isolated. Not measured: Sunshine capturing Android's frames, and
video playback (no network without the firewall rule below).

Other numbers: first start to `sys.boot_completed` 14 s, later starts 11-13 s, stop 1 s;
SmartTube cold start 0.15 s; key to next frame 15 ms through the compositor and 63 ms by ADB;
idle 1% of a core and 1.9 GiB (2.8 GiB at 3840x2160).

Keys through the compositor must be real evdev scancodes from a virtual keyboard that stays
connected (Waydroid forwards the scancode and ignores the keymap; Android adds its
`wayland_keyboard` only while the seat has a keyboard). `wtype` invents a keymap and sends
codes 1, 2, 3..., so its first key arrives as Escape, which Android reads as Back.

Setting it up again from nothing (the staged copy already has all of this):

    D=~/.local/share/obsidience-tv-android; P="sudo podman --root $D/containers --runroot /run/obsidience-tv-android/storage --tmpdir /run/obsidience-tv-android/libpod"
    # images: release 20260403 of WayDroid-ATV/waydroid-androidtv-builds, digests in artifacts.lock.json
    $P build --network host -t localhost/obsidience-tv-android:1 obsidience/tv/host/android
    sudo podman network create --disable-dns --subnet 10.89.240.0/24 --interface-name obstv0 obsidience-tv
    systemctl --user start obsidience-tv-android       # first start initialises state/ from the images
    # once: the workstation's ADB public key (never the private key), then the setup wizard
    $P exec -i obsidience-tv-android lxc-attach -P /var/lib/waydroid/lxc -n waydroid --clear-env -- \
      /system/bin/sh -c 'cat >> /data/misc/adb/adb_keys && chown system:shell /data/misc/adb/adb_keys && chmod 0640 /data/misc/adb/adb_keys && settings put global adb_enabled 1 && setprop ctl.restart adbd' < ~/.android/adbkey.pub
    adb connect 10.89.240.2:5555                        # reachable from the workstation only

Android reaches the network only with a route rule, which is not installed (without it only
ICMP passes the firewall, so apps show "Unable to resolve host"):
`sudo ufw route allow in on obstv0 out on enp12s0 comment 'Obsidience TV Android'`.
Starting a container on the bridge sets `net.ipv4.ip_forward=1` until reboot.

Not yet checked: TFT running beside it (start TFT with this instance up; its payload must be
`/sys/fs/cgroup/lxc.payload.waydroid` and its compatibility hook must attach), pacing on the
television's panel, hardware video decoding, and the remote's keys.

Rollback: `systemctl --user disable --now obsidience-tv-android`; `adb disconnect
10.89.240.2:5555`; `sudo podman network rm obsidience-tv`; the ufw route rule if it was added;
`sudo rm -rf ~/.local/share/obsidience-tv-android /run/obsidience-tv-android`. No host package
was installed for it.


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

- The television cannot show a 60 fps stream without repeats: its panel refreshes at
  60.071 Hz (SurfaceFlinger's measured period, 16.647 ms; the mode is advertised as
  60.000004), so about once in 14 s a refresh has no new frame, whatever the host does.
  That floor is 0.12% of refreshes; 30 fps programmes meet the same one on any player.
- Sunshine sends each frame the moment its encode finishes, 3-30 ms after the capture
  and different for every frame (a shared GPU; `sudo python3 framesniff.py IFACE SECONDS`
  reads its outgoing packets). Left alone, Moonlight's "smoothest" pacing showed that as
  minutes without a skipped refresh and then about 20 s with 10-18 skipped a second,
  every 5-6 minutes (0.6-0.8% overall). `tvpace.c` is preloaded into Sunshine by its
  unit and holds the first packet of each frame until the frame's slot on an even 60 fps
  grid, placed just behind the slowest recent frame: video leaves about 20-35 ms later,
  sound does not. With it the television skipped 1-5 refreshes at each 14 s crossing and
  had no long burst (0.4-0.5% overall, 13 minutes). It holds only frames of a steady
  60 fps stream and passes everything else through; once a minute the journal says how
  many frames missed their slot (`tvpace: ... late`). The dynamic loader starts Sunshine
  because glibc ignores `LD_PRELOAD` for a program with file capabilities; Sunshine then
  runs without them, which Wayland capture does not need. The unit builds the library
  when it is missing or older than its source. After a `sunshine` update check the two
  packet layouts it reads (its header comment names them) and that the journal still
  counts frames.
- A break view's start and end each cost the stream about 20 frames (0.4 s) while the
  second player's window appears or goes.
- Do not raise the output's refresh rate to even the captures: at 120-1000 Hz the player's
  pictures are sampled badly (with 30 fps video 13-40% of the pictures stayed on screen for
  one or three stream frames instead of two, against 4-8% at 60 Hz, measured on a private
  copy of this stack), and Sunshine's portal capture halves 60 fps content. Details of
  those measurements: commit message history and `AGENTS.local.md`.
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

Black or half-drawn frames do not show in refresh timing. `flashcheck ADB_SERIAL [SECONDS]`
records the television's own screen and counts frames that are suddenly dark between two
bright ones. With the compositor's Vulkan renderer on the RTX 4080 it found 5 in 90 s (frames
black above a tear line: Sunshine read its capture buffer before the compositor had finished
drawing it); with the GLES2 renderer none in 170 s. The GLES2 renderer is the setting.
