// Obsidience style-option portraits: native <option> rows cannot contain
// canvases, so the five node-style fields use this compact visual listbox.
import { useEffect, useRef, useState, type ReactNode } from "react";
import type {
  Knowledge3dTuning,
  Knowledge3dTuningField,
} from "@/components/themes/obsidience/knowledge-3d";

const SIZE = 22;
const CYAN = "#67e8f9";
const DEEP = "#155e75";
type Painter = (ctx: CanvasRenderingContext2D, size: number) => void;

function glow(ctx: CanvasRenderingContext2D, size: number, radius: number, color: string, alpha: number) {
  const gradient = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, radius);
  gradient.addColorStop(0, color);
  gradient.addColorStop(1, "rgba(0,0,0,0)");
  ctx.globalAlpha = alpha;
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, size, size);
  ctx.globalAlpha = 1;
}

function disc(ctx: CanvasRenderingContext2D, size: number) {
  const radius = size * 0.34;
  const gradient = ctx.createRadialGradient(
    size / 2 - radius * 0.3, size / 2 - radius * 0.34, radius * 0.1,
    size / 2, size / 2, radius,
  );
  gradient.addColorStop(0, "#f0f9ff");
  gradient.addColorStop(0.35, CYAN);
  gradient.addColorStop(1, DEEP);
  ctx.fillStyle = gradient;
  ctx.beginPath();
  ctx.arc(size / 2, size / 2, radius, 0, Math.PI * 2);
  ctx.fill();
}

function ring(ctx: CanvasRenderingContext2D, size: number, radius: number, dashed = false) {
  ctx.strokeStyle = CYAN;
  ctx.lineWidth = 1.4;
  ctx.setLineDash(dashed ? [3, 2] : []);
  ctx.beginPath();
  ctx.arc(size / 2, size / 2, radius, 0, Math.PI * 2);
  ctx.stroke();
  ctx.setLineDash([]);
}

function flare(ctx: CanvasRenderingContext2D, size: number, span: number) {
  ctx.strokeStyle = "rgba(255,255,255,0.85)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(size / 2 - span, size / 2);
  ctx.lineTo(size / 2 + span, size / 2);
  ctx.moveTo(size / 2, size / 2 - span);
  ctx.lineTo(size / 2, size / 2 + span);
  ctx.stroke();
}

function tile(ctx: CanvasRenderingContext2D, size: number, rounded: boolean, hollow = false) {
  const inset = size * 0.18;
  const side = size - inset * 2;
  const gradient = ctx.createLinearGradient(inset, inset, size - inset, size - inset);
  gradient.addColorStop(0, "#ecfeff");
  gradient.addColorStop(0.35, CYAN);
  gradient.addColorStop(1, DEEP);
  ctx.beginPath();
  ctx.roundRect(inset, inset, side, side, rounded ? size * 0.13 : size * 0.025);
  ctx.fillStyle = gradient;
  ctx.globalAlpha = hollow ? 0.16 : 0.9;
  ctx.fill();
  ctx.globalAlpha = 1;
  ctx.strokeStyle = CYAN;
  ctx.lineWidth = 1.35;
  ctx.stroke();
}

function dataMarks(ctx: CanvasRenderingContext2D, size: number) {
  ctx.strokeStyle = "rgba(207,250,254,0.78)";
  ctx.lineWidth = 0.8;
  for (const offset of [-0.13, 0.13]) {
    ctx.beginPath();
    ctx.moveTo(size * 0.3, size * (0.5 + offset));
    ctx.lineTo(size * 0.7, size * (0.5 + offset));
    ctx.stroke();
  }
}

const SUBJECT: Painter[] = [
  (ctx, size) => { disc(ctx, size); ring(ctx, size, size * 0.44); },
  (ctx, size) => { glow(ctx, size, size * 0.48, CYAN, 0.9); glow(ctx, size, size * 0.2, "#fff", 0.9); },
  (ctx, size) => { disc(ctx, size); glow(ctx, size, size * 0.16, "#fff", 1); flare(ctx, size, size * 0.3); },
  (ctx, size) => { ctx.globalAlpha = 0.18; disc(ctx, size); ctx.globalAlpha = 1; ring(ctx, size, size * 0.4); },
  (ctx, size) => { glow(ctx, size, size * 0.48, CYAN, 0.45); tile(ctx, size, true); },
  (ctx, size) => { tile(ctx, size, false, true); dataMarks(ctx, size); },
];

const ARTICLE: Painter[] = [
  (ctx, size) => { glow(ctx, size, size * 0.46, CYAN, 0.8); glow(ctx, size, size * 0.14, "#fff", 1); flare(ctx, size, size * 0.42); },
  (ctx, size) => { glow(ctx, size, size * 0.46, CYAN, 0.8); glow(ctx, size, size * 0.14, "#fff", 1); },
  disc,
  (ctx, size) => { glow(ctx, size, size * 0.34, "#fcd34d", 0.85); glow(ctx, size, size * 0.12, "#fff7ed", 1); },
  (ctx, size) => { glow(ctx, size, size * 0.46, CYAN, 0.65); tile(ctx, size, true); flare(ctx, size, size * 0.26); },
  (ctx, size) => { tile(ctx, size, false); dataMarks(ctx, size); },
];

const RINGS: Painter[] = [
  (ctx, size) => { ctx.globalAlpha = 0.35; disc(ctx, size); ctx.globalAlpha = 1; ring(ctx, size, size * 0.42); },
  (ctx, size) => { ctx.globalAlpha = 0.35; disc(ctx, size); ctx.globalAlpha = 1; ring(ctx, size, size * 0.42, true); },
  (ctx, size) => { ctx.globalAlpha = 0.35; disc(ctx, size); ctx.globalAlpha = 1; ring(ctx, size, size * 0.44); ring(ctx, size, size * 0.32); },
  (ctx, size) => { ctx.globalAlpha = 0.55; disc(ctx, size); ctx.globalAlpha = 1; },
];

