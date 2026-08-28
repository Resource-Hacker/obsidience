/** Models: reasoning-model inventory and comparable per-model benchmarks. */

import { useEffect, useState } from "react";
import { BrainCircuit, Play, Settings2 } from "lucide-react";
import { api, openReader, type HarnessStatus, type ModelBenchmark, type ModelOption } from "@/lib/api";

const GPU_LABELS: Record<string, string> = { rtx4080: "RTX 4080 SUPER", rtx4000: "RTX 4000 Ada" };
const layoutLabel = (devices: string[]) => devices.map((device) => GPU_LABELS[device] ?? device).join(" + ");

function ModelCard({ model, result, benchmarking, onBenchmark }: {
  model: ModelOption; result: ModelBenchmark | null; benchmarking: string | null;
  onBenchmark: (model: ModelOption) => void;
}) {
  const validLayouts = model.device_sets.filter((layout) => layout.every((device) => model.allowed_devices.includes(device)));
  const comparison = result?.contract ? result : null;
  return (
    <section className={`rounded border p-2.5 ${model.loaded
      ? "border-emerald-300/25 bg-emerald-300/[0.035]"
      : model.installed ? "border-cyan-300/14 bg-cyan-300/[0.02]" : "border-rose-300/18 bg-rose-300/[0.025]"}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-cyan-50">{model.label}</p>
          <p className="mt-0.5 text-[8px] leading-4 text-cyan-100/52">{model.purpose}</p>
        </div>
        <span className={`shrink-0 text-[8px] ${model.loaded ? "text-emerald-300" : model.installed ? "text-cyan-300/45" : "text-rose-300/70"}`}>
          {model.loaded ? "● loaded" : model.installed ? model.state : "not installed"}
        </span>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[8px]">
        <p className="text-cyan-200/42">Quantization</p><p className="text-right text-cyan-50/65">{model.quantization}</p>
        <p className="text-cyan-200/42">Context</p><p className="text-right text-cyan-50/65">{(model.context_tokens / 1024).toFixed(0)}K</p>
        <p className="text-cyan-200/42">Works with</p><p className="text-right text-cyan-50/65">{validLayouts.map(layoutLabel).join(" · ") || "no enabled layout"}</p>
      </div>
      <div className="mt-2 flex flex-wrap gap-1">
        {model.capabilities.map((capability) => <span key={capability} className="rounded border border-violet-300/14 px-1.5 py-0.5 text-[7px] text-violet-200/60">{capability}</span>)}
      </div>
      <div className="mt-2 grid grid-cols-2 gap-1.5">
        <div className="rounded border border-emerald-300/14 bg-emerald-300/[0.025] px-2 py-1.5">
          <p className="text-[7px] uppercase tracking-[0.12em] text-emerald-100/45">TTFT</p>
          <p className="mt-0.5 text-[9px] text-emerald-200/78">{comparison?.ttft_ms != null ? `${comparison.ttft_ms.toFixed(1)} ms` : "Not recorded"}</p>
        </div>
        <div className="rounded border border-emerald-300/14 bg-emerald-300/[0.025] px-2 py-1.5">
          <p className="text-[7px] uppercase tracking-[0.12em] text-emerald-100/45">Throughput</p>
          <p className="mt-0.5 text-[9px] text-emerald-200/78">{comparison?.tokens_per_second != null ? `${comparison.tokens_per_second.toFixed(2)} tok/s` : "Not recorded"}</p>
        </div>
      </div>
      <p className="mt-1 truncate text-[7px] text-cyan-200/28" title={model.source_manifest}>Source · {model.source_manifest}</p>
      <div className="mt-2 flex gap-1.5">
        <button type="button" onClick={() => onBenchmark(model)} disabled={!model.installed || Boolean(benchmarking)}
          className="flex items-center gap-1 rounded border border-emerald-300/28 px-2 py-1 text-[8px] uppercase tracking-[0.12em] text-emerald-200 hover:bg-emerald-300/10 disabled:opacity-35">
          <Play size={9} /> {benchmarking === model.id ? "Testing…" : "Benchmark"}
        </button>
        <button type="button" onClick={() => openReader(`@runtime/model/${model.id}`)}
          className="flex items-center gap-1 rounded border border-cyan-300/22 px-2 py-1 text-[8px] uppercase tracking-[0.12em] text-cyan-200/65 hover:bg-cyan-300/10 hover:text-cyan-50">
          <Settings2 size={9} /> Configure
        </button>
      </div>
    </section>
  );
}

export function StatusPaneBody() {
  const [status, setStatus] = useState<HarnessStatus | null>(null);
  const [models, setModels] = useState<ModelOption[]>([]);
  const [benchmarking, setBenchmarking] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, ModelBenchmark>>({});
  const [error, setError] = useState<string | null>(null);

  async function pull() {
    const [nextStatus, nextModels] = await Promise.all([api.status(), api.models()]);
    setStatus(nextStatus);
    setModels(nextModels.models.filter((model) => model.task_capable));
  }
  useEffect(() => {
    void pull().catch(() => setStatus(null));
    const timer = setInterval(() => void pull().catch(() => undefined), 10_000);
    return () => clearInterval(timer);
  }, []);

  async function runBenchmark(model: ModelOption) {
    if (benchmarking) return;
    const devices = model.active_devices.length ? model.active_devices
      : model.assigned_devices.length ? model.assigned_devices
        : model.device_sets.find((layout) => layout.every((device) => model.allowed_devices.includes(device))) ?? [];
    if (!devices.length) { setError(`No valid enabled GPU layout for ${model.label}.`); return; }
    setBenchmarking(model.id); setError(null);
    try {
      const result = await api.benchmarkModel(model.id, devices);
      setResults((current) => ({ ...current, [model.id]: result }));
      await pull();
    } catch (cause) { setError(String(cause)); }
    finally { setBenchmarking(null); }
  }

  if (!status) return <p className="p-4 font-mono text-[11px] text-rose-300/80">Models service offline — start Obsidience with <code>obsidience serve</code>.</p>;
  return (
    <div className="h-full space-y-3 overflow-y-auto p-3 font-mono text-[11px] text-cyan-100/85">
      <div className="flex items-start justify-between gap-3 rounded border border-cyan-300/14 bg-cyan-300/[0.025] px-2.5 py-2">
        <div className="flex min-w-0 items-start gap-2">
          <BrainCircuit size={13} className="mt-0.5 shrink-0 text-cyan-300/70" />
          <div><p className="text-[9px] uppercase tracking-[0.16em] text-cyan-50">Task reasoning models</p>
            <p className="mt-0.5 text-[8px] leading-4 text-cyan-200/42">Selected per Task with that Task's reasoning effort. Speech transport is fixed under Hardware.</p></div>
        </div>
        <span className="shrink-0 rounded-full border border-cyan-300/12 px-1.5 py-0.5 text-[7px] text-cyan-200/45">{models.length}</span>
      </div>
      <div className="space-y-2">{models.map((model) => <ModelCard key={model.id} model={model}
        result={results[model.id] ?? model.last_benchmark} benchmarking={benchmarking} onBenchmark={(row) => void runBenchmark(row)} />)}</div>
      {error ? <p className="rounded border border-rose-300/20 px-2 py-1.5 text-[8px] text-rose-300">{error}</p> : null}
      <p className="border-t border-cyan-300/10 pt-2 text-[8px] text-cyan-200/35">{status.notes} Articles · {status.tasks} Tasks · {status.sources} Source files · {status.source_issues} Source issues</p>
    </div>
  );
}
