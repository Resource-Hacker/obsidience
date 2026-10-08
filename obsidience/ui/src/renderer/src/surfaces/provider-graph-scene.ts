import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { GraphPublisher, type GraphControl } from "./graph-stream";
import { providerGraphAssets, providerLinkIndex } from "./provider-graph-assets";
import { CODE_STRUCTURE } from "./code-spherical-layout";
import { createKnowledge3dLabelLayer, type Knowledge3dLabelMeta } from "@/components/themes/obsidience/knowledge-3d-labels";
import { memoryTimeAxis, memoryInitialOffset, memoryRelationshipWeight, memoryLens, memoryLensX, type MemoryLens, type MemoryTimeAxis } from "./memory-time-layout";

export interface ProviderNode {
  id: string; name: string; kind: string; color: string;
  x?: number; y?: number; z?: number; size?: number;
  file?: string; qualified_name?: string; ref?: string; text?: string; graph_id?: string;
  start_line?: number; end_line?: number; body_hash?: string; external?: boolean;
  aliases?: string[];
  date?: string; occurred_start?: string | null; occurred_end?: string | null;
  tags?: string[]; proof_count?: number; support?: string[];
}
export interface ProviderEdge { source: string; target: string; kind: string; color?: string; weight?: number }
export interface ProviderGraph {
  provider: string; graph_id: string; nodes: ProviderNode[]; edges: ProviderEdge[];
  total: number; limited: boolean; missed?: number; updated_at?: string; project?: string;
  code_root?: string; code_file?: string; external_count?: number;
  index?: {state: string; updated_at?: string; error?: string};
}
export interface GraphOperation {
  id: string; kind: string; status: string; refs: string[]; label: string;
  graph_id: string; at: number; expires_at: number; refresh: boolean;
}
type Point = ProviderNode & { x: number; y: number; z: number };
type Pulse = { until: number; start: number; color: THREE.Color };
type LayoutPoint = {x: number; y: number; z: number; vx?: number; vy?: number; vz?: number};
export type ProviderPresentation = Pick<GraphPublisher, "publishCatalog" | "publishState" | "frame" | "dispose">;
export type ProviderPresentationFactory = (canvas: HTMLCanvasElement, command: (command: GraphControl) => void,
  redraw: () => void, consumers: (count: number) => void) => ProviderPresentation;
/** One disposable renderer; provider layout workers share its visible lifetime. */
export class ProviderGraphScene {
  readonly presentation: ProviderPresentation;
  private renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
  private scene = new THREE.Scene();
  private camera = new THREE.PerspectiveCamera(48, 1, 0.1, 100000);
  private controls: OrbitControls;
  private group = new THREE.Group();
  private points: THREE.Points | null = null;
  private lines: THREE.Mesh<THREE.InstancedBufferGeometry, THREE.ShaderMaterial> | null = null;
  private positionTexture: THREE.DataTexture | null = null;
  private colorTexture: THREE.DataTexture | null = null;
  private linkIndex = {adjacency: new Map<string, number[]>(), overview: new Set<number>()};
  private nodeColors = new Float32Array(0);

  private timeAxis: MemoryTimeAxis | null = null;
  private timeGuides = new THREE.Group();
  private sourceData: ProviderGraph | null = null;
  private visibleKey = "";
  private memoryLens: MemoryLens | null = null;
  private memoryRange = "";
  private layoutPositions = new Map<string, LayoutPoint>();
  private projectView: {positions: Map<string, LayoutPoint>; camera: THREE.Vector3; target: THREE.Vector3} | null = null;
  private ghost: {group: THREE.Group; positions: THREE.DataTexture | null; colors: THREE.DataTexture | null} | null = null;
  private transition: {at: number; kind: "enter" | "return" | "update"; unfolding: boolean; camera: boolean} | null = null;
  private arrivals = new Map<string, LayoutPoint>();
  private layoutWorker: Worker | null = null;
  private layoutPending = false;
  private layoutReady = false;
  private layoutAlpha = 0;
  private fitAfterLayout = false;
  private searchQuery = "";
  private searchMatches = new Set<string>();
  private labels = createKnowledge3dLabelLayer();
  private readonly noLabelActivity = new Set<string>();
  private labelsDirty = true;
  private nodes: Point[] = [];
  private edges: ProviderEdge[] = [];
  private indices = new Map<string, number>();
  private aliases = new Map<string, string>();
  private pulses = new Map<string, Pulse>();
  private selected = "";
  private selection = new Map<string, number>();
  private hovered = "";
  private paintNodes = new Set<string>();
  private raf = 0;
  private wakeTimer: ReturnType<typeof setTimeout> | 0 = 0;
  private visible = true;
  private disposed = false;
  private fitted = false;
  private lastFrame = 0;
  private lastPaint = 0;
  private spinAt = 0;
  private pointerInside = false;
  private remotePointerInside = false;
  private interacting = false;
  private motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
  private cameraFlight: { at: number; from: THREE.Vector3; to: THREE.Vector3; targetFrom: THREE.Vector3; targetTo: THREE.Vector3 } | null = null;
  private resize: ResizeObserver;
  private ray = new THREE.Raycaster();
  private cursor = new THREE.Vector2();
  private down = { x: 0, y: 0 };
  private pixelRatio = Math.min(window.devicePixelRatio || 1, 1.5);

