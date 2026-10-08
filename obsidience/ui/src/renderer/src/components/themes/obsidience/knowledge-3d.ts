// Pure math + policy for the 3D knowledge scene. Everything WebGL-free so
// the contracts stay unit-testable under jsdom (which has no GL context).
//
// The same d3-force-3d engine as vasturiano's radialout example: taxonomy
// springs, weak relationship springs, charge and collision choose the angles.
// First-level peers share an inner radius; each branch divides the remaining
// distance across its descendants. One radius constraint fits the tree
// without fixed directions or expanding depth layers. Moving sibling bisectors
// keep each descendant inside its branch in one force pass.
// The existing scene owns cooling and rendering; the 2D layout is independent.

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
 *  cap; idle ambient rotation renders at half cadence in every profile
 *  (owner 2026-10-08: idle spin capped at 15 fps, timer-driven). The thinking
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
/** Dolly clamps as multiples of the framed distance; the camera starts
 *  slightly outside the exact framing so the ball's near hemisphere (which
 *  perspective enlarges) stays inside the hub's asymmetric headroom. */
export const KNOWLEDGE_3D_MIN_DOLLY = 0.35;
export const KNOWLEDGE_3D_MAX_DOLLY = 2.4;
export const KNOWLEDGE_3D_INITIAL_DOLLY = 1.1;

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
  if (!options.focusActive && !options.interacting) return 1000 / KNOWLEDGE_3D_IDLE_FPS;
  if (options.animationProfile === "maximum") return 0;
  return options.focusActive
    ? 1000 / KNOWLEDGE_3D_SWEEP_FPS
    : 1000 / KNOWLEDGE_3D_ACTIVE_FPS;
}

/** Advance a capped-frame deadline without discarding residual time. `null`
 *  means the frame is not due. Maximum/native-refresh mode uses interval 0 for
 *  active motion and therefore accepts every requestAnimationFrame callback. */
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
  /** Legacy 2D link spacing; 3D radius is fitted from the live branches. */
  linkDistance: number;
  /** Padding around 3D nodes and branches; the sphere fits this clearance. */
  branchClearance: number;
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
  /** Legacy 2D label setting; the 3D hover label follows the pointer. */
  labelDistance: number;
  /** Saved presentation scale, retained for profile and satellite appearance.
   *  Physical radius is fitted automatically from the branch population. */
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
  // The shared solver has fixed motion settings. Satellites retain their
  // smaller presentation baseline; physical spacing is fitted automatically.
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
  linkDistance: 1,
  branchClearance: 1,
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
  /** Scene-wide controls owned by the main graph. */
  mainOnly?: true;
}

/** Slider metadata for the front-end panel; clamping uses the same table
 *  so a stale persisted value can never leave the sanctioned range. */
