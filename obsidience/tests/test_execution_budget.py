"""Delivery reservation is visible before acquisition exhausts the real budget."""
import asyncio

from obsidience.harness.execution import executor
from obsidience.tests.test_executor_completion_image import action, finish, harness  # noqa: F401


def test_budget_is_visible_initially_and_on_every_remaining_decision(harness, monkeypatch):
    monkeypatch.setattr(executor.CONFIG, 'max_steps', 4)
    decisions = [action('harness.status')] * 3 + [finish('failed', finding=None)]
    _trace, status, _summary = asyncio.run(harness.run(decisions, ['Observed health.'] * 3))
    assert status == 'failed' and len(harness.requests) == 4
    for remaining, request in zip([4, 3, 2, 1], harness.requests, strict=True):
        content = request[-1]['content']
        assert f'Execution budget: {remaining} model decision' in content
    assert 'required delivery or publication' in harness.requests[0][-1]['content']
    assert 'FINAL STEP' in harness.requests[-1][-1]['content']
    assert 'actual delivery outcome' in harness.requests[-1][-1]['content']
