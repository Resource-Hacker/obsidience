---
type: tool
title: source.handoff
description: Return one self-contained finding as immutable Source Inbox evidence
  with exactly title and content containing source:// citations.
obsidience:
  binding: capability:source.handoff
  source: obsidience/harness/capabilities/source/handoff.py
---

## Runtime

Return one self-contained finding as immutable Source Inbox evidence with exactly title and content containing source:// citations. The controller verifies research provenance and required read receipts. A handoff is not wiki acceptance; Curator publication remains a separate outcome.

## Reference

A Feed `Tasks/research/distill` execution must first read its complete activating Source and cite it in the handoff. Its controller retains the captured Feed/destination binding in the immutable Inbox. Exactly one handoff is allowed per Distill execution: exact retries reuse it; a changed retry is rejected. Source text cannot select a destination or publication policy.

Deliver one cited Darwin synthesis to the physical Source Inbox. Only an actual Darwin `Tasks/research/...` execution may use this Tool; identity comes from the controller.

Use `{"title":str,"content":str}`. Title is 1–300 characters; self-contained Markdown content is 1–500,000 characters with at least one exact resolving `source://<uuid>` citation. Invalid arguments, citations or persistence produce `Source handoff rejected` without partial delivery.

All citations resolve before an immutable file is written under `obsidience/evidence/inbox/`. A new handoff emits `source.inbox` once for Alexandria; exact duplicates reuse the handoff. Success reports `dropped` or `already present`, path, stable citation, hash and event count. This Tool creates neither Knowledge nor Review and never writes the Vault.
