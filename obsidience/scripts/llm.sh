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
PARALLEL=$(jq -er '.max_num_seqs | select(type == "number") | select(. == floor and . >= 1 and . <= 32)' "$LAUNCH") || exit 64
MMPROJ=$(jq -er '.projector_path // empty' "$LAUNCH") || exit 64
# Keep the compiler's fixed-prefix message checkpoint across Tool follow-ups.
# b10078's 8192-token spacing evicts that boundary from ordinary ~6K packets.
# The upstream 32-checkpoint bound remains unchanged; this does not expand KV.
exec env CUDA_DEVICE_ORDER=PCI_BUS_ID \
  CUDA_VISIBLE_DEVICES="$GPU_UUIDS" \
  LD_LIBRARY_PATH="$LLAMA/lib:$LD_LIBRARY_PATH" \
  "$LLAMA/bin/llama-server" \
  -m "$MODEL" --alias obsidience-gemma \
  --mmproj "$MMPROJ" --mmproj-offload --image-max-tokens 512 \
  --host 127.0.0.1 --port 8089 -ngl 99 -c "$CTX" --parallel "$PARALLEL" \
  --checkpoint-min-step 0 --jinja
