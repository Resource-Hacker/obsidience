// Pure math + policy for the 3D knowledge scene. Everything WebGL-free so
// the contracts stay unit-testable under jsdom (which has no GL context).
//
// Owner-directed 2026-07-31 (third revision, reference: vasturiano's
// 3d-force-graph): the model is a LIVE physics simulation — d3-force-3d
// (the exact engine behind that reference) with link springs on the
// taxonomy tree, weak springs on attested cross-links, many-body charge
// repulsion and one coupled spherical solver for avoidance, outward edges,
// shared depth shells and recursive moving crown territories radiating from the
// pinned Brain as a ball. Seeds are normalized onto their shared layers
// before the first frame and visibly spread/wobble angularly into place
// as the simulation cools; the scene ticks until cooling AND geometric
// convergence (or an explicit bounded failure), then the ball only rotates. Rendering stays
// 2D-parity (the sprite shader replicating the flat canvas painter) with
// the depth glow attenuated, and the ambient 2D/3D toggle remains.

import {
  createSphericalConstraint,
  type SphericalConstraint,
  type SphericalState,
} from "./knowledge-spherical";
export type { SphericalState, SphericalResiduals, SphericalStatus } from "./knowledge-spherical";

import {
  forceCollide,
  forceRadial,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type ForceSimulation,
  type ForceSimulationNode,
} from "d3-force-3d";
import type {
  KnowledgeLayout,
  KnowledgeLayoutNode,
} from "./knowledge-layout";
import type {
  GraphicsAdapterPreference,
  GraphicsAnimationProfile,
} from "../../../../../main/config/schema";
import { isKnowledgeLeafRole } from "./knowledge-ontology";
import type { KnowledgeHierarchyRole } from "./knowledge-ontology";

/** World-unit span the camera frames (the ball's outer shells live well
 *  inside this). */
export const KNOWLEDGE_3D_WORLD_SPAN = 190;
/** Camera framing margin so rotation/drift never clips rim nodes; carries
 *  the 2D KNOWLEDGE_AMBIENT_MAX_RENDER_SCALE (1.047 drift peak) obligation
 *  into the camera frustum. */
export const KNOWLEDGE_3D_FRAME_MARGIN = 1.08;
/** Render cadences (fps). Interaction runs at the 2D pipeline's 30 fps
 *  cap; idle ambient rotation renders at half cadence. The thinking
 *  sweep runs at 60 fps (owner 2026-08-02: "the line should feel like it
 *  is filling up the beam fluidly" — a 33 ms gate beats unevenly against
 *  the 120 Hz kiosk display and made the traveling fronts stutter). */
export const KNOWLEDGE_3D_ACTIVE_FPS = 30;
export const KNOWLEDGE_3D_SWEEP_FPS = 60;
export const KNOWLEDGE_3D_IDLE_FPS = 15;
/** Browser rAF timestamps can arrive fractionally before an exact cadence
 *  boundary. Accepting a frame within this tolerance avoids turning a nominal
 *  60 Hz stream into a 30 Hz sawtooth. */
export const KNOWLEDGE_3D_FRAME_EARLY_TOLERANCE_MS = 1;
/** Pointer movement below this (px) stays a click — and ambient clicks stay
 *  inert (inspect-gated), matching the 2D interaction contract. */
export const KNOWLEDGE_3D_DRAG_THRESHOLD_PX = 5;

/** The camera starts head-on and orbits the Brain anchor. The ball is
 *  readable from every azimuth, so yaw is unclamped and idles as a slow
 *  continuous rotation; polar keeps a clamp away from the poles so drag
 *  can never gimbal-flip the view. */
export const KNOWLEDGE_3D_INITIAL_POLAR = Math.PI / 2;
export const KNOWLEDGE_3D_MIN_POLAR = 0.35;
export const KNOWLEDGE_3D_MAX_POLAR = Math.PI - 0.35;
/** Idle yaw in radians/second — slow enough to read labels, alive enough
 *  to make the model unmistakably 3D. */
export const KNOWLEDGE_3D_IDLE_YAW_RAD_PER_SEC = 0.05;
/** Dolly clamps as multiples of the framed distance; the camera starts
 *  slightly outside the exact framing so the ball's near hemisphere (which
 *  perspective enlarges) stays inside the hub's asymmetric headroom. */
export const KNOWLEDGE_3D_MIN_DOLLY = 0.35;
export const KNOWLEDGE_3D_MAX_DOLLY = 2.4;
export const KNOWLEDGE_3D_INITIAL_DOLLY = 1.1;

/** 3D sprites attenuate the palette depth-glow alpha: identical alpha over
 *  the denser ball (plus perspective-enlarged near nodes) reads bloomier
 *  than the flat map, so the 3D model tones it down to match the 2D look. */
export const KNOWLEDGE_3D_GLOW_ATTENUATION = 0.6;

/** The kiosk display's xsettingsd broadcasts Gtk/EnableAnimations 0, which
 *  Chromium maps to prefers-reduced-motion. That appliance artifact must
 *  not veto the contractual 3D motion — only document visibility pauses
 *  the loop (no hidden work). */
export function knowledge3dAnimationEnabled(options: {
  visible: boolean;
  reducedMotion: boolean;
}): boolean {
  return options.visible;
}

export function knowledge3dFrameIntervalMs(options: {
  focusActive: boolean;
  interacting: boolean;
  animationProfile?: GraphicsAnimationProfile;
}): number {
  if (options.animationProfile === "maximum") return 0;
  if (options.focusActive) return 1000 / KNOWLEDGE_3D_SWEEP_FPS;
  return options.interacting
    ? 1000 / KNOWLEDGE_3D_ACTIVE_FPS
    : 1000 / KNOWLEDGE_3D_IDLE_FPS;
}

/** Advance a capped-frame deadline without discarding residual time. `null`
 *  means the frame is not due. Maximum/native-refresh mode uses interval 0 and
 *  therefore accepts every requestAnimationFrame callback. */
export function advanceKnowledge3dFrameDeadline(
  previousDeadline: number,
  now: number,
  intervalMs: number,
): number | null {
  if (intervalMs <= 0 || !Number.isFinite(previousDeadline)) return now;
  const elapsed = now - previousDeadline;
  if (elapsed + KNOWLEDGE_3D_FRAME_EARLY_TOLERANCE_MS < intervalMs) {
    return null;
  }
  const intervals = Math.max(
    1,
    Math.floor(
      (elapsed + KNOWLEDGE_3D_FRAME_EARLY_TOLERANCE_MS) / intervalMs,
    ),
  );
  return previousDeadline + intervals * intervalMs;
}

export function knowledge3dWebglPowerPreference(
  preference: GraphicsAdapterPreference,
): "default" | "low-power" | "high-performance" {
  if (preference === "low-power") return "low-power";
  if (preference === "high-performance") return "high-performance";
  return "default";
}

export function clampKnowledge3dPolar(polar: number): number {
  return Math.min(
    KNOWLEDGE_3D_MAX_POLAR,
    Math.max(KNOWLEDGE_3D_MIN_POLAR, polar),
  );
}

export function clampKnowledge3dDolly(
  distance: number,
  framedDistance: number,
): number {
  return Math.min(
    framedDistance * KNOWLEDGE_3D_MAX_DOLLY,
    Math.max(framedDistance * KNOWLEDGE_3D_MIN_DOLLY, distance),
  );
}

export function isKnowledge3dDrag(
  downX: number,
  downY: number,
  x: number,
  y: number,
): boolean {
  return (
    Math.hypot(x - downX, y - downY) >= KNOWLEDGE_3D_DRAG_THRESHOLD_PX
  );
}

/** Map a normalized 2D layout point into world coordinates (used to align
 *  the ball's center — Brain — with the reactor's hub anchor on screen). */
export function knowledge3dWorldPoint(
  x: number,
  y: number,
  viewportAspect: number,
): { x: number; y: number } {
  return {
    x: (x - 0.5) * KNOWLEDGE_3D_WORLD_SPAN * viewportAspect,
    y: (0.5 - y) * KNOWLEDGE_3D_WORLD_SPAN,
  };
}

export interface Knowledge3dBallNode {
  id: string;
  /** Normalized 2D radial layout position (0..1, y down) — supplies the
   *  depth-1 azimuth seed so the peers keep their sectors. */
  x: number;
  y: number;
  depth?: number;
  role?: KnowledgeHierarchyRole | string;
  parentId?: string | null;
  /** World-unit disc radius — the collision shell ("avoidance radius"). */
  radius: number;
}

/** Satellite orbit clamps (owner directive 2026-08-03: each has_knowledge
 *  subagent's vault renders as a SMALLER ball orbiting the main one). The
 *  main ball's outer shell sits at ≈51 world units at defaults inside the
 *  190-unit framed span, so radii of 60-110 keep every satellite clear of
 *  the main silhouette yet inside the framed frustum at the default
 *  dolly. */
// Widened 2026-08-03 (owner: a real distance-from-main control): the low
// end tucks a satellite against the main ball's rim, the high end parks it
// well outside — reachable via wheel-dolly even past the framed distance.
export const KNOWLEDGE_3D_ORBIT_RADIUS_MIN = 50;
export const KNOWLEDGE_3D_ORBIT_RADIUS_MAX = 160;
export const KNOWLEDGE_3D_ORBIT_RADIUS_DEFAULT = 78;
export const KNOWLEDGE_3D_ORBIT_SPEED_DEFAULT = 0.02;
export const KNOWLEDGE_3D_BALL_SCALE_DEFAULT = 0.45;
/** Default satellite self-spin (rad/s about the cloud's local Y axis) —
 *  deliberately faster than the camera's idle yaw so a satellite visibly
 *  turns at its own rate instead of appearing welded to the main ball's
 *  camera-driven rotation (owner 2026-08-03: "the satellites should rotate
 *  independently of the middle animation"). */
export const KNOWLEDGE_3D_SPIN_SPEED_DEFAULT = 0.07;
/** Default orbit-plane inclination (degrees; ~the old hashed average). */
export const KNOWLEDGE_3D_ORBIT_TILT_DEFAULT_DEG = 25;
/** The Tune 3D panel group holding the satellite-only knobs — hidden when
 *  the main agent is selected (orbit fields are inert on the main ball). */
export const KNOWLEDGE_3D_ORBIT_TUNING_GROUP = "Orbit";

/** Operator-tunable 3D graph settings (owner-directed 2026-07-31): every
 *  physics and visual knob below is adjustable live from the ambient
 *  "Tune 3D" slider panel and persisted as a presentation preference.
 *  Physics keys rebuild the simulation in place (positions preserved,
 *  alpha reheated); visual keys drive material uniforms directly. */
export interface Knowledge3dTuning {
  /** 2D thinking sweep: seconds to reach the FIRST article (minimum). */
  sweepSeconds: number;
  /** 2D deadline for the WHOLE route (articles + relation tails). */
  sweepMaxSeconds: number;
  /** 3D: constant animation-progress speed in plan units/second — no
   *  minimum duration or deadline (owner 2026-08-02: timers re-paced the
   *  fronts and made the animation visibly wait). */
  sweepSpeed: number;
  /** Match this graph sweep to the measured activation-context duration. */
  automaticSweepSpeed: number;
  /** 2D layout ring scales: Brain→branch, branch spacing, article ring. */
  ring2dPeers: number;
  ring2dBranches: number;
  ring2dArticles: number;
  /** Depth-1 shell distance (world units). */
  shellBase: number;
  /** Per-depth shell increment (world units). */
  shellStep: number;
  /** Many-body repulsion magnitude. */
  chargeStrength: number;
  /** d3 velocity decay — lower is springier. */
  velocityDecay: number;
  /** Node depth-glow attenuation (1 = the 2D palette alpha). */
  nodeGlow: number;
  /** Beam widths in CSS px (soft glow envelope, not the core line). */
  tendrilWidth: number;
  branchWidth: number;
  /** Width the taxonomy taper lands on at the article-level arm (owner
   *  2026-08-02: with article spokes unpainted at rest, the lit arm can
   *  afford more presence than the old fixed 1 px). */
  articleWidth: number;
  crossWidth: number;
  /** Beam opacities. */
  branchOpacity: number;
  crossOpacity: number;
  /** Cross-link dash cycles per world unit. */
  dashFrequency: number;
  /** Cross-link curvature: midpoint bulge as a fraction of the span. */
  /** Retained for saved tuning compatibility; links now follow their shells. */
  crossCurve: number;
  /** Overall spring rest multiplier: the ACTUAL distance of every
   *  parent-child link (brain-branch, branch-subnode, subnode-child,
   *  child-article) — owner 2026-08-04: shells alone never compressed
   *  the real link lengths. */
  linkDistance: number;
  sizeCore: number;
  sizeBranch: number;
  sizeSubnode: number;
  sizeChild: number;
  sizeArticle: number;
  /** Streak speed multiplier, curve-fraction length, and how many light
   *  streaks travel each article link (geometry — rebuilds in place). */
  streakSpeed: number;
  streakSpan: number;
  streakCount: number;
  /** Idle rotation, radians/second. */
  yawSpeed: number;
  /** Line visibility toggles (0|1): article↔subject spokes, structural
   *  subject↔subject arms, and Brain↔peer spokes as permanent beams. */
  lineArticles: number;
  lineBranches: number;
  linePeers: number;
  /** Word-label offset multiplier — how far label plates sit from their
   *  node (1 = the classic placement). */
  labelDistance: number;
  /** Satellite orbit (per-subagent knowledge balls, owner 2026-08-03):
   *  radius of the tilted circle the agent's ball rides around the main
   *  ball (world units), angular speed (rad/s), and the shell scale that
   *  makes the satellite a genuinely smaller ball. All three are INERT on
   *  the main ball — its Tune 3D panel hides the Orbit group. */
  /** Whole-graph render scale: group transform + matched sprite/beam
   *  pixel scaling, no physics rebuild. Works for main and satellites. */
  graphScale: number;
  /** Per-tier node shader variants (each indexes its options list). */
  subjectStyle: number;
  subnodeStyle: number;
  articleStyle: number;
  ringStyle: number;
  coreStyle: number;
  /** Role-glyph nameplates over every ball (read from the main record). */
  rolePlates: number;
  orbitRadius: number;
  orbitSpeed: number;
  /** Orbit-plane inclination in DEGREES: 0 = equatorial (the main ball's
   *  horizontal plane), 90 = polar (passing over the poles). Each agent's
   *  plane is additionally rotated by a hashed node angle so satellites
   *  sharing a tilt never stack on one ellipse. */
  orbitTilt: number;
  /** Self-rotation of the satellite ball about its own axis, independent
   *  of both the orbit and the camera's idle yaw. */
  spinSpeed: number;
  ballScale: number;
  /** Visible orbital ring toggle + its beam width/opacity. */
  orbitLine: number;
  orbitLineWidth: number;
  orbitLineOpacity: number;
}

