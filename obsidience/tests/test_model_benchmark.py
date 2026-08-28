from __future__ import annotations

import pytest

from obsidience.harness.models.benchmark import (
    MODEL_COMPARISON_CONTRACT,
    comparison_result,
)


def test_comparison_uses_complete_request_wall_time() -> None:
    result = comparison_result(
        model_id="model:test",
        devices=["rtx4080"],
        tested_at="2026-08-25T00:00:00-0700",
        samples=[
            {"ttft_ms": 100, "total_seconds": 1, "completion_tokens": 10},
            {"ttft_ms": 200, "total_seconds": 2, "completion_tokens": 20},
            {"ttft_ms": 300, "total_seconds": 3, "completion_tokens": 30},
        ],
    )

    assert result["contract"] == MODEL_COMPARISON_CONTRACT
    assert result["ttft_ms"] == 200
    assert result["tokens_per_second"] == 10
    assert result["completion_tokens"] == 60
    assert result["total_seconds"] == 6


def test_comparison_rejects_nonstandard_sample_count() -> None:
    with pytest.raises(ValueError, match="exactly 3 samples"):
        comparison_result(
            model_id="model:test",
            devices=["rtx4080"],
            tested_at="2026-08-25T00:00:00-0700",
            samples=[
                {"ttft_ms": 100, "total_seconds": 1, "completion_tokens": 10}
            ],
        )
