// One layer of the Knowledge orb's glass for a memory stream, twisting through
// it. The stream itself is drawn as it always was. The glass follows the
// memories that matter most, the best connected: its centre line is where
// they lie along time, so it winds with the helix the bank settles into, and
// it is as wide as they spread. Those records press craters into it — wider
// and deeper the larger and better linked — and carry a seed of slowly turning
// dust in their own colour; every other record is left as it was. The glass
// follows the records as they are displayed, lens included; it adds no force
// nodes or picking targets, and being pure added light it needs no sorting or
// depth test.
import * as THREE from "three";
import {
  ADDITIVE, BOKEH_FRAGMENT, LIGHT_GLSL, NOISE_GLSL, type Knowledge3dGlass,
} from "@/components/themes/obsidience/knowledge-3d-shell";

/** Slices of the stream's outline along time, at most. */
const PROFILE = 160;
/** Survey texels along time and around the axis. */
const SURVEY = [1024, 256] as const;
/** The smooth maximum that joins neighbouring craters; it fits a half float. */
const SHARPNESS = "8.0";
/** The share of a bank, best connected first, that the glass belongs to. */
const CORE = 0.15;
/** The glass stands this many times as far from its centre line as its
 *  records typically lie, so most of them rest just inside it. */
const WIDTH = 1.35;
/** Sheen lines around the glass. Fives, so the heavier fifth line also meets
 *  itself where the glass closes. */
const LINES = [15];
/** A crater's floor lies this far below the glass by [lightest, heaviest], as
 *  fractions of its radius; a record lying deeper still takes its crater down
 *  with it by at most DEEPER, and one far from the glass presses none. The
 *  mouth reaches this share of the way to a neighbour. */
const FLOOR = [0.02, 0.07];
const DEEPER = 0.1;
const MOUTH = [0.55, 0.85];
/** A crater shows its rings once its mouth is this many canvas pixels wide,
 *  from none to all of them; smaller, they would only cloud the glass. */
const RINGS_FROM = [14, 44];
const DUST_PER_SLEEVE = 20_000;
/** Dust is this dense on screen at most, in points per canvas pixel. */
const DUST_DENSITY = 0.06;
/** A ripple spreads this many of the stream's radii in this many seconds. */
const RIPPLE_REACH = "2.4";
const RIPPLE_SECONDS = 2.6;
/** The glass dims to this while a record is being inspected. */
const INSPECTING = 0.35;
/** A stream is drawn far smaller than the orb, so its sheen is this much
 *  stronger at the same tuning; a sleeve carries far more records than a shell
 *  of the orb, so each crater floor glows this much of the orb's. */
const PRESENCE = 1.25;
const FLOOR_GLOW = 0.35;

const STREAM_GLSL = `
uniform sampler2D uProfile;
uniform vec4 uAxis;    // first slice's x, length, greatest radius, slices in use
uniform vec3 uSleeve;  // this sleeve's share of the outline, greatest radius, deepest crater
uniform float uTime;
uniform float uPixelRatio;
uniform float uZoom;  // canvas pixels per unit at the stream
uniform float uCalm;
uniform vec4 uDrops[8];     // x, angle, unused, age: 0 as it lands to 1 when spent
uniform vec4 uDropTints[8]; // colour; strength
// The stream at a place along time, 0 to 1: this sleeve's radius there, and
// where the stream's centre line lies off the time axis.
vec3 streamAt(float along) {
  vec4 at = texture2D(uProfile, vec2((along * (uAxis.w - 1.0) + 0.5) / ${PROFILE}.0, 0.5));
  return vec3(at.r * uSleeve.x, at.gb);
}
// Depth past the axis in units of the stream's greatest radius: -1 on the
// near wall, +1 on the far one.
float streamDepth(vec4 view, vec3 centre) {
  return ((modelViewMatrix * vec4(centre, 1.0)).z - view.z) / max(uAxis.z, 1e-3);
}
float streamFog(float depth) {
  return exp(-max(0.0, depth + 0.55) * 1.15);
}
// Circle of confusion in canvas pixels; a stream seen small blurs less.
float streamConfusion(float depth) {
  return min(abs(depth) * 4.5, 18.0) * uPixelRatio * clamp(uZoom, 0.25, 1.0);
}
// A touched record drops into its sleeve like a stone into water: a short
// train of crests spreads along and around the sleeve from where the record
// lies, in the record's colour, fading as it goes. Returns the height of the
// glass here (positive on a crest) and the colour its crests carry.
float rippleWave(float x, float angle, float radius, out vec3 tint) {
  float wave = 0.0;
  float weight = 0.0;
  tint = vec3(0.0);
  float spread = ${RIPPLE_REACH} * uAxis.z;
  for (int drop = 0; drop < 8; drop++) {
    float age = uDrops[drop].w;
    if (age >= 1.0) continue;
    float around = abs(mod(angle - uDrops[drop].y + 3.14159265359, 6.28318530718) - 3.14159265359) * radius;
    float offset = (length(vec2(x - uDrops[drop].x, around)) - age * spread) * 2.4 / spread;
    float height = sin(offset * 20.0) * exp(-offset * offset * 14.0)
      * (1.0 - age) * (1.0 - age) * uDropTints[drop].w;
    wave += height;
    tint += uDropTints[drop].rgb * max(height, 0.0);
    weight += max(height, 0.0);
  }
  tint = weight > 0.0 ? tint / weight : vec3(1.0);
  return wave;
}
// A place on the cratered sleeve: along time and around the axis, 0 to 1.
vec3 streamPoint(vec2 st, vec3 at, float depth, float lift, float wave) {
  // Past the stream's last record there is no glass for a ripple to lift.
  float radius = at.x > 0.0 ? max(0.0, at.x * (1.0 + lift) - uSleeve.z * depth + 0.03 * uAxis.z * wave) : 0.0;
  float angle = st.y * 6.28318530718;
  return vec3(uAxis.x + st.x * uAxis.y, at.y + radius * cos(angle), at.z + radius * sin(angle));
}
`;

