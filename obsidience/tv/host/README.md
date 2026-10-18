# TV host

The television shows a session hosted on the workstation: content plays here and
the Fire TV only displays it through Moonlight. Fire OS is the display client, not
the place where channels load.

This file is the current contract. The measurements behind it are in the installation's
archive note `~/Notes/instruction-archive/obsidience-tv-host-history-20261015.md` and in the
commit messages.

| Path | Holds |
| --- | --- |
| `tv/host/` (this directory) | What the units run: `tuner.py`, `break-view`, `remote.py`, `voice.py`, `mode`, `show`, `tvpace.c`, the sway, Sunshine, Snapcast and PipeWire configuration, `modes/`, `android/` (the Android TV container) and the checks `input-check` and `flashcheck` |
| `tv/systemd/` | The unit sources and the udev seat rule |
| `tv/firetv-agent/` | The Fire TV agent `org.obsidience.tv` and its `build.sh` |

## Services

User units, installed as copies of `tv/systemd/` in `~/.config/systemd/user` and enabled
(`obsidience-tv-mode@` is a template that GameMode starts). The units name files in this
directory by absolute path, and a change to a unit source takes effect only once its copy is
reinstalled (`scripts/deploy` does that for the player and the tuner).

| Unit | Owns |
| --- | --- |
| `obsidience-tv-audio.service` | A private PipeWire server (`$XDG_RUNTIME_DIR/obsidience-tv`), configured only by `audio/` |
| `obsidience-tv-audio-policy.service` | WirePlumber for that server, policy only, state in the runtime directory |
| `obsidience-tv-audio-pulse.service` | Its PulseAudio endpoint (Sunshine captures through it) and the idle sink `obsidience_tv` |
| `obsidience-tv-session.service` | A headless sway compositor with one output; its GPU and size come from the TV mode (below): 1920x1080@60 on the integrated GPU, or 3840x2160@60 on the RTX 4080 |
| `obsidience-tv-player.service` | `mpv --idle` in that compositor; JSON IPC at `$XDG_RUNTIME_DIR/obsidience-tv-player.sock`, used by the tuner only |
| `obsidience-tv-tuner.service` | `tuner.py` (system Python with streamlink): the one owner of the player's IPC socket and of what plays; control socket `$XDG_RUNTIME_DIR/obsidience-tv/tuner.sock` |
| `obsidience-tv-sunshine.service` | Sunshine (HEVC on the mode's GPU: VAAPI on the integrated GPU, or NVENC on the RTX 4080), connected only to that compositor and that audio server |
| `obsidience-tv-remote.service` | `remote.py` (system Python with pywayland): the television's remote keys, typed into that compositor through a virtual keyboard (section below) |
| `obsidience-tv-android.service` | Android TV in its own container (section below); its window is one more client of that compositor |
| `obsidience-tv-voice*.service` | The Executive's voice on the television (four units, section below) |
| `obsidience-tv-mode@.service` | One run of `mode <1080p\|default>`, started by GameMode |

`72-obsidience-tv-seat.rules` is installed as a copy in `/etc/udev/rules.d` (Boundaries).

The session publishes its Wayland socket name in `$XDG_RUNTIME_DIR/obsidience-tv/wayland`
(the player and Sunshine wait for it) and its control socket in `.../obsidience-tv/sway`
(`show` reads it). Stopping the session stops both, and the tuner with
them. The tuner is not part of the Harness: a channel keeps playing while the Harness
restarts.

## Modes

`mode 4k|1080p|default|reload|client|status` (this directory) is the one place that decides
which GPU carries the TV session.

| Mode | Session and encode | Stream | |
| --- | --- | --- | --- |
| `1080p` (default) | Integrated GPU, VAAPI | 1920x1080, about 15 Mbit/s | Nothing else competes for that GPU the way the desktop and games compete for the RTX 4080 |
| `4k` | RTX 4080, NVENC | 3840x2160, about 63 Mbit/s | Sharper; only as smooth as that card is free |

1080p is the default because on the RTX 4080 the stream stutters while the desktop or a game
uses that card. The integrated GPU cannot encode 3840x2160 at 60 frames a second, so 4K needs
the RTX 4080. A 30 fps stream at 3840x2160 is not a mode: it missed the panel's cadence on both
GPUs.

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

The stream's size and rate are whatever Moonlight asks for: its "Video resolution" and
"Video frame rate" settings, which cannot be set from outside the app. So `mode` changes
them on the television's screen over ADB (host list, settings button, the setting, the entry
by name), reads each back from the same list, and remembers the values in
`~/.local/state/obsidience-tv/moonlight-resolution` so that nothing is touched when it
already fits. Moonlight then chooses its default bit rate for that size. A television that
is off, unreachable or showing another app is left alone; `tv.control` runs `mode client`
before it next starts the stream. A stream started by hand in between asks for the old size.

