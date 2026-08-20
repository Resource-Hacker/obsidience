"""STT via faster-whisper (lazy). TTS lives client-side (kokoro-js, local ONNX model)."""

from __future__ import annotations

import io
import threading

from .config import CONFIG

_model = None
_lock = threading.Lock()
_error: str | None = None


def available() -> dict:
    if not CONFIG.voice_enabled:
        return {"stt": False, "reason": "disabled in config"}
    try:
        import faster_whisper  # noqa: F401
        return {"stt": True, "model": CONFIG.whisper_model, "error": _error}
    except ImportError:
        return {"stt": False, "reason": "faster-whisper not installed (pip install faster-whisper)"}


def _get_model():
    global _model, _error
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel
            try:
                _model = WhisperModel(CONFIG.whisper_model, device="cpu", compute_type="int8")
            except Exception as exc:  # noqa: BLE001
                _error = str(exc)
                raise
    return _model


def transcribe_wav(data: bytes) -> str:
    model = _get_model()
    segments, _info = model.transcribe(io.BytesIO(data), beam_size=5, vad_filter=True)
    return " ".join(s.text.strip() for s in segments).strip()
