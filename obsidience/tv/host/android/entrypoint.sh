#!/bin/bash
# Obsidience TV Android: an unmodified Waydroid inside its own namespaces.
set -euo pipefail
shopt -s nullglob

# 1. cgroup v2: empty this namespace's root so LXC can delegate controllers below it.
#    The name matters: LXC (as root) takes PID 1's cgroup as its base and strips a trailing
#    "/init.scope", so the payload lands at this namespace's root, never the host's.
mkdir -p /sys/fs/cgroup/init.scope
xargs -rn1 < /sys/fs/cgroup/cgroup.procs > /sys/fs/cgroup/init.scope/cgroup.procs || :
sed -e 's/ / +/g' -e 's/^/+/' < /sys/fs/cgroup/cgroup.controllers > /sys/fs/cgroup/cgroup.subtree_control

# 2. Devices: /dev here is the container's own copy. Android must never get host input,
#    cameras, sound cards, the NVIDIA cards, or binder nodes copied from the host.
render=$(basename "$(echo /sys/bus/pci/devices/"$IGPU_PCI"/drm/renderD*)")
for n in /dev/uhid /dev/uinput /dev/input /dev/hidraw* /dev/video* /dev/media* /dev/fb* \
         /dev/snd /dev/nvidia* /dev/binderfs /dev/binder /dev/hwbinder /dev/vndbinder; do
  umount -R "$n" 2>/dev/null || :
  rm -rf "$n"
done
for n in /dev/dri/card* /dev/dri/renderD*; do [ "$n" = "/dev/dri/$render" ] || rm -f "$n"; done
{ [ ! -e /dev/uhid ] && [ ! -e /dev/uinput ] && [ -c "/dev/dri/$render" ]; } || exit 1
# The host creates loop nodes on demand in its own devtmpfs; this /dev needs them made. Loop
# numbers are host-wide: each running Android holds about 42 of them for its APEX images, so
# the two image mounts here get whatever numbers are free above those.
for i in $(seq 0 255); do [ -e "/dev/loop$i" ] || mknod -m 0660 "/dev/loop$i" b 7 "$i"; done

# 3. Binder: a new binderfs instance that exists only in this mount namespace.
mkdir /dev/binderfs
mount -t binder binder /dev/binderfs
for d in binder hwbinder vndbinder; do
  [ -c "/dev/binderfs/$d" ]
  chmod 0666 "/dev/binderfs/$d"
  ln -s "/dev/binderfs/$d" "/dev/$d"
done

# 4. The session user. The image runs its composer as the session's user ("user host") without
#    capabilities, and the TV compositor's socket is owner-only, so the session must run as that
#    socket's owner. The container manager stays root.
[ -S /run/tv/wayland-0 ]
uid=$(stat -c %u /run/tv/wayland-0) gid=$(stat -c %g /run/tv/wayland-0)
export HOME=/var/lib/waydroid/home XDG_DATA_HOME=/var/lib/waydroid/home
if ! getent passwd "$uid" >/dev/null; then
  getent group "$gid" >/dev/null || groupadd -g "$gid" tv
  useradd -u "$uid" -g "$gid" -M -d "$HOME" -s /usr/bin/nologin tv
fi
install -d -o "$uid" -g "$gid" "$HOME"
chown "$uid:$gid" /run/tv
as_user() { setpriv --reuid="$uid" --regid="$gid" --clear-groups "$@"; }

# 5. Buses private to this container, never the host's. The session sees only the TV
#    compositor and the TV audio server.
mkdir -p /run/dbus
dbus-uuidgen --ensure=/etc/machine-id
dbus-daemon --system --fork
export XDG_RUNTIME_DIR=/run/tv WAYLAND_DISPLAY=wayland-0 PULSE_RUNTIME_PATH=/run/tv/pulse
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/tv/bus
as_user dbus-daemon --session --address="$DBUS_SESSION_BUS_ADDRESS" --fork

# 6. First run: initialise from the read-only images (no download), then set properties.
if [ ! -f /var/lib/waydroid/waydroid.cfg ]; then
  waydroid init -f
  python3 - <<'PY'
import configparser
path = "/var/lib/waydroid/waydroid.cfg"
cfg = configparser.ConfigParser()
cfg.read(path)
if "properties" not in cfg:
    cfg["properties"] = {}
cfg["properties"].update({
    "atv.setup.bt_remote_pairing": "false",
    "persist.waydroid.suspend": "false",
})
with open(path, "w") as f:
    cfg.write(f)
PY
  waydroid upgrade -o
fi
# Render-node numbers can change across boots; regenerate the node list when they do.
grep -q "/dev/dri/$render " /var/lib/waydroid/lxc/waydroid/config_nodes || waydroid upgrade -o

# 7. Container manager, ADB relay to Android's fixed address, then the full-screen session.
stop() { as_user waydroid session stop 2>/dev/null || :; waydroid container stop 2>/dev/null || :; }
trap stop EXIT INT TERM
waydroid container start &
for _ in $(seq 120); do
  busctl --system status id.waydro.Container >/dev/null 2>&1 && break
  sleep 0.25
done
socat TCP-LISTEN:5555,fork,reuseaddr TCP:192.168.240.112:5555 &
as_user waydroid show-full-ui &
wait $!
