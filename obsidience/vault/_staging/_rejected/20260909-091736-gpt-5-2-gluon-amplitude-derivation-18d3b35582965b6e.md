---
type: knowledge
status: stable
title: GPT-5.2 Gluon Amplitude Derivation
obsidience:
  proposal: true
  action: create
  target: Projects/Research/gpt-5-2-gluon-amplitude-derivation--8c4e2f1a.md
  agent: Alexandria
  task: Tasks/ingest
  run_id: e81b37022b86
  reason: Ingest Learn handoff from source://8b503df8-228e-46b5-8c4e-e7059d9a457c
    preserving Darwin's finding on GPT-5.2's gluon amplitude derivation with full
    provenance.
  review_class: article
  authored_fields:
  - article_status
  - kind
  proposed_at: '2026-09-09T09:17:36'
  rejected_at: '2026-09-09T09:23:26'
  rejected_reason: 'Rejected during Connections acceptance: Learn run 2618387a04e2
    was activated by the BBC Source but researched an unrelated ambient browser title.
    No claim about the factual correctness of the unrelated research; this output
    does not fulfill its activating Source.'
---

# GPT-5.2 Derives New Result in Theoretical Physics

A new preprint (arXiv:2602.12176) demonstrates that GPT-5.2 proposed a new formula for single-minus gluon tree amplitudes, a configuration that physicists had expected to have zero amplitude under generic momenta. The result has been formally proved and verified by human collaborators.

## The Amplitude Studied

A scattering amplitude where one gluon has negative helicity and all remaining gluons have positive helicity. The regime is the half-collinear regime — a specific, well-defined slice of momentum space where standard textbook arguments (assuming generic momenta) no longer apply. The amplitude does not vanish on this slice; a simple formula exists (Eq. 39 in the preprint) that was conjectured by GPT-5.2 Pro, then formally proved by an internal GPT-5.2 scaffolded model over ~12 hours.

## Methodology

- Human authors computed base cases by hand for integer values up to some small n, obtaining complicated expressions (Eqs. 29–32) via Feynman diagram expansion (complexity grows superexponentially in n).
- GPT-5.2 Pro reduced these to much simpler forms (Eqs. 35–38) and spotted the general pattern.
- Verification: formal proof by internal scaffolded GPT-5.2; analytic verification against the Berends-Giele recursion relation; check against the soft theorem constraint.

## Extensions

The amplitudes have already been extended from gluons to gravitons. Additional generalizations are in progress.

## Expert Assessment

> "I am already thinking about this preprint's implications for aspects of my group's research program. This is clearly journal-level research advancing the frontiers of theoretical physics, and its novelty will inspire future developments and subsequent publications." — Nathaniel Craig, UC Santa Barbara

> "This preprint felt like a glimpse into the future of AI-assisted science... By coupling GPT-5.2 with human domain experts, the paper provides a template for validating LLM-driven insights and satisfies what we expect from rigorous scientific inquiry." — Nathaniel Craig

## Key References

- Preprint: arXiv:2602.12176 — *Single-minus gluon tree amplitudes are nonzero*
- Authors: Alfredo Guevara (IAS), Alex Lupsasca (Vanderbilt/OpenAI), David Skinner (Cambridge), Andrew Strominger (Harvard), Kevin Weil (OpenAI)
- Source: [OpenAI, "GPT-5.2 derives a new result in theoretical physics" (Feb 13, 2026)](source://f95a9235-fd6a-47fc-87e0-4284087e9774)

## Uncertainty and Limitations

This is a new preprint currently under review. The formula is verified but the broader implications for quantum field theory and the automation of pattern recognition in physics remain subjects of future investigation.

## Context

This finding demonstrates a concrete instance of AI-assisted theoretical physics discovery: an LLM conjectured a nontrivial result in quantum field theory that was then formally proved and independently verified. It extends the [research request](/Agents/Executive/Architecture/research-requests--7bf0113c.md) pattern where bounded findings are preserved for future reference.
