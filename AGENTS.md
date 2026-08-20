# Obsidience — assistant guidance

This is the GREENFIELD graph-native harness experiment (parallel to the
Hermes-plugin conversion happening elsewhere). Read DESIGN.md first; its Laws
section is binding. Rules for working here:

- Do NOT modify the legacy stacks from this project (~/.local/src/opendex-hermes,
  /var/lib/ai/src/*, ~/.hermes) — copy-in only, and note provenance.
- Everything under ui/src/components/themes/jarvis/ and ui/src/main/tts/ is
  copied from HEREBRUM (2026-08-20) and then adapted; keep adaptations minimal
  and prefer thin hosts over editing the copied engine files.
- The vault is user-owned: never hand-edit accepted notes from automation;
  agent writes go through _staging/ + review. The harness alone writes
  Receipts/ and task status fields.
- Keep it a dev build: small modules, no ceremony, no new frameworks.
