#!/bin/sh
# Zynerji HOMEUSER profile. Obsidience's optimized Qwen vLLM 0.27.1 build
# already carries the quantized Qwen3.5 embedding and lm_head plumbing this
# checkpoint requires, so share the proven engine instead of compiling a
# second multi-gigabyte CUDA runtime.
VLLM=/var/lib/ai/src/obsidience-qwen38-vllm/venv/bin/vllm
MODEL=/var/lib/ai/models/obsidience-qwen38-homeuser
CUDA_WHEEL_LIB=/var/lib/ai/src/obsidience-qwen38-vllm/venv/lib/python3.12/site-packages/nvidia/cu13/lib
LAUNCH=/home/wissenschafter/Projects/obsidience/obsidience/state/model-launch/obsidience-qwen38-27b-homeuser.json
GPU_UUIDS=$(jq -er '.gpu_uuids | join(",")' "$LAUNCH") || exit 64
GPU_COUNT=$(jq -er '.gpu_uuids | length' "$LAUNCH") || exit 64
GPU_UTIL=$(jq -er '.gpu_memory_utilization' "$LAUNCH") || exit 64
MAX_LEN=$(jq -er '.context_tokens' "$LAUNCH") || exit 64
MAX_SEQS=$(jq -er '.max_num_seqs' "$LAUNCH") || exit 64

set -- \
  serve "$MODEL" \
  --served-model-name obsidience-qwen38-27b-homeuser \
  --host 127.0.0.1 \
  --port 8091 \
  --tensor-parallel-size "$GPU_COUNT" \
  --max-model-len "$MAX_LEN" \
  --kv-cache-dtype fp8 \
  --gpu-memory-utilization "$GPU_UTIL" \
  --max-num-batched-tokens 2048 \
  --max-num-seqs "$MAX_SEQS"

if [ "$GPU_COUNT" -gt 1 ]; then
  set -- "$@" --disable-custom-all-reduce
fi

exec env \
  CUDA_DEVICE_ORDER=PCI_BUS_ID \
  CUDA_VISIBLE_DEVICES="$GPU_UUIDS" \
  NCCL_P2P_DISABLE=1 \
  LD_LIBRARY_PATH="$CUDA_WHEEL_LIB:/opt/cuda/lib64" \
  HF_HUB_OFFLINE=1 \
  TRANSFORMERS_OFFLINE=1 \
  "$VLLM" "$@"