export const DEFAULT_KNOWLEDGE_3D_TUNING: Knowledge3dTuning = {
  sweepSeconds: 1.6,
  sweepMaxSeconds: 5,
  sweepSpeed: 0.7,
  automaticSweepSpeed: 1,
  ring2dPeers: 1,
  ring2dBranches: 1,
  ring2dArticles: 1,
  shellBase: 22,
  shellStep: 9,
  // Owner 2026-08-04: no slider — pinned to the old range midpoints.
  // ballScale is slider-less too (second round: it read identically to
  // Graph scale and confused the tuner — Graph scale is THE size control;
  // satellites keep the standard smaller physics underneath).
  chargeStrength: 30,
  velocityDecay: 0.35,
  nodeGlow: 0.6,
  tendrilWidth: 12,
  branchWidth: 8,
  articleWidth: 2,
  crossWidth: 6,
  branchOpacity: 0.75,
  crossOpacity: 0.75,
  dashFrequency: 0.28,
  crossCurve: 0.22,
  linkDistance: 1,
  sizeCore: 1,
  sizeBranch: 1,
  sizeSubnode: 1,
  sizeChild: 1,
  sizeArticle: 1,
  streakSpeed: 1,
  streakSpan: 0.06,
  streakCount: 2,
  yawSpeed: 0.05,
  labelDistance: 1,
  lineArticles: 0,
  lineBranches: 1,
  linePeers: 0,
  graphScale: 1,
  subjectStyle: 0,
  subnodeStyle: 0,
  articleStyle: 0,
  ringStyle: 0,
  coreStyle: 0,
  rolePlates: 1,
  orbitRadius: KNOWLEDGE_3D_ORBIT_RADIUS_DEFAULT,
  orbitSpeed: KNOWLEDGE_3D_ORBIT_SPEED_DEFAULT,
  orbitTilt: KNOWLEDGE_3D_ORBIT_TILT_DEFAULT_DEG,
  spinSpeed: KNOWLEDGE_3D_SPIN_SPEED_DEFAULT,
  ballScale: KNOWLEDGE_3D_BALL_SCALE_DEFAULT,
  orbitLine: 0,
  orbitLineWidth: 2.5,
  orbitLineOpacity: 0.35,
};

export interface Knowledge3dTuningField {
  key: keyof Knowledge3dTuning;
  label: string;
  group: string;
  min: number;
  max: number;
  step: number;
  /** Discrete choice fields (owner 2026-08-03, WeakAuras-style pickers):
   *  the numeric value indexes `options`; the panel renders a dropdown
   *  instead of a slider. Clamping runs the same min/max table. */
  options?: readonly string[];
  /** On/off fields (owner 2026-08-03): 0/1 semantics rendered as a
   *  checkbox instead of a slider; the consumers keep their >=0.5 law. */
  toggle?: true;
  /** Plain-language hover tooltip: what the knob actually does. */
  description?: string;
  /** Hidden for the main (non-orbiting) graph in the tuning pane. */
  satelliteOnly?: true;
}

/** Slider metadata for the front-end panel; clamping uses the same table
 *  so a stale persisted value can never leave the sanctioned range. */
export const KNOWLEDGE_3D_TUNING_FIELDS: readonly Knowledge3dTuningField[] = [
  // Whole-graph render scale (owner 2026-08-03): a pure visual transform on
  // the cloud's group — nodes, beams, and spacing scale together with NO
  // physics rebuild, so the main ball or any satellite resizes live.
  { key: "graphScale", label: "Graph scale", group: "Layout", min: 0.4, max: 2, step: 0.05, description: "Visual zoom for this whole graph: nodes, spacing, and beams scale together with no physics rebuild." },
  { key: "linkDistance", label: "Link distance", group: "Layout", min: 0.4, max: 2, step: 0.05, description: "Length of every parent-child link: brain to branch, branch to sub-branch, down to the article spokes. The real spacing control - rebuilds in place." },
  { key: "yawSpeed", label: "Rotation speed", group: "Motion", min: 0, max: 0.2, step: 0.005, description: "Idle camera rotation around the graph. Pauses while dragging or focused on a satellite." },
  { key: "automaticSweepSpeed", label: "Automatic speed", group: "Thinking", min: 0, max: 1, step: 1, toggle: true, description: "Match this agent's thinking sweep to the measured fast-context retrieval duration. Turn this off to use Animation speed." },
  { key: "sweepSpeed", label: "Animation speed", group: "Thinking", min: 0.1, max: 3, step: 0.05, description: "Manual speed of the thinking animation. Used when Automatic speed is off or no live retrieval measurement exists." },
  { key: "tendrilWidth", label: "Tendril width", group: "Thinking", min: 1, max: 24, step: 0.5, description: "Width of the lit beam from the core out to a top-level branch while thinking." },
  { key: "branchWidth", label: "Branch width", group: "Beams", min: 1, max: 20, step: 0.5, description: "Width of the widest structural beams; deeper arms thin down to the article line width." },
  { key: "articleWidth", label: "Article line width", group: "Beams", min: 1, max: 4, step: 0.25, description: "Width the depth taper lands on at the article-level arms." },
  { key: "branchOpacity", label: "Branch opacity", group: "Beams", min: 0, max: 1, step: 0.05, description: "Opacity of the resting structural tubes." },
  { key: "nodeGlow", label: "Node glow", group: "Nodes", min: 0, max: 1.5, step: 0.05, description: "Strength of the soft depth glow behind subject nodes." },
  // Per-tier node sizes (owner 2026-08-04): real size multipliers — they
  // feed the sprite radius AND the physics radius (collision/spring
  // floors), so a change rebuilds the simulation in place.
  { key: "sizeCore", label: "Brain size", group: "Nodes", min: 0.4, max: 2.2, step: 0.05, description: "Size of the central core node." },
  { key: "sizeBranch", label: "Branch size", group: "Nodes", min: 0.4, max: 2.2, step: 0.05, description: "Size of the top-level branch nodes." },
  { key: "sizeSubnode", label: "Sub-branch size", group: "Nodes", min: 0.4, max: 2.2, step: 0.05, description: "Size of second-level subject nodes." },
  { key: "sizeChild", label: "Child size", group: "Nodes", min: 0.4, max: 2.2, step: 0.05, description: "Size of deeper child subject nodes." },
  { key: "sizeArticle", label: "Article size", group: "Nodes", min: 0.4, max: 2.2, step: 0.05, description: "Size of the article orbs." },
  // Style pickers (owner 2026-08-03, folded under Nodes): shader variants
  // per node TIER — top-level branch subjects, deeper sub-branch subjects,
  // article orbs, the subject rings, and the central AI plasma core.
  { key: "subjectStyle", label: "Branch nodes", group: "Nodes", min: 0, max: 5, step: 1, options: ["Classic disc", "Plasma orb", "Gem", "Hollow", "Rounded square", "Data tile"], description: "Shape and surface style for top-level branch subjects; square choices are offered for the Library graph." },
  { key: "subnodeStyle", label: "Sub-branch nodes", group: "Nodes", min: 0, max: 5, step: 1, options: ["Classic disc", "Plasma orb", "Gem", "Hollow", "Rounded square", "Data tile"], description: "Shape and surface style for deeper subject nodes; square choices are offered for the Library graph." },
  { key: "articleStyle", label: "Article nodes", group: "Nodes", min: 0, max: 5, step: 1, options: ["Jewel star", "Plasma orb", "Classic disc", "Ember", "Jewel square", "Data pixel"], description: "Shape and surface style for article nodes; square choices are offered for the Library graph." },
  { key: "ringStyle", label: "Node rings", group: "Nodes", min: 0, max: 3, step: 1, options: ["Solid", "Dashed", "Double", "None"], description: "Ring stroke style around subject nodes. Auto-curated rings always stay visible." },
  { key: "coreStyle", label: "AI core", group: "Nodes", min: 0, max: 4, step: 1, options: ["Plasma filaments", "Calm core", "Vortex", "Pulsar", "Data block"], description: "Style of the central core: plasma variants for agents, the geometric Data block for the shared library." },
  // WoW-nameplate-style role glyphs (owner 2026-08-03): read from the MAIN
  // record only; one toggle governs every ball's plate.
  { key: "rolePlates", label: "Role nameplates", group: "Nodes", min: 0, max: 1, step: 1, toggle: true, description: "Float each agent's neon role glyph over its ball, always facing you - see who does what at a glance." },
  { key: "crossWidth", label: "Link width", group: "Beams", min: 1, max: 16, step: 0.5, description: "Width of the curved article-to-article link beams." },
  { key: "crossOpacity", label: "Link opacity", group: "Beams", min: 0, max: 1, step: 0.05, description: "Opacity of the curved article links at rest." },
  { key: "dashFrequency", label: "Dash frequency", group: "Beams", min: 0.05, max: 0.8, step: 0.01, description: "Density of the checkered dashes along article links." },
  { key: "streakSpeed", label: "Light speed", group: "Beams", min: 0.1, max: 4, step: 0.1, description: "Travel speed of the light streaks riding the article links." },
  { key: "streakSpan", label: "Light length", group: "Beams", min: 0.01, max: 0.2, step: 0.005, description: "Length of each traveling light streak." },
  { key: "streakCount", label: "Light count", group: "Beams", min: 0, max: 8, step: 1, description: "Light streaks per article link. Zero disables them (rebuilds the geometry)." },
  { key: "labelDistance", label: "Label distance", group: "Labels", min: 0.6, max: 2.5, step: 0.05, description: "How far hover labels sit from their nodes." },
  { key: "lineArticles", label: "Article", group: "Beams", min: 0, max: 1, step: 1, toggle: true, description: "Keep article spokes visible at rest. They always light while thinking rides them." },
  { key: "lineBranches", label: "Branch", group: "Beams", min: 0, max: 1, step: 1, toggle: true, description: "Keep the deeper structural tubes visible at rest." },
  { key: "linePeers", label: "Brain", group: "Beams", min: 0, max: 1, step: 1, toggle: true, description: "Keep the core-to-branch spokes visible at rest. Normally only the thinking path lights them." },
  // Satellite-only Orbit group (hidden for the main agent in the panel;
  // clamped for every record by the same table).
  { key: "orbitRadius", label: "Orbit distance", group: "Motion", satelliteOnly: true, min: KNOWLEDGE_3D_ORBIT_RADIUS_MIN, max: KNOWLEDGE_3D_ORBIT_RADIUS_MAX, step: 1, description: "How far this satellite orbits from the main graph." },
  // Signed speeds: the sign IS the direction (owner 2026-08-03).
  { key: "orbitSpeed", label: "Orbit speed", group: "Motion", satelliteOnly: true, min: -0.2, max: 0.2, step: 0.005, description: "Orbit rate around the main graph. Negative reverses direction." },
  { key: "orbitTilt", label: "Orbit tilt", group: "Motion", satelliteOnly: true, min: 0, max: 90, step: 1, description: "Orbit plane inclination: 0 is equatorial, 90 passes over the poles." },
  { key: "spinSpeed", label: "Self spin", group: "Motion", satelliteOnly: true, min: -0.3, max: 0.3, step: 0.005, description: "How fast the ball rotates on its own axis. Negative reverses direction." },
  // Visible orbital ring (owner 2026-08-03): the satellite's actual path,
  // drawn with the article links' dashed beam styling.
  { key: "orbitLine", label: "Orbit ring", group: "Beams", satelliteOnly: true, min: 0, max: 1, step: 1, toggle: true, description: "Show this satellite's orbital path as a dashed ring, styled like the article links." },
  { key: "orbitLineWidth", label: "Ring width", group: "Beams", satelliteOnly: true, min: 1, max: 8, step: 0.25, description: "Width of the orbital ring beam." },
  { key: "orbitLineOpacity", label: "Ring opacity", group: "Beams", satelliteOnly: true, min: 0, max: 1, step: 0.05, description: "Opacity of the orbital ring's dashes." },
];

/** Clamp an untrusted (persisted) value into a complete valid tuning. */
export function clampKnowledge3dTuning(value: unknown): Knowledge3dTuning {
  const source = (
    typeof value === "object" && value !== null ? value : {}
  ) as Record<string, unknown>;
  const tuning = { ...DEFAULT_KNOWLEDGE_3D_TUNING };
  for (const field of KNOWLEDGE_3D_TUNING_FIELDS) {
    const raw = source[field.key];
    if (typeof raw === "number" && Number.isFinite(raw)) {
      tuning[field.key] = Math.min(field.max, Math.max(field.min, raw));
    }
  }
  return tuning;
}

/** Depth shells: the simulation's radial force targets (weak — the springs
 *  and collisions shape the ball; this only keeps hierarchy depth reading
 *  outward from the middle and the silhouette frame-sized). */
/** Per-tier node size multiplier (owner 2026-08-04): feeds BOTH the
 *  sprite radius and the physics radius, so sized nodes keep honest
 *  collision/spring floors. */
export function knowledge3dNodeSizeMultiplier(
  tuning: Knowledge3dTuning,
  node: { role?: string; depth?: number; subject?: boolean },
): number {
  const depth = node.depth ?? 3;
  if (node.role === "root" || depth === 0) return tuning.sizeCore;
  if (node.subject) {
    if (depth <= 1) return tuning.sizeBranch;
    if (depth === 2) return tuning.sizeSubnode;
    return tuning.sizeChild;
  }
  return tuning.sizeArticle;
}

/** Minimum hierarchy-layer spacing and taxonomy spring rest length.
 *  A crowded layer expands as a whole; individual branches cannot trade
 *  semantic depth for extra radial space. */
export const KNOWLEDGE_3D_LINK_BASE_PX = 14;

export function knowledge3dLinkRest(
  tuning: Knowledge3dTuning = DEFAULT_KNOWLEDGE_3D_TUNING,
): number {
  return KNOWLEDGE_3D_LINK_BASE_PX * tuning.linkDistance;
}

export function knowledge3dMaxShell(
  tuning: Knowledge3dTuning = DEFAULT_KNOWLEDGE_3D_TUNING,
): number {
  return knowledge3dLinkRest(tuning) * 4.2;
}
/** Each node's personal space (the collision radius) — larger than its
 *  disc so the tight ball still breathes. */
export function knowledge3dAvoidanceRadius(node: {
  radius: number;
}): number {
  return node.radius * 1.4 + 2.75;
}
/** Nodes seed OUTSIDE their neighborhoods so the cooling simulation reads
 *  as gravity pulling the ball together. */
export const KNOWLEDGE_3D_FALL_SEED_FACTOR = 1.5;

/** Live-simulation tuning (d3-force-3d — the 3d-force-graph engine).
 *  velocityDecay is the springiness knob: lower = bouncier. alphaDecay
 *  sets how long the settle visibly wobbles (~4-5 s at 30 fps); the scene
 *  stops ticking below alphaMin and a refreshed snapshot reheats to
 *  KNOWLEDGE_3D_REHEAT_ALPHA instead of replaying the full drop. */
