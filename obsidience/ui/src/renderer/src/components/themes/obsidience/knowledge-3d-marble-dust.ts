// Marble dust (owner 2026-10-14): each dust-marble node holds a cloud of the
// Knowledge shells' own depth-of-field dust in its middle, as the graph holds
// its core: densest at the centre, almost none at the glass. As a crater seed's
// motes circle their node's bearing, every mote here circles its own axis,
// leaning from that bearing, at its own rate and in its own direction (60 to
// 300 whole turns an hour), and bobs gently besides, so the dust drifts past
// itself inside the glass. Focus sits at the node's centre: two motes in five
// lie in a thin slab there as small crisp points; the rest blur toward the
// front and back into the shells' soft discs, rings when far out, whose light
// spreads with their area. Pale as the shells' dust, with its gentle twinkle.
// Pure added light, drawn just after the node sprites; whole turns and whole
// cycles per hour keep the hourly uTime wrap seamless.
import * as THREE from "three";
import { ADDITIVE, LIGHT_GLSL } from "./knowledge-3d-shell";

/** The dust cloud's spread, in marble radii (one standard deviation). */
const DUST_SPREAD = 0.34;
/** Motes carried per marble; a marble shows a share of them by its area and
 *  the dust setting, so the default keeps its density up to about 60 pixels. */
export const MARBLE_MOTES = 5000;

