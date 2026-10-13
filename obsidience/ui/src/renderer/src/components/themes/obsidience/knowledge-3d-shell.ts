// The Knowledge ball drawn as a layered glass orb: one shell per layer of the
// force layout, each a sheen of fine contour lines and depth-of-field dust.
// Every node rests in a crater of its own layer's shell — wider and deeper
// the larger and better linked the node — and fills it with a seed: an orb of
// slowly turning dust in its branch colour. The shell nearest the core is the
// most solid and the outermost the clearest. The shells follow the actual
// layout; they add no force nodes, picking targets or activity routes, and
// being pure added light they need no sorting or depth test.
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
  /** The scan plane: height in cloud radii (-1 bottom, 1 top), gain, and how
   *  far its light turns amber (0 ambient survey, 1 thinking). */
  uScan: { value: THREE.Vector3 };
}

const OPTICS_GLSL = `
uniform float uFocusSwing;
uniform float uPixelRatio;
uniform float uReach;
uniform float uModelScale;
uniform vec3 uScan;
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
// Brightness gain where the scan plane passes a cloud-local point.
float knowledgeScan(vec3 local) {
  float plane = local.y / max(uReach, 1e-3) - uScan.x;
  return uScan.y * exp(-plane * plane * 700.0);
}
`;

/** Light added to a premultiplied canvas: alpha follows the brightest channel. */
const LIGHT_GLSL = `
const vec3 AMBER = vec3(1.0, 0.604, 0.235);
vec4 knowledgeLight(vec3 light) {
  return vec4(light, clamp(max(light.r, max(light.g, light.b)), 0.0, 1.0));
}
`;