export const KNOWLEDGE_3D_ALPHA_MIN = 0.006;
export const KNOWLEDGE_3D_ALPHA_DECAY = 0.02;
export const KNOWLEDGE_3D_VELOCITY_DECAY =
  DEFAULT_KNOWLEDGE_3D_TUNING.velocityDecay;
export const KNOWLEDGE_3D_REHEAT_ALPHA = 0.4;
const TAXONOMY_LINK_STRENGTH = 0.7;
const CROSS_LINK_STRENGTH = 0.03;
const COLLIDE_ITERATIONS = 2;

export interface KnowledgeForceNode extends ForceSimulationNode {
  id: string;
  depth?: number;
  role?: KnowledgeHierarchyRole | string;
  /** Exact placement parent; defines private 3D depth and the outward cap. */
  parentId?: string | null;
  /** World-unit disc radius (avoidance derives from it). */
  radius: number;
}

export interface KnowledgeForceLink {
  source: string;
  target: string;
  taxonomy: boolean;
}

/** Taxonomy springs rest a shell step apart (longer for the depth-1
 *  peers), never shorter than the two avoidance shells in contact. */
export function knowledge3dLinkDistance(
  childDepth: number | undefined,
  sourceRadius: number,
  targetRadius: number,
  tuning: Knowledge3dTuning = DEFAULT_KNOWLEDGE_3D_TUNING,
): number {
  void childDepth;
  const base = knowledge3dLinkRest(tuning);
  return Math.max(
    base,
    // Contact floor scales with the multiplier too (down to bare touch)
    // so compressing actually compresses instead of parking on the old
    // personal-space sum (owner 2026-08-04).
    (knowledge3dAvoidanceRadius({ radius: sourceRadius }) +
      knowledge3dAvoidanceRadius({ radius: targetRadius })) *
      Math.min(1, tuning.linkDistance),
  );
}

/** One radius per semantic depth, anchored near the original settled
 *  Brain-to-branch distance (about 1.4 taxonomy spring lengths). Cube-root
 *  increments beyond that first layer retain a rounder whole cloud without
 *  allowing deeper descendants to expand the empty space around Brain.
 *  Visible-node clearance and surface packing may expand whole layers.
 *  Half the surface remains free for angular settling and uneven branches.
 *  Only membership, depth, glyph size and spacing affect these radii. */
export function knowledge3dDepthRadii(
  nodes: readonly KnowledgeForceNode[],
  tuning: Knowledge3dTuning = DEFAULT_KNOWLEDGE_3D_TUNING,
): ReadonlyMap<number, number> {
  const layers = new Map<number, { largest: number; area: number }>();
  for (const node of nodes) {
    const depth = isBallRoot(node) ? 0 : (node.depth ?? 3);
    const size = knowledge3dAvoidanceRadius(node);
    const layer = layers.get(depth) ?? { largest: 0, area: 0 };
    layer.largest = Math.max(layer.largest, size);
    layer.area += size * size;
    layers.set(depth, layer);
  }
  const radii = new Map<number, number>([[0, 0]]);
  const byId = new Map(nodes.map(node => [node.id, node]));
  const fans = new Map<number, Map<string, number>>();
  for (const node of nodes) {
    const parent = node.parentId ? byId.get(node.parentId) : undefined;
    if (!parent || isBallRoot(parent)) continue;
    const depth = node.depth ?? 3;
    if ((parent.depth ?? 3) + 1 !== depth) continue;
    const groups = fans.get(depth) ?? new Map<string, number>();
    groups.set(parent.id, (groups.get(parent.id) ?? 0) + knowledge3dAvoidanceRadius(node) ** 2);
    fans.set(depth, groups);
  }
  const step = knowledge3dLinkRest(tuning);
  const firstRadius = Math.max(
    step * 1.4,
    (layers.get(0)?.largest ?? 0) + (layers.get(1)?.largest ?? 0),
    Math.sqrt((layers.get(1)?.area ?? 0) / 2),
  );
  let previousRadius = 0;
  let previousSize = layers.get(0)?.largest ?? 0;
  for (const depth of [...layers.keys()].filter(depth => depth > 0).sort((a, b) => a - b)) {
    const layer = layers.get(depth)!;
    const radius = Math.max(
      firstRadius + step * Math.cbrt(depth - 1),
      previousRadius + previousSize + layer.largest,
      Math.sqrt(layer.area / 2),
      // The outward cap has area 2*pi*(R^2 - parentR*R).
      // Reserve half of it for the direct fan's avoidance footprints.
      ...[...(fans.get(depth) ?? [])].map(([id, area]) => {
        const parentRadius = radii.get(byId.get(id)!.depth ?? 3) ?? 0;
        return (parentRadius + Math.sqrt(parentRadius ** 2 + 4 * area)) / 2;
      }),
    );
    radii.set(depth, radius);
    previousRadius = radius;
    previousSize = layer.largest;
  }
  return radii;
}

const sphericalConstraints = new WeakMap<ForceSimulation<KnowledgeForceNode>, SphericalConstraint>();

/** One canonical physical signature for refresh and solver continuity. */
export function knowledge3dPhysicsSignature(
  nodes: readonly KnowledgeForceNode[], links: readonly KnowledgeForceLink[],
  tuning: Knowledge3dTuning,
): string {
  return JSON.stringify([
    tuning.chargeStrength, tuning.velocityDecay, tuning.linkDistance,
    [...nodes].sort((a, b) => a.id.localeCompare(b.id)).map(node => [
      node.id, node.depth, node.role, node.parentId, node.radius,
    ]),
    [...links].sort((a, b) => a.source.localeCompare(b.source)
      || a.target.localeCompare(b.target) || Number(a.taxonomy) - Number(b.taxonomy))
      .map(link => [link.source, link.target, link.taxonomy]),
  ]);
}

export function captureKnowledge3dLayout(
  simulation: ForceSimulation<KnowledgeForceNode>,
): SphericalState | undefined {
  return sphericalConstraints.get(simulation)?.capture();
}

/** Alpha is a cooling schedule, not evidence that the geometry is valid. */
export function knowledge3dSimulationNeedsTick(
  simulation: ForceSimulation<KnowledgeForceNode>,
): boolean {
  return simulation.alpha() > KNOWLEDGE_3D_ALPHA_MIN
    || (sphericalConstraints.get(simulation)?.needsTick() ?? false);
}

/** Build the live simulation: springs, charge, collision, radial hierarchy
 *  and moving branch territories. Brain is pinned at the origin; the scene
 *  owns the tick cadence. d3-force uses a deterministic internal LCG, so identical
 *  inputs replay identically. */
export function createKnowledgeForceSimulation(
  nodes: KnowledgeForceNode[],
  links: readonly KnowledgeForceLink[],
  tuning: Knowledge3dTuning = DEFAULT_KNOWLEDGE_3D_TUNING,
  dimensions: 2 | 3 = 3,
  previousLayout?: SphericalState,
): ForceSimulation<KnowledgeForceNode> {
  if (dimensions === 3) {
    // The 2D projection gives Articles a common terminal paint tier. That
    // value cannot define 3D distance: private physics depth comes from the
    // exact parent chain, including shallow Articles. Preserve the existing
    // fallback for incomplete/cyclic inputs without traversing them forever.
    const byId = new Map(nodes.map(node => [node.id, node]));
    const depths = new Map(nodes.filter(isBallRoot).map(node => [node.id, 0]));
    for (const node of nodes) {
      const path: KnowledgeForceNode[] = [], seen = new Set<string>();
      let ancestor: KnowledgeForceNode | undefined = node;
      while (ancestor && !depths.has(ancestor.id) && !seen.has(ancestor.id)) {
        seen.add(ancestor.id);
        path.push(ancestor);
        ancestor = ancestor.parentId ? byId.get(ancestor.parentId) : undefined;
      }
      if (!ancestor || !depths.has(ancestor.id)) continue;
      let depth = depths.get(ancestor.id)!;
      for (const member of path.reverse()) {
        member.depth = ++depth;
        depths.set(member.id, depth);
      }
    }
  }
  for (const node of nodes) {
    if (isBallRoot(node)) {
      node.x = 0;
      node.y = 0;
      node.fx = 0;
      node.fy = 0;
      if (dimensions === 3) {
        node.z = 0;
        node.fz = 0;
      }
    }
  }
  type ResolvedLink = {
    source: KnowledgeForceNode;
    target: KnowledgeForceNode;
    taxonomy: boolean;
  };
  const simulation = forceSimulation(nodes, dimensions)
    .stop()
    .alphaMin(KNOWLEDGE_3D_ALPHA_MIN)
    .alphaDecay(KNOWLEDGE_3D_ALPHA_DECAY)
    .velocityDecay(tuning.velocityDecay)
    .force(
      "link",
      forceLink(links.map((link) => ({ ...link })))
        .id((node: KnowledgeForceNode) => node.id)
        .distance((link: ResolvedLink) =>
          link.taxonomy
            ? knowledge3dLinkDistance(
                Math.max(link.source.depth ?? 3, link.target.depth ?? 3),
                link.source.radius,
                link.target.radius,
                tuning,
              )
            : knowledge3dLinkRest(tuning) * 2.4,
        )
        .strength((link: ResolvedLink) =>
          link.taxonomy ? TAXONOMY_LINK_STRENGTH : CROSS_LINK_STRENGTH,
        ),
    )
    .force(
      "charge",
      forceManyBody()
        .strength(-tuning.chargeStrength)
        .distanceMax(knowledge3dLinkRest(tuning) * 3),
    )
    .force(
      "collide",
      dimensions === 3 ? null : forceCollide()
        .radius((node: KnowledgeForceNode) =>
          knowledge3dAvoidanceRadius(node),
        )
        .iterations(COLLIDE_ITERATIONS),
    )
    .force(
      "dagRadial",
      dimensions === 3 ? null : forceRadial((node: KnowledgeForceNode) =>
        (node.depth ?? 3) * knowledge3dLinkRest(tuning),
      ).strength((node: KnowledgeForceNode) =>
        isBallRoot(node) ? 0 : 0.9,
      ),
    )
    .force(
      "outwardHemisphere",
      dimensions === 3 ? null : forceKnowledgeLeafHemisphere(nodes, dimensions),
    );
  if (dimensions === 3) {
    const constraint = createSphericalConstraint(nodes, {
      radii: knowledge3dDepthRadii(nodes, tuning),
      avoidance: knowledge3dAvoidanceRadius,
      velocityDecay: tuning.velocityDecay,
      alphaMin: KNOWLEDGE_3D_ALPHA_MIN,
      signature: knowledge3dPhysicsSignature(nodes, links, tuning),
      previous: previousLayout,
    });
    // Last in d3's force order: solve contacts, outwardness and recursive
    // crown boundaries together against the SAME predicted integration.
    simulation.force("depthLayers", constraint);
    sphericalConstraints.set(simulation, constraint);
  }
  return simulation;
}

/** Legacy Cartesian outward boundary retained for the separate 2D layout.
 * Its elastic shallow correction and hard backstop are unchanged. The 3D
 * factory uses the coupled spherical solver instead. */
export function forceKnowledgeLeafHemisphere(
  nodes: readonly KnowledgeForceNode[],
  dimensions: 2 | 3 = 3,
): (alpha: number) => void {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  // Every child with a non-root parent, including subjects.
  const leaves = nodes.filter(
    (node) =>
      !isBallRoot(node) &&
      node.parentId != null &&
      byId.has(node.parentId),
  );
  return () => {
    for (const leaf of leaves) {
      const parent = byId.get(leaf.parentId!);
      if (!parent || isBallRoot(parent)) continue;
      const px = parent.x ?? 0;
      const py = parent.y ?? 0;
      const pz = dimensions === 3 ? (parent.z ?? 0) : 0;
      const parentRadial = Math.hypot(px, py, pz);
      if (parentRadial < 1e-6) continue;
      const ux = px / parentRadial;
      const uy = py / parentRadial;
      const uz = pz / parentRadial;
      const wx = (leaf.x ?? 0) - px;
      const wy = (leaf.y ?? 0) - py;
      const wz = dimensions === 3 ? (leaf.z ?? 0) - pz : 0;
      const inward = wx * ux + wy * uy + wz * uz;
      if (inward >= 0) continue;
      // SPRINGY boundary (owner 2026-08-04: the axis slots are starting
      // areas — children free-fall around their avoidance dome, and the
      // ball should feel elastic, not caged): shallow violations get a
      // proportional restoring push and a damped (never zeroed) inward
      // velocity, so a node arriving fast dips past the equator and
      // bounces back; only a deep violation snaps to the hard backstop.
      const hardLimit = -3;
      const softness = 0.3;
      const pull =
        inward < hardLimit ? inward - hardLimit : inward * softness;
      leaf.x = (leaf.x ?? 0) - ux * pull;
      leaf.y = (leaf.y ?? 0) - uy * pull;
      if (dimensions === 3) leaf.z = (leaf.z ?? 0) - uz * pull;
      const vInward =
        (leaf.vx ?? 0) * ux +
        (leaf.vy ?? 0) * uy +
        (dimensions === 3 ? (leaf.vz ?? 0) * uz : 0);
      if (vInward < 0) {
        const bounce = vInward * 0.5;
        leaf.vx = (leaf.vx ?? 0) - ux * bounce;
        leaf.vy = (leaf.vy ?? 0) - uy * bounce;
        if (dimensions === 3) leaf.vz = (leaf.vz ?? 0) - uz * bounce;
      }
    }
  };
}

function hash01(value: string, salt: number): number {
  let hash = 2166136261 ^ salt;
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return ((hash >>> 0) % 10_000) / 10_000;
}

export function knowledge3dShellRadius(
  depth: number,
  tuning: Knowledge3dTuning = DEFAULT_KNOWLEDGE_3D_TUNING,
): number {
  if (depth <= 0) return 0;
  // Raw level law — dagLevelDistance semantics (vasturiano radialout):
  // no cap, the Link distance slider spaces every level uniformly.
  return knowledge3dLinkRest(tuning) * depth;
}

function isBallSubject(node: {
  role?: string;
}): boolean {
  return node.role === "section";
}

function isBallRoot(node: {
  role?: KnowledgeHierarchyRole | string;
  depth?: number;
}): boolean {
  return node.role === "root" || (node.depth ?? 3) === 0;
}

/** Deterministic spherical targets: depth-1 branches keep their 2D azimuth
 *  (so the six peers keep their sectors when viewed head-on) but tilt out
 *  of the screen plane with a stable per-id sign/magnitude, covering the
 *  full sphere; every descendant radiates outward from Brain within its
 *  parent's cone at its depth shell. Identical inputs give identical
 *  bytes. Run relaxKnowledge3dBall over the result for the avoidance
 *  radius. */
