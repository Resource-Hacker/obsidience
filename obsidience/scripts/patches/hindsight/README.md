# Hindsight native patches

Apply the patches in numeric order to the pinned Hindsight environment. Exact
preimage and resulting module hashes are recorded in `artifacts.lock.json`.
The Hindsight service owns these modules; the Harness does not load them.

Patch 0007 follows 0002 for `engine/search/reranking.py`. It places qualified
memory text before date and provenance context in cross-encoder input. Stored
memories and their uncertainty, source labels and timestamps remain unchanged.

```sh
patch --forward -d <hindsight-venv>/lib/python3.13/site-packages -p1 < obsidience/scripts/patches/hindsight/0007-rank-fact-before-provenance.patch
```

Reranker model selection remains native installation configuration. Validate
recall quality and API latency on the target CPU before selecting a larger model;
a change in ranking input order alone does not establish a latency or quality gain.