export const KNOWLEDGE_3D_TUNING_FIELDS: readonly Knowledge3dTuningField[] = [
  { key: "branchClearance", label: "Branch clearance", group: "Layout", min: 0.5, max: 2, step: 0.05, description: "Space around nodes and branches. Lower values pack the sphere closer; higher values make it grow. Article and node sizes stay the same." },
  { key: "yawSpeed", label: "Rotation speed", group: "Motion", mainOnly: true, min: 0, max: 0.2, step: 0.005, description: "Camera rotation around all graphs. Pauses while dragging or focused on a satellite." },
  { key: "automaticSweepSpeed", label: "Automatic speed", group: "Thinking", min: 0, max: 1, step: 1, toggle: true, description: "Reveal the packet at a readable pace, keep paths flowing through speech, and fade when playback ends. Turn this off to set the reveal speed." },
  { key: "sweepSpeed", label: "Animation speed", group: "Thinking", min: 0.1, max: 3, step: 0.05, description: "Speed of the continuous path reveal when Automatic speed is off. Speech never skips unfinished links." },
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
  { key: "rolePlates", label: "Role nameplates", group: "Nodes", mainOnly: true, min: 0, max: 1, step: 1, toggle: true, description: "Show the role glyph above every graph." },
  { key: "crossWidth", label: "Link width", group: "Beams", min: 1, max: 16, step: 0.5, description: "Width of the curved article-to-article link beams." },
  { key: "crossOpacity", label: "Link opacity", group: "Beams", min: 0, max: 1, step: 0.05, description: "Opacity of the curved article links at rest." },
  { key: "dashFrequency", label: "Dash frequency", group: "Beams", min: 0.05, max: 0.8, step: 0.01, description: "Density of the checkered dashes along article links." },
  { key: "streakSpeed", label: "Light speed", group: "Beams", min: 0.1, max: 4, step: 0.1, description: "Travel speed of the light streaks riding the article links." },
  { key: "streakSpan", label: "Light length", group: "Beams", min: 0.01, max: 0.2, step: 0.005, description: "Length of each traveling light streak." },
  { key: "streakCount", label: "Light count", group: "Beams", min: 0, max: 8, step: 1, description: "Light streaks per article link. Zero disables them (rebuilds the geometry)." },
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
  // Old physical radius/link-distance values no longer override automatic fit.
  // The briefly exposed graphRadius key represented presentation scale;
  // migrate that separately without resizing glyphs.
  const savedScale = source.graphScale ?? source.graphRadius;
  if (typeof savedScale === "number" && Number.isFinite(savedScale)) {
    tuning.graphScale = Math.min(2, Math.max(0.4, savedScale));
  }
  return tuning;
}

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

