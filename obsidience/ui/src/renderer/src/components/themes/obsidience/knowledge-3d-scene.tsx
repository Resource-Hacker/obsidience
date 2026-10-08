import type { GraphSource } from "@/lib/shell-client";
import { GraphPublisher, type GraphControl } from "@/surfaces/graph-stream";
// Real-time 3D knowledge model (three.js). Owner-directed 2026-07-31: the
// model IS the 2D radial map lifted into 3D space. Node positions are the
// deterministic 2D layout verbatim (plus a bounded per-node depth), and the
// point-sprite shader procedurally replicates the 2D canvas painter — the
// offset highlight gradient disc, dark rim, ring stroke, depth glow, and
// per-node alpha. The scene is a dumb renderer: every color/radius/scale/
// alpha arrives prepared from the backdrop's shared styling helpers.
//
// Consolidation (owner 2026-08-04): the MAIN executive ball is built by the
// SAME createKnowledge3dCloud cloud implementation as every satellite
// (main: true — raw node ids, no orbit transform, no ballScale shrink).
// This module owns what is genuinely scene-global: the
// camera/orbit/pointer surface, the sweep timeline clock, role nameplates,
// orbit rings, screen-space labels, and the per-frame loop.
import { useEffect, useRef } from "react";
import * as THREE from "three";
import {
  POINT_DEPTH_FRAGMENT_SHADER, POINT_VERTEX_SHADER, POINT_FRAGMENT_SHADER,
  BEAM_VERTEX_SHADER, TAXONOMY_PATH_FRAGMENT_SHADER, CROSS_PATH_FRAGMENT_SHADER,
  PARTICLE_VERTEX_SHADER, PARTICLE_FRAGMENT_SHADER,
} from "./knowledge-3d-shaders";
import {
  KNOWLEDGE_3D_FRAME_EARLY_TOLERANCE_MS,
  KNOWLEDGE_3D_INITIAL_DOLLY,
  KNOWLEDGE_3D_INITIAL_POLAR,
  clampKnowledge3dDolly,
  clampKnowledge3dPolar,
  isKnowledge3dDrag,
  knowledge3dAnimationEnabled,
  advanceKnowledge3dFrameDeadline,
  knowledge3dMaxShell,
  knowledge3dFrameIntervalMs,
  knowledge3dFramedDistance,
  knowledge3dWebglPowerPreference,
  knowledge3dSweepTail,
  knowledgeAgentNodeId,
  extendKnowledge3dPathSpec,
  knowledgeSweepProgress3d,
  parseKnowledgeAgentNodeId,
  type Knowledge3dPathSpec,
  type Knowledge3dTuning,
  type KnowledgeFocusPhase,
} from "./knowledge-3d";
import type {
  GraphicsAdapterPreference,
  GraphicsAnimationProfile,
} from "../../../../../main/config/schema";
import {
  knowledgeRoleForAgent,
  paintKnowledgeRoleIcon,
} from "./knowledge-role-icons";
import {
  createKnowledge3dLabelLayer,
  type Knowledge3dLabelMeta,
} from "./knowledge-3d-labels";
import {
  createKnowledge3dOrbitRing,
  createKnowledge3dDeliveryComet,
  createKnowledge3dCloud,
  KNOWLEDGE_LINK_APPROVAL_DURATION_MS,
  KNOWLEDGE_ACTIVITY_FADE_MS,
  knowledge3dCloudPhysicsSignature,
  type Knowledge3dOrbitRing,
  type Knowledge3dRenderEdge,
  type Knowledge3dRenderNode,
  type Knowledge3dRelationEffect,
  type Knowledge3dCloud,
  type Knowledge3dCloudDeps,
  type Knowledge3dCloudInput,
} from "./knowledge-3d-cloud";

// The render-model types live with the one cloud implementation; re-export
// so the backdrop's import surface is unchanged.
export type {
  Knowledge3dLabelMeta,
  Knowledge3dRenderEdge,
  Knowledge3dRenderNode,
  Knowledge3dRelationEffect,
};
export { KNOWLEDGE_LINK_APPROVAL_DURATION_MS };

export interface Knowledge3dSceneProps {
  sharePresentation?: boolean;
  presentationSource?: import("@/lib/shell-client").GraphSource;
  primaryGraphId?: string;
  onPresentationReady?: (publisher: GraphPublisher | null) => void;
  onPresentationCommand?: (command: GraphControl) => void;
  onPresentationConsumers?: (count: number) => void;
  nodes: Knowledge3dRenderNode[];
  edges: Knowledge3dRenderEdge[];
  hub: { x: number; y: number };
  focusNodeIds: ReadonlySet<string>;
  /** Sweep-plan windows per beam key — the thinking rides the REAL beams
   *  (owner 2026-08-02): a beam head travels the path first, the solid
   *  center line launches when the head reaches the first node, the whole
   *  path pulses neon when the fill completes, then segmented flow streams
   *  start-to-finish. */
  pathSpec: Knowledge3dPathSpec | null;
  focusActive: boolean;
  /** Stable run identity; an extension of the same packet keeps its clock. */
  focusKey: string | number;
  clearedActivityKeys?: ReadonlySet<string>;
  /** Speech retains the continuous route clock; null releases the path. */
  focusPhase: KnowledgeFocusPhase;
  /** Exact operation endpoints: read, Tool, pending, committed, failed. */
  activityAccents?: ReadonlyMap<string, { color: string; mode: number }>;
  selectionPath?: { agentId: string; id: string; spec: Knowledge3dPathSpec } | null;
  /** Speaker PCM envelope; read by the existing frame loop, never graph physics. */
  speechEnvelope?: { current: { level: number; updatedAt: number } };
  visible: boolean;
  reducedMotion: boolean;
  /** Startup adapter request and live cadence are independent: adapter
   *  changes require context/application recreation, while animation profile
   *  changes are consumed directly by the frame loop. */
  adapterPreference: GraphicsAdapterPreference;
  animationProfile: GraphicsAnimationProfile;
  hoveredNodeId: string | null;
  labelIds: readonly string[];
  showActivityLabels: boolean;
  labelMetadata: ReadonlyMap<string, Knowledge3dLabelMeta>;
  /** Live operator tuning from the ambient slider panel. */
  tuning: Knowledge3dTuning;
  /** Satellite knowledge balls — one per has_knowledge subagent, each a
   *  smaller cloud orbiting the main graph with its OWN tuning record
   *  (owner 2026-08-03). Node ids arrive raw; the scene namespaces them
   *  as agent:<id>/<nodeId> in projections and pointer events. */
  satellites?: ReadonlyArray<Knowledge3dCloudInput>;
  /** Pending Review links and confirmed approval flashes, separate from graph edges. */
  relationEffects?: readonly Knowledge3dRelationEffect[];
  /** Developer test sweep on ONE satellite (owner 2026-08-03: Test
   *  thinking runs on the SELECTED graph): the scene drives that cloud's
   *  beams/nodes on the same constant-speed timeline law as the main
   *  ball. `key` restarts the run. */
  satelliteSweeps?: ReadonlyArray<{
    agentId: string;
    spec: Knowledge3dPathSpec;
    key: string | number;
    phase?: KnowledgeFocusPhase;
    nodeIds?: ReadonlySet<string>;
    accents?: ReadonlyMap<string, { color: string; mode: number }>;
    /** Readable automatic reveal speed; absent means use the graph slider. */
    speed?: number;
    /** Task sweeps HOLD after the run (path stays lit, dashes streaming)
     *  until the backdrop clears them at Task end; test sweeps clear on the
     *  backdrop's own timer. */
    hold?: boolean;
    /** Bumping this replays the whole-path neon pulse without restarting
     *  the sweep — the launch flash when a delivery comet departs. */
    pulseKey?: number;
  }>;
  /** Delivery comets (owner 2026-08-04): a finished Task filed an article
   *  into another graph — fly it from the assignee's ball to the new node.
   *  toAgentId null = the main executive ball. */
  deliveries?: ReadonlyArray<{
    key: string;
    fromAgentId: string;
    toAgentId: string | null;
    nodeId: string;
  }>;
  onDeliveryDone?: (key: string) => void;
  /** Camera focus on a node (owner 2026-08-03: left-click for the reader
   *  stabilizes the camera on that node — satellite AND main ball): the
   *  camera center blends from the world origin to the node's live
   *  position, a stationary orbit that follows it; idle yaw pauses.
   *  agentId null = a main-ball node. */
  cameraFocus?: { agentId: string | null; nodeId: string } | null;
  /** A non-drag click on empty space (used to release the camera focus). */
  onBackgroundClick?: () => void;
  onHover?: (id: string | null) => void;
  /** Ambient node interaction: a non-drag left click reads a node, a right
   *  click opens its action menu (owner directive 2026-08-02). */
  onNodeAction?: (
    kind: "click" | "context",
    id: string,
    at: { x: number; y: number },
  ) => void;
  onContextLost: () => void;
}

