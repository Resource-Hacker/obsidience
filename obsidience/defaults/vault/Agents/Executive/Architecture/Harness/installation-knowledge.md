---
type: knowledge
title: Installation knowledge and publication
sources:
- resource: obsidience/defaults/README.md
- resource: obsidience/harness/knowledge/vault.py
obsidience:
  owner_maintained: true
---

The tracked `obsidience/defaults/vault/` is a deliberately reviewed installation
template. `obsidience init` installs it once into a new local Vault and refuses
to overwrite an existing Vault. Updates do not synchronize defaults into a live
installation or promote live Articles into defaults.

The live Vault, Sources, Inbox, archives, proposals, SQLite, conversations,
connections and machine settings are ignored by the application's Git repository.
A separate local Vault Git repository retains Article audit commits without a
remote. SQLite remains the execution and Review ledger. Git publication is an
explicit development operation, never a capability granted by a Knowledge link.

A reusable correction may be authored separately in the default template after
reviewing its complete text, metadata, links and dependency grants. Installation
facts and local owner permissions remain local. Cordis service ownership applies
to both stores; neither the template nor Git creates another knowledge authority.
