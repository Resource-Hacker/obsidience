#!/bin/sh
# Obsidience's own model server (llama.cpp) on :8089, RTX 4000 Ada.
LLAMA=/var/lib/ai/opt/llama.cpp-b10078
MODEL=/var/lib/ai/models/jarvis-fixed/gemma-4-26b-a4b-it-qat-7b92b5b2/gemma-4-26B-A4B-it-qat-UD-Q4_K_XL.gguf
exec env CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=1 \
  LD_LIBRARY_PATH="$LLAMA/lib:$LD_LIBRARY_PATH" \
  "$LLAMA/bin/llama-server" \
  -m "$MODEL" --alias obsidience-gemma \
  --host 127.0.0.1 --port 8089 -ngl 99 -c 16384 --jinja
