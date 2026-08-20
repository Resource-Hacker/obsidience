#!/bin/sh
# Obsidience dev build: harness daemon + Electron UI (HMR).
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PYTHONPATH="$ROOT/harness"
"$ROOT/.venv/bin/python" -m obsidience serve &
HARNESS_PID=$!
trap 'kill $HARNESS_PID 2>/dev/null' EXIT INT TERM
cd "$ROOT/ui" && pnpm dev