/** Evenly spaced branch directions for N depth-1 peers: pole anchors
 *  (first up, second down — the owner's ordering law) plus a
 *  deterministic Thomson-style repulsion for the rest. Six converge to
 *  the octahedron, seven to the pentagonal bipyramid. */
export function knowledge3dBranchDirections(
  count: number,
): ReadonlyArray<readonly [number, number, number]> {
  if (count <= 0) return [];
  if (count === 1) return [[0, 1, 0]];
  const points: Array<[number, number, number]> = [
    [0, 1, 0],
    [0, -1, 0],
  ];
  // Deterministic golden-spiral init for the free points, biased to the
  // equatorial band so the relaxation starts spread out.
  for (let index = 2; index < count; index += 1) {
    const free = count - 2;
    const y = ((index - 2 + 0.5) / free - 0.5) * 0.8;
    const radial = Math.sqrt(Math.max(0.05, 1 - y * y));
    const angle = (index - 2) * 2.399963229728653;
    points.push([
      Math.cos(angle) * radial,
      y,
      Math.sin(angle) * radial,
    ]);
  }
  // Pairwise repulsion on the sphere, poles pinned. 160 rounds is far
  // past convergence for the ≤ 20 peers a real vault carries.
  for (let round = 0; round < 160; round += 1) {
    const step = 0.12;
    for (let a = 2; a < points.length; a += 1) {
      let fx = 0;
      let fy = 0;
      let fz = 0;
      for (let b = 0; b < points.length; b += 1) {
        if (a === b) continue;
        const dx = points[a][0] - points[b][0];
        const dy = points[a][1] - points[b][1];
        const dz = points[a][2] - points[b][2];
        const distanceSq = Math.max(1e-4, dx * dx + dy * dy + dz * dz);
        const inverse = 1 / (distanceSq * Math.sqrt(distanceSq));
        fx += dx * inverse;
        fy += dy * inverse;
        fz += dz * inverse;
      }
      let nx = points[a][0] + fx * step;
      let ny = points[a][1] + fy * step;
      let nz = points[a][2] + fz * step;
      const length = Math.hypot(nx, ny, nz) || 1;
      points[a] = [nx / length, ny / length, nz / length];
    }
  }
  return points;
}

export function knowledge3dBallTargets(
  nodes: readonly Knowledge3dBallNode[],
  hub: { x: number; y: number },
  tuning: Knowledge3dTuning = DEFAULT_KNOWLEDGE_3D_TUNING,
): Float32Array {
  const targets = new Float32Array(nodes.length * 3);
  const directions = new Float32Array(nodes.length * 3);
  const indexById = new Map(nodes.map((node, index) => [node.id, index]));
  const physicalNodes: KnowledgeForceNode[] = nodes.map(node => ({ ...node }));
  const physicalById = new Map(physicalNodes.map(node => [node.id, node]));
  for (const node of physicalNodes) {
    if (isBallRoot(node)) { node.depth = 0; continue; }
    let at: KnowledgeForceNode | undefined = node;
    let depth = 0;
    const seen = new Set<string>();
    while (at && !isBallRoot(at) && !seen.has(at.id)) {
      seen.add(at.id); depth++;
      at = at.parentId ? physicalById.get(at.parentId) : undefined;
    }
    if (at && isBallRoot(at)) node.depth = depth;
  }
  const seedRadii = knowledge3dDepthRadii(physicalNodes, tuning);
  // Depth-1 branch law (owner 2026-08-04, second round: a fixed axis
  // table stranded the seventh peer on a lone diagonal beside four
  // coplanar axes): the first branch anchors straight UP, the second
  // straight DOWN, and every remaining peer relaxes to an EVENLY spaced
  // direction via a deterministic Thomson-style repulsion with the two
  // poles held fixed — six peers converge to the octahedron, seven to
  // the pentagonal bipyramid, any N stays balanced. Encounter-ordered,
  // no randomness: identical vaults seed identical skeletons.
  const peerSlot = new Map<string, number>();
  for (const node of nodes) {
    if (isBallRoot(node)) continue;
    const parentIndex =
      node.parentId != null ? indexById.get(node.parentId) : undefined;
    if (parentIndex === undefined || isBallRoot(nodes[parentIndex])) {
      peerSlot.set(node.id, peerSlot.size);
    }
  }
  const peerDirections = knowledge3dBranchDirections(peerSlot.size);
  // Leaf siblings fan deterministically across the parent's outward cap
  // on their common Brain-centered shell, with equal-area angular slots.
  const leafSlot = new Map<string, { index: number; count: number }>();
  {
    const leavesByParent = new Map<string, string[]>();
    for (const node of nodes) {
      if (isBallSubject(node) || isBallRoot(node)) continue;
      if (node.parentId == null) continue;
      const siblings = leavesByParent.get(node.parentId) ?? [];
      siblings.push(node.id);
      leavesByParent.set(node.parentId, siblings);
    }
    for (const siblings of leavesByParent.values()) {
      siblings.sort();
      siblings.forEach((id, index) =>
        leafSlot.set(id, { index, count: siblings.length }),
      );
    }
  }
  // Parents always sit at a shallower depth, so processing in depth order
  // guarantees a child sees its parent's direction.
  const order = nodes
    .map((_, index) => index)
    .sort((a, b) => (physicalNodes[a].depth ?? 99) - (physicalNodes[b].depth ?? 99));
  for (const index of order) {
    const node = nodes[index];
    if (isBallRoot(node)) continue; // Brain pinned at the ball's center.
    const parentIndex =
      node.parentId != null ? indexById.get(node.parentId) : undefined;
    const parentIsHub =
      parentIndex === undefined || isBallRoot(nodes[parentIndex]);
    let dx: number;
    let dy: number;
    let dz: number;
    if (parentIsHub) {
      const slot = peerSlot.get(node.id) ?? 0;
      const direction = peerDirections[Math.min(slot, peerDirections.length - 1)];
      dx = direction[0];
      dy = direction[1];
      dz = direction[2];
    } else {
      const px = directions[parentIndex * 3];
      const py = directions[parentIndex * 3 + 1];
      const pz = directions[parentIndex * 3 + 2];
      // Orthonormal basis perpendicular to the parent direction.
      const reference = Math.abs(py) < 0.9 ? [0, 1, 0] : [1, 0, 0];
      let ux = py * reference[2] - pz * reference[1];
      let uy = pz * reference[0] - px * reference[2];
      let uz = px * reference[1] - py * reference[0];
      const uLength = Math.hypot(ux, uy, uz) || 1;
      ux /= uLength;
      uy /= uLength;
      uz /= uLength;
      const vx = py * uz - pz * uy;
      const vy = pz * ux - px * uz;
      const vz = px * uy - py * ux;
      const slot = leafSlot.get(node.id);
      if (slot && parentIndex !== undefined) {
        const radius = seedRadii.get(physicalNodes[index].depth ?? 3)!;
        const parentRadius = seedRadii.get(physicalNodes[parentIndex].depth ?? 3)!;
        const minimumCosine = Math.min(1, parentRadius / radius);
        const cosine = minimumCosine + (1 - minimumCosine) * (slot.index + 0.5) / slot.count;
        const gamma = hash01(node.parentId ?? node.id, 41) * Math.PI * 2
          + slot.index * 2.399963229728653;
        const sine = Math.sqrt(Math.max(0, 1 - cosine * cosine));
        dx = px * cosine + (ux * Math.cos(gamma) + vx * Math.sin(gamma)) * sine;
        dy = py * cosine + (uy * Math.cos(gamma) + vy * Math.sin(gamma)) * sine;
        dz = pz * cosine + (uz * Math.cos(gamma) + vz * Math.sin(gamma)) * sine;
      } else {
        // Cones narrow with depth so subject subtrees stay coherent bundles.
        const depth = node.depth ?? 3;
        const cone = Math.max(0.22, 0.85 - 0.16 * (depth - 1));
        const beta = cone * (0.35 + 0.6 * hash01(node.id, 29));
        const gamma = hash01(node.id, 31) * Math.PI * 2;
        const sinBeta = Math.sin(beta);
        dx = px * Math.cos(beta) + (ux * Math.cos(gamma) + vx * Math.sin(gamma)) * sinBeta;
        dy = py * Math.cos(beta) + (uy * Math.cos(gamma) + vy * Math.sin(gamma)) * sinBeta;
        dz = pz * Math.cos(beta) + (uz * Math.cos(gamma) + vz * Math.sin(gamma)) * sinBeta;
      }
    }
    const length = Math.hypot(dx, dy, dz) || 1;
    directions[index * 3] = dx / length;
    directions[index * 3 + 1] = dy / length;
    directions[index * 3 + 2] = dz / length;
    const shell = seedRadii.get(physicalNodes[index].depth ?? 3)!;
    targets[index * 3] = directions[index * 3] * shell;
    targets[index * 3 + 1] = directions[index * 3 + 1] * shell;
    targets[index * 3 + 2] = directions[index * 3 + 2] * shell;
  }
  return targets;
}

/** Legacy radial seed expansion. The live 3D constructor immediately
 * restores common shell radii before rendering; settling is angular. */
export function seedKnowledge3dPositions(targets: Float32Array): Float32Array {
  const positions = new Float32Array(targets.length);
  for (let index = 0; index < targets.length; index += 1) {
    positions[index] = targets[index] * KNOWLEDGE_3D_FALL_SEED_FACTOR;
  }
  return positions;
}

// ── Satellite knowledge balls (per-subagent vaults, owner 2026-08-03) ──────
// Each has_knowledge subagent's graph is a SMALLER ball orbiting the main
// one: same shaders and styling helpers, own simulation and tuning, and
// path-inert (the thinking sweep stays main-only). Everything here is pure
// math so the orbit contract stays WebGL-free and unit-testable.

/** Render-model node ids for satellite clouds are namespaced at the
 *  render-model boundary so two agents' vaults sharing claim ids can never
 *  collide in projection maps, hover state, or overlay layouts. The agent
 *  grammar forbids "/", so splitting at the FIRST "/" is exact. */
export const KNOWLEDGE_3D_AGENT_NODE_PREFIX = "agent:";

export function knowledgeAgentNodeId(agentId: string, nodeId: string): string {
  return `${KNOWLEDGE_3D_AGENT_NODE_PREFIX}${agentId}/${nodeId}`;
}

/** Split a possibly agent-qualified node id exactly once. Unqualified ids
 *  (the main ball, whose behavior must stay byte-identical) return
 *  `agentId: null` with the id untouched; a malformed "agent:" id with no
 *  separator is treated as an ordinary main-ball id rather than guessed
 *  at. */
export function parseKnowledgeAgentNodeId(id: string): {
  agentId: string | null;
  nodeId: string;
} {
  if (!id.startsWith(KNOWLEDGE_3D_AGENT_NODE_PREFIX)) {
    return { agentId: null, nodeId: id };
  }
  const separator = id.indexOf("/", KNOWLEDGE_3D_AGENT_NODE_PREFIX.length);
  if (separator < 0) return { agentId: null, nodeId: id };
  const agentId = id.slice(KNOWLEDGE_3D_AGENT_NODE_PREFIX.length, separator);
  if (agentId.length === 0) return { agentId: null, nodeId: id };
  return { agentId, nodeId: id.slice(separator + 1) };
}

/** Per-agent Tune 3D persistence key. The main agent keeps the existing v3
 *  key VERBATIM (zero migration); satellite records bumped v1 -> v2 on
 *  2026-08-04 (migration: article arms default VISIBLE — satellites are
 *  path-inert, so dormant tubes are their only resting structure). */
export function knowledge3dTuningKey(agentId?: string): string {
  return agentId === undefined || agentId === "main"
    ? "obsidience.obsidience-knowledge.tuning3d.v3"
    : `obsidience.obsidience-knowledge.tuning3d.${agentId}.v2`;
}

/** The retired satellite v1 key — read once for the v2 migration. */
export function knowledge3dTuningKeyV1(agentId: string): string {
  return `obsidience.obsidience-knowledge.tuning3d.${agentId}.v1`;
}

export function clampKnowledge3dOrbitRadius(radius: number): number {
  if (!Number.isFinite(radius)) return KNOWLEDGE_3D_ORBIT_RADIUS_DEFAULT;
  return Math.min(
    KNOWLEDGE_3D_ORBIT_RADIUS_MAX,
    Math.max(KNOWLEDGE_3D_ORBIT_RADIUS_MIN, radius),
  );
}

/** Deterministic per-agent orbit geometry: the initial phase and the plane
 *  tilt hash from the agent NAME, so a layout replays identically across
 *  sessions — no Math.random, no Date.now. */
export function knowledge3dOrbitPhase(agentId: string): number {
  return hash01(agentId, 43) * Math.PI * 2;
}

/** Hashed rotation of the whole orbit about the Y axis (the longitude of
 *  the ascending node): satellites dialed to the SAME "Orbit tilt" still
 *  ride distinct planes instead of stacking on one ellipse. */
export function knowledge3dOrbitNodeAngle(agentId: string): number {
  return hash01(agentId, 47) * Math.PI * 2;
}

/** Position on the tilted orbit circle around the world origin at the
 *  given scene-clock time. `timeSeconds` must be the UNWRAPPED scene
 *  clock: this runs in JS doubles (no fp32 fract() erosion), and feeding
 *  the shader's hourly-wrapped uTime here would teleport every satellite
 *  once an hour. Pure and deterministic — identical inputs give identical
 *  bytes. */
export function knowledge3dOrbitPosition(
  agentId: string,
  tuning: Pick<Knowledge3dTuning, "orbitRadius" | "orbitSpeed" | "orbitTilt">,
  timeSeconds: number,
): { x: number; y: number; z: number } {
  // Signed: a negative speed orbits the other way (owner 2026-08-03).
  const speed = Number.isFinite(tuning.orbitSpeed) ? tuning.orbitSpeed : 0;
  const theta = knowledge3dOrbitPhase(agentId) + speed * timeSeconds;
  return knowledge3dOrbitPointAt(agentId, tuning, theta);
}

/** Point on the orbit circle at angle theta — the SAME geometry the live
 *  orbit traces, shared with the visible orbit-ring builder so the ring
 *  and the satellite can never drift apart (owner 2026-08-03). */