// One quad per record, drawn twice so a crater across the seam stays whole:
// how far the record presses its sleeve in, summed as a smooth maximum.
const PRESS_VERTEX = `
attribute vec4 aCrater; // along, around, mouth, relative depth
attribute vec4 aShape;  // chroma, sleeve radius at the record, sleeve
uniform float uOrder;
uniform float uSpan;
varying vec2 vOffset;
varying float vDepth;
varying vec2 vChroma;
void main() {
  vec2 reach = vec2(aCrater.z / uSpan, min(0.5, aCrater.z / (6.28318530718 * max(aShape.z, 1e-3))));
  float seam = position.z * (aCrater.y < 0.5 ? 1.0 : -1.0);
  vOffset = position.xy;
  vDepth = aCrater.w;
  vChroma = aShape.xy;
  gl_Position = aShape.w == uOrder && aCrater.w > 0.0
    ? vec4((aCrater.xy + position.xy * reach + vec2(0.0, seam)) * 2.0 - 1.0, 0.0, 1.0)
    : vec4(2.0, 2.0, 2.0, 1.0);
}
`;

const PRESS_FRAGMENT = `
precision highp float;
varying vec2 vOffset;
varying float vDepth;
varying vec2 vChroma;
void main() {
  float k = 1.0 - dot(vOffset, vOffset);
  if (k <= 0.0) discard;
  float weight = exp(${SHARPNESS} * vDepth * k * k) - 1.0;
  gl_FragColor = vec4(weight * vChroma, 0.0, weight);
}
`;

// rg: blended record chroma, b: the sheen's drift, a: crater depth (0 rim, 1 floor).
const RESOLVE_FRAGMENT = `
precision highp float;
uniform sampler2D uPress;
uniform vec3 uPlace; // length and this sleeve's radius, in the stream's greatest radii; seed
varying vec2 vUv;
${NOISE_GLSL}
void main() {
  vec4 press = texture2D(uPress, vUv);
  float blend = min(press.a, 6.0e4);
  float depth = log(1.0 + blend) / ${SHARPNESS};
  float angle = vUv.y * 6.28318530718;
  vec3 place = vec3(vUv.x * uPlace.x, cos(angle) * uPlace.y, sin(angle) * uPlace.y);
  // Hand-blown, not machined: crater walls wander and the sheen drifts.
  depth *= 1.0 + 0.3 * (valueNoise(place * 9.0) - 0.5);
  vec3 across = place + uPlace.z;
  float drift = 0.1 * (valueNoise(across * 2.3) - 0.5) + 0.05 * (valueNoise(across * 5.1) - 0.5)
    + 0.02 * (valueNoise(across * 11.0) - 0.5);
  gl_FragColor = vec4(blend > 0.0 ? press.rg / max(press.a, 1e-6) : vec2(0.0), drift, depth);
}
`;

const GLASS_VERTEX = `
uniform sampler2D uSurvey;
varying vec2 vSt;
varying float vFog;
varying float vEdge;
varying float vWave;
varying vec3 vWaveTint;
varying float vSwell;
${STREAM_GLSL}
void main() {
  vSt = position.xy;
  float angle = vSt.y * 6.28318530718;
  float x = uAxis.x + vSt.x * uAxis.y;
  vec3 at = streamAt(vSt.x);
  float rim = at.x;
  vWave = rippleWave(x, angle, rim, vWaveTint);
  vec4 view = modelViewMatrix * vec4(streamPoint(vSt, at, texture2D(uSurvey, vSt).a, 0.0, vWave), 1.0);
  vFog = streamFog(streamDepth(view, vec3(x, at.yz)));
  // Glass shows at its edge: how nearly this wall is seen side-on.
  vEdge = 1.0 - abs(dot(normalize(normalMatrix * vec3(0.0, cos(angle), sin(angle))), normalize(view.xyz)));
  vSwell = rim / max(uAxis.z, 1e-3);
  gl_Position = projectionMatrix * view;
}
`;

