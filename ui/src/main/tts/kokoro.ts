import { createRequire } from "node:module";
import { KokoroTTS } from "kokoro-js";
import { asPlayableWav } from "./wav-payload";

const MODEL_ID = "onnx-community/Kokoro-82M-v1.0-ONNX";
const MODEL_CACHE_DIR =
  process.env.HEREBRUM_KOKORO_CACHE_DIR ??
  "/var/lib/ai/models/kokoro-82m-v1.0-onnx";
const MAX_TEXT_CHARS = 4_000;
const MAX_AUDIO_BYTES = 8 * 1024 * 1024;

export const KOKORO_VOICES = [
  "bm_fable",
  "bm_george",
  "bm_daniel",
  "bm_lewis",
] as const;
export type KokoroVoice = (typeof KOKORO_VOICES)[number];

export interface KokoroSpeechOptions {
  voice?: string;
  speed?: number;
}

type KokoroConstructorArgs = ConstructorParameters<typeof KokoroTTS>;
interface KokoroTransformersRuntime {
  AutoTokenizer: {
    from_pretrained(
      modelId: string,
    ): Promise<KokoroConstructorArgs[1]>;
  };
  StyleTextToSpeech2Model: {
    from_pretrained(
      modelId: string,
      options: Record<string, unknown>,
    ): Promise<KokoroConstructorArgs[0]>;
  };
  env: {
    cacheDir: string | null;
    allowRemoteModels: boolean;
    allowLocalModels: boolean;
  };
}

// Resolve Transformers.js from Kokoro's own dependency tree. HEREBRUM also uses
// a newer Transformers.js in the renderer for Whisper; loading that version
// here would create incompatible Tensor objects and duplicate a large runtime
// in the packaged app.
const requireFromMain = createRequire(__filename);
const requireFromKokoro = createRequire(requireFromMain.resolve("kokoro-js"));
const {
  AutoTokenizer,
  StyleTextToSpeech2Model,
  env,
} = requireFromKokoro("@huggingface/transformers") as KokoroTransformersRuntime;

function selectedVoice(value: string | undefined): KokoroVoice {
  return KOKORO_VOICES.includes(value as KokoroVoice)
    ? (value as KokoroVoice)
    : "bm_fable";
}

function selectedSpeed(value: number | undefined): number {
  if (!Number.isFinite(value)) return 1.05;
  return Math.max(0.8, Math.min(1.25, value!));
}

// This is Kokoro's dedicated Transformers.js 3.x dependency. Keeping its cache
// fixed and remote loading disabled makes voice synthesis local-only at runtime
// and prevents an accidental model download during a spoken turn.
env.cacheDir = MODEL_CACHE_DIR;
env.allowRemoteModels = false;
env.allowLocalModels = true;

let enginePromise: Promise<KokoroTTS> | null = null;
let warmPromise: Promise<void> | null = null;
let synthesisTail: Promise<void> = Promise.resolve();
let synthesisGeneration = 0;

async function loadEngine(): Promise<KokoroTTS> {
  enginePromise ??= Promise.all([
    StyleTextToSpeech2Model.from_pretrained(MODEL_ID, {
      dtype: "q8",
      device: "cpu",
      session_options: {
        // Eight threads on the unpinned 16-core 9950X: inference is strictly
        // serialized (never two concurrent runs), Holo is GPU-offloaded on
        // CCD0 and the voice worker pinned to CCD1, so the scheduler can
        // place these on idle cores. Measured 2026-07-30: 4 threads gave
        // ~24-26 ms/char, which lost the race between the second clip's
        // synthesis and the first (brevity-capped) clip's playback — the
        // audible pause after the first sentence. The model never touches
        // a GPU; do not go wider than 8 (82M q8 saturates on bandwidth).
        intraOpNumThreads: 8,
        interOpNumThreads: 1,
        executionMode: "sequential",
        enableCpuMemArena: true,
        enableMemPattern: true,
      },
    }),
    AutoTokenizer.from_pretrained(MODEL_ID),
  ]).then(([model, tokenizer]) => new KokoroTTS(model, tokenizer));
  return enginePromise;
}

/**
 * Load and exercise the local model once so the first user-visible sentence
 * does not pay model/session/phonemizer initialization costs.
 */
export function preloadKokoroSpeech(): Promise<void> {
  warmPromise ??= loadEngine().then(async (engine) => {
    await engine.generate("System ready.", {
      voice: "bm_fable",
      speed: 1.05,
    });
  });
  return warmPromise;
}

async function synthesizeClip(
  text: string,
  options: KokoroSpeechOptions,
): Promise<Buffer> {
  const trimmed = text.trim();
  if (!trimmed) throw new Error("Missing text for synthesis.");
  if (trimmed.length > MAX_TEXT_CHARS) {
    throw new Error("Kokoro speech input exceeds the per-clip limit.");
  }

  await preloadKokoroSpeech();
  const engine = await loadEngine();
  const startedAt = performance.now();
  const audio = await engine.generate(trimmed, {
    voice: selectedVoice(options.voice),
    speed: selectedSpeed(options.speed),
  });
  // Per-clip synthesis timing: the first clip's cost is the dominant lever on
  // time-to-first-audio (RTF ~0.3 on this CPU), and without this line a synth
  // regression is invisible until it is audible.
  console.info(
    `[opendex tts] kokoro clip ${Math.round(performance.now() - startedAt)}ms/${trimmed.length}ch`,
  );
  // RawAudio already emits a browser-playable RIFF/WAVE container. Returning it
  // directly avoids a process launch plus an unnecessary lossy MP3 encode for
  // every streamed sentence.
  return asPlayableWav(audio.toWav(), MAX_AUDIO_BYTES);
}

/**
 * Kokoro's single CPU inference session is deliberately serialized. The next
 * sentence can synthesize while the renderer plays the current one, without a
 * burst of competing ONNX runs when several sentences are queued together.
 */
export function synthesizeKokoroSpeech(
  text: string,
  options: KokoroSpeechOptions = {},
): Promise<Buffer> {
  const generation = synthesisGeneration;
  const job = synthesisTail.then(() => {
    if (generation !== synthesisGeneration) {
      const error = new Error("Kokoro speech request was cancelled.");
      error.name = "AbortError";
      throw error;
    }
    return synthesizeClip(text, options);
  });
  synthesisTail = job.then(
    () => undefined,
    () => undefined,
  );
  return job;
}

/** Drop queued clips after STOP/provider changes. An inference already running
 * finishes in native code, but stale work behind it is skipped immediately. */
export function cancelPendingKokoroSpeech(): void {
  synthesisGeneration += 1;
}
