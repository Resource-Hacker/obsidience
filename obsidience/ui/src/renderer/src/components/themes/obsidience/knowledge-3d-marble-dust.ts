// Marble dust (owner 2026-10-14): each dust-marble node is packed with the
// Knowledge shells' own depth-of-field dust. Focus sits at the node's
// centre: two motes in five lie in a thin slab there and glitter as crisp
// one-pixel points, the rest fill the ball and blur toward its front and
// back into soft discs whose light spreads with their area, so they read as
// depth and never pile up; a few white-hot glints twinkle among them. Three
// layers of motes turn about their own tilted axes, at their own rates and
// in their own directions, so they drift past one another. No spiral, disc
// or bulge. Pure added light, drawn just after the node sprites; whole
// turns and whole cycles per hour keep the hourly uTime wrap seamless.
import * as THREE from "three";
import { ADDITIVE, LIGHT_GLSL } from "./knowledge-3d-shell";

/** Motes carried per marble; a marble shows a share of them by its area and
 *  the dust setting, so the default keeps its density up to 80 pixels. */
export const MARBLE_MOTES = 5000;
/** Layers of motes, each turning its own way. */
const LAYERS = 3;

const MARBLE_DUST_VERTEX = `
attribute vec4 aMote;   // node slot, layer, kind (0 deep, 1 in focus, 2 glint), phase
attribute vec3 aRandom; // size, brightness, rank in the visible share
uniform sampler2D uNodes; // per slot: centre and radius; tint and focus; base alpha; each layer's axis and turns per hour
uniform float uTime;
uniform float uPerspective;
uniform float uPixelRatio;
uniform float uPulse;
uniform float uSpeechLevel;
uniform float uMarbleDust;
varying float vAlpha;
varying float vSoft;
varying float vRing;
varying vec4 vShape; // blur radius, point radius and crisp spread in pixels; light of the blur
varying vec3 vColor;
// One turn an hour, in radians per second.
const float HOURLY = 0.0017453293;
void main() {
  int slot = int(aMote.x);
  vec4 node = texelFetch(uNodes, ivec2(slot, 0), 0);
  vec4 look = texelFetch(uNodes, ivec2(slot, 1), 0);
  vec4 spin = texelFetch(uNodes, ivec2(slot, 3 + int(aMote.y)), 0);
  float focus = look.w;
  // Dimmed sections dim their dust as the sprite dims its glass.
  float baseAlpha = mix(texelFetch(uNodes, ivec2(slot, 2), 0).x, 1.0, focus);
  float phase = aMote.w;
  // The node sprite's own focus swell, so the dust keeps filling its glass.
  float radius = node.w * (1.0 + focus * (0.10 + 0.06 * uPulse));
  float turn = uTime * spin.w * HOURLY;
  vec3 place = position * cos(turn) + cross(spin.xyz, position) * sin(turn)
    + spin.xyz * dot(spin.xyz, position) * (1.0 - cos(turn));
  vec3 cycles = floor(vec3(40.0, 55.0, 70.0) + fract(phase * vec3(13.1, 7.7, 5.3)) * 50.0);
  place += 0.04 * sin(uTime * cycles * HOURLY + phase * vec3(61.0, 17.0, 43.0));
  // Inside the glass.
  place *= min(1.0, 0.93 / max(length(place), 1e-4));
  vec4 centre = modelViewMatrix * vec4(node.xyz, 1.0);
  vec3 offset = mat3(modelViewMatrix) * place * radius;
  float reach = radius * length(modelViewMatrix[0].xyz);
  float radiusPx = reach * uPerspective / max(1.0, -centre.z);
  float marble = radiusPx / uPixelRatio;
  // Depth through the marble in its own radii, +1 nearest the viewer; the
  // focal slab's motes stay within a few hundredths of the focal plane.
  float depth = offset.z / max(reach, 1e-4);
  float kind = aMote.z;
  float blur = kind > 0.5 ? depth * 0.08 : depth;
  float confusion = min(0.2 * blur * blur * radiusPx, min(12.0 * uPixelRatio, 0.18 * radiusPx));
  // In focus a mote is about a pixel on a small marble, a little more on a large one.
  float base = (0.8 + aRandom.x * mix(0.45, 0.9, smoothstep(30.0, 90.0, marble))
    + 0.25 * step(1.5, kind)) * uPixelRatio;
  float size = base + confusion;
  vSoft = smoothstep(1.0, 2.5, confusion / uPixelRatio);
  vRing = smoothstep(6.0, 16.0, confusion / uPixelRatio);
  // A crisp mote is a small gaussian inside a larger point, so it keeps its
  // light as it slides between pixels; a blurred one spreads the same light
  // over its disc.
  float drawn = max(size, (1.0 - vSoft) * (2.4 * base + 1.0));
  gl_PointSize = drawn;
  vShape = vec4(size * 0.5, drawn * 0.5, 0.45 * base, 2.6 * base * base / (size * size));
  // A marble shows a share of its motes by its area, so small and large
  // marbles carry the same dust per pixel (three motes for every four square
  // pixels of radius); the dust setting adds motes, and each one fades in and
  // out at the edge of the share instead of popping.
  float share = min(1.0, marble * marble * 0.75 * uMarbleDust / ${MARBLE_MOTES}.0);
  float shown = clamp((share - aRandom.z) * 30.0, 0.0, 1.0);
  float glint = step(1.5, kind);
  float bright = aRandom.y * aRandom.y;
  float twinkle = 0.8 + 0.2 * sin(uTime * floor(400.0 + phase * 1400.0) * HOURLY + phase * 61.0);
  float flash = 0.5 + 0.5 * sin(uTime * floor(300.0 + fract(phase * 7.3) * 900.0) * HOURLY + phase * 29.0);
  twinkle = mix(twinkle, 0.12 + 0.88 * flash * flash * flash * flash, glint);
  // Lit from the marble's highlight side, upper left and toward the viewer.
  float lit = 0.75 + 0.25 * dot(offset / max(reach, 1e-4), vec3(-0.45, 0.55, 0.7));
  // Focus brightens the glitter, hardly the blur, and less as the dust
  // setting already brightens it, so a thinking marble never fills white.
  float lift = 1.0 + focus * (0.05 + 0.6 * (1.0 - vSoft)) / max(uMarbleDust * uMarbleDust * uMarbleDust, 1.0);
  vAlpha = (0.3 + 0.7 * bright) * mix(1.0, 2.0, glint) * twinkle * lit * mix(0.55, 1.0, 0.5 + 0.5 * depth)
    * shown * sqrt(max(uMarbleDust, 0.0)) * lift * (1.0 + 0.3 * uSpeechLevel) * baseAlpha
    * smoothstep(3.0, 9.0, marble) * 2.4;
  vColor = mix(mix(look.rgb, vec3(1.0), 0.06 + 0.3 * bright * bright), vec3(1.0, 0.98, 0.94), 0.8 * glint);
  vec4 clip = projectionMatrix * vec4(centre.xyz + offset, 1.0);
  // Depth of the node's own disc, so a nearer node's depth-prepass disc hides
  // this dust while its own disc does not.
  vec4 at = projectionMatrix * centre;
  clip.z = (at.z / at.w - 1e-4) * clip.w;
  gl_Position = clip;
  // A mote that is not shown is moved off screen instead of being discarded.
  if (radius <= 0.0 || vAlpha < 0.003) gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
}
`;