// The sheen: fine lines running with time, one canvas pixel wide at any zoom,
// that bend where the stream swells and close into rings wherever a crater
// presses the glass.
const GLASS_FRAGMENT = `
uniform sampler2D uSurvey;
uniform float uLevels;
uniform float uRings;
uniform float uSolid;
uniform float uGlow;
uniform float uCalm;
varying vec2 vSt;
varying float vFog;
varying float vEdge;
varying float vWave;
varying vec3 vWaveTint;
varying float vSwell;
${LIGHT_GLSL}
void main() {
  vec4 field = texture2D(uSurvey, vSt);
  float level = vSt.y * uLevels + (0.5 * vSwell + field.b) * uLevels * 0.5 + field.a * uRings;
  float spacing = fwidth(level);
  float line = 1.0 - smoothstep(0.25, 1.2, abs(fract(level - 0.5) - 0.5) / max(spacing, 1e-5));
  line = mix(line, min(spacing, 1.0), smoothstep(0.4, 0.95, spacing));
  float weight = mod(floor(level + 0.5), 5.0) < 0.5 ? 0.5 : 0.2;
  float crest = max(vWave, 0.0);
  vec3 tint = vec3(0.62 + field.r - field.g, 0.62 + field.g, 0.62 - field.r - field.g);
  vec3 color = mix(mix(tint, vec3(0.78, 1.0, 0.94), 0.86), mix(vec3(1.0), vWaveTint, min(1.0, crest * 3.0)),
    min(1.0, crest * 1.35));
  float edge = vEdge * vEdge * vEdge * vEdge * 0.07;
  vec3 glow = mix(tint, vec3(1.0), 0.2) * field.a * field.a * uGlow;
  gl_FragColor = knowledgeLight(
    (color * (line * weight * (1.0 + 3.0 * crest) + edge) * (uSolid + 0.6 * crest) + glow) * vFog * uCalm);
}
`;

const DUST_VERTEX = `
attribute vec4 aRandom; // size, keep, lift, twinkle phase
uniform sampler2D uSurvey;
uniform vec2 uTexel;
uniform float uGain;
varying float vAlpha;
varying float vRing;
varying vec3 vColor;
${STREAM_GLSL}
void main() {
  vec2 st = position.xy;
  vec4 field = texture2D(uSurvey, st);
  // Crater walls catch a low sun from one side.
  float east = texture2D(uSurvey, st + vec2(uTexel.x, 0.0)).a - field.a;
  float north = texture2D(uSurvey, st + vec2(0.0, uTexel.y)).a - field.a;
  float shade = 0.22 + 0.78 * max(0.0, dot(
    normalize(vec3(east, 0.012, north)), normalize(vec3(-0.45, 0.8, 0.4))));
  bool haze = aRandom.z > 0.0;
  float x = uAxis.x + st.x * uAxis.y;
  vec3 at = streamAt(st.x);
  float rim = at.x;
  vec3 waveTint;
  float wave = rippleWave(x, st.y * 6.28318530718, rim, waveTint);
  vec4 view = modelViewMatrix * vec4(streamPoint(st, at, field.a, aRandom.z, wave), 1.0);
  gl_Position = projectionMatrix * view;
  float depth = streamDepth(view, vec3(x, at.yz));
  float confusion = streamConfusion(depth);
  float base = (1.0 + aRandom.x * 1.3) * uPixelRatio;
  float size = base + confusion;
  gl_PointSize = size;
  // Blur spreads light without adding any.
  float energy = base * base / (size * size);
  float twinkle = 0.82 + 0.18 * sin(uTime * (0.7 + aRandom.x * 2.5) + aRandom.w * 61.0);
  // Dust gathers in the craters, around the records.
  float light = haze
    ? 0.16 * aRandom.w * smoothstep(0.25, 0.85, field.a)
    : shade * (0.5 + 0.5 * field.a) * (0.55 + 0.45 * aRandom.w);
  float crest = max(wave, 0.0);
  vAlpha = light * energy * twinkle * streamFog(depth) * (1.0 + 3.0 * crest) * uGain * uCalm;
  // Dust lies evenly over the glass, so a narrow stretch carries less of it,
  // and thins away from the craters. A point that is not shown is moved off
  // screen here instead of being rasterised and discarded.
  if (position.z * uSleeve.y > rim || aRandom.y > 0.55 + 0.45 * smoothstep(0.0, 0.6, field.a)
      || vAlpha < 0.004) gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
  vRing = smoothstep(5.0, 15.0, confusion / uPixelRatio);
  vec3 tint = vec3(0.62 + field.r - field.g, 0.62 + field.g, 0.62 - field.r - field.g);
  vColor = mix(haze ? vec3(0.88, 0.94, 1.0) : mix(tint, vec3(1.0), 0.6),
    mix(vec3(1.0), waveTint, min(1.0, crest * 3.0)), min(1.0, crest * 1.35));
}
`;