const FOV_DEGREES = 45;
const HOVER_RADIUS_PX = 26;
/** Whole-path neon pulse duration once the solid fill completes. */
const PATH_GLOW_SECONDS = 0.55;

interface CssRgba {
  r: number;
  g: number;
  b: number;
  a: number;
}

function hslChannel(hue: number, saturation: number, light: number): number {
  const k = (((hue / 30) % 12) + 12) % 12;
  const a = saturation * Math.min(light, 1 - light);
  return light - a * Math.max(-1, Math.min(k - 3, 9 - k, 1));
}

/** Parse the palette's CSS colors into RAW sRGB components. rgb()/rgba()
 *  and hsl()/hsla() are parsed manually — THREE.Color must not be used
 *  for these because ColorManagement converts CSS input into the linear
 *  working space, which visibly darkens and muddies the branch hues in
 *  our raw shaders. Hex falls through to THREE.Color read back as sRGB. */
export function parseKnowledgeCssColor(css: string): CssRgba {
  const rgb = /rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)/u.exec(
    css,
  );
  if (rgb) {
    return {
      r: Number(rgb[1]) / 255,
      g: Number(rgb[2]) / 255,
      b: Number(rgb[3]) / 255,
      a: rgb[4] === undefined ? 1 : Number(rgb[4]),
    };
  }
  const hsl = /hsla?\(\s*([\d.-]+)(?:deg)?\s*,\s*([\d.]+)%\s*,\s*([\d.]+)%\s*(?:,\s*([\d.]+)\s*)?\)/u.exec(
    css,
  );
  if (hsl) {
    const hue = ((Number(hsl[1]) % 360) + 360) % 360;
    const saturation = Number(hsl[2]) / 100;
    const light = Number(hsl[3]) / 100;
    return {
      r: hslChannel(hue, saturation, light),
      g: hslChannel(hue - 120, saturation, light),
      b: hslChannel(hue + 120, saturation, light),
      a: hsl[4] === undefined ? 1 : Number(hsl[4]),
    };
  }
  try {
    const color = new THREE.Color(css);
    const srgb = new THREE.Color();
    color.getRGB(srgb, THREE.SRGBColorSpace);
    return { r: srgb.r, g: srgb.g, b: srgb.b, a: 1 };
  } catch {
    return { r: 0.133, g: 0.827, b: 0.933, a: 1 };
  }
}