## The Executive's voice on the television

Owner request, 2026-10-12: the television as a second speaker for the Executive's voice, in
step with the desk speakers. A second speaker over Wi-Fi is in step only if both speakers play
each moment of sound at an agreed time, which is what Snapcast is for.

| Unit | Owns |
| --- | --- |
| `obsidience-tv-voice-sink.service` | a small PipeWire client (`voice/pipe-sink.conf`, module pipe-tunnel) that offers the sink `obsidience_tv_voice` and writes what plays into it to the pipe `$XDG_RUNTIME_DIR/obsidience-tv/voice.fifo` |
| `obsidience-tv-voice-server.service` | `snapserver` with `voice/snapserver.conf`: reads that pipe; stream port 1704 and control port 1705 (the firewall admits only the television) |
| `obsidience-tv-voice-desk.service` | `snapclient` (host id `obsidience-desk`) on the Executive's physical speaker, named in `voice/desk.env` |
| `obsidience-tv-voice.service` | `voice.py`: while a television client listens, the voice chain in front of the speakers, and which of its two paths is audible |

On the television the Snapcast app (`de.badaix.snapcast` 0.29.0.2, sideloaded unmodified)
finds the server by mDNS; its client runs as a foreground service and keeps playing while
Moonlight is in front. Each client plays every chunk at the server's time plus the server's
`buffer` (300 ms) and keeps correcting its clock, so the voice on this route starts 0.3 s
later.

The client goes with the television's screen. It neither starts itself after the television
restarts nor stops when it sleeps, so `tv.control` starts and stops it through the app's own
receiver (`am broadcast -a de.badaix.snapcast.START_SERVICE` or `STOP_SERVICE`
`-n de.badaix.snapcast/.BroadcastReceiver`, which does not touch the screen): with its own
power commands, when the television's agent reports that the screen went off or came on by
the remote, and when it starts the stream. With the television off there is no client, no
chain, and the voice plays on the desk speakers directly, as it did before all this.

