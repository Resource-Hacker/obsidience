// Real-time 3D knowledge model (three.js). Owner-directed 2026-07-31: the
// model IS the 2D radial map lifted into 3D space. Node positions are the
// deterministic 2D layout verbatim (plus a bounded per-node depth), and the
// point-sprite shader procedurally replicates the 2D canvas painter — the
// offset highlight gradient disc, dark rim, ring stroke, depth glow, and
// per-node alpha. The scene is a dumb renderer: every color/radius/scale/
// alpha arrives prepared from the backdrop's shared styling helpers.
//
// Consolidation (owner 2026-08-04): the MAIN executive ball is built by the
// SAME createKnowledge3dSatellite cloud implementation as every satellite
// (main: true — raw node ids, no orbit transform, no ballScale shrink).
// This module owns what is genuinely scene-global: the shader sources, the
// camera/orbit/pointer surface, the sweep timeline clock, role nameplates,
// orbit rings, screen-space labels, and the per-frame loop.
import { useEffect, useRef } from "react";
import * as THREE from "three";
import {
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
  createKnowledge3dSatellite,
  satellitePhysicsSignature,
  type Knowledge3dOrbitRing,
  type Knowledge3dRenderEdge,
  type Knowledge3dRenderNode,
  type Knowledge3dSatelliteCloud,
  type Knowledge3dSatelliteDeps,
  type Knowledge3dSatelliteInput,
} from "./knowledge-3d-satellites";

// The render-model types live with the one cloud implementation; re-export
// so the backdrop's import surface is unchanged.
export type {
  Knowledge3dLabelMeta,
  Knowledge3dRenderEdge,
  Knowledge3dRenderNode,
};