// The shells' bokeh (a large blur is a ring, as through a lens), with a
// crisp gaussian for motes in focus.
const MARBLE_DUST_FRAGMENT = `
varying float vAlpha;
varying float vSoft;
varying float vRing;
varying vec4 vShape;
varying vec3 vColor;
${LIGHT_GLSL}
void main() {
  float d = length(gl_PointCoord * 2.0 - 1.0) * vShape.y;
  if (d > vShape.y || vAlpha <= 0.0) discard;
  float r = d / vShape.x;
  float disc = 1.0 - smoothstep(0.65, 1.0, r);
  float ring = smoothstep(0.55, 0.86, r) * (1.0 - smoothstep(0.88, 1.0, r));
  float bokeh = mix(disc, disc * 0.22 + ring * 1.5, vRing) * vShape.w;
  float spark = exp(-d * d / (2.0 * vShape.z * vShape.z));
  gl_FragColor = knowledgeLight(vColor * mix(spark, bokeh, vSoft) * vAlpha);
}
`;

export interface MarbleDustUniforms {
  uTime: { value: number };
  /** Canvas pixels per view unit at unit distance, as the node sprites use. */
  uPerspective: { value: number };
  uPixelRatio: { value: number };
  uPulse: { value: number };
  /** The Executive's voice level, 0 to 1: the dust lifts a little as it speaks. */
  uSpeechLevel: { value: number };
  /** Amount of dust: more and brighter motes as it rises; 1 by default. */
  uMarbleDust: { value: number };
}

