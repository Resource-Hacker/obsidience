#!/bin/sh
# Obsidience's one resident text embedder: EmbeddingGemma 2 (text-only BF16
# GGUF) behind llama-server's OpenAI-compatible /v1/embeddings, CPU only.
# The Harness Knowledge index and Hindsight memory are its only clients and
# apply EmbeddingGemma's task prefixes themselves; the server embeds as given.
# Same pinned engine as llm.sh; CUDA is hidden, so no GPU is ever touched.
LLAMA=/var/lib/ai/opt/llama.cpp-b11509-obsidience-admission-20261008
MODEL=${OBSIDIENCE_EMBED_MODEL:-/var/lib/ai/models/obsidience-embeddinggemma-2/embeddinggemma-2-BF16.gguf}
set --
# Browsers can reach loopback ports; inference requires the model service key
# (health stays public). The Harness and Hindsight send the same key.
if [ -n "${CREDENTIALS_DIRECTORY:-}" ] && [ -r "$CREDENTIALS_DIRECTORY/obsidience-model-api-key" ]; then
  set -- "$@" --api-key-file "$CREDENTIALS_DIRECTORY/obsidience-model-api-key"
fi
# One 8,192-token sequence per micro-batch (the model's whole window; a
# non-causal embedding must fit one ubatch). BF16 runs natively on the 9950X
# (avx512_bf16) and matched sentence-transformers float32 at cosine 1.00000.
exec env CUDA_VISIBLE_DEVICES= \
  LD_LIBRARY_PATH="$LLAMA/lib:$LD_LIBRARY_PATH" \
  "$LLAMA/bin/llama-server" \
  -m "$MODEL" --alias embeddinggemma-2-bf16-68bae29d \
  --embeddings --pooling mean --device none -ngl 0 \
  --threads 8 --threads-batch 8 -c 8192 -b 8192 -ub 8192 --parallel 1 --cache-ram 0 \
  --host 127.0.0.1 --port 8791 --no-webui "$@"