export interface Knowledge3dSceneProps {
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
  /** thinking → tendrils reach out; speaking → they arrive and the
   *  articles light up; null → no query path. */
  focusPhase: KnowledgeFocusPhase;
  visible: boolean;
  reducedMotion: boolean;
  /** Startup adapter request and live cadence are independent: adapter
   *  changes require context/application recreation, while animation profile
   *  changes are consumed directly by the frame loop. */
  adapterPreference: GraphicsAdapterPreference;
  animationProfile: GraphicsAnimationProfile;
  hoveredNodeId: string | null;
  labelIds: readonly string[];
  activeLabelNodeIds: ReadonlySet<string>;
  labelMetadata: ReadonlyMap<string, Knowledge3dLabelMeta>;
  /** Live operator tuning from the ambient slider panel. */
  tuning: Knowledge3dTuning;
  /** Satellite knowledge balls — one per has_knowledge subagent, each a
   *  smaller cloud orbiting the main graph with its OWN tuning record
   *  (owner 2026-08-03). Node ids arrive raw; the scene namespaces them
   *  as agent:<id>/<nodeId> in projections and pointer events. */
  satellites?: ReadonlyArray<Knowledge3dSatelliteInput>;
  /** Developer test sweep on ONE satellite (owner 2026-08-03: Test
   *  thinking runs on the SELECTED graph): the scene drives that cloud's
   *  beams/nodes on the same constant-speed timeline law as the main
   *  ball. `key` restarts the run. */
  satelliteSweeps?: ReadonlyArray<{
    agentId: string;
    spec: Knowledge3dPathSpec;
    key: number;
    /** Measured retrieval-derived speed; absent means use the graph slider. */
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
  onHover: (id: string | null) => void;
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

/** Depth prepass for node occlusion (owner 2026-08-03): only the SOLID
 *  orb disc (and the Brain sphere) writes depth — never the soft glow —
 *  so the cross-link streak comets are properly hidden behind nodes no
 *  matter how translucent the node's visible pass renders. */
const POINT_DEPTH_FRAGMENT_SHADER = `
varying vec4 vStyle;
varying float vDiscFrac;
uniform float uArticleStyle;
uniform float uCoreStyle;
uniform float uSubjectStyle;
uniform float uSubnodeStyle;
float roundedBoxDistance(vec2 point, float halfSize, float corner) {
  vec2 q = abs(point) - vec2(halfSize - corner);
  return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - corner;
}
void main() {
  vec2 p = (gl_PointCoord - 0.5) * 2.0 / max(vDiscFrac, 1e-4);
  float variant = vStyle.x < 0.5
    ? uArticleStyle
    : (vStyle.x < 1.2
      ? uSubjectStyle
      : (vStyle.x < 1.5 ? uSubnodeStyle : uCoreStyle));
  bool squareNode = vStyle.x < 1.5 && variant > 3.5;
  float solid = vStyle.x > 1.5 ? 0.9 : 1.0;
  if (squareNode) {
    float corner = variant < 4.5 ? 0.16 : 0.045;
    if (roundedBoxDistance(p, solid * 0.82, corner) > 0.0) discard;
  } else if (length(p) > solid) discard;
  gl_FragColor = vec4(0.0);
}
`;

const POINT_VERTEX_SHADER = `
attribute float aRadius;
attribute float aExtent;
attribute float aGlowScale;
attribute vec3 aCore;
attribute vec3 aDark;
attribute vec4 aRing;
attribute vec4 aGlow;
attribute vec4 aStyle; // (subject, ringScale, ringWidthPx, baseAlpha)
attribute float aFocus;
attribute float aSeed;
attribute float aCurate;
uniform float uPerspective;
uniform float uPulse;
uniform float uTime;
uniform float uGlowScale;
uniform float uModelScale;
varying vec3 vCore;
varying vec3 vDark;
varying vec4 vRing;
varying vec4 vGlow;
varying vec4 vStyle;
varying float vGlowScale;
varying float vDiscFrac;
varying float vRadiusPx;
varying float vFocus;
varying float vTwinkle;
varying float vSeed;
varying float vCurate;
void main() {
  vCore = aCore;
  vDark = aDark;
  vRing = aRing;
  vGlow = aGlow;
  vStyle = aStyle;
  vGlowScale = aGlowScale;
  vFocus = aFocus;
  vSeed = aSeed;
  vCurate = aCurate;
  // Article orbs TWINKLE as RARE, FAST events (owner 2026-08-02, second
  // round: the constant shimmer read as nothing — an individual twinkle
  // must be noticeable during the idle spin). Time is cut into per-node
  // cells (~7-13 s); roughly half the cells fire one short pulse
  // (~0.4-0.6 s rise-and-fall) at a hashed offset, peaking at a hashed
  // 25-75% of the selected brightness; otherwise the orb rests dark.
  float cellLen = 7.0 + aSeed * 6.0;
  float cellTime = uTime / cellLen + aSeed * 17.0;
  float cellHash = fract(
    sin((floor(cellTime) + aSeed * 91.7) * 12.9898) * 43758.5453
  );
  float pulseCenter = 0.2 + cellHash * 0.6;
  float pulseHalf = 0.25 / cellLen;
  float pulse = max(
    0.0,
    1.0 - abs(fract(cellTime) - pulseCenter) / pulseHalf
  );
  pulse = pulse * pulse * (3.0 - 2.0 * pulse);
  vTwinkle =
    step(0.5, cellHash) * pulse * (0.25 + 0.5 * fract(cellHash * 7.31));
  vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
  // 2D parity: active/hovered discs grow ~2.5px, not a multiplicative bloom.
  float swell = 1.0 + aFocus * (0.10 + 0.06 * uPulse);
  float radiusPx = aRadius * uModelScale * swell * uPerspective / max(1.0, -mvPosition.z);
  float size = clamp(radiusPx * aExtent * 2.0, 1.5, 1200.0);
  vRadiusPx = max(radiusPx, 0.75);
  vDiscFrac = (radiusPx * 2.0) / size;
  gl_PointSize = size;
  gl_Position = projectionMatrix * mvPosition;
}
`;

// Procedural replica of the 2D painter's node pass, composited source-over
// exactly like canvas: depth glow, then ring stroke, then the gradient disc.
const POINT_FRAGMENT_SHADER = `
uniform float uTime;
uniform float uGlowScale;
varying vec3 vCore;
varying vec3 vDark;
varying vec4 vRing;
varying vec4 vGlow;
varying vec4 vStyle;
varying float vGlowScale;
varying float vDiscFrac;
varying float vRadiusPx;
varying float vFocus;
varying float vTwinkle;
varying float vSeed;
varying float vCurate;
uniform float uArticleStyle;
uniform float uCoreStyle;
uniform float uSubjectStyle;
uniform float uSubnodeStyle;
uniform float uRingStyle;
float roundedBoxDistance(vec2 point, float halfSize, float corner) {
  vec2 q = abs(point) - vec2(halfSize - corner);
  return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - corner;
}
void main() {
  vec2 p = (gl_PointCoord - 0.5) * 2.0 / max(vDiscFrac, 1e-4);
  float r = length(p);
  float aa = 1.6 / vRadiusPx;
  float nodeVariant = vStyle.x < 0.5
    ? uArticleStyle
    : (vStyle.x < 1.2
      ? uSubjectStyle
      : (vStyle.x < 1.5 ? uSubnodeStyle : uCoreStyle));
  bool squareNode = vStyle.x < 1.5 && nodeVariant > 3.5;
  // Leaves shimmer ambiently via the twinkle floor; a real focus (the
  // thinking sweep, hover) always wins. Subjects never twinkle.
  float boost = vStyle.x > 0.5 ? vFocus : max(vFocus, vTwinkle);
  float effAlpha = mix(vStyle.w, 1.0, boost);
  vec3 acc = vec3(0.0);
  float accA = 0.0;
  if (vStyle.x > 0.5) {
    // Depth glow: gradient from 0.25r (palette glow) to glowScale*r (clear).
    float glowT = clamp((r - 0.25) / max(vGlowScale - 0.25, 1e-3), 0.0, 1.0);
    float glowA = vGlow.a * uGlowScale * (1.0 - glowT);
    acc = vGlow.rgb * glowA;
    accA = glowA;
    // Ring stroke at ringScale*r, ringWidth device pixels wide. The Brain
    // draws NO ring — it is a bare floating ball of light.
    float ringA = 0.0;
    if (vStyle.x < 1.5) {
      float halfW = (vStyle.z * 0.5) / vRadiusPx;
      float ringDistance = squareNode
        ? abs(roundedBoxDistance(p, vStyle.y, nodeVariant < 4.5 ? 0.18 : 0.06))
        : abs(r - vStyle.y);
      ringA = vRing.a * (1.0 - smoothstep(halfW, halfW + aa, ringDistance));
      // Ring style variants (owner 2026-08-03): 0 solid, 1 dashed,
      // 2 double, 3 none. An auto-curated node's ring must stay visible
      // (the marker contract), so its spinning perforation overrides
      // "None" back to a solid base.
      if (uRingStyle > 2.5) {
        ringA = vCurate > 0.5 ? ringA : 0.0;
      } else if (uRingStyle > 1.5) {
        float innerDistance = squareNode
          ? abs(roundedBoxDistance(
              p,
              vStyle.y * 0.78,
              nodeVariant < 4.5 ? 0.14 : 0.045))
          : abs(r - vStyle.y * 0.78);
        float inner = vRing.a *
          (1.0 - smoothstep(halfW, halfW + aa, innerDistance));
        ringA = max(ringA, inner * 0.6);
      } else if (uRingStyle > 0.5 && vCurate < 0.5) {
        float cell = fract(atan(p.y, p.x) * 1.2732395 - vSeed * 37.0);
        float dash = smoothstep(0.0, 0.06, cell) *
          (1.0 - smoothstep(0.62, 0.68, cell));
        ringA *= dash;
      }
      if (vCurate > 0.5) {
        // Auto-curated node: the ring itself is PERFORATED and SPINS
        // (owner 2026-08-03, replacing the orbiting comet) — eight
        // rotating dashes at a 68% duty cycle, ~0.9 rad/s. The dash
        // count must stay an INTEGER: the atan branch cut jumps the
        // angle by 2π = exactly 8 cells, so fract() stays seamless
        // across it. The spin rate is 4125 cells/hour (1.1458333/s) so
        // the hourly uTime wrap lands on a whole cell instead of
        // snapping every curated ring at once. Phase is seed-hashed so
        // a curated fan never spins in lockstep.
        float cell = fract(
          atan(p.y, p.x) * 1.2732395 - uTime * 1.1458333 - vSeed * 37.0);
        float dash = smoothstep(0.0, 0.06, cell) *
          (1.0 - smoothstep(0.62, 0.68, cell));
        ringA *= dash;
      }
    }
    acc = vRing.rgb * ringA + acc * (1.0 - ringA);
    accA = ringA + accA * (1.0 - ringA);
    vec3 disc;
    float discA;
    if (vStyle.x > 1.5) {
      // The core is a translucent plasma BALL, never a flat spiral or a
      // solid disc; uCoreStyle picks the variant (owner 2026-08-03,
      // WeakAuras-style style list). The plasma variants keep the
      // spherical depth falloff + bright see-through core identity; the
      // Data block variant is the sanctioned exception (owner 2026-08-04:
      // the shared library's core is deliberately GEOMETRIC so Library
      // never reads as an agent's plasma ball).
      if (uCoreStyle > 3.5) {
        // Data block: an isometric neon data cube in the node's own
        // tint — hexagon silhouette, three shaded faces meeting at the
        // front corner, scan rows climbing the sides.
        vec2 q = vec2(p.x, -p.y);
        float R = 0.78;
        float apothem = R * 0.8660254;
        float hexDist = max(
          abs(q.x),
          max(
            abs(0.5 * q.x + 0.8660254 * q.y),
            abs(0.5 * q.x - 0.8660254 * q.y)
          )
        );
        float inside = 1.0 - smoothstep(apothem - aa, apothem + aa, hexDist);
        // Face sectors around the front corner (rays at 30/150/270 in
        // y-up space): top face bright, right medium, left dark.
        float s1 = 0.8660254 * q.y - 0.5 * q.x;
        float s2 = 0.8660254 * q.y + 0.5 * q.x;
        bool topFace = s1 > 0.0 && s2 > 0.0;
        float face = topFace ? 0.95 : (q.x < 0.0 ? 0.38 : 0.62);
        face += topFace
          ? 0.05 * sin(uTime * 0.8)
          : 0.09 * (0.5 + 0.5 * sin(q.y * 16.0 - uTime * 2.0));
        // Neon edges: the silhouette plus the three corner rays.
        float lw = max(0.05, aa * 1.5);
        float edge = 1.0 - smoothstep(lw * 0.5, lw, abs(hexDist - apothem));
        vec2 d1 = vec2(0.8660254, 0.5);
        vec2 d2 = vec2(-0.8660254, 0.5);
        vec2 d3 = vec2(0.0, -1.0);
        float t1 = clamp(dot(q, d1), 0.0, R);
        float t2 = clamp(dot(q, d2), 0.0, R);
        float t3 = clamp(dot(q, d3), 0.0, R);
        edge = max(edge, 1.0 - smoothstep(lw * 0.5, lw, length(q - d1 * t1)));
        edge = max(edge, 1.0 - smoothstep(lw * 0.5, lw, length(q - d2 * t2)));
        edge = max(edge, 1.0 - smoothstep(lw * 0.5, lw, length(q - d3 * t3)));
        edge *= 1.0 - smoothstep(apothem + lw, apothem + lw * 2.0, hexDist);
        // Soft halo past the silhouette keeps the additive glow the rest
        // of the scene wears.
        float halo = exp(-max(0.0, hexDist - apothem) * 9.0) *
          (1.0 - inside) * 0.3;
        float faceA = inside * (0.34 + 0.3 * face) * effAlpha;
        float edgeA = edge * (0.85 + 0.15 * boost) * effAlpha;
        float haloA = halo * effAlpha;
        discA = min(1.0, faceA + edgeA + haloA);
        vec3 faceColor = mix(vCore, vec3(1.0), 0.12) * (0.35 + 0.65 * face);
        vec3 edgeColor = mix(vCore, vec3(1.0), 0.7);
        disc = (faceColor * faceA + edgeColor * edgeA +
          mix(vCore, vec3(1.0), 0.4) * haloA) / max(discA, 1e-4);
      } else {
      float depth = sqrt(max(0.0, 1.0 - r * r));
      float plasmaCore = exp(-r * r * 3.0);
      float brightness;
      if (uCoreStyle < 0.5) {
        // Plasma filaments: the classic cellular churn.
        vec2 q = p * 1.6;
        float n1 = sin(q.x * 3.1 + uTime * 1.3) * sin(q.y * 3.7 - uTime * 1.1);
        float n2 = sin((q.x + q.y) * 2.3 - uTime * 1.7) *
          sin((q.x - q.y) * 2.9 + uTime * 1.4);
        float n3 = sin(q.x * 6.3 - uTime * 2.2) * sin(q.y * 5.7 + uTime * 2.6);
        float churn = 0.5 + 0.25 * n1 + 0.15 * n2 + 0.10 * n3;
        brightness = clamp(plasmaCore * 0.9 + churn * depth * 0.95, 0.0, 1.0);
      } else if (uCoreStyle < 1.5) {
        // Calm core: the bare translucent ball, no turbulence.
        brightness = clamp(plasmaCore * 1.05 + depth * 0.5, 0.0, 1.0);
      } else if (uCoreStyle < 2.5) {
        // Vortex: the churn coordinates swirl harder toward the center.
        float ang = (1.0 - r) * 3.2 + uTime * 0.9;
        vec2 q = mat2(cos(ang), -sin(ang), sin(ang), cos(ang)) * p * 1.9;
        float n1 = sin(q.x * 4.1 + uTime * 1.6) * sin(q.y * 4.7 - uTime * 1.2);
        float n2 = sin((q.x + q.y) * 3.1 - uTime * 2.0) *
          sin((q.x - q.y) * 2.7 + uTime * 1.5);
        float churn = 0.52 + 0.3 * n1 + 0.18 * n2;
        brightness = clamp(plasmaCore * 0.85 + churn * depth, 0.0, 1.0);
      } else {
        // Pulsar: calm ball + expanding radial rings (phase snaps once an
        // hour with the uTime wrap, same accepted tradeoff as the churn).
        float wave = 0.5 + 0.5 * sin(r * 14.0 - uTime * 2.4);
        brightness = clamp(
          plasmaCore + depth * 0.35 + wave * wave * depth * 0.55, 0.0, 1.0);
      }
      disc = mix(vec3(0.45, 0.75, 1.0), vec3(1.0), brightness);
      discA = brightness * (1.0 - smoothstep(0.88, 1.02, r)) * effAlpha;
      }
    } else {
      // Subject disc variants per tier (owner 2026-08-03): branch nodes
      // ride uSubjectStyle, deeper sub-branch nodes uSubnodeStyle.
      // 0 Classic disc, 1 Plasma orb, 2 Gem, 3 Hollow. Obsidience adds
      // 4 Rounded square and 5 Data tile for the Library satellite.
      float variant = nodeVariant;
      float t = clamp((length(p - vec2(-0.28, -0.32)) - 0.08) / 0.92, 0.0, 1.0);
      vec3 classic = t < 0.28
        ? mix(vec3(0.941, 0.976, 1.0), vCore, t / 0.28)
        : mix(vCore, vDark, (t - 0.28) / 0.72);
      float edge = 1.0 - smoothstep(1.0 - aa, 1.0 + aa, r);
      if (variant < 0.5) {
        disc = classic;
        discA = edge * effAlpha;
      } else if (variant < 1.5) {
        // Plasma orb: translucent glow ball in the branch tint.
        float halo = exp(-r * r * 1.2);
        disc = mix(vCore, vec3(1.0), halo * 0.55);
        discA = max(halo * 0.85, edge * 0.25) * edge * effAlpha;
      } else if (variant < 2.5) {
        // Gem: the classic disc with a white-hot heart and a faint flare.
        float heart = exp(-r * r * 5.0);
        float flare = (1.0 - smoothstep(0.02, 0.1, min(abs(p.x), abs(p.y))))
          * (1.0 - smoothstep(0.2, 1.0, r)) * 0.3;
        disc = mix(classic, vec3(1.0), clamp(heart + flare, 0.0, 0.85));
        discA = edge * effAlpha;
      } else if (variant < 3.5) {
        // Hollow: the ring carries the node; only a whisper of fill.
        disc = classic;
        discA = edge * 0.14 * effAlpha;
      } else {
        // Library square nodes retain the same palette/depth language while
        // changing the actual sprite silhouette. Rounded square is a filled
        // glass tile; Data tile is a sharper hollow frame with scan rows.
        float corner = variant < 4.5 ? 0.16 : 0.045;
        float boxDistance = roundedBoxDistance(p, 0.82, corner);
        float boxInside = 1.0 - smoothstep(-aa, aa, boxDistance);
        float boxEdge = 1.0 - smoothstep(aa * 0.35, aa * 1.8, abs(boxDistance));
        if (variant < 4.5) {
          float heart = exp(-dot(p, p) * 4.2);
          disc = mix(classic, vec3(1.0), heart * 0.48);
          discA = boxInside * effAlpha;
        } else {
          float rows = smoothstep(0.76, 0.96, abs(sin(p.y * 17.0 - uTime * 1.8)));
          disc = mix(vDark, vCore, 0.5 + rows * 0.35);
          discA = max(boxEdge, boxInside * (0.12 + rows * 0.12)) * effAlpha;
        }
      }
    }
    acc = disc * discA + acc * (1.0 - discA);
    accA = discA + accA * (1.0 - discA);
  } else {
    // Article leaves: uArticleStyle picks the orb variant (owner
    // 2026-08-03, WeakAuras-style style list). 0 Jewel star is the classic
    // halo + white-hot core + four-point flare (owner 2026-08-02, same as
    // the 2D map); 1 Plasma orb drops the flare; 2 Classic disc is the 2D
    // gradient disc + dark rim with no additive halo; 3 Ember is a
    // tighter, warmer plasma. Focus (the thinking sweep) boosts them all.
    if (uArticleStyle > 3.5) {
      float corner = uArticleStyle < 4.5 ? 0.16 : 0.045;
      float boxDistance = roundedBoxDistance(p, 0.78, corner);
      float boxInside = 1.0 - smoothstep(-aa, aa, boxDistance);
      float boxEdge = 1.0 - smoothstep(aa * 0.35, aa * 1.8, abs(boxDistance));
      float halo = exp(-max(0.0, boxDistance) * 5.5) * (1.0 - boxInside);
      if (uArticleStyle < 4.5) {
        float heart = exp(-dot(p, p) * 7.0);
        float flare = (1.0 - smoothstep(0.018, 0.09, min(abs(p.x), abs(p.y))))
          * (1.0 - smoothstep(0.25, 1.2, r));
        float jewelA = clamp(boxInside + halo * 0.52 + flare * 0.45, 0.0, 1.0)
          * effAlpha;
        vec3 jewel = mix(vCore, vec3(1.0), clamp(heart + flare * 0.5, 0.0, 0.88));
        acc = jewel * jewelA;
        accA = jewelA;
      } else {
        float rows = smoothstep(0.78, 0.96, abs(sin(p.y * 18.0 - uTime * 2.0)));
        float pixelA = max(boxEdge, boxInside * (0.48 + rows * 0.22)) * effAlpha;
        acc = mix(vDark, vCore, 0.62 + rows * 0.25) * pixelA;
        accA = pixelA;
      }
    } else if (uArticleStyle > 1.5 && uArticleStyle < 2.5) {
      float t = clamp((length(p - vec2(-0.28, -0.32)) - 0.08) / 0.92, 0.0, 1.0);
      vec3 flat3 = t < 0.28
        ? mix(vec3(0.941, 0.976, 1.0), vCore, t / 0.28)
        : mix(vCore, vDark, (t - 0.28) / 0.72);
      float flatA = (1.0 - smoothstep(1.0 - aa, 1.0 + aa, r)) * effAlpha;
      acc = flat3 * flatA;
      accA = flatA;
    } else {
      bool ember = uArticleStyle > 2.5;
      vec3 haloTint = mix(vCore, vec3(1.0), 0.25);
      float halo = ember
        ? exp(-r * r * 1.7) * (0.38 + boost * 0.55)
        : exp(-r * r * 0.85) * (0.28 + boost * 0.5);
      float coreT = smoothstep(0.0, ember ? 0.42 : 0.62, r);
      vec3 orb = mix(ember ? vec3(1.0, 0.97, 0.9) : vec3(1.0, 1.0, 0.98),
        vCore, coreT);
      float disc = ember
        ? 1.0 - smoothstep(0.55, 0.9, r)
        : 1.0 - smoothstep(0.78, 1.05, r);
      float flare = uArticleStyle < 0.5
        ? (1.0 - smoothstep(0.015, 0.085, min(abs(p.x), abs(p.y))))
          * (1.0 - smoothstep(0.3, 2.6, r)) * (0.35 + boost * 0.4)
        : 0.0;
      float orbA = clamp(disc + halo + flare, 0.0, 1.0) * effAlpha;
      vec3 orbColor =
        (orb * disc + haloTint * (halo + flare) * (1.0 - disc)) /
        max(disc + (halo + flare) * (1.0 - disc), 1e-4);
      acc = orbColor * orbA;
      accA = orbA;
    }
  }
  if (accA <= 0.004) discard;
  vec3 color = acc / max(accA, 1e-4);
  color = mix(color, vec3(1.0), boost * 0.45);
  gl_FragColor = vec4(color, accA);
}
`;

// Links render as screen-space BEAM quads, not GL lines: each segment is
// extruded perpendicular to its screen direction in the vertex shader and
// shaded with a bright core plus a soft glow falloff (additive), so the
// connectors read as light beams. Widths/opacities ride live tuning
// uniforms.
const BEAM_VERTEX_SHADER = `
attribute vec3 aStart;
attribute vec3 aEnd;
attribute float aSide;
attribute float aEnd01;
attribute vec3 aColor;
attribute float aArc;
attribute float aWidth;
attribute float aP;
attribute float aDormant;
attribute float aHover;
uniform vec2 uViewportPx;
uniform float uWidthPx;
uniform float uFloorPx;
uniform float uGlow;
varying vec3 vColor;
varying float vAcross;
varying float vArc;
varying float vP;
varying float vDormant;
varying float vHover;
void main() {
  vP = aP;
  vDormant = aDormant;
  vHover = aHover;
  vec4 clipA = projectionMatrix * modelViewMatrix * vec4(aStart, 1.0);
  vec4 clipB = projectionMatrix * modelViewMatrix * vec4(aEnd, 1.0);
  vec2 pixA = (clipA.xy / max(abs(clipA.w), 1e-4)) * uViewportPx * 0.5;
  vec2 pixB = (clipB.xy / max(abs(clipB.w), 1e-4)) * uViewportPx * 0.5;
  vec2 direction = pixB - pixA;
  float len = max(length(direction), 1e-3);
  direction /= len;
  // aWidth is the depth-taper coordinate: 0 = the top arm at the full
  // width slider, 1 = the article-level arm at its own live width slider
  // (both uniforms, so neither slider needs a geometry rebuild). The
  // completion pulse SWELLS on-path beams to nearly double width (owner
  // 2026-08-02: the whole beam pulses with bloom around it, not just the
  // center line).
  float swell = aP >= 0.0 ? 1.0 + uGlow * 0.9 : 1.0;
  vec2 normalPx = vec2(-direction.y, direction.x) *
    (mix(uWidthPx, uFloorPx, aWidth) * swell * 0.5 * aSide);
  vec4 clip = mix(clipA, clipB, aEnd01);
  clip.xy += (normalPx / (uViewportPx * 0.5)) * clip.w;
  vColor = aColor;
  vAcross = aSide;
  vArc = aArc;
  gl_Position = clip;
}
`;

// Shared active-path timeline (owner 2026-08-02): every beam fragment
// carries its plan-progress coordinate vP (-1 off-path). The BEAM head
// (uBeamP) travels the path first, revealing/brightening the hollow tube;
// the SOLID center line (uSolidP) launches once the head clears the first
// node and fills behind its own comet; when the fill completes the whole
// path pulses NEON (uGlow); then segmented dashes stream one direction
// (uFlowAge) — information flowing — in the beam's own gradient colors.
// On terminal cross-links vP is V-shaped, so both fronts naturally read
// as two comets departing the endpoints and meeting at the middle.
const PATH_TIMELINE_GLSL = `
  float head = 1.0 - smoothstep(0.0, uHeadSpan, uBeamP - vP);
  float alpha = max(uOpacity, 0.55) * band;
  vec3 color = mix(vColor, vec3(1.0), head * 0.6);
  float coreA = 0.0;
  if (uSolidP >= vP) {
    float solidHead = 1.0 - smoothstep(0.0, uHeadSpan, uSolidP - vP);
    coreA = core * (0.85 + solidHead * 0.15);
    color = mix(color, vec3(1.0), core * (0.25 + solidHead * 0.5));
  }
  if (uFlowAge >= 0.0) {
    float dashOn =
      fract(vArc * uDashFreq - uFlowAge * 0.9) <= 0.55 ? 1.0 : 0.0;
    coreA = core * mix(0.25, 0.95, dashOn);
    color = mix(vColor, vec3(1.0), core * dashOn * 0.35);
  }
  // Completion pulse: the vertex shader swells the quad, and the whole
  // widened envelope lights with a soft bloom falloff around the beam
  // (owner 2026-08-02: the full beam pulses, not just the center line).
  color = mix(color, vec3(1.0), uGlow * 0.6);
  float bloom = uGlow * (1.0 - smoothstep(0.0, 1.0, t)) * 0.85;
  float a = min(1.0, (alpha + coreA) * (1.0 + uGlow * 0.6) + bloom);
  gl_FragColor = vec4(color, a);
`;

// Taxonomy beams (Brain spokes, structural arms, article spokes) —
// hollow-beam profile: a flat translucent TUBE with a crisply feathered
// silhouette. Dormant beams paint the tube ONLY (owner 2026-08-02: the
// bright center line is reserved for the thinking animation, so the
// chosen path is unmistakable); invisible-at-rest beams (aDormant 0)
// exist purely for the path timeline.
const TAXONOMY_PATH_FRAGMENT_SHADER = `
uniform float uOpacity;
uniform float uDashFreq;
uniform float uBeamP;
uniform float uSolidP;
uniform float uGlow;
uniform float uFlowAge;
uniform float uHeadSpan;
varying vec3 vColor;
varying float vAcross;
varying float vArc;
varying float vP;
varying float vDormant;
varying float vHover;
void main() {
  float t = abs(vAcross);
  float band = (1.0 - smoothstep(0.88, 1.0, t)) * 0.24;
  float core = 1.0 - smoothstep(0.14, 0.24, t);
  if (vP < 0.0 || uBeamP < vP) {
    // Hover preview (owner 2026-08-02): the hovered node's WHOLE subtree
    // shows its beam links down to the end articles — including the
    // at-rest-invisible Brain spokes and article arms — as tubes with a
    // soft center hint.
    if (vHover > 0.5) {
      gl_FragColor = vec4(
        mix(vColor, vec3(1.0), core * 0.2),
        max(uOpacity, 0.5) * min(1.0, band + core * 0.35)
      );
      return;
    }
    if (vDormant < 0.5) discard;
    gl_FragColor = vec4(vColor, uOpacity * band);
    return;
  }
${PATH_TIMELINE_GLSL}
}
`;

// Article cross-links: gently curved beams in the REVERSED gradient,
// checkered by arc length while dormant; the active path rides the same
// shared timeline as the taxonomy beams.
const CROSS_PATH_FRAGMENT_SHADER = `
uniform float uOpacity;
uniform float uDashFreq;
uniform float uBeamP;
uniform float uSolidP;
uniform float uGlow;
uniform float uFlowAge;
uniform float uHeadSpan;
varying vec3 vColor;
varying float vAcross;
varying float vArc;
varying float vP;
varying float vDormant;
void main() {
  float t = abs(vAcross);
  float band = (1.0 - smoothstep(0.88, 1.0, t)) * 0.24;
  float core = 1.0 - smoothstep(0.14, 0.24, t);
  if (vP < 0.0 || uBeamP < vP) {
    // Dormant: static checkered dashes at the tuned opacity.
    if (fract(vArc * uDashFreq) > 0.55) discard;
    float profile = min(1.0, band + core);
    gl_FragColor =
      vec4(mix(vColor, vec3(1.0), core * 0.2), uOpacity * profile);
    return;
  }
${PATH_TIMELINE_GLSL}
}
`;

// Elongated silver streaks streaming along the cross-link curves: each is
// a thin two-vertex line whose head/tail sample the bezier at t and
// t-STREAK_SPAN in the vertex shader, so the streaming costs zero CPU
// once the ball settles.
const PARTICLE_VERTEX_SHADER = `
attribute vec3 aP0;
attribute vec3 aP1;
attribute vec3 aP2;
attribute float aPhase;
attribute float aSpeed;
attribute float aTip;
uniform float uTime;
uniform float uSpeedScale;
uniform float uStreakSpan;
varying float vTip;
void main() {
  vTip = aTip;
  float head = fract(uTime * aSpeed * uSpeedScale + aPhase);
  float t = max(0.0, head - (1.0 - aTip) * uStreakSpan);
  vec3 a = mix(aP0, aP1, t);
  vec3 b = mix(aP1, aP2, t);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(mix(a, b, t), 1.0);
}
`;

const PARTICLE_FRAGMENT_SHADER = `
varying float vTip;
void main() {
  gl_FragColor = vec4(0.86, 0.93, 1.0, 0.2 + 0.65 * vTip);
}
`;

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

    // The MAIN executive cloud: built by the same createKnowledge3dSatellite
    // implementation as every satellite, flagged main: true (owner
    // 2026-08-04 consolidation — one graph code path for all agents).
    let mainCloud: Knowledge3dSatelliteCloud | null = null;
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
    let tendrilPhase: KnowledgeFocusPhase = null;
    let tendrilPhaseStartedAt = 0;
    let tendrilProgressAtPhaseStart = 0;
    let tendrilProgress = 0;
    let solidProgress = 0;
    let glowStartedAt = -1;

    // Scene-global uniform objects shared into every cloud: the viewport,
    // the perspective/pulse/time trio the point shaders read, and the ONE
    // particle clock every cloud's shooting stars ride.
    const viewportUniform = { value: new THREE.Vector2(1, 1) };
    const uniforms = {
      uPerspective: { value: 1 },
      uPulse: { value: 0 },
      uTime: { value: 0 },
    };
    const sharedParticleTime = { value: 0 };
    // The scene module owns the canonical shader strings; every cloud —
    // main and satellites — receives the same deps object.
    const cloudDeps: Knowledge3dSatelliteDeps = {
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
    const satelliteClouds = new Map<string, Knowledge3dSatelliteCloud>();
    let builtSatellites: ReadonlyArray<Knowledge3dSatelliteInput> | undefined;
    // Role nameplates (owner 2026-08-03): a WoW-style glyph sprite floats
    // over every ball — THREE.Sprite always faces the camera (fixed
    // orientation) and sits on the spin axis, so orbit/spin never skew it.
    const rolePlates = new Map<string, THREE.Sprite>();
    let mainPlate: THREE.Sprite | null = null;
    function createRolePlate(agentId: string): THREE.Sprite {
      const texture = new THREE.CanvasTexture(
        paintKnowledgeRoleIcon(knowledgeRoleForAgent(agentId), 128),
      );
      texture.colorSpace = THREE.SRGBColorSpace;
      const material = new THREE.SpriteMaterial({
        map: texture,
        transparent: true,
        opacity: 0.85,
        depthTest: false,
        depthWrite: false,
      });
      const sprite = new THREE.Sprite(material);
      sprite.renderOrder = 90;
      return sprite;
    }
    function disposeRolePlate(sprite: THREE.Sprite): void {
      sprite.parent?.remove(sprite);
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
        key: number;
        startedAt: number;
        glowStartedAt: number;
        pulseKey: number;
        pulseStartedAt: number;
        /** The cloud object the spec was applied to: a snapshot refetch
         *  rebuilds the cloud (fresh beams start dormant, aP = -1), and
         *  the finished flow ITSELF refetches the assignee — the spec
         *  must re-apply to the NEW object or the lit path and launch
         *  pulse die mid-flash. */
        cloud: Knowledge3dSatelliteCloud;
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
      builtPhysicsSignature = satellitePhysicsSignature(current.tuning);
      // Preserve live positions/velocities by id before tearing down, so a
      // refreshed snapshot reheats in place instead of replaying the drop;
      // a tuning-only rebuild also hands over the OLD tuning so carried
      // positions prescale onto the new shells per depth — geometry
      // sliders respond instantly instead of drifting there.
      const carried = mainCloud?.captureSimNodes();
      const tuningOnlyRebuild =
        mainCloud !== null &&
        mainCloud.builtNodes === nodes &&
        mainCloud.builtEdges === edges;
      const previousTuning = tuningOnlyRebuild
        ? mainCloud?.builtTuning
        : undefined;
      if (mainCloud) {
        mainCloud.dispose(scene);
        mainCloud = null;
      }
      if (!nodes.length || !width || !height) return;
      mainCloud = createKnowledge3dSatellite(
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
        previousTuning,
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
          existing.builtSignature === satellitePhysicsSignature(input.tuning)
        ) {
          continue;
        }
        // Same agent, new build inputs: carry positions/velocities over so
        // a physics-slider drag or refreshed snapshot reheats in place
        // instead of replaying the drop (main-ball parity). A tuning-only
        // rebuild (same nodes/edges) also hands over the OLD tuning so the
        // replacement pre-scales carried positions onto the new shells —
        // geometry sliders respond instantly instead of drifting there.
        const carried = existing?.captureSimNodes();
        const tuningOnlyRebuild =
          existing &&
          existing.builtNodes === input.nodes &&
          existing.builtEdges === input.edges;
        if (existing) existing.dispose(scene);
        if (!input.nodes.length) {
          satelliteClouds.delete(input.agentId);
          continue;
        }
        const cloud = createKnowledge3dSatellite(
          input,
          cloudDeps,
          height,
          pixelRatio,
          carried,
          tuningOnlyRebuild ? existing.builtTuning : undefined,
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

    function pickNearest(clientX: number, clientY: number): string | null {
      const bounds = renderer.domElement.getBoundingClientRect();
      if (!bounds.width || !bounds.height) return null;
      const px = (clientX - bounds.left) / bounds.width;
      const py = (clientY - bounds.top) / bounds.height;
      const projected = projectAll();
      let best: string | null = null;
      let bestDistance = HOVER_RADIUS_PX;
      for (const [id, point] of projected) {
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
      propsRef.current.onHover(pickNearest(event.clientX, event.clientY));
    }

    function onPointerLeave(): void {
      propsRef.current.onHover(null);
    }

    function onWheel(event: WheelEvent): void {
      event.preventDefault();
      orbit.distance = clampKnowledge3dDolly(
        orbit.distance * (event.deltaY > 0 ? 1.08 : 0.92),
        framed,
      );
      orbit.interactingUntil = performance.now() + 1200;
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
    let frameDeadline = 0;
    let lastTick = performance.now();
    const emptyProjection = new Map<string, { x: number; y: number }>();

    function frame(now: number): void {
      if (disposed) return;
      rafId = requestAnimationFrame(frame);
      const current = propsRef.current;
      if (
        !knowledge3dAnimationEnabled({
          visible: current.visible,
          reducedMotion: current.reducedMotion,
        })
      ) {
        lastTick = now;
        return;
      }
      const interacting = now < orbit.interactingUntil;
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
      const interval = knowledge3dFrameIntervalMs({
        focusActive:
          current.focusActive || simActive || lastSweepHot ||
          deliveryComets.size > 0 || (current.deliveries?.length ?? 0) > 0 ||
          current.cameraFocus != null,
        interacting: interacting || lastSweepHeld,
        animationProfile: current.animationProfile,
      });
      const nextDeadline = advanceKnowledge3dFrameDeadline(
        frameDeadline,
        now,
        interval,
      );
      if (nextDeadline === null) return;
      const dt = Math.min(0.2, (now - lastTick) / 1000);
      frameDeadline = nextDeadline;
      lastTick = now;

      // The render model and the host geometry are the only build inputs:
      // a new snapshot layout, a resize, or an aspect change re-targets the
      // spring; identity-stable props cost nothing per frame.
      if (
        current.nodes !== builtNodes ||
        current.edges !== builtEdges ||
        width !== builtWidth ||
        height !== builtHeight ||
        satellitePhysicsSignature(current.tuning) !== builtPhysicsSignature
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
      // uModelScale + screen-px beam widths), dash frequency, streaks,
      // and the settled-curve resync on a Link curve change.
      mainCloud?.applyTuning(tuning, pixelRatio);

      // Tick the live physics while hot, then go dormant: the cooled ball
      // only rotates via the camera transform (zero per-node work).
      mainCloud?.tickIfHot();

      // Satellites: live tuning (visual + orbit knobs update without a
      // rebuild), orbit advance, and their own sim ticks while hot. The
      // orbit rides the UNWRAPPED clock: theta = phase + speed·t, so the
      // shader clock's hourly wrap would teleport every satellite ~165°
      // once an hour (adversarial review 2026-08-03) — JS doubles don't
      // need the fp32 fract() protection the wrap exists for.
      // Main ball's executive nameplate rides the same toggle.
      const platesOn = tuning.rolePlates >= 0.5;
      if (platesOn && !mainPlate) {
        mainPlate = createRolePlate("main");
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
        const top = knowledge3dMaxShell(tuning) + 13;
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
            // transform carries graphScale × ballScale, so the plate's
            // local offset margin and scale divide ballScale back out —
            // the world-space glyph stays keyed to graphScale exactly
            // once, same as before the consolidation.
            const ballScale = Math.max(0.05, input.tuning.ballScale);
            const satTop =
              knowledge3dMaxShell(input.tuning) + 9 / ballScale;
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

      // Path timeline (owner 2026-08-02): the beam head travels the plan
      // first; the solid center line launches once the head clears the
      // first node out of the Brain and fills at the same constant speed;
      // the whole path pulses NEON when the fill completes; then the
      // segmented flow streams start-to-finish — all at the single
      // "Animation speed" rate, with no minimum duration or hold.
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
      const spec = current.pathSpec;
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
      if (current.focusPhase !== tendrilPhase) {
        tendrilPhaseStartedAt = now;
        tendrilProgressAtPhaseStart =
          current.focusPhase === null ? 0 : tendrilProgress;
        tendrilPhase = current.focusPhase;
      }
      if (!spec || tendrilPhase === null || !current.focusActive) {
        tendrilProgress = 0;
        solidProgress = 0;
        glowStartedAt = -1;
        mainCloud?.drivePathTimeline(-1, -1, 0, -1);
      } else {
        // ONE master clock at ONE constant speed (owner 2026-08-02: no
        // minimum duration — timers re-paced the fronts and made the
        // animation visibly wait): the beam front is the master progress
        // capped at the route end; the solid front trails it by exactly
        // the first-node lag and finishes during the tail run-out.
        tendrilProgress = knowledgeSweepProgress3d(
          tendrilPhase,
          now - tendrilPhaseStartedAt,
          tendrilProgressAtPhaseStart,
          tuning.sweepSpeed,
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
        );
      }
      sharedParticleTime.value = shaderTime;
      // Nodes ignite as the SOLID line reaches them (owner 2026-08-02),
      // gated by the focus set so only the active route may light.
      mainCloud?.applyFocusReveal(spec ?? null, solidProgress, {
        active: current.focusActive,
        nodeIds: current.focusNodeIds,
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
      for (const [agentId] of sweepStates) {
        if (!sweeps.some((entry) => entry.agentId === agentId)) {
          satelliteClouds.get(agentId)?.applyPathSpec(null);
          satelliteClouds.get(agentId)?.applyFocusReveal(null, 0);
          sweepStates.delete(agentId);
        }
      }
      for (const sweep of sweeps) {
        const cloud = satelliteClouds.get(sweep.agentId);
        if (!cloud) continue;
        let state = sweepStates.get(sweep.agentId);
        if (!state || state.key !== sweep.key) {
          state = {
            key: sweep.key,
            startedAt: now,
            glowStartedAt: -1,
            pulseKey: sweep.pulseKey ?? 0,
            pulseStartedAt: -1,
            cloud,
          };
          sweepStates.set(sweep.agentId, state);
          cloud.applyPathSpec(sweep.spec);
        } else if (state.cloud !== cloud) {
          // The cloud was rebuilt under a live sweep: re-arm the path on
          // the fresh geometry (the timeline clock keeps running).
          state.cloud = cloud;
          cloud.applyPathSpec(sweep.spec);
        }
        if ((sweep.pulseKey ?? 0) !== state.pulseKey) {
          state.pulseKey = sweep.pulseKey ?? 0;
          state.pulseStartedAt = now;
        }
        const cloudTuning =
          (current.satellites ?? []).find(
            (input) => input.agentId === sweep.agentId,
          )?.tuning ?? tuning;
        const tail = knowledge3dSweepTail(sweep.spec);
        const progress = knowledgeSweepProgress3d(
          "thinking",
          now - state.startedAt,
          0,
          sweep.speed ?? cloudTuning.sweepSpeed,
          sweep.spec.maxProgress,
          tail,
        );
        const solid = progress - sweep.spec.firstNodeProgress;
        if (state.glowStartedAt < 0 && solid >= sweep.spec.maxProgress - 1e-4) {
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
          Math.min(progress, sweep.spec.maxProgress),
          solid > 1e-4 ? Math.min(solid, sweep.spec.maxProgress) : -1,
          glow,
          flowAge,
        );
        cloud.applyFocusReveal(sweep.spec, solid);
        if (flowAge < 0 || state.pulseStartedAt >= 0) {
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
      const labelsNeeded =
        current.labelIds.length > 0 || current.activeLabelNodeIds.size > 0;
      labelLayer.update(
        labelsNeeded ? projectAll() : emptyProjection,
        current.labelIds,
        current.activeLabelNodeIds,
        current.labelMetadata,
        current.focusActive,
        now,
      );
      renderer.clear(true, true, true);
      renderer.render(scene, camera);
      renderer.clearDepth();
      labelLayer.render(renderer);
    }
    rafId = requestAnimationFrame(frame);

    return () => {
      disposed = true;
      cancelAnimationFrame(rafId);
      observer.disconnect();
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

  return (
    <div
      ref={hostRef}
      data-testid="knowledge-3d-scene"
      className="absolute inset-0"
      aria-hidden="true"
    />
  );
}
