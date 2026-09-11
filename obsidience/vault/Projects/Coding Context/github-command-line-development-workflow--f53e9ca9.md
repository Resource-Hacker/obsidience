---
type: knowledge
title: GitHub command-line development workflow
---

Package-managed Git and GitHub CLI are the workstation’s GitHub development path. GitHub CLI authenticates the owner through the KDE Secret Service keyring, and HTTPS Git operations use the GitHub CLI credential helper; tokens never belong in project files, shell profiles, instructions, or logs.

Global commit attribution uses the owner’s GitHub-linked private no-reply identity. New repositories default to `main`, and `push.autoSetupRemote` establishes upstream tracking on first push.

Repositories belong in dedicated directories such as `/home/wissenschafter/Projects/<project>`. Never initialize `/home/wissenschafter` itself as a Git repository because it contains private workstation configuration and data.

Live acceptance verified authentication, credential-helper routing, attribution, default branch and push settings, and authenticated repository enumeration without creating or modifying a repository.

## Relationships

- `implements` [Local-first architecture](/Agents/Executive/Architecture/Harness/local-first-architecture--7d8e77cc.md) — Dedicated local repositories and keyring-backed credentials keep project state owner-controlled without embedding secrets in the graph.
