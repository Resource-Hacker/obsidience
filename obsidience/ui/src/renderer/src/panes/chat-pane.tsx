/** The Executive conversation shared by text and Realtime speech. */

import { useCallback, useEffect, useRef, useState } from "react";
import { Plus, Send } from "lucide-react";
import { ArticleMarkdown } from "@/components/themes/obsidience/workspace/article-markdown";
import { WS_BASE } from "@/lib/api";

interface Turn {
  id: string;
  conversation_id: string;
  sequence: number;
  role: "user" | "assistant";
  source: "text" | "realtime";
  text: string;
  run_id?: string | null;
  state: string;
  created_at: number;
}

interface ContextUsage {
  conversation_id: string;
  used_tokens: number;
  capacity_tokens: number;
  percent: number;
  compact_at: number;
  compacting: boolean;
}

function mergeTurn(current: Turn[], turn: Turn): Turn[] {
  const byId = new Map(current.map((item) => [item.id, item]));
  byId.set(turn.id, turn);
  return [...byId.values()].sort((left, right) => left.sequence - right.sequence);
}

export function ChatPaneBody() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [context, setContext] = useState<ContextUsage | null>(null);
  const [compactAt, setCompactAt] = useState(80);
  const ws = useRef<WebSocket | null>(null);
  const conversationId = useRef<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let closed = false;
    let retry: ReturnType<typeof setTimeout> | null = null;
    const connect = () => {
      if (closed) return;
      const sock = new WebSocket(`${WS_BASE}/ws/chat`);
      ws.current = sock;
      sock.onopen = () => setConnected(true);
      sock.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data as string) as {
            type: string;
            conversation_id?: string;
            turns?: Turn[];
            turn?: Turn;
            used_tokens?: number;
            capacity_tokens?: number;
            percent?: number;
            compact_at?: number;
            compacting?: boolean;
          };
          if (message.type === "history" && message.conversation_id && message.turns) {
            conversationId.current = message.conversation_id;
            setTurns(message.turns.reduce<Turn[]>((current, turn) => mergeTurn(current, turn), []));
            setResetting(false);
          } else if (message.type === "turn" && message.turn) {
            if (message.turn.conversation_id === conversationId.current) {
              setTurns((current) => mergeTurn(current, message.turn!));
            }
          } else if (message.type === "context" && message.conversation_id === conversationId.current) {
            const next: ContextUsage = {
              conversation_id: message.conversation_id,
              used_tokens: message.used_tokens ?? 0,
              capacity_tokens: message.capacity_tokens ?? 0,
              percent: message.percent ?? 0,
              compact_at: message.compact_at ?? 80,
              compacting: message.compacting ?? false,
            };
            setContext(next);
            setCompactAt(next.compact_at);
          } else if (message.type === "start") {
            setBusy(true);
          } else if (message.type === "end") {
            setBusy(false);
          }
        } catch {
          // Ignore malformed status frames; the canonical history stays intact.
        }
      };
      sock.onclose = () => {
        if (ws.current === sock) ws.current = null;
        setConnected(false);
        setBusy(false);
        setResetting(false);
        if (!closed) retry = setTimeout(connect, 1_000);
      };
    };
    connect();
    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      ws.current?.close();
      ws.current = null;
    };
  }, []);

  const send = useCallback((text: string) => {
    const clean = text.trim();
    const socket = ws.current;
    if (!clean || busy || resetting || socket?.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ text: clean, source: "text" }));
    setDraft("");
    setBusy(true);
  }, [busy, resetting]);

  const newConversation = useCallback(() => {
    const socket = ws.current;
    if (busy || resetting || socket?.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ type: "new_conversation" }));
    setResetting(true);
  }, [busy, resetting]);

  const changeCompactThreshold = useCallback((percent: number) => {
    const socket = ws.current;
    if (busy || resetting || context?.compacting || socket?.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ type: "set_compact_threshold", percent }));
    setCompactAt(percent);
  }, [busy, context?.compacting, resetting]);

  const compact = useCallback(() => {
    const socket = ws.current;
    if (busy || resetting || context?.compacting || socket?.readyState !== WebSocket.OPEN) return;
    socket.send(JSON.stringify({ type: "compact" }));
    setContext((current) => current ? { ...current, compacting: true } : current);
  }, [busy, context?.compacting, resetting]);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
  }, [turns]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 justify-end border-b border-cyan-300/10 px-2 py-1.5">
        <button onClick={newConversation} disabled={!connected || busy || resetting}
          className="flex items-center gap-1 rounded border border-cyan-300/20 px-2 py-1 font-mono text-[10px] uppercase tracking-[0.12em] text-cyan-200/60 hover:bg-cyan-300/10 disabled:opacity-35">
          <Plus size={11} /> New conversation
        </button>
      </div>
      <div ref={scroller} className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        {turns.length === 0 ? <p className="font-mono text-[11px] leading-relaxed text-cyan-200/50">
          Executive answers from the vault. Realtime speech appears here automatically.
        </p> : turns.map((turn) => (
          <div key={turn.id} className={turn.role === "user" ? "text-right" : ""}>
            <div className={`inline-block max-w-[92%] rounded-lg border px-3 py-2 text-left text-[12.5px] leading-relaxed ${turn.role === "user"
              ? "border-cyan-300/30 bg-cyan-400/10 text-cyan-50"
              : "border-cyan-300/15 bg-[#051018]/80 text-cyan-100/90"}`}>
              <ArticleMarkdown content={turn.text || "…"} />
            </div>
          </div>
        ))}
      </div>
      <div className="shrink-0 border-t border-cyan-300/15 p-2">
        <div className="mb-1.5 flex items-center gap-2 font-mono text-[9px] uppercase tracking-[0.1em] text-cyan-200/45"
          title={`Immediate Observations: ${context?.used_tokens ?? 0} / ${context?.capacity_tokens ?? 0} tokens`}>
          <span>Immediate</span>
          <div className="h-1 min-w-12 flex-1 overflow-hidden rounded-full bg-cyan-950/80">
            <div className="h-full bg-cyan-300/60 transition-[width]"
              style={{ width: `${Math.max(0, Math.min(100, context?.percent ?? 0))}%` }} />
          </div>
          <span>{Math.round(context?.percent ?? 0)}%</span>
          <span className="text-cyan-200/30">Compact at</span>
          <select value={compactAt}
            onChange={(event) => changeCompactThreshold(Number(event.target.value))}
            disabled={!connected || busy || resetting || context?.compacting}
            aria-label="Automatic compact threshold"
            className="rounded border border-cyan-300/15 bg-[#03101a] px-1 py-0.5 text-[9px] text-cyan-100/65 outline-none disabled:opacity-35">
            {[60, 70, 80, 90].map((percent) => <option key={percent} value={percent}>{percent}%</option>)}
          </select>
        </div>
        <div className="flex items-end gap-2">
          <textarea value={draft} onChange={(event) => setDraft(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); send(draft); } }}
            rows={2} placeholder={busy || resetting ? "…" : "Speak to the vault"}
            className="min-h-0 flex-1 resize-none rounded border border-cyan-300/20 bg-[#03101a]/80 px-2 py-1.5 font-mono text-[12px] text-cyan-50 outline-none placeholder:text-cyan-200/30 focus:border-cyan-300/50" />
          <button onClick={compact} disabled={!connected || busy || resetting || context?.compacting}
            className="rounded border border-cyan-300/20 px-2 py-2 font-mono text-[9px] uppercase tracking-[0.1em] text-cyan-200/55 hover:bg-cyan-300/10 disabled:opacity-35">
            {context?.compacting ? "Compacting…" : "Compact"}
          </button>
          <button onClick={() => send(draft)} disabled={!connected || busy || resetting}
            className="rounded border border-cyan-300/25 p-2 text-cyan-300/70 hover:bg-cyan-300/10 disabled:opacity-40">
            <Send size={14} />
          </button>
        </div>
      </div>
    </div>
  );
}
