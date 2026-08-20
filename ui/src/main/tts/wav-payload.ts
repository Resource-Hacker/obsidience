const MIN_WAV_BYTES = 44;

function asciiAt(buffer: Buffer, offset: number, value: string): boolean {
  return buffer.subarray(offset, offset + value.length).toString("ascii") === value;
}

/**
 * Turn the WAV emitted by Transformers.js RawAudio into the bounded Buffer
 * returned over Electron IPC. Kokoro currently emits a standard RIFF/WAVE
 * header followed by 24 kHz mono IEEE-float samples.
 */
export function asPlayableWav(
  payload: ArrayBuffer,
  maxBytes: number,
): Buffer {
  const wav = Buffer.from(payload);
  if (wav.byteLength > maxBytes) {
    throw new Error("Kokoro speech audio exceeded the per-clip limit.");
  }
  if (
    wav.byteLength <= MIN_WAV_BYTES ||
    !asciiAt(wav, 0, "RIFF") ||
    !asciiAt(wav, 8, "WAVE")
  ) {
    throw new Error("Kokoro speech synthesis returned invalid WAV audio.");
  }
  return wav;
}