/** Base spacing control; 3D divides the whole ball across each branch. */
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
}, clearance = 1): number {
  // Scale only the surrounding padding. At 1, preserve the accepted layout.
  return node.radius * 1.4 + 2.75 + (clearance - 1) * (node.radius * 0.4 + 2.75);
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
export const KNOWLEDGE_3D_REHEAT_ALPHA = 0.4;
const TAXONOMY_LINK_STRENGTH = 0.7;
const CROSS_LINK_STRENGTH = 0.03;
const COLLIDE_ITERATIONS = 2;

export interface KnowledgeForceNode extends ForceSimulationNode {
  id: string;
  depth?: number;
  role?: KnowledgeHierarchyRole | string;
  /** Exact placement parent; defines private 3D depth and branch membership. */
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

/** Every Brain branch starts on one shared inner radius. Each branch divides
 * the remaining radius across its own depth; earlier Articles keep their layer.
 * Population and glyph clearance size the WHOLE ball once, not separate crowns.
 */
export interface Knowledge3dRadialLayout {
  radius: number;
  radii: ReadonlyMap<string, number>;
  clearances: ReadonlyMap<string, number>;
  depths: ReadonlyMap<string, number>;
  fractions: ReadonlyMap<string, number>;
  footprints: ReadonlyMap<string, ReadonlyMap<number, number>>;
}

export function knowledge3dRadialLayout(
  nodes: readonly KnowledgeForceNode[],
  branchClearance = 1,
): Knowledge3dRadialLayout {
  const byId = new Map(nodes.map(node => [node.id, node]));
  const clearances = new Map(nodes.map(node => [node.id, knowledge3dAvoidanceRadius(node, branchClearance)]));
  const ancestry = new Map<string, { depth: number; branch: string }>();
  for (const node of nodes) {
    if (isBallRoot(node)) ancestry.set(node.id, { depth: 0, branch: node.id });
  }
  for (const node of nodes) {
    const path: KnowledgeForceNode[] = [], seen = new Set<string>();
    let at: KnowledgeForceNode | undefined = node;
    while (at && !ancestry.has(at.id) && !seen.has(at.id)) {
      seen.add(at.id);
      path.push(at);
      at = at.parentId ? byId.get(at.parentId) : undefined;
    }
    let parent = at ? ancestry.get(at.id) : undefined;
    for (const member of path.reverse()) {
      const depth = parent ? parent.depth + 1 : 1;
      const branch = parent && parent.depth > 0 ? parent.branch : member.id;
      parent = { depth, branch };
      ancestry.set(member.id, parent);
    }
  }
  const branchDepth = new Map<string, number>();
  for (const { depth, branch } of ancestry.values()) {
    branchDepth.set(branch, Math.max(depth, branchDepth.get(branch) ?? 0));
  }
  const firstLayer = 1 / Math.max(1, ...branchDepth.values());
  const fractions = new Map<string, number>();
  for (const node of nodes) {
    const { depth, branch } = ancestry.get(node.id)!;
    const remainingDepth = (branchDepth.get(branch) ?? 1) - 1;
    const fraction = depth === 0 ? 0 : firstLayer + (remainingDepth > 0
      ? (1 - firstLayer) * (depth - 1) / remainingDepth : 0);
    fractions.set(node.id, fraction);
  }
  const layers = [...new Set(fractions.values())].sort((a, b) => a - b);
  const footprints = new Map(nodes.map(node => [node.id, new Map<number, number>()]));
  for (const node of [...nodes].sort((a, b) => ancestry.get(b.id)!.depth - ancestry.get(a.id)!.depth)) {
    const fraction = fractions.get(node.id)!;
    const profile = footprints.get(node.id)!;
    for (const layer of layers) {
      // Once past a node's layer, only its continuing descendants need room.
      const footprint = Math.max(profile.get(layer) ?? 0,
        fraction > 0 && fraction >= layer ? (clearances.get(node.id)! / fraction) ** 2 : 0);
      profile.set(layer, footprint);
      const parent = node.parentId ? footprints.get(node.parentId) : undefined;
      if (parent) parent.set(layer, (parent.get(layer) ?? 0) + footprint);
    }
  }
  // A branch inherits its children's required area, including earlier layers.
  // Reserve 40% of the surface for physical clearance discs, leaving room at
  // branch boundaries. There is no saved size or fixed radius floor.
  const footprint = nodes.filter(node => !node.parentId || !byId.has(node.parentId))
    .reduce((sum, node) => sum + (footprints.get(node.id)!.get(layers[0]) ?? 0), 0);
  let radius = Math.sqrt(footprint / 1.6);
  for (const node of nodes) {
    const parent = node.parentId ? byId.get(node.parentId) : undefined;
    if (!parent) continue;
    const step = fractions.get(node.id)! - fractions.get(parent.id)!;
    if (step > 0) radius = Math.max(radius,
      (clearances.get(node.id)! + clearances.get(parent.id)!) / step);
  }
  return {
    radius,
    radii: new Map([...fractions].map(([id, fraction]) => [id, radius * fraction])),
    clearances,
    depths: new Map([...ancestry].map(([id, { depth }]) => [id, depth])),
    fractions,
    footprints,
  };
}

/** Only distance from Brain is constrained. D3's links, charge and collision
 * forces choose the angles, as in radialout. Predict its damped step so
 * every integrated node stays on its assigned radius, including the first frame.
 */
function forceKnowledgeRadialOut(
  nodes: readonly KnowledgeForceNode[], layout: Knowledge3dRadialLayout,
  velocityDecay: number,
): (alpha: number) => void {
  const retainedVelocity = 1 - velocityDecay;
  const project = (node: KnowledgeForceNode, initial: boolean): void => {
    const radius = layout.radii.get(node.id) ?? 0;
    if (!radius) return;
    const x = (node.x ?? 0) + (initial ? 0 : (node.vx ?? 0) * retainedVelocity);
    const y = (node.y ?? 0) + (initial ? 0 : (node.vy ?? 0) * retainedVelocity);
    const z = (node.z ?? 0) + (initial ? 0 : (node.vz ?? 0) * retainedVelocity);
    const length = Math.hypot(x, y, z);
    const scale = length > 1e-10 ? radius / length : 0;
    const px = length > 1e-10 ? x * scale : radius;
    const py = y * scale, pz = z * scale;
    if (initial) {
      node.x = px; node.y = py; node.z = pz;
    } else {
      node.vx = (px - (node.x ?? 0)) / retainedVelocity;
      node.vy = (py - (node.y ?? 0)) / retainedVelocity;
      node.vz = (pz - (node.z ?? 0)) / retainedVelocity;
    }
  };
  for (const node of nodes) project(node, true);
  return (alpha: number) => {
    for (const node of nodes) project(node, false);
    if (alpha > KNOWLEDGE_3D_ALPHA_MIN || !layout.radius) return;
    // At the final ordinary tick, fit any remaining physical contact pressure
    // with one scalar expansion. This is the minimum scale for these bearings;
    // no extra solver pass, idle audit or growth loop is needed.
    const predicted = nodes.map(node => [
      (node.x ?? 0) + (node.vx ?? 0) * retainedVelocity,
      (node.y ?? 0) + (node.vy ?? 0) * retainedVelocity,
      (node.z ?? 0) + (node.vz ?? 0) * retainedVelocity,
    ]);
    let scale = 1;
    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        const a = predicted[i], b = predicted[j];
        const distance = Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
        if (distance > 1e-8) scale = Math.max(scale,
          (layout.clearances.get(nodes[i].id)! + layout.clearances.get(nodes[j].id)!) / distance);
      }
    }
    if (scale > 1) {
      layout.radius *= scale;
      layout.radii = new Map([...layout.radii].map(([id, radius]) => [id, radius * scale]));
      for (const node of nodes) project(node, false);
    }
  };
}

