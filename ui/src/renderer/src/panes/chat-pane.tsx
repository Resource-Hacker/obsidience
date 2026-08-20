/** Operator chat: WS streaming + push-to-talk STT + Kokoro TTS. */

import { useCallback, useEffect, useRef, useState } from "react";
import { Mic, Send, Square, Volume2, VolumeX } from "lucide-react";
import { JarvisMarkdown } from "@/components/themes/jarvis/workspace/jarvis-markdown";
import { WS_BASE, api } from "@/lib/api";

interface Turn { role: "user" | "assistant"; text: string }

export function ChatPaneBody() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [speak, setSpeak] = useState(true);
  const [recording, setRecording] = useState(false);
  const [sttAvailable, setSttAvailable] = useState(false);
  const ws = useRef<WebSocket | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const audioEl = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    api.status().then((s) => setSttAvailable(Boolean(s.voice?.stt))).catch(() => undefined);
  }, []);

  const ensureSocket = useCallback((): WebSocket => {
    if (ws.current && ws.current.readyState === WebSocket.OPEN) return ws.current;
    const sock = new WebSocket(`${WS_BASE}/ws/chat`);
    sock.onmessage = (ev) => {
      const msg = JSON.parse(ev.data as string) as { type: string; text?: string };
      if (msg.type === "start") {
        setTurns((t) => [...t, { role: "assistant", text: "" }]);
      } else if (msg.type === "delta") {
        setTurns((t) => {
          const next = [...t];
          next[next.length - 1] = { role: "assistant", text: next[next.length - 1].text + (msg.text ?? "") };
          return next;
        });
      } else if (msg.type === "end") {
        setBusy(false);
        if (speakRef.current && msg.text) void speakText(msg.text);
      }
    };
    sock.onclose = () => { ws.current = null; setBusy(false); };
    ws.current = sock;
    return sock;
  }, []);

  const speakRef = useRef(speak);
  speakRef.current = speak;

  async function speakText(text: string) {
    const bridge = window.obsidience;
    if (!bridge) return;
    try {
      const wav = await bridge.synthesize(text.replace(/\[\[|\]\]/g, "").slice(0, 1200));
      const blob = new Blob([wav], { type: "audio/wav" });
      audioEl.current?.pause();
      const audio = new Audio(URL.createObjectURL(blob));
      audioEl.current = audio;
      void audio.play();
    } catch {
      /* TTS unavailable — text is already on screen */
    }
  }

  const send = useCallback((text: string) => {
    const clean = text.trim();
    if (!clean || busy) return;
    setTurns((t) => [...t, { role: "user", text: clean }]);
    setDraft("");
    setBusy(true);
    const sock = ensureSocket();
    const payload = JSON.stringify({ text: clean });
    if (sock.readyState === WebSocket.OPEN) sock.send(payload);
    else sock.onopen = () => sock.send(payload);
  }, [busy, ensureSocket]);

  async function toggleMic() {
    if (recording) {
      recorder.current?.stop();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const rec = new MediaRecorder(stream, { mimeType: "audio/webm" });
      const chunks: Blob[] = [];
      rec.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
      rec.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setRecording(false);
        try {
          const text = await api.transcribe(new Blob(chunks, { type: "audio/webm" }));
          if (text) send(text);
        } catch {
          setTurns((t) => [...t, { role: "assistant", text: "_(transcription failed)_" }]);
        }
      };
      rec.start();
      recorder.current = rec;
      setRecording(true);
    } catch {
      setSttAvailable(false);
    }
  }

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
  }, [turns]);

  return (
    <div className="flex h-full flex-col">
      <div ref={scroller} className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3">
        {turns.length === 0 ? (
          <p className="font-mono text-[11px] leading-relaxed text-cyan-200/50">
            The Operator answers from the vault. Ask about tasks, runbooks, or anything indexed.
          </p>
        ) : turns.map((t, i) => (
          <div key={i} className={t.role === "user" ? "text-right" : ""}>
            <div className={`inline-block max-w-[92%] rounded-lg border px-3 py-2 text-left text-[12.5px] leading-relaxed ${
              t.role === "user"
                ? "border-cyan-300/30 bg-cyan-400/10 text-cyan-50"
                : "border-cyan-300/15 bg-[#051018]/80 text-cyan-100/90"}`}>
              <JarvisMarkdown content={t.text || "…"} />
            </div>
          </div>
        ))}
      </div>
      <div className="flex shrink-0 items-end gap-2 border-t border-cyan-300/15 p-2">
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(draft); }
          }}
          rows={2}
          placeholder={busy ? "…" : "Speak to the vault"}
          className="min-h-0 flex-1 resize-none rounded border border-cyan-300/20 bg-[#03101a]/80 px-2 py-1.5 font-mono text-[12px] text-cyan-50 outline-none placeholder:text-cyan-200/30 focus:border-cyan-300/50"
        />
        {sttAvailable ? (
          <button onClick={toggleMic} title={recording ? "Stop and transcribe" : "Push to talk"}
            className={`rounded border p-2 transition-colors ${recording
              ? "border-rose-400/60 bg-rose-500/20 text-rose-200"
              : "border-cyan-300/25 text-cyan-300/70 hover:bg-cyan-300/10"}`}>
            {recording ? <Square size={14} /> : <Mic size={14} />}
          </button>
        ) : null}
        <button onClick={() => setSpeak((s) => !s)} title="Speak replies (Kokoro)"
          className={`rounded border p-2 ${speak ? "border-cyan-300/40 text-cyan-100" : "border-cyan-300/15 text-cyan-300/40"}`}>
          {speak ? <Volume2 size={14} /> : <VolumeX size={14} />}
        </button>
        <button onClick={() => send(draft)} disabled={busy}
          className="rounded border border-cyan-300/25 p-2 text-cyan-300/70 hover:bg-cyan-300/10 disabled:opacity-40">
          <Send size={14} />
        </button>
      </div>
    </div>
  );
}