export function knowledge3dOrbitPointAt(
  agentId: string,
  tuning: Pick<Knowledge3dTuning, "orbitRadius" | "orbitTilt">,
  theta: number,
): { x: number; y: number; z: number } {
  const radius = clampKnowledge3dOrbitRadius(tuning.orbitRadius);
  // Inclination from the per-agent slider (owner 2026-08-03: polar vs
  // equatorial): 0 deg keeps the orbit in the main ball's horizontal
  // plane, 90 deg sends it over the poles.
  const tiltDeg = Number.isFinite(tuning.orbitTilt) ? tuning.orbitTilt : 0;
  const tilt = (Math.min(90, Math.max(0, tiltDeg)) * Math.PI) / 180;
  const baseX = radius * Math.cos(theta);
  const baseY = radius * Math.sin(theta) * Math.sin(tilt);
  const baseZ = radius * Math.sin(theta) * Math.cos(tilt);
  const node = knowledge3dOrbitNodeAngle(agentId);
  const cosNode = Math.cos(node);
  const sinNode = Math.sin(node);
  return {
    x: baseX * cosNode + baseZ * sinNode,
    y: baseY,
    z: -baseX * sinNode + baseZ * cosNode,
  };
}

/** Satellite self-rotation about its local Y axis, independent of both the
 *  orbit and the camera's idle yaw (which is what spins the MAIN ball's
 *  view — without a spin of their own, satellites read as welded to the
 *  middle animation; owner 2026-08-03). Hashed start angle and direction
 *  per agent; same UNWRAPPED-clock rule as the orbit. */
export function knowledge3dSpinAngle(
  agentId: string,
  tuning: Pick<Knowledge3dTuning, "spinSpeed">,
  timeSeconds: number,
): number {
  // Signed: the slider's sign IS the spin direction (owner 2026-08-03) —
  // a hashed direction would silently fight an operator-chosen sign.
  const speed = Number.isFinite(tuning.spinSpeed) ? tuning.spinSpeed : 0;
  return hash01(agentId, 61) * Math.PI * 2 + speed * timeSeconds;
}

/** Distance at which a camera with the given vertical fov frames the whole
 *  world span (plus the drift margin). */
/** Ambient 2D physics is SETTLE-TO-PLACE (owner feedback 2026-08-01: the
 *  map must look exactly as it always did — physics is only HOW nodes
 *  arrive). Every node's target is its deterministic radial-layout
 *  position; an underdamped spring pulls it there while collisions keep
 *  the flight natural, and the caller FREEZES at the cooled
 *  collision-aware equilibrium (velocities zeroed, no snap back to exact
 *  targets — collide and edge clearance win over target identity), so the
 *  settled view reads as the classic map while every node rests mutually
 *  aware. */
export const KNOWLEDGE_2D_SETTLE_STRENGTH = 0.07;
export const KNOWLEDGE_2D_SETTLE_VELOCITY_DECAY = 0.25;

/** Per-node spring strength, hash-staggered so a branch's nodes arrive as
 *  a natural cascade instead of a lockstep column. */
export function knowledgeSettleStrength(id: string): number {
  return 0.055 + hash01(id, 41) * 0.03;
}

/** Random initial condition for ambient 2D. It deliberately knows nothing
 *  about node id, hierarchy sector, target position, or article role: those
 *  old deterministic placement inputs made physics decorate a fixed map
 *  instead of creating the map. An injectable source keeps tests bounded. */
export function knowledge2dPhysicsSeed(
  hub: { x: number; y: number },
  scatterRadius: number,
  random: () => number = Math.random,
): { x: number; y: number } {
  const angle = random() * Math.PI * 2;
  const radius = Math.sqrt(Math.max(0, Math.min(1, random()))) *
    Math.max(1, scatterRadius);
  return {
    x: hub.x + Math.cos(angle) * radius,
    y: hub.y + Math.sin(angle) * radius,
  };
}

export interface KnowledgeSettleNode extends ForceSimulationNode {
  id: string;
  /** Target position (canvas px — the radial layout's point). */
  tx: number;
  ty: number;
  /** Canvas px disc radius (collision jostle during flight). */
  radius: number;
  pinned?: boolean;
  /** Leaf-role nodes (articles) avoid painted taxonomy segments. Subjects
   *  never do: they anchor the wedge geometry the spokes emanate from, and
   *  edge-pushing them wedged whole hubs hundreds of px off the map
   *  (adversarial review 2026-08-01: the News peer froze 201 px from home
   *  between two Websites arms). */
  avoidsEdges?: boolean;
  /** Hierarchy parent — segments belonging to the node's own family (its
   *  parent's fan, and the spoke into its parent) use the small sibling
   *  padding instead of the full foreign margin. */
  parentId?: string;
  /** Plasma-orb articles: hold a minimum distance from the parent and
   *  always rest OUTWARD of it relative to the Brain — the target spring
   *  keeps pulling them toward the middle; the floor stops them (owner
   *  2026-08-01). */
  radiates?: boolean;
  /** Subjects only: reserved article-cluster radius (canvas px). Foreign
   *  orbs stay outside it even when the subject has no articles. */
  orbit?: number;
  /** Frozen bearing about the Brain (radians). Telescoped from the parent
   *  so every chain radiates on its parent's outward ray. */
  bearing?: number;
  /** Hierarchy depth (0 = Brain) — orders the hard radial constraint. */
  depth?: number;
}

/** Every node's frozen bearing telescopes from its parent: a child's
 *  bearing is its parent's plus a CLAMPED cone offset, so deep chains
 *  radiate away from the center along their parent's ray (owner
 *  2026-08-01: the raw sector azimuth sent Input up-left while its
 *  Hardware chain ran down-left). Depth-1 peers keep their exact sector
 *  azimuths. */
export const KNOWLEDGE_2D_BEARING_CONE = 0.6;

export function knowledgeTelescopedBearings(
  nodes: ReadonlyArray<{
    id: string;
    x: number;
    y: number;
    depth?: number;
    parentId?: string | null;
  }>,
  anchor: { x: number; y: number },
  cone: number = KNOWLEDGE_2D_BEARING_CONE,
): Map<string, number> {
  const azimuth = new Map<string, number>();
  for (const node of nodes) {
    azimuth.set(
      node.id,
      Math.atan2(node.y - anchor.y, node.x - anchor.x),
    );
  }
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const bearings = new Map<string, number>();
  const wrap = (value: number): number => {
    let result = value;
    while (result > Math.PI) result -= Math.PI * 2;
    while (result < -Math.PI) result += Math.PI * 2;
    return result;
  };
  const ordered = [...nodes].sort(
    (left, right) => (left.depth ?? 99) - (right.depth ?? 99),
  );
  for (const node of ordered) {
    const parent = node.parentId ? byId.get(node.parentId) : undefined;
    if (!parent || (node.depth ?? 0) <= 1) {
      bearings.set(node.id, azimuth.get(node.id)!);
      continue;
    }
    const parentBearing =
      bearings.get(parent.id) ?? azimuth.get(parent.id)!;
    const offset = wrap(azimuth.get(node.id)! - azimuth.get(parent.id)!);
    bearings.set(
      node.id,
      parentBearing + Math.max(-cone, Math.min(cone, offset)),
    );
  }
  return bearings;
}

/** Foreign orbs stay outside every subject's reserved article orbit —
 *  the ring its own articles rest at (owner 2026-08-01: Tools orbs sat
 *  right against the article-less Coding Context). Pushes only the orb;
 *  subjects never move. Not alpha-scaled, so the reservation holds at
 *  rest. */
export function forceKnowledgeOrbit(
  nodes: readonly KnowledgeSettleNode[],
  strength = 0.5,
): () => void {
  const subjects = nodes.filter(
    (node) => (node.orbit ?? 0) > 0 && !node.radiates,
  );
  const orbs = nodes.filter((node) => node.radiates && !node.pinned);
  return () => {
    for (const subject of subjects) {
      const orbit = subject.orbit!;
      const sx = subject.x ?? 0;
      const sy = subject.y ?? 0;
      for (const orb of orbs) {
        if (orb.parentId === subject.id) continue;
        let dx = (orb.x ?? 0) - sx;
        let dy = (orb.y ?? 0) - sy;
        let distance = Math.hypot(dx, dy);
        if (distance >= orbit) continue;
        if (distance < 1e-3) {
          dx = 1;
          dy = 0;
          distance = 1;
        }
        const push = ((orbit - distance) / distance) * strength;
        orb.vx = (orb.vx ?? 0) + dx * push;
        orb.vy = (orb.vy ?? 0) + dy * push;
        // Slide AROUND the reservation toward the orb's own target side —
        // a pure radial wall stranded orbs whose home lay past a foreign
        // subject (adversarial finding class: walls must funnel, 2026-08-01).
        const targetCross =
          dx * ((orb.ty ?? 0) - sy) - dy * ((orb.tx ?? 0) - sx);
        if (Math.abs(targetCross) > 1e-6) {
          const side = targetCross > 0 ? 1 : -1;
          const tangent = push * 0.6 * side;
          orb.vx += (-dy / distance) * tangent;
          orb.vy += (dx / distance) * tangent;
        }
      }
    }
  };
}

/** Minimum spoke length between a radiating orb and its subject beyond
 *  their touching footprints. */
export const KNOWLEDGE_2D_RADIATE_GAP_PX = 12;
export const KNOWLEDGE_2D_RADIATE_STRENGTH = 0.55;

/** Orb radiation floor: keeps every plasma-orb article at least
 *  (parent.radius + node.radius + gap) from its subject AND farther from
 *  the Brain hub than the subject, while the springs pull it home. Not
 *  alpha-scaled, so the floor holds at rest like forceCollide. */
export function forceKnowledgeRadiate(
  nodes: readonly KnowledgeSettleNode[],
  hub: { x: number; y: number },
  gap: number = KNOWLEDGE_2D_RADIATE_GAP_PX,
  strength: number = KNOWLEDGE_2D_RADIATE_STRENGTH,
): () => void {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const pairs = nodes.flatMap((node) => {
    if (!node.radiates || !node.parentId) return [];
    const parent = byId.get(node.parentId);
    return parent && parent !== node ? [{ node, parent }] : [];
  });
  return () => {
    for (const { node, parent } of pairs) {
      const px = parent.x ?? 0;
      const py = parent.y ?? 0;
      let nx = node.x ?? 0;
      let ny = node.y ?? 0;
      // Floor 1: minimum spoke length off the subject.
      const minDistance = node.radius + parent.radius + gap;
      let dx = nx - px;
      let dy = ny - py;
      let distance = Math.hypot(dx, dy);
      if (distance < 1e-3) {
        // Degenerate: leave along the parent's outward hub ray.
        const hx = px - hub.x;
        const hy = py - hub.y;
        const hubLength = Math.hypot(hx, hy) || 1;
        dx = hx / hubLength;
        dy = hy / hubLength;
        distance = 1;
      }
      if (distance < minDistance) {
        const push = ((minDistance - distance) / distance) * strength;
        node.vx = (node.vx ?? 0) + dx * push;
        node.vy = (node.vy ?? 0) + dy * push;
        nx += dx * push;
        ny += dy * push;
      }
      // Floor 2: radiate — the orb never rests closer to the Brain than
      // its subject.
      const parentHub = Math.hypot(px - hub.x, py - hub.y);
      const nodeHubX = nx - hub.x;
      const nodeHubY = ny - hub.y;
      const nodeHub = Math.hypot(nodeHubX, nodeHubY);
      if (nodeHub < parentHub + 2 && nodeHub > 1e-3) {
        const deficit = parentHub + 2 - nodeHub;
        const push = (deficit / nodeHub) * strength;
        node.vx = (node.vx ?? 0) + nodeHubX * push;
        node.vy = (node.vy ?? 0) + nodeHubY * push;
      }
    }
  };
}

/** A painted taxonomy segment the settle simulation must keep nodes clear
 *  of. `source` is the child endpoint, `target` the parent (the snapshot's
 *  edge orientation). */
export interface KnowledgeSettleEdge {
  source: string;
  target: string;
}

/** Clearance margin between a node's visual footprint and any taxonomy
 *  spoke it does not terminate. Covers the default beam widths with room
 *  to spare; a Branch-width slider pushed past 16 px paints a half-width
 *  beyond this margin and may graze a resting leaf's halo — accepted at
 *  slider extremes rather than widening every wall. */
export const KNOWLEDGE_2D_EDGE_CLEARANCE_PX = 8;
/** Padding against the node's OWN family of spokes (its parent's fan and
 *  the spoke into its parent). A dense fan is intentional geometry — the
 *  Agent Tools fan packs ~20 spokes under 2° apart, and demanding the full
 *  foreign margin there marched every article to the screen edge (owner
 *  2026-08-01: "way off to the side of the screen"). The sibling padding
 *  only keeps the line visibly outside the disc. */
export const KNOWLEDGE_2D_EDGE_SIBLING_CLEARANCE_PX = 3;
export const KNOWLEDGE_2D_EDGE_CLEARANCE_STRENGTH = 0.5;
/** Along-spoke outward drift added to every clearance push. Inside a
 *  dense fan the perpendicular pushes of two neighbouring spokes cancel at
 *  the wedge midline and a trapped leaf would rest there, inside BOTH
 *  clearance zones; the drift slides it outward along the wedge until the
 *  spokes diverge past 2× clearance (adversarial review 2026-08-01). */
export const KNOWLEDGE_2D_EDGE_DRIFT = 0.35;

/** Node↔edge clearance: forceCollide separates node circles, but a node
 *  resting ON another branch's article spoke still reads as attached to it
 *  (owner 2026-08-01: a Temporary Observations article sat on a Tools
 *  article line). Each tick, every leaf node (`avoidsEdges`) within
 *  clearance of a segment it does not terminate is nudged perpendicular
 *  off it. Like forceCollide this is NOT alpha-scaled, so as the target
 *  springs decay the clearance wins and the equilibrium respects it.
 *  A node whose own target lies clear on the FAR side of the segment is
 *  funneled through toward its target instead of walled on the stale side
 *  (adversarial review 2026-08-01: the one-sided wall stranded refreshed
 *  survivors at clearance on the wrong side forever). Two segments closer
 *  than 2× clearance rest the node on their midline — the best-effort
 *  maximum-separation compromise. Deterministic: fixed iteration order,
 *  and the degenerate on-the-line case falls back to the perpendicular on
 *  the side of the node's own layout target. */
