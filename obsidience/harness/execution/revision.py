"""Source files whose bytes identify the Harness implementations that evaluate, optimize and repair.

Paths are relative to the Harness package root. A change that moves, splits or
retires a member updates its set here in the same commit; the recorded revision
then changes, which deliberately invalidates artifacts prepared by the old code.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]

# Frozen Runbook case evaluator (refinement._code_revision): a sorted {path: sha256} map.
REFINEMENT = (
    "execution/refinement.py", "execution/evaluation.py", "execution/executor.py",
    "execution/native.py", "execution/native_turn.py", "execution/capability_core.py",
    "execution/adk/runner.py", "execution/adk/plugin.py",
    "models/llm.py", "models/context.py", "models/runtime.py",
    "knowledge/dependencies.py",
)

# AutoSaddler optimization (optimization._revision): a sorted {path: sha256} map.
OPTIMIZATION = (
    "execution/optimization.py", "execution/adk/optimization.py",
    "execution/adk/runner.py", "execution/native.py", "execution/native_turn.py",
    "execution/capability_core.py",
    "execution/adk/plugin.py", "execution/adk/tools.py", "requirements.lock.txt",
    "execution/adk/sessions.py", "capabilities/harness/optimize.py",
    "execution/executor.py", "execution/evaluation.py", "execution/trace.py",
    "capabilities/registry.py", "capabilities/task/complete.py",
    "models/llm.py", "models/context.py", "models/runtime.py",
    "execution/optimization_incidents.py", "capabilities/vault/propose.py",
    "capabilities/source/read.py", "capabilities/vault/read.py",
    "capabilities/vault/search.py", "capabilities/vault/validate.py",
    "execution/refinement.py",
    "memory/hindsight.py", "knowledge/links.py", "knowledge/format.py",
    "knowledge/review.py", "knowledge/scope.py",
    "knowledge/curation.py", "knowledge/source.py",
)

# Repair (repair._code_revision): the bytes concatenated in this order, so order matters.
REPAIR = (
    "execution/repair.py", "execution/scheduler.py", "execution/executor.py",
    "capabilities/registry.py", "capabilities/harness/repair.py",
    "capabilities/harness/status.py", "memory/hindsight.py",
)
