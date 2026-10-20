/** The demo's stand-in for the Harness: its HTTP routes answer from the
 *  static files in data/, and its two sockets (/ws/activity, /ws/trace) are
 *  in-page objects fed by the tour. Nothing leaves the page but requests for
 *  the demo's own files; the Shell's command socket simply never connects. */

const API = "http://127.0.0.1:8765";
const WS_API = "ws://127.0.0.1:8765";
const pageFetch = window.fetch.bind(window);
const files = new Map<string, Promise<string>>();

export function dataUrl(name: string): string {
  return new URL(`data/${name}`, document.baseURI).href;
}

export function dataText(name: string): Promise<string> {
  let text = files.get(name);
  if (!text) {
    text = pageFetch(dataUrl(name)).then(response => {
      if (!response.ok) throw new Error(`${name}: ${response.status}`);
      return response.text();
    });
    files.set(name, text);
  }
  return text;
}

export async function dataJson<T>(name: string): Promise<T> {
  return JSON.parse(await dataText(name)) as T;
}

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });
}

async function route(url: URL): Promise<Response> {
  switch (url.pathname) {
    case "/api/graph": return new Response(await dataText("graph.json"), { headers: { "content-type": "application/json" } });
    case "/api/graphs/memory/banks": return new Response(await dataText("banks.json"), { headers: { "content-type": "application/json" } });
    case "/api/graphs/memory": return new Response(await dataText("memory.json"), { headers: { "content-type": "application/json" } });
    case "/api/graphs/code": return new Response(await dataText("code.json"), { headers: { "content-type": "application/json" } });
    case "/api/graphs/code/refresh": return json({ state: "snapshot" }, 202);
    case "/api/graphs/memory/record": {
      const graph = await dataJson<{ nodes: { id: string; text?: string; kind: string; date?: string }[] }>("memory.json");
      const id = url.searchParams.get("id") || "";
      const node = graph.nodes.find(entry => entry.id.endsWith("/" + id));
      return node ? json({ id, text: node.text, fact_type: node.kind, mentioned_at: node.date }) : json({ detail: "Unknown memory" }, 404);
    }
    // A well-formed token; the command socket it unlocks never opens here.
    case "/api/shell/command-token": return json({ token: "0".repeat(64) });
    default: return json({ detail: "Not part of the demo" }, 404);
  }
}

window.fetch = (input: RequestInfo | URL, init?: RequestInit) => {
  const href = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
  if (!href.startsWith(API)) return pageFetch(input, init);
  const signal = init?.signal;
  if (signal?.aborted) return Promise.reject(new DOMException("Aborted", "AbortError"));
  return route(new URL(href));
};

type Hub = { attach(socket: DemoSocket, url: URL): void; detach(socket: DemoSocket): void };
const hubs = new Map<string, Hub>();

export function registerSocketHub(path: string, hub: Hub): void {
  hubs.set(path, hub);
}

/** A WebSocket-shaped object for the Harness sockets; never a network connection. */
export class DemoSocket extends EventTarget {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;
  readonly CONNECTING = 0;
  readonly OPEN = 1;
  readonly CLOSING = 2;
  readonly CLOSED = 3;
  readyState = 0;
  readonly url: string;
  protocol = "";
  extensions = "";
  binaryType: BinaryType = "blob";
  bufferedAmount = 0;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  private hub: Hub | undefined;

  constructor(url: string | URL, _protocols?: string | string[]) {
    super();
    this.url = String(url);
    const parsed = new URL(this.url);
    // Only the Harness's own sockets have a stand-in; any other stays connecting.
    this.hub = this.url.startsWith(WS_API) ? hubs.get(parsed.pathname) : undefined;
    if (this.hub) {
      const hub = this.hub;
      queueMicrotask(() => {
        if (this.readyState !== 0) return;
        this.readyState = 1;
        this.fire("open", new Event("open"));
        hub.attach(this, parsed);
      });
    }
  }

  send(_data: unknown): void { /* the demo Harness takes no commands */ }

  close(): void {
    if (this.readyState >= 2) return;
    this.readyState = 3;
    this.hub?.detach(this);
    queueMicrotask(() => this.fire("close", new CloseEvent("close", { code: 1000, wasClean: true })));
  }

  deliver(frame: unknown): void {
    if (this.readyState !== 1) return;
    this.fire("message", new MessageEvent("message", { data: JSON.stringify(frame) }));
  }

  private fire(type: "open" | "message" | "close", event: Event): void {
    const handler = (this as unknown as Record<string, ((event: Event) => void) | null>)["on" + type];
    try { handler?.call(this, event); } catch (error) { reportError(error); }
    this.dispatchEvent(event);
  }
}

(window as unknown as { WebSocket: unknown }).WebSocket = DemoSocket;

// Embedded in a page, a panel's scrollIntoView must not scroll the host page
// under its reader: scroll only the nearest scrolling box inside the demo.
if (window.top !== window) {
  Element.prototype.scrollIntoView = function (this: Element, arg?: boolean | ScrollIntoViewOptions) {
    let box = this.parentElement;
    while (box && !(/(auto|scroll)/.test(getComputedStyle(box).overflowY) && box.scrollHeight > box.clientHeight))
      box = box.parentElement;
    if (!box) return;
    const block = typeof arg === "object" ? arg.block ?? "start" : arg === false ? "end" : "start";
    const r = this.getBoundingClientRect(), b = box.getBoundingClientRect();
    box.scrollTop += block === "start" ? r.top - b.top : block === "end" ? r.bottom - b.bottom
      : block === "center" ? (r.top + r.bottom - b.top - b.bottom) / 2
      : r.top < b.top ? r.top - b.top : r.bottom > b.bottom ? Math.min(r.bottom - b.bottom, r.top - b.top) : 0;
  };
}