export function forceKnowledgeEdgeClearance(
  nodes: readonly KnowledgeSettleNode[],
  edges: readonly KnowledgeSettleEdge[],
  margin: number = KNOWLEDGE_2D_EDGE_CLEARANCE_PX,
  strength: number = KNOWLEDGE_2D_EDGE_CLEARANCE_STRENGTH,
): () => void {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const segments = edges.flatMap((edge) => {
    const a = byId.get(edge.source);
    const b = byId.get(edge.target);
    return a && b && a !== b ? [{ a, b }] : [];
  });
  return () => {
    for (const { a, b } of segments) {
      const ax = a.x ?? 0;
      const ay = a.y ?? 0;
      const bx = b.x ?? 0;
      const by = b.y ?? 0;
      const abx = bx - ax;
      const aby = by - ay;
      const lengthSq = abx * abx + aby * aby;
      if (lengthSq < 1e-6) continue;
      const minX = Math.min(ax, bx);
      const maxX = Math.max(ax, bx);
      const minY = Math.min(ay, by);
      const maxY = Math.max(ay, by);
      const length = Math.sqrt(lengthSq);
      for (const node of nodes) {
        if (!node.avoidsEdges || node === a || node === b || node.pinned) {
          continue;
        }
        const family =
          node.parentId !== undefined &&
          (a.id === node.parentId || b.id === node.parentId);
        const clearance =
          node.radius +
          (family ? KNOWLEDGE_2D_EDGE_SIBLING_CLEARANCE_PX : margin);
        const nx = node.x ?? 0;
        const ny = node.y ?? 0;
        if (
          nx < minX - clearance ||
          nx > maxX + clearance ||
          ny < minY - clearance ||
          ny > maxY + clearance
        ) {
          continue;
        }
        let t = ((nx - ax) * abx + (ny - ay) * aby) / lengthSq;
        if (t < 0) t = 0;
        else if (t > 1) t = 1;
        let dx = nx - (ax + abx * t);
        let dy = ny - (ay + aby * t);
        let distance = Math.hypot(dx, dy);
        if (distance >= clearance) continue;
        const targetCross = abx * (node.ty - ay) - aby * (node.tx - ax);
        if (distance < 1e-3) {
          // Exactly on the line: leave along the perpendicular on the same
          // side as the node's own target (stable and deterministic).
          const side = targetCross >= 0 ? 1 : -1;
          dx = (-aby / length) * side;
          dy = (abx / length) * side;
          distance = 1;
        } else {
          // Funnel-through: if the node's own target rests clear on the
          // FAR side of this segment's line, reverse the push so the wall
          // guides the node across instead of pinning it on the stale
          // side (springs decay with alpha; the wall does not).
          const nodeCross = abx * (ny - ay) - aby * (nx - ax);
          const targetLineDistance = Math.abs(targetCross) / length;
          if (
            targetLineDistance >= clearance &&
            nodeCross * targetCross < 0
          ) {
            dx = -dx;
            dy = -dy;
          }
        }
        const push = ((clearance - distance) / distance) * strength;
        node.vx = (node.vx ?? 0) + dx * push;
        node.vy = (node.vy ?? 0) + dy * push;
        // Outward along the spoke (parent b → child a): squeezed wedges
        // drain toward the fan rim instead of resting on the midline.
        const outward = (clearance - distance) * strength;
        node.vx += (-abx / length) * outward * KNOWLEDGE_2D_EDGE_DRIFT;
        node.vy += (-aby / length) * outward * KNOWLEDGE_2D_EDGE_DRIFT;
      }
    }
  };
}

/** One smooth constant-speed thinking sweep for the ambient 2D map
 *  (owner 2026-08-01: per-hop comet clocks made every segment travel at a
 *  different speed, lines popped in full-length, and end nodes lit before
 *  the beam visually reached them). The plan maps ONE progress value
 *  (knowledgeTendrilProgress — min sweep duration, speech-forced arrival)
 *  onto arc-length windows: every route from the Brain runs at constant
 *  speed relative to its own longest continuation, node highlights fire
 *  exactly when the head passes them, and the two cross-link comets meet
 *  at the MIDDLE of the article link at progress 1. */
export interface KnowledgeSweepEdge {
  id: string;
  source: string;
  target: string;
  taxonomy: boolean;
}

export interface KnowledgeSweepCrossSpan {
  from: number;
  to: number;
  /** meet — terminal link: comets depart BOTH endpoints and meet at the
   *  middle; through — the head traverses the full curve from `nearId`
   *  and continues the route beyond it. */
  mode: "meet" | "through";
  nearId: string;
}

export interface KnowledgeSweepPlan {
  /** Fraction of the sweep at which each node ignites. Values may exceed
   *  1: the sweep TIMER covers reaching the articles over taxonomy
   *  (progress 1 at the minimum animation time); relation hops and
   *  everything beyond them run on naturally at the same branch speed for
   *  however long their arc lengths need (owner 2026-08-01). */
  nodeArrival: Map<string, number>;
  /** Taxonomy edge draw window [from, to]; hubId is the end the line
   *  grows from. */
  edgeSpan: Map<string, { from: number; to: number; hubId: string }>;
  /** Cross-link windows. */
  crossSpan: Map<string, KnowledgeSweepCrossSpan>;
  /** Progress at which the LAST element completes (≥ 1). */
  maxProgress: number;
  /** Arrival of the EARLIEST article on the route (min-timer anchor). */
  firstArticleProgress: number;
}

/** Route the sweep over the MIXED active graph — taxonomy spokes AND
 *  article cross-links — so a path that continues through an article's
 *  relation sequences AFTER the beam reaches that article, never before
 *  the Brain beam even starts (owner 2026-08-01). Terminal cross-links
 *  keep the two-comet meet-at-the-middle; through links carry the head
 *  across the whole curve and onward. */
/** Ambient 2D sweep progress: LINEAR to 1 over the sweep duration in
 *  every phase (owner 2026-08-01: the 3D thinking cap made the head stall
 *  at ~0.8 — right at the article — before the cross-link finished; the
 *  2D route must complete in one smooth constant-speed sequence at the
 *  minimum animation time). Never runs backward within a phase. */
export function knowledgeSweepProgress2d(
  msInPhase: number,
  progressAtPhaseStart: number,
  sweepMs: number = KNOWLEDGE_3D_TENDRIL_SWEEP_MS,
  sweepMaxMs: number = sweepMs * 3,
  firstArticleProgress = 1,
  maxProgress = 1,
): number {
  // Two-segment timeline (owner 2026-08-01): the MIN timer is the time to
  // the FIRST article; everything after (remaining articles + relation
  // tails) finishes by the MAX timer.
  const minMs = Math.max(200, sweepMs);
  const maxMs = Math.max(minMs + 200, sweepMaxMs);
  const firstP = Math.max(1e-3, Math.min(firstArticleProgress, maxProgress));
  const elapsed = Math.max(0, msInPhase);
  const atStart = progressAtPhaseStart;
  let value: number;
  if (elapsed <= minMs) {
    value = (elapsed / minMs) * firstP;
  } else {
    value =
      firstP +
      ((elapsed - minMs) / (maxMs - minMs)) *
        Math.max(0, maxProgress - firstP);
  }
  return Math.min(Math.max(maxProgress, 1), Math.max(atStart, value));
}

export function computeKnowledgeSweepPlan(
  rootId: string,
  nodeIds: readonly string[],
  edgeIds: readonly string[],
  edges: readonly KnowledgeSweepEdge[],
  positionById: ReadonlyMap<string, { x: number; y: number }>,
  articleIds?: ReadonlySet<string>,
): KnowledgeSweepPlan {
  const activeEdgeIds = new Set(edgeIds);
  const inPath = new Set(nodeIds);
  const active = edges.filter(
    (edge) =>
      activeEdgeIds.has(edge.id) &&
      positionById.has(edge.source) &&
      positionById.has(edge.target) &&
      (!edge.taxonomy || (inPath.has(edge.source) && inPath.has(edge.target))),
  );
  const length = (edge: KnowledgeSweepEdge): number => {
    const a = positionById.get(edge.source)!;
    const b = positionById.get(edge.target)!;
    return Math.hypot(b.x - a.x, b.y - a.y);
  };
  const neighbors = new Map<
    string,
    Array<{ edge: KnowledgeSweepEdge; other: string; length: number }>
  >();
  for (const edge of active) {
    const px = length(edge);
    if (!neighbors.has(edge.source)) neighbors.set(edge.source, []);
    if (!neighbors.has(edge.target)) neighbors.set(edge.target, []);
    neighbors.get(edge.source)!.push({ edge, other: edge.target, length: px });
    neighbors.get(edge.target)!.push({ edge, other: edge.source, length: px });
  }
  // Dijkstra from the Brain over arc length (small graphs — the active
  // path is bounded by the focus limits).
  const distance = new Map<string, number>([[rootId, 0]]);
  const treeParent = new Map<string, { id: string; edge: KnowledgeSweepEdge }>();
  const settled = new Set<string>();
  while (true) {
    let currentId: string | null = null;
    let best = Infinity;
    for (const [id, value] of distance) {
      if (!settled.has(id) && value < best) {
        best = value;
        currentId = id;
      }
    }
    if (currentId === null) break;
    settled.add(currentId);
    for (const { edge, other, length: px } of neighbors.get(currentId) ?? []) {
      const candidate = best + px;
      if (candidate < (distance.get(other) ?? Infinity)) {
        distance.set(other, candidate);
        treeParent.set(other, { id: currentId, edge });
      }
    }
  }
  const treeChildren = new Map<string, string[]>();
  for (const [child, parent] of treeParent) {
    if (!treeChildren.has(parent.id)) treeChildren.set(parent.id, []);
    treeChildren.get(parent.id)!.push(child);
  }
  // Terminal cross tree edges become MEET links: the head only travels to
  // the middle, so the far node's effective distance is near + half.
  const meetFar = new Set<string>();
  for (const [child, parent] of treeParent) {
    if (parent.edge.taxonomy) continue;
    if ((treeChildren.get(child) ?? []).length > 0) continue;
    meetFar.add(child);
    distance.set(
      child,
      distance.get(parent.id)! + length(parent.edge) / 2,
    );
  }
  const order = [...settled].sort(
    (left, right) => (distance.get(left) ?? 0) - (distance.get(right) ?? 0),
  );
  // PRE-CROSS subtree: reachable from the root without traversing a
  // relation. The sweep TIMER (progress 0→1 over the minimum animation
  // time) normalizes over this taxonomy phase only; relation hops and
  // their continuations inherit the branch's px-per-progress rate and run
  // past 1 for as long as their lengths need.
  const preCross = new Set<string>([rootId]);
  for (const id of order) {
    const parent = treeParent.get(id);
    if (!parent) continue;
    if (parent.edge.taxonomy && preCross.has(parent.id)) preCross.add(id);
  }
  const longestPre = new Map<string, number>();
  for (let index = order.length - 1; index >= 0; index -= 1) {
    const id = order[index];
    if (!preCross.has(id)) continue;
    let value = distance.get(id)!;
    for (const child of treeChildren.get(id) ?? []) {
      if (!preCross.has(child)) continue;
      value = Math.max(value, longestPre.get(child) ?? 0);
    }
    longestPre.set(id, value);
  }
  // px-per-progress denominator per node: pre-cross nodes pace their own
  // longest taxonomy route; beyond-cross nodes inherit their tree
  // parent's rate so the tail runs at the branch's speed.
  const denominator = new Map<string, number>();
  for (const id of order) {
    if (preCross.has(id)) {
      denominator.set(id, Math.max(1e-6, longestPre.get(id) ?? 0));
    } else {
      const parent = treeParent.get(id);
      denominator.set(
        id,
        parent
          ? (denominator.get(parent.id) ?? 1e-6)
          : Math.max(1e-6, distance.get(id) ?? 1e-6),
      );
    }
  }
  const nodeArrival = new Map<string, number>();
  const edgeSpan = new Map<string, { from: number; to: number; hubId: string }>();
  const crossSpan = new Map<string, KnowledgeSweepCrossSpan>();
  let maxProgress = 1;
  for (const id of order) {
    const denom = denominator.get(id)!;
    const arrival = (distance.get(id) ?? 0) / denom;
    nodeArrival.set(id, arrival);
    maxProgress = Math.max(maxProgress, arrival);
    const parent = treeParent.get(id);
    if (!parent) continue;
    const from = (distance.get(parent.id) ?? 0) / denom;
    const to = arrival;
    if (parent.edge.taxonomy) {
      edgeSpan.set(parent.edge.id, { from, to, hubId: parent.id });
    } else {
      crossSpan.set(parent.edge.id, {
        from,
        to,
        mode: meetFar.has(id) ? "meet" : "through",
        nearId: parent.id,
      });
    }
  }
  // Non-tree active cross-links (both endpoints reached another way):
  // comets depart both ends once both are lit and meet at the middle,
  // running at the launch endpoint's branch speed.
  for (const edge of active) {
    if (edge.taxonomy || crossSpan.has(edge.id)) continue;
    const candidates = [edge.source, edge.target].filter((id) =>
      nodeArrival.has(id),
    );
    if (candidates.length === 0) continue;
    const nearId = candidates.reduce((best, id) =>
      nodeArrival.get(id)! > nodeArrival.get(best)! ? id : best,
    );
    const from = nodeArrival.get(nearId)!;
    const to =
      from + length(edge) / 2 / (denominator.get(nearId) ?? 1e-6);
    crossSpan.set(edge.id, { from, to, mode: "meet", nearId: edge.source });
    maxProgress = Math.max(maxProgress, to);
  }
  for (const span of crossSpan.values()) {
    maxProgress = Math.max(maxProgress, span.to);
  }
  let firstArticleProgress = 1;
  if (articleIds) {
    for (const [id, arrival] of nodeArrival) {
      if (articleIds.has(id)) {
        firstArticleProgress = Math.min(firstArticleProgress, arrival);
      }
    }
  }
  if (firstArticleProgress >= 1) {
    firstArticleProgress = Math.min(1, maxProgress);
  }
  return {
    nodeArrival,
    edgeSpan,
    crossSpan,
    maxProgress,
    firstArticleProgress,
  };
}

/** 3D per-beam path spec (owner 2026-08-02: the 3D thinking must ride the
 *  REAL beams — spokes, arms, article spokes, and crosses all animate on
 *  one constant-speed plan timeline, never on separate overlay lines).
 *  Each active edge carries its sweep-plan progress window keyed by the
 *  scene's "source|target" beam key; `meet` marks terminal cross-links
 *  whose comets depart BOTH endpoints and converge at the middle. */
export interface Knowledge3dPathEdgeSpan {
  from: number;
  to: number;
  meet: boolean;
  /** True when the sweep grows from the edge's source endpoint. */
  fromSource: boolean;
}

export interface Knowledge3dPathSpec {
  edgeSpans: ReadonlyMap<string, Knowledge3dPathEdgeSpan>;
  nodeArrival: ReadonlyMap<string, number>;
  /** Arrival of the FIRST node out of the Brain — the solid center-line
   *  front launches when the beam head crosses this (owner 2026-08-02:
   *  "the beam goes first, then the solid line starts moving once the
   *  beam has reached the first node"). */
  firstNodeProgress: number;
  firstArticleProgress: number;
  maxProgress: number;
}

