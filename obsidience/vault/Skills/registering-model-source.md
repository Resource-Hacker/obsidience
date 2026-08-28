---
title: Register model Source
kind: skill
tool: '[[Tools/model.source]]'
---

Call `model.source` with the exact registered `model_id` before relying on
an artifact.

- Verify that the returned fingerprint and Source path are present.
- Treat the manifest as immutable artifact material, not accepted Knowledge.
- Do not copy model weights into Markdown or create a Knowledge Article for the
  binary.
- If the fingerprint changes, characterize the revision as new evidence rather
  than overwriting an earlier Source record.