const ADDITIVE = {
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
vec3 shellPoint(vec3 direction, float depth, float lift) {
  return direction * (uShell.x * (1.0 + lift) - uShell.y * depth);
}
`;

const GLASS_VERTEX = `
varying vec2 vSt;
varying float vFog;
varying float vEdge;
${OPTICS_GLSL}
${SPHERE_GLSL}
${SHELL_GLSL}
void main() {
  vSt = position.xy;
  vec3 direction = sphereDirection(vSt);
  vec4 view = modelViewMatrix * vec4(shellPoint(direction, texture2D(uSurvey, vSt).a, 0.0), 1.0);
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
uniform vec3 uScan;
varying vec2 vSt;
varying float vFog;
varying float vEdge;
${LIGHT_GLSL}
void main() {
  vec4 field = texture2D(uSurvey, vSt);
  float height = cos(vSt.y * 3.14159265359);
  float level = (0.5 + 0.5 * height + field.b) * uLevels + field.a * uRings;
  float spacing = fwidth(level);
  float line = 1.0 - smoothstep(0.25, 1.2, abs(fract(level - 0.5) - 0.5) / max(spacing, 1e-5));
  line = mix(line, min(spacing, 1.0), smoothstep(0.4, 0.95, spacing));
  float weight = mod(floor(level + 0.5), 5.0) < 0.5 ? 0.5 : 0.2;
  float plane = height - uScan.x;
  float scan = uScan.y * exp(-plane * plane * 350.0);
  vec3 tint = vec3(0.62 + field.r - field.g, 0.62 + field.g, 0.62 - field.r - field.g);
  vec3 color = mix(mix(tint, vec3(0.78, 1.0, 0.94), 0.86), mix(vec3(1.0), AMBER, uScan.z), min(1.0, scan * 0.3));
  float edge = vEdge * vEdge * vEdge * vEdge * 0.07;
  // A crater glows from its floor in its node's colour. The glow does not
  // thin with the glass, so a clear shell still shows where its nodes rest.
  vec3 glow = mix(tint, vec3(1.0), 0.2) * field.a * field.a * uGlow;
  gl_FragColor = knowledgeLight((color * (line * weight * (1.0 + scan) + edge) * uSolid + glow) * vFog);
}
`;

const DUST_VERTEX = `
attribute vec3 aDirection;
attribute vec4 aRandom; // size, keep, lift, twinkle phase
uniform float uTime;
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
  vec3 local = shellPoint(aDirection, field.a, aRandom.z);
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
  float scan = knowledgeScan(local);
  // uGain is set for a ball about 450 canvas pixels in radius; a smaller
  // one carries the same light per area instead of clotting.
  vec4 centre = modelViewMatrix * vec4(0.0, 0.0, 0.0, 1.0);
  float apparent = uReach * uModelScale * uPerspective / max(1.0, -centre.z) / 450.0;
  vAlpha = aRandom.y > 0.3 + 0.7 * smoothstep(0.0, 0.6, field.a) ? 0.0
    : light * energy * twinkle * knowledgeFog(depth) * (1.0 + scan) * uGain * min(1.0, apparent * apparent);
  vRing = smoothstep(5.0, 15.0, confusion / uPixelRatio);
  vec3 tint = vec3(0.62 + field.r - field.g, 0.62 + field.g, 0.62 - field.r - field.g);
  vColor = mix(haze ? vec3(0.88, 0.94, 1.0) : mix(tint, vec3(1.0), 0.6),
    mix(vec3(1.0), AMBER, uScan.z), min(1.0, scan * 0.3));
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
uniform float uTime;
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
  float turn = uTime * aRandom.z * 0.0017453293 + aRandom.y * 6.2831853;
  float along = dot(node.xyz, aMote.xyz);
  vec3 turned = aMote.xyz * cos(turn) + cross(node.xyz, aMote.xyz) * sin(turn)
    + node.xyz * along * (1.0 - cos(turn));
  turned -= node.xyz * along * (1.0 - min(1.0, node.w * uShell.y / max(orb, 1e-4)));
  vec3 local = node.xyz * shape.w + turned * orb;
  vec4 view = modelViewMatrix * vec4(local, 1.0);
  gl_Position = projectionMatrix * view;
  float depth = knowledgeDepth(view);
  float confusion = knowledgeConfusion(depth);
  float base = (1.0 + aRandom.x * 1.3) * uPixelRatio;
  float size = base + confusion;
  gl_PointSize = size;
  float twinkle = 0.75 + 0.25 * sin(uTime * (0.7 + aRandom.x * 2.5) + aRandom.y * 61.0);
  float scan = knowledgeScan(local);
  vec4 centre = modelViewMatrix * vec4(0.0, 0.0, 0.0, 1.0);
  float apparent = uReach * uModelScale * uPerspective / max(1.0, -centre.z) / 450.0;
  // Fading toward the edge of the seed.
  vAlpha = (1.0 - 0.75 * dot(aMote.xyz, aMote.xyz)) * (0.45 + 0.55 * aRandom.y)
    * base * base / (size * size) * twinkle * knowledgeFog(depth) * (1.0 + scan)
    * uGain * min(1.0, apparent * apparent);
  vRing = smoothstep(5.0, 15.0, confusion / uPixelRatio);
  vec3 tint = vec3(0.62 + shape.x - shape.y, 0.62 + shape.y, 0.62 - shape.x - shape.y);
  vColor = mix(mix(tint, vec3(1.0), 0.3), mix(vec3(1.0), AMBER, uScan.z), min(1.0, scan * 0.3));
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
/** The rim stands this far above a shell's nodes, as a fraction of the layer
 *  radius. A crater's floor lies below its node, and its mouth reaches toward
 *  the nearest neighbour, by these [lightest, heaviest] amounts. */
const RIM = 0.05;
const FLOOR = [0.03, 0.11];
const MOUTH = [0.55, 0.85];

/** The Glass tuning group; see Knowledge3dTuning. */
export interface Knowledge3dGlass {
  shellInner: number;
  shellOuter: number;
  craterDepth: number;
  craterGlow: number;
  seedGlow: number;
  sheenLines: number;
  shellDust: number;
}

export interface Knowledge3dShells {
  /** Glass, dust and seeds for every shell; add them to the cloud's group. */
  layers: readonly THREE.Object3D[];
  applyTuning(glass: Knowledge3dGlass): void;
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
}): Knowledge3dShells {
  const { positions, layers, sizes, weights, tints, optics } = options;
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
    // Row 2: icon radius.
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
    const glassMaterial = new THREE.ShaderMaterial({
      uniforms: {
        ...optics, uSurvey: survey, uShell: shape, uSolid: { value: 1 }, uGlow: { value: 0 },
        uLevels: { value: levels }, uRings: { value: 7 },
      },
      vertexShader: GLASS_VERTEX, fragmentShader: GLASS_FRAGMENT,
      side: THREE.DoubleSide, ...ADDITIVE,
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
        ...optics, uSurvey: survey, uShell: shape, uTexel: { value: 1 / width }, uGain: { value: 0 },
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
      uniforms: { ...optics, uNodes: { value: texture }, uShell: shape, uGain: { value: 0 } },
      vertexShader: SEED_VERTEX, fragmentShader: BOKEH_FRAGMENT, ...ADDITIVE,
    });
    const seeds = new THREE.Points(seedGeometry, seedMaterial);
    seeds.name = "knowledge-shell-seeds";
    seeds.frustumCulled = false;
    drawn.push(seeds);
    disposables.push(texture, surveyMaterial, glassMaterial, dustGeometry, dustMaterial, seedGeometry, seedMaterial);
    return { members, press, data, texture, surveyMaterial, survey, shape, width, levels,
      glass: glassMaterial.uniforms, dust: dustMaterial.uniforms, seeds: seedMaterial.uniforms,
      // Light per point for full dust at this shell's size.
      dustGain: 0.9 * 170_000 * reach * reach / dustCount,
      target: null as THREE.WebGLRenderTarget | null, floors: new Float32Array(count) };
  });

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
          Math.acos(Math.min(1, nearest)) * (MOUTH[0] + (MOUTH[1] - MOUTH[0]) * press[slot])));
      }
      shell.texture.needsUpdate = true;
      shell.shape.value.set(rim, deepest);
    }
    if (!(outer > 0)) return false;
    optics.uReach.value = outer;
    return true;
  };

  return {
    layers: drawn,
    invalidate() { dirty = true; },
    applyTuning(glass) {
      if (glass.craterDepth !== craterDepth) {
        craterDepth = glass.craterDepth;
        dirty = true;
      }
      shells.forEach((shell, order) => {
        // Most solid nearest the core, clearest outermost.
        const solid = shells.length > 1
          ? glass.shellInner + (glass.shellOuter - glass.shellInner) * order / (shells.length - 1)
          : (glass.shellInner + glass.shellOuter) / 2;
        shell.glass.uSolid.value = solid;
        shell.glass.uLevels.value = shell.levels * glass.sheenLines;
        shell.glass.uRings.value = 7 * glass.sheenLines;
        shell.dust.uGain.value = shell.dustGain * solid * glass.shellDust;
        shell.seeds.uGain.value = 1.1 * glass.seedGlow;
        shell.glass.uGlow.value = 0.16 * glass.craterGlow;
      });
    },
    prepare(renderer) {
      if (!dirty || ++skipped < cadence) return;
      skipped = 0;
      dirty = false;
      if (!survey()) { show(false); return; }
      const float = renderer.extensions.has("EXT_color_buffer_float")
        && renderer.extensions.has("OES_texture_float_linear");
      const previous = renderer.getRenderTarget();
      for (const shell of shells) {
        if (!shell.target) {
          shell.target = new THREE.WebGLRenderTarget(shell.width, shell.width / 2, {
            type: float ? THREE.FloatType : THREE.HalfFloatType, format: THREE.RGBAFormat,
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
      renderer.setRenderTarget(previous);
      show(true);
    },
    dispose() {
      for (const shell of shells) shell.target?.dispose();
      for (const disposable of disposables) disposable.dispose();
    },
  };
}