export function Knowledge3dScene(props: Knowledge3dSceneProps) {
  const hostRef = useRef<HTMLDivElement>(null);
  const propsRef = useRef(props);
  const syncPresentation = useRef<() => void>(() => {});
  const wakeRef = useRef<() => void>(() => {});
  propsRef.current = props;

  useEffect(() => {
    const mount = hostRef.current;
    if (!mount) return;
    const host: HTMLDivElement = mount;

    let disposed = false;
    let created: THREE.WebGLRenderer | null = null;
    try {
      created = new THREE.WebGLRenderer({
        alpha: true,
        antialias: true,
        powerPreference: knowledge3dWebglPowerPreference(
          props.adapterPreference,
        ),
      });
    } catch {
      created = null;
    }
    if (!created) {
      propsRef.current.onContextLost();
      return;
    }
    const renderer: THREE.WebGLRenderer = created;
    renderer.setClearColor(0x000000, 0);
    renderer.autoClear = false;
    host.appendChild(renderer.domElement);
    renderer.domElement.style.width = "100%";
    renderer.domElement.style.height = "100%";
    renderer.domElement.style.display = "block";

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(FOV_DEGREES, 1, 1, 4000);
    const labelLayer = createKnowledge3dLabelLayer();
    const framed = knowledge3dFramedDistance(FOV_DEGREES);
    const orbit = {
      azimuth: 0,
      polar: KNOWLEDGE_3D_INITIAL_POLAR,
      distance: framed * KNOWLEDGE_3D_INITIAL_DOLLY,
      dragging: false,
      downX: 0,
      downY: 0,
      lastX: 0,
      lastY: 0,
      interactingUntil: 0,
    };
    // The ball stays centered at the world origin and the camera orbits
    // that same point, so Brain is always the exact center of the model
    // and rotation can never swing it off-axis; a projection view-offset
    // then shifts the whole rendered frame so that shared center sits
    // concentric with the background arc reactor.
    const viewAnchor = { x: 0.5, y: 0.5 };
    function applyViewAnchor(): void {
      if (!width || !height) return;
      camera.setViewOffset(
        width,
        height,
        (0.5 - viewAnchor.x) * width,
        (0.5 - viewAnchor.y) * height,
        width,
        height,
      );
    }

    // The MAIN executive cloud: built by the same createKnowledge3dCloud
    // implementation as every satellite, flagged main: true (owner
    // 2026-08-04 consolidation — one graph code path for all agents).
    let mainCloud: Knowledge3dCloud | null = null;
    let builtNodes: Knowledge3dRenderNode[] | null = null;
    let builtEdges: Knowledge3dRenderEdge[] | null = null;
    let builtWidth = 0;
    let builtHeight = 0;
    let builtPhysicsSignature = "";
    let hoverAppliedId: string | null | undefined = undefined;
    // Path timeline state: progress carries across phase transitions so
    // arrival completes from wherever thinking left it; the solid front
    // and the glow/flow clock derive from it every frame. The beam
    // uniforms live per-cloud; this is the one JS-side clock driving them.
    let appliedPathSpec: Knowledge3dPathSpec | null | undefined = undefined;
    let requestedPathSpec: Knowledge3dPathSpec | null = null;
    let tendrilPhase: KnowledgeFocusPhase = null;
    let tendrilPhaseStartedAt = 0;
    let tendrilProgressAtPhaseStart = 0;
    let tendrilProgress = 0;
    let solidProgress = 0;
    let glowStartedAt = -1;
    let mainFadeStartedAt = -1;
    let retainedFocus: Pick<Knowledge3dSceneProps, "pathSpec" | "focusNodeIds" | "activityAccents" | "focusPhase" | "focusKey" | "tuning"> | null = null;
    let appliedFocusKey: string | number | null = null;
    let selectionMoving = false;

    // Scene-global uniform objects shared into every cloud: the viewport,
    // the perspective/pulse/time trio the point shaders read, and the ONE
    // particle clock every cloud's shooting stars ride.
    const viewportUniform = { value: new THREE.Vector2(1, 1) };
    const uniforms = {
      uPerspective: { value: 1 },
      uPulse: { value: 0 },
      uSpeechLevel: { value: 0 },
      uTime: { value: 0 },
    };
    const sharedParticleTime = { value: 0 };
    // The scene module owns the canonical shader strings; every cloud —
    // main and satellites — receives the same deps object.
    const cloudDeps: Knowledge3dCloudDeps = {
      pointVertexShader: POINT_VERTEX_SHADER,
      pointFragmentShader: POINT_FRAGMENT_SHADER,
      pointDepthFragmentShader: POINT_DEPTH_FRAGMENT_SHADER,
      beamVertexShader: BEAM_VERTEX_SHADER,
      taxonomyFragmentShader: TAXONOMY_PATH_FRAGMENT_SHADER,
      crossFragmentShader: CROSS_PATH_FRAGMENT_SHADER,
      particleVertexShader: PARTICLE_VERTEX_SHADER,
      particleFragmentShader: PARTICLE_FRAGMENT_SHADER,
      particleTime: sharedParticleTime,
      parseColor: parseKnowledgeCssColor,
      sharedUniforms: uniforms,
      viewportUniform,
    };
    // Satellite clouds keyed by agent id; rebuilt per entry only when that
    // entry's inputs change, so one agent's tuning drag never replays
    // another ball's fall (owner 2026-08-03).
    const satelliteClouds = new Map<string, Knowledge3dCloud>();
    let builtSatellites: ReadonlyArray<Knowledge3dCloudInput> | undefined;
    // Role nameplates float over each ball. Library opts into a local Y turn;
    // other glyphs retain their camera-facing sprite behavior.
    type RolePlate = THREE.Sprite | THREE.Mesh<THREE.PlaneGeometry, THREE.MeshBasicMaterial>;
    const rolePlates = new Map<string, RolePlate>();
    let mainPlate: RolePlate | null = null;
    let libraryPlatePhase = 0;
    function createRolePlate(agentId: string): RolePlate {
      const role = knowledgeRoleForAgent(agentId);
      const texture = new THREE.CanvasTexture(
        paintKnowledgeRoleIcon(role, 128),
      );
      texture.colorSpace = THREE.SRGBColorSpace;
      const appearance = {
        map: texture,
        transparent: true,
        opacity: 0.85,
        depthTest: false,
        depthWrite: false,
      };
      if (role === "library") {
        const plate = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), new THREE.MeshBasicMaterial({
          ...appearance, side: THREE.DoubleSide, forceSinglePass: true,
        }));
        const parentRotation = new THREE.Quaternion(), cameraRotation = new THREE.Quaternion();
        const turn = new THREE.Quaternion(), axis = new THREE.Vector3(0, 1, 0);
        // Each presentation has its own camera. Remove the cloud's rotation
        // before applying that camera's facing direction and the icon's turn.
        plate.onBeforeRender = (_renderer, _scene, viewCamera) => {
          if (plate.parent) plate.parent.getWorldQuaternion(parentRotation);
          else parentRotation.identity();
          viewCamera.getWorldQuaternion(cameraRotation);
          plate.quaternion.copy(parentRotation.invert()).multiply(cameraRotation)
            .multiply(turn.setFromAxisAngle(axis, libraryPlatePhase));
          plate.updateWorldMatrix(false, false);
        };
        plate.renderOrder = 90;
        return plate;
      }
      const sprite = new THREE.Sprite(new THREE.SpriteMaterial(appearance));
      sprite.renderOrder = 90;
      return sprite;
    }
    function disposeRolePlate(sprite: RolePlate): void {
      sprite.parent?.remove(sprite);
      if (sprite instanceof THREE.Mesh) sprite.geometry.dispose();
      sprite.material.map?.dispose();
      sprite.material.dispose();
    }
    // Visible orbital rings keyed by agent (owner 2026-08-03): the ring is
    // the PATH, parented to the scene root — it neither orbits nor spins.
    const orbitRings = new Map<string, Knowledge3dOrbitRing>();
    // Per-agent satellite sweeps (Task thinking runs on EVERY cloud with a
    // live Task, concurrently): each cloud's clock starts when its entry's
    // key changes; the glow arms when its solid fill completes; a pulseKey
    // bump replays the neon pulse without restarting the run.
    const sweepStates = new Map<
      string,
      {
        key: string | number;
        startedAt: number;
        progress: number;
        progressAtStart: number;
        glowStartedAt: number;
        pulseKey: number;
        pulseStartedAt: number;
        /** The cloud object the spec was applied to: a snapshot refetch
         *  rebuilds the cloud (fresh beams start dormant, aP = -1), and
         *  the finished flow ITSELF refetches the assignee — the spec
         *  must re-apply to the NEW object or the lit path and launch
         *  pulse die mid-flash. */
        cloud: Knowledge3dCloud;
        sweep: NonNullable<Knowledge3dSceneProps["satelliteSweeps"]>[number];
        spec: Knowledge3dPathSpec;
        fadeStartedAt: number;
      }
    >();
    // Frame-gate memory: in-flight sweeps/comets earn 60 fps, a HELD Task
    // path (streaming dashes for minutes) only the interacting tier.
    let lastSweepHot = false;
    let lastSweepHeld = false;
    const deliveryComets = new Map<
      string,
      ReturnType<typeof createKnowledge3dDeliveryComet>
    >();
    const deliveryPoint = new THREE.Vector3();
    // Camera focus blend: 0 = world origin (main ball), 1 = the focused
    // satellite node; the target refreshes per frame so the stationary
    // orbit FOLLOWS the orbiting satellite.
    let focusBlend = 0;
    const focusPoint = new THREE.Vector3();
    const focusTargetPoint = new THREE.Vector3();

    let width = 0;
    let height = 0;
    let pixelRatio = 1;

    function updatePerspectiveUniform(): void {
      uniforms.uPerspective.value =
        (height * pixelRatio) /
        (2 * Math.tan(((FOV_DEGREES / 2) * Math.PI) / 180));
    }

    function buildMain(): void {
      const current = propsRef.current;
      const { nodes, edges, hub } = current;
      viewAnchor.x = hub.x;
      viewAnchor.y = hub.y;
      applyViewAnchor();
      builtNodes = nodes;
      builtEdges = edges;
      builtWidth = width;
      builtHeight = height;
      builtPhysicsSignature = knowledge3dCloudPhysicsSignature(current.tuning);
      // Carry the cooling state as well as positions. A repaint must not
      // reheat an unchanged layout; the shared cloud compares force inputs.
      const carried = mainCloud?.captureSimulation();
      if (mainCloud) {
        mainCloud.dispose(scene);
        mainCloud = null;
      }
      if (!nodes.length || !width || !height) return;
      mainCloud = createKnowledge3dCloud(
        {
          agentId: "main",
          nodes,
          edges,
          tuning: current.tuning,
          hub,
          main: true,
        },
        cloudDeps,
        height,
        pixelRatio,
        carried,
      );
      scene.add(mainCloud.group);
      // Force path/hover attribute refills: fresh geometry starts fully
      // dormant even when a query or hover is mid-flight.
      appliedPathSpec = undefined;
      hoverAppliedId = undefined;
    }

    // Diff the satellites prop against the live clouds: create/rebuild only
    // entries whose inputs changed, drop vanished agents. Runs every frame
    // but exits on identity, so identity-stable props cost one comparison.
    let builtSatelliteViewport = "";
    function syncSatellites(): void {
      const next = propsRef.current.satellites;
      // The viewport is a build input (worldPerPx/ring widths bake it in):
      // a resize rebuilds the clouds like it rebuilds the main ball.
      const viewportKey = `${width}x${height}x${pixelRatio}`;
      if (next === builtSatellites && viewportKey === builtSatelliteViewport) {
        return;
      }
      // Never record inputs we could not build yet (zero-size host):
      // the next sized frame must retry.
      if (!width || !height) return;
      builtSatellites = next;
      builtSatelliteViewport = viewportKey;
      const wanted = new Set<string>();
      for (const input of next ?? []) {
        wanted.add(input.agentId);
        const existing = satelliteClouds.get(input.agentId);
        if (
          existing &&
          existing.builtNodes === input.nodes &&
          existing.builtEdges === input.edges &&
          existing.builtSignature === knowledge3dCloudPhysicsSignature(input.tuning)
        ) {
          continue;
        }
        // Each cloud retains its own cooling state. Updates in another
        // graph or paint-only changes cannot disturb this cloud's layout.
        const carried = existing?.captureSimulation();
        if (existing) existing.dispose(scene);
        if (!input.nodes.length) {
          satelliteClouds.delete(input.agentId);
          continue;
        }
        const cloud = createKnowledge3dCloud(
          input,
          cloudDeps,
          height,
          pixelRatio,
          carried,
        );
        satelliteClouds.set(input.agentId, cloud);
        scene.add(cloud.group);
      }
      for (const [agentId, cloud] of satelliteClouds) {
        if (!wanted.has(agentId)) {
          cloud.dispose(scene);
          satelliteClouds.delete(agentId);
        }
      }
    }

    function applyCamera(): void {
      const polar = clampKnowledge3dPolar(orbit.polar);
      // Camera focus (owner 2026-08-03): the orbit center blends from the
      // world origin to the focused satellite node, and the dolly closes
      // in so the small ball fills the frame; drag/wheel keep working
      // around the blended center.
      const distance =
        clampKnowledge3dDolly(orbit.distance, framed) * (1 - focusBlend) +
        Math.max(34, orbit.distance * 0.42) * focusBlend;
      camera.position.set(
        focusPoint.x + distance * Math.sin(polar) * Math.sin(orbit.azimuth),
        focusPoint.y + distance * Math.cos(polar),
        focusPoint.z + distance * Math.sin(polar) * Math.cos(orbit.azimuth),
      );
      camera.lookAt(focusPoint);
    }

    function resize(): void {
      const bounds = host.getBoundingClientRect();
      const nextWidth = Math.max(1, Math.round(bounds.width));
      const nextHeight = Math.max(1, Math.round(bounds.height));
      if (nextWidth === width && nextHeight === height) return;
      width = nextWidth;
      height = nextHeight;
      pixelRatio = Math.min(window.devicePixelRatio || 1, 1.5);
      renderer.setPixelRatio(pixelRatio);
      renderer.setSize(width, height, false);
      labelLayer.resize(width, height, pixelRatio);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      applyViewAnchor();
      viewportUniform.value.set(width * pixelRatio, height * pixelRatio);
      updatePerspectiveUniform();
    }
    const observer = new ResizeObserver(resize);
    observer.observe(host);
    resize();

    function projectAll(): Map<string, { x: number; y: number }> {
      const projected = new Map<string, { x: number; y: number }>();
      // Main entries keep raw ids (main: true); satellite entries merge
      // under their agent-namespaced ids, so picking and labels see one
      // flat map.
      mainCloud?.projectInto(projected, camera);
      for (const cloud of satelliteClouds.values()) {
        cloud.projectInto(projected, camera);
      }
      return projected;
    }

    function pickNearest(clientX: number, clientY: number, graphId?: string): string | null {
      const bounds = renderer.domElement.getBoundingClientRect();
      if (!bounds.width || !bounds.height) return null;
      const px = (clientX - bounds.left) / bounds.width;
      const py = (clientY - bounds.top) / bounds.height;
      const projected = projectAll();
      let best: string | null = null;
      let bestDistance = HOVER_RADIUS_PX;
      for (const [id, point] of projected) {
        if (graphId && (parseKnowledgeAgentNodeId(id).agentId ?? propsRef.current.primaryGraphId ?? "main") !== graphId) continue;
        const distance = Math.hypot(
          (point.x - px) * bounds.width,
          (point.y - py) * bounds.height,
        );
        if (distance < bestDistance) {
          bestDistance = distance;
          best = id;
        }
      }
      return best;
    }

    let hoverAt = 0;
    function onPointerDown(event: PointerEvent): void {
      orbit.dragging = false;
      orbit.downX = event.clientX;
      orbit.downY = event.clientY;
      orbit.lastX = event.clientX;
      orbit.lastY = event.clientY;
      renderer.domElement.setPointerCapture(event.pointerId);
      const onMove = (move: PointerEvent) => {
        if (
          !orbit.dragging &&
          isKnowledge3dDrag(orbit.downX, orbit.downY, move.clientX, move.clientY)
        ) {
          orbit.dragging = true;
        }
        if (orbit.dragging) {
          orbit.azimuth -= (move.clientX - orbit.lastX) * 0.005;
          orbit.polar = clampKnowledge3dPolar(
            orbit.polar - (move.clientY - orbit.lastY) * 0.004,
          );
          orbit.interactingUntil = performance.now() + 1200;
          wake();
        }
        orbit.lastX = move.clientX;
        orbit.lastY = move.clientY;
      };
      const onUp = (up: PointerEvent) => {
        renderer.domElement.releasePointerCapture(up.pointerId);
        renderer.domElement.removeEventListener("pointermove", onMove);
        renderer.domElement.removeEventListener("pointerup", onUp);
        // A non-drag left press acts on the node under the pointer (reader
        // card); the ≥5px drag threshold still separates orbiting from
        // clicking so camera work never opens a card.
        if (!orbit.dragging && up.button === 0) {
          const picked = pickNearest(up.clientX, up.clientY);
          if (picked) {
            propsRef.current.onNodeAction?.("click", picked, {
              x: up.clientX,
              y: up.clientY,
            });
          } else {
            propsRef.current.onBackgroundClick?.();
          }
        }
        orbit.dragging = false;
      };
      renderer.domElement.addEventListener("pointermove", onMove);
      renderer.domElement.addEventListener("pointerup", onUp);
    }

    function onHoverMove(event: PointerEvent): void {
      const now = performance.now();
      if (now - hoverAt < 50 || orbit.dragging) return;
      hoverAt = now;
      propsRef.current.onHover?.(pickNearest(event.clientX, event.clientY));
    }

    function onPointerLeave(): void {
      propsRef.current.onHover?.(null);
    }

    function onWheel(event: WheelEvent): void {
      event.preventDefault();
      orbit.distance = clampKnowledge3dDolly(
        orbit.distance * (event.deltaY > 0 ? 1.08 : 0.92),
        framed,
      );
      orbit.interactingUntil = performance.now() + 1200;
      wake();
    }

    function onContextMenu(event: MouseEvent): void {
      event.preventDefault();
      const picked = pickNearest(event.clientX, event.clientY);
      if (picked) {
        propsRef.current.onNodeAction?.("context", picked, {
          x: event.clientX,
          y: event.clientY,
        });
      }
    }

    renderer.domElement.addEventListener("pointerdown", onPointerDown);
    renderer.domElement.addEventListener("pointermove", onHoverMove);
    renderer.domElement.addEventListener("contextmenu", onContextMenu);
    renderer.domElement.addEventListener("pointerleave", onPointerLeave);
    renderer.domElement.addEventListener("wheel", onWheel, { passive: false });
    const lostContext = () => propsRef.current.onContextLost();
    renderer.domElement.addEventListener("webglcontextlost", lostContext);

    let rafId = 0;
    let wakeTimer = 0;
    let paused = false;
    let frameDeadline = 0;
    let lastTick = performance.now();
    /** Run on the coming display refresh. A pending deadline timer is
     *  superseded, so props or input re-evaluate the cadence at once. */
    function wake(): void {
      if (wakeTimer) {
        window.clearTimeout(wakeTimer);
        wakeTimer = 0;
      }
      if (!disposed && !rafId) rafId = requestAnimationFrame(frame);
    }
    /** Sleep until a capped frame is due instead of polling every refresh. */
    function sleepUntil(deadline: number, now: number): void {
      if (rafId) return;
      window.clearTimeout(wakeTimer);
      wakeTimer = window.setTimeout(wake,
        Math.max(1, deadline - now - KNOWLEDGE_3D_FRAME_EARLY_TOLERANCE_MS));
    }
    wakeRef.current = wake;
    const emptyProjection = new Map<string, { x: number; y: number }>();

    // Open viewers borrow the live clouds and this renderer. Their isolated
    // camera pass adds no second graph, simulation or WebGL context. A 2D
    // transfer canvas supplies its frames to WebRTC and releases on close.
    type Preview = {canvas: HTMLCanvasElement; camera: THREE.PerspectiveCamera;
      publisher: GraphPublisher; cloud: () => Knowledge3dCloud | null | undefined;
      count: number; zoom: number; unforward?: () => void};
    const previews = new Map<string, Preview>();
    const previewCenter = new THREE.Vector3();
    const primaryId = propsRef.current.primaryGraphId ?? "main";
    function consumerCount() {
      propsRef.current.onPresentationConsumers?.([...previews.values()].reduce((sum, preview) => sum + preview.count, 0));
    }
    function positionPreview(preview: Preview, cloud: Knowledge3dCloud) {
      const input = cloud === mainCloud ? propsRef.current.tuning
        : propsRef.current.satellites?.find(entry => entry.agentId === cloud.agentId)?.tuning ?? propsRef.current.tuning;
      cloud.group.getWorldPosition(previewCenter);
      const radius = (cloud.layoutDiagnostics()?.radius ?? knowledge3dMaxShell(input)) * cloud.group.scale.x;
      const distance = (radius + 20 * input.graphScale) / Math.sin(FOV_DEGREES * Math.PI / 360) * preview.zoom;
      preview.camera.position.setFromSphericalCoords(distance, clampKnowledge3dPolar(orbit.polar), orbit.azimuth).add(previewCenter);
      preview.camera.lookAt(previewCenter); preview.camera.updateMatrixWorld();
    }
    function createPreview(id: string, source: GraphSource, cloud: Preview["cloud"]): Preview {
      const canvas = document.createElement("canvas"); canvas.width = canvas.height = 1;
      const preview = {canvas, camera: new THREE.PerspectiveCamera(FOV_DEGREES, 1, 0.1, 10000), cloud, count: 0, zoom: 1} as Preview;
      previews.set(id, preview);
      preview.publisher = new GraphPublisher(source, canvas, command => {
        const {action, x = 0, y = 0, dx = 0, dy = 0} = command;
        if (action === "orbit") {
          orbit.azimuth -= dx * 6; orbit.polar = clampKnowledge3dPolar(orbit.polar - dy * 5);
          orbit.interactingUntil = performance.now() + 1200;
        } else if (action === "zoom") preview.zoom = Math.max(0.35, Math.min(3, preview.zoom * Math.exp(dy * 0.3)));
        else if (action === "hover" || action === "click") {
          const target = preview.cloud(); let picked: string | null = null;
          if (target) {
            positionPreview(preview, target);
            const points = new Map<string, {x: number; y: number}>(); target.projectInto(points, preview.camera);
            let best = HOVER_RADIUS_PX / 1024;
            for (const [node, point] of points) {
              const distance = Math.hypot(point.x - x, point.y - y);
              if (distance < best) { best = distance; picked = node; }
            }
          }
          if (action === "hover") propsRef.current.onHover?.(picked);
          else propsRef.current.onPresentationCommand?.(picked ? {action: "select", id: picked} : {action: "clear"});
        } else if (action === "fit") {
          preview.zoom = 1; propsRef.current.onPresentationCommand?.({action: "clear"});
        } else if (action === "leave") propsRef.current.onHover?.(null);
        else propsRef.current.onPresentationCommand?.(command);
        frameDeadline = 0;
        wake();
      }, () => { frameDeadline = 0; wake(); }, count => {
        preview.count = count; const size = count ? 1024 : 1;
        if (canvas.width !== size) canvas.width = canvas.height = size;
        consumerCount();
      });
      return preview;
    }
    const primaryPreview = propsRef.current.sharePresentation
      ? createPreview(primaryId, propsRef.current.presentationSource ?? "knowledge", () => mainCloud) : null;
    const publisher = primaryPreview?.publisher ?? null;
    propsRef.current.onPresentationReady?.(publisher);
    function syncPreviewPorts() {
      if (!publisher) return;
      const live = new Set([primaryId]);
      for (const {agentId: id} of propsRef.current.satellites ?? []) {
        live.add(id);
        if (!previews.has(id)) {
          const preview = createPreview(id, `knowledge:${id}` as GraphSource, () => satelliteClouds.get(id));
          preview.unforward = publisher.forwardTo(preview.publisher);
        }
      }
      for (const [id, preview] of previews) if (!live.has(id)) {
        preview.unforward?.(); preview.publisher.dispose(); previews.delete(id);
      }
    }
    syncPresentation.current = syncPreviewPorts;
    syncPreviewPorts();
    function renderPreviews() {
      const active = [...previews.values()].filter(preview => preview.publisher.hasViewers && preview.cloud());
      if (!active.length) return;
      const visibility = scene.children.map(child => [child, child.visible] as const);
      const side = Math.min(width, height, 1024);
      renderer.setViewport(0, 0, side, side); renderer.setScissor(0, 0, side, side); renderer.setScissorTest(true);
      viewportUniform.value.set(side * pixelRatio, side * pixelRatio);
      uniforms.uPerspective.value = side * pixelRatio / (2 * Math.tan(FOV_DEGREES * Math.PI / 360));
      for (const preview of active) {
        const cloud = preview.cloud()!; positionPreview(preview, cloud);
        for (const [child] of visibility) child.visible = child === cloud.group;
        renderer.clear(true, true, true); renderer.render(scene, preview.camera);
        const transfer = preview.canvas.getContext("2d")!;
        transfer.globalCompositeOperation = "copy";
        transfer.drawImage(renderer.domElement, 0, renderer.domElement.height - side * pixelRatio,
          side * pixelRatio, side * pixelRatio, 0, 0, preview.canvas.width, preview.canvas.height);
        preview.publisher.frame();
      }
      for (const [child, visible] of visibility) child.visible = visible;
      renderer.setScissorTest(false); renderer.setViewport(0, 0, width, height);
      viewportUniform.value.set(width * pixelRatio, height * pixelRatio); updatePerspectiveUniform();
    }

    function frame(now: number): void {
      rafId = 0;
      if (disposed) return;
      const current = propsRef.current;
      if (
        !knowledge3dAnimationEnabled({
          visible: current.visible,
          reducedMotion: current.reducedMotion,
        })
      ) {
        // Hidden: stop the loop; the render that shows it again wakes it.
        paused = true;
        return;
      }
      if (paused) {
        // Resume from rest without a catch-up step.
        paused = false;
        lastTick = now;
        frameDeadline = 0;
      }
      const interacting = now < orbit.interactingUntil;
      const relationEffects = current.relationEffects ?? [];
      const pendingLinks = relationEffects.some((effect) => effect.phase === "pending");
      const approvalActive = relationEffects.some((effect) =>
        effect.phase === "approved" && Number.isFinite(effect.startedAt) &&
        effect.startedAt <= now &&
        now - effect.startedAt < KNOWLEDGE_LINK_APPROVAL_DURATION_MS);
      let satellitesHot = false;
      for (const cloud of satelliteClouds.values()) {
        if (cloud.isHot()) {
          satellitesHot = true;
          break;
        }
      }
      // Satellites always orbit, so any live satellite keeps the loop at
      // least at the idle cadence; a settling satellite ORs into the sim
      // term so its fall keeps ticking at full rate.
      const simActive = (mainCloud?.isHot() ?? false) || satellitesHot;
      const envelope = current.speechEnvelope?.current;
      const speechTarget = envelope && now - envelope.updatedAt < 250 ? envelope.level : 0;
      const interval = knowledge3dFrameIntervalMs({
        focusActive:
          current.focusActive || retainedFocus !== null || speechTarget > 0 || uniforms.uSpeechLevel.value > 0.001 ||
          mainFadeStartedAt >= 0 || selectionMoving ||
          simActive || lastSweepHot || approvalActive ||
          deliveryComets.size > 0 || (current.deliveries?.length ?? 0) > 0 ||
          current.cameraFocus != null,
        interacting: interacting || lastSweepHeld || pendingLinks,
        animationProfile: current.animationProfile,
      });
      const nextDeadline = advanceKnowledge3dFrameDeadline(
        frameDeadline,
        now,
        interval,
      );
      if (nextDeadline === null) {
        sleepUntil(frameDeadline + interval, now);
        return;
      }
      const dt = Math.min(0.2, (now - lastTick) / 1000);
      frameDeadline = nextDeadline;
      lastTick = now;
      // Schedule the next frame first; uncapped active motion follows the display.
      if (interval > 0) sleepUntil(frameDeadline + interval, now);
      else rafId = requestAnimationFrame(frame);
      // Active render time only: 30 seconds per turn, with the existing
      // visibility gate and bounded resume delta. Match Memory icons' motion preference.
      if (!current.reducedMotion)
        libraryPlatePhase = (libraryPlatePhase + dt * Math.PI * 2 / 30) % (Math.PI * 2);
      // A quick attack follows consonants; a short release bridges 40 ms PCM
      // samples. Silence, STOP and a stalled stream return the orb to rest.
      const speechTau = speechTarget > uniforms.uSpeechLevel.value ? 0.025 : 0.085;
      uniforms.uSpeechLevel.value += (speechTarget - uniforms.uSpeechLevel.value)
        * (1 - Math.exp(-dt / speechTau));

      // The render model and the host geometry are the only build inputs:
      // a new snapshot layout, a resize, or an aspect change re-targets the
      // spring; identity-stable props cost nothing per frame.
      if (
        current.nodes !== builtNodes ||
        current.edges !== builtEdges ||
        width !== builtWidth ||
        height !== builtHeight ||
        knowledge3dCloudPhysicsSignature(current.tuning) !== builtPhysicsSignature
      ) {
        buildMain();
      }
      syncSatellites();

      // Live tuning: visual knobs drive uniforms directly every frame.
      // uTime wraps hourly: the shaders run fp32, and an unbounded
      // seconds-since-load value erodes fract() resolution until the
      // ~0.5 s twinkle pulses turn into stepped blinks after days of
      // kiosk uptime (adversarial review 2026-08-02). The wrap reshuffles
      // the chaotic churn/twinkle phases once an hour — imperceptible.
      const shaderTime = (now % 3_600_000) / 1000;
      const tuning = current.tuning;
      uniforms.uTime.value = shaderTime;
      // Live tuning rides the cloud's own uniform writes — node glow,
      // styles, the whole-graph render transform (group scale + matched
      // uModelScale + screen-px beam widths), dash frequency and streaks.
      mainCloud?.applyTuning(tuning, pixelRatio);

      // Tick the live physics while hot, then go dormant: the cooled ball
      // only rotates via the camera transform (zero per-node work).
      mainCloud?.tickIfHot();
      mainCloud?.applyRelationEffects(relationEffects, now);

      // Satellites: live tuning (visual + orbit knobs update without a
      // rebuild), orbit advance, and their own sim ticks while hot. The
      // orbit rides the UNWRAPPED clock: theta = phase + speed·t, so the
      // shader clock's hourly wrap would teleport every satellite ~165°
      // once an hour (adversarial review 2026-08-03) — JS doubles don't
      // need the fp32 fract() protection the wrap exists for.
      // Main ball's executive nameplate rides the same toggle.
      const platesOn = tuning.rolePlates >= 0.5;
      if (platesOn && !mainPlate) {
        mainPlate = createRolePlate(current.primaryGraphId ?? "main");
      } else if (!platesOn && mainPlate) {
        disposeRolePlate(mainPlate);
        mainPlate = null;
      }
      if (mainPlate && mainCloud) {
        // Re-attaches after cloud rebuilds, like the satellite plates.
        if (mainPlate.parent !== mainCloud.group) {
          mainCloud.group.add(mainPlate);
        }
        // Above the outermost shell; group scale multiplies this.
        const top = (mainCloud.layoutDiagnostics()?.radius ?? knowledge3dMaxShell(tuning)) + 13;
        mainPlate.position.set(0, top, 0);
        mainPlate.scale.setScalar(18);
      }
      if (satelliteClouds.size || orbitRings.size || rolePlates.size) {
        const orbitSeconds = now / 1000;
        const liveAgents = new Set<string>();
        for (const input of current.satellites ?? []) {
          const cloud = satelliteClouds.get(input.agentId);
          if (!cloud) continue;
          liveAgents.add(input.agentId);
          cloud.applyTuning(input.tuning, pixelRatio);
          cloud.updateOrbit(input.tuning, orbitSeconds);
          cloud.tickIfHot();
          cloud.applyRelationEffects(relationEffects, now);
          // Role nameplate lifecycle (re-attaches after cloud rebuilds).
          let plate = rolePlates.get(input.agentId);
          if (platesOn && !plate) {
            plate = createRolePlate(input.agentId);
            rolePlates.set(input.agentId, plate);
          } else if (!platesOn && plate) {
            disposeRolePlate(plate);
            rolePlates.delete(input.agentId);
            plate = undefined;
          }
          if (plate) {
            if (plate.parent !== cloud.group) cloud.group.add(plate);
            // Satellite physics run at FULL scale and the group render
            // transform carries saved graphScale × ballScale, so the plate's
            // local offset margin and scale divide ballScale back out —
            // the world-space glyph stays keyed to graphScale exactly
            // once, same as before the consolidation.
            const ballScale = Math.max(0.05, input.tuning.ballScale);
            const satTop =
              (cloud.layoutDiagnostics()?.radius ?? knowledge3dMaxShell(input.tuning)) + 9 / ballScale;
            plate.position.set(0, satTop, 0);
            plate.scale.setScalar(12 / ballScale);
          }
          // Orbital ring lifecycle rides the per-agent toggle.
          const wantRing = input.tuning.orbitLine >= 0.5;
          let ring = orbitRings.get(input.agentId);
          if (wantRing && !ring) {
            const rootColor =
              input.nodes.find(
                (node) => node.role === "root" || node.depth === 0,
              )?.core ?? "rgba(103, 232, 249, 1)";
            ring = createKnowledge3dOrbitRing(input.agentId, rootColor, {
              beamVertexShader: BEAM_VERTEX_SHADER,
              crossFragmentShader: CROSS_PATH_FRAGMENT_SHADER,
              parseColor: parseKnowledgeCssColor,
              viewportUniform,
            });
            orbitRings.set(input.agentId, ring);
            scene.add(ring.object);
          } else if (!wantRing && ring) {
            ring.dispose(scene);
            orbitRings.delete(input.agentId);
            ring = undefined;
          }
          ring?.update(input.tuning, pixelRatio);
        }
        for (const [ringAgentId, ring] of orbitRings) {
          if (!liveAgents.has(ringAgentId)) {
            ring.dispose(scene);
            orbitRings.delete(ringAgentId);
          }
        }
        for (const [plateAgentId, plate] of rolePlates) {
          if (!liveAgents.has(plateAgentId)) {
            disposeRolePlate(plate);
            rolePlates.delete(plateAgentId);
          }
        }
      }

      // The beam head leads the solid fill on one readable clock. Flow
      // continues through speaking. Only reaching the final link triggers
      // the neon pulse; speech edges never fast-forward a moving front.
      // Hover-subtree preview: recompute the descendant set and the beam
      // flags only when the hovered node changes.
      if (current.hoveredNodeId !== hoverAppliedId) {
        hoverAppliedId = current.hoveredNodeId;
        // Route the raw id to the owning cloud — every cloud (main and
        // satellite) previews the hovered node's WHOLE subtree; a
        // namespaced id never matches a main node, so the main hover
        // path stays inert for it.
        const parsedHover = hoverAppliedId
          ? parseKnowledgeAgentNodeId(hoverAppliedId)
          : null;
        for (const [cloudAgentId, cloud] of satelliteClouds) {
          cloud.setHovered(
            parsedHover && parsedHover.agentId === cloudAgentId
              ? parsedHover.nodeId
              : null,
          );
        }
        mainCloud?.setHovered(
          hoverAppliedId && parsedHover?.agentId == null
            ? hoverAppliedId
            : null,
        );
      }
      const selection = current.selectionPath;
      selectionMoving = mainCloud?.driveSelection(selection?.agentId === "main" ? selection.spec : null,
        selection?.id ?? "", now) ?? false;
      for (const [agentId, cloud] of satelliteClouds) {
        selectionMoving = cloud.driveSelection(selection?.agentId === agentId ? selection.spec : null,
          selection?.id ?? "", now) || selectionMoving;
      }
      if (retainedFocus && current.clearedActivityKeys?.has(String(retainedFocus.focusKey))) {
        retainedFocus = null;
        mainFadeStartedAt = -1;
      }
      if (current.pathSpec && current.focusActive && !current.clearedActivityKeys?.has(String(current.focusKey))) {
        const sameRun = retainedFocus?.focusKey === current.focusKey;
        const pathSpec = sameRun && requestedPathSpec === current.pathSpec
          ? retainedFocus!.pathSpec
          : extendKnowledge3dPathSpec(sameRun ? retainedFocus!.pathSpec : null, current.pathSpec, tendrilProgress);
        requestedPathSpec = current.pathSpec;
        retainedFocus = { ...current, pathSpec };
        mainFadeStartedAt = -1;
      } else if (retainedFocus?.pathSpec && mainFadeStartedAt < 0
        && tendrilProgress >= retainedFocus.pathSpec.maxProgress + knowledge3dSweepTail(retainedFocus.pathSpec)) {
        mainFadeStartedAt = now;
      }
      const fadeT = mainFadeStartedAt < 0 ? 0 : Math.min(1, (now - mainFadeStartedAt) / KNOWLEDGE_ACTIVITY_FADE_MS);
      const pathOpacity = 1 - fadeT * fadeT * (3 - 2 * fadeT);
      if (fadeT === 1) { retainedFocus = null; mainFadeStartedAt = -1; }
      const focus = retainedFocus ?? current;
      const spec = focus.pathSpec;
      if (retainedFocus && focus.focusKey !== appliedFocusKey) {
        appliedFocusKey = focus.focusKey;
        tendrilProgress = 0;
        solidProgress = 0;
        tendrilProgressAtPhaseStart = 0;
        tendrilPhaseStartedAt = now;
        glowStartedAt = -1;
      }
      if (spec !== appliedPathSpec) {
        appliedPathSpec = spec;
        mainCloud?.applyPathSpec(spec ?? null);
        // Rebase the clock on the visible (capped) progress: the linear
        // term keeps accruing while parked at the cap, so without a
        // rebase a plan that GROWS mid-flight (a later Obsidience retrieval
        // extends the route) snaps the extension on instantly instead of
        // traveling it (adversarial review 2026-08-02). If the extension
        // re-opens the route, the completion pulse re-arms for the full
        // fill.
        tendrilPhaseStartedAt = now;
        tendrilProgressAtPhaseStart = tendrilProgress;
        if (
          spec &&
          glowStartedAt >= 0 &&
          tendrilProgress - spec.firstNodeProgress <
            spec.maxProgress - 1e-4
        ) {
          glowStartedAt = -1;
        }
      }
      if (focus.focusPhase !== tendrilPhase) {
        tendrilPhaseStartedAt = now;
        tendrilProgressAtPhaseStart =
          focus.focusPhase === null ? 0 : tendrilProgress;
        tendrilPhase = focus.focusPhase;
      }
      if (!spec || tendrilPhase === null || !retainedFocus) {
        tendrilProgress = 0;
        solidProgress = 0;
        glowStartedAt = -1;
        mainCloud?.drivePathTimeline(-1, -1, 0, -1);
      } else {
        // Keep beam and trailing fill on the same continuous clock, including
        // any remaining route after a short reply has already ended.
        tendrilProgress = knowledgeSweepProgress3d(
          tendrilPhase,
          now - tendrilPhaseStartedAt,
          tendrilProgressAtPhaseStart,
          focus.tuning.sweepSpeed,
          spec.maxProgress,
          // Run-out covers the solid front's lag PLUS the ignition ramp
          // so the deepest article (arrival == maxProgress) completes.
          knowledge3dSweepTail(spec),
        );
        solidProgress = tendrilProgress - spec.firstNodeProgress;
        if (
          glowStartedAt < 0 &&
          solidProgress >= spec.maxProgress - 1e-4
        ) {
          glowStartedAt = now;
        }
        let glow = 0;
        let flowAge = -1;
        if (glowStartedAt >= 0) {
          const age = (now - glowStartedAt) / 1000;
          if (age < PATH_GLOW_SECONDS) {
            glow = Math.sin((age / PATH_GLOW_SECONDS) * Math.PI);
          } else {
            flowAge = age - PATH_GLOW_SECONDS;
          }
        }
        mainCloud?.drivePathTimeline(
          Math.min(tendrilProgress, spec.maxProgress),
          solidProgress > 1e-4
            ? Math.min(solidProgress, spec.maxProgress)
            : -1,
          glow,
          flowAge,
          Math.max(0.02, spec.firstArticleProgress * 0.07),
          pathOpacity,
        );
      }
      sharedParticleTime.value = shaderTime;
      // Nodes ignite as the SOLID line reaches them (owner 2026-08-02),
      // gated by the focus set so only the active route may light.
      mainCloud?.applyFocusReveal(spec ?? null, solidProgress, {
        active: Boolean(retainedFocus),
        nodeIds: focus.focusNodeIds,
        accents: focus.activityAccents,
        opacity: pathOpacity,
      });
      uniforms.uPulse.value = 0.5 + 0.5 * Math.sin(now / 300);

      // Satellite sweeps: same constant-speed law as the main path — beam
      // head first, solid front trailing by the first-node lag, neon glow
      // on completion, then segmented flow. Task thinking (owner 2026-08-04)
      // runs one sweep per working agent CONCURRENTLY and HOLDS the lit
      // path (dashes streaming) until the Task finishes; a pulseKey bump
      // replays the whole-path pulse as a delivery comet departs.
      const sweeps = current.satelliteSweeps ?? [];
      let satelliteSweepHot = false;
      let satelliteSweepHeld = false;
      const fadingSweeps = [];
      for (const [agentId, state] of sweepStates) {
        if (current.clearedActivityKeys?.has(String(state.key))) {
          satelliteClouds.get(agentId)?.applyPathSpec(null);
          satelliteClouds.get(agentId)?.applyFocusReveal(null, 0);
          sweepStates.delete(agentId);
          continue;
        }
        if (!sweeps.some((entry) => entry.agentId === agentId)) {
          if (state.fadeStartedAt < 0 && state.progress >= state.spec.maxProgress + knowledge3dSweepTail(state.spec)) state.fadeStartedAt = now;
          if (state.fadeStartedAt < 0 || now - state.fadeStartedAt < KNOWLEDGE_ACTIVITY_FADE_MS) fadingSweeps.push(state.sweep);
          else {
            satelliteClouds.get(agentId)?.applyPathSpec(null);
            satelliteClouds.get(agentId)?.applyFocusReveal(null, 0);
            sweepStates.delete(agentId);
          }
        } else {
          state.fadeStartedAt = -1;
        }
      }
      for (const sweep of [...sweeps, ...fadingSweeps]) {
        if (current.clearedActivityKeys?.has(String(sweep.key))) continue;
        const cloud = satelliteClouds.get(sweep.agentId);
        if (!cloud) continue;
        let state = sweepStates.get(sweep.agentId);
        if (!state || state.key !== sweep.key) {
          state = {
            key: sweep.key,
            startedAt: now,
            progress: 0,
            progressAtStart: 0,
            glowStartedAt: -1,
            pulseKey: sweep.pulseKey ?? 0,
            pulseStartedAt: -1,
            cloud,
            sweep,
            spec: sweep.spec,
            fadeStartedAt: -1,
          };
          sweepStates.set(sweep.agentId, state);
          cloud.applyPathSpec(state.spec);
        } else if (state.cloud !== cloud) {
          // The cloud was rebuilt under a live sweep: re-arm the path on
          // the fresh geometry (the timeline clock keeps running).
          state.cloud = cloud;
          cloud.applyPathSpec(state.spec);
        }
        if (state.sweep.spec !== sweep.spec) {
          state.spec = extendKnowledge3dPathSpec(state.spec, sweep.spec, state.progress);
          cloud.applyPathSpec(state.spec);
          state.progressAtStart = state.progress;
          state.startedAt = now;
          if (state.progress - state.spec.firstNodeProgress < state.spec.maxProgress) state.glowStartedAt = -1;
        }
        state.sweep = sweep;
        const fadeT = state.fadeStartedAt < 0 ? 0 : Math.min(1, (now - state.fadeStartedAt) / KNOWLEDGE_ACTIVITY_FADE_MS);
        const opacity = 1 - fadeT * fadeT * (3 - 2 * fadeT);
        if ((sweep.pulseKey ?? 0) !== state.pulseKey) {
          state.pulseKey = sweep.pulseKey ?? 0;
          state.pulseStartedAt = now;
        }
        const cloudTuning =
          (current.satellites ?? []).find(
            (input) => input.agentId === sweep.agentId,
          )?.tuning ?? tuning;
        const tail = knowledge3dSweepTail(state.spec);
        const progress = knowledgeSweepProgress3d(
          sweep.phase ?? "thinking",
          now - state.startedAt,
          state.progressAtStart,
          sweep.speed ?? cloudTuning.sweepSpeed,
          state.spec.maxProgress,
          tail,
        );
        state.progress = progress;
        const solid = progress - state.spec.firstNodeProgress;
        if (state.glowStartedAt < 0 && solid >= state.spec.maxProgress - 1e-4) {
          state.glowStartedAt = now;
        }
        let glow = 0;
        let flowAge = -1;
        if (state.glowStartedAt >= 0) {
          const age = (now - state.glowStartedAt) / 1000;
          if (age < PATH_GLOW_SECONDS) {
            glow = Math.sin((age / PATH_GLOW_SECONDS) * Math.PI);
          } else {
            flowAge = age - PATH_GLOW_SECONDS;
          }
        }
        if (state.pulseStartedAt >= 0) {
          const pulseAge = (now - state.pulseStartedAt) / 1000;
          if (pulseAge < PATH_GLOW_SECONDS) {
            glow = Math.max(
              glow,
              Math.sin((pulseAge / PATH_GLOW_SECONDS) * Math.PI),
            );
          } else {
            state.pulseStartedAt = -1;
          }
        }
        cloud.drivePathTimeline(
          Math.min(progress, state.spec.maxProgress),
          solid > 1e-4 ? Math.min(solid, state.spec.maxProgress) : -1,
          glow,
          flowAge,
          undefined,
          opacity,
        );
        cloud.applyFocusReveal(state.spec, solid, {
          active: true, nodeIds: sweep.nodeIds ?? new Set(sweep.spec.nodeArrival.keys()), accents: sweep.accents,
          opacity,
        });
        if (flowAge < 0 || state.pulseStartedAt >= 0 || state.fadeStartedAt >= 0) {
          satelliteSweepHot = true;
        } else if (sweep.hold) {
          satelliteSweepHeld = true;
        }
      }
      lastSweepHot = satelliteSweepHot;
      lastSweepHeld = satelliteSweepHeld;

      // Delivery comets: the article flies from the assignee's ball to the
      // freshly-admitted node on the target graph (main or satellite) and
      // bursts as its arrival flash. Both endpoints re-resolve every frame
      // because both clouds keep orbiting/spinning mid-flight.
      const currentDeliveries = current.deliveries ?? [];
      for (const [key, comet] of deliveryComets) {
        if (!currentDeliveries.some((entry) => entry.key === key)) {
          comet.dispose(scene);
          deliveryComets.delete(key);
        }
      }
      for (const delivery of currentDeliveries) {
        let comet = deliveryComets.get(delivery.key);
        if (!comet) {
          comet = createKnowledge3dDeliveryComet(delivery.key, scene);
          deliveryComets.set(delivery.key, comet);
        }
        const fromCloud = satelliteClouds.get(delivery.fromAgentId);
        const toCloud =
          delivery.toAgentId === null
            ? mainCloud
            : (satelliteClouds.get(delivery.toAgentId) ?? null);
        const status = comet.update(
          now,
          (out) => {
            if (!fromCloud) return false;
            fromCloud.group.getWorldPosition(deliveryPoint);
            out.copy(deliveryPoint);
            return true;
          },
          (out) => toCloud?.nodeWorldPosition(delivery.nodeId, out) ?? false,
          uniforms.uPerspective.value as number,
        );
        if (status !== "active") {
          comet.dispose(scene);
          deliveryComets.delete(delivery.key);
          current.onDeliveryDone?.(delivery.key);
        }
      }

      // Camera focus: refresh the target from the ORBITING satellite every
      // frame and ease the blend; idle yaw pauses while focused so the
      // orbit is genuinely stationary.
      const focusRequest = current.cameraFocus;
      let focusResolved = false;
      if (focusRequest) {
        if (focusRequest.agentId === null) {
          // Main-ball node: world position through the (scaled) main group.
          if (
            mainCloud?.nodeWorldPosition(focusRequest.nodeId, focusTargetPoint)
          ) {
            focusResolved = true;
          }
        } else {
          const cloud = satelliteClouds.get(focusRequest.agentId);
          if (
            cloud?.nodeWorldPosition(focusRequest.nodeId, focusTargetPoint)
          ) {
            focusResolved = true;
          }
        }
      }
      focusBlend = Math.min(
        1,
        Math.max(0, focusBlend + (focusResolved ? 1 : -1) * dt * 2.4),
      );
      if (focusResolved) {
        focusPoint.lerpVectors(
          focusPoint.lengthSq() < 1e-9 && focusBlend < 0.05
            ? focusTargetPoint
            : focusPoint,
          focusTargetPoint,
          Math.min(1, dt * 6 + (focusBlend >= 1 ? 1 : 0)),
        );
      } else if (focusBlend <= 0) {
        focusPoint.set(0, 0, 0);
      } else {
        focusPoint.multiplyScalar(Math.max(0, 1 - dt * 2.4));
      }

      if (!interacting && focusBlend < 0.5) {
        orbit.azimuth += tuning.yawSpeed * dt;
      }
      applyCamera();
      // Painter's algorithm: each cloud re-sorts its sprite draw order
      // back-to-front in cloud-local space (worldToLocal folds translation,
      // spin, and the uniform render scale into the comparison).
      mainCloud?.sortSprites(camera.position);
      // Inter-cloud occlusion: every material renders depthTest:false, so
      // clouds occlude by draw order alone — farthest cloud first. Each
      // cloud keeps its intra offsets (beams 0, orbs 1, streaks 2) inside
      // a base block of 4 per rank.
      if (satelliteClouds.size) {
        const ranked: Array<{ distance: number; children: THREE.Object3D[] }> =
          [];
        if (mainCloud) {
          ranked.push({
            distance: mainCloud.distanceTo(camera.position),
            children: mainCloud.group.children,
          });
        }
        for (const cloud of satelliteClouds.values()) {
          cloud.sortSprites(camera.position);
          ranked.push({
            distance: cloud.distanceTo(camera.position),
            children: cloud.group.children,
          });
        }
        ranked.sort((a, b) => b.distance - a.distance);
        ranked.forEach((entry, rank) => {
          for (const child of entry.children) {
            child.renderOrder = rank * 4 + (child.renderOrder % 4);
          }
        });
      }
      // Labels follow the same admitted path and frame clock as their beams.
      const activeLabelNodeIds = new Set<string>();
      if (current.showActivityLabels && retainedFocus && spec) {
        for (const [id, arrival] of spec.nodeArrival) {
          if (focus.focusNodeIds.has(id) && arrival <= solidProgress) activeLabelNodeIds.add(id);
        }
      }
      for (const [agentId, state] of current.showActivityLabels ? sweepStates : []) {
        for (const [id, arrival] of state.spec.nodeArrival) {
          if ((!state.sweep.nodeIds || state.sweep.nodeIds.has(id))
            && arrival <= state.progress - state.spec.firstNodeProgress) {
            activeLabelNodeIds.add(knowledgeAgentNodeId(agentId, id));
          }
        }
      }
      const labelIds = [...new Set([...current.labelIds, ...activeLabelNodeIds])];
      labelLayer.update(
        labelIds.length ? projectAll() : emptyProjection,
        labelIds,
        activeLabelNodeIds,
        current.labelMetadata,
        Boolean(retainedFocus),
        now,
      );
      renderPreviews();
      renderer.clear(true, true, true);
      renderer.render(scene, camera);
      renderer.clearDepth();
      labelLayer.render(renderer);
    }
    rafId = requestAnimationFrame(frame);

    return () => {
      disposed = true;
      syncPresentation.current = () => {};
      wakeRef.current = () => {};
      cancelAnimationFrame(rafId);
      window.clearTimeout(wakeTimer);
      observer.disconnect();
      for (const preview of previews.values()) { preview.unforward?.(); preview.publisher.dispose(); }
      previews.clear();
      propsRef.current.onPresentationReady?.(null);
      renderer.domElement.removeEventListener("pointerdown", onPointerDown);
      renderer.domElement.removeEventListener("pointermove", onHoverMove);
      renderer.domElement.removeEventListener("contextmenu", onContextMenu);
      renderer.domElement.removeEventListener("pointerleave", onPointerLeave);
      renderer.domElement.removeEventListener("wheel", onWheel);
      renderer.domElement.removeEventListener("webglcontextlost", lostContext);
      mainCloud?.dispose(scene);
      mainCloud = null;
      for (const cloud of satelliteClouds.values()) cloud.dispose(scene);
      satelliteClouds.clear();
      for (const ring of orbitRings.values()) ring.dispose(scene);
      orbitRings.clear();
      for (const comet of deliveryComets.values()) comet.dispose(scene);
      deliveryComets.clear();
      for (const plate of rolePlates.values()) disposeRolePlate(plate);
      rolePlates.clear();
      if (mainPlate) disposeRolePlate(mainPlate);
      mainPlate = null;
      labelLayer.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
    // Mount-once: everything dynamic reads through propsRef.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => syncPresentation.current(), [props.satellites]);
  // Every prop change (visibility, focus, activity) re-evaluates the cadence.
  useEffect(() => wakeRef.current());

  return (
    <div
      ref={hostRef}
      data-testid="knowledge-3d-scene"
      className="absolute inset-0"
      aria-hidden="true"
    />
  );
}
