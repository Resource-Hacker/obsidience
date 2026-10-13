// Presentation detail attached to the real graph. One additive draw call,
// no extra force nodes, picking targets or activity routes. The position
// texture uploads only when the cloud's existing solver moves its nodes.
import * as THREE from "three";

const MAX_POINTS = 24000;
const NODE_POINTS = 28;
const BRANCH_POINTS = 36;

const vertexShader = `
attribute vec3 aAttach; // source index, target index, interpolation
attribute vec3 aOffset;
attribute vec3 aColor;
attribute float aSeed;
uniform sampler2D uNodes;
uniform float uTextureSize;
uniform float uPerspective;
uniform float uModelScale;
uniform float uPixelRatio;
uniform float uTime;
uniform float uGlowScale;
uniform float uBranchOpacity;
varying vec3 vColor;
varying float vAlpha;
vec4 nodeAt(float index) {
  vec2 uv = (vec2(mod(index, uTextureSize), floor(index / uTextureSize)) + 0.5) / uTextureSize;
  return texture2D(uNodes, uv);
}
void main() {
  vec4 a = nodeAt(aAttach.x);
  vec4 b = nodeAt(aAttach.y);
  bool nodeDust = aAttach.x == aAttach.y;
  float radius = nodeDust ? max(0.32, a.w) : 0.18;
  vec3 at = mix(a.xyz, b.xyz, aAttach.z) + aOffset * radius;
  vec4 view = modelViewMatrix * vec4(at, 1.0);
  vec4 center = modelViewMatrix * vec4(0.0, 0.0, 0.0, 1.0);
  float depth = max(1.0, -view.z);
  float base = clamp((0.13 + aSeed * 0.14) * uModelScale * uPerspective / depth,
    0.7 * uPixelRatio, 1.7 * uPixelRatio);
  // A little optical softness only on decorative light behind the graph's
  // centre. Energy compensation prevents blurred points becoming brighter.
  float blur = min(2.2 * uPixelRatio, max(0.0, center.z - view.z) * 0.018 * uPixelRatio);
  float size = base + blur;
  gl_PointSize = size;
  gl_Position = projectionMatrix * view;
  float energy = base * base / (size * size);
  float depthFade = exp(-max(0.0, center.z - view.z) * 0.012);
  // Slow local scintillation is decoration, never a travelling activity cue.
  float scintillation = 0.88 + 0.12 * sin(uTime * 0.7 + aSeed * 37.0);
  float strength = nodeDust ? 0.48 * min(uGlowScale, 2.0) : 0.4 * uBranchOpacity;
  // Subpixel satellite detail fades instead of accumulating a white clump.
  float detail = smoothstep(0.25, 1.25, uModelScale * uPerspective / depth);
  vAlpha = strength * energy * depthFade * scintillation * detail;
  vColor = mix(aColor, vec3(0.85, 0.95, 1.0), 0.2);
}
`;

const fragmentShader = `
varying vec3 vColor;
varying float vAlpha;
void main() {
  vec2 p = gl_PointCoord * 2.0 - 1.0;
  float d = dot(p, p);
  if (d > 1.0) discard;
  float light = (1.0 - d) * (1.0 - d);
  gl_FragColor = vec4(vColor, light * vAlpha);
}
`;

export function createKnowledge3dLightLayer(options: {
  ids: readonly string[];
  positions: Float32Array;
  radii: Float32Array;
  colors: Float32Array;
  /** Only visible taxonomy arms; never invent edges from proximity. */
  branches: readonly (readonly [number, number])[];
  uniforms: {
    uPerspective: { value: number };
    uModelScale: { value: number };
    uTime: { value: number };
    uGlowScale: { value: number };
    uBranchOpacity: { value: number };
  };
  pixelRatio: number;
}) {
  const { ids, positions, radii, colors, branches } = options;
  const size = Math.max(1, Math.ceil(Math.sqrt(ids.length)));
  const texels = new Float32Array(size * size * 4);
  const texture = new THREE.DataTexture(texels, size, size, THREE.RGBAFormat, THREE.FloatType);
  texture.minFilter = texture.magFilter = THREE.NearestFilter;
  texture.generateMipmaps = false;
  const syncPositions = () => {
    for (let i = 0; i < ids.length; i++) {
      texels[i * 4] = positions[i * 3];
      texels[i * 4 + 1] = positions[i * 3 + 1];
      texels[i * 4 + 2] = positions[i * 3 + 2];
      texels[i * 4 + 3] = radii[i];
    }
    texture.needsUpdate = true;
  };
  syncPositions();
  const density = Math.min(1, MAX_POINTS / Math.max(1, ids.length * NODE_POINTS + branches.length * BRANCH_POINTS));
  const perNode = Math.floor(NODE_POINTS * density);
  const perBranch = Math.floor(BRANCH_POINTS * density);
  const count = ids.length * perNode + branches.length * perBranch;
  const attaches = new Float32Array(count * 3);
  const offsets = new Float32Array(count * 3);
  const tints = new Float32Array(count * 3);
  const seeds = new Float32Array(count);
  // Stable identity seeds avoid a different constellation on paint refresh.
  const seedFor = (id: string) => {
    let hash = 2166136261;
    for (let i = 0; i < id.length; i++) hash = Math.imul(hash ^ id.charCodeAt(i), 16777619);
    return hash >>> 0;
  };
  let state = 1;
  const random = () => {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    return state / 4294967296;
  };
  let point = 0;
  const add = (a: number, b: number, t: number, shell: boolean) => {
    attaches.set([a, b, t], point * 3);
    const z = random() * 2 - 1;
    const theta = random() * Math.PI * 2;
    const radius = shell ? 1.4 + random() * 2.5 : Math.sqrt(random());
    const ring = Math.sqrt(1 - z * z) * radius;
    offsets.set([Math.cos(theta) * ring, Math.sin(theta) * ring, z * radius], point * 3);
    for (let axis = 0; axis < 3; axis++) {
      tints[point * 3 + axis] = colors[a * 3 + axis] * (1 - t) + colors[b * 3 + axis] * t;
    }
    seeds[point++] = random();
  };
  ids.forEach((id, i) => {
    state = seedFor(id);
    for (let j = 0; j < perNode; j++) add(i, i, 0, true);
  });
  for (const [a, b] of branches) {
    state = seedFor(`${ids[a]}|${ids[b]}`);
    for (let j = 0; j < perBranch; j++) add(a, b, (j + 0.5) / perBranch, false);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(new Float32Array(count * 3), 3));
  geometry.setAttribute("aAttach", new THREE.BufferAttribute(attaches, 3));
  geometry.setAttribute("aOffset", new THREE.BufferAttribute(offsets, 3));
  geometry.setAttribute("aColor", new THREE.BufferAttribute(tints, 3));
  geometry.setAttribute("aSeed", new THREE.BufferAttribute(seeds, 1));
  const pixelRatio = { value: options.pixelRatio };
  const material = new THREE.ShaderMaterial({
    uniforms: { ...options.uniforms, uNodes: { value: texture }, uTextureSize: { value: size }, uPixelRatio: pixelRatio },
    vertexShader, fragmentShader,
    transparent: true, depthTest: true, depthWrite: false,
    blending: THREE.AdditiveBlending,
  });
  const points = new THREE.Points(geometry, material);
  points.name = "knowledge-structure-light";
  points.frustumCulled = false;
  points.renderOrder = 0;
  return {
    points,
    syncPositions,
    setPixelRatio(ratio: number) { pixelRatio.value = ratio; },
    dispose() { geometry.dispose(); material.dispose(); texture.dispose(); },
  };
}
