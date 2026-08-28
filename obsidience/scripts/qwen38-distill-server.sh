#!/bin/sh
# Fully GPU-resident 4080 specialist. The Q8 KV cache and embedded MTP head
# preserve a useful 32K context without offloading any transformer layer.
LLAMA=/var/lib/ai/opt/llama.cpp-b21e4de
MODEL=/var/lib/ai/models/obsidience-qwen38-9b-distill/Qwen3.8-9B-Distill-Heretic-Uncensored-Q8_0.gguf
LAUNCH=/home/wissenschafter/Projects/obsidience/obsidience/state/model-launch/obsidience-qwen38-9b-distill.json
GPU_UUIDS=$(jq -er '.gpu_uuids | join(",")' "$LAUNCH") || exit 64
CTX=$(jq -er '.context_tokens' "$LAUNCH") || exit 64

exec env \
  CUDA_DEVICE_ORDER=PCI_BUS_ID \
  CUDA_VISIBLE_DEVICES="$GPU_UUIDS" \
  LD_LIBRARY_PATH="$LLAMA/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
  "$LLAMA/bin/llama-server" \
  --model "$MODEL" \
  --alias obsidience-qwen38-9b-distill \
  --host 127.0.0.1 \
  --port 8092 \
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
  --split-mode none \
  --spec-type draft-mtp \
  --spec-draft-n-max 3 \
  --spec-draft-n-min 0 \
  --jinja \
  --no-context-shift \
  --metrics \
  --no-webui