const radialLayouts = new WeakMap<ForceSimulation<KnowledgeForceNode>, Knowledge3dRadialLayout>();

/** One recursive branch rule: descendants determine space at each radial layer.
 * Siblings share moving boundaries; outer Articles use local contact spacing.
 * Membership and demand are built once, with the ordinary D3 cooling loop.
 */
function forceKnowledgeBranchSeparation(
  nodes: readonly KnowledgeForceNode[], radial: Knowledge3dRadialLayout,
  velocityDecay: number, chargeStrength: number,
): ((alpha: number) => void) & { initialize: (members: KnowledgeForceNode[], random: () => number, dimensions: number) => void } {
  const byId = new Map(nodes.map(node => [node.id, node]));
  const indexById = new Map(nodes.map((node, index) => [node.id, index]));
  const children = new Map<string, KnowledgeForceNode[]>();
  const members = new Map(nodes.map(node => [node.id, [] as number[]]));
  nodes.forEach((node, index) => {
    if (node.parentId && byId.has(node.parentId)) {
      const siblings = children.get(node.parentId) ?? [];
      siblings.push(node);
      children.set(node.parentId, siblings);
    }
    const seen = new Set<string>();
    let branch: KnowledgeForceNode | undefined = node;
    while (branch && !seen.has(branch.id)) {
      seen.add(branch.id);
      members.get(branch.id)!.push(index);
      branch = branch.parentId ? byId.get(branch.parentId) : undefined;
    }
  });
  const clearance = nodes.map(node => radial.clearances.get(node.id)!);
  const forks = [...children].filter(([, siblings]) => siblings.length > 1)
    .sort(([a], [b]) => (byId.get(b)!.depth ?? 0) - (byId.get(a)!.depth ?? 0))
    .map(([parent, siblings]) => ({
      siblings,
      branches: siblings.some(node => children.has(node.id)) ? siblings.map(node => ({
        index: indexById.get(node.id)!,
        layers: [...radial.footprints.get(node.id)!].map(([layer, footprint]) => ({
          width: Math.sqrt(footprint),
          members: members.get(node.id)!.filter(index => radial.fractions.get(nodes[index].id) === layer),
        })),
      })) : [],
      // One sibling force at every fork. Inherited area gives crowded branches
      // room; terminal siblings distribute evenly within that room.
      charge: forceManyBody().strength((node: KnowledgeForceNode) =>
        -chargeStrength * (members.get(parent)!.length - 1)
          * radial.footprints.get(node.id)!.get(radial.fractions.get(node.id)!)!
          / radial.footprints.get(parent)!.get(radial.fractions.get(node.id)!)!),
    }));
  const retainedVelocity = 1 - velocityDecay;
  const outer = nodes.filter(node => radial.fractions.get(node.id) === 1);
  const neighborDistance = radial.radius * Math.sqrt(8 / Math.max(1, outer.length));
  // Spherical force relaxation: outer Articles repel even when their contact
  // discs no longer touch. The radial constraint removes outward motion and
  // the branch pass below keeps the remaining tangential motion in its branch.
  const surfaceCharge = forceManyBody()
    .strength(-neighborDistance * neighborDistance * 0.3)
    .distanceMin(neighborDistance * 0.5)
    .distanceMax(neighborDistance * 3);
  // Every outer Article gets the same local neighbor-spacing rule. Half of
  // the sphere's area is reserved for these contact discs, leaving room for
  // branch borders. This fills empty patches without fixed angular targets.
  const surfaceSpacing = forceCollide()
    .radius((node: KnowledgeForceNode) => Math.max(radial.clearances.get(node.id)!,
      radial.radius * Math.sqrt(2 / Math.max(1, outer.length))))
    .iterations(COLLIDE_ITERATIONS);
  const force = (alpha: number): void => {
    for (const fork of forks) fork.charge(alpha);
    if (outer.length > 1) surfaceCharge(alpha);
    if (outer.length > 1) surfaceSpacing(alpha);
    const directions = nodes.map(node => {
      const x = (node.x ?? 0) + (node.vx ?? 0) * retainedVelocity;
      const y = (node.y ?? 0) + (node.vy ?? 0) * retainedVelocity;
      const z = (node.z ?? 0) + (node.vz ?? 0) * retainedVelocity;
      const radius = Math.hypot(x, y, z) || 1;
      return [x / radius, y / radius, z / radius, radius];
    });
    const projected = directions.map(direction => direction.slice());
    const clearBoundary = (indices: readonly number[], nx: number, ny: number, nz: number, offset: number): void => {
      for (const index of indices) {
        const [x, y, z, radius] = projected[index];
        const margin = Math.max(-0.98, Math.min(0.98, offset + Math.min(0.2, clearance[index] / radius)));
        const side = Math.max(-1, Math.min(1, x * nx + y * ny + z * nz));
        if (side >= margin) continue;
        const tangentScale = Math.sqrt((1 - margin * margin) / Math.max(1e-8, 1 - side * side));
        projected[index][0] = (x - nx * side) * tangentScale + nx * margin;
        projected[index][1] = (y - ny * side) * tangentScale + ny * margin;
        projected[index][2] = (z - nz * side) * tangentScale + nz * margin;
      }
    };
    // Inner forks settle first; their enclosing branch has the final boundary.
    for (const { branches } of forks) {
      for (let i = 0; i < branches.length; i += 1) {
        for (let j = i + 1; j < branches.length; j += 1) {
          const a = branches[i], b = branches[j];
          const left = directions[a.index], right = directions[b.index];
          const nx = left[0] - right[0], ny = left[1] - right[1], nz = left[2] - right[2];
          const length = Math.hypot(nx, ny, nz);
          if (length < 1e-8) continue;
          // Divide the arc by inherited width, so a crowded branch can use
          // nearby room without entering its smaller neighbor's clearance.
          const angle = 2 * Math.asin(Math.min(1, length / 2));
          for (let layer = 0; layer < a.layers.length; layer += 1) {
            const left = a.layers[layer], right = b.layers[layer];
            // Ended branches reserve no space beyond their last layer.
            if (!left.width || !right.width) continue;
            const offset = Math.sin(angle * (0.5 - left.width / (left.width + right.width)));
            clearBoundary(left.members, nx / length, ny / length, nz / length, offset);
            clearBoundary(right.members, -nx / length, -ny / length, -nz / length, -offset);
          }
        }
      }
    }
    nodes.forEach((node, index) => {
      if (isBallRoot(node)) return;
      const [x, y, z, radius] = projected[index];
      node.vx = (x * radius - (node.x ?? 0)) / retainedVelocity;
      node.vy = (y * radius - (node.y ?? 0)) / retainedVelocity;
      node.vz = (z * radius - (node.z ?? 0)) / retainedVelocity;
    });
  };
  return Object.assign(force, {
    initialize(_members: KnowledgeForceNode[], random: () => number, dimensions: number): void {
      for (const fork of forks) fork.charge.initialize(fork.siblings, random, dimensions);
      surfaceCharge.initialize(outer, random, dimensions);
      surfaceSpacing.initialize(outer, random, dimensions);
    },
  });
}

