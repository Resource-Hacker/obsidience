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

Edge renders WebGL through ANGLE/Vulkan on the AMD iGPU selected by the installation.
The unit masks the host `/dev/dri` tree with a private temporary filesystem and
binds only its selected AMD card and render node; NVIDIA device nodes remain
inaccessible. The launcher verifies both DRI nodes against their actual sysfs PCI
identity and AMD vendor before starting Edge. The private unit drop-in sets
`OBSIDIENCE_DISCORD_CAMERA_GPU_PCI`, `OBSIDIENCE_DISCORD_CAMERA_GPU_NODES`
(card then render-node basename), and matching `BindPaths`. A changed device mapping fails
closed and requires updating the unit and launcher together. Direct launches
outside this device namespace are refused.

The browser loads only the installed Radeon Vulkan ICD, selects that PCI device,
and disables software rasterizer fallback. After the graph mounts, the launcher
checks its existing WebGL2 renderer and requires AMD/Radeon/RADV, rejecting NVIDIA,
SwiftShader and llvmpipe. It emits only a fixed `renderer_verified` receipt, never
raw renderer/page data. Hardware failure stops the producer; it does not silently
switch back to an unbounded software renderer. Chromium's sandbox remains enabled.
FFmpeg decodes/converts images on the CPU with one decoder thread, one filter
thread and one rawvideo encoder thread. `TasksMax=192`, picture settings and 15-fps
cadence stay unchanged. Actual throughput and resource cost require deployment
measurement; no renderer was started while preparing this change.

The default camera format is 1280x720, 15 fps, YUV420P; `--size 1920x1080` selects
1080p at the same cadence. Only the latest captured JPEG is retained. A slow camera
write has a two-second deadline, and a capture stall beyond two seconds stops the
producer. Dependency loss, navigation outside the exact graph page, unavailable
graph data and cancellation close the browser and encoder. The service does not
restart or reconnect in a loop. Configure the kernel device's timeout below so an
absent producer becomes a blank camera instead of retaining an old graph frame.

## Dependencies

Use the installed Microsoft Edge browser, Mesa `vulkan-radeon` providing
`/usr/share/vulkan/icd.d/radeon_icd.json`, Python with `websockets`, FFmpeg and a
matching-kernel `v4l2loopback` module. `v4l2-ctl` from
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
v4l2-ctl --device=/dev/video42 --set-ctrl=timeout=1000 --set-output-parm=15
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
has established its format. The `camera_ready` journal event and systemd READY notification follow a bounded
readback of the exact V4L2 device label, capture capability, YU12 format, selected
size and 15-fps setting. They do not establish a captured frame or Discord delivery
acceptance. The initial format check stops after ten seconds; it does not become
ongoing device polling.

For 1080p, install a user service override replacing ExecStart with the same
script and `--size 1920x1080`. Do not change desktop display resolution or the
owner's normal Edge flags/profile. Automatic start/module persistence is optional
and belongs to the parent deployment decision; this template is not enabled by
preparation. To stop, use `systemctl --user stop obsidience-discord-camera.service`.
Unloading/removing the dedicated loopback device requires closing its producer
and every consuming application first; never unload another camera's module.

After deployment, verify real V4L2 format/frame flow, AMD-only device visibility
and open GPU descriptors in the service namespace, task usage and measured capture
cadence, then let the owner select/preview the
camera in Discord. Installation status and a loaded HTML page cannot establish
those outcomes.

## Upstream contracts

- [Chromium headless GPU hardware](https://chromium.googlesource.com/chromium/src/+/main/docs/gpu/using-gpu-hardware-in-headless-chrome.md)
  documents `--enable-gpu` and ANGLE Vulkan for headless Linux without X11.
- [Chrome headless Vulkan](https://developer.chrome.com/blog/supercharge-web-ai-testing)
  documents Vulkan enablement and the surface-free rendering flag.
- [Mesa device selection](https://docs.mesa3d.org/envvars.html#dri-prime)
  documents PCI selection and the Vulkan `!` restriction to the selected device.
- [systemd filesystem namespaces](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html#BindPaths=)
  documents private bind mounts beneath a `TemporaryFileSystem=...:ro` mount.
- [Microsoft Edge DevTools Protocol](https://learn.microsoft.com/en-us/microsoft-edge/devtools/protocol/)
  documents custom tooling clients; Edge matches Chromium's protocol.
- [Page.captureScreenshot](https://chromedevtools.github.io/devtools-protocol/tot/Page/#method-captureScreenshot)
  supplies own-page viewport images. This adapter uses no input commands.
- [v4l2loopback](https://github.com/v4l2loopback/v4l2loopback)
  documents the producer/capture capability transition and missing-input timeout.

## Failure diagnosis

Browser stderr is consumed through a bounded in-memory classifier and never
printed or retained as raw lines. The journal reports only fixed failure codes
(for example `browser_profile_read_only` or `browser_sandbox_unavailable`) and a
numeric browser exit code where available. Browser profiles, configuration and
cache belong to the same ephemeral runtime directory: Edge Crashpad uses
`XDG_CONFIG_HOME` even when `--user-data-dir` is supplied, so a read-only home
requires this explicit private XDG location. No browser sandbox is disabled.

The parent should perform one bounded native-service start after integration,
inspect `/proc/<camera-main-pid>/root/dev/dri` for exactly the two configured AMD nodes,
and inspect the service descendants' open GPU descriptors for those AMD devices
only. Require `renderer_verified` with `amd_vulkan`, then `camera_ready` and real
V4L2 frame flow at the selected size/15 fps. Sample the service's `TasksCurrent`,
`TasksMax`, CPU delta and cgroup `pids.events` during that same bounded run;
`pids.events:max` establishes whether the old EAGAIN was a task-limit denial.
Do not infer frame delivery or physical viewer acceptance from those startup
receipts. If hardware initialization fails, retain the fixed failure code and
stop; do not raise task limits or enable an implicit software fallback.

The producer sets the loopback output time-per-frame explicitly before opening
FFmpeg. FFmpeg output `-r` paces frames but does not update that kernel setting;
leaving its default would advertise 30 fps for a 15-fps producer.
