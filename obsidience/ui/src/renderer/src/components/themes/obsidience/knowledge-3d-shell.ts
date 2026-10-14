// The Knowledge ball drawn as a layered glass orb: one shell per layer of the
// force layout, each a sheen of fine contour lines and depth-of-field dust.
// Every node rests in a crater of its own layer's shell — wider and deeper
// the larger and better linked the node — and fills it with a seed: an orb of
// slowly turning dust in its branch colour. Each shell has its own solidity;
// by default the one nearest the core is the most solid and the outer ones
// the clearest. The shells follow the actual layout; they add no force nodes,
// picking targets or activity routes, and being pure added light they need no
// sorting or depth test.
import * as THREE from "three";

/** Shared by every glass layer of a cloud. */
export interface Knowledge3dOptics {
  uTime: { value: number };
  uPerspective: { value: number };
  /** Focal plane behind (+) or before (-) the cloud centre, in cloud radii. */
  uFocusSwing: { value: number };
  uPixelRatio: { value: number };
  /** Outer radius in cloud-local units, and the group's render scale. */
  uReach: { value: number };
  uModelScale: { value: number };
}

const OPTICS_GLSL = `
uniform float uFocusSwing;
uniform float uPixelRatio;
uniform float uReach;
uniform float uModelScale;
uniform float uTime;
uniform vec4 uDrops[8];     // bearing; age, 0 as it lands to 1 when spent
uniform vec4 uDropTints[8]; // colour; strength
uniform float uDropSpans[8]; // how far the ring spreads in its life, radians
// Depth past the cloud centre in cloud radii: -1 nearest, +1 farthest.
float knowledgeDepth(vec4 view) {
  return ((modelViewMatrix * vec4(0.0, 0.0, 0.0, 1.0)).z - view.z) / max(uReach * uModelScale, 1e-3);
}
float knowledgeFog(float depth) {
  return exp(-max(0.0, depth + 0.55) * 1.15);
}
// Circle of confusion in canvas pixels.
float knowledgeConfusion(float depth) {
  return min(abs(depth - uFocusSwing) * 4.5, 18.0) * uPixelRatio;
}
// A node drops into its shell like a stone into water: a short train of
// crests spreads across the shell from the node's bearing, in the node's
// colour, fading as it goes. A wide drop crosses the whole layer; a small one
// is the same ripple in miniature. Returns the height of the glass here
// (positive on a crest) and the colour its crests carry.
float rippleWave(vec3 direction, out vec3 tint) {
  float wave = 0.0;
  float weight = 0.0;
  tint = vec3(0.0);
  for (int drop = 0; drop < 8; drop++) {
    float age = uDrops[drop].w;
    if (age >= 1.0) continue;
    // Radians from the node, less how far its ring has spread, in units of
    // a full-size ripple.
    float offset = (acos(clamp(dot(direction, uDrops[drop].xyz), -1.0, 1.0)) - age * uDropSpans[drop])
      * 2.4 / uDropSpans[drop];
    float height = sin(offset * 20.0) * exp(-offset * offset * 14.0)
      * (1.0 - age) * (1.0 - age) * uDropTints[drop].w;
    wave += height;
    tint += uDropTints[drop].rgb * max(height, 0.0);
    weight += max(height, 0.0);
  }
  tint = weight > 0.0 ? tint / weight : vec3(1.0);
  return wave;
}
`;

/** Light added to a premultiplied canvas: alpha follows the brightest channel. */
export const LIGHT_GLSL = `
const vec3 AMBER = vec3(1.0, 0.604, 0.235);
vec4 knowledgeLight(vec3 light) {
  return vec4(light, clamp(max(light.r, max(light.g, light.b)), 0.0, 1.0));
}
`;

export const ADDITIVE = {
  transparent: true, depthTest: false, depthWrite: false,
  blending: THREE.CustomBlending, blendEquation: THREE.AddEquation,
  blendSrc: THREE.OneFactor, blendDst: THREE.OneFactor,
} as const;

const SPHERE_GLSL = `
vec3 sphereDirection(vec2 st) {
  float longitude = (st.x - 0.5) * 6.28318530718;
  float latitude = st.y * 3.14159265359;
  return vec3(sin(latitude) * cos(longitude), cos(latitude), sin(latitude) * sin(longitude));
}
`;

// One pass over a shell's bearings: how far each of its nodes presses the
// glass in. A smooth maximum joins neighbouring craters at a saddle.
// rg: blended branch chroma, b: the sheen's drift, a: crater depth (0 rim, 1 floor).
const SURVEY_FRAGMENT = `
precision highp float;
uniform sampler2D uNodes;
uniform int uCount;
uniform float uSeed;
varying vec2 vUv;
${SPHERE_GLSL}
float hash(vec3 p) {
  p = fract(p * 0.1031);
  p += dot(p, p.zyx + 31.32);
  return fract((p.x + p.y) * p.z);
}
float valueNoise(vec3 p) {
  vec3 i = floor(p);
  vec3 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(
    mix(mix(hash(i), hash(i + vec3(1.0, 0.0, 0.0)), f.x),
      mix(hash(i + vec3(0.0, 1.0, 0.0)), hash(i + vec3(1.0, 1.0, 0.0)), f.x), f.y),
    mix(mix(hash(i + vec3(0.0, 0.0, 1.0)), hash(i + vec3(1.0, 0.0, 1.0)), f.x),
      mix(hash(i + vec3(0.0, 1.0, 1.0)), hash(i + vec3(1.0, 1.0, 1.0)), f.x), f.y),
    f.z);
}
void main() {
  vec3 direction = sphereDirection(vUv);
  float blend = 0.0;
  vec2 chroma = vec2(0.0);
  for (int i = 0; i < uCount; i++) {
    vec4 node = texelFetch(uNodes, ivec2(i, 0), 0);
    vec4 shape = texelFetch(uNodes, ivec2(i, 1), 0);
    float x = acos(clamp(dot(direction, node.xyz), -1.0, 1.0)) / shape.z;
    if (x >= 1.0) continue;
    float k = 1.0 - x * x;
    float weight = exp(14.0 * node.w * k * k) - 1.0;
    blend += weight;
    chroma += weight * shape.xy;
  }
  float depth = log(1.0 + blend) / 14.0;
  // Hand-blown, not machined: the walls of a crater wander a little, and the
  // sheen's levels drift across the glass instead of ruling it.
  depth *= 1.0 + 0.3 * (valueNoise(direction * 9.0) - 0.5);
  vec3 across = direction + uSeed;
  float drift = 0.1 * (valueNoise(across * 2.3) - 0.5) + 0.05 * (valueNoise(across * 5.1) - 0.5)
    + 0.02 * (valueNoise(across * 11.0) - 0.5);
  gl_FragColor = vec4(blend > 0.0 ? chroma / blend : vec2(0.0), drift, depth);
}
`;

