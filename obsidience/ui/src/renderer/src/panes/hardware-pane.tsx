/** Hardware defaults: one truthful component assignment per physical compute slot. */

import { useCallback, useEffect, useState } from "react";
import { AudioLines, Camera, Cpu, Gauge, Mic, MonitorCog, Volume2 } from "lucide-react";
import {
  api,
  type HardwareSensors,
  type HardwareState,
} from "@/lib/api";

function clampPercent(value: number | null | undefined) {
  return Math.max(0, Math.min(100, value ?? 0));
}

function memoryLabel(value: number | null | undefined) {
  if (value == null) return "—";
  return value >= 1024 ? `${(value / 1024).toFixed(1)} GiB` : `${value} MiB`;
}

function SensorBar({ label, value, detail, color = "cyan" }: {
  label: string; value: number | null | undefined; detail: string; color?: "cyan" | "violet";
}) {
  const width = clampPercent(value);
  return (
    <div>
      <div className="mb-1 flex items-center justify-between gap-2 text-[8px]">
        <span className="uppercase tracking-[0.13em] text-cyan-200/45">{label}</span>
        <span className="text-cyan-50/72">{value == null ? "sampling…" : `${value.toFixed(1)}%`} · {detail}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full border border-cyan-300/12 bg-black/35">
        <div className={`h-full rounded-full transition-[width] duration-500 ${color === "violet"
          ? "bg-gradient-to-r from-violet-500/60 to-fuchsia-300/90"
          : "bg-gradient-to-r from-cyan-600/60 to-cyan-200/95"}`}
          style={{ width: `${width}%` }} />
      </div>
    </div>
  );
}

function Reading({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded border border-cyan-300/10 bg-cyan-300/[0.018] px-2 py-1.5">
      <p className="text-[7px] uppercase tracking-[0.12em] text-cyan-200/35">{label}</p>
      <p className="mt-0.5 truncate text-[9px] text-cyan-50/72" title={value}>{value}</p>
    </div>
  );
}

function SensorSuite({ sensors }: { sensors: HardwareSensors | null | undefined }) {
  if (!sensors || sensors.status !== "online") {
    return <p className="rounded border border-rose-300/12 px-2 py-2 text-[8px] text-rose-200/55">Sensor telemetry unavailable.</p>;
  }
  const memoryDetail = sensors.memory_total_mib == null
    ? "unavailable"
    : `${memoryLabel(sensors.memory_used_mib)} / ${memoryLabel(sensors.memory_total_mib)}`;
  const readings = [
    sensors.temperature_c != null && ["Temperature", `${sensors.temperature_c.toFixed(1)} °C`],
    sensors.power_w != null && ["Power", sensors.power_limit_w != null
      ? `${sensors.power_w.toFixed(1)} / ${sensors.power_limit_w.toFixed(0)} W`
      : sensors.power_w < 0.1 ? `${(sensors.power_w * 1000).toFixed(0)} mW` : `${sensors.power_w.toFixed(1)} W`],
    sensors.clock_core_mhz != null && ["Core clock", `${sensors.clock_core_mhz} MHz`],
    sensors.clock_memory_mhz != null && ["Memory clock", `${sensors.clock_memory_mhz} MHz`],
    sensors.fan_percent != null && ["Fan", `${sensors.fan_percent}%`],
    sensors.pstate && ["Power state", sensors.pstate],
    sensors.pcie_generation != null && sensors.pcie_width != null
      && ["PCIe link", `Gen ${sensors.pcie_generation} ×${sensors.pcie_width}`],
    sensors.memory_controller_percent != null
      && ["Memory engine", `${sensors.memory_controller_percent}%`],
    sensors.encoder_percent != null && ["Encoder", `${sensors.encoder_percent}%`],
    sensors.decoder_percent != null && ["Decoder", `${sensors.decoder_percent}%`],
    sensors.media_engine_percent != null && ["Media engine", `${sensors.media_engine_percent}%`],
    sensors.load_1m != null && ["Load average", `${sensors.load_1m} · ${sensors.load_5m} · ${sensors.load_15m}`],
    sensors.physical_cores != null && ["Topology", `${sensors.physical_cores} cores · ${sensors.threads} threads`],
    sensors.driver && ["Driver", sensors.driver],
  ].filter(Boolean) as [string, string][];
  return (
    <div className="space-y-2.5">
      <SensorBar label={sensors.memory_label ?? "Memory"} value={sensors.memory_used_percent}
        detail={memoryDetail} color="violet" />
      <SensorBar label="Utilization" value={sensors.utilization_percent}
        detail={sensors.utilization_percent == null ? "warming sensor" : "live compute"} />
      <div className="grid grid-cols-2 gap-1.5 xl:grid-cols-3">
        {readings.map(([label, value]) => <Reading key={label} label={label} value={value} />)}
      </div>
    </div>
  );
}

