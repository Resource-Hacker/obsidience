/** Terminal pane: HEREBRUM-style tmux mirror plus live Obsidience actions. */

import { useEffect, useRef, useState } from "react";
import { FitAddon } from "@xterm/addon-fit";
import { Terminal } from "@xterm/xterm";
import "@xterm/xterm/css/xterm.css";
import { WS_BASE } from "@/lib/api";

interface TraceEntry {
  at: number;
  channel: string;
  line: string;
  detail?: string[];
}

const TRACE_STYLE: Record<string, string> = {
  run: "border-cyan-300/35 text-cyan-200",
  tool: "border-amber-300/40 text-amber-200",
  result: "border-teal-300/35 text-teal-200",
  status: "border-violet-300/35 text-violet-200",
  error: "border-rose-300/45 text-rose-200",
};

function ActionTraceView() {
  const [entries, setEntries] = useState<TraceEntry[]>([]);
  const [connected, setConnected] = useState(false);
  const [follow, setFollow] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let disposed = false;
    let socket: WebSocket | null = null;
    let retry = 0;
    const connect = () => {
      if (disposed) return;
      socket = new WebSocket(`${WS_BASE}/ws/trace`);
      socket.onopen = () => setConnected(true);
      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data) as {
            type: "snapshot" | "entry"; entries?: TraceEntry[]; entry?: TraceEntry;
          };
          if (message.type === "snapshot") setEntries((message.entries ?? []).slice(-500));
          if (message.type === "entry" && message.entry) {
            setEntries((current) => [...current, message.entry!].slice(-500));
          }
        } catch { /* malformed trace frames are ignored */ }
      };
      socket.onclose = () => {
        setConnected(false);
        if (!disposed) retry = window.setTimeout(connect, 1_500);
      };
    };
    connect();
    return () => {
      disposed = true;
      window.clearTimeout(retry);
      socket?.close();
    };
  }, []);

  useEffect(() => {
    if (follow && scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [entries, follow]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-black/40">
      <div className="flex shrink-0 items-center justify-between border-b border-cyan-300/10 px-3 py-1.5">
        <span className="font-mono text-[9px] uppercase tracking-wider text-cyan-300/45">
          {connected ? "Live" : "Reconnecting"} · {entries.length} actions
        </span>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1 font-mono text-[9px] uppercase text-cyan-200/55">
            <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)}
              className="h-3 w-3 accent-cyan-400" /> Follow
          </label>
          <button onClick={() => setEntries([])}
            className="rounded border border-cyan-300/20 px-2 py-0.5 font-mono text-[9px] uppercase text-cyan-200/55 hover:bg-cyan-300/10">
            Clear
          </button>
        </div>
      </div>
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto p-3 font-mono text-[10px] leading-5">
        {entries.length === 0 ? <p className="text-cyan-200/30">Waiting for the next task action.</p> : null}
        {entries.map((entry, index) => (
          <div key={`${entry.at}-${index}`} className="mb-1">
            <div className="flex items-baseline gap-2">
              <span className="shrink-0 text-cyan-300/25">
                {new Date(entry.at).toLocaleTimeString([], { hour12: false })}
              </span>
              <span className={`shrink-0 rounded border px-1 text-[8px] uppercase tracking-wider ${TRACE_STYLE[entry.channel] ?? TRACE_STYLE.status}`}>
                {entry.channel}
              </span>
              <span className="break-words text-cyan-100/80">{entry.line}</span>
            </div>
            {entry.detail?.length ? (
              <div className="ml-[6.8rem] border-l border-cyan-300/20 pl-2 text-cyan-200/45">
                {entry.detail.map((line, i) => <div key={i} className="break-words">{line}</div>)}
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </div>
  );
}

type ConsoleStatus = "connecting" | "live" | "closed" | "error";
const BASE_FONT = 14;
const MIN_FONT = 7;
const BASE_SPACING = 0.25;

function LocalConsoleView() {
  const hostRef = useRef<HTMLDivElement>(null);
  const handleRef = useRef<Awaited<ReturnType<NonNullable<typeof window.obsidience>["openLocalTerminal"]>> | null>(null);
  const [generation, setGeneration] = useState(0);
  const [status, setStatus] = useState<ConsoleStatus>("connecting");
  const [message, setMessage] = useState("Connecting to codex tmux…");

  useEffect(() => {
    const host = hostRef.current;
    const bridge = window.obsidience;
    if (!host || !bridge) return;
    let disposed = false;
    let frame = 0;
    let targetColumns: number | null = null;
    const terminal = new Terminal({
      allowTransparency: true,
      cursorBlink: true,
      fontFamily: '"JetBrains Mono", "Cascadia Mono", "Fira Code", monospace',
      fontSize: BASE_FONT,
      fontWeight: "400",
      fontWeightBold: "700",
      letterSpacing: BASE_SPACING,
      lineHeight: 1.12,
      scrollback: 10_000,
      smoothScrollDuration: 80,
      theme: {
        background: "#020609", foreground: "#b8f7ff", cursor: "#67e8f9",
        selectionBackground: "#155e75aa", black: "#020609", red: "#fb7185",
        green: "#5eead4", yellow: "#fcd34d", blue: "#38bdf8",
        magenta: "#d8b4fe", cyan: "#67e8f9", white: "#e6fbff",
        brightBlack: "#54717a", brightRed: "#fda4af", brightGreen: "#99f6e4",
        brightYellow: "#fde68a", brightBlue: "#7dd3fc", brightMagenta: "#e9d5ff",
        brightCyan: "#a5f3fc", brightWhite: "#ffffff",
      },
    });
    const fitAddon = new FitAddon();
    terminal.loadAddon(fitAddon);
    terminal.open(host);

    const fit = () => {
      if (disposed) return;
      try {
        if (targetColumns === null) {
          fitAddon.fit();
        } else {
          terminal.options.letterSpacing = BASE_SPACING;
          for (let i = 0; i < 5; i += 1) {
            const proposed = fitAddon.proposeDimensions();
            if (!proposed || proposed.cols === targetColumns) break;
            const current = terminal.options.fontSize ?? BASE_FONT;
            const next = Math.max(MIN_FONT, current * (proposed.cols / targetColumns));
            if (Math.abs(next - current) < 0.01) break;
            terminal.options.fontSize = next;
          }
          terminal.options.fontSize = Math.max(MIN_FONT, (terminal.options.fontSize ?? BASE_FONT) * 0.8);
          const proposed = fitAddon.proposeDimensions();
          terminal.resize(targetColumns, Math.max(8, proposed?.rows ?? terminal.rows));
        }
        handleRef.current?.resize({ cols: terminal.cols, rows: terminal.rows });
      } catch { /* layout may be between frames */ }
    };
    const scheduleFit = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(fit);
    };
    const observer = new ResizeObserver(scheduleFit);
    observer.observe(host);
    fit();
    const input = terminal.onData((data) => handleRef.current?.write(data));

    setStatus("connecting");
    void bridge.openLocalTerminal({
      cols: terminal.cols,
      rows: terminal.rows,
      onData: (data) => { if (!disposed) terminal.write(data); },
      onExit: ({ exitCode, signal }) => {
        if (disposed) return;
        handleRef.current = null;
        setStatus("closed");
        setMessage(`Detached (exit ${exitCode}${signal ? `, signal ${signal}` : ""})`);
      },
    }).then((handle) => {
      if (disposed) { handle.close(); return; }
      handleRef.current = handle;
      targetColumns = handle.windowCols;
      setStatus("live");
      setMessage(`${handle.label} · ${handle.linkedSession}`);
      scheduleFit();
      terminal.focus();
    }).catch((error) => {
      if (disposed) return;
      const safe = String(error).replace(/[\r\n]+/g, " ").slice(0, 240);
      setStatus("error");
      setMessage(safe);
      terminal.writeln(`\r\n\x1b[31mTerminal unavailable: ${safe}\x1b[0m`);
    });

    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      observer.disconnect();
      input.dispose();
      handleRef.current?.close();
      handleRef.current = null;
      terminal.dispose();
    };
  }, [generation]);

  return (
    <div className="relative h-full min-h-0 overflow-hidden bg-[#020609]">
      <div ref={hostRef} aria-label="Interactive mirrored Codex terminal"
        className="absolute inset-0 p-1 [text-shadow:0_0_8px_rgba(103,232,249,0.26)]" />
      {(status === "closed" || status === "error") ? (
        <div className="absolute right-2 top-2 flex max-w-[80%] items-center gap-2 rounded border border-rose-300/30 bg-[#071017]/95 px-2 py-1">
          <span className="truncate font-mono text-[9px] text-rose-100/75">{message}</span>
          <button onClick={() => setGeneration((value) => value + 1)}
            className="rounded border border-cyan-300/30 px-2 py-0.5 font-mono text-[9px] uppercase text-cyan-100/75">
            Reconnect
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function TerminalPaneBody() {
  const [view, setView] = useState<"console" | "trace">("console");
  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 gap-1 border-b border-cyan-300/15 bg-slate-950/45 px-2 py-1.5">
        <button onClick={() => setView("console")}
          className={`rounded border px-2.5 py-1 font-mono text-[9px] uppercase tracking-[0.14em] ${view === "console" ? "border-cyan-300/45 bg-cyan-300/10 text-cyan-100" : "border-transparent text-cyan-200/45"}`}>
          Local Console
        </button>
        <button onClick={() => setView("trace")}
          className={`rounded border px-2.5 py-1 font-mono text-[9px] uppercase tracking-[0.14em] ${view === "trace" ? "border-violet-300/40 bg-violet-300/10 text-violet-100" : "border-transparent text-cyan-200/45"}`}>
          Action Trace
        </button>
      </div>
      <div className="min-h-0 flex-1">{view === "console" ? <LocalConsoleView /> : <ActionTraceView />}</div>
    </div>
  );
}
