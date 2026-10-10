#!/bin/sh
# Obsidience's responsive Gemma server. The hardware manager writes the exact
# GPU/context launch profile before systemd starts this service.
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PRODUCT_ROOT=$(dirname -- "$SCRIPT_DIR")
# Pinned b11509 with exact input-budget admission plus Gemma 4 schema-constrained
# Tool arguments (2026-10-09; artifacts.lock.json llama_cpp_executive_g4grammar).
# Rollback: LLAMA=/var/lib/ai/opt/llama.cpp-b11509-obsidience-admission-20261008
LLAMA=/var/lib/ai/opt/llama.cpp-b11509-obsidience-admission-g4grammar-20261009
MODEL=${OBSIDIENCE_MODEL:-"$PRODUCT_ROOT/state/models/executive.gguf"}
LAUNCH="$PRODUCT_ROOT/state/model-launch/obsidience-gemma.json"
GPU_UUIDS=$(jq -er '.gpu_uuids | join(",")' "$LAUNCH") || exit 64
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
