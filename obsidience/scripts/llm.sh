#!/bin/sh
# Obsidience's responsive Gemma server. The hardware manager writes the exact
# GPU/context launch profile before systemd starts this service.
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PRODUCT_ROOT=$(dirname -- "$SCRIPT_DIR")
# Pinned b11509 with exact input-budget admission plus Gemma 4 schema-constrained
# Tool arguments (2026-10-09; artifacts.lock.json llama_cpp_executive_g4grammar), plus
# five tensor-split patches (2026-10-18; even expert split, vocab-split tied head,
# draft sampling, all-reduce pool, masked NextN), a size-selected hybrid all-reduce, device
# top-64 sampling candidates and one merged dense+MoE all-reduce per layer (patches 01-08,
# /var/lib/ai/src/gpu-tuning-20261018/llama-tp/patches; outputs identical to tp5, decode -5..9%).
# Rollback: LLAMA=/var/lib/ai/opt/llama.cpp-b11509-obsidience-admission-g4grammar-tp5-20261018
LLAMA=/var/lib/ai/opt/llama.cpp-b11509-obsidience-admission-g4grammar-tp6-20261018
MODEL=${OBSIDIENCE_MODEL:-"$PRODUCT_ROOT/state/models/executive.gguf"}
LAUNCH="$PRODUCT_ROOT/state/model-launch/obsidience-gemma.json"
GPU_UUIDS=$(jq -er '.gpu_uuids | join(",")' "$LAUNCH") || exit 64
GPU_COUNT=$(jq -er '.gpu_uuids | length' "$LAUNCH") || exit 64
SPLIT_MODE=$(jq -er '.split_mode // "layer" | select(. == "layer" or . == "tensor")' "$LAUNCH") || exit 64
CTX=$(jq -er '.context_tokens' "$LAUNCH") || exit 64
PARALLEL=$(jq -er '.max_num_seqs | select(type == "number") | select(. == floor and . >= 1 and . <= 32)' "$LAUNCH") || exit 64
MMPROJ=$(jq -er '.projector_path // empty' "$LAUNCH") || exit 64
TEMPLATE=$(jq -r '.chat_template_path // empty' "$LAUNCH") || exit 64
MTP=$(jq -r '.mtp_path // empty' "$LAUNCH") || exit 64
set --
if [ -n "$TEMPLATE" ]; then
  [ -r "$TEMPLATE" ] || exit 66
  set -- "$@" --chat-template-file "$TEMPLATE"
fi
if [ -n "$MTP" ]; then
  [ -r "$MTP" ] || exit 66
  MTP_TOKENS=$(jq -er '.mtp_tokens | select(type == "number") | select(. == floor and . >= 1 and . <= 16)' "$LAUNCH") || exit 64
  set -- "$@" --spec-draft-model "$MTP" --spec-type draft-mtp \
    --spec-draft-n-max "$MTP_TOKENS" --spec-draft-n-min 0 --spec-draft-ngl 99
fi
# CUDA_VISIBLE_DEVICES lists the launch's GPUs in CUDA order (CUDA0 = first: the
# CPU-attached RTX 4000, which holds the projector). The split stays even: speech
# shares the chipset RTX 4000, and llama.cpp's default split by free memory would
# leave the tensor-mode peer waiting. One GPU keeps the single-device layout.
if [ "$GPU_COUNT" -gt 1 ]; then
  set -- "$@" --split-mode "$SPLIT_MODE" --tensor-split 1,1
  if [ "$SPLIT_MODE" = tensor ]; then
    # Two RTX 4000s (2026-10-18): small (decode) all-reduces use the internal pinned-host
    # path, large (prefill) ones NCCL over shared memory with P2P off: decode -1.1 ms/step
    # at NCCL prefill speed (patch 06). P2P into the chipset card is capped at ~2 GB/s.
    export NCCL_P2P_DISABLE=1 GGML_CUDA_ALLREDUCE=hybrid
  fi
fi
# Browsers can reach loopback ports; inference requires the service key
# (health and model listings stay public). The Harness sends the same key.
if [ -n "${CREDENTIALS_DIRECTORY:-}" ] && [ -r "$CREDENTIALS_DIRECTORY/obsidience-model-api-key" ]; then
  set -- "$@" --api-key-file "$CREDENTIALS_DIRECTORY/obsidience-model-api-key"
fi
# Checkpoints every >=1024 tokens: since #28302 (b11xxx) spacing-based eviction
# only applies when the 32-checkpoint list is full, so fewer batch splits cut
# cold prefill ~42% (26.9 -> 15.6 s at 39.7K) with no warm-turn penalty (2026-10-08).
# Retain the selector and several Task prefixes across ordinary work changes.
# Their SWA snapshots exceed the server's default 8 GiB RAM cache together.
exec env CUDA_DEVICE_ORDER=PCI_BUS_ID \
  CUDA_VISIBLE_DEVICES="$GPU_UUIDS" \
  LD_LIBRARY_PATH="$LLAMA/lib:$LD_LIBRARY_PATH" \
  "$LLAMA/bin/llama-server" \
  -m "$MODEL" --alias obsidience-gemma \
  --mmproj "$MMPROJ" --mmproj-offload --image-max-tokens 512 \
  --host 127.0.0.1 --port 8089 -ngl 99 -c "$CTX" --parallel "$PARALLEL" \
  --batch-size 4096 --ubatch-size 1024 --flash-attn on \
  --checkpoint-min-step 1024 --cache-ram 16384 --no-reasoning-preserve \
  --jinja "$@"