export function knowledge3dPathSpec(
  plan: KnowledgeSweepPlan,
  edges: readonly { id: string; source: string; target: string }[],
): Knowledge3dPathSpec {
  const edgeSpans = new Map<string, Knowledge3dPathEdgeSpan>();
  for (const edge of edges) {
    const span = plan.edgeSpan.get(edge.id);
    if (span) {
      edgeSpans.set(`${edge.source}|${edge.target}`, {
        from: span.from,
        to: span.to,
        meet: false,
        fromSource: span.hubId === edge.source,
      });
      continue;
    }
    const cross = plan.crossSpan.get(edge.id);
    if (cross) {
      edgeSpans.set(`${edge.source}|${edge.target}`, {
        from: cross.from,
        to: cross.to,
        meet: cross.mode === "meet",
        fromSource: cross.nearId === edge.source,
      });
    }
  }
  let firstNodeProgress = Number.POSITIVE_INFINITY;
  for (const arrival of plan.nodeArrival.values()) {
    if (arrival > 1e-6 && arrival < firstNodeProgress) {
      firstNodeProgress = arrival;
    }
  }
  if (!Number.isFinite(firstNodeProgress)) {
    firstNodeProgress = plan.firstArticleProgress * 0.25;
  }
  return {
    edgeSpans,
    nodeArrival: plan.nodeArrival,
    firstNodeProgress,
    firstArticleProgress: plan.firstArticleProgress,
    maxProgress: plan.maxProgress,
  };
}

/** 3D sweep progress in PLAN units (owner 2026-08-02, final form): ONE
 *  constant animation-progress SPEED — no minimum duration, no thinking
 *  hold, no arrive window. Timers re-paced the fronts mid-route and made
 *  the animation visibly wait; the sweep now simply runs from the moment
 *  the path arrives at `speedPerSec` plan-units/second until the whole
 *  route (plus the solid front's tail run-out) is filled. Phase only
 *  gates existence (null clears); `progressAtPhaseStart` keeps the clock
 *  continuous and monotonic across the thinking→speaking flip. */
export function knowledgeSweepProgress3d(
  phase: KnowledgeFocusPhase,
  msInPhase: number,
  progressAtPhaseStart: number,
  speedPerSec: number,
  maxProgress = 1,
  tailProgress = 0,
): number {
  if (phase === null) return 0;
  const endProgress = maxProgress + Math.max(0, tailProgress);
  const rate = Math.max(0.05, speedPerSec) / 1000;
  return Math.min(
    endProgress,
    progressAtPhaseStart + Math.max(0, msInPhase) * rate,
  );
}

/** Hover subtree (owner 2026-08-02): hovering a node previews the beam
 *  links for the WHOLE path from that node down to its end articles.
 *  Returns the hovered id plus every descendant (parent-map BFS); the
 *  Brain therefore yields the entire taxonomy. */
export function knowledgeSubtreeIds(
  parentById: ReadonlyMap<string, string | null | undefined>,
  hoveredId: string,
): Set<string> {
  const childrenByParent = new Map<string, string[]>();
  for (const [id, parent] of parentById) {
    if (!parent || id === hoveredId) continue;
    const siblings = childrenByParent.get(parent);
    if (siblings) siblings.push(id);
    else childrenByParent.set(parent, [id]);
  }
  const subtree = new Set<string>([hoveredId]);
  const queue = [hoveredId];
  while (queue.length) {
    const id = queue.pop()!;
    for (const child of childrenByParent.get(id) ?? []) {
      if (subtree.has(child)) continue;
      subtree.add(child);
      queue.push(child);
    }
  }
  return subtree;
}

/** The hover preview lights the subtree's end articles at HALF the
 *  selected brightness (owner 2026-08-02). */
export const KNOWLEDGE_3D_HOVER_ARTICLE_LEVEL = 0.5;

/** Node-ignition ramp width in plan units: a node reaches full brightness
 *  this far after the solid front passes its arrival. The master clock's
 *  tail run-out must cover the first-node lag PLUS this window — the
 *  deepest article's arrival equals maxProgress exactly, so a run-out of
 *  the lag alone parks the solid front right AT its arrival and the ramp
 *  never starts (adversarial review 2026-08-02: the queried article's orb
 *  stayed dark while its label lit). */
export function knowledge3dRevealWindow(firstArticleProgress: number): number {
  return Math.max(0.02, firstArticleProgress * 0.08);
}

export function knowledge3dSweepTail(spec: {
  firstNodeProgress: number;
  firstArticleProgress: number;
}): number {
  return spec.firstNodeProgress + knowledge3dRevealWindow(spec.firstArticleProgress);
}

/** Polar-constrained fall (owner 2026-08-01: "give all the balls the same
 *  plane... one axis has 0 degrees to move in so they fall the right way
 *  toward the center while staying the proper minimum distance away from
 *  their parent"): each ball's BEARING about the Brain is anchored to its
 *  deterministic layout azimuth — the frozen axis, so branches can never
 *  scramble sideways — while its RADIUS is pure physics: gravity pulls
 *  every ball toward the center and the floors (parent article distance,
 *  collide, reservations) stop it. */
export function forceKnowledgePolarFall(
  nodes: readonly KnowledgeSettleNode[],
  hub: { x: number; y: number },
  gravity = 1.1,
  bearingStrength = 0.14,
): (alpha: number) => void {
  const bearing = new Map<string, number>();
  for (const node of nodes) {
    bearing.set(
      node.id,
      node.bearing ?? Math.atan2(node.ty - hub.y, node.tx - hub.x),
    );
  }
  return (alpha: number) => {
    for (const node of nodes) {
      if (node.pinned) continue;
      const dx = (node.x ?? 0) - hub.x;
      const dy = (node.y ?? 0) - hub.y;
      const radius = Math.hypot(dx, dy);
      if (radius < 1) continue;
      const ux = dx / radius;
      const uy = dy / radius;
      // Fall toward the center (alpha-scaled motion; the floors are not).
      node.vx = (node.vx ?? 0) - ux * gravity * alpha;
      node.vy = (node.vy ?? 0) - uy * gravity * alpha;
      // The frozen axis: bearing pinned to the layout azimuth.
      const target = bearing.get(node.id)!;
      let error = target - Math.atan2(dy, dx);
      while (error > Math.PI) error -= Math.PI * 2;
      while (error < -Math.PI) error += Math.PI * 2;
      const tangential = error * radius * bearingStrength * alpha;
      node.vx += -uy * tangential;
      node.vy += ux * tangential;
    }
  };
}

/** Every child keeps its parent's article-ring distance as a floor and
 *  always rests OUTWARD of the parent — at every level, subjects and orbs
 *  alike (owner 2026-08-01: "staying the proper minimum distance away
 *  from their parent node away from the center"). Pushes only the child;
 *  not alpha-scaled, so the floor holds at rest. */
export function forceKnowledgeParentFloor(
  nodes: readonly KnowledgeSettleNode[],
  hub: { x: number; y: number },
  strength = 0.6,
): () => void {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const pairs = nodes.flatMap((node) => {
    if (!node.parentId) return [];
    const parent = byId.get(node.parentId);
    return parent && parent !== node ? [{ node, parent }] : [];
  });
  return () => {
    for (const { node, parent } of pairs) {
      if (parent.pinned && node.pinned) continue;
      const floor = Math.max(
        node.radius + parent.radius + 12,
        parent.orbit ?? 0,
      );
      const px = parent.x ?? 0;
      const py = parent.y ?? 0;
      let dx = (node.x ?? 0) - px;
      let dy = (node.y ?? 0) - py;
      let distance = Math.hypot(dx, dy);
      if (distance < 1e-3) {
        const hx = px - hub.x;
        const hy = py - hub.y;
        const hubLength = Math.hypot(hx, hy) || 1;
        dx = hx / hubLength;
        dy = hy / hubLength;
        distance = 1;
      }
      if (distance < floor) {
        const push = ((floor - distance) / distance) * strength;
        node.vx = (node.vx ?? 0) + dx * push;
        node.vy = (node.vy ?? 0) + dy * push;
      }
      // Radiate: never closer to the Brain than the parent.
      const parentHub = Math.hypot(px - hub.x, py - hub.y);
      const nodeHubX = (node.x ?? 0) - hub.x;
      const nodeHubY = (node.y ?? 0) - hub.y;
      const nodeHub = Math.hypot(nodeHubX, nodeHubY);
      if (nodeHub < parentHub + 4 && nodeHub > 1e-3) {
        const push = ((parentHub + 4 - nodeHub) / nodeHub) * strength;
        node.vx = (node.vx ?? 0) + nodeHubX * push;
        node.vy = (node.vy ?? 0) + nodeHubY * push;
      }
    }
  };
}

/** Minimum radial step between a child and its parent — the L_min of the
 *  hierarchical radial rule r(child) ≥ r(parent) + L_min. */
export const KNOWLEDGE_RADIAL_MIN_STEP_PX = 26;

/** The HARD outward constraint of the rooted radial force layout (owner
 *  2026-08-01, formal spec): every child stays strictly farther from the
 *  center than its parent, enforced as a position projection each tick in
 *  BFS depth order — the one rule the organic forces can never violate. */
export function forceKnowledgeRadialOrder(
  nodes: readonly KnowledgeSettleNode[],
  hub: { x: number; y: number },
  minStep: number = KNOWLEDGE_RADIAL_MIN_STEP_PX,
  velocityFactor = 1,
): () => void {
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const ordered = [...nodes].sort(
    (left, right) => (left.depth ?? 99) - (right.depth ?? 99),
  );
  const safeVelocityFactor = Math.max(1e-6, velocityFactor);
  return () => {
    const nextRadiusById = new Map<string, number>();
    for (const node of ordered) {
      const x = node.x ?? 0;
      const y = node.y ?? 0;
      // D3 discards accumulated velocity for fixed nodes during integration.
      // Predict that exact position here as well; link/charge can temporarily
      // write velocity onto the pinned Brain before D3 clamps it back to fx/fy.
      let nextX = node.pinned
        ? (node.fx ?? node.tx)
        : x + (node.vx ?? 0) * safeVelocityFactor;
      let nextY = node.pinned
        ? (node.fy ?? node.ty)
        : y + (node.vy ?? 0) * safeVelocityFactor;
      let nextRadius = Math.hypot(nextX - hub.x, nextY - hub.y);
      if (node.pinned) {
        nextRadiusById.set(node.id, nextRadius);
        continue;
      }
      const parent = node.parentId ? byId.get(node.parentId) : undefined;
      if (!parent) {
        nextRadiusById.set(node.id, nextRadius);
        continue;
      }
      const parentNextRadius =
        nextRadiusById.get(parent.id) ??
        Math.hypot(
          (parent.x ?? 0) +
            (parent.vx ?? 0) * safeVelocityFactor -
            hub.x,
          (parent.y ?? 0) +
            (parent.vy ?? 0) * safeVelocityFactor -
            hub.y,
        );
      const need = parentNextRadius + minStep;
      if (nextRadius < need) {
        let dx = nextX - hub.x;
        let dy = nextY - hub.y;
        let directionLength = Math.hypot(dx, dy);
        if (directionLength < 1e-6) {
          dx = x - hub.x;
          dy = y - hub.y;
          directionLength = Math.hypot(dx, dy);
        }
        if (directionLength < 1e-6) {
          dx = Math.cos(node.bearing ?? 0);
          dy = Math.sin(node.bearing ?? 0);
          directionLength = 1;
        }
        nextX = hub.x + (dx / directionLength) * need;
        nextY = hub.y + (dy / directionLength) * need;
        node.vx = (nextX - x) / safeVelocityFactor;
        node.vy = (nextY - y) / safeVelocityFactor;
        nextRadius = need;
      }
      nextRadiusById.set(node.id, nextRadius);
    }
  };
}

export interface KnowledgeSettleLink {
  source: string;
  target: string;
  taxonomy: boolean;
  /** Desired Euclidean separation in canvas pixels. */
  distance?: number;
}

/** Constant padding P in ||x_i-x_j|| >= R_i + R_j + P. */
export const KNOWLEDGE_2D_COLLISION_PADDING_PX = 10;

/** One topology spring length for every ambient-2D taxonomy edge. The
 *  operator's legacy 2D distance scalar now scales this physical value;
 *  source-map geometry never does. */
export const KNOWLEDGE_2D_LINK_DISTANCE_PX = 150;

export function knowledge2dLinkDistance(
  tuning: Pick<Knowledge3dTuning, "ring2dPeers"> =
    DEFAULT_KNOWLEDGE_2D_TUNING,
): number {
  return KNOWLEDGE_2D_LINK_DISTANCE_PX * tuning.ring2dPeers;
}

export function createKnowledgeSettleSimulation(
  nodes: KnowledgeSettleNode[],
  velocityDecay: number = KNOWLEDGE_2D_SETTLE_VELOCITY_DECAY,
  edges: readonly KnowledgeSettleEdge[] = [],
  hub?: { x: number; y: number },
  links: readonly KnowledgeSettleLink[] = [],
  chargeStrength = 42,
): ForceSimulation<KnowledgeSettleNode> {
  for (const node of nodes) {
    if (node.pinned) {
      node.x = node.tx;
      node.y = node.ty;
      node.fx = node.tx;
      node.fy = node.ty;
    }
  }
  return forceSimulation(nodes, 2)
    .stop()
    .alphaMin(KNOWLEDGE_3D_ALPHA_MIN)
    .alphaDecay(KNOWLEDGE_3D_ALPHA_DECAY)
    .velocityDecay(velocityDecay)
    // Rooted radial force-directed layout (owner spec 2026-08-01): free
    // organic 2D movement from links + many-body + collide, with ONE hard
    // rule — the outward radial constraint — and the root pinned.
    .force(
      "link",
      hub && links.length > 0
        ? forceLink(
            links.map((link) => ({ ...link })),
          )
            .id((node: KnowledgeSettleNode) => node.id)
            .distance(
              (link: {
                source: KnowledgeSettleNode;
                target: KnowledgeSettleNode;
                taxonomy: boolean;
                distance?: number;
              }) => {
                if (!link.taxonomy) {
                  return link.distance ?? KNOWLEDGE_2D_LINK_DISTANCE_PX * 1.4;
                }
                const parent =
                  (link.source.depth ?? 99) <= (link.target.depth ?? 99)
                    ? link.source
                    : link.target;
                const child =
                  parent === link.source ? link.target : link.source;
                return Math.max(
                  link.distance ?? KNOWLEDGE_2D_LINK_DISTANCE_PX,
                  parent.radius +
                    child.radius +
                    KNOWLEDGE_2D_COLLISION_PADDING_PX,
                );
              },
            )
            .strength(
              (link: { taxonomy: boolean }) => (link.taxonomy ? 0.5 : 0.02),
            )
        : null,
    )
    .force(
      "charge",
      hub
        ? forceManyBody()
            .strength(-chargeStrength)
            .distanceMax(620)
        : null,
    )
    .force(
      "x",
      hub
        ? null
        : forceX((node: KnowledgeSettleNode) => node.tx).strength(
            (node: KnowledgeSettleNode) =>
              node.pinned ? 0.4 : knowledgeSettleStrength(node.id),
          ),
    )
    .force(
      "y",
      hub
        ? null
        : forceY((node: KnowledgeSettleNode) => node.ty).strength(
            (node: KnowledgeSettleNode) =>
              node.pinned ? 0.4 : knowledgeSettleStrength(node.id),
          ),
    )
    .force(
      "collide",
      forceCollide()
        .radius(
          (node: KnowledgeSettleNode) =>
            node.radius + KNOWLEDGE_2D_COLLISION_PADDING_PX / 2,
        )
        .iterations(3),
    )
    .force(
      "edge-clearance",
      !hub && edges.length > 0
        ? forceKnowledgeEdgeClearance(nodes, edges)
        : null,
    )
    .force(
      "orbit",
      !hub && nodes.some((node) => (node.orbit ?? 0) > 0)
        ? forceKnowledgeOrbit(nodes)
        : null,
    )
    // Last by design. D3 applies forces in insertion order and then
    // integrates velocity, so this predictive projection sees every
    // organic force and makes the next position obey the hard radial rule.
    .force(
      "radial-order",
      hub
        ? forceKnowledgeRadialOrder(
            nodes,
            hub,
            KNOWLEDGE_RADIAL_MIN_STEP_PX,
            1 - velocityDecay,
          )
        : null,
    );
}