/** One canonical physical signature for refresh and solver continuity. */
export function knowledge3dPhysicsSignature(
  nodes: readonly KnowledgeForceNode[], links: readonly KnowledgeForceLink[],
  tuning: Knowledge3dTuning,
): string {
  return JSON.stringify([
    tuning.chargeStrength, tuning.velocityDecay, tuning.linkDistance, tuning.branchClearance,
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
): Knowledge3dRadialLayout | undefined {
  return radialLayouts.get(simulation);
}

/** Use the ordinary scene-owned D3 cooling schedule. */
export function knowledge3dSimulationNeedsTick(
  simulation: ForceSimulation<KnowledgeForceNode>,
): boolean {
  return simulation.alpha() > KNOWLEDGE_3D_ALPHA_MIN;
}

/** Build the live simulation: springs, charge, collision, radial hierarchy
 *  with one shared outer radius. Brain is pinned at the origin; the scene
 *  owns the tick cadence. d3-force uses a deterministic internal LCG, so identical
 *  inputs replay identically. */
export function createKnowledgeForceSimulation(
  nodes: KnowledgeForceNode[],
  links: readonly KnowledgeForceLink[],
  tuning: Knowledge3dTuning = DEFAULT_KNOWLEDGE_3D_TUNING,
  dimensions: 2 | 3 = 3,
  minimumRadius = 0,
): ForceSimulation<KnowledgeForceNode> {
  // Physical depth follows exact ancestry, not the 2D terminal paint tier.
  const radial = dimensions === 3 ? knowledge3dRadialLayout(nodes, tuning.branchClearance) : undefined;
  if (radial && minimumRadius > radial.radius) {
    radial.radius = minimumRadius;
    radial.radii = new Map([...radial.fractions].map(([id, fraction]) => [id, fraction * minimumRadius]));
  }
  if (radial) for (const node of nodes) node.depth = radial.depths.get(node.id);
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
            ? radial ? Math.abs(radial.radii.get(link.source.id)! - radial.radii.get(link.target.id)!)
              : knowledge3dLinkDistance(
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
      dimensions === 3 ? null : forceManyBody()
        .strength(-tuning.chargeStrength)
        .distanceMax(knowledge3dLinkRest(tuning) * 3),
    )
    .force(
      "collide",
      forceCollide()
        .radius((node: KnowledgeForceNode) =>
          radial ? radial.clearances.get(node.id)! : knowledge3dAvoidanceRadius(node),
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
  if (radial) {
    simulation.force("branchSeparation", forceKnowledgeBranchSeparation(
      nodes, radial, tuning.velocityDecay, tuning.chargeStrength,
    ));
    simulation.force("dagRadial", forceKnowledgeRadialOut(nodes, radial, tuning.velocityDecay));
    radialLayouts.set(simulation, radial);
  }
  return simulation;
}

/** Legacy Cartesian outward boundary retained for the separate 2D layout.
 * Its elastic shallow correction and hard backstop are unchanged. The 3D
 * factory uses the normalized radialout layout instead. */
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

function isBallRoot(node: {
  role?: KnowledgeHierarchyRole | string;
  depth?: number;
}): boolean {
  return node.role === "root" || (node.depth ?? 3) === 0;
}

/** Stable, unstructured 3D seeds. No pole anchors or geometric branch slots:
 * the force engine and moving sibling boundaries form the tree.
 */
export function knowledge3dBallTargets(
  nodes: readonly Knowledge3dBallNode[],
  hub: { x: number; y: number },
  tuning: Knowledge3dTuning = DEFAULT_KNOWLEDGE_3D_TUNING,
): Float32Array {
  void hub;
  const { radii } = knowledge3dRadialLayout(nodes, tuning.branchClearance);
  const targets = new Float32Array(nodes.length * 3);
  nodes.forEach((node, index) => {
    const radius = radii.get(node.id) ?? 0;
    const z = hash01(node.id, 29) * 2 - 1;
    const angle = hash01(node.id, 31) * Math.PI * 2;
    const circle = Math.sqrt(1 - z * z);
    targets[index * 3] = radius * circle * Math.cos(angle);
    targets[index * 3 + 1] = radius * circle * Math.sin(angle);
    targets[index * 3 + 2] = radius * z;
  });
  return targets;
}

/** The constructor restores normalized branch radii before rendering. */
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

/** Extend a live route without moving its existing timing coordinates.
 * Newly supplied links begin ahead of the current head, even when their
 * freshly normalized route would otherwise fall behind it. */
export function extendKnowledge3dPathSpec(
  previous: Knowledge3dPathSpec | null,
  next: Knowledge3dPathSpec,
  progress: number,
): Knowledge3dPathSpec {
  if (!previous?.edgeSpans.size) return next;
  const starts = [
    ...[...next.edgeSpans].filter(([key]) => !previous.edgeSpans.has(key)).map(([, span]) => span.from),
    ...[...next.nodeArrival].filter(([id]) => !previous.nodeArrival.has(id)).map(([, arrival]) => arrival),
  ];
  // Route-only ancestors are absent from nodeArrival. Recover their arrival
  // from the retained beams so a second extension cannot outrun its junction.
  const reached = new Map(previous.nodeArrival);
  for (const [key, span] of previous.edgeSpans) {
    if (span.meet) continue;
    const [source, target] = key.split("|");
    for (const [id, arrival] of [[source, span.fromSource ? span.from : span.to],
      [target, span.fromSource ? span.to : span.from]] as const) {
      reached.set(id, Math.min(reached.get(id) ?? Infinity, arrival));
    }
  }
  let offset = starts.length ? Math.max(0, progress - Math.min(...starts)) : 0;
  for (const [key, span] of next.edgeSpans) {
    if (previous.edgeSpans.has(key)) continue;
    const [source, target] = key.split("|");
    const origins = span.meet ? [source, target] : [span.fromSource ? source : target];
    for (const id of origins) offset = Math.max(offset, (reached.get(id) ?? 0) - span.from);
  }
  const edgeSpans = new Map([...next.edgeSpans].map(([key, span]) => [key,
    previous.edgeSpans.get(key) ?? { ...span, from: span.from + offset, to: span.to + offset },
  ]));
  const nodeArrival = new Map([...next.nodeArrival].map(([id, arrival]) => [id,
    previous.nodeArrival.get(id) ?? arrival + offset,
  ]));
  return {
    edgeSpans, nodeArrival,
    firstNodeProgress: previous.firstNodeProgress,
    firstArticleProgress: previous.firstArticleProgress,
    maxProgress: Math.max(0, ...[...edgeSpans.values()].map(span => span.to), ...nodeArrival.values()),
  };
}

/** Continuous progress through the real route, including the trailing fill.
 *  Speech changes neither the speed nor the remaining distance. */
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
