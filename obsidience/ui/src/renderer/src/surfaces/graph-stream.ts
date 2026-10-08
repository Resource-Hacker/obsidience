import { openGraphPort, type GraphSignal, type GraphSource } from "@/lib/shell-client";
import type { ProviderNode } from "./provider-graph-scene";

export const MEMORY_TYPES: Record<string, string> = {world: "World facts", experience: "Experiences", observation: "Observations"};
export type GraphControl = {action: string; id?: string; graphId?: string; value?: string | boolean; x?: number; y?: number; dx?: number; dy?: number};
export interface GraphCatalog {
  nodes: ProviderNode[]; count: number; links: number;
  banks?: {id: string; name: string; agent_ref: string}[]; limited?: boolean;
  graphs?: {id: string; name: string; count?: number; links?: number}[];
}
export interface GraphViewState {
  graphId?: string; bank?: string; memoryType?: string; allSymbols?: boolean; follow?: boolean; timeRange?: string;
  count?: number; links?: number;
  loading?: boolean; error?: string; connected?: boolean;
  codeFile?: string; codeIndex?: {state: string; updated_at?: string; error?: string};
  externalShown?: number; externalTotal?: number;
  selected?: ProviderNode | null; neighbors?: {node: ProviderNode; kind: string}[];
  hover?: ProviderNode | null; latest?: {label: string; status: string};
}
type Message = {type: "catalog"; value: GraphCatalog} | {type: "state"; value: GraphViewState};
type Peer = {pc: RTCPeerConnection; channel?: RTCDataChannel; ice: RTCIceCandidateInit[]; chain: Promise<void>};
const RTC = {iceServers: []}; // Same-machine peers, no discovery or relay service.
const CHUNK = 8000, MAX_MESSAGE = 16 * 1024 * 1024;
type MessageKind = "catalog" | "state" | "control";

/** Bounded message framing uses the native data channel's backpressure. */
class Messages {
  private queue: {type: MessageKind; parts: string[]; next: number}[] = [];
  private incoming = new Map<MessageKind, {parts: string[]; size: number}>();
  constructor(private channel: RTCDataChannel, receive: (message: any) => void) {
    channel.bufferedAmountLowThreshold = 65536;
    channel.onbufferedamountlow = () => this.flush();
    channel.onmessage = event => {
      if (typeof event.data !== "string" || event.data.length > CHUNK * 6 + 100) return;
      try {
        const part = JSON.parse(event.data);
        if (!["catalog", "state", "control"].includes(part.kind)) return;
        const kind = part.kind as MessageKind;
        if (part.begin === true) this.incoming.set(kind, {parts: [], size: 0});
        const incoming = this.incoming.get(kind);
        if (!incoming || typeof part.text !== "string" || incoming.size + part.text.length > MAX_MESSAGE) { this.incoming.delete(kind); return; }
        incoming.parts.push(part.text); incoming.size += part.text.length;
        if (part.end === true) {
          this.incoming.delete(kind); receive(JSON.parse(incoming.parts.join("")));
        }
      } catch { this.incoming.clear(); }
    };
  }
  send(value: unknown) {
    const encoded = JSON.stringify(value);
    if (encoded.length > MAX_MESSAGE) return;
    const kind = (value as {type?: string})?.type;
    const type: MessageKind = kind === "catalog" || kind === "state" ? kind : "control";
    // Presentation snapshots supersede queued snapshots of the same kind.
    // Each kind has its own bounded framing, so state can interrupt a large
    // catalog without losing either message. Controls remain ordered.
    if (type !== "control") this.queue = this.queue.filter(item => item.next > 0 || item.type !== type);
    else if (this.queue.length >= MAX_MESSAGE / CHUNK) return;
    const parts: string[] = [];
    for (let i = 0; i < encoded.length; i += CHUNK)
      parts.push(JSON.stringify({kind: type, begin: i === 0, text: encoded.slice(i, i + CHUNK), end: i + CHUNK >= encoded.length}));
    const item: (typeof this.queue)[number] = {type, parts, next: 0};
    if (type === "state") this.queue.splice(this.queue[0]?.type === "state" && this.queue[0].next > 0 ? 1 : 0, 0, item);
    else this.queue.push(item);
    this.flush();
  }
  private flush() {
    while (this.channel.readyState === "open" && this.channel.bufferedAmount < 131072 && this.queue.length) {
      const item = this.queue[0];
      this.channel.send(item.parts[item.next++]);
      if (item.next === item.parts.length) this.queue.shift();
    }
  }
  dispose() { this.queue = []; this.incoming.clear(); this.channel.onmessage = this.channel.onbufferedamountlow = null; }
}

