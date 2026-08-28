#!/bin/sh
# Portable specialist runtime derived from syv-ai/qwen38-27b-rtx3090. This
# profile needs both GPUs; the hardware manager owns displacement/restoration.
STACK=/var/lib/ai/src/obsidience-qwen38-vllm
MODEL=/var/lib/ai/models/obsidience-qwen38-vllm/Qwen3.8-27B-Uncensored-W4A16
LAUNCH=/home/wissenschafter/Projects/obsidience/obsidience/state/model-launch/obsidience-qwen38-27b-w4a16.json
GPU_UUIDS=$(jq -er '.gpu_uuids | join(",")' "$LAUNCH") || exit 64
GPU_COUNT=$(jq -er '.gpu_uuids | length' "$LAUNCH") || exit 64
GPU_UTIL=$(jq -er '.gpu_memory_utilization' "$LAUNCH") || exit 64
MAX_LEN=$(jq -er '.context_tokens' "$LAUNCH") || exit 64
MAX_SEQS=$(jq -er '.max_num_seqs' "$LAUNCH") || exit 64

exec env \
  CUDA_DEVICE_ORDER=PCI_BUS_ID \
  CUDA_VISIBLE_DEVICES="$GPU_UUIDS" \
  NCCL_P2P_DISABLE=1 \
  HOST=127.0.0.1 \
  PORT=8082 \
  SERVED_MODEL_NAME=obsidience-qwen38-27b-w4a16 \
  MODEL="$MODEL" \
  GPU_UTIL="$GPU_UTIL" \
  CTX=long \
  MAX_LEN="$MAX_LEN" \
  MAX_SEQS="$MAX_SEQS" \
  SPEC=mtp \
  DRAFT_TOKENS=2 \
  PREFIX_CACHE=1 \
  EXTRA_ARGS="--tensor-parallel-size $GPU_COUNT --dtype float16 --disable-custom-all-reduce" \
  /usr/bin/bash "$STACK/single-user/start_qwen.sh"