export function HardwarePaneBody() {
  const [hardware, setHardware] = useState<HardwareState | null>(null);
  const [changing, setChanging] = useState<string | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(() => {
    api.hardware().then(setHardware).catch((cause) => setError(String(cause)));
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") refresh();
    }, 3_000);
    return () => clearInterval(timer);
  }, [refresh]);

  async function assign(device: string, component: string) {
    setChanging(device);
    setError("");
    try {
      setHardware(await api.setHardware(device, component));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      refresh();
    } finally {
      setChanging(null);
    }
  }

  async function assignInterface(hardwareInterface: string, selection: string) {
    setChanging(hardwareInterface);
    setError("");
    try {
      setHardware(await api.setHardwareInterface(hardwareInterface, selection));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
      refresh();
    } finally {
      setChanging(null);
    }
  }

  async function assignVoice(voice: string) {
    setChanging("speech-voice");
    setError("");
    try {
      await api.setSpeechVoice(voice);
      refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setChanging(null);
    }
  }

  if (!hardware) {
    return <p className="p-4 font-mono text-[10px] text-cyan-200/45">Reading hardware assignments…</p>;
  }

  return (
    <div className="h-full overflow-y-auto p-3 font-mono text-[10px] text-cyan-100/80">
      <div className="mb-3 rounded border border-cyan-300/15 bg-cyan-300/[0.025] p-2.5">
        <div className="flex items-center gap-2 text-cyan-50">
          <Gauge size={13} className="text-cyan-300/70" />
          <span className="uppercase tracking-[0.16em]">Warm defaults</span>
        </div>
        <p className="mt-1 text-[8px] leading-4 text-cyan-200/45">
          These are loaded when hardware is idle. A Task may temporarily use an allowed device,
          then the displaced default returns.
        </p>
      </div>

      <div className="space-y-2">
        {hardware.slots.map((slot) => {
          const selected = slot.options.find((option) => option.id === slot.selected);
          const busy = changing === slot.id || hardware.switching;
          return (
            <section key={slot.id}
              className="rounded-lg border border-cyan-300/14 bg-[#03101a]/72 p-3 shadow-[0_12px_34px_rgba(0,0,0,0.18)]">
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="flex items-center gap-2 text-[11px] text-cyan-50">
                  {slot.kind === "cpu" ? <Cpu size={14} className="text-violet-300/70" />
                    : <MonitorCog size={14} className="text-cyan-300/70" />}
                  {slot.label}
                </span>
                <span className={`text-[8px] uppercase tracking-[0.14em] ${busy
                  ? "animate-pulse text-amber-200/70"
                  : slot.selected === "none" ? "text-cyan-300/30" : "text-emerald-300/65"}`}>
                  {busy ? "applying" : slot.selected === "none" ? "idle" : "default"}
                </span>
              </div>
              <SensorSuite sensors={slot.sensors} />
              <div className="my-2.5 border-t border-cyan-300/10" />
              <select value={slot.selected} disabled={busy}
                onChange={(event) => void assign(slot.id, event.target.value)}
                aria-label={`${slot.label} default component`}
                className="w-full rounded border border-cyan-300/22 bg-[#020a12] px-2 py-1.5 text-[9px] text-cyan-50 outline-none hover:border-cyan-300/45 disabled:opacity-45">
                {slot.options.map((option) => (
                  <option key={option.id} value={option.id} disabled={!option.available}>
                    {option.label}{option.linked ? " · uses both GPUs" : ""}{!option.available ? " · unavailable" : ""}
                  </option>
                ))}
              </select>
              <p className="mt-1.5 text-[8px] leading-4 text-cyan-200/38">{slot.note}</p>
              {selected?.linked ? (
                <p className="mt-1 text-[8px] text-amber-200/55">Linked assignment: both GPU rows move together.</p>
              ) : null}
            </section>
          );
        })}
      </div>

      <div className="mb-2 mt-4 rounded border border-violet-300/15 bg-violet-300/[0.025] p-2.5">
        <div className="flex items-center gap-2 text-cyan-50">
          <Mic size={13} className="text-violet-300/70" />
          <span className="uppercase tracking-[0.16em]">Inputs and outputs</span>
        </div>
        <p className="mt-1 text-[8px] leading-4 text-violet-100/45">
          Realtime opens the selected microphone and speaker on its next start. Camera selects the physical device used by the live Camera pane and Camera Tools.
        </p>
      </div>

      <div className="space-y-2">
        {hardware.interfaces.map((slot) => {
          const busy = changing === slot.id;
          const selected = slot.options.find((option) => option.id === slot.selected);
          const Icon = slot.kind === "input" ? Mic : slot.kind === "output" ? Volume2 : Camera;
          return (
            <section key={slot.id}
              className="rounded-lg border border-violet-300/14 bg-[#080b18]/72 p-3 shadow-[0_12px_34px_rgba(0,0,0,0.18)]">
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className="flex items-center gap-2 text-[11px] text-cyan-50">
                  <Icon size={14} className="text-violet-300/72" /> {slot.label}
                </span>
                <span className={`text-[8px] uppercase tracking-[0.14em] ${busy
                  ? "animate-pulse text-amber-200/70"
                  : selected?.available ? "text-emerald-300/65" : "text-rose-300/65"}`}>
                  {busy ? "saving" : selected?.available ? "available" : "missing"}
                </span>
              </div>
              <select value={slot.selected} disabled={busy}
                onChange={(event) => void assignInterface(slot.id, event.target.value)}
                aria-label={slot.label}
                className="w-full rounded border border-violet-300/22 bg-[#020a12] px-2 py-1.5 text-[9px] text-cyan-50 outline-none hover:border-violet-300/45 disabled:opacity-45">
                {slot.options.map((option) => (
                  <option key={option.id} value={option.id} disabled={!option.available}>
                    {option.label}{!option.available ? " · unavailable" : ""}
                  </option>
                ))}
              </select>
              <p className="mt-1 text-[8px] text-violet-100/38">{selected?.detail}</p>
              <p className="mt-1 text-[8px] leading-4 text-cyan-200/38">{slot.note}</p>
            </section>
          );
        })}
      </div>

      <section className="mt-4 rounded-lg border border-cyan-300/16 bg-[#03101a]/72 p-3">
        <div className="flex items-center gap-2 text-[11px] text-cyan-50">
          <AudioLines size={14} className="text-cyan-300/72" /> Fixed Realtime speech
        </div>
        <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[8px]">
          <p className="text-cyan-200/42">Transport</p><p className="text-right text-cyan-50/70">{hardware.speech.transport}</p>
          <p className="text-cyan-200/42">Turn taking</p><p className="text-right text-cyan-50/70">{hardware.speech.turn_taking}</p>
          <p className="text-cyan-200/42">Streaming ASR</p><p className="text-right text-cyan-50/70">{hardware.speech.asr}</p>
          <p className="text-cyan-200/42">ASR hardware</p><p className="text-right text-cyan-50/70">{hardware.speech.asr_device} · {hardware.speech.asr_chunk_ms} ms</p>
          <p className="text-cyan-200/42">Speech output</p><p className="text-right text-cyan-50/70">{hardware.speech.tts} · {hardware.speech.tts_device}</p>
        </div>
        <label className="mt-2 block text-[8px] uppercase tracking-[0.13em] text-cyan-200/45">Voice</label>
        <select value={hardware.speech.voice} disabled={changing === "speech-voice"}
          onChange={(event) => void assignVoice(event.target.value)}
          className="mt-1 w-full rounded border border-cyan-300/22 bg-[#020a12] px-2 py-1.5 text-[9px] text-cyan-50 outline-none hover:border-cyan-300/45 disabled:opacity-45">
          {(hardware.speech.voices ?? []).map((voice) => <option key={voice.id} value={voice.id}>{voice.label}</option>)}
        </select>
        <p className="mt-1.5 text-[8px] leading-4 text-cyan-200/38">
          The speech engine is infrastructure, not a Task model. Only the character voice is selectable.
        </p>
      </section>

      <div className="mt-3 rounded border border-violet-300/12 bg-violet-300/[0.025] p-2 text-[8px] leading-4 text-violet-100/50">
        Hardware sensors are read-only and local. Audio and Camera selectors choose exact physical endpoints; opening Camera shows a local video-only view.
        Model and reasoning remain per-Task choices in the Task Reader.
      </div>
      {error ? <p className="mt-2 text-[9px] text-rose-300/85">{error}</p> : null}
    </div>
  );
}