/** Planar (ambient 2D) ball targets: the same branch-cone construction
 *  flattened into the viewport plane — depth-1 peers keep their exact 2D
 *  azimuth sectors, descendants fan inside a planar cone around their
 *  parent's direction, and every z stays 0 so the same force engine (run
 *  with numDimensions 2) settles the graph in-plane. */
export function knowledge2dBallTargets(
  nodes: readonly Knowledge3dBallNode[],
  hub: { x: number; y: number },
  tuning: Knowledge3dTuning = DEFAULT_KNOWLEDGE_2D_TUNING,
): Float32Array {
  const targets = new Float32Array(nodes.length * 3);
  const directions = new Float32Array(nodes.length * 2);
  const indexById = new Map(nodes.map((node, index) => [node.id, index]));
  const order = nodes
    .map((_, index) => index)
    .sort((a, b) => (nodes[a].depth ?? 99) - (nodes[b].depth ?? 99));
  for (const index of order) {
    const node = nodes[index];
    if (isBallRoot(node)) continue;
    const parentIndex =
      node.parentId != null ? indexById.get(node.parentId) : undefined;
    const parentIsHub =
      parentIndex === undefined || isBallRoot(nodes[parentIndex]);
    let angle: number;
    if (parentIsHub) {
      // 2D y grows downward; world y grows upward.
      angle = Math.atan2(hub.y - node.y, node.x - hub.x);
    } else {
      const parentAngle = Math.atan2(
        directions[parentIndex * 2 + 1],
        directions[parentIndex * 2],
      );
      const depth = node.depth ?? 3;
      const cone = Math.max(0.22, 0.85 - 0.16 * (depth - 1));
      const beta = cone * (0.35 + 0.6 * hash01(node.id, 29));
      const sign = hash01(node.id, 31) < 0.5 ? -1 : 1;
      angle = parentAngle + sign * beta;
    }
    directions[index * 2] = Math.cos(angle);
    directions[index * 2 + 1] = Math.sin(angle);
    const shell =
      knowledge3dShellRadius(node.depth ?? 3, tuning) *
      (1 + (hash01(node.id, 37) - 0.5) * 0.08);
    targets[index * 3] = Math.cos(angle) * shell;
    targets[index * 3 + 1] = Math.sin(angle) * shell;
    targets[index * 3 + 2] = 0;
  }
  return targets;
}

/** The ambient 2D physics view shares the 3D tuning shape (yawSpeed is
 *  simply unused in-plane); its slider panel and persistence are separate
 *  so each renderer keeps its own dialed-in feel. */
export const DEFAULT_KNOWLEDGE_2D_TUNING: Knowledge3dTuning = {
  ...DEFAULT_KNOWLEDGE_3D_TUNING,
  velocityDecay: KNOWLEDGE_2D_SETTLE_VELOCITY_DECAY,
  // The classic 2D map's full subject glow — attenuation is a 3D-density
  // concern, never part of the original flat look.
  nodeGlow: 1,
  // Gradient cross-links rest at half opacity; the thinking sweep paints
  // the full-opacity line over them.
  crossOpacity: 0.5,
  yawSpeed: 0,
  branchWidth: 10,
};

/** Ambient 2D exposes only genuine simulation and paint controls. */
/**
 * Group tuning fields by their category label, preserving both the first
 * appearance order of each group and the field order within it, so the
 * tuner panels can render headed sections instead of one flat list.
 */
export function groupKnowledgeTuningFields(
  fields: readonly Knowledge3dTuningField[],
): Array<{ group: string; fields: Knowledge3dTuningField[] }> {
  const groups: Array<{ group: string; fields: Knowledge3dTuningField[] }> = [];
  const byName = new Map<string, Knowledge3dTuningField[]>();
  for (const field of fields) {
    let bucket = byName.get(field.group);
    if (!bucket) {
      bucket = [];
      byName.set(field.group, bucket);
      groups.push({ group: field.group, fields: bucket });
    }
    bucket.push(field);
  }
  return groups;
}

export const KNOWLEDGE_2D_TUNING_FIELDS: readonly Knowledge3dTuningField[] = [
  { key: "ring2dPeers", label: "Link distance", group: "Layout", min: 0.5, max: 1.6, step: 0.05 },
  { key: "chargeStrength", label: "Node repulsion", group: "Motion", min: 0, max: 120, step: 2 },
  { key: "velocityDecay", label: "Damping", group: "Motion", min: 0.1, max: 0.6, step: 0.01 },
  { key: "sweepSeconds", label: "Min sweep to first article (s)", group: "Thinking", min: 0.5, max: 6, step: 0.1 },
  { key: "sweepMaxSeconds", label: "Max sweep total (s)", group: "Thinking", min: 1, max: 12, step: 0.5 },
  { key: "branchWidth", label: "Branch width", group: "Beams", min: 1, max: 20, step: 0.5 },
  { key: "branchOpacity", label: "Branch opacity", group: "Beams", min: 0, max: 1, step: 0.05 },
  { key: "nodeGlow", label: "Node glow", group: "Nodes", min: 0, max: 1.5, step: 0.05 },
  { key: "labelDistance", label: "Label distance", group: "Nodes", min: 0.6, max: 2.5, step: 0.05 },
  { key: "crossWidth", label: "Link width", group: "Article links", min: 1, max: 16, step: 0.5 },
  { key: "crossOpacity", label: "Link opacity", group: "Article links", min: 0, max: 1, step: 0.05 },
  { key: "dashFrequency", label: "Dash frequency", group: "Article links", min: 0.05, max: 0.8, step: 0.01 },
];

export function clampKnowledge2dTuning(value: unknown): Knowledge3dTuning {
  const source = (
    typeof value === "object" && value !== null ? value : {}
  ) as Record<string, unknown>;
  const tuning = { ...DEFAULT_KNOWLEDGE_2D_TUNING };
  for (const field of KNOWLEDGE_2D_TUNING_FIELDS) {
    const raw = source[field.key];
    if (typeof raw === "number" && Number.isFinite(raw)) {
      tuning[field.key] = Math.min(field.max, Math.max(field.min, raw));
    }
  }
  return tuning;
}

export function knowledge3dFramedDistance(fovDegrees: number): number {
  const half = ((fovDegrees / 2) * Math.PI) / 180;
  return (
    ((KNOWLEDGE_3D_WORLD_SPAN / 2) * KNOWLEDGE_3D_FRAME_MARGIN) /
    Math.tan(half)
  );
}

/** Tendril/reveal pacing (owner-directed 2026-07-31, retuned same day:
 *  warm turns finish in 1-3 s, so the sweep must be FAST). While thinking,
 *  the tendrils sweep LINEARLY through the intermediate subnodes — hitting
 *  and lighting each one in real time within KNOWLEDGE_3D_TENDRIL_SWEEP_MS
 *  — then park just short of the articles (the cap sits below the article
 *  reveal threshold). The moment speech begins the final hop completes
 *  within KNOWLEDGE_3D_TENDRIL_ARRIVE_MS and the articles light up.
 *  Progress never runs backward within a phase. */
export type KnowledgeFocusPhase = "thinking" | "speaking" | null;
export const KNOWLEDGE_3D_TENDRIL_THINKING_CAP = 0.8;
export const KNOWLEDGE_3D_TENDRIL_SWEEP_MS = 1100;
export const KNOWLEDGE_3D_TENDRIL_ARRIVE_MS = 550;

/** The sweep duration is tunable (owner 2026-08-01: the reveal completed
 *  too fast to see) and doubles as the animation's MINIMUM: when speech
 *  starts early the arrival still plays out the remaining sweep at the
 *  same rate instead of snapping, so the full path is always visible for
 *  at least the tuned duration. */
export function knowledgeTendrilProgress(
  phase: KnowledgeFocusPhase,
  msInPhase: number,
  progressAtPhaseStart: number,
  sweepMs: number = KNOWLEDGE_3D_TENDRIL_SWEEP_MS,
): number {
  const duration = Math.max(200, sweepMs);
  if (phase === null) return 0;
  if (phase === "thinking") {
    return Math.max(
      progressAtPhaseStart,
      Math.min(
        KNOWLEDGE_3D_TENDRIL_THINKING_CAP,
        (Math.max(0, msInPhase) / duration) *
          KNOWLEDGE_3D_TENDRIL_THINKING_CAP,
      ),
    );
  }
  const arriveMs = Math.max(
    KNOWLEDGE_3D_TENDRIL_ARRIVE_MS,
    (1 - progressAtPhaseStart) * duration,
  );
  return (
    progressAtPhaseStart +
    (1 - progressAtPhaseStart) *
      Math.min(1, Math.max(0, msInPhase) / arriveMs)
  );
}

/** Per-node reveal along the tendril sweep: rank 0 (hub) lights first and
 *  the deepest rank (articles) lights only as progress reaches 1 — i.e.
 *  exactly when speech begins. */
export function knowledgeFocusRevealLevel(
  rank: number,
  maxRank: number,
  progress: number,
): number {
  const fraction = maxRank > 0 ? rank / maxRank : 0;
  // Intermediate ranks spread across the thinking sweep; the deepest rank
  // (articles) starts strictly ABOVE the thinking cap so it can only light
  // during the speech-onset arrival.
  const start = fraction * 0.82;
  const end = start + 0.14;
  return Math.min(1, Math.max(0, (progress - start) / (end - start)));
}

/** Depth-ordered reveal for the query path: the lighting visibly branches
 *  outward from Brain, exactly the old center-out reading. Returns delay
 *  ranks (0 = hub) keyed by node id. */
export function knowledgeFocusRevealOrder(
  focusNodeIds: readonly string[],
  depthById: ReadonlyMap<string, number>,
): Map<string, number> {
  const ranks = new Map<string, number>();
  const depths = focusNodeIds
    .map((id) => depthById.get(id) ?? 0)
    .sort((a, b) => a - b);
  const unique = Array.from(new Set(depths));
  for (const id of focusNodeIds) {
    ranks.set(id, unique.indexOf(depthById.get(id) ?? 0));
  }
  return ranks;
}

/** Rebuild a KnowledgeLayout whose x/y are camera-projected normalized
 *  screen coordinates, preserving every other node field. The existing SVG
 *  focus overlay (traces, node waves, label plates, leader lines) consumes
 *  this untouched — the entire current thinking look rides on top of the
 *  rotating 3D model. */
export function projectedKnowledgeLayout(
  layout: KnowledgeLayout,
  projected: ReadonlyMap<string, { x: number; y: number }>,
): KnowledgeLayout {
  const nodes: KnowledgeLayoutNode[] = layout.nodes.map((node) => {
    const point = projected.get(node.id);
    return point ? { ...node, x: point.x, y: point.y } : node;
  });
  return { ...layout, nodes };
}

/** Leaf discs in the 2D painter are flat fills; subject discs carry the
 *  highlight gradient, rim, ring, and depth glow. The 3D sprites branch on
 *  the same predicate so the two renderers cannot disagree. */
export function isKnowledge3dSubjectRole(
  role: KnowledgeHierarchyRole | undefined,
): boolean {
  return role !== undefined && !isKnowledgeLeafRole(role);
}

/** Delivery comet timing (owner 2026-08-04: when a satellite's Task files an
 *  article into another agent's graph, the source ball pulses and a comet —
 *  the visual representation of the article — flies to the new node and
 *  ignites it). The comet may have to WAIT for the target node to exist in
 *  the refreshed cloud before it can fly; a target that never materializes
 *  expires the delivery instead of stranding a comet forever. */
export const KNOWLEDGE_3D_DELIVERY_WAIT_MAX_MS = 12_000;
export const KNOWLEDGE_3D_DELIVERY_FLIGHT_MS = 1_600;
export const KNOWLEDGE_3D_DELIVERY_BURST_MS = 500;

/** Ease-in-out cubic: the comet leaves its ball gently, crosses fast, and
 *  settles onto the node — a thrown object, not a linear scan. */
export function knowledgeDeliveryEase(t: number): number {
  const x = Math.min(1, Math.max(0, t));
  return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
}

/** Comet position along a quadratic bezier from the source ball's center to
 *  the target node. The control point pushes the midpoint AWAY from the
 *  world origin (the balls orbit the origin, so an outward bow clears the
 *  executive ball instead of tunnelling through it); a near-origin midpoint
 *  (opposite-side delivery) falls back to a fixed vertical lift so the
 *  curve stays well-defined. Pure math — pinned by a WebGL-free contract
 *  test. */
export function knowledgeDeliveryCometPosition(
  from: { x: number; y: number; z: number },
  to: { x: number; y: number; z: number },
  t: number,
): { x: number; y: number; z: number } {
  const eased = knowledgeDeliveryEase(t);
  const midX = (from.x + to.x) / 2;
  const midY = (from.y + to.y) / 2;
  const midZ = (from.z + to.z) / 2;
  const spanX = to.x - from.x;
  const spanY = to.y - from.y;
  const spanZ = to.z - from.z;
  const span = Math.sqrt(spanX * spanX + spanY * spanY + spanZ * spanZ);
  const midLen = Math.sqrt(midX * midX + midY * midY + midZ * midZ);
  const lift = span * 0.3;
  let controlX = midX;
  let controlY = midY + lift;
  let controlZ = midZ;
  if (midLen > 1e-3) {
    controlX = midX + (midX / midLen) * lift;
    controlY = midY + (midY / midLen) * lift;
    controlZ = midZ + (midZ / midLen) * lift;
  }
  const a = (1 - eased) * (1 - eased);
  const b = 2 * (1 - eased) * eased;
  const c = eased * eased;
  return {
    x: a * from.x + b * controlX + c * to.x,
    y: a * from.y + b * controlY + c * to.y,
    z: a * from.z + b * controlZ + c * to.z,
  };
}