// Shared by the glass and its dust: a bearing's place on the cratered shell.
const SHELL_GLSL = `
uniform sampler2D uSurvey;
uniform vec2 uShell; // rim radius, deepest crater, in cloud-local units
// A crest lifts the glass by a twentieth of its radius.
vec3 shellPoint(vec3 direction, float depth, float lift, float wave) {
  return direction * (uShell.x * (1.0 + lift + 0.05 * wave) - uShell.y * depth);
}
`;

// The core's glass hugs the core's disc a few canvas pixels out at any zoom,
// and swells with it while it thinks or speaks.
const CORE_HUG_GLSL = `
uniform vec3 uHug;       // the core's radius, cloud-local; the gap in CSS pixels; the distance setting
uniform float uHugSwell; // the core sprite's own swell
uniform float uPerspective;
float coreHug(vec3 centre, float extraPx) {
  vec4 hub = modelViewMatrix * vec4(centre, 1.0);
  float perUnit = uPerspective * length(modelViewMatrix[0].xyz) / max(1.0, -hub.z);
  return uHug.z * (uHug.x * uHugSwell + uHug.y * uPixelRatio / max(perUnit, 1e-4))
    + extraPx * uPixelRatio / max(perUnit, 1e-4);
}
`;

const GLASS_VERTEX = `
varying vec2 vSt;
varying float vFog;
varying float vEdge;
varying float vWave;
varying vec3 vWaveTint;
${OPTICS_GLSL}
${SPHERE_GLSL}
${SHELL_GLSL}
#ifdef CORE_HUG
${CORE_HUG_GLSL}
#endif
void main() {
  vSt = position.xy;
  vec3 direction = sphereDirection(vSt);
  vWave = rippleWave(direction, vWaveTint);
#ifdef CORE_HUG
  vec4 view = modelViewMatrix * vec4(direction * coreHug(vec3(0.0), 0.0), 1.0);
#else
  vec4 view = modelViewMatrix * vec4(shellPoint(direction, texture2D(uSurvey, vSt).a, 0.0, vWave), 1.0);
#endif
  vFog = knowledgeFog(knowledgeDepth(view));
  // Glass shows at its edge: how nearly this bearing is seen side-on.
  vEdge = 1.0 - abs(dot(normalize(normalMatrix * direction), normalize(view.xyz)));
  gl_Position = projectionMatrix * view;
}
`;

// The sheen: drifting altitude levels one canvas pixel wide at any zoom, drawn
// into rings wherever a crater presses the glass. Where levels fall closer
// than a pixel they resolve to their mean coverage, so the limb glows instead
// of shimmering.
const GLASS_FRAGMENT = `
uniform sampler2D uSurvey;
uniform float uLevels;
uniform float uRings;
uniform float uSolid;
uniform float uGlow;
uniform float uEdge; // how brightly the limb glows where the glass is seen side-on
varying vec2 vSt;
varying float vFog;
varying float vEdge;
varying float vWave;
varying vec3 vWaveTint;
${LIGHT_GLSL}
void main() {
  vec4 field = texture2D(uSurvey, vSt);
  float height = cos(vSt.y * 3.14159265359);
  float level = (0.5 + 0.5 * height + field.b) * uLevels + field.a * uRings;
  float spacing = fwidth(level);
  float line = 1.0 - smoothstep(0.25, 1.2, abs(fract(level - 0.5) - 0.5) / max(spacing, 1e-5));
  line = mix(line, min(spacing, 1.0), smoothstep(0.4, 0.95, spacing));
  float weight = mod(floor(level + 0.5), 5.0) < 0.5 ? 0.5 : 0.2;
  // A ripple's crest lights the glass in the colour of the node that sent it.
  float crest = max(vWave, 0.0);
  vec3 tint = vec3(0.62 + field.r - field.g, 0.62 + field.g, 0.62 - field.r - field.g);
  vec3 color = mix(mix(tint, vec3(0.78, 1.0, 0.94), 0.86), mix(vec3(1.0), vWaveTint, min(1.0, crest * 3.0)),
    min(1.0, crest * 1.35));
  float edge = vEdge * vEdge * vEdge * vEdge * uEdge;
  // A crater glows from its floor in its node's colour. The glow does not
  // thin with the glass, so a clear shell still shows where its nodes rest.
  vec3 glow = mix(tint, vec3(1.0), 0.2) * field.a * field.a * uGlow;
  // A crest shows even on a clear shell.
  gl_FragColor = knowledgeLight((color * (line * weight * (1.0 + 3.0 * crest) + edge) * (uSolid + 0.6 * crest) + glow) * vFog);
}
`;

