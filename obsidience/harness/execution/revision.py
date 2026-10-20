"""Source files whose bytes identify the Harness implementations that evaluate, optimize and repair.

Paths are relative to the Harness package root. A change that moves, splits or
retires a member updates its set here in the same commit; the recorded revision
then changes, which deliberately invalidates artifacts prepared by the old code.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]

# Frozen Runbook case evaluator (optimization.cases._code_revision): a sorted {path: sha256} map.
REFINEMENT = (
    "execution/optimization/cases.py", "execution/optimization/store.py",
    "execution/optimization/evaluation.py", "execution/executor.py",
    "execution/native.py", "execution/native_turn.py", "execution/capability_core.py",
    "execution/adk/runner.py", "execution/adk/plugin.py", "execution/adk/model.py", "execution/availability.py",
    "capabilities/registry.py",
    "models/llm.py", "models/context.py", "models/runtime.py",
    "knowledge/dependencies.py",
)

# Selected instruction optimizer (optimization.admission.implementation_revision): a sorted {path: sha256} map.
OPTIMIZATION = (
    "execution/optimization/__init__.py", "execution/optimization/admission.py", "execution/optimization/scenario.py",
    "execution/optimization/backend.py", "execution/optimization/harness2.py",
    "execution/optimization/experience.py",
    "execution/adk/runner.py", "execution/native.py", "execution/native_turn.py",
    "execution/capability_core.py",
    "execution/adk/plugin.py", "execution/availability.py", "execution/adk/tools.py", "requirements.lock.txt",
    "execution/adk/sessions.py", "execution/adk/model.py", "capabilities/harness/optimize.py",
    "execution/executor.py", "execution/optimization/evaluation.py", "execution/trace.py",
    "capabilities/registry.py", "capabilities/task/complete.py", "execution/completion.py",
    "models/llm.py", "models/context.py", "models/runtime.py",
    "execution/optimization/incidents.py", "capabilities/vault/propose.py", "knowledge/proposals.py",
    "capabilities/source/read.py", "capabilities/vault/read.py",
    "capabilities/vault/search.py", "capabilities/vault/validate.py",
    "execution/optimization/cases.py", "execution/optimization/store.py",
    "memory/hindsight.py", "knowledge/links.py", "knowledge/format.py", "knowledge/okf.py",
    "knowledge/review.py", "knowledge/scope.py",
    "knowledge/curation.py", "knowledge/source.py",
)

# Repair (repair._code_revision): the bytes concatenated in this order, so order matters.
REPAIR = (
    "execution/repair.py", "execution/availability.py", "execution/scheduler.py", "execution/executor.py",
    "capabilities/registry.py", "capabilities/harness/repair.py",
    "capabilities/harness/status.py", "memory/hindsight.py",
)
