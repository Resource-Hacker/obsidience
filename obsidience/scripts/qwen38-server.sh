#!/bin/sh
# Exact OrcaRouter Q8 quality profile. The hardware manager supplies both GPUs
# and restores displaced defaults after the Task.
LLAMA=/var/lib/ai/opt/llama.cpp-b21e4de
MODEL=/var/lib/ai/models/obsidience-qwen38-27b-q8/Qwen3.8-27B-Uncensored-Q8_0.gguf
LAUNCH=/home/wissenschafter/Projects/obsidience/obsidience/state/model-launch/obsidience-qwen38-27b-q8.json
GPU_UUIDS=$(jq -er '.gpu_uuids | join(",")' "$LAUNCH") || exit 64
CTX=$(jq -er '.context_tokens' "$LAUNCH") || exit 64

exec env \
  CUDA_DEVICE_ORDER=PCI_BUS_ID \
  CUDA_VISIBLE_DEVICES="$GPU_UUIDS" \
  LD_LIBRARY_PATH="$LLAMA/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
  "$LLAMA/bin/llama-server" \
  --model "$MODEL" \
  --alias obsidience-qwen38-27b-q8 \
  --host 127.0.0.1 \
  --port 8090 \
  --ctx-size "$CTX" \
  --parallel 1 \
  --threads 16 \
  --threads-batch 24 \
  --batch-size 2048 \
  --ubatch-size 512 \
  --flash-attn on \
  --cache-type-k q8_0 \
  --cache-type-v q8_0 \
  --gpu-layers auto \
  --split-mode layer \
  --fit on \
  --fit-target 768,768 \
  --fit-ctx "$CTX" \
  --spec-type draft-mtp \
  --spec-draft-n-max 2 \
  --spec-draft-n-min 0 \
  --jinja \
  --no-context-shift \
  --metrics \
  --no-webui
