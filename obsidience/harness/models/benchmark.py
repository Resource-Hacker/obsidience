"""One standalone, comparable benchmark contract for every text model."""

from __future__ import annotations

import math
import statistics
from typing import Any


MODEL_COMPARISON_CONTRACT = "obsidience.model-comparison.v1"
MODEL_COMPARISON_MAX_TOKENS = 256
MODEL_COMPARISON_WARMUPS = 1
MODEL_COMPARISON_SAMPLES = 3
MODEL_COMPARISON_TEMPERATURE = 0.0
MODEL_COMPARISON_PROMPT = (
    "Produce a numbered list of exactly 24 concise, non-repeating checks for maintaining "
    "a local Markdown knowledge graph. Start immediately with item 1, use one sentence per "
    "item, and continue sequentially without a preface or conclusion until all 24 items are "
    "complete or the output limit is reached."
)


def _nearest_rank(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot summarize an empty model benchmark")
    return ordered[max(0, math.ceil(probability * len(ordered)) - 1)]


def comparison_result(
    *,
    model_id: str,
    devices: list[str],
    samples: list[dict[str, Any]],
    tested_at: str,
    metrics: dict[str, int | float | bool] | None = None,
    runtime_receipt: str | None = None,
) -> dict[str, Any]:
    """Aggregate identical standalone samples with end-to-end timing.

    Throughput deliberately includes TTFT and every other request cost. This
    makes autoregressive, frame-synchronous, and atomic diffusion models
    comparable without borrowing a provider-specific steady-decode metric.
    """

    if len(samples) != MODEL_COMPARISON_SAMPLES:
        raise ValueError(
            f"model comparison requires exactly {MODEL_COMPARISON_SAMPLES} samples"
        )
    normalized: list[dict[str, float | int]] = []
    for sample in samples:
        ttft_ms = float(sample["ttft_ms"])
        total_seconds = float(sample["total_seconds"])
        completion_tokens = int(sample["completion_tokens"])
        if not math.isfinite(ttft_ms) or ttft_ms <= 0:
            raise ValueError("model comparison TTFT must be positive and finite")
        if not math.isfinite(total_seconds) or total_seconds <= 0:
            raise ValueError("model comparison duration must be positive and finite")
        if completion_tokens <= 0:
            raise ValueError("model comparison must produce completion tokens")
        normalized.append(
            {
                "ttft_ms": ttft_ms,
                "total_seconds": total_seconds,
                "completion_tokens": completion_tokens,
            }
        )

    ttfts = [float(row["ttft_ms"]) for row in normalized]
    latencies_ms = [float(row["total_seconds"]) * 1_000 for row in normalized]
    completion_tokens = sum(int(row["completion_tokens"]) for row in normalized)
    total_seconds = sum(float(row["total_seconds"]) for row in normalized)
    tokens_per_second = completion_tokens / total_seconds
    primary_ttft_ms = statistics.median(ttfts)
    result: dict[str, Any] = {
        "model_id": model_id,
        "kind": "model_comparison",
        "contract": MODEL_COMPARISON_CONTRACT,
        "devices": devices,
        "tested_at": tested_at,
        "output_budget_tokens": MODEL_COMPARISON_MAX_TOKENS,
        "warmup_count": MODEL_COMPARISON_WARMUPS,
        "sample_count": MODEL_COMPARISON_SAMPLES,
        "completion_tokens": completion_tokens,
        "ttft_ms": round(primary_ttft_ms, 2),
        "tokens_per_second": round(tokens_per_second, 2),
        "total_seconds": round(total_seconds, 3),
        "summary": f"TTFT {primary_ttft_ms:.1f} ms · {tokens_per_second:.2f} end-to-end tok/s",
        "metrics": {
            "ttft_p95_ms": round(_nearest_rank(ttfts, 0.95), 2),
            "latency_p50_ms": round(statistics.median(latencies_ms), 2),
            "latency_p95_ms": round(_nearest_rank(latencies_ms, 0.95), 2),
            **(metrics or {}),
        },
    }
    if runtime_receipt:
        result["runtime_receipt"] = runtime_receipt
    return result