const DUST_VERTEX = `
attribute vec3 aDirection;
attribute vec4 aRandom; // size, keep, lift, twinkle phase
uniform float uPerspective;
uniform float uGain;
uniform float uTexel;
varying float vAlpha;
varying float vRing;
varying vec3 vColor;
${OPTICS_GLSL}
${LIGHT_GLSL}
${SHELL_GLSL}
void main() {
  float latitude = acos(clamp(aDirection.y, -1.0, 1.0));
  vec2 st = vec2(atan(aDirection.z, aDirection.x) / 6.28318530718 + 0.5, latitude / 3.14159265359);
  vec4 field = texture2D(uSurvey, st);
  // Crater walls catch a low sun from one side.
  float east = (texture2D(uSurvey, st + vec2(uTexel, 0.0)).a - field.a) / max(sin(latitude), 0.05);
  float north = texture2D(uSurvey, st + vec2(0.0, uTexel * 2.0)).a - field.a;
  float shade = 0.22 + 0.78 * max(0.0, dot(
    normalize(vec3(east, 0.012, north)), normalize(vec3(-0.45, 0.8, 0.4))));
  bool haze = aRandom.z > 0.0;
  vec3 waveTint;
  float wave = rippleWave(aDirection, waveTint);
  vec3 local = shellPoint(aDirection, field.a, aRandom.z, wave);
  vec4 view = modelViewMatrix * vec4(local, 1.0);
  gl_Position = projectionMatrix * view;
  float depth = knowledgeDepth(view);
  float confusion = knowledgeConfusion(depth);
  float base = (1.0 + aRandom.x * 1.3) * uPixelRatio;
  float size = base + confusion;
  gl_PointSize = size;
  // Blur spreads light without adding any.
  float energy = base * base / (size * size);
  float twinkle = 0.82 + 0.18 * sin(uTime * (0.7 + aRandom.x * 2.5) + aRandom.w * 61.0);
  // Dust gathers in the craters, around the nodes.
  float light = haze
    ? 0.16 * aRandom.w * smoothstep(0.25, 0.85, field.a)
    : shade * (0.5 + 0.5 * field.a) * (0.55 + 0.45 * aRandom.w);
  float crest = max(wave, 0.0);
  // uGain is set for a ball about 450 canvas pixels in radius; a smaller
  // one carries the same light per area instead of clotting.
  vec4 centre = modelViewMatrix * vec4(0.0, 0.0, 0.0, 1.0);
  float apparent = uReach * uModelScale * uPerspective / max(1.0, -centre.z) / 450.0;
  vAlpha = light * energy * twinkle * knowledgeFog(depth) * (1.0 + 3.0 * crest) * uGain * min(1.0, apparent * apparent);
  // Dust thins away from the craters; a point that is not shown is moved off
  // screen here instead of being rasterised and discarded.
  if (aRandom.y > 0.3 + 0.7 * smoothstep(0.0, 0.6, field.a) || vAlpha < 0.004) gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
  vRing = smoothstep(5.0, 15.0, confusion / uPixelRatio);
  vec3 tint = vec3(0.62 + field.r - field.g, 0.62 + field.g, 0.62 - field.r - field.g);
  vColor = mix(haze ? vec3(0.88, 0.94, 1.0) : mix(tint, vec3(1.0), 0.6),
    mix(vec3(1.0), waveTint, min(1.0, crest * 3.0)), min(1.0, crest * 1.35));
}
`;

// A seed: motes scattered through a ball that fills the node's crater, each
// circling the node's own bearing. Whole turns per hour, so the hourly uTime
// wrap is seamless.
const SEED_VERTEX = `
attribute vec4 aMote;   // place in the unit ball, node slot
attribute vec3 aRandom; // size, phase, turns per hour
uniform sampler2D uNodes;
uniform vec2 uShell;
uniform float uPerspective;
uniform float uGain;
varying float vAlpha;
varying float vRing;
varying vec3 vColor;
${OPTICS_GLSL}
${LIGHT_GLSL}
void main() {
  vec4 node = texelFetch(uNodes, ivec2(int(aMote.w), 0), 0);
  vec4 shape = texelFetch(uNodes, ivec2(int(aMote.w), 1), 0);
  // The orb shows around the node's own icon and stays inside the crater's
  // mouth; along the node's bearing it is no taller than the crater is deep.
  float mouth = shape.z * shape.w;
  float orb = min(max(1.8 * texelFetch(uNodes, ivec2(int(aMote.w), 2), 0).x, 0.55 * mouth), 0.9 * mouth);
  // A consulted or hovered node's seed swells and burns amber, and a seed
  // rides and brightens with any ripple that crosses its node.
  float focus = texelFetch(uNodes, ivec2(int(aMote.w), 2), 0).y;
  vec3 waveTint;
  float wave = rippleWave(node.xyz, waveTint);
  orb *= 1.0 + 0.3 * focus;
  float turn = uTime * aRandom.z * 0.0017453293 + aRandom.y * 6.2831853;
  float along = dot(node.xyz, aMote.xyz);
  vec3 turned = aMote.xyz * cos(turn) + cross(node.xyz, aMote.xyz) * sin(turn)
    + node.xyz * along * (1.0 - cos(turn));
  turned -= node.xyz * along * (1.0 - min(1.0, node.w * uShell.y / max(orb, 1e-4)));
  vec3 local = node.xyz * shape.w * (1.0 + 0.05 * wave) + turned * orb;
  vec4 view = modelViewMatrix * vec4(local, 1.0);
  gl_Position = projectionMatrix * view;
  float depth = knowledgeDepth(view);
  float confusion = knowledgeConfusion(depth);
  float base = (1.0 + aRandom.x * 1.3) * uPixelRatio;
  float size = base + confusion;
  gl_PointSize = size;
  float twinkle = 0.75 + 0.25 * sin(uTime * (0.7 + aRandom.x * 2.5) + aRandom.y * 61.0);
  vec4 centre = modelViewMatrix * vec4(0.0, 0.0, 0.0, 1.0);
  float apparent = uReach * uModelScale * uPerspective / max(1.0, -centre.z) / 450.0;
  // Fading toward the edge of the seed.
  vAlpha = (1.0 - 0.75 * dot(aMote.xyz, aMote.xyz)) * (0.45 + 0.55 * aRandom.y)
    * base * base / (size * size) * twinkle * knowledgeFog(depth)
    * uGain * (1.0 + 2.5 * focus + 2.0 * max(wave, 0.0)) * min(1.0, apparent * apparent);
  vRing = smoothstep(5.0, 15.0, confusion / uPixelRatio);
  vec3 tint = vec3(0.62 + shape.x - shape.y, 0.62 + shape.y, 0.62 - shape.x - shape.y);
  vColor = mix(mix(tint, vec3(1.0), 0.3), mix(AMBER, vec3(1.0), 0.25), focus);
}
`;

