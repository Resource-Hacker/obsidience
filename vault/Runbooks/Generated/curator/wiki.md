---
approved_at: '2026-08-21T10:16:42'
assignee: Agents/Alexandria/Alexandria
for_agent: '[[Agents/Alexandria/Alexandria]]'
generated_by: '[[Runbooks/create-a-runbook]]'
kind: runbook
provenance: proposed by Darwin (task Tasks/generate/runbook)
runbook: Tasks/wiki
skills:
- '[[Skills/appending-temporary-observations]]'
- '[[Skills/completing-a-task]]'
- '[[Skills/task-authoring]]'
- '[[Skills/listing-the-vault]]'
- '[[Skills/proposing-changes]]'
- '[[Skills/reading-the-vault]]'
- '[[Skills/searching-the-vault]]'
- '[[Skills/validating-the-vault]]'
task: '[[Tasks/wiki]]'
title: wiki maintenance
---

# wiki maintenance

## Prerequisites
- Access to the `Sources/` folder.
- Awareness of the current maintenance cycle.

## Ordered Actions
1. **Ingest New Sources**
   - List files in `Sources/` using `vault.list` to identify new material.
   - Read new source content using `vault.read`.
   - Synthesize source documents and stage them using `vault.propose`.
   - Use `Skills/appending-temporary-observations` to track ingestion progress.
2. **Copyedit Articles**
   - Identify recent or new articles via `vault.list` or `vault.search`.
   - Read article content with `vault.read`.
   - Refine prose for clarity and consistency.
   - Stage updates using `vault.propose`.
3. **Validate Links**
   - Use `vault.search` to identify potential broken or outdated wikilinks.
   - Verify link targets using `vault.read`.
   - Stage link corrections using `vault.propose`.
4. **Categorize Content**
   - Identify articles requiring metadata or structural updates.
   - Use `vault.propose` to update metadata (e.g., `kind`, `assignee`) or index files.
5. **Check Contradictions**
   - Search for existing information related to new evidence using `vault.search`.
   - Read existing articles with `vault.read` to identify discrepancies.
   - Stage resolutions via `vault.propose`.
6. **Improve Weakest Article**
   - Identify an article with minimal content or outdated information.
   - Read the article with `vault.read`.
   - Stage improvements using `vault.propose`.

## Stop Conditions
- All steps in the maintenance loop are completed for the current batch of sources and articles.
- No further actions are required for the current cycle.

## Completion Criteria
- All maintenance actions have been staged via `vault.propose`.
- Use `Skills/completing-a-task` to end the session.

## Recovery
- If a tool fails, use `Skills/appending-temporary-observations` to record the error.
- If a critical error occurs (e.g., `vault.validate` failure), stop and use `Skills/completing-a-task` with status `failed` and a detailed reason.