function control(value: any): value is GraphControl {
  if (!value || typeof value !== "object" || !["orbit", "zoom", "click", "hover", "leave", "select", "clear", "fit", "refresh", "bank", "memoryType", "allSymbols", "follow", "search", "timeRange", "back", "enterFile"].includes(value.action)) return false;
  for (const key of ["x", "y", "dx", "dy"]) if (value[key] !== undefined && (typeof value[key] !== "number" || !Number.isFinite(value[key]) || Math.abs(value[key]) > 4)) return false;
  return (value.id === undefined || typeof value.id === "string" && value.id.length <= 4096)
    && (value.graphId === undefined || typeof value.graphId === "string" && value.graphId.length <= 128)
    && (value.value === undefined || typeof value.value === "boolean" || typeof value.value === "string" && value.value.length <= 256);
}

async function acceptSignal(peer: Peer, signal: RTCSessionDescriptionInit | RTCIceCandidateInit) {
  if ("type" in signal) {
    await peer.pc.setRemoteDescription(signal);
    for (const ice of peer.ice.splice(0)) await peer.pc.addIceCandidate(ice);
  } else if (peer.pc.remoteDescription) await peer.pc.addIceCandidate(signal);
  else peer.ice.push(signal);
}

/** The stage alone acquires the canvas stream; the last viewer releases it. */
export class GraphPublisher {
  private peers = new Map<string, Peer & {messages: Messages | null}>();
  private stream: MediaStream | null = null;
  private track: CanvasCaptureMediaStreamTrack | null = null;
  private catalog: GraphCatalog = {nodes: [], count: 0, links: 0};
  private state: GraphViewState = {};
  private followers = new Set<GraphPublisher>();
  private port: ReturnType<typeof openGraphPort>;
  private disposed = false;
  constructor(view: GraphSource, private canvas: HTMLCanvasElement, private command: (command: GraphControl) => void,
    private redraw: () => void, private consumers: (count: number) => void) {
    this.port = openGraphPort(view, "stage", message => this.signal(message));
    canvas.dataset.graphOwner = view;
  }
  publishCatalog(value: GraphCatalog) { this.catalog = value; this.broadcast({type: "catalog", value}); for (const follower of this.followers) follower.publishCatalog(value); }
  publishState(value: GraphViewState) { this.state = value; this.broadcast({type: "state", value}); for (const follower of this.followers) follower.publishState(value); }
  forwardTo(follower: GraphPublisher) {
    this.followers.add(follower); follower.publishCatalog(this.catalog); follower.publishState(this.state);
    return () => this.followers.delete(follower);
  }
  get hasViewers() { return this.peers.size > 0; }
  private broadcast(message: Message) { for (const peer of this.peers.values()) peer.messages?.send(message); }
  frame() { this.track?.requestFrame(); }
  private signal(event: GraphSignal) {
    if (this.disposed) return;
    if (event.action === "disconnect") { for (const id of [...this.peers.keys()]) this.remove(id); return; }
    if (event.action === "left" && event.id) { this.remove(event.id); return; }
    if (event.action === "peer" && event.id && !this.peers.has(event.id)) {
      const id = event.id, pc = new RTCPeerConnection(RTC);
      const peer = {pc, channel: pc.createDataChannel("graph-presentation"), ice: [], chain: Promise.resolve(), messages: null as Messages | null};
      this.peers.set(id, peer);
      try {
        if (!this.stream) {
          this.stream = this.canvas.captureStream(0);
          this.track = this.stream.getVideoTracks()[0] as CanvasCaptureMediaStreamTrack;
          this.track.contentHint = "detail";
        }
        const sender = pc.addTrack(this.track!, this.stream);
        peer.channel.onopen = () => {
          peer.messages = new Messages(peer.channel, message => { if (control(message)) this.command(message); });
          peer.messages.send({type: "catalog", value: this.catalog});
          peer.messages.send({type: "state", value: this.state});
          const parameters = sender.getParameters();
          if (parameters.encodings?.length) {
            parameters.encodings[0].maxBitrate = 12000000;
            sender.setParameters(parameters).catch(() => {});
          }
          this.redraw();
        };
        pc.onicecandidate = event => { if (event.candidate) this.port.signal(id, event.candidate.toJSON()); };
        pc.onconnectionstatechange = () => {
          if (pc.connectionState === "connected") this.redraw();
          else if (["failed", "closed"].includes(pc.connectionState)) this.remove(id);
        };
        this.consumers(this.peers.size);
        peer.chain = pc.createOffer().then(async offer => { await pc.setLocalDescription(offer); this.port.signal(id, pc.localDescription!); })
          .catch(error => { console.warn("Graph stream offer:", String(error)); this.remove(id); });
      } catch (error) { console.warn("Graph canvas stream:", String(error)); this.remove(id); }
    } else if (event.action === "signal" && event.id && event.signal) {
      const peer = this.peers.get(event.id);
      if (peer) peer.chain = peer.chain.then(() => acceptSignal(peer, event.signal!)).catch(() => this.remove(event.id!));
    }
  }
  private remove(id: string) {
    const peer = this.peers.get(id); if (!peer) return;
    this.peers.delete(id); peer.messages?.dispose(); peer.pc.close();
    if (!this.peers.size) { this.stream?.getTracks().forEach(track => track.stop()); this.stream = null; this.track = null; }
    this.consumers(this.peers.size);
  }
  dispose() { this.disposed = true; this.port.dispose(); for (const id of [...this.peers.keys()]) this.remove(id); delete this.canvas.dataset.graphOwner; }
}

