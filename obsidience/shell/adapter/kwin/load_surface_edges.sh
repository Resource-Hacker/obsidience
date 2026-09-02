#!/usr/bin/env bash
set -euo pipefail

adapter_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
script="${adapter_dir}/surface_edges.js"
runtime_dir="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
name_file="${runtime_dir}/obsidience-surface-edge-adapter.name"
ready_file="${runtime_dir}/obsidience-surface-edge-adapter.ready"
generation="$(sha256sum "$script" | cut -c1-12)"
base_name="dp4-edge-bridge-${generation}"

edge_loaded() {
  local active_name=""
  [[ -r "$name_file" && -r "$ready_file" ]] || return 1
  IFS= read -r active_name < "$name_file"
  [[ -n "$active_name" && "$(<"$ready_file")" == "ready" ]] || return 1
  [[ "$(qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.isScriptLoaded "$active_name" 2>/dev/null || true)" == "true" ]]
}

if [[ "${1:-}" == "--check" ]]; then
  edge_loaded
  exit
fi

for _ in {1..80}; do
  if qdbus6 org.kde.KWin /Scripting >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done

if edge_loaded && [[ "$(<"$name_file")" == "${base_name}-"* ]]; then
  exit 0
fi

previous_name=""
if [[ -r "$name_file" ]]; then
  IFS= read -r previous_name < "$name_file"
fi

failed_names=()
active_name=""
for attempt in 1 2; do
  name="${base_name}-$(date +%s%N)-${attempt}"
  rm -f -- "$ready_file"
  object_path="$(qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.loadScript "$script" "$name")"
  if [[ -z "$object_path" || "$object_path" == "false" ]]; then
    failed_names+=("$name")
    continue
  fi
  if [[ "$object_path" =~ ^[0-9]+$ ]]; then
    object_path="/Scripting/Script${object_path}"
  fi
  qdbus6 org.kde.KWin "$object_path" org.kde.kwin.Script.run >/dev/null

  for _ in {1..20}; do
    if [[ -r "$ready_file" ]] && \
       [[ "$(<"$ready_file")" == "ready" ]] && \
       [[ "$(qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.isScriptLoaded "$name" 2>/dev/null || true)" == "true" ]]; then
      active_name="$name"
      break 2
    fi
    sleep 0.1
  done
  failed_names+=("$name")
done

if [[ -z "$active_name" ]]; then
  for failed_name in "${failed_names[@]}"; do
    qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript "$failed_name" >/dev/null 2>&1 || true
  done
  echo "Obsidience Surface edge adapter did not execute its readiness handshake" >&2
  exit 1
fi

printf '%s\n' "$active_name" > "$name_file"
for stale_name in dp4-edge-bridge "$previous_name" "${failed_names[@]}"; do
  [[ -n "$stale_name" && "$stale_name" != "$active_name" ]] || continue
  qdbus6 org.kde.KWin /Scripting org.kde.kwin.Scripting.unloadScript "$stale_name" >/dev/null 2>&1 || true
done
