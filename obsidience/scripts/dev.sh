#!/bin/sh
# Obsidience dev build: harness daemon + Electron UI (HMR).
PRODUCT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT_ROOT="$(dirname "$PRODUCT_ROOT")"
export DISPLAY=:2
unset WAYLAND_DISPLAY SESSION_MANAGER
export GDK_BACKEND=x11
export QT_QPA_PLATFORM=xcb
export XDG_SESSION_TYPE=x11
export ELECTRON_OZONE_PLATFORM_HINT=x11
export XCURSOR_SIZE=48
export PYTHONPATH="$PROJECT_ROOT"
"$PROJECT_ROOT/.venv/bin/python" -m obsidience.harness serve &
HARNESS_PID=$!
trap 'kill $HARNESS_PID 2>/dev/null' EXIT INT TERM
cd "$PRODUCT_ROOT/ui" && pnpm dev
