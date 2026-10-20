/** The looping showcase: activity and Action Trace frames recorded from the
 *  real Harness emitters (generate.py), replayed through the demo sockets on
 *  the page's clock. Each replay gets fresh run identities and timestamps. */
import { DemoSocket, registerSocketHub } from "./runtime";

export type View = "knowledge" | "memory" | "code";
type Json = Record<string, any>;
export interface TourData {
  question: string; recall_question: string; code_query: string;
  segments: { view: View; start?: number; answer?: string; memories?: { text: string; type: string; date: string }[] }[];
  frames: { t: number; frame: Json }[];
  trace: { t: number; entry: Json }[];
  packet_refs: string[]; code_refs: string[];
}
export interface TourState { segment: number; view: View; playing: boolean; progress: number; replay: number }

/** Lead: time for a freshly shown graph to settle before its moment begins. */
const TIMING: Record<View, { lead: number; length: number }> = {
  knowledge: { lead: 5_000, length: 13_500 },
  memory: { lead: 3_500, length: 9_500 },
  code: { lead: 3_000, length: 10_000 },
};
const HISTORY = 100, TRACE_HISTORY = 500, TICK_MS = 50;
/** Presentation cues inside a moment (ms after it began), handled by the chrome. */
const CUES: { view: View; at: number; name: string }[] = [
  // After the turn's last trace entry: unfold its Hindsight recall into memory cards.
  { view: "knowledge", at: TIMING.knowledge.lead + 4_000, name: "recall-cards" },
];

function retime(value: Json | undefined, recordedAt: number, now: number, keys: string[]): void {
  if (!value) return;
  for (const key of keys) {
    if (typeof value[key] === "number" && value[key] > 0) value[key] = now + (value[key] - recordedAt);
  }
}

export class Tour {
  private segments: { view: View; frames: TourData["frames"]; trace: TourData["trace"]; base: number }[];
  private segment = 0;
  private elapsed = 0;
  private next = { frame: 0, trace: 0 };
  private replay = 0;
  private playing = true;
  private visible = true;
  private last = performance.now();
  private timer: ReturnType<typeof setInterval>;
  private listeners = new Set<(state: TourState) => void>();
  private progressListeners = new Set<(progress: number) => void>();
  private cueListeners = new Set<(name: string) => void>();
  private nextCue = 0;
  private shown = "";
  // The demo Harness's retained stream, as its real endpoints keep it.
  private history: Json[] = [];
  private playback: Json = { status: "idle", level: 0, run_id: "", playback_id: "" };
  private operations = new Map<string, Json>();
  private traceEntries: Json[] = [];
  private activitySockets = new Set<DemoSocket>();
  private traceSockets = new Set<DemoSocket>();

  constructor(readonly data: TourData) {
    const bases = data.segments.map(segment => segment.start ?? 0);
    this.segments = data.segments.map((segment, index) => {
      const low = bases[index], high = bases[index + 1] ?? Infinity;
      return { view: segment.view, base: low,
        frames: data.frames.filter(entry => entry.t >= low && entry.t < high),
        trace: data.trace.filter(entry => entry.t >= low && entry.t < high) };
    });
    registerSocketHub("/ws/activity", {
      attach: socket => {
        this.activitySockets.add(socket);
        this.pruneOperations();
        socket.deliver({ type: "snapshot", entries: this.history, playback: this.playback,
          operations: [...this.operations.values()] });
      },
      detach: socket => { this.activitySockets.delete(socket); },
    });
    registerSocketHub("/ws/trace", {
      attach: (socket, url) => {
        this.traceSockets.add(socket);
        const after = Number(url.searchParams.get("after"));
        const cursor = this.traceEntries.at(-1)?.seq ?? 0;
        const replay = url.searchParams.has("after") && Number.isSafeInteger(after) && after <= cursor
          && after >= (this.traceEntries[0]?.seq ?? 1) - 1;
        socket.deliver({ type: replay ? "replay" : "snapshot", cursor, gap: false, journal_available: true,
          entries: replay ? this.traceEntries.filter(entry => entry.seq > after) : this.traceEntries });
      },
      detach: socket => { this.traceSockets.delete(socket); },
    });
    this.timer = setInterval(() => this.tick(), TICK_MS);
  }

  state(): TourState {
    const timing = TIMING[this.segments[this.segment].view];
    return { segment: this.segment, view: this.segments[this.segment].view, playing: this.playing,
      progress: Math.min(1, this.elapsed / (timing.lead + timing.length)), replay: this.replay };
  }

  /** Moment, view and play state changes. */
  subscribe(listener: (state: TourState) => void): () => void {
    this.listeners.add(listener);
    listener(this.state());
    return () => { this.listeners.delete(listener); };
  }