// The core's band (owner 2026-10-14): white dust packed between the glass
// hugging the core and the first layout shell, swirling around the core. Each
// mote circles an axis leaning a little from the cloud's own, the inner ones
// faster, at whole turns an hour, so the hourly uTime wrap is seamless.
const CORE_DUST_VERTEX = `
attribute vec4 aMote;   // unit bearing; place across the band, 0 inner to 1 outer
attribute vec4 aRandom; // size, phase, turns per hour, brightness
attribute vec3 aLean;   // how the mote's axis leans from the cloud's
uniform vec3 uCore;     // the core's centre, cloud-local
uniform vec2 uBand;     // the band's outer radius, cloud-local, in y
uniform float uGain;
varying float vAlpha;
varying float vRing;
varying vec3 vColor;
${OPTICS_GLSL}
${LIGHT_GLSL}
${CORE_HUG_GLSL}
void main() {
  vec3 axis = normalize(vec3(0.0, 1.0, 0.0) + aLean);
  float turn = uTime * aRandom.z * 0.0017453293 + aRandom.y * 6.2831853;
  vec3 d = aMote.xyz;
  vec3 turned = d * cos(turn) + cross(axis, d) * sin(turn) + axis * dot(axis, d) * (1.0 - cos(turn));
  // From just outside the core's glass out to the first layout shell.
  float inner = coreHug(uCore, 2.0);
  vec3 local = uCore + turned * mix(inner, max(uBand.y, inner * 1.5), aMote.w);
  vec4 view = modelViewMatrix * vec4(local, 1.0);
  gl_Position = projectionMatrix * view;
  float depth = knowledgeDepth(view);
  float confusion = knowledgeConfusion(depth);
  float base = (1.0 + aRandom.x * 1.3) * uPixelRatio;
  float size = base + confusion;
  gl_PointSize = size;
  float twinkle = 0.78 + 0.22 * sin(uTime * floor(2500.0 + aRandom.y * 5000.0) * 0.0017453293 + aRandom.y * 61.0);
  vec4 centre = modelViewMatrix * vec4(0.0, 0.0, 0.0, 1.0);
  float apparent = uReach * uModelScale * uPerspective / max(1.0, -centre.z) / 450.0;
  // Densest against the core's glass, thinning out toward the first shell.
  float edges = smoothstep(0.0, 0.08, aMote.w) * (1.0 - smoothstep(0.75, 1.0, aMote.w));
  vAlpha = edges * aRandom.w * base * base / (size * size) * twinkle * knowledgeFog(depth)
    * uGain * min(1.0, apparent * apparent);
  if (vAlpha < 0.003) gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
  vRing = smoothstep(5.0, 15.0, confusion / uPixelRatio);
  vColor = vec3(1.0, 0.98, 0.95);
}
`;

// A large blur is a ring, as through a lens.
const BOKEH_FRAGMENT = `
varying float vAlpha;
varying float vRing;
varying vec3 vColor;
${LIGHT_GLSL}
void main() {
  vec2 p = gl_PointCoord * 2.0 - 1.0;
  float r = length(p);
  if (r > 1.0 || vAlpha <= 0.0) discard;
  float disc = 1.0 - smoothstep(0.65, 1.0, r);
  float ring = smoothstep(0.55, 0.86, r) * (1.0 - smoothstep(0.88, 1.0, r));
  gl_FragColor = knowledgeLight(vColor * mix(disc, disc * 0.22 + ring * 1.5, vRing) * vAlpha);
}
`;

/** A ball never carries more shells than this; closer layers share one. */
const MAX_SHELLS = 4;
/** A full ripple crosses most of its shell (radians) in this many seconds. */
const RIPPLE_SPREAD = 2.4;
const RIPPLE_SECONDS = 2.6;
/** The rim stands this far above a shell's nodes, as a fraction of the layer
 *  radius. A crater's floor lies below its node, and its mouth reaches toward
 *  the nearest neighbour, by these [lightest, heaviest] amounts. */
const RIM = 0.05;
/** The core's glass hugs its disc this many CSS pixels out (owner 2026-10-14). */
const CORE_GAP_PX = 5;
const FLOOR = [0.03, 0.11];
const MOUTH = [0.55, 0.85];

/** The Glass tuning group; see Knowledge3dTuning. */
export interface Knowledge3dGlass {
  shellLayer1: number;
  shellLayer2: number;
  shellLayer3: number;
  shellLayer4: number;
  craterDepth: number;
  craterGlow: number;
  seedGlow: number;
  sheenLines: number;
  shellDust: number;
  /** The glass hugging the core, and the white dust swirling between it and
   *  the first layout shell (owner 2026-10-14). */
  coreGlass: number;
  /** The core glass's distance: 1 hugs the core five pixels out. */
  coreGlassDistance: number;
  coreDust: number;
}

export interface Knowledge3dShells {
  /** Glass, dust and seeds for every shell; add them to the cloud's group. */
  layers: readonly THREE.Object3D[];
  applyTuning(glass: Knowledge3dGlass): void;
  /** Each node's highlight (thinking reveal, selection, hover), 0 to 1. */
  setFocus(levels: Float32Array): void;
  /** Send a ripple across a node's shell from where the node rests. By
   *  default it crosses the whole layer; a small one names a shorter spread
   *  (radians) and life (seconds). */
  ripple(node: number, strength: number, spread?: number, seconds?: number): void;
  /** Let the ripples spread. */
  advance(dtSeconds: number): void;
  /** Call after the solver moved its nodes. */
  invalidate(): void;
  /** Resurvey if the layout moved since the last frame. */
  prepare(renderer: THREE.WebGLRenderer): void;
  dispose(): void;
}