const MARBLE_DUST_VERTEX = `
attribute vec4 aMote;   // node slot, turns per hour, kind (0 deep, 1 in focus), phase
attribute vec3 aLean;   // how the mote's axis leans from the node's bearing
attribute vec3 aRandom; // size, brightness, rank in the visible share
uniform sampler2D uNodes; // per slot: centre and radius; tint and focus; base alpha
uniform float uTime;
uniform float uPerspective;
uniform float uPixelRatio;
uniform float uPulse;
uniform float uSpeechLevel;
uniform float uMarbleDust;
uniform float uMarbleOpacity; // the marbles' glass solidity, as the sprites draw it
uniform int uSlots;
varying float vAlpha;
varying float vSoft;
varying float vRing;
varying vec4 vShape; // blur radius, point radius and crisp spread in pixels; light of the blur
varying vec3 vColor;
// One turn an hour, in radians per second.
const float HOURLY = 0.0017453293;
// How much of what lies behind a marble's glass it hides at this fraction of
// its radius: the sprite's body, thicker toward the limb (knowledge-3d-shaders.ts).
float marbleGlass(float r) {
  float limb = 1.0 - sqrt(max(0.0, 1.0 - r * r));
  float bodyA = 1.0 - exp(-2.5 * uMarbleOpacity);
  return bodyA + (1.0 - bodyA) * limb * limb * 0.6 * min(uMarbleOpacity, 1.0);
}
void main() {
  int slot = int(aMote.x);
  vec4 node = texelFetch(uNodes, ivec2(slot, 0), 0);
  vec4 look = texelFetch(uNodes, ivec2(slot, 1), 0);
  float focus = look.w;
  // Dimmed sections dim their dust as the sprite dims its glass.
  float baseAlpha = mix(texelFetch(uNodes, ivec2(slot, 2), 0).x, 1.0, focus);
  float phase = aMote.w;
  // The node sprite's own focus swell, so the dust keeps filling its glass.
  float radius = node.w * (1.0 + focus * (0.10 + 0.06 * uPulse));
  // The mote circles its own axis, leaning from the node's bearing.
  vec3 bearing = dot(node.xyz, node.xyz) > 1e-8 ? normalize(node.xyz) : vec3(0.0, 1.0, 0.0);
  vec3 axis = normalize(bearing + aLean);
  float turn = uTime * aMote.y * HOURLY + phase * 6.2831853;
  vec3 place = position * cos(turn) + cross(axis, position) * sin(turn)
    + axis * dot(axis, position) * (1.0 - cos(turn));
  // And bobs a little, so it floats rather than wheels.
  vec3 cycles = floor(vec3(90.0, 120.0, 150.0) + fract(phase * vec3(13.1, 7.7, 5.3)) * 120.0);
  place += 0.05 * sin(uTime * cycles * HOURLY + phase * vec3(61.0, 17.0, 43.0));
  // The rare mote that drifts out fades before the glass instead of piling on it.
  float away = length(place);
  float rim = 1.0 - smoothstep(0.7, 0.9, away);
  place *= min(1.0, 0.9 / max(away, 1e-4));
  vec4 centre = modelViewMatrix * vec4(node.xyz, 1.0);
  vec3 offset = mat3(modelViewMatrix) * place * radius;
  float reach = radius * length(modelViewMatrix[0].xyz);
  float radiusPx = reach * uPerspective / max(1.0, -centre.z);
  float marble = radiusPx / uPixelRatio;
  // Depth through the marble in its own radii, +1 nearest the viewer; the
  // focal slab's motes stay within a few hundredths of the focal plane.
  float depth = offset.z / max(reach, 1e-4);
  float blur = aMote.z > 0.5 ? depth * 0.08 : depth;
  // The shells' circle of confusion, grown with the distance from focus.
  float confusion = min(abs(blur) * 0.16 * radiusPx, min(16.0 * uPixelRatio, 0.2 * radiusPx));
  // In focus a mote is a pixel or two, as on the shells.
  float base = (0.9 + aRandom.x * mix(0.6, 1.1, smoothstep(30.0, 90.0, marble))) * uPixelRatio;
  float size = base + confusion;
  vSoft = smoothstep(1.0, 2.5, confusion / uPixelRatio);
  // Far out of focus a disc becomes a ring, as through a lens.
  vRing = smoothstep(5.0, 10.0, confusion / uPixelRatio);
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
  float bright = aRandom.y;
  // The shells' gentle twinkle.
  float twinkle = 0.82 + 0.18 * sin(uTime * floor(400.0 + phase * 1400.0) * HOURLY + phase * 61.0);
  // Lit from the marble's highlight side, upper left and toward the viewer.
  float lit = 0.8 + 0.2 * dot(offset / max(reach, 1e-4), vec3(-0.45, 0.55, 0.7));
  // Focus brightens the crisp motes, hardly the blur, and less as the dust
  // setting already brightens them, so a thinking marble never fills white.
  float lift = 1.0 + focus * (0.05 + 0.6 * (1.0 - vSoft)) / max(uMarbleDust * uMarbleDust * uMarbleDust, 1.0);
  vAlpha = rim * (0.45 + 0.55 * bright) * twinkle * lit * mix(0.6, 1.0, 0.5 + 0.5 * depth)
    * shown * sqrt(max(uMarbleDust, 0.0)) * lift * (1.0 + 0.3 * uSpeechLevel) * baseAlpha
    * smoothstep(3.0, 9.0, marble) * 0.45;
  // The shells' pale dust: the branch colour, desaturated as the glass
  // carries it, lifted between the seeds' white and the shell dust's.
  vec3 tint = look.rgb;
  float red = 0.5 * (tint.r - tint.b), green = 0.25 * (2.0 * tint.g - tint.r - tint.b);
  vColor = mix(vec3(0.62 + red - green, 0.62 + green, 0.62 - red - green), vec3(1.0), 0.3 + 0.3 * bright);
  // Seen through every nearer marble's glass: marbles write no depth, so dust
  // behind one shows through it, dimmed as its glass dims whatever is behind.
  vec3 seen = centre.xyz + offset;
  vec2 onScreen = seen.xy / max(1e-4, -seen.z);
  float scale = length(modelViewMatrix[0].xyz);
  if (vAlpha >= 0.003) {
    for (int other = 0; other < uSlots; other++) {
      vec4 near = texelFetch(uNodes, ivec2(other, 0), 0);
      if (other == slot || near.w <= 0.0) continue;
      vec4 nearCentre = modelViewMatrix * vec4(near.xyz, 1.0);
      if (nearCentre.z <= centre.z) continue;
      vec4 nearLook = texelFetch(uNodes, ivec2(other, 1), 0);
      float nearRadius = near.w * (1.0 + nearLook.w * (0.10 + 0.06 * uPulse)) * scale / max(1e-4, -nearCentre.z);
      float r = length(onScreen - nearCentre.xy / max(1e-4, -nearCentre.z)) / max(nearRadius, 1e-6);
      if (r >= 1.0) continue;
      float nearAlpha = mix(texelFetch(uNodes, ivec2(other, 2), 0).x, 1.0, nearLook.w);
      vAlpha *= 1.0 - marbleGlass(r) * nearAlpha;
    }
  }
  vec4 clip = projectionMatrix * vec4(seen, 1.0);
  // Depth of the node's own centre, so opaque nodes, articles and the core in
  // front still hide it through the depth prepass.
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
  /** The marbles' glass solidity, 0 to 1.5, so dust behind a marble dims as its glass does. */
  uMarbleOpacity: { value: number };
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
  /** 0 to 1 per slot; picks each marble's constellation and its motes' turns. */
  seeds: Float32Array;
  /** Base opacity per slot, as the node sprite's; focus lifts it to 1. */
  alphas: Float32Array;
  uniforms: MarbleDustUniforms;
}): MarbleDust {
  const { tints, seeds, alphas } = options;
  const count = seeds.length;
  const rows = 3;
  // Row 0: centre, radius. Row 1: tint, focus. Row 2: base alpha.
  const data = new Float32Array(Math.max(1, count) * rows * 4);
  const texture = new THREE.DataTexture(data, Math.max(1, count), rows, THREE.RGBAFormat, THREE.FloatType);
  texture.minFilter = texture.magFilter = THREE.NearestFilter;
  texture.generateMipmaps = false;

  const places = new Float32Array(count * MARBLE_MOTES * 3);
  const motes = new Float32Array(count * MARBLE_MOTES * 4);
  const leans = new Float32Array(count * MARBLE_MOTES * 3);
  const randoms = new Float32Array(count * MARBLE_MOTES * 3);
  for (let slot = 0; slot < count; slot++) {
    let state = (Math.floor(seeds[slot] * 1e6) * 2654435761 + slot * 97 + 1) >>> 0;
    const random = () => {
      state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
      return state / 4294967296;
    };
    const gaussian = () => Math.sqrt(-2 * Math.log(1 - random())) * Math.cos(2 * Math.PI * random());
    data.set([tints[slot * 3], tints[slot * 3 + 1], tints[slot * 3 + 2], 0], (count + slot) * 4);
    data[(2 * count + slot) * 4] = alphas[slot];
    for (let i = 0; i < MARBLE_MOTES; i++) {
      // A cloud in the middle of the glass, as the core sits in the middle of
      // the graph: densest at the centre, thinning to almost none at the rim
      // (a gaussian ball, cut off well inside the glass).
      let x = 0, y = 0, z = 0;
      do {
        x = gaussian() * DUST_SPREAD; y = gaussian() * DUST_SPREAD; z = gaussian() * DUST_SPREAD;
      } while (x * x + y * y + z * z > 0.85 * 0.85);
      const at = slot * MARBLE_MOTES + i;
      places[at * 3] = x; places[at * 3 + 1] = y; places[at * 3 + 2] = z;
      // Its axis leans up to fifty degrees from the bearing; its rate is
      // mostly slow, 60 to 300 whole turns an hour, either way round.
      const height = random() * 2 - 1, angle = random() * Math.PI * 2, ring = 0.8 * Math.sqrt(1 - height * height);
      leans.set([Math.cos(angle) * ring, 0.8 * height, Math.sin(angle) * ring], at * 3);
      const pace = random();
      motes[at * 4] = slot;
      motes[at * 4 + 1] = (random() < 0.5 ? -1 : 1) * Math.round(60 + 240 * pace * pace);
      motes[at * 4 + 2] = random() < 0.25 ? 1 : 0;
      motes[at * 4 + 3] = random();
      // The rank is stratified, so any share of the motes is an even sample.
      randoms[at * 3] = random(); randoms[at * 3 + 1] = random(); randoms[at * 3 + 2] = (i + 0.5) / MARBLE_MOTES;
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(places, 3));
  geometry.setAttribute("aMote", new THREE.BufferAttribute(motes, 4));
  geometry.setAttribute("aLean", new THREE.BufferAttribute(leans, 3));
  geometry.setAttribute("aRandom", new THREE.BufferAttribute(randoms, 3));
  const material = new THREE.ShaderMaterial({
    uniforms: { ...options.uniforms, uNodes: { value: texture }, uSlots: { value: count } },
    vertexShader: MARBLE_DUST_VERTEX, fragmentShader: MARBLE_DUST_FRAGMENT,
    // The depth prepass hides dust behind a nearer opaque node or the core;
    // marbles write no depth and dim it themselves (above).
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