// A seed: motes scattered through a small ball about the record, each
// circling the line from the axis out through the record. Whole turns per
// hour, so the hourly uTime wrap is seamless.
const SEED_VERTEX = `
attribute vec4 aSeed;   // chroma, orb radius, record
attribute vec3 aRandom; // size, phase, turns per hour
uniform sampler2D uPositions;
uniform float uTextureSize;
uniform float uGain;
varying float vAlpha;
varying float vRing;
varying vec3 vColor;
${STREAM_GLSL}
void main() {
  vec3 record = texture2D(uPositions,
    (vec2(mod(aSeed.w, uTextureSize), floor(aSeed.w / uTextureSize)) + 0.5) / uTextureSize).xyz;
  vec3 centre = vec3(record.x, streamAt((record.x - uAxis.x) / uAxis.y).yz);
  float radius = length(record.yz - centre.yz);
  vec3 outward = radius > 1e-3 ? vec3(0.0, (record.yz - centre.yz) / radius) : vec3(0.0, 1.0, 0.0);
  float turn = uTime * aRandom.z * 0.0017453293 + aRandom.y * 6.2831853;
  vec3 turned = position * cos(turn) + cross(outward, position) * sin(turn)
    + outward * dot(outward, position) * (1.0 - cos(turn));
  vec4 view = modelViewMatrix * vec4(record + turned * aSeed.z, 1.0);
  gl_Position = projectionMatrix * view;
  float depth = streamDepth(view, centre);
  float confusion = streamConfusion(depth);
  float base = (1.0 + aRandom.x * 1.3) * uPixelRatio;
  float size = base + confusion;
  gl_PointSize = size;
  float twinkle = 0.75 + 0.25 * sin(uTime * (0.7 + aRandom.x * 2.5) + aRandom.y * 61.0);
  // Fading toward the edge of the seed. Seen small, a seed is a few pixels
  // across and its motes share them, so each carries less light.
  vAlpha = (1.0 - 0.75 * dot(position, position)) * (0.45 + 0.55 * aRandom.y)
    * base * base / (size * size) * twinkle * streamFog(depth) * uGain * uCalm
    * clamp(uZoom * uZoom, 0.03, 1.0);
  if (vAlpha < 0.004) gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
  vRing = smoothstep(5.0, 15.0, confusion / uPixelRatio);
  vColor = mix(vec3(0.62 + aSeed.x - aSeed.y, 0.62 + aSeed.y, 0.62 - aSeed.x - aSeed.y), vec3(1.0), 0.3);
}
`;

export interface MemoryGlassRecords {
  /** Displayed positions, three floats per record, updated in place. */
  positions: Float32Array;
  /** The same positions as the stream's texture, one texel per record. */
  positionTexture: THREE.DataTexture;
  /** Each record's icon radius. */
  radii: ArrayLike<number>;
  /** How heavily each record presses the glass: its size and its links. */
  weights: Float32Array;
  /** Colour per record, three floats. */
  tints: Float32Array;
  /** How many connections each record has. */
  links: Float32Array;
}

export interface MemoryGlass {
  /** Add beside the stream's own group and keep its rotation the same. */
  group: THREE.Group;
  setRecords(records: MemoryGlassRecords): void;
  applyTuning(glass: Knowledge3dGlass): void;
  /** Call after the records moved. */
  invalidate(): void;
  resize(pixelRatio: number): void;
  /** Send a ripple across a record's sleeve from where the record lies. */
  ripple(record: number): void;
  /** Advance the glass to this frame; `zoom` is canvas pixels per unit at the
   *  stream. True while a ripple or a change of brightness is still under way. */
  advance(time: number, zoom: number, inspecting: boolean): boolean;
  /** Resurvey if the records moved since the last frame. */
  prepare(renderer: THREE.WebGLRenderer): void;
  dispose(): void;
}