export interface MarbleDust {
  points: THREE.Points;
  /** A marble's centre and radius in the layer's local units (radius 0 hides
   *  it) and its focus, 0 to 1. Call update() after a batch. */
  setNode(slot: number, x: number, y: number, z: number, radius: number, focus: number): void;
  update(): void;
  dispose(): void;
}

export function createMarbleDust(options: {
  /** Branch colour per slot, three floats. */
  tints: Float32Array;
  /** 0 to 1 per slot; picks each marble's spins and constellation. */
  seeds: Float32Array;
  /** Base opacity per slot, as the node sprite's; focus lifts it to 1. */
  alphas: Float32Array;
  uniforms: MarbleDustUniforms;
}): MarbleDust {
  const { tints, seeds, alphas } = options;
  const count = seeds.length;
  const rows = 3 + LAYERS;
  // Row 0: centre, radius. Row 1: tint, focus. Row 2: base alpha. Then per
  // layer: spin axis, turns per hour.
  const data = new Float32Array(Math.max(1, count) * rows * 4);
  const texture = new THREE.DataTexture(data, Math.max(1, count), rows, THREE.RGBAFormat, THREE.FloatType);
  texture.minFilter = texture.magFilter = THREE.NearestFilter;
  texture.generateMipmaps = false;

  const places = new Float32Array(count * MARBLE_MOTES * 3);
  const motes = new Float32Array(count * MARBLE_MOTES * 4);
  const randoms = new Float32Array(count * MARBLE_MOTES * 3);
  for (let slot = 0; slot < count; slot++) {
    let state = (Math.floor(seeds[slot] * 1e6) * 2654435761 + slot * 97 + 1) >>> 0;
    const random = () => {
      state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
      return state / 4294967296;
    };
    data.set([tints[slot * 3], tints[slot * 3 + 1], tints[slot * 3 + 2], 0], (count + slot) * 4);
    data[(2 * count + slot) * 4] = alphas[slot];
    // Each layer turns about its own tilted axis; the second against the
    // first, the third faster.
    const direction = random() < 0.5 ? -1 : 1;
    const rates = [direction * Math.round(6 + random() * 4), -direction * Math.round(10 + random() * 6),
      (random() < 0.5 ? -1 : 1) * Math.round(16 + random() * 8)];
    for (let layer = 0; layer < LAYERS; layer++) {
      const y = random() * 2 - 1, angle = random() * Math.PI * 2, ring = Math.sqrt(1 - y * y);
      data.set([Math.cos(angle) * ring, y, Math.sin(angle) * ring, rates[layer]], ((3 + layer) * count + slot) * 4);
    }
    for (let i = 0; i < MARBLE_MOTES; i++) {
      // An even fill of the ball: no clouds, arms or core.
      let x = 0, y = 0, z = 0;
      do {
        x = random() * 2 - 1; y = random() * 2 - 1; z = random() * 2 - 1;
      } while (x * x + y * y + z * z > 1);
      const at = slot * MARBLE_MOTES + i;
      places[at * 3] = x; places[at * 3 + 1] = y; places[at * 3 + 2] = z;
      const pick = random(), layerPick = random();
      motes[at * 4] = slot;
      motes[at * 4 + 1] = layerPick < 0.4 ? 0 : layerPick < 0.75 ? 1 : 2;
      motes[at * 4 + 2] = pick < 0.03 ? 2 : pick < 0.43 ? 1 : 0;
      motes[at * 4 + 3] = random();
      // The rank is stratified, so any share of the motes is an even sample.
      randoms[at * 3] = random(); randoms[at * 3 + 1] = random(); randoms[at * 3 + 2] = (i + 0.5) / MARBLE_MOTES;
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(places, 3));
  geometry.setAttribute("aMote", new THREE.BufferAttribute(motes, 4));
  geometry.setAttribute("aRandom", new THREE.BufferAttribute(randoms, 3));
  const material = new THREE.ShaderMaterial({
    uniforms: { ...options.uniforms, uNodes: { value: texture } },
    vertexShader: MARBLE_DUST_VERTEX, fragmentShader: MARBLE_DUST_FRAGMENT,
    // The depth prepass hides dust behind a nearer node, as for the streaks.
    ...ADDITIVE, depthTest: true,
  });
  const points = new THREE.Points(geometry, material);
  points.name = "knowledge-marble-dust";
  points.frustumCulled = false;
  return {
    points,
    setNode(slot, x, y, z, radius, focus) {
      data.set([x, y, z, radius], slot * 4);
      data[(count + slot) * 4 + 3] = focus;
    },
    update() { texture.needsUpdate = true; },
    dispose() {
      geometry.dispose();
      material.dispose();
      texture.dispose();
    },
  };
}