const CORE: Painter[] = [
  (ctx, size) => {
    glow(ctx, size, size * 0.46, CYAN, 0.75);
    ctx.strokeStyle = "rgba(255,255,255,0.75)";
    ctx.lineWidth = 1;
    for (let index = 0; index < 3; index += 1) {
      ctx.beginPath();
      ctx.arc(size / 2 + (index - 1) * 2, size / 2 + ((index * 7) % 3) - 1,
        size * (0.18 + index * 0.08), index * 1.9, index * 1.9 + 2.4);
      ctx.stroke();
    }
  },
  (ctx, size) => { glow(ctx, size, size * 0.44, CYAN, 0.7); glow(ctx, size, size * 0.18, "#fff", 0.9); },
  (ctx, size) => {
    glow(ctx, size, size * 0.42, CYAN, 0.6);
    ctx.strokeStyle = "rgba(255,255,255,0.8)";
    ctx.lineWidth = 1.1;
    for (let arm = 0; arm < 2; arm += 1) {
      ctx.beginPath();
      for (let step = 0; step <= 12; step += 1) {
        const progress = step / 12;
        const angle = arm * Math.PI + progress * 3.4;
        const radius = progress * size * 0.4;
        const x = size / 2 + Math.cos(angle) * radius;
        const y = size / 2 + Math.sin(angle) * radius;
        if (step === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }
  },
  (ctx, size) => {
    glow(ctx, size, size * 0.2, "#fff", 0.95);
    ctx.strokeStyle = "rgba(165,243,252,0.8)";
    ctx.lineWidth = 1;
    for (const radius of [0.18, 0.3, 0.42]) {
      ctx.beginPath();
      ctx.arc(size / 2, size / 2, size * radius, 0, Math.PI * 2);
      ctx.stroke();
    }
  },
  (ctx, size) => {
    const center = size / 2;
    const radius = size * 0.4;
    const vertex = (angle: number) => ({
      x: center + Math.cos(angle) * radius,
      y: center - Math.sin(angle) * radius,
    });
    ctx.strokeStyle = "rgba(110,231,183,0.9)";
    ctx.fillStyle = "rgba(52,211,153,0.28)";
    ctx.lineWidth = 1.1;
    ctx.beginPath();
    for (let index = 0; index < 6; index += 1) {
      const point = vertex((30 + index * 60) * Math.PI / 180);
      if (index === 0) ctx.moveTo(point.x, point.y); else ctx.lineTo(point.x, point.y);
    }
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    for (const angle of [30, 150, 270]) {
      const point = vertex(angle * Math.PI / 180);
      ctx.beginPath();
      ctx.moveTo(center, center);
      ctx.lineTo(point.x, point.y);
      ctx.stroke();
    }
  },
];

const PAINTERS: Partial<Record<keyof Knowledge3dTuning, Painter[]>> = {
  subjectStyle: SUBJECT,
  subnodeStyle: SUBJECT,
  articleStyle: ARTICLE,
  ringStyle: RINGS,
  coreStyle: CORE,
};

function StylePortrait({ fieldKey, optionIndex }: {
  fieldKey: keyof Knowledge3dTuning;
  optionIndex: number;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const element = canvas.current;
    const painter = PAINTERS[fieldKey]?.[optionIndex];
    const context = element?.getContext("2d");
    if (!element || !painter || !context) return;
    context.clearRect(0, 0, SIZE, SIZE);
    painter(context, SIZE);
  }, [fieldKey, optionIndex]);
  return <canvas ref={canvas} width={SIZE} height={SIZE} className="shrink-0 rounded bg-[#02070c]" aria-hidden="true" />;
}

export function StyleSelect({ field, value, onChange }: {
  field: Knowledge3dTuningField;
  value: number;
  onChange: (next: number) => void;
}) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const pointer = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) setOpen(false);
    };
    const keyboard = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("pointerdown", pointer);
    window.addEventListener("keydown", keyboard);
    return () => {
      window.removeEventListener("pointerdown", pointer);
      window.removeEventListener("keydown", keyboard);
    };
  }, [open]);
  const options = field.options ?? [];
  const row = (index: number): ReactNode => (
    <><StylePortrait fieldKey={field.key} optionIndex={index} /><span className="truncate">{options[index]}</span></>
  );
  return (
    <div ref={root} className="relative">
      <button type="button" onClick={() => setOpen((current) => !current)} aria-haspopup="listbox"
        aria-expanded={open} aria-label={field.label} title={field.description}
        className="mt-1 flex w-full items-center gap-2 rounded border border-cyan-300/25 bg-[#061019] px-2 py-1 text-left font-mono text-[10px] uppercase tracking-wider text-cyan-100">
        {row(value)}<span className="ml-auto text-cyan-300/50">▾</span>
      </button>
      {open ? (
        <div role="listbox" aria-label={field.label}
          className="absolute left-0 right-0 z-30 mt-1 rounded border border-cyan-300/30 bg-[#030a10]/97 p-1 shadow-[0_0_25px_rgba(34,211,238,0.12)] backdrop-blur">
          {options.map((option, index) => (
            <button key={option} type="button" role="option" aria-selected={index === value}
              onClick={() => { setOpen(false); if (index !== value) onChange(index); }}
              className={`flex w-full items-center gap-2 rounded px-2 py-1 text-left font-mono text-[10px] uppercase tracking-wider ${index === value ? "bg-cyan-300/15 text-cyan-100" : "text-cyan-200/70 hover:bg-cyan-300/8 hover:text-cyan-100"}`}>
              {row(index)}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