export function createMemoryGlass(): MemoryGlass {
  const group = new THREE.Group();
  // Under the stream's own threads and icons.
  group.renderOrder = -1;
  group.visible = false;
  const disposables: Array<{ dispose(): void }> = [];

  const profileData = new Uint16Array(PROFILE * 4);
  const profile = new THREE.DataTexture(profileData, PROFILE, 1, THREE.RGBAFormat, THREE.HalfFloatType);
  profile.minFilter = profile.magFilter = THREE.LinearFilter;
  const shared = {
    uProfile: { value: profile }, uAxis: { value: new THREE.Vector4(0, 1, 1, 2) },
    uTime: { value: 0 }, uPixelRatio: { value: 1 }, uZoom: { value: 1 }, uCalm: { value: 1 },
  };
  disposables.push(profile);

  // The grid the vertex shader wraps onto each sleeve.
  const columns = 384, rows = 128;
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

  // The survey: records press into a scratch target, sleeve by sleeve, and a
  // second pass turns each sum into that sleeve's crater field.
  const target = (filter: THREE.MagnificationTextureFilter) => new THREE.WebGLRenderTarget(SURVEY[0], SURVEY[1], {
    type: THREE.HalfFloatType, format: THREE.RGBAFormat, minFilter: filter, magFilter: filter,
    wrapS: THREE.ClampToEdgeWrapping, wrapT: THREE.RepeatWrapping, depthBuffer: false, generateMipmaps: false,
  });
  const press = target(THREE.NearestFilter);
  const pressGeometry = new THREE.InstancedBufferGeometry();
  pressGeometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array([
    -1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0, -1, -1, 1, 1, -1, 1, 1, 1, 1, -1, 1, 1]), 3));
  pressGeometry.setIndex([0, 1, 2, 0, 2, 3, 4, 5, 6, 4, 6, 7]);
  pressGeometry.instanceCount = 0;
  const pressMaterial = new THREE.ShaderMaterial({
    uniforms: { uOrder: { value: 0 }, uSpan: { value: 1 } },
    vertexShader: PRESS_VERTEX, fragmentShader: PRESS_FRAGMENT, ...ADDITIVE,
  });
  const pressMesh = new THREE.Mesh(pressGeometry, pressMaterial);
  pressMesh.frustumCulled = false;
  const pressScene = new THREE.Scene();
  pressScene.add(pressMesh);
  const resolveMaterial = new THREE.ShaderMaterial({
    uniforms: { uPress: { value: press.texture }, uPlace: { value: new THREE.Vector3() } },
    vertexShader: "varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }",
    fragmentShader: RESOLVE_FRAGMENT, depthTest: false, depthWrite: false, blending: THREE.NoBlending,
  });
  const resolveQuad = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), resolveMaterial);
  resolveQuad.frustumCulled = false;
  const resolveScene = new THREE.Scene();
  resolveScene.add(resolveQuad);
  const surveyCamera = new THREE.Camera();
  disposables.push(press, pressGeometry, pressMaterial, resolveQuad.geometry, resolveMaterial);

  // Stable randoms, so a refresh keeps each sleeve's constellation.
  let state = 2077;
  const random = () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };

  const sleeves = LINES.map((lines) => {
    const survey = target(THREE.LinearFilter);
    const drops = { value: new Float32Array(32) }, dropTints = { value: new Float32Array(32) };
    for (let drop = 0; drop < 8; drop++) drops.value[drop * 4 + 3] = 1;
    const uniforms = {
      ...shared, uDrops: drops, uDropTints: dropTints, uSurvey: { value: survey.texture },
      uSleeve: { value: new THREE.Vector3(1, 1, 0) },
    };
    const glassMaterial = new THREE.ShaderMaterial({
      uniforms: { ...uniforms, uSolid: { value: 1 }, uGlow: { value: 0 }, uLevels: { value: lines }, uRings: { value: 7 } },
      vertexShader: GLASS_VERTEX, fragmentShader: GLASS_FRAGMENT,
      // Added light needs no back-then-front ordering: one draw, both faces.
      side: THREE.DoubleSide, forceSinglePass: true, ...ADDITIVE,
    });
    const glass = new THREE.Mesh(glassGeometry, glassMaterial);
    glass.frustumCulled = false;

    const places = new Float32Array(DUST_PER_SLEEVE * 3);
    const randoms = new Float32Array(DUST_PER_SLEEVE * 4);
    for (let i = 0; i < DUST_PER_SLEEVE; i++) {
      // Along, around, and the share of the greatest radius it needs to show.
      places.set([random(), random(), random()], i * 3);
      // One in eight floats just off the glass as haze.
      randoms.set([random(), random(), i % 8 === 0 ? -Math.log(1 - random() * 0.98) * 0.03 : 0, random()], i * 4);
    }
    const dustGeometry = new THREE.BufferGeometry();
    dustGeometry.setAttribute("position", new THREE.BufferAttribute(places, 3));
    dustGeometry.setAttribute("aRandom", new THREE.BufferAttribute(randoms, 4));
    const dustMaterial = new THREE.ShaderMaterial({
      uniforms: { ...uniforms, uTexel: { value: new THREE.Vector2(1 / SURVEY[0], 1 / SURVEY[1]) }, uGain: { value: 0 } },
      vertexShader: DUST_VERTEX, fragmentShader: BOKEH_FRAGMENT, ...ADDITIVE,
    });
    const dust = new THREE.Points(dustGeometry, dustMaterial);
    dust.frustumCulled = false;
    dust.renderOrder = 1;
    group.add(glass, dust);
    disposables.push(survey, glassMaterial, dustGeometry, dustMaterial);
    return { survey, lines, glass, dust, shape: uniforms.uSleeve.value, drops: drops.value, dropTints: dropTints.value,
      nextDrop: 0, glassUniforms: glassMaterial.uniforms, dustUniforms: dustMaterial.uniforms,
      // Dust per unit of this sleeve's surface, and its light at full strength.
      density: 0, dustGain: 0,
      // How far apart its records lie, and its crater rings at full size.
      spacing: 0, rings: 7 };
  });

  const seedMaterial = new THREE.ShaderMaterial({
    uniforms: {
      ...shared, uSleeve: { value: new THREE.Vector3(1, 1, 0) },
      uDrops: { value: new Float32Array(32) }, uDropTints: { value: new Float32Array(32) },
      uPositions: { value: null as THREE.Texture | null }, uTextureSize: { value: 1 }, uGain: { value: 0 },
    },
    vertexShader: SEED_VERTEX, fragmentShader: BOKEH_FRAGMENT, ...ADDITIVE,
  });
  let seeds: THREE.Points | null = null;
  disposables.push(seedMaterial);

  let records: MemoryGlassRecords | null = null;
  let count = 0;
  let craters = new Float32Array(0), shapes = new Float32Array(0);
  let presses = new Float32Array(0), pulls = new Float32Array(0);
  let core = new Uint8Array(0), cored = 1;
  const raw = new Float32Array(PROFILE), rim = new Float32Array(PROFILE), scratch = new Float32Array(PROFILE);
  const tally = new Float32Array(PROFILE), centreY = new Float32Array(PROFILE), centreZ = new Float32Array(PROFILE);
  // The slices of the last survey, for placing a ripple about the centre line.
  let frame = { start: 0, slice: 1, slices: 2 };
  let dirty = true;
  let craterDepth = 1;
  let calm = 1;
  let lastFrame = 0;

  const survey = (): boolean => {
    if (!records || !count) return false;
    const { positions, radii } = records;
    let first = Infinity, last = -Infinity;
    for (let i = 0; i < count; i++) {
      first = Math.min(first, positions[i * 3]);
      last = Math.max(last, positions[i * 3]);
    }
    const slice = Math.max(6, (last - first) / 110);
    const window = 2;
    const start = first - (2 * window + 1) * slice;
    const slices = Math.min(PROFILE, Math.ceil((last - first) / slice) + 4 * window + 3);
    const span = (slices - 1) * slice;
    // The glass's centre line: where the well connected lie near each slice,
    // each record counted by its pull, eased so the glass twists smoothly with
    // the helix the bank settles into.
    raw.fill(0); scratch.fill(0); tally.fill(0);
    let from = slices, to = -1;
    for (let i = 0; i < count; i++) {
      const at = Math.round((positions[i * 3] - start) / slice);
      raw[at] += pulls[i] * positions[i * 3 + 1]; scratch[at] += pulls[i] * positions[i * 3 + 2]; tally[at] += pulls[i];
      from = Math.min(from, at); to = Math.max(to, at);
    }
    let up = NaN, out = NaN;
    for (let at = 0; at < slices; at++) {
      let y = 0, z = 0, near = 0;
      for (let other = Math.max(0, at - window); other <= Math.min(slices - 1, at + window); other++) {
        const share = 1 - Math.abs(other - at) / (window + 1);
        y += raw[other] * share; z += scratch[other] * share; near += tally[other] * share;
      }
      if (near > 0) { up = y / near; out = z / near; }
      centreY[at] = up; centreZ[at] = out;
    }
    // Before the first record the centre line lies where it first appears.
    for (let at = slices - 1; at >= 0; at--) {
      if (Number.isNaN(centreY[at])) { centreY[at] = up; centreZ[at] = out; } else { up = centreY[at]; out = centreZ[at]; }
    }
    const ease = (values: Float32Array, open: boolean, passes: number) => {
      for (let pass = 0; pass < passes; pass++) {
        scratch.set(values);
        for (let at = 0; at < slices; at++) {
          // An open end falls to nothing; a closed one holds its own value.
          const before = at ? scratch[at - 1] : open ? 0 : scratch[at];
          const after = at < slices - 1 ? scratch[at + 1] : open ? 0 : scratch[at];
          values[at] = (before + 2 * scratch[at] + after) / 4;
        }
      }
    };
    ease(centreY, false, 5); ease(centreZ, false, 5);
    const centred = (values: Float32Array, x: number) => {
      const along = (x - start) / slice, at = Math.min(slices - 2, Math.max(0, Math.floor(along)));
      return values[at] + (values[at + 1] - values[at]) * (along - at);
    };
    frame = { start, slice, slices };
    // Its radius: how far from that line the well connected typically lie,
    // and a little more, closing past the first and last record.
    raw.fill(0);
    for (let i = 0; i < count; i++) {
      const x = positions[i * 3], at = Math.round((x - start) / slice);
      raw[at] += pulls[i] * ((positions[i * 3 + 1] - centred(centreY, x)) ** 2 + (positions[i * 3 + 2] - centred(centreZ, x)) ** 2);
    }
    const outline = rim.subarray(0, PROFILE);
    let held = 0;
    for (let at = 0; at < slices; at++) {
      let spread = 0, near = 0;
      for (let other = Math.max(0, at - window); other <= Math.min(slices - 1, at + window); other++) {
        const share = 1 - Math.abs(other - at) / (window + 1);
        spread += raw[other] * share; near += tally[other] * share;
      }
      if (near > 0) held = WIDTH * Math.sqrt(spread / near) + 6;
      outline[at] = at >= from - 1 && at <= to + 1 ? held : 0;
    }
    ease(outline, true, 3);
    let greatest = 0, mean = 0, occupied = 0;
    profileData.fill(0);
    for (let at = 0; at < slices; at++) {
      if (outline[at] > 0) { greatest = Math.max(greatest, outline[at]); mean += outline[at]; occupied += 1; }
      profileData.set([THREE.DataUtils.toHalfFloat(outline[at]), THREE.DataUtils.toHalfFloat(centreY[at]),
        THREE.DataUtils.toHalfFloat(centreZ[at])], at * 4);
    }
    if (!(greatest > 0)) return false;
    mean /= occupied;
    profile.needsUpdate = true;
    shared.uAxis.value.set(start, span, greatest, slices);
    const [sleeve] = sleeves;
    const area = occupied * slice * Math.PI * 2 * mean;
    // How far apart the glass's records lie, were they spread evenly over it.
    sleeve.spacing = Math.sqrt(area / cored);
    // Dust shows in proportion to the glass's radius where it lies.
    sleeve.density = DUST_PER_SLEEVE * (occupied / slices) * (mean / greatest) / area;

    // One of its records presses the glass where it lies near it: fully just
    // inside, less the farther it is from it, and deeper for a heavier one.
    let deepest = 1e-4;
    for (let i = 0; i < count; i++) {
      craters[i * 4 + 3] = 0;
      if (!core[i]) continue;
      const x = positions[i * 3];
      const y = positions[i * 3 + 1] - centred(centreY, x), z = positions[i * 3 + 2] - centred(centreZ, x);
      const reach = centred(outline, x);
      const under = reach - Math.hypot(y, z);
      const away = Math.min(1, Math.max(0, (Math.abs(under) / Math.max(reach, 1e-3) - 0.35) / 0.55));
      const depth = (Math.min(Math.max(0, under), DEEPER * reach)
        + (FLOOR[0] + (FLOOR[1] - FLOOR[0]) * presses[i]) * reach * craterDepth) * (1 - away * away * (3 - 2 * away));
      craters.set([(x - start) / span, (Math.atan2(z, y) / (Math.PI * 2) + 1) % 1,
        // The mouth always clears the record's own icon.
        Math.max(2.4 * radii[i], (MOUTH[0] + (MOUTH[1] - MOUTH[0]) * presses[i]) * sleeve.spacing), depth], i * 4);
      shapes[i * 4 + 2] = reach;
      deepest = Math.max(deepest, depth);
    }
    for (let i = 0; i < count; i++) craters[i * 4 + 3] /= deepest;
    (pressGeometry.getAttribute("aCrater") as THREE.BufferAttribute).needsUpdate = true;
    (pressGeometry.getAttribute("aShape") as THREE.BufferAttribute).needsUpdate = true;
    pressMaterial.uniforms.uSpan.value = span;
    sleeve.shape.set(1, greatest, deepest);
    seedMaterial.uniforms.uSleeve.value.set(1, greatest, 0);
    return true;
  };

  return {
    group,
    setRecords(next) {
      records = next;
      count = next.weights.length;
      craters = new Float32Array(count * 4);
      shapes = new Float32Array(count * 4);
      presses = new Float32Array(count);
      // The glass belongs to the best connected records, and each record draws
      // its centre line by how connected it is beside the bank's great hubs.
      const ranked = [...next.links.keys()].sort((a, b) => next.links[b] - next.links[a] || a - b);
      cored = Math.max(1, Math.round(CORE * count));
      core = new Uint8Array(count);
      for (let rank = 0; rank < cored && rank < count; rank++) core[ranked[rank]] = 1;
      const hub = Math.max(1, next.links[ranked[Math.floor(count * 0.005)] ?? 0] ?? 1);
      pulls = Float32Array.from(next.links, (links) => 0.02 + Math.pow(Math.min(1, links / hub), 1.5));
      let lightest = Infinity, heaviest = 0;
      for (let i = 0; i < count; i++) {
        lightest = Math.min(lightest, next.weights[i]);
        heaviest = Math.max(heaviest, next.weights[i]);
      }
      // Motes per seed: the heavier the record, the fuller its orb.
      const motes: number[] = [], seedData: number[] = [], seedRandoms: number[] = [];
      for (let i = 0; i < count; i++) {
        // Square root: one hub should not flatten every ordinary record's crater.
        presses[i] = heaviest > lightest ? Math.sqrt((next.weights[i] - lightest) / (heaviest - lightest)) : 1;
        const r = next.tints[i * 3], g = next.tints[i * 3 + 1], b = next.tints[i * 3 + 2];
        shapes[i * 4] = (r - b) / 2;
        shapes[i * 4 + 1] = (2 * g - r - b) / 4;
        if (!core[i]) continue;
        for (let mote = Math.round(8 + 16 * presses[i]); mote > 0; mote--) {
          const y = random() * 2 - 1, angle = random() * Math.PI * 2, ring = Math.sqrt(1 - y * y), radius = Math.sqrt(random());
          motes.push(Math.cos(angle) * ring * radius, y * radius, Math.sin(angle) * ring * radius);
          seedData.push(shapes[i * 4], shapes[i * 4 + 1], next.radii[i] * (1.6 + 1.4 * presses[i]), i);
          seedRandoms.push(random(), random(), (random() < 0.5 ? -1 : 1) * Math.round(60 + random() * 240));
        }
      }
      // A geometry's attributes cannot change size once drawn.
      pressGeometry.dispose();
      for (const [name, array] of [["aCrater", craters], ["aShape", shapes]] as const) {
        const attribute = new THREE.InstancedBufferAttribute(array, 4);
        attribute.setUsage(THREE.DynamicDrawUsage);
        pressGeometry.setAttribute(name, attribute);
      }
      pressGeometry.instanceCount = count;
      if (seeds) { group.remove(seeds); seeds.geometry.dispose(); }
      const seedGeometry = new THREE.BufferGeometry();
      seedGeometry.setAttribute("position", new THREE.Float32BufferAttribute(motes, 3));
      seedGeometry.setAttribute("aSeed", new THREE.Float32BufferAttribute(seedData, 4));
      seedGeometry.setAttribute("aRandom", new THREE.Float32BufferAttribute(seedRandoms, 3));
      seeds = new THREE.Points(seedGeometry, seedMaterial);
      seeds.frustumCulled = false;
      seeds.renderOrder = 2;
      group.add(seeds);
      seedMaterial.uniforms.uPositions.value = next.positionTexture;
      seedMaterial.uniforms.uTextureSize.value = next.positionTexture.image.width;
      dirty = true;
    },
    applyTuning(glass) {
      if (glass.craterDepth !== craterDepth) {
        craterDepth = glass.craterDepth;
        dirty = true;
      }
      const solids = [glass.shellLayer1];
      sleeves.forEach((sleeve, order) => {
        sleeve.glassUniforms.uSolid.value = solids[order] * PRESENCE;
        // Whole fives, so the lines and the heavier fifth one meet where the
        // sleeve closes on itself.
        sleeve.glassUniforms.uLevels.value = Math.max(5, Math.round(sleeve.lines * glass.sheenLines / 5) * 5);
        sleeve.rings = 7 * glass.sheenLines;
        sleeve.glassUniforms.uGlow.value = 0.16 * glass.craterGlow * FLOOR_GLOW;
        sleeve.dustGain = 0.9 * solids[order] * glass.shellDust;
      });
      seedMaterial.uniforms.uGain.value = 1.1 * glass.seedGlow;
    },
    invalidate() { dirty = true; },
    resize(pixelRatio) { shared.uPixelRatio.value = pixelRatio; },
    ripple(record) {
      if (!records || record >= count) return;
      const [sleeve] = sleeves;
      const drop = sleeve.nextDrop;
      sleeve.nextDrop = (drop + 1) % 8;
      const { positions, tints } = records;
      const x = positions[record * 3];
      const along = (x - frame.start) / frame.slice, at = Math.min(frame.slices - 2, Math.max(0, Math.floor(along)));
      const centre = (values: Float32Array) => values[at] + (values[at + 1] - values[at]) * (along - at);
      sleeve.drops.set([x, Math.atan2(positions[record * 3 + 2] - centre(centreZ),
        positions[record * 3 + 1] - centre(centreY)), 0, 0], drop * 4);
      // The record's colour, lifted a little toward white so it reads as light.
      sleeve.dropTints.set([0.25 + 0.75 * tints[record * 3], 0.25 + 0.75 * tints[record * 3 + 1],
        0.25 + 0.75 * tints[record * 3 + 2], 1], drop * 4);
    },
    advance(time, zoom, inspecting) {
      const dt = lastFrame ? Math.min(0.05, Math.max(0, time - lastFrame) / 1000) : 0;
      lastFrame = time;
      shared.uTime.value = (time / 1000) % 3600;
      shared.uZoom.value = zoom;
      const target = inspecting ? INSPECTING : 1;
      calm += (target - calm) * (1 - Math.exp(-dt / 0.2));
      let moving = Math.abs(target - calm) > 0.004;
      if (!moving) calm = target;
      shared.uCalm.value = calm;
      for (const sleeve of sleeves) {
        const mouth = (sleeve.spacing * zoom - RINGS_FROM[0]) / (RINGS_FROM[1] - RINGS_FROM[0]);
        sleeve.glassUniforms.uRings.value = sleeve.rings * Math.min(1, Math.max(0, mouth));
        // The same light per canvas area however small the stream is drawn.
        sleeve.dustUniforms.uGain.value = sleeve.dustGain
          * Math.min(1, DUST_DENSITY * zoom * zoom / Math.max(sleeve.density, 1e-9));
        for (let drop = 0; drop < 8; drop++) {
          const age = sleeve.drops[drop * 4 + 3];
          if (age >= 1) continue;
          sleeve.drops[drop * 4 + 3] = Math.min(1, age + dt / RIPPLE_SECONDS);
          moving = true;
        }
      }
      return moving;
    },
    prepare(renderer) {
      if (!dirty) return;
      dirty = false;
      group.visible = survey();
      if (!group.visible) return;
      const previous = renderer.getRenderTarget();
      const axis = shared.uAxis.value;
      sleeves.forEach((sleeve, order) => {
        if (!sleeve.glass.visible) return;
        pressMaterial.uniforms.uOrder.value = order;
        renderer.setRenderTarget(press);
        renderer.render(pressScene, surveyCamera);
        resolveMaterial.uniforms.uPlace.value.set(axis.y / axis.z, sleeve.shape.y / axis.z, order * 7.3);
        renderer.setRenderTarget(sleeve.survey);
        renderer.render(resolveScene, surveyCamera);
      });
      renderer.setRenderTarget(previous);
    },
    dispose() {
      seeds?.geometry.dispose();
      for (const disposable of disposables) disposable.dispose();
    },
  };
}
