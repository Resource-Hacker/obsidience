---
title: Obsidience
kind: note
---
Obsidience is a graph-native agent harness: a plain Obsidian vault plus a
small interpreter. Four authoring primitives — recursive [[Tasks/maintain-vault|tasks]],
procedural runbooks, skills (reusable tool knowledge), and executable tools —
resolve through exact wikilinks (edges dispatch); hybrid retrieval assembles
each session's briefing (vectors inform). Sessions may invoke only the tools
their skills grant. Agents stage proposals in `_staging/` for owner review;
approvals and receipts are git-committed. LLM: local Gemma via llama.cpp.
Voice: faster-whisper STT, kokoro-js TTS.