export function createKnowledge3dShells(options: {
  /** Live cloud-local node positions, three floats per node. */
  positions: Float32Array;
  /** Each node's layer as a fraction of the outer radius; 0 for the core. */
  layers: Float32Array;
  /** Each node's icon radius in cloud-local units. */
  sizes: Float32Array;
  /** How heavily each node presses its shell: its size and its links. */
  weights: Float32Array;
  /** Branch colour per node, three floats. */
  tints: Float32Array;
  /** 1 for a full-size ball; smaller clouds carry proportionally less. */
  detail: number;
  optics: Knowledge3dOptics;
  /** The core node's index, or -1: it gets its own glass and a band of dust. */
  core?: number;
  /** The Executive's voice level, which swells the core sprite. */
  speech?: { value: number };
}): Knowledge3dShells {
  const { positions, layers, sizes, weights, tints, optics } = options;
  const core = options.core ?? -1;
  const detail = Math.min(1, Math.max(0.25, options.detail));
  const drawn: THREE.Object3D[] = [];
  const show = (visible: boolean) => { for (const layer of drawn) layer.visible = visible; };
  const disposables: Array<{ dispose(): void }> = [];

  // Layers closer than the tolerance share a shell; widen it until few enough.
  const fractions = [...new Set(Array.from(layers).filter((layer) => layer > 0)
    .map((layer) => Math.round(layer * 1000) / 1000))].sort((a, b) => a - b);
  let bands: number[][] = [];
  for (let tolerance = 0.08; ; tolerance += 0.04) {
    bands = [];
    for (const fraction of fractions) {
      const band = bands[bands.length - 1];
      if (band && fraction - band[0] <= tolerance) band.push(fraction);
      else bands.push([fraction]);
    }
    if (bands.length <= MAX_SHELLS) break;
  }

  // The bearing grid the vertex shader wraps onto each dimpled sphere.
  const columns = detail > 0.6 ? 256 : 128, rows = columns / 2;
  const grid = new Float32Array((columns + 1) * (rows + 1) * 3);
  const gridIndex = new Uint32Array(columns * rows * 6);
  for (let row = 0; row <= rows; row++) for (let column = 0; column <= columns; column++) {
    grid.set([column / columns, row / rows, 0], (row * (columns + 1) + column) * 3);
  }
  for (let row = 0; row < rows; row++) for (let column = 0; column < columns; column++) {
    const a = row * (columns + 1) + column, b = a + columns + 1;
    gridIndex.set([a, b, a + 1, a + 1, b, b + 1], (row * columns + column) * 6);
  }
  const glassGeometry = new THREE.BufferGeometry();
  glassGeometry.setAttribute("position", new THREE.BufferAttribute(grid, 3));
  glassGeometry.setIndex(new THREE.BufferAttribute(gridIndex, 1));
  disposables.push(glassGeometry);

  const surveyQuad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2));
  surveyQuad.frustumCulled = false;
  const surveyScene = new THREE.Scene();
  surveyScene.add(surveyQuad);
  const surveyCamera = new THREE.Camera();
  disposables.push(surveyQuad.geometry);

  // Stable random bearings, so a paint refresh keeps each shell's constellation.
  let state = 2077;
  const random = () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
  const dustBudget = 170_000 * Math.max(0.2, detail * detail);
  const area = bands.reduce((sum, band) => sum + band[band.length - 1] ** 2, 0);

  const shells = bands.map((band, order) => {
    const members: number[] = [];
    layers.forEach((layer, index) => {
      const fraction = Math.round(layer * 1000) / 1000;
      if (fraction >= band[0] && fraction <= band[band.length - 1]) members.push(index);
    });
    const count = members.length;
    const reach = band[band.length - 1];
    const width = detail > 0.6 && reach > 0.6 ? 1024 : 512;
    // Row 0: bearing and relative crater depth. Row 1: chroma, mouth, radius.
    // Row 2: icon radius, focus.
    const data = new Float32Array(count * 12);
    const texture = new THREE.DataTexture(data, count, 3, THREE.RGBAFormat, THREE.FloatType);
    texture.minFilter = texture.magFilter = THREE.NearestFilter;
    texture.generateMipmaps = false;
    // Press: 0 for the lightest node on this shell, 1 for the heaviest.
    const press = new Float32Array(count);
    let lightest = Infinity, heaviest = 0;
    for (const node of members) {
      lightest = Math.min(lightest, weights[node]);
      heaviest = Math.max(heaviest, weights[node]);
    }
    members.forEach((node, slot) => {
      const r = tints[node * 3], g = tints[node * 3 + 1], b = tints[node * 3 + 2];
      data[(count + slot) * 4] = (r - b) / 2;
      data[(count + slot) * 4 + 1] = (2 * g - r - b) / 4;
      data[(2 * count + slot) * 4] = sizes[node];
      // Square root: a hub should not flatten every ordinary Article's crater.
      press[slot] = heaviest > lightest ? Math.sqrt((weights[node] - lightest) / (heaviest - lightest)) : 1;
    });
    const surveyMaterial = new THREE.ShaderMaterial({
      uniforms: { uNodes: { value: texture }, uCount: { value: count }, uSeed: { value: order * 7.3 } },
      vertexShader: "varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }",
      fragmentShader: SURVEY_FRAGMENT,
      depthTest: false, depthWrite: false, blending: THREE.NoBlending,
    });
    const survey = { value: null as THREE.Texture | null };
    const shape = { value: new THREE.Vector2(1, 0) };
    const levels = (detail > 0.6 ? 56 : 30) * reach;
    // Eight ripples at a time, all spent to begin with: bearing and age,
    // colour and strength, and how far each spreads.
    const drops = { value: new Float32Array(32) }, dropTints = { value: new Float32Array(32) };
    const dropSpans = { value: new Float32Array(8).fill(1) };
    for (let drop = 0; drop < 8; drop++) drops.value[drop * 4 + 3] = 1;
    const rippling = { uDrops: drops, uDropTints: dropTints, uDropSpans: dropSpans };
    const glassMaterial = new THREE.ShaderMaterial({
      uniforms: {
        ...optics, ...rippling, uSurvey: survey, uShell: shape, uSolid: { value: 1 }, uGlow: { value: 0 },
        uLevels: { value: levels }, uRings: { value: 7 }, uEdge: { value: 0.07 },
      },
      vertexShader: GLASS_VERTEX, fragmentShader: GLASS_FRAGMENT,
      // Added light needs no back-then-front ordering: one draw, both faces.
      side: THREE.DoubleSide, forceSinglePass: true, ...ADDITIVE,
    });
    const glass = new THREE.Mesh(glassGeometry, glassMaterial);
    glass.name = "knowledge-shell-glass";
    glass.frustumCulled = false;
    drawn.push(glass);

    const dustCount = Math.max(1, Math.round(dustBudget * reach * reach / area));
    const directions = new Float32Array(dustCount * 3);
    const randoms = new Float32Array(dustCount * 4);
    for (let i = 0; i < dustCount; i++) {
      const y = random() * 2 - 1, angle = random() * Math.PI * 2, ring = Math.sqrt(1 - y * y);
      directions.set([Math.cos(angle) * ring, y, Math.sin(angle) * ring], i * 3);
      // One in eight floats just off the glass as haze.
      randoms.set([random(), random(), i % 8 === 0 ? -Math.log(1 - random() * 0.98) * 0.03 : 0, random()], i * 4);
    }
    const dustGeometry = new THREE.BufferGeometry();
    dustGeometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(dustCount * 3), 3));
    dustGeometry.setAttribute("aDirection", new THREE.BufferAttribute(directions, 3));
    dustGeometry.setAttribute("aRandom", new THREE.BufferAttribute(randoms, 4));
    const dustMaterial = new THREE.ShaderMaterial({
      uniforms: {
        ...optics, ...rippling, uSurvey: survey, uShell: shape, uTexel: { value: 1 / width }, uGain: { value: 0 },
      },
      vertexShader: DUST_VERTEX, fragmentShader: BOKEH_FRAGMENT, ...ADDITIVE,
    });
    const dust = new THREE.Points(dustGeometry, dustMaterial);
    dust.name = "knowledge-shell-dust";
    dust.frustumCulled = false;
    drawn.push(dust);

    // Seeds: the heavier the node, the more motes its orb carries.
    const moteCounts = Array.from(press, (weight) => Math.round((40 + 110 * weight) * Math.max(0.35, detail)));
    const moteCount = moteCounts.reduce((sum, value) => sum + value, 0);
    const motes = new Float32Array(moteCount * 4);
    const moteRandoms = new Float32Array(moteCount * 3);
    let mote = 0;
    moteCounts.forEach((perNode, slot) => {
      for (let i = 0; i < perNode; i++, mote++) {
        // Weighted outward, so most motes show around the node's icon.
        const y = random() * 2 - 1, angle = random() * Math.PI * 2, ring = Math.sqrt(1 - y * y), radius = Math.sqrt(random());
        motes.set([Math.cos(angle) * ring * radius, y * radius, Math.sin(angle) * ring * radius, slot], mote * 4);
        moteRandoms.set([random(), random(), (random() < 0.5 ? -1 : 1) * Math.round(60 + random() * 240)], mote * 3);
      }
    });
    const seedGeometry = new THREE.BufferGeometry();
    seedGeometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(moteCount * 3), 3));
    seedGeometry.setAttribute("aMote", new THREE.BufferAttribute(motes, 4));
    seedGeometry.setAttribute("aRandom", new THREE.BufferAttribute(moteRandoms, 3));
    const seedMaterial = new THREE.ShaderMaterial({
      uniforms: { ...optics, ...rippling, uNodes: { value: texture }, uShell: shape, uGain: { value: 0 } },
      vertexShader: SEED_VERTEX, fragmentShader: BOKEH_FRAGMENT, ...ADDITIVE,
    });
    const seeds = new THREE.Points(seedGeometry, seedMaterial);
    seeds.name = "knowledge-shell-seeds";
    seeds.frustumCulled = false;
    drawn.push(seeds);
    disposables.push(texture, surveyMaterial, glassMaterial, dustGeometry, dustMaterial, seedGeometry, seedMaterial);
    return { members, press, data, texture, surveyMaterial, survey, shape, width, levels,
      drops: drops.value, dropTints: dropTints.value, dropSpans: dropSpans.value,
      dropSeconds: new Float32Array(8).fill(1), nextDrop: 0,
      glass: glassMaterial.uniforms, dust: dustMaterial.uniforms, seeds: seedMaterial.uniforms,
      // Light per point for full dust at this shell's size.
      dustGain: 0.9 * 170_000 * reach * reach / dustCount,
      target: null as THREE.WebGLRenderTarget | null, floors: new Float32Array(count) };
  });

  // The core's glass hugs it with a visible gap; its band of white dust fills
  // the space out to the first layout shell. Both draw after the node sprites
  // (renderOrder 2) and test depth, so the core hides what lies behind it.
  const coreUniforms = {
    survey: { value: null as THREE.Texture | null },
    shape: { value: new THREE.Vector2(1, 0) },
    centre: { value: new THREE.Vector3() },
    band: { value: new THREE.Vector2(1, 2) },
    hug: { value: new THREE.Vector3(1, CORE_GAP_PX, 1) },
    hugSwell: { value: 1 },
  };
  const speech = options.speech ?? { value: 0 };
  let coreFocus = 0;
  // The core sprite's swell (knowledge-3d-shaders.ts), so the glass keeps its gap.
  const syncHugSwell = () => {
    coreUniforms.hugSwell.value = (1 + coreFocus * 0.13) * (1 + 0.32 * speech.value);
  };
  let coreTarget: THREE.WebGLRenderTarget | null = null;
  let coreSurveyMaterial: THREE.ShaderMaterial | null = null;
  let coreGlass: THREE.Mesh | null = null;
  let coreGlassUniforms: Record<string, { value: unknown }> | null = null;
  let coreDustUniforms: Record<string, { value: unknown }> | null = null;
  let coreDustGain = 0;
  if (core >= 0) {
    // No nodes rest on it: its survey carries only the shells' drift.
    const empty = new THREE.DataTexture(new Float32Array(12), 1, 3, THREE.RGBAFormat, THREE.FloatType);
    empty.needsUpdate = true;
    coreSurveyMaterial = new THREE.ShaderMaterial({
      uniforms: { uNodes: { value: empty }, uCount: { value: 0 }, uSeed: { value: 31.7 } },
      vertexShader: "varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }",
      fragmentShader: SURVEY_FRAGMENT,
      depthTest: false, depthWrite: false, blending: THREE.NoBlending,
    });
    const spent = { value: new Float32Array(32) };
    for (let drop = 0; drop < 8; drop++) spent.value[drop * 4 + 3] = 1;
    const still = { uDrops: spent, uDropTints: { value: new Float32Array(32) }, uDropSpans: { value: new Float32Array(8).fill(1) } };
    const glassMaterial = new THREE.ShaderMaterial({
      uniforms: {
        ...optics, ...still, uSurvey: coreUniforms.survey, uShell: coreUniforms.shape, uSolid: { value: 1 },
        uGlow: { value: 0 }, uLevels: { value: 12 }, uRings: { value: 0 },
        uHug: coreUniforms.hug, uHugSwell: coreUniforms.hugSwell,
        // A brighter limb than a layout shell's, so the small sphere reads as one.
        uEdge: { value: 0.45 },
      },
      defines: { CORE_HUG: 1 },
      vertexShader: GLASS_VERTEX, fragmentShader: GLASS_FRAGMENT,
      side: THREE.DoubleSide, forceSinglePass: true, ...ADDITIVE, depthTest: true,
    });
    coreGlassUniforms = glassMaterial.uniforms;
    coreGlass = new THREE.Mesh(glassGeometry, glassMaterial);
    coreGlass.name = "knowledge-core-glass";
    coreGlass.frustumCulled = false;
    coreGlass.renderOrder = 2;
    drawn.push(coreGlass);

    const moteCount = Math.round(30_000 * Math.max(0.25, detail * detail));
    const motes = new Float32Array(moteCount * 4);
    const moteRandoms = new Float32Array(moteCount * 4);
    const leans = new Float32Array(moteCount * 3);
    for (let i = 0; i < moteCount; i++) {
      const y = random() * 2 - 1, angle = random() * Math.PI * 2, ring = Math.sqrt(1 - y * y);
      // Gathered toward the core's glass, so the band is densest around it.
      const across = Math.pow(random(), 1.6);
      motes.set([Math.cos(angle) * ring, y, Math.sin(angle) * ring, across], i * 4);
      // One way round, the inner dust faster; a few strays the other way.
      const turns = Math.round(40 + 220 * (1 - across) * (1 - across)) * (random() < 0.9 ? 1 : -1);
      moteRandoms.set([random(), random(), turns, 0.35 + 0.65 * random()], i * 4);
      const lean = 0.35 * random(), leanAngle = random() * Math.PI * 2;
      leans.set([Math.cos(leanAngle) * lean, 0, Math.sin(leanAngle) * lean], i * 3);
    }
    const coreDustGeometry = new THREE.BufferGeometry();
    coreDustGeometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(moteCount * 3), 3));
    coreDustGeometry.setAttribute("aMote", new THREE.BufferAttribute(motes, 4));
    coreDustGeometry.setAttribute("aRandom", new THREE.BufferAttribute(moteRandoms, 4));
    coreDustGeometry.setAttribute("aLean", new THREE.BufferAttribute(leans, 3));
    const coreDustMaterial = new THREE.ShaderMaterial({
      uniforms: { ...optics, uCore: coreUniforms.centre, uBand: coreUniforms.band, uGain: { value: 0 },
        uHug: coreUniforms.hug, uHugSwell: coreUniforms.hugSwell },
      vertexShader: CORE_DUST_VERTEX, fragmentShader: BOKEH_FRAGMENT, ...ADDITIVE, depthTest: true,
    });
    coreDustUniforms = coreDustMaterial.uniforms;
    coreDustGain = 30_000 / moteCount;
    const coreDust = new THREE.Points(coreDustGeometry, coreDustMaterial);
    coreDust.name = "knowledge-core-dust";
    coreDust.frustumCulled = false;
    coreDust.renderOrder = 2;
    drawn.push(coreDust);
    disposables.push(empty, coreSurveyMaterial, glassMaterial, coreDustGeometry, coreDustMaterial);
  }

  show(false);
  let dirty = true;
  let craterDepth = 1;
  // A large graph need not resurvey on every solver tick while it settles.
  const cadence = layers.length > 600 ? 4 : 1;
  let skipped = cadence;

  const survey = (): boolean => {
    let outer = 0;
    for (const shell of shells) {
      const { members, press, data, floors } = shell;
      const count = members.length;
      let rim = 0;
      members.forEach((node, slot) => {
        const x = positions[node * 3], y = positions[node * 3 + 1], z = positions[node * 3 + 2];
        const radius = Math.hypot(x, y, z);
        if (radius > 1e-4) data.set([x / radius, y / radius, z / radius], slot * 4);
        data[(count + slot) * 4 + 3] = radius;
        floors[slot] = radius * (1 - (FLOOR[0] + (FLOOR[1] - FLOOR[0]) * press[slot]) * craterDepth);
        rim = Math.max(rim, radius * (1 + RIM * craterDepth));
        outer = Math.max(outer, radius);
      });
      let deepest = 1e-4;
      for (let slot = 0; slot < count; slot++) deepest = Math.max(deepest, rim - floors[slot]);
      for (let slot = 0; slot < count; slot++) {
        // A crater's mouth reaches toward the nearest neighbour on its shell:
        // about halfway for a light node, so each keeps its own and adjacent
        // ones meet at a ridge; further for a heavy one. It always clears the
        // node's own icon.
        let nearest = -1;
        for (let other = 0; other < count; other++) {
          if (other === slot) continue;
          nearest = Math.max(nearest, data[slot * 4] * data[other * 4]
            + data[slot * 4 + 1] * data[other * 4 + 1] + data[slot * 4 + 2] * data[other * 4 + 2]);
        }
        data[slot * 4 + 3] = (rim - floors[slot]) / deepest;
        data[(count + slot) * 4 + 2] = Math.min(0.5, Math.max(0.04,
          2.4 * sizes[members[slot]] / Math.max(data[(count + slot) * 4 + 3], 1e-4),
          Math.acos(Math.max(-1, Math.min(1, nearest))) * (MOUTH[0] + (MOUTH[1] - MOUTH[0]) * press[slot])));
      }
      shell.texture.needsUpdate = true;
      shell.shape.value.set(rim, deepest);
    }
    if (!(outer > 0)) return false;
    optics.uReach.value = outer;
    if (coreGlass && core >= 0) {
      const cx = positions[core * 3], cy = positions[core * 3 + 1], cz = positions[core * 3 + 2];
      coreGlass.position.set(cx, cy, cz);
      coreUniforms.hug.value.x = sizes[core];
      const hug = sizes[core] * 1.3;
      coreUniforms.centre.value.set(cx, cy, cz);
      // Out to just inside the first layout shell's deepest crater floor.
      let first = outer;
      for (const shell of shells.slice(0, 1)) for (const floor of shell.floors) first = Math.min(first, floor);
      coreUniforms.band.value.set(hug, Math.max(hug * 1.6, first * 0.9));
    }
    return true;
  };

  return {
    layers: drawn,
    invalidate() { dirty = true; },
    ripple(node, strength, spread = RIPPLE_SPREAD, seconds = RIPPLE_SECONDS) {
      for (const shell of shells) {
        const slot = shell.members.indexOf(node);
        if (slot < 0) continue;
        const drop = shell.nextDrop;
        shell.nextDrop = (drop + 1) % 8;
        shell.drops.set([shell.data[slot * 4], shell.data[slot * 4 + 1], shell.data[slot * 4 + 2], 0], drop * 4);
        // The node's colour, lifted a little toward white so it reads as light.
        shell.dropTints.set([0.25 + 0.75 * tints[node * 3], 0.25 + 0.75 * tints[node * 3 + 1],
          0.25 + 0.75 * tints[node * 3 + 2], strength], drop * 4);
        shell.dropSpans[drop] = spread;
        shell.dropSeconds[drop] = seconds;
      }
    },
    advance(dtSeconds) {
      syncHugSwell();
      for (const shell of shells) {
        for (let drop = 0; drop < 8; drop++) {
          const age = shell.drops[drop * 4 + 3];
          if (age < 1) shell.drops[drop * 4 + 3] = Math.min(1, age + dtSeconds / shell.dropSeconds[drop]);
        }
      }
    },
    setFocus(levels) {
      if (core >= 0) coreFocus = levels[core];
      for (const shell of shells) {
        const count = shell.members.length;
        shell.members.forEach((node, slot) => { shell.data[(2 * count + slot) * 4 + 1] = levels[node]; });
        shell.texture.needsUpdate = true;
      }
    },
    applyTuning(glass) {
      if (glass.craterDepth !== craterDepth) {
        craterDepth = glass.craterDepth;
        dirty = true;
      }
      const layers = [glass.shellLayer1, glass.shellLayer2, glass.shellLayer3, glass.shellLayer4];
      shells.forEach((shell, order) => {
        const solid = layers[order];
        shell.glass.uSolid.value = solid;
        shell.glass.uLevels.value = shell.levels * glass.sheenLines;
        shell.glass.uRings.value = 7 * glass.sheenLines;
        shell.dust.uGain.value = shell.dustGain * solid * glass.shellDust;
        shell.seeds.uGain.value = 1.1 * glass.seedGlow;
        shell.glass.uGlow.value = 0.16 * glass.craterGlow;
      });
      if (coreGlassUniforms) {
        coreGlassUniforms.uSolid.value = glass.coreGlass;
        coreUniforms.hug.value.z = glass.coreGlassDistance;
        coreGlassUniforms.uLevels.value = 14 * glass.sheenLines;
      }
      if (coreDustUniforms) coreDustUniforms.uGain.value = 0.7 * coreDustGain * glass.coreDust;
    },
    prepare(renderer) {
      if (!dirty || ++skipped < cadence) return;
      skipped = 0;
      dirty = false;
      if (!survey()) { show(false); return; }
      const previous = renderer.getRenderTarget();
      for (const shell of shells) {
        if (!shell.target) {
          shell.target = new THREE.WebGLRenderTarget(shell.width, shell.width / 2, {
            // Half floats resolve every level and filter without an extension.
            type: THREE.HalfFloatType, format: THREE.RGBAFormat,
            minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter,
            wrapS: THREE.RepeatWrapping, wrapT: THREE.ClampToEdgeWrapping,
            depthBuffer: false, generateMipmaps: false,
          });
          shell.survey.value = shell.target.texture;
        }
        surveyQuad.material = shell.surveyMaterial;
        renderer.setRenderTarget(shell.target);
        renderer.render(surveyScene, surveyCamera);
      }
      if (coreSurveyMaterial && !coreTarget) {
        coreTarget = new THREE.WebGLRenderTarget(256, 128, {
          type: THREE.HalfFloatType, format: THREE.RGBAFormat,
          minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter,
          wrapS: THREE.RepeatWrapping, wrapT: THREE.ClampToEdgeWrapping,
          depthBuffer: false, generateMipmaps: false,
        });
        coreUniforms.survey.value = coreTarget.texture;
        surveyQuad.material = coreSurveyMaterial;
        renderer.setRenderTarget(coreTarget);
        renderer.render(surveyScene, surveyCamera);
      }
      renderer.setRenderTarget(previous);
      show(true);
    },
    dispose() {
      for (const shell of shells) shell.target?.dispose();
      coreTarget?.dispose();
      for (const disposable of disposables) disposable.dispose();
    },
  };
}
