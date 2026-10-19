# Instruction improvement with Harness2

`harness.optimize` uses Google Research Harness2's pinned Propose–Probe–Compose
method inside Heimdall Audit. Google ADK still executes each isolated trial.
AutoSaddler remains installed for immutable candidates, parent lineage, durable
attempts and an explicit rollback search backend. Only one search backend owns
an activation.

## Scope and retained behavior

The default performs one sequential refinement step, with one worker at a time:
baseline, general candidate, task-specific candidate, then a composed candidate.
The existing model owner handles every proposal and trial; no external agent CLI,
provider server, benchmark installer or second scheduler is started.

Candidates may edit only the bound Agent identity or Runbook instruction body,
using the existing whole-unit mutation validator. Article links, metadata,
capability grants, model configuration and code remain outside this scope.
All candidate Tool calls are intercepted by the existing ADK trial evaluator.
The optimizer never reruns the real task to measure a candidate.

Harness2's preference for a final candidate is not acceptance. Publication still
requires the existing repeated baseline/control comparison, training improvement,
control pass floor and regression limits, Tool-count check and applicable
Executive latency check. Missing evidence and execution errors cannot become
success. The incumbent instructions remain when no candidate qualifies.

The AutoSaddler artifact layer preserves completed attempt receipts across an
interruption. Backend, installed-source manifest, model, case content,
implementation and experience inputs are bound to the job. Foreground interruption
cancels and joins inference and the synchronous search worker before releasing
ownership. Session, trial and job budgets remain bounded across retries.

Only training evidence reaches proposals, composition or lesson extraction.
Control cases and results stay outside that context. Retained lessons are bounded
private optimizer evidence, not accepted Knowledge or Hindsight Memory. A case
freezes its prior experience; later publications cannot change a resumed search.
New lessons become eligible only after independently validated instruction
publication and its committed Audit/Review evidence.

## Dependency and rollback

Run from the repository root after installing ordinary Harness requirements:

```sh
python3 obsidience/scripts/install-optimization
```

`--build-only` produces the wheel without installing it. The installer verifies
the exact upstream archive, applies the tracked patch, and includes a manifest
of every Python source file. Runtime admission verifies the expected manifest
and installed source bytes. The Apache-2.0 license is included in the wheel;
the revision, source digest and patch are recorded in `artifacts.lock.json`.

The local `0.1.0+obsidience.1` patch admits Python 3.14 and disables implicit
working-directory `.env` loading on import. The refinement implementation is
unchanged. This is a locally validated embedded package; it does not claim
upstream support for all CLI/benchmark paths on Python 3.14.

`OBSIDIENCE_OPTIMIZER_BACKEND=autosaddler` selects the retained original engine.
Use the installation's normal idle Harness deployment procedure to change that
setting. Changing backend invalidates prepared cases; prepare fresh cases under
the selected backend. Failed Harness2 work never silently switches engines.
Existing reports retain their original backend identity and remain historical
evidence, rather than being relabeled as Harness2 results.

## Upstream research informing this integration

Reviewed upstream revision `1cfe254e8d25b15f37048c3730134686abe60335` and live
GitHub discussions on 2026-10-18. The fixes below were open and unmerged when
reviewed. Their presence is not evidence that the pinned release includes them.

| Finding | Source | Integration consequence |
| --- | --- | --- |
| Selection excludes the baseline; one-step selection takes the single final | [selection](https://github.com/google-research/harness2/blob/1cfe254e8d25b15f37048c3730134686abe60335/harness2/core/selection.py#L94), [scheduler](https://github.com/google-research/harness2/blob/1cfe254e8d25b15f37048c3730134686abe60335/harness2/core/schedule.py#L513) | Independent comparison and `not_improved` remain authoritative. |
| Proposal cache omits model/channel configuration; resume can omit task/source and experience changes | [PR 48](https://github.com/google-research/harness2/pull/48), [issue 65](https://github.com/google-research/harness2/issues/65), [PR 21](https://github.com/google-research/harness2/pull/21), [PR 36](https://github.com/google-research/harness2/pull/36) | Use the existing content-bound job and attempt records, not upstream provider/scheduler caches. |
| Interrupted audit fragments and unparseable trajectories can be treated as usable evidence | [PR 69](https://github.com/google-research/harness2/pull/69), [PR 72](https://github.com/google-research/harness2/pull/72) | Require complete structured responses and actual validated trial records. |
| Concurrent experience streams can prune each other's inputs | [PR 54](https://github.com/google-research/harness2/pull/54) | One owner, immutable case snapshots, no upstream mutable library writer. |
| Rollout spend and earlier partial-run costs are not fully accounted for | [issue 4](https://github.com/google-research/harness2/issues/4), [issue 50](https://github.com/google-research/harness2/issues/50), [PR 74](https://github.com/google-research/harness2/pull/74) | Preserve model accounting and bounded durable attempts/deadlines; native recursion counts are not a spend cap. |
| Rejudging can retain an old grade after a run changes | [issue 44](https://github.com/google-research/harness2/issues/44), [PR 45](https://github.com/google-research/harness2/pull/45) | Bind comparison and publication to immutable candidate observations and exact receipts. |

The reviewed comments were contributor discussion, not demonstrated Google
maintainer approval. In [PR 48's author reply](https://github.com/google-research/harness2/pull/48#issuecomment-6259664146),
the proposed cache key was revised to exclude timeout; older summaries still
described the earlier proposal.

The [Hacker News discussion](https://news.ycombinator.com/item?id=50140036)
asked for matched-model harness comparisons. An actual
[LocalLLaMA comment](https://www.reddit.com/r/LocalLLaMA/comments/1x9gfnb/comment/phl8i8a/)
raised overfitting concerns; the same discussion considered context pressure
for local models. These are useful evaluation questions, not measured defects
or proof that one optimizer is better. Compare the same captured cases, model
and budgets, keep controls private, and measure the actual supplied context.

AutoSaddler's [V2 architecture](https://github.com/microsoft/AutoSaddler/blob/main/docs/v2-architecture.md)
and [scenario contract](https://github.com/microsoft/AutoSaddler/blob/main/docs/scenario-integration.md)
explain the durable candidates, attempt journal and split evaluation retained
here. Current upstream documentation may include additions beyond our pinned
AutoSaddler revision; installed behavior and the recorded pin remain authoritative.
