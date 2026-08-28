from obsidience.harness.models.runtime import _benchmark_doc


def test_realtime_first_text_is_projected_as_ttft_only() -> None:
    projected = _benchmark_doc({
        "kind": "realtime_audio",
        "summary": "old component receipt",
        "metrics": {"first_text_ms": 111.9, "interrupt_ack_ms": 0.2},
    })

    assert projected is not None
    assert projected["ttft_ms"] == 111.9
    assert "tokens_per_second" not in projected
