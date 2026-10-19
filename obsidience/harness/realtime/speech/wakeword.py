"""Streaming wake-word spotter: the fast first stage before ASR confirmation.

A microWakeWord model (int8 TFLite, 26k parameters) reads the worker's captured
16 kHz mono PCM on CPU: one 40-channel feature per 10 ms and one inference per
30 ms, averaged over the manifest's sliding window. It reports the name about
0.2 s after it is spoken, well before the first ASR partial. It never opens a
command window: the ASR text match remains the authority.
"""

from __future__ import annotations

from pathlib import Path

from pymicro_wakeword import MicroWakeWord, MicroWakeWordFeatures

FEATURE_STEP_SECS = 0.01
# One spoken name keeps the averaged probability above the cutoff for a few
# inferences; report it once.
REFRACTORY_SECS = 1.0


class WakeWordSpotter:
    """Feed captured PCM in order; ``process`` returns True on a detection."""

    def __init__(self, manifest: str | Path, *, cutoff: float | None = None) -> None:
        self._model = MicroWakeWord.from_config(manifest)
        if cutoff is not None:
            self._model.probability_cutoff = cutoff
        self._features = MicroWakeWordFeatures()
        self.wake_word = self._model.wake_word
        self.cutoff = self._model.probability_cutoff
        self.score = 0.0
        self._step = 0
        self._quiet_until = 0

    def process(self, pcm: bytes) -> bool:
        """Consume 16 kHz mono s16le PCM; True when the name was just heard."""
        detected = False
        for features in self._features.process_streaming(pcm):
            self._step += 1
            probability = self._model.process_streaming_prob(features)
            if probability is not None and probability > self.cutoff and self._step >= self._quiet_until:
                self._quiet_until = self._step + round(REFRACTORY_SECS / FEATURE_STEP_SECS)
                self.score = probability
                detected = True
        return detected
