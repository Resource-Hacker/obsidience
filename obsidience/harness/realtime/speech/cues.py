"""Bounded local cue assets and ordinary ordered Pipecat output frames."""
from dataclasses import dataclass
from pathlib import Path
import wave
from pipecat.frames.frames import Frame, OutputAudioRawFrame

NAMES = frozenset({'ready', 'accepted', 'complete', 'cancel', 'error'})
RATE = 24000
CHUNK_BYTES = 1920  # Existing transport: 40 ms, mono s16le.

class CueAudioFrame(OutputAudioRawFrame):
    pass

@dataclass
class CueMarker(Frame):
    cue_name: str
    generation: int
    epoch: int
    end: bool = False

@dataclass
class ReplyFinished(Frame):
    binding: dict
    successful: bool


def load_assets(root: Path) -> dict[str, bytes]:
    assets = {}
    for name in NAMES:
        try:
            path = root / f'{name}.wav'
            if path.stat().st_size > 250000:
                continue
            with wave.open(str(path), 'rb') as wav:
                if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getcomptype()) != (1, 2, RATE, 'NONE'):
                    continue
                if not 0 < wav.getnframes() <= RATE * 4:
                    continue
                pcm = wav.readframes(wav.getnframes())
            if len(pcm) != wav.getnframes() * 2:
                continue
            if name == "ready":
                # Start the opening cue on its first actual sample. Preserve
                # every nonzero sample, its gain, and the rest of the clip.
                start = 0
                while start < len(pcm) and pcm[start:start + 2] == b'\0\0':
                    start += 2
                pcm = pcm[start:]
                if not pcm:
                    continue
            assets[name] = pcm + b'\0' * (-len(pcm) % CHUNK_BYTES)
        except (OSError, EOFError, wave.Error):
            continue
    return assets