/** A viewer decodes the existing image. It owns no Three scene or simulation. */
export class GraphSubscriber {
  private peer: Peer | null = null;
  private messages: Messages | null = null;
  private port: ReturnType<typeof openGraphPort>;
  private disposed = false;
  constructor(view: GraphSource, private video: HTMLVideoElement, private receive: (message: Message) => void,
    private status: (connected: boolean, error?: string) => void) {
    this.port = openGraphPort(view, "viewer", event => this.signal(event));
  }
  send(command: GraphControl) { this.messages?.send(command); }
  private signal(event: GraphSignal) {
    if (this.disposed) return;
    if (event.action === "disconnect" || event.action === "left") { this.close(); return; }
    if (event.action === "rejected") { this.status(false, event.reason); return; }
    if (event.action === "peer" && event.id) {
      this.close();
      const pc = new RTCPeerConnection(RTC), id = event.id;
      this.peer = {pc, ice: [], chain: Promise.resolve()};
      pc.onicecandidate = event => { if (event.candidate) this.port.signal(id, event.candidate.toJSON()); };
      pc.ontrack = event => {
        if (this.disposed || this.peer?.pc !== pc) return;
        const stream = new MediaStream([event.track]);
        this.video.srcObject = stream;
        this.video.play().catch(error => {
          if (!this.disposed && this.peer?.pc === pc && this.video.srcObject === stream)
            this.status(false, String(error));
        });
      };
      pc.ondatachannel = event => {
        if (this.peer?.pc !== pc) return;
        this.peer.channel = event.channel;
        // onmessage must be installed immediately: the remote channel is open.
        this.messages = new Messages(event.channel, message => {
          if (message?.type === "catalog" && Array.isArray(message.value?.nodes)
            || message?.type === "state" && message.value)
            this.receive(message);
        });
      };
      pc.onconnectionstatechange = () => {
        if (this.disposed || this.peer?.pc !== pc) return;
        this.status(pc.connectionState === "connected");
        if (pc.connectionState === "failed") this.status(false, "Stage connection interrupted. Reopen this viewer to reconnect.");
      };
    } else if (event.action === "signal" && event.signal && this.peer) {
      const peer = this.peer;
      peer.chain = peer.chain.then(async () => {
        await acceptSignal(peer, event.signal!);
        if ("type" in event.signal! && event.signal!.type === "offer") {
          await peer.pc.setLocalDescription(await peer.pc.createAnswer());
          this.port.signal(event.id!, peer.pc.localDescription!);
        }
      }).catch(error => this.status(false, String(error)));
    }
  }
  private close() {
    this.messages?.dispose(); this.messages = null;
    const peer = this.peer; this.peer = null; peer?.pc.close();
    (this.video.srcObject as MediaStream | null)?.getTracks().forEach(track => track.stop());
    this.video.srcObject = null; this.status(false);
  }
  dispose() { this.disposed = true; this.port.dispose(); this.close(); }
}
