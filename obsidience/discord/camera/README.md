# Squanchbot Graph local camera

This optional producer presents the dedicated bot graph as a local camera named
`Squanchbot Graph`. The owner selects that camera in the normal Discord client.
It does not make the official bot account publish video, automate a user account,
or change Discord's selected devices. No audio device or speech pipeline is used.

The producer owns a separate headless Edge page at exactly
`http://127.0.0.1:8765/shell/knowledge/?surface=discord`, an ephemeral private
browser profile/debugging endpoint, and one FFmpeg producer for `/dev/video42`.
It captures only that page's viewport through Edge's DevTools Protocol. It never
opens the desktop, a screen recorder, the existing Edge profile or the native
Executive graph. It requires the dedicated graph surface's `discordGraph=ready`
and `discordGraphData=available` markers plus a canvas, and rechecks them before
each screenshot. The markers are presentation/data readiness, not proof of an
Agent turn or of what Discord viewers actually receive.

SwiftShader renders WebGL on the CPU. The unit additionally makes DRI and NVIDIA
device nodes inaccessible, so it cannot allocate graph VRAM on the RTX 4000 or
compete for either NVIDIA GPU. FFmpeg decodes/converts images on the CPU. This
keeps the user's graph content and rendering settings; actual 15-fps throughput
and CPU cost still require deployment measurement. No GPU/renderer was started
while preparing this component. It does not replace or restart the native graph
stage.

The default camera format is 1280x720, 15 fps, YUV420P; `--size 1920x1080` selects
1080p at the same cadence. Only the latest captured JPEG is retained. A slow camera
write has a two-second deadline, and a capture stall beyond two seconds stops the
producer. Dependency loss, navigation outside the exact graph page, unavailable
graph data and cancellation close the browser and encoder. The service does not
restart or reconnect in a loop. Configure the kernel device's timeout below so an
absent producer becomes a blank camera instead of retaining an old graph frame.

## Dependencies

Use the installed Microsoft Edge browser with bundled SwiftShader, Python with
`websockets`, FFmpeg and a matching-kernel `v4l2loopback` module. `v4l2-ctl` from
v4l-utils configures and verifies the camera. The producer redistributes none
of those system binaries and changes no global browser settings.

The selected device must be unused and the module must match the running kernel.
Inspect current device ownership before provisioning; never unload another
camera's module. Installation-specific versions and rollback belong in the local
installation record; upstream dependency provenance lives in `artifacts.lock.json`.

## Parent deployment commands

Run only after integrating the dedicated graph surface/data markers and these
files. Inspect `/sys/module/v4l2loopback` and `/dev/video42` first. The following
load command is for the currently unloaded module; do not unload an existing
loopback module that another producer owns.

```bash
sudo modprobe v4l2loopback devices=1 video_nr=42 card_label='Squanchbot Graph' exclusive_caps=1 max_buffers=2
v4l2-ctl --device=/dev/video42 --set-ctrl=timeout=1000
install -m 0644 obsidience/discord/systemd/obsidience-discord-camera.service "$HOME/.config/systemd/user/obsidience-discord-camera.service"
systemctl --user daemon-reload
systemctl --user start obsidience-discord-camera.service
v4l2-ctl --device=/dev/video42 --get-fmt-video
systemctl --user status obsidience-discord-camera.service
```

The owner is already a member of `video`; confirm the new device is writable by
that group. The script refuses a physical video device or a virtual node whose
name differs from `Squanchbot Graph`. Start the producer before selecting it in
Discord: `exclusive_caps=1` exposes it as a capture camera only while a producer
has established its format. The initial `frames_submitted` journal event means
FFmpeg accepted source bytes, not camera readback or Discord delivery acceptance.

For 1080p, install a user service override replacing ExecStart with the same
script and `--size 1920x1080`. Do not change desktop display resolution or the
owner's normal Edge flags/profile. Automatic start/module persistence is optional
and belongs to the parent deployment decision; this template is not enabled by
preparation. To stop, use `systemctl --user stop obsidience-discord-camera.service`.
Unloading/removing the dedicated loopback device requires closing its producer
and every consuming application first; never unload another camera's module.

After deployment, verify real V4L2 format/frame flow, per-process software-renderer
ownership and measured capture cadence, then let the owner select/preview the
camera in Discord. Installation status and a loaded HTML page cannot establish
those outcomes.

## Upstream contracts

- [Chromium SwiftShader](https://chromium.googlesource.com/chromium/src/+/main/docs/gpu/swiftshader.md)
  documents CPU rendering and the explicit trusted-page WebGL opt-in flags.
- [Microsoft Edge DevTools Protocol](https://learn.microsoft.com/en-us/microsoft-edge/devtools/protocol/)
  documents custom tooling clients; Edge matches Chromium's protocol.
- [Page.captureScreenshot](https://chromedevtools.github.io/devtools-protocol/tot/Page/#method-captureScreenshot)
  supplies own-page viewport images. This adapter uses no input commands.
- [v4l2loopback](https://github.com/v4l2loopback/v4l2loopback)
  documents the producer/capture capability transition and missing-input timeout.