  constructor(private host: HTMLElement, private code: boolean,
    private onPick: (node: ProviderNode | null) => void,
    private onHover: (node: ProviderNode | null, x: number, y: number) => void,
    private onCommand: (command: GraphControl) => void, onConsumers: (count: number) => void,
    private options: {presentation?: ProviderPresentationFactory; timeGuides?: boolean} = {}) {
    this.renderer.setPixelRatio(this.pixelRatio);
    this.renderer.setClearColor(0x02060c, 0);
    this.renderer.domElement.setAttribute("aria-label", "Interactive 3D graph. Drag to orbit, scroll to zoom; use search to select a record.");
    this.host.appendChild(this.renderer.domElement);
    this.scene.add(this.group);
    this.scene.add(this.timeGuides);
    this.camera.position.set(0, 0, 850);
    if (!code) this.camera.position.set(310, 140, 850);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = false;
    this.controls.autoRotateSpeed = 0.5; // One Code revolution every two minutes.
    if (code) this.controls.mouseButtons.RIGHT = undefined;
    this.controls.minDistance = 15;
    this.controls.maxDistance = 50000;
    this.controls.addEventListener("change", this.cameraChanged);
    this.controls.addEventListener("start", this.interactionStart);
    this.controls.addEventListener("end", this.interactionEnd);
    this.motionPreference.addEventListener("change", this.request);
    this.resize = new ResizeObserver(this.onResize);
    this.resize.observe(host);
    const canvas = this.renderer.domElement;
    canvas.addEventListener("pointerenter", this.pointerEnter);
    canvas.addEventListener("pointermove", this.pointerMove);
    canvas.addEventListener("pointerdown", this.pointerDown);
    canvas.addEventListener("pointerup", this.pointerUp);
    canvas.addEventListener("pointerleave", this.pointerLeave);
    canvas.addEventListener("contextmenu", this.contextMenu);
    const presentation: ProviderPresentationFactory = options.presentation
      || ((canvas, command, redraw, consumers) => new GraphPublisher(code ? "code" : "memory", canvas, command, redraw, consumers));
    this.presentation = presentation(canvas,
      command => { if (!this.remote(command)) onCommand(command); }, this.request,
      count => {
        if (!count) {
          this.remotePointerInside = false;
          if (!this.pointerInside) { this.setHover(""); this.onHover(null, 0, 0); }
          this.search(""); this.request();
        }
        onConsumers(count);
      });
    this.onResize();
  }
  private remote(command: GraphControl): boolean {
    const {action, x = 0, y = 0, dx = 0, dy = 0} = command;
    if (action === "orbit" || action === "zoom") {
      this.remotePointerInside = true;
      this.stopFlight();
      const offset = this.camera.position.clone().sub(this.controls.target);
      const spherical = new THREE.Spherical().setFromVector3(offset);
      if (action === "orbit") { spherical.theta -= dx * Math.PI * 2; spherical.phi -= dy * Math.PI * 2; spherical.makeSafe(); }
      else spherical.radius = THREE.MathUtils.clamp(spherical.radius * Math.exp(dy * 0.3), this.controls.minDistance, this.controls.maxDistance);
      this.camera.position.copy(this.controls.target).add(offset.setFromSpherical(spherical));
      this.controls.update(); this.request(); return true;
    }
    if (action === "click" || action === "hover") {
      this.remotePointerInside = true;
      const rect = this.renderer.domElement.getBoundingClientRect();
      const node = this.pick({clientX: rect.left + x * rect.width, clientY: rect.top + y * rect.height});
      if (action === "click") this.onPick(node);
      else { this.setHover(node?.id || ""); this.onHover(node, x * rect.width, y * rect.height); }
      return true;
    }
    if (action === "leave") {
      this.remotePointerInside = false; this.setHover(""); this.onHover(null, 0, 0); this.request(); return true;
    }
    return false;
  }
  private stopFlight = () => {
    this.cameraFlight = null; this.fitAfterLayout = false;
    if (this.transition) this.transition.camera = false;
  };
  private interactionStart = () => { this.interacting = true; this.stopFlight(); this.request(); };
  private interactionEnd = () => { this.interacting = false; this.request(); };
  private cameraChanged = () => { this.labelsDirty = true; this.request(); };
  private onResize = () => {
    const w = Math.max(1, this.host.clientWidth), h = Math.max(1, this.host.clientHeight);
    this.renderer.setSize(w, h);
    this.labels.resize(w, h, this.pixelRatio);
    if (this.points) (this.points.material as THREE.ShaderMaterial).uniforms.uPerspective.value =
      h * this.pixelRatio / (2 * Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2)));
    this.lines?.material.uniforms.uViewportPx.value.set(w * this.pixelRatio, h * this.pixelRatio);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.cameraChanged();
  };
  private clearSprites(group: THREE.Group) {
    for (const object of [...group.children]) {
      group.remove(object);
      if (object instanceof THREE.Sprite) {
        object.material.map?.dispose(); object.material.dispose();
      } else if (object instanceof THREE.LineSegments) {
        object.geometry.dispose(); (object.material as THREE.Material).dispose();
      }
    }
  }
  private clearGeometry() {
    this.positionTexture?.dispose(); this.colorTexture?.dispose();
    this.positionTexture = this.colorTexture = null;
    for (const object of [...this.group.children]) {
      this.group.remove(object);
      const mesh = object as THREE.Points;
      mesh.geometry.dispose();
      const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      materials.forEach(material => material.dispose());
    }
    this.clearSprites(this.timeGuides);
    this.labels.update(new Map(), [], this.noLabelActivity, new Map(), false, 0);
  }
  private clearGhost() {
    if (!this.ghost) return;
    this.scene.remove(this.ghost.group);
    for (const object of this.ghost.group.children) {
      const mesh = object as THREE.Mesh;
      mesh.geometry.dispose(); (mesh.material as THREE.Material).dispose();
    }
    this.ghost.positions?.dispose(); this.ghost.colors?.dispose(); this.ghost = null;
  }
  private retainGeometry() {
    this.clearGhost();
    const group = new THREE.Group(); group.position.copy(this.group.position); group.scale.copy(this.group.scale);
    for (const object of [...this.group.children]) group.add(object);
    this.scene.add(group);
    this.ghost = {group, positions: this.positionTexture, colors: this.colorTexture};
    this.positionTexture = this.colorTexture = null; this.points = this.lines = null;
  }
  private opacity(group: THREE.Group, value: number) {
    for (const object of group.children) {
      const material = (object as THREE.Mesh).material as THREE.ShaderMaterial;
      const uniform = material.uniforms.uProviderOpacity || material.uniforms.uOpacity;
      if (uniform) uniform.value = value;
    }
  }
  private changedSymbols(data: ProviderGraph, previous: ProviderGraph | null) {
    if (!this.code || !previous || data.code_root !== previous.code_root) return;
    const old = new Map(previous.nodes.map(node => [node.id, node]));
    const now = Date.now();
    for (const node of data.nodes) {
      const before = old.get(node.id);
      if (!before || before.body_hash && node.body_hash && before.body_hash !== node.body_hash) {
        this.pulses.set(node.id, {start: now, until: now + 4000, color: new THREE.Color(before ? "#fbbf24" : "#6ee7b7")});
        this.paintNodes.add(node.id);
      }
    }
  }
  setData(data: ProviderGraph, visibleIds: Set<string>) {
    const visibleKey = [...visibleIds].join("|"), previous = this.sourceData;
    if (data === previous && visibleKey === this.visibleKey) return;
    this.changedSymbols(data, previous);
    const scopeChanged = this.code && !!previous && previous.code_root !== data.code_root;
    // A refresh carrying the same physical inputs updates metadata in place.
    // No geometry churn, giant sorted fingerprint, simulation restart or reheat.
    const samePhysics = !scopeChanged && previous?.graph_id === data.graph_id
      && previous.nodes.length === data.nodes.length && previous.edges.length === data.edges.length
      && data.nodes.every((n, i) => {
        const p = previous.nodes[i];
        return n.id === p.id && (this.code ? n.kind === p.kind && n.file === p.file
          : n.date === p.date && n.x === p.x && n.y === p.y && n.z === p.z);
      }) && data.edges.every((e, i) => {
        const p = previous.edges[i];
        return e.source === p.source && e.target === p.target && e.kind === p.kind && e.weight === p.weight;
      });
    const sameLayout = samePhysics && visibleKey === this.visibleKey;
    this.sourceData = data; this.visibleKey = visibleKey;
    if (sameLayout && data.nodes.every((n, i) => n.kind === previous.nodes[i].kind && n.color === previous.nodes[i].color)) {
      for (const n of data.nodes) {
        const index = this.indices.get(n.id);
        if (index !== undefined) Object.assign(this.nodes[index], {
          ...n, x: this.nodes[index].x, y: this.nodes[index].y, z: this.nodes[index].z,
        });
      }
      this.search(this.searchQuery, true); this.labelsDirty = true; this.request();
      return;
    }
    if (data.graph_id !== previous?.graph_id) {
      this.nodes = []; this.fitted = false;
      this.selection.clear(); this.pulses.clear(); this.paintNodes.clear();
      this.selected = this.hovered = "";
      this.memoryRange = ""; this.memoryLens = null;
      this.layoutPositions.clear();
      this.searchMatches.clear();
    }
    const transitioning = this.code && !!previous && (scopeChanged || !!data.code_root && !samePhysics);
    if (transitioning) {
      if (!scopeChanged && this.points) {
        const next = new Set(data.nodes.map(node => node.id));
        const colors = this.points.geometry.getAttribute("aCore") as THREE.BufferAttribute;
        const removed = new THREE.Color("#fb7185");
        for (const node of this.nodes) if (!next.has(node.id)) colors.setXYZ(this.indices.get(node.id)!, removed.r, removed.g, removed.b);
        colors.needsUpdate = true;
      }
      this.retainGeometry(); this.arrivals.clear();
      this.transition = {at: performance.now(), kind: scopeChanged ? data.code_root ? "enter" : "return" : "update", unfolding: false, camera: true};
      if (scopeChanged) {
        this.layoutWorker?.terminate(); this.layoutWorker = null; this.layoutReady = false;
        if (!previous.code_root) this.projectView = {positions: new Map(this.layoutPositions),
          camera: this.camera.position.clone(), target: this.controls.target.clone()};
        this.layoutPositions = data.code_root ? new Map() : new Map(this.projectView?.positions);
        const anchor = data.code_root ? this.projectView?.positions.get(data.code_root) : null;
        this.group.position.set(anchor?.x || 0, anchor?.y || 0, anchor?.z || 0);
        this.group.scale.setScalar(1);
      } else {
        for (const node of data.nodes) if (!this.layoutPositions.has(node.id))
          this.arrivals.set(node.id, {x: 0, y: 0, z: 0});
      }
    }
    this.clearGeometry(); this.aliases.clear();
    // Filters retain the complete bank's scale, dates and undated bucket.
    this.timeAxis = this.code ? null : memoryTimeAxis(data.nodes);
    if (!this.code) for (const n of data.nodes) {
      const p = this.layoutPositions.get(n.id) || {x: 0, ...memoryInitialOffset(n.id)};
      this.layoutPositions.set(n.id, {...p, x: this.timeAxis?.position(n.id) ?? -100});
    }
    this.nodes = data.nodes.filter(n => visibleIds.has(n.id))
      .map(n => ({...n, ...(this.layoutPositions.get(n.id) || {x: 0, y: 0, z: 0})}))
      .sort((a, b) => a.id.localeCompare(b.id));
    this.indices = new Map(this.nodes.map((n, i) => [n.id, i]));
    for (const n of this.nodes) {
      this.aliases.set(n.id, n.id);
      for (const alias of n.aliases || []) this.aliases.set(alias, n.id);
      if (n.qualified_name) this.aliases.set("qn:" + n.qualified_name, n.id);
      if (n.file && n.kind === "File") this.aliases.set("file:" + n.file, n.id);
    }
    this.edges = data.edges.filter(e => e.source !== e.target && this.indices.has(e.source) && this.indices.has(e.target));
    this.linkIndex = providerLinkIndex(this.nodes, this.edges, this.code);
    const assets = providerGraphAssets(this.nodes, this.code, this.pixelRatio);
    this.points = assets.points; this.lines = assets.lines;
    this.positionTexture = assets.positions; this.colorTexture = assets.colors;
    this.nodeColors = new Float32Array(this.points.geometry.getAttribute("aCore").array);
    this.group.add(this.lines, this.points);
    if (data.code_root) {
      const root = this.indices.get(data.code_root);
      if (root !== undefined) this.points.geometry.getAttribute("aRadius").setX(root, 6.6);
    }
    // Code's first frame comes from spherical seeds, never native flat layout.
    this.group.visible = !this.code || this.layoutPositions.size > 0;
    this.selection.clear();
    this.paintNodes = new Set([...this.pulses.keys(), this.selected, this.hovered]);
    this.applyMemoryFocus(); this.search(this.searchQuery, true);
    this.updateLinks(); this.updatePositions(); this.updateTimeGuides(); this.onResize();
    if (!samePhysics) {
      this.fitAfterLayout = !this.fitted && !this.transition;
      this.startLayout(data);
    }
    if (!this.fitted && this.nodes.length && this.group.visible) {
      this.fitBounds(false); this.fitted = true;
    }
    if (scopeChanged) {
      if (data.code_root) this.fly(this.group.position.clone(), 110, true);
      else if (this.projectView) this.cameraFlight = {at: performance.now(), from: this.camera.position.clone(),
        to: this.projectView.camera.clone(), targetFrom: this.controls.target.clone(), targetTo: this.projectView.target.clone()};
    }
    this.request();
  }
  private startLayout(data: ProviderGraph) {
    this.layoutWorker?.terminate(); this.layoutWorker = null;
    this.layoutPending = false; this.layoutReady = false; this.layoutAlpha = 0;
    const members = data.nodes.slice().sort((a, b) => a.id.localeCompare(b.id));
    const indices = new Map(members.map((node, i) => [node.id, i]));
    for (const id of this.layoutPositions.keys()) if (!indices.has(id)) this.layoutPositions.delete(id);
    if (!members.length) return;
    const worker = this.code
      ? new Worker(new URL("./code-layout.worker.ts", import.meta.url), {type: "module"})
      : new Worker(new URL("./memory-layout.worker.ts", import.meta.url), {type: "module"});
    this.layoutWorker = worker; this.layoutPending = true; this.layoutAlpha = 0.85;
    worker.onmessage = event => {
      if (this.disposed || this.layoutWorker !== worker) return;
      const {positions, alpha} = event.data as {positions: Float32Array; alpha: number};
      members.forEach((node, i) => {
        const offset = i * 6;
        this.layoutPositions.set(node.id, {x: positions[offset], y: positions[offset + 1], z: positions[offset + 2],
          vx: positions[offset + 3], vy: positions[offset + 4], vz: positions[offset + 5]});
      });
      this.layoutAlpha = alpha; this.layoutPending = false; this.layoutReady = true; this.request();
    };
    worker.onerror = () => {
      if (this.layoutWorker !== worker) return;
      worker.terminate(); this.layoutWorker = null; this.layoutPending = false; this.layoutAlpha = 0;
      console.error(`${this.code ? "Code" : "Memory"} layout worker failed; retaining the last layout.`); this.request();
    };
    if (this.code) {
      worker.postMessage({type: "init", graph: {nodes: members.map(({id, kind, file}) => ({id, kind, file})), edges: data.edges, code_root: data.code_root},
        preserve: !!data.code_root || this.transition?.kind === "return",
        previous: [...this.layoutPositions].map(([id, point]) => ({id, ...point}))});
      return;
    }
    const edges = data.edges.filter(edge => edge.source !== edge.target && indices.has(edge.source) && indices.has(edge.target));
    const pairs = new Float32Array(edges.length * 3);
    edges.forEach((edge, i) => pairs.set([indices.get(edge.source)!, indices.get(edge.target)!, memoryRelationshipWeight(edge)], i * 3));
    // Full-bank physics is independent of filters, selection, search and lens.
    worker.postMessage({type: "init", alpha: this.layoutAlpha, pairs,
      nodes: members.map((node, i) => {
        const p = this.layoutPositions.get(node.id)!;
        return {id: String(i), ...p, fx: p.x};
      })}, [pairs.buffer]);
  }
  private updateLinks() {
    if (!this.lines) return;
    const shown = new Set(this.linkIndex.overview);
    for (const id of [this.selected, this.hovered])
      for (const index of this.linkIndex.adjacency.get(id) || []) shown.add(index);
    const values = new Float32Array(shown.size * 4);
    let offset = 0;
    for (const index of shown) {
      const edge = this.edges[index], source = this.indices.get(edge.source)!, target = this.indices.get(edge.target)!;
      // Stable endpoint order gives reciprocal relationships the same thread.
      const a = Math.min(source, target), b = Math.max(source, target);
      const opacity = this.code ? 0.15 : edge.kind === "entity" ? 0.035 : edge.kind === "temporal" ? 0.025 : 0.18;
      values.set([a, b, (a * 0.6180339887 + b * 0.4142135624) % 1 * Math.PI * 2, opacity], offset);
      offset += 4;
    }
    // Replacing a BufferAttribute repeatedly strands its old WebGLBuffer.
    // Reuse capacity, and explicitly release the geometry before growing it.
    let links = this.lines.geometry.getAttribute("aLink") as THREE.InstancedBufferAttribute | undefined;
    if (!links || links.count < shown.size) {
      this.lines.geometry.dispose();
      links = new THREE.InstancedBufferAttribute(new Float32Array(Math.max(shown.size, 1) * 8), 4);
      links.setUsage(THREE.DynamicDrawUsage); this.lines.geometry.setAttribute("aLink", links);
    }
    (links.array as Float32Array).set(values); links.needsUpdate = true;
    this.lines.geometry.instanceCount = shown.size;
    this.lines.material.uniforms.uSelected.value = this.indices.get(this.selected) ?? -1;
    this.lines.material.uniforms.uHovered.value = this.indices.get(this.hovered) ?? -1;
  }
  private updateTimeGuides() {
    if (this.code || !this.nodes.length || this.options.timeGuides === false) return;
    // Guides are part of the stage image, so viewers receive these exact pixels.
    const {start, end, length, origin, dateAt} = this.timeAxis || {start: 0, end: 0, length: 0, origin: 0, dateAt: () => 0};
    let y = Infinity;
    for (const node of this.nodes) y = Math.min(y, node.y - 55);
    const left = this.timeAxis ? memoryLensX(origin, this.memoryLens) : -100;
    const right = this.timeAxis ? memoryLensX(origin + length, this.memoryLens) : left;
    if (this.timeGuides.children.length) {
      this.timeGuides.position.y = y;
      return;
    }
    const segments = this.timeAxis ? [left, 0, 0, right, 0, 0, right, 0, 0, right - 12, 7, 0, right, 0, 0, right - 12, -7, 0] : [];
    const count = !this.timeAxis ? 0 : end === start ? 1 : length < 300 ? 2 : 5;
    const formatter = new Intl.DateTimeFormat(undefined, end - start < 86400000
      ? {month: "short", day: "numeric", hour: "2-digit", minute: "2-digit"} : {month: "short", day: "numeric"});
    const labels: {x: number; text: string; caption?: boolean; y?: number}[] = [];
    for (let i = 0; i < count; i++) {
      const ratio = count === 1 ? 0.5 : i / (count - 1), x = memoryLensX(origin + ratio * length, this.memoryLens);
      segments.push(x, -5, 0, x, 5, 0);
      const prefix = count === 1 ? "" : i === 0 ? "OLDER · " : i === count - 1 ? "NEWER · " : "";
      labels.push({x, text: prefix + formatter.format(dateAt(ratio))});
    }
    const center = (left + right) / 2;
    labels.push({x: center, text: !this.timeAxis ? "DATES UNAVAILABLE · NO CHRONOLOGY INFERRED"
      : this.memoryLens ? "FOCUS EXPANDED · FIT TO RESET" : "ORGANIC TIMELINE · SPACING FOLLOWS ACTIVITY", caption: true});
    labels.push({x: center, text: "STRONGEST THREADS · SELECT FOR ALL LINKS", caption: true, y: -125});
    if (this.nodes.some(n => !Number.isFinite(Date.parse(n.date || ""))))
      labels.push({x: memoryLensX(origin - 100, this.memoryLens), text: "UNDATED"});
    for (const {x, text, caption, y: labelY} of labels) {
      const label = document.createElement("canvas"); label.width = 512; label.height = 96;
      const ctx = label.getContext("2d")!;
      ctx.font = `${caption ? 24 : 38}px sans-serif`; ctx.textAlign = "center"; ctx.fillStyle = "#92b9cc";
      ctx.fillText(text, 256, 52, 500);
      const texture = new THREE.CanvasTexture(label); texture.colorSpace = THREE.SRGBColorSpace;
      const sprite = new THREE.Sprite(new THREE.SpriteMaterial({map: texture, transparent: true, depthWrite: false, opacity: 0.82}));
      const width = Math.max(caption ? 330 : 150, (right - left) * (caption ? 0.48 : 0.22));
      sprite.position.set(x, labelY ?? (caption ? -88 : -30), 0); sprite.scale.set(width, width * 96 / 512, 1);
      this.timeGuides.add(sprite);
    }
    const geometry = new THREE.BufferGeometry(); geometry.setAttribute("position", new THREE.Float32BufferAttribute(segments, 3));
    this.timeGuides.add(new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({color: 0x568198, transparent: true, opacity: 0.36, depthWrite: false})));
    this.timeGuides.position.y = y;
  }
  private updatePositions() {
    if (!this.points || !this.positionTexture) return;
    const p = this.points.geometry.getAttribute("position") as THREE.BufferAttribute;
    const texture = this.positionTexture.image.data as Float32Array;
    this.nodes.forEach((n, i) => {
      p.setXYZ(i, n.x, n.y, n.z);
      texture[i * 4] = n.x; texture[i * 4 + 1] = n.y; texture[i * 4 + 2] = n.z;
    });
    p.needsUpdate = true; this.positionTexture.needsUpdate = true;
    this.points.geometry.computeBoundingSphere();
  }
  select(id: string, range = "") {
    id = this.aliases.get(id) || id;
    if (this.selected === id && this.memoryRange === range) return;
    this.paintNodes.add(this.selected); this.paintNodes.add(id);
    this.selected = id; this.memoryRange = range;
    this.fitAfterLayout = false;
    if (!this.code) { this.applyMemoryFocus(); this.frameMemoryFocus(); }
    this.updateEmphasis(); this.updateLinks(); this.labelsDirty = true; this.request();
  }
  private applyMemoryFocus() {
    if (this.code) return;
    let ids = this.selected ? [this.selected] : [];
    if (this.timeAxis && /^\d{4}-\d{2}-\d{2}\/\d{4}-\d{2}-\d{2}$/.test(this.memoryRange)) {
      const [from, to] = this.memoryRange.split("/");
      const start = new Date(from + "T00:00:00").getTime(), end = new Date(to + "T23:59:59.999").getTime();
      ids = this.timeAxis.range(start, end);
    }
    this.setMemoryLens(this.timeAxis ? memoryLens(this.timeAxis, ids) : null);
  }
  private setMemoryLens(lens: MemoryLens | null) {
    this.memoryLens = lens;
    this.clearSprites(this.timeGuides); this.applyLayoutPositions();
    this.labelsDirty = true; this.request();
  }
  private applyLayoutPositions() {
    for (const node of this.nodes) {
      const point = this.layoutPositions.get(node.id);
      if (!point) continue;
      const d = this.memoryLens ? (point.x - this.memoryLens.center) / this.memoryLens.radius : Infinity;
      const expansion = 1 + 0.3 / (1 + d * d);
      node.x = memoryLensX(point.x, this.memoryLens); node.y = point.y * expansion; node.z = point.z * expansion;
    }
    this.updatePositions(); this.updateTimeGuides(); this.labelsDirty = true;
  }
  private frameMemoryFocus() {
    if (!this.memoryLens) { this.fitBounds(true); return; }
    // Center the expanded section so wheel zoom explores that section, not
    // the middle of the entire bank. Fit always restores the whole history.
    this.fly(new THREE.Vector3(this.memoryLens.center, 0, 0),
      Math.max(700, this.memoryLens.radius * 10) * Math.max(1, 1 / this.camera.aspect), true);
  }
  search(query: string, force = false) {
    if (this.code || !force && query === this.searchQuery) return;
    for (const id of this.searchMatches) this.paintNodes.add(id);
    this.searchQuery = query.slice(0, 256);
    const q = this.searchQuery.trim().toLocaleLowerCase();
    this.searchMatches = new Set(q ? this.nodes.filter(n =>
      [n.name, n.text, ...(n.tags || [])].some(value => value?.toLocaleLowerCase().includes(q))).map(n => n.id) : []);
    for (const id of this.searchMatches) this.paintNodes.add(id);
    this.updateEmphasis(); this.labelsDirty = true; this.request();
  }
  private updateEmphasis() {
    if (this.code || !this.points) return;
    const context = new Set([this.selected, this.hovered, ...this.searchMatches]);
    for (const id of [this.selected, this.hovered]) for (const index of this.linkIndex.adjacency.get(id) || []) {
      const edge = this.edges[index]; context.add(edge.source); context.add(edge.target);
    }
    const inspecting = !!(this.selected || this.hovered || this.searchQuery.trim());
    const style = this.points.geometry.getAttribute("aStyle") as THREE.BufferAttribute;
    this.nodes.forEach((node, i) => style.setW(i, !inspecting || context.has(node.id) ? 0.8 : 0.16));
    style.needsUpdate = true;
  }
  private updateDetailLabels(scale: number) {
    // Knowledge owns label assets and placement. Only native record metadata
    // and a bounded, camera-dependent candidate set belong to this adapter.
    const now = Date.now();
    const priorityIds = new Set([this.hovered, this.selected,
      ...[...this.pulses].filter(([, pulse]) => pulse.until > now).map(([id]) => id)]);
    const inspect = scale >= 1.4;
    const nodes = inspect ? this.nodes : [...priorityIds].flatMap(id => {
      const index = this.indices.get(id); return index === undefined ? [] : [this.nodes[index]];
    });
    const candidates: {node: Point; x: number; y: number; score: number; depth: number}[] = [];
    const p = new THREE.Vector3(), local = new THREE.Vector3();
    this.camera.updateMatrixWorld(); this.group.updateMatrixWorld(true);
    for (const node of nodes) {
      p.set(node.x, node.y, node.z).applyMatrix4(this.group.matrixWorld); local.copy(p).applyMatrix4(this.camera.matrixWorldInverse);
      p.project(this.camera);
      if (local.z >= 0 || p.z < -1 || p.z > 1 || Math.abs(p.x) > 1 || Math.abs(p.y) > 1) continue;
      const x = (p.x + 1) / 2, y = (1 - p.y) / 2;
      const priority = node.id === this.hovered ? -8 : node.id === this.selected ? -6
        : priorityIds.has(node.id) ? -4 : this.searchMatches.has(node.id) ? -2 : 0;
      candidates.push({node, x, y, score: priority + p.x ** 2 + p.y ** 2, depth: -local.z});
    }
    candidates.sort((a, b) => a.score - b.score);
    const projected = new Map<string, {x: number; y: number}>();
    const metadata = new Map<string, Knowledge3dLabelMeta>();
    for (const {node, x, y, depth} of candidates.slice(0, 12)) {
      const root = this.code && (node.id === this.sourceData?.code_root || node.kind === "Project"), section = this.code && CODE_STRUCTURE.has(node.kind);
      const radius = this.points?.geometry.getAttribute("aRadius").getX(this.indices.get(node.id)!) || 3.2;
      projected.set(node.id, {x, y});
      metadata.set(node.id, {
        label: (node.external ? "↗ " : "") + node.name.slice(0, 74) + (node.name.length > 74 ? "…" : ""),
        // These are shared visual tiers only, never provider Article identities.
        role: root ? "root" : section ? "section" : "claim", depth: root ? 0 : section ? 1 : 2,
        branch: node.kind, radius: Math.max(3, radius * this.host.clientHeight
          / (2 * Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2)) * depth)),
        accent: node.color, accentSoft: node.color,
      });
    }
    // Provider activity already owns the node pulse; do not add a second ring.
    this.labels.update(projected, [...projected.keys()], this.noLabelActivity, metadata, false, now);
  }
  private setHover(id: string) {
    if (this.hovered === id) return;
    this.paintNodes.add(this.hovered); this.paintNodes.add(id);
    this.hovered = id; this.updateEmphasis(); this.updateLinks(); this.labelsDirty = true; this.request();
  }
  activity(operations: GraphOperation[]) {
    const now = Date.now();
    for (const op of operations) {
      if (op.status === "running" || (op.expires_at && op.expires_at < now - 900)) continue;
      const color = new THREE.Color(["failed", "interrupted"].includes(op.status) ? "#fb7185" : op.kind === "edit" ? "#fbbf24" : op.kind === "read" ? "#67e8f9" : op.kind === "consolidate" ? "#e9a8ff" : "#6ee7b7");
      for (const ref of op.refs) {
        const id = this.aliases.get(ref);
        if (id) {
          this.pulses.set(id, { start: op.at, until: (op.expires_at || op.at + 3500) + 900, color });
          this.paintNodes.add(id);
        }
      }
    }
    this.labelsDirty = true; this.request();
  }
  focus(ids: string[]) {
    // An edit refresh inside a file never resets the owner's camera. The file
    // entry transition already frames the local sphere; explicit picks may zoom.
    if (this.transition?.kind === "enter") return;
    const nodes = ids.map(id => this.indices.get(this.aliases.get(id) || id)).filter(i => i !== undefined).map(i => this.nodes[i!]);
    if (!nodes.length) return;
    if (!this.code) {
      if (this.selected || this.memoryRange) return;
      this.setMemoryLens(this.timeAxis ? memoryLens(this.timeAxis, nodes.map(n => n.id)) : null);
      this.frameMemoryFocus(); return;
    }
    const box = new THREE.Box3().setFromPoints(nodes.map(n => new THREE.Vector3(n.x, n.y, n.z)));
    this.fly(box.getCenter(new THREE.Vector3()).add(this.group.position), Math.max(100, box.getSize(new THREE.Vector3()).length() * 1.5), true);
  }
  fit(animate = true) {
    this.fitAfterLayout = false;
    if (!this.code) this.setMemoryLens(null);
    this.fitBounds(animate);
  }
  private fitBounds(animate: boolean) {
    if (!this.nodes.length) return;
    const box = new THREE.Box3().setFromPoints(this.nodes.map(n => new THREE.Vector3(n.x, n.y, n.z)));
    if (!this.code) {
      // Include the whole axial sweep so an irregular coil cannot spin out of frame.
      const radius = this.nodes.reduce((radius, node) => Math.max(radius, Math.hypot(node.y, node.z)), 0);
      box.expandByPoint(new THREE.Vector3(box.min.x, -radius, -radius));
      box.expandByPoint(new THREE.Vector3(box.max.x, radius, radius));
    }
    if (this.timeGuides.children.length) box.expandByObject(this.timeGuides);
    if (!this.code) {
      // Fit the actual viewport, not a sphere enclosing the long timeline.
      // Four wide desktop rows should use their width without clipping depth.
      box.expandByScalar(12);
      const center = box.getCenter(new THREE.Vector3());
      const inverse = this.camera.quaternion.clone().invert();
      const tangent = Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2));
      let distance = 130;
      for (const x of [box.min.x, box.max.x]) for (const y of [box.min.y, box.max.y]) for (const z of [box.min.z, box.max.z]) {
        const corner = new THREE.Vector3(x, y, z).sub(center).applyQuaternion(inverse);
        distance = Math.max(distance, corner.z + 1.1 * Math.max(Math.abs(corner.x) / (tangent * this.camera.aspect), Math.abs(corner.y) / tangent));
      }
      this.fly(center, distance, animate); return;
    }
    const radius = box.getSize(new THREE.Vector3()).length() * 0.5;
    const distance = radius / Math.sin(THREE.MathUtils.degToRad(24)) * Math.max(1, 1 / this.camera.aspect) * 0.94;
    this.fly(box.getCenter(new THREE.Vector3()).add(this.group.position), Math.max(130, distance), animate);
  }
  private fly(target: THREE.Vector3, distance: number, animate: boolean) {
    const direction = this.camera.position.clone().sub(this.controls.target).normalize();
    const to = target.clone().addScaledVector(direction, distance);
    if (animate) this.cameraFlight = { at: performance.now(), from: this.camera.position.clone(), to, targetFrom: this.controls.target.clone(), targetTo: target };
    else { this.camera.position.copy(to); this.controls.target.copy(target); this.controls.update(); }
    this.request();
  }
  setVisible(visible: boolean) {
    this.visible = visible;
    if (!visible) {
      cancelAnimationFrame(this.raf); this.raf = 0; this.spinAt = 0;
      clearTimeout(this.wakeTimer); this.wakeTimer = 0;
      this.pointerInside = this.remotePointerInside = this.interacting = false;
      this.setHover(""); this.onHover(null, 0, 0);
    }
    else this.request();
  }
  private canSpin() {
    return this.nodes.length > 1 && this.group.visible && !this.motionPreference.matches
      && !this.pointerInside && !this.remotePointerInside && !this.interacting
      && !this.selected && !this.hovered && !this.searchQuery.trim() && !this.memoryLens
      && !this.transition && !this.cameraFlight;
  }
  /** Render on the coming display refresh; supersedes a pending idle wait. */
  private request = () => {
    if (this.wakeTimer) { clearTimeout(this.wakeTimer); this.wakeTimer = 0; }
    if (!this.disposed && this.visible && !this.raf) this.raf = requestAnimationFrame(this.frame);
  };
  /** Sleep until the next frame is due instead of polling every refresh. */
  private sleep(ms: number) {
    if (this.raf || this.disposed || !this.visible) return;
    clearTimeout(this.wakeTimer);
    this.wakeTimer = setTimeout(this.request, Math.max(1, ms));
  }
  private frame = (time: number) => {
    this.raf = 0;
    if (this.disposed || !this.visible) return;
    // A 240-Hz desktop does not require 240 full graph/video frames per second.
    // Idle spin needs only 15 Hz; retain 60 Hz for direct interaction/activity.
    const spinning = this.canSpin();
    const fps = spinning && !this.paintNodes.size && !this.layoutPending && this.layoutAlpha <= 0.006 ? 15 : 60;
    const wait = 1000 / fps - 0.5 - (time - this.lastPaint);
    if (wait > 0) { this.sleep(wait); return; }
    this.lastPaint = time;
    let moving = false;
    if (this.layoutReady) {
      this.layoutReady = false; this.applyLayoutPositions(); this.group.visible = true;
      if (!this.fitted && this.nodes.length) { this.fitBounds(false); this.fitted = true; }
    }
    if (this.layoutWorker && !this.layoutPending && this.layoutAlpha > 0.006) {
      this.layoutPending = true; this.layoutWorker.postMessage({type: "step"});
    }
    if (this.fitAfterLayout && !this.layoutPending && this.layoutAlpha <= 0.006) {
      this.fitAfterLayout = false; this.fitBounds(true);
    }
    if (this.transition) {
      const transition = this.transition;
      const delay = transition.kind === "enter" ? 550 : 0;
      const t = Math.max(0, Math.min(1, (time - transition.at - delay) / 650));
      const eased = t * t * (3 - 2 * t);
      if (transition.kind === "enter") {
        this.group.scale.setScalar(0.015 + 0.985 * eased);
        if (t > 0 && !transition.unfolding && this.layoutPositions.size) {
          transition.unfolding = true;
          if (transition.camera) this.fitBounds(true);
        }
      }
      if (this.arrivals.size) {
        for (const node of this.nodes) {
          const from = this.arrivals.get(node.id), to = this.layoutPositions.get(node.id);
          if (from && to) {
            node.x = from.x + (to.x - from.x) * eased;
            node.y = from.y + (to.y - from.y) * eased;
            node.z = from.z + (to.z - from.z) * eased;
          }
        }
        this.updatePositions();
      }
      this.opacity(this.group, eased);
      if (this.ghost) this.opacity(this.ghost.group, 1 - eased);
      this.labelsDirty = true;
      if (t === 1) {
        this.transition = null; this.arrivals.clear(); this.group.scale.setScalar(1); this.clearGhost();
      }
      moving = true;
    }
    if (this.cameraFlight) {
      const flight = this.cameraFlight, t = Math.min(1, (time - flight.at) / 550), eased = 1 - Math.pow(1 - t, 3);
      this.camera.position.lerpVectors(flight.from, flight.to, eased);
      this.controls.target.lerpVectors(flight.targetFrom, flight.targetTo, eased);
      this.controls.update();
      if (t === 1) this.cameraFlight = null;
      moving = true;
    }
    if (spinning && !moving) {
      const seconds = this.spinAt ? Math.min(0.05, (time - this.spinAt) / 1000) : 0;
      this.spinAt = time;
      if (this.code) {
        // Orbit the existing camera; file transitions keep their exact coordinates.
        this.controls.autoRotate = true; this.controls.update(seconds); this.controls.autoRotate = false;
      } else {
        // Chronology is x. Rotate only the rendered coil, never layout coordinates.
        this.group.rotation.x = (this.group.rotation.x + seconds * Math.PI * 2 / 90) % (Math.PI * 2);
        this.labelsDirty = true;
      }
      moving = true;
    } else this.spinAt = 0;
    const now = Date.now(), blend = Math.min(1, Math.max(1, time - this.lastFrame) / 130);
    this.lastFrame = time;
    if (this.points) {
      const colors = this.points.geometry.getAttribute("aCore") as THREE.BufferAttribute;
      const intensity = this.points.geometry.getAttribute("aFocus") as THREE.BufferAttribute;
      let dirty = false;
      for (const id of this.paintNodes) {
        const i = this.indices.get(id);
        if (i === undefined) { this.paintNodes.delete(id); continue; }
        const node = this.nodes[i]; dirty = true;
        const target = node.id === this.selected || node.id === this.hovered || this.searchMatches.has(node.id) ? 1 : 0;
        let select = this.selection.get(node.id) || 0;
        select += (target - select) * blend;
        if (Math.abs(target - select) < 0.005) select = target;
        else moving = true;
        this.selection.set(node.id, select);
        const pulse = this.pulses.get(node.id);
        let level = 0;
        if (pulse && pulse.until > now) {
          const fade = Math.min(1, (pulse.until - now) / 900);
          const arrival = Math.min(1, Math.max(0, now - pulse.start) / 180);
          level = fade * arrival * (0.8 + Math.sin((now - pulse.start) / 170) * 0.2);
          moving = true;
        } else if (this.pulses.delete(node.id)) this.labelsDirty = true;
        const offset = i * 3, mix = select * 0.65, p = level * 0.8;
        const r = this.nodeColors[offset] * (1 - mix) + 0.75 * mix;
        const g = this.nodeColors[offset + 1] * (1 - mix) + 0.95 * mix;
        const b = this.nodeColors[offset + 2] * (1 - mix) + mix;
        colors.setXYZ(i, r * (1 - p) + (pulse?.color.r || 0) * p,
          g * (1 - p) + (pulse?.color.g || 0) * p, b * (1 - p) + (pulse?.color.b || 0) * p);
        intensity.setX(i, Math.max(select, level));
        colors.addUpdateRange(i * 3, 3); intensity.addUpdateRange(i, 1);
        if (select === target && !this.pulses.has(id)) this.paintNodes.delete(id);
      }
      if (dirty) colors.needsUpdate = intensity.needsUpdate = true;
    }
    // Links use immutable colors plus selected/hovered uniforms. Orbiting and
    // pulsing a few returned records never rewrites the full bank's links.
    const scale = this.host.clientHeight / (2 * Math.tan(THREE.MathUtils.degToRad(this.camera.fov / 2))
      * Math.max(1, this.camera.position.distanceTo(this.controls.target)));
    if (!this.code && this.lines) {
      this.lines.material.uniforms.uOverview.value = THREE.MathUtils.clamp(scale * 0.5, 0.12, 1)
        * (this.selected || this.hovered || this.searchQuery.trim() ? 0.2 : 1);
    }
    if (this.labelsDirty) {
      this.labelsDirty = false;
      if (this.transition?.kind === "enter" && !this.transition.unfolding)
        this.labels.update(new Map(), [], this.noLabelActivity, new Map(), false, 0);
      else this.updateDetailLabels(scale);
    }
    this.renderer.render(this.scene, this.camera);
    this.renderer.autoClear = false;
    this.renderer.clearDepth();
    this.labels.render(this.renderer);
    this.renderer.autoClear = true;
    this.presentation.frame();
    if (moving) this.sleep(1000 / fps - 0.5 - (performance.now() - time));
  };
  private pick(event: {clientX: number; clientY: number}): ProviderNode | null {
    if (!this.points) return null;
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.cursor.set((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1);
    this.ray.setFromCamera(this.cursor, this.camera);
    this.ray.params.Points!.threshold = this.camera.position.distanceTo(this.controls.target)
      * (this.code ? 0.009 : 12 * Math.tan(THREE.MathUtils.degToRad(24)) / Math.max(1, rect.height));
    this.group.updateMatrixWorld(true);
    const hits = this.ray.intersectObject(this.points);
    if (!this.code) hits.sort((a, b) => (a.distanceToRay || 0) - (b.distanceToRay || 0));
    return hits.length && hits[0].index !== undefined ? this.nodes[hits[0].index] : null;
  }
  private pointerEnter = () => { this.pointerInside = true; this.request(); };
  private pointerDown = (event: PointerEvent) => { this.pointerInside = true; this.down = { x: event.clientX, y: event.clientY }; };
  private pointerMove = (event: PointerEvent) => {
    if (event.buttons) return;
    const node = this.pick(event); this.setHover(node?.id || "");
    this.onHover(node, event.offsetX, event.offsetY);
    this.renderer.domElement.style.cursor = node ? "pointer" : "grab";
    this.request();
  };
  private pointerUp = (event: PointerEvent) => {
    if (event.button === 0 && Math.hypot(event.clientX - this.down.x, event.clientY - this.down.y) < 5) this.onPick(this.pick(event));
  };
  private pointerLeave = () => { this.pointerInside = false; this.setHover(""); this.onHover(null, 0, 0); this.request(); };
  private contextMenu = (event: MouseEvent) => {
    if (!this.code) return;
    event.preventDefault();
    if (this.sourceData?.code_root) this.onCommand({action: "back"});
  };
  dispose() {
    this.presentation.dispose();
    this.disposed = true; cancelAnimationFrame(this.raf); clearTimeout(this.wakeTimer); this.resize.disconnect();
    this.layoutWorker?.terminate(); this.layoutWorker = null;
    this.motionPreference.removeEventListener("change", this.request);
    this.controls.dispose(); this.clearGhost(); this.clearGeometry(); this.labels.dispose(); this.renderer.dispose();
    this.renderer.domElement.removeEventListener("pointerenter", this.pointerEnter);
    this.renderer.domElement.removeEventListener("pointermove", this.pointerMove);
    this.renderer.domElement.removeEventListener("pointerdown", this.pointerDown);
    this.renderer.domElement.removeEventListener("pointerup", this.pointerUp);
    this.renderer.domElement.removeEventListener("pointerleave", this.pointerLeave);
    this.renderer.domElement.removeEventListener("contextmenu", this.contextMenu);
    this.renderer.domElement.remove();
  }
}
