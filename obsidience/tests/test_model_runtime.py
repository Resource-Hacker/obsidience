from obsidience.harness.models.runtime import (
    EXECUTIVE_MODEL,
    GEMMA_PROJECTOR_SHA256,
    MODELS,
    _benchmark_doc,
)


def test_realtime_first_text_is_projected_as_ttft_only() -> None:
    projected = _benchmark_doc({
        "kind": "realtime_audio",
        "summary": "old component receipt",
        "metrics": {"first_text_ms": 111.9, "interrupt_ack_ms": 0.2},
    })

    assert projected is not None
    assert projected["ttft_ms"] == 111.9
    assert "tokens_per_second" not in projected


def test_executive_model_has_one_attested_vision_projector() -> None:
    spec = MODELS[EXECUTIVE_MODEL]
    assert "vision" in spec.capabilities
    assert spec.projector_path is not None and spec.projector_path.is_file()
    assert spec.projector_sha256 == GEMMA_PROJECTOR_SHA256