  onCue(listener: (name: string) => void): () => void {
    this.cueListeners.add(listener);
    return () => { this.cueListeners.delete(listener); };
  }

  /** The current moment's progress, every tick. */
  onProgress(listener: (progress: number) => void): () => void {
    this.progressListeners.add(listener);
    listener(this.state().progress);
    return () => { this.progressListeners.delete(listener); };
  }

  /** Pause ends any spoken reply; playing again starts the current moment over. */
  setPlaying(playing: boolean): void {
    if (playing === this.playing) return;
    this.playing = playing;
    if (!playing) this.quiet();
    else this.restartSegment(this.segment);
    this.notify();
  }

  /** Off screen or hidden: hold the tour as a pause does, and resume when shown. */
  setVisible(visible: boolean): void {
    if (visible === this.visible) return;
    this.visible = visible;
    if (!visible) this.quiet();
    else if (this.playing) this.restartSegment(this.segment);
  }

  play(segment = 0): void {
    this.playing = true;
    this.restartSegment(segment);
    this.notify();
  }

  dispose(): void { clearInterval(this.timer); }

  private restartSegment(segment: number): void {
    this.segment = segment;
    this.elapsed = 0;
    this.next = { frame: 0, trace: 0 };
    this.nextCue = 0;
    this.replay += 1;
    this.last = performance.now();
  }

  private notify(): void {
    const state = this.state(), key = `${state.segment}:${state.playing}:${state.replay}`;
    for (const listener of this.progressListeners) listener(state.progress);
    if (key === this.shown) return;
    this.shown = key;
    for (const listener of this.listeners) listener(state);
  }

  private quiet(): void {
    if (this.playback.status === "idle") return;
    this.publishActivity({ type: "playback", playback: { ...this.playback, status: "idle", level: 0, at: Date.now() } });
  }

  private tick(): void {
    const now = performance.now(), step = now - this.last;
    this.last = now;
    if (!this.playing || !this.visible) return;
    this.elapsed += Math.min(step, 250);
    const current = this.segments[this.segment], timing = TIMING[current.view];
    const due = current.base + this.elapsed - timing.lead;
    while (this.next.frame < current.frames.length && current.frames[this.next.frame].t <= due)
      this.deliverFrame(current.frames[this.next.frame++]);
    while (this.next.trace < current.trace.length && current.trace[this.next.trace].t <= due)
      this.deliverTrace(current.trace[this.next.trace++]);
    const cues = CUES.filter(cue => cue.view === current.view);
    while (this.nextCue < cues.length && cues[this.nextCue].at <= this.elapsed) {
      const name = cues[this.nextCue++].name;
      for (const listener of this.cueListeners) listener(name);
    }
    if (this.elapsed >= timing.lead + timing.length) {
      this.restartSegment((this.segment + 1) % this.segments.length);
    }
    this.notify();
  }

  /** Recorded identities get this replay's suffix, so the UI sees a new turn. */
  private fresh<T>(value: T): T {
    const suffix = (this.replay % 0x10000).toString(16).padStart(4, "0");
    return JSON.parse(JSON.stringify(value).replace(/(?<![-\w])([0-9a-f]{28})[0-9a-f]{4}(?![-\w])/g, `$1${suffix}`));
  }

  private deliverFrame({ t, frame }: TourData["frames"][number]): void {
    const copy = this.fresh(frame), now = Date.now();
    if (copy.type === "operation") retime(copy.operation, t, now, ["at", "started_at", "expires_at"]);
    else if (copy.type === "playback") retime(copy.playback, t, now, ["at"]);
    else retime(copy, t, now, ["at"]);
    this.publishActivity(copy);
  }

  private publishActivity(frame: Json): void {
    if (frame.type === "operation") {
      this.operations.delete(frame.operation.id);
      this.operations.set(frame.operation.id, frame.operation);
      this.pruneOperations();
    } else if (frame.type === "playback") {
      this.playback = frame.playback;
    } else {
      const { type: _type, ...entry } = frame;
      this.history = [...this.history, entry].slice(-HISTORY);
    }
    for (const socket of this.activitySockets) socket.deliver(frame);
  }

  private pruneOperations(): void {
    const now = Date.now();
    for (const [id, operation] of this.operations)
      if (operation.expires_at && now >= operation.expires_at) this.operations.delete(id);
  }

  private deliverTrace({ t, entry }: TourData["trace"][number]): void {
    const copy = this.fresh(entry);
    retime(copy, t, Date.now(), ["at"]);
    copy.seq = entry.seq + this.replay * 1000;
    this.traceEntries = [...this.traceEntries, copy].slice(-TRACE_HISTORY);
    for (const socket of this.traceSockets) socket.deliver({ type: "entry", entry: copy, cursor: copy.seq });
  }
}
