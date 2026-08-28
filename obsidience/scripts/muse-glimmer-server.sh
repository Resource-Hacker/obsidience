#!/bin/sh
# Muse Glimmer task model. One-card mode is conservative text-only; assigning
# both cards adds the official vision projector and lossless DFlash drafter.
LLAMA=/var/lib/ai/opt/llama.cpp-b21e4de
ROOT=/var/lib/ai/models/obsidience-muse-glimmer-30b
MODEL="$ROOT/Muse-Glimmer-30B-KQuant-17GB-Q4_K_M.gguf"
LAUNCH=/home/wissenschafter/Projects/obsidience/obsidience/state/model-launch/obsidience-muse-glimmer-30b.json
GPU_UUIDS=$(jq -er '.gpu_uuids | join(",")' "$LAUNCH") || exit 64
CTX=$(jq -er '.context_tokens' "$LAUNCH") || exit 64
GPU_COUNT=$(jq -er '.gpu_uuids | length' "$LAUNCH") || exit 64

set -- \
  --model "$MODEL" \
  --alias obsidience-muse-glimmer-30b \
  --host 127.0.0.1 \
  --port 8095 \
  --ctx-size "$CTX" \
  --parallel 1 \
  --threads 16 \
  --threads-batch 24 \
  --batch-size 2048 \
  --ubatch-size 512 \
  --flash-attn on \
  --cache-type-k q8_0 \
  --cache-type-v q8_0 \
  --gpu-layers 99 \
  --jinja \
  --temp 1.0 \
  --top-p 0.95 \
  --top-k 64 \
  --no-context-shift \
  --metrics \
  --no-webui

if [ "$GPU_COUNT" -gt 1 ]; then
  set -- "$@" \
    --split-mode layer \
    --mmproj "$ROOT/mmproj-Muse-Glimmer-30B-Q4_K_M.gguf" \
    --model-draft "$ROOT/dflash-Muse-Glimmer-30B-Q4_K_M.gguf" \
    --gpu-layers-draft 99
else
  set -- "$@" --split-mode none
fi

exec env \
  CUDA_DEVICE_ORDER=PCI_BUS_ID \
  CUDA_VISIBLE_DEVICES="$GPU_UUIDS" \
  LD_LIBRARY_PATH="$LLAMA/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
  "$LLAMA/bin/llama-server" "$@"
