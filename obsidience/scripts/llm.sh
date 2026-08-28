#!/bin/sh
# Obsidience's responsive Gemma server. The hardware manager writes the exact
# GPU/context launch profile before systemd starts this service.
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PRODUCT_ROOT=$(dirname -- "$SCRIPT_DIR")
LLAMA=/var/lib/ai/opt/llama.cpp-b10078
MODEL=${OBSIDIENCE_MODEL:-"$PRODUCT_ROOT/state/models/executive.gguf"}
LAUNCH="$PRODUCT_ROOT/state/model-launch/obsidience-gemma.json"
GPU_UUIDS=$(jq -er '.gpu_uuids | join(",")' "$LAUNCH") || exit 64
CTX=$(jq -er '.context_tokens' "$LAUNCH") || exit 64
exec env CUDA_DEVICE_ORDER=PCI_BUS_ID \
  CUDA_VISIBLE_DEVICES="$GPU_UUIDS" \
  LD_LIBRARY_PATH="$LLAMA/lib:$LD_LIBRARY_PATH" \
  "$LLAMA/bin/llama-server" \
  -m "$MODEL" --alias obsidience-gemma \
  --host 127.0.0.1 --port 8089 -ngl 99 -c "$CTX" --jinja
