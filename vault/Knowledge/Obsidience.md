---
title: Obsidience
kind: note
---
Obsidience is a graph-native agent harness: a plain Obsidian vault plus a
small executor. Tasks resolve their assignee charter and mandatory runbook
through exact wikilinks (edges dispatch); hybrid retrieval assembles each
session's briefing (vectors inform). Agents cannot write the vault — they
stage proposals in `_staging/` for owner review; approvals and receipts are
git-committed. The local LLM is Gemma via llama.cpp; STT is faster-whisper;
TTS is kokoro-js in the desktop app.