Speech can afford 0.3 s; the chirp that opens the line cannot (owner: it must be as snappy as
possible). While a television client listens, `voice.py` keeps a voice sink
(`obsidience_tv_voice_in`) that the speech worker's one playback stream is put on, with two
paths out of it that run all the time: one straight to the desk speakers, one into the
Snapcast sink. Exactly one is audible, and choosing is a mute, never a move (moving the
worker's stream for each reply stalled it for two seconds). The direct path is audible while
the Executive waits for its name, so the opening chirp is immediate. Once the line is open
and that chirp has ended, while the owner speaks, the Snapcast path takes over: the
"accepted" chirp, the reply and the closing chirp play on both speakers in step, and then
the direct path returns. A command spoken over the opening chirp switches after the
"accepted" chirp instead. A reply ending in a question has no closing chirp: the line opens
again with its ready chirp in step, and the exchange ends with that line's closing or cancel
chirp. `voice.py` reads those moments from the Harness (`/ws/trace` chirp
lines, `/ws/realtime` state) and the television's presence from the Snapcast server. A
television that stops listening during an exchange changes nothing until the exchange ends;
none begins on the Snapcast path without it. The echo reference is unchanged: it is the
monitor of the physical speaker, which carries the voice whichever way it arrives there.

A reply must not be lost to this. In step, `voice.py` compares, electrically, what goes
into the chain with what the desk speakers receive: sound in and none out for 0.9 s puts the
direct path back at once and restarts the server; a shorter sound (a chirp) that never came
out restarts the server when the exchange ends. The server reads a pipe, not its own PipeWire
input, which stopped producing chunks after running a while. To check the path without a
sound anyone hears, play one second of 90 Hz at -40 dBFS into `obsidience_tv_voice` and look
for it on the desk speaker's monitor.

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
- 4K: the session renders and encodes on the RTX 4080; the model GPU is
  never used. Four pins keep it there: the compositor's render node
  (`WLR_RENDER_DRM_DEVICE`, sway needs `--unsupported-gpu`), the player's Vulkan device
  UUID, Sunshine's `CUDA_VISIBLE_DEVICES` UUID and Sunshine's `adapter_name`. Without
  `adapter_name` Sunshine allocates its capture buffers on another card and every
  capture fails ("Frame capture failed"; the compositor logs "DMA-BUF format is
  external-only", or with the Vulkan renderer "can't be used with modifier LINEAR").
  The iGPU cannot carry 4K: its encoder is shared with the side-panel screen recorders.
- Player frame timing is per mode, chosen by measurement on the TV panel
  (`TV_VIDEO_SYNC` in `modes/`): audio-clock timing on the RTX 4080, display-synced on the iGPU.
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

1. The TV agent (`org.obsidience.tv`, version 2, `obsidience/tv/firetv-agent`) asks Fire OS for key
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
3. `remote.py` holds one `zwp_virtual_keyboard_v1` in the TV compositor with the stock keymap
   for as long as the unit runs and, while the agent grants keys, sends each key as its evdev
   scancode (table in `remote.py`: arrows, Enter, Escape, Menu, Play/Pause, Rewind, Fast
   forward) to whatever window that compositor focuses. A connection that ends releases held
   keys. Key repeat is the receiving program's business.

The keyboard stays while the television is off, on purpose. It is the seat's only keyboard, so
when it comes or goes Android sees a hardware keyboard appear or vanish and restarts the activity
in front; SmartTube's player then plays its last video again although it had been stopped, unseen
and audible behind the channel. Restarting this unit alone still does that once: afterwards read
`tv.control`'s state, or stop Android's player (`cmd media_session dispatch stop`).

It fails closed: `remote.py` reads the compositor's socket name from
`$XDG_RUNTIME_DIR/obsidience-tv/wayland`, connects by that path, and refuses (exit 78, not
restarted) unless the process behind the socket runs in `obsidience-tv-session.service` and
offers the virtual-keyboard global. The unit's environment names no compositor.

The player ignores every key (`--input-default-bindings=no` in its unit): mpv's defaults would
seek in a live stream, pause it or leave full screen. The break view already did the same.

`remote.py --debug` logs each key with the time it spent in the agent, on the way, and here.

Rollback: `systemctl --user disable --now obsidience-tv-remote` (the agent then takes no key);
remove the unit copy. Agent version 1 again: uninstall `org.obsidience.tv` (a lower version does
not install over a higher one), set `VERSION = 1` in `harness/tv/agent.py` and let
the Harness install and enable it.

## Playing something

Ask the tuner, never the player: one JSON line per request on `tuner.sock`, one JSON
line back (`{"ok": true, "state": {...}}`). The Harness does this through
`obsidience/harness/tv/player.py`; by hand:

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

A channel is resolved by streamlink's Pluto plugin inside the tuner (one warm session),
muxed by its ffmpeg and written into a FIFO (`stream-N.fifo` beside the socket) that the
player reads; mpv's own HLS reader cannot play Pluto across an ad break, and over streamlink's
HTTP server mpv times out during the break. A new play stops the previous picture at once and
releases the previous stream beside its own start.

The plugin drops the advertisement segments, and the player plays the programme it still
holds (up to about eight seconds). Once it has run dry and the plugin reports
advertisements, the tuner draws a break card over the last frame (channel, "Commercial
break", elapsed time) and reports `break`; the plugin can see the first advertisement a
second or two after the player ran dry, which reads as `loading` until then. When the
programme returns the player first buffers eight seconds (`cache-pause-wait`), then plays,
and the tuner removes the card and reports `playing`. A first picture waits for the same
margin (about 0.1 s on an ordinary channel change). A channel tuned in during its break
shows the card within a few seconds, over the empty screen, and its picture when the break
ends. A stream that ends or fails is opened once more with a fresh session; if that fails
too the state is `failed` and nothing loops. The journal (`journalctl --user -u
obsidience-tv-tuner`) names titles and channel ids, state changes and when advertisements
begin and end, never a stream address.

With `--break-view PROGRAM` (the unit passes `break-view` from this directory) the tuner runs
that program while playback is idle and for as long as each break lasts, with title and
`idle`/`break` arguments, and kills it when content loads or the programme returns.
Stopping content or reaching file EOF returns to the idle view. Paused content retains its
picture. `break-view` shows the workstation screen that holds the Executive graph
(owner request, 2026-10-12): the screen recorder already used for screen replay captures the
desktop USB-C Surface (its current connector, resolved by `shell/surface_identity.py`) at 30
frames a second, encoded on the GPU that drives that output, and a second
mpv (`app_id` `obsidience-tv-break`) plays it in the TV session, where the window rule puts it
full screen above the channel's player until it exits; a caption names the channel and the
break; idle mode shows the graph without that caption. The same presenter owns both modes,
and the mirror does not run while content is loading, playing or paused. Moonlight displays
this idle screen through the existing TV stream. The card still shows first
(the view needs a second or two to its first picture) and stays when the graph stage
(`obsidience-shell-knowledge.service`) is not running. This is the one place where desktop
content reaches the TV: whatever the USB-C Surface shows is what a break shows. The view is
killed rather than asked to quit because a quitting player kept its window for a second.

After a streamlink update, check what the tuner relies on beyond its public session,
plugin and stream calls: the Pluto plugin taking a channel id in the page address,
keeping its `app_version` per instance and accepting a new `url` on the same instance;
a muxed stream's `substreams`, each opened through its own `open()` (the tuner takes the
readers there) and reporting advertisements through `is_paused()`; and the muxer's
`pipes` (released on close, or a writer waits forever for an ffmpeg that is gone) and
`process` (reaped on close).

## Android TV instance

TV apps run on the workstation, not on Fire OS: an unmodified Waydroid 1.6.3 with the
WayDroid-ATV image (Android TV 16, LineageOS 23.0, build 20260403, no Google services) runs
inside the rootful Podman container `obsidience-tv-android`, built from `android/`
(`Containerfile`, `entrypoint.sh`). The container has its own binderfs, cgroup namespace,
bridge network and D-Bus, so it never meets the Waydroid TFT uses on the host. Its window
(`app_id` `Waydroid`) is a client of the TV compositor. A mode switch restarts the session and
this unit with it (Android is back in 11-13 s).

The television shows one source at a time. `sway.conf` gives each a workspace of its own
(`player`: the channel player and its break view; `android`: this instance; sway keeps one
fullscreen window per workspace and tiles the others, which would resize Android's display) and
the session starts on `player`. `show player|android|status` (this directory) is the one place
that switches: it asks the session's compositor, and only that one (the process behind the
published control socket must run in `obsidience-tv-session.service`), prints the source then
shown, exits 0 only when that is the one asked for, and refuses a source that has no window (an
empty screen). It starts and stops nothing. A source that is not shown keeps running: Android
kept playing, sounding and decoding at full rate while hidden, and its picture was back within
one screenshot (0.2 s) of the switch. So whoever switches also ends what the other source plays;
`tv.control` does (the tuner's `stop`, Android's `cmd media_session dispatch stop`).

`tv.control` opens a YouTube video here instead of in the Fire OS app whenever this instance
answers on its ADB address: one `am start` of the watch link in SmartTube, the media session's
`playing` as the readback, `show android`, then Moonlight on the television as for a channel
(`obsidience/harness/tv/android.py` is the client). Live streams stay on Fire OS.

Two properties are required, and `entrypoint.sh` sets both on the first start (in
`state/waydroid.cfg`; to change one later, stop the unit and edit `[properties]` there and the
same line in `state/waydroid_base.prop`):

- `debug.ffmpeg-codec2.threads=4`. Every video decoder of this image is in its ffmpeg codec
  service, which announces an output delay of twice its thread count, by default one thread per
  CPU: 64 frames on this 32-thread CPU. Android 16 then gives the decoder more buffer slots than
  the service's slot tables hold (64), and it crashed within a second of every 720p and 1080p
  start. With 4 the delay is 8. Hardware decoding uses one thread anyway.
- `persist.waydroid.no_presentation=true`. A headless output is no clock: it reports a frame
  as presented when the client commits it, and Android's composer then fell to about 51 frames
  a second. Without the feedback its vsync runs free at 60 Hz.

SmartTube's video preset is set to "1080p 60fps vp9" (player, HQ button, Video presets); on
automatic it chose 2160p60 for a 1920x1080 display, which this GPU did not carry. Decoding is
VA-API on the integrated GPU without a copy; `media.sf.hwaccel=0` selects software decoding in
the same service.

Android's low-memory killer reads the workstation's memory pressure, not its own: under host
memory pressure it can kill SmartTube in front. Not solved (`ro.lmk.*` is the place to look);
playback simply ends and the launcher shows.

Everything it owns is under `~/.local/share/obsidience-tv-android`: `dl/` and `images/` (the
verified release archives and the two images, read-only in the container), `state/` (Waydroid
configuration and Android's data), `apps/` (verified APKs) and `containers/` (Podman's store
for this image). Podman is always called with `--root` that store, `--runroot
/run/obsidience-tv-android/storage --tmpdir /run/obsidience-tv-android/libpod` (an image commit
into the default store on the root filesystem once failed for lack of Btrfs space).

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
- Keys through the compositor must be real evdev scancodes from a virtual keyboard that stays
  connected (Waydroid forwards the scancode and ignores the keymap; Android adds its
  `wayland_keyboard` only while the seat has a keyboard). `wtype` invents a keymap and sends
  codes 1, 2, 3..., so its first key arrives as Escape, which Android reads as Back.

Setting it up again from nothing (the installed copy already has all of this):

    D=~/.local/share/obsidience-tv-android; P="sudo podman --root $D/containers --runroot /run/obsidience-tv-android/storage --tmpdir /run/obsidience-tv-android/libpod"
    # images: release 20260403 of WayDroid-ATV/waydroid-androidtv-builds, digests in artifacts.lock.json
    $P build --network host -t localhost/obsidience-tv-android:1 obsidience/tv/host/android
    sudo podman network create --disable-dns --subnet 10.89.240.0/24 --interface-name obstv0 obsidience-tv
    systemctl --user start obsidience-tv-android       # first start initialises state/ from the images
    # once: the workstation's ADB public key (never the private key), then the setup wizard
    $P exec -i obsidience-tv-android lxc-attach -P /var/lib/waydroid/lxc -n waydroid --clear-env -- \
      /system/bin/sh -c 'cat >> /data/misc/adb/adb_keys && chown system:shell /data/misc/adb/adb_keys && chmod 0640 /data/misc/adb/adb_keys && settings put global adb_enabled 1 && setprop ctl.restart adbd' < ~/.android/adbkey.pub
    adb connect 10.89.240.2:5555                        # reachable from the workstation only

Android reaches the network only with a route rule (installed 2026-10-12; without it only
ICMP passes the firewall, so apps show "Unable to resolve host"):
`sudo ufw route allow in on obstv0 out on enp12s0 comment 'Obsidience TV Android'`.
Starting a container on the bridge sets `net.ipv4.ip_forward=1` until reboot.

Not yet checked: TFT running beside it (start TFT with this instance up; its payload must be
`/sys/fs/cgroup/lxc.payload.waydroid` and its compatibility hook must attach), pacing on the
television's panel (every measurement so far is from the workstation's side of the stream), a
video at the `4k` mode's 3840x2160 display, and the remote's keys in SmartTube.

Rollback: `systemctl --user disable --now obsidience-tv-android`; `adb disconnect
10.89.240.2:5555`; `sudo podman network rm obsidience-tv`; the ufw route rule if it was added;
`sudo rm -rf ~/.local/share/obsidience-tv-android /run/obsidience-tv-android`. No host package
was installed for it.

## Television side

Moonlight 12.2 (`com.limelight`), paired with this host. Settings chosen for
television: 4K, 60 FPS, 80 Mbps (about 63 Mbps of video), frame pacing "Prefer
smoothest video", connection warnings off. `am start -n com.limelight/.ShortcutTrampoline --es UUID
<host uniqueid> --es Name Obsidience` opens the host's app list; one select starts
"Obsidience TV"; with `--es AppName "Obsidience TV"` it starts the app directly. When
the host restarts, Moonlight shows "Connection Terminated" and must be started again.
Firewall: the TV's address only, tcp 47984, 47989, 48010 and
udp 47998-48000, 48002, 48010.

## Known limits

- The television cannot show a 60 fps stream without repeats: its panel refreshes at
  60.071 Hz (SurfaceFlinger's measured period, 16.647 ms; the mode is advertised as
  60.000004), so about once in 14 s a refresh has no new frame, whatever the host does.
  That floor is 0.12% of refreshes; 30 fps programmes meet the same one on any player.
- Sunshine sends each frame the moment its encode finishes, a different 3-30 ms after the
  capture for every frame, which Moonlight's "smoothest" pacing shows as bursts of skipped
  refreshes. `tvpace.c` is preloaded into Sunshine by its unit and holds the first packet of
  each frame until the frame's slot on an even 60 fps grid, placed just behind the slowest
  recent frame: video leaves about 20-35 ms later, sound does not. It holds only frames of a
  steady 60 fps stream and passes everything else through; once a minute the journal says how
  many frames missed their slot (`tvpace: ... late`). The dynamic loader starts Sunshine
  because glibc ignores `LD_PRELOAD` for a program with file capabilities; Sunshine then
  runs without them, which Wayland capture does not need. The unit builds the library
  when it is missing or older than its source. After a `sunshine` update check the two
  packet layouts it reads (its header comment names them) and that the journal still
  counts frames.
- A break view's start and end each cost the stream about 20 frames (0.4 s) while the
  second player's window appears or goes.
- In mode `4k` the GLES2 compositor on the RTX 4080 misses refreshes with the Android
  instance's own 3840x2160 frames; the cause is not isolated.
- Do not raise the output's refresh rate to even the captures: at 120-1000 Hz the player's
  pictures are sampled badly, and Sunshine's portal capture halves 60 fps content.
- wlroots' headless output re-arms a whole-millisecond frame timer after each commit, so
  a "60 Hz" output is not a 60.00 Hz clock (clients estimate 62-70 Hz).

## Checking smoothness

Measure on the TV, not on the workstation: `dumpsys SurfaceFlinger --latency
"SurfaceView - com.limelight/com.limelight.Game#0"` lists presented frames (every
interval should be one refresh), and Moonlight's logcat shows discarded audio.

Black or half-drawn frames do not show in refresh timing. `flashcheck ADB_SERIAL [SECONDS]`
records the television's own screen and counts frames that are suddenly dark between two
bright ones. The compositor's renderer is GLES2 (`TV_RENDERER`): with Vulkan on the RTX 4080
Sunshine captured half-drawn frames, black above a tear line.

## Optional Obsidience Media destination

The TV is one playback destination of the independent [media server](../../media/README.md).
Its catalogue and client delivery do not depend on these TV units. The optional
local-file variant extends this tuner, not the compositor, Sunshine or remote
keyboard. It is disabled until private media configuration explicitly enables it.

`play` with `provider:local` admits one approved regular MP4/M4V or Matroska/WebM
file by private root, relative path and file revision, plus catalogue instance,
item, media-source and source-revision identities. The typed client supplies a
fresh request generation. Paths remain request-only; readback exposes sanitized
identity and generation. `playing_verified` requires the matching playlist entry
and playback event; `loading` after the bounded wait remains unverified. Finite
EOF returns idle with an `ended` receipt and never runs channel reconnection.

`stop` with the exact observed local source and generation confirms unload and
idle before success. Generic pause/resume reject local files until the VOD
control slice supplies identity-bound controls. Existing channel and Android
transport paths are preserved. Restart the tuner/player only through the guarded
deployer at an idle boundary; never restart this compositor for a media change.
