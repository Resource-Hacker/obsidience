// Shared Knowledge graph visual assets. Provider views reuse these shaders;
// layout and data ownership remain specific to each graph.
import { KNOWLEDGE_CROSS_SEGMENTS, KNOWLEDGE_SHELL_ROUTE_GLSL } from "./knowledge-3d-links";

export const KNOWLEDGE_LINK_APPROVAL_DURATION_MS = 4000;

/** Only the solid disc writes depth, never the transparent halo. */
export const POINT_DEPTH_FRAGMENT_SHADER = `
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
  // Squares: Articles 4-5, subjects 5-6 (subject 4 is the round marble).
  float squareFirst = vStyle.x < 0.5 ? 4.0 : 5.0;
  bool squareNode = vStyle.x < 1.5 && variant > squareFirst - 0.5;
  // A Dust marble is glass: what lies behind it shows through, so it writes
  // no depth (its dust layer dims what its glass covers).
  if (vStyle.x > 0.5 && vStyle.x < 1.5 && variant > 3.5 && variant < 4.5) discard;
  float solid = vStyle.x > 1.5 ? 0.9 : 1.0;
  if (squareNode) {
    float corner = variant < squareFirst + 0.5 ? 0.16 : 0.045;
    if (roundedBoxDistance(p, solid * 0.82, corner) > 0.0) discard;
  } else if (length(p) > solid) discard;
  gl_FragColor = vec4(0.0);
}
`;

export const POINT_VERTEX_SHADER = `
attribute float aRadius;
attribute float aExtent;
attribute float aGlowScale;
attribute vec3 aCore;
attribute vec3 aDark;
attribute vec4 aRing;
attribute vec4 aGlow;
attribute vec4 aStyle; // (subject, ringScale, ringWidthPx, baseAlpha)
attribute float aFocus;
attribute float aSwell; // extra size as a fraction: 1 doubles the node
attribute vec4 aActivity;
attribute float aSeed;
attribute float aCurate;
uniform float uPerspective;
uniform float uPulse;
uniform float uSpeechLevel;
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
varying vec4 vActivity;
varying float vTwinkle;
varying float vSeed;
varying float vCurate;
varying float vSpeech;
varying vec2 vCentre; // the sprite's centre, in clip space
varying vec3 vCloudX;
varying vec3 vCloudY;
void main() {
  // The cloud's own x and y axes as the camera sees them, so a marble's
  // glass carries its sheen in the cloud's frame and turns with the graph.
  vCloudX = normalize(modelViewMatrix[0].xyz);
  vCloudY = normalize(modelViewMatrix[1].xyz);
  vCore = aCore;
  vDark = aDark;
  vRing = aRing;
  vGlow = aGlow;
  vStyle = aStyle;
  vGlowScale = aGlowScale;
  vFocus = aFocus;
  vActivity = aActivity;
  vSeed = aSeed;
  vCurate = aCurate;
  vSpeech = step(1.5, aStyle.x) * uSpeechLevel;
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
#ifdef KNOWLEDGE_PROVIDER
  // Large provider graphs are static at rest, not a second ambient clock.
  vTwinkle = 0.0;
#endif
  vec4 mvPosition = modelViewMatrix * vec4(position, 1.0);
  // 2D parity: active/hovered discs grow ~2.5px, not a multiplicative bloom.
  float swell = 1.0 + aFocus * (0.10 + 0.06 * uPulse);
  swell *= 1.0 + 0.32 * vSpeech;
  swell *= 1.0 + aSwell;
  float radiusPx = aRadius * uModelScale * swell * uPerspective / max(1.0, -mvPosition.z);
#ifdef KNOWLEDGE_MEMORY
  // The same orbs read as a quiet ribbon at distance and reveal their full
  // cores/glow on approach. Every record remains present and pickable.
  float detail = smoothstep(1.0, 4.0, radiusPx);
  vStyle.w *= mix(0.65, 1.0, detail);
  vGlow.a *= mix(0.45, 1.0, detail);
#endif
  float size = clamp(radiusPx * aExtent * 2.0, 1.5, 1200.0);
  vRadiusPx = max(radiusPx, 0.75);
  vDiscFrac = (radiusPx * 2.0) / size;
  gl_PointSize = size;
  gl_Position = projectionMatrix * mvPosition;
  vCentre = gl_Position.xy / gl_Position.w;
}
`;

// Glass marble (owner 2026-10-14): a branch node as a clear marble in the
// Knowledge shells' own glass — their hairline sheen levels one canvas pixel
// wide, wandering on the same value-noise drift, every fifth one brighter,
// on the front face and through it on the back, fixed to the cloud so they
// turn with the graph; a limb, a small highlight — over a tinted body. Its
// solidity (uMarbleOpacity, 0 to 1.5) works as a shell layer's: at 0 only the
// dust is left, the glass light grows with it as a shell's does, and the body
// darkens toward opaque, almost fully at the top. The dust inside is real
// points drawn after the sprites (knowledge-3d-marble-dust.ts); here only its
// unresolved haze. The body bends the scene behind it as a glass ball does
// (uMarbleRefraction): the canvas as it stood before the node sprites, upside
// down through the middle, crowding toward the limb, where the glass reflects
// instead; each colour bends a little differently.
const GLASS_MARBLE_GLSL = `
uniform float uMarbleOpacity;
uniform float uMarbleDust;
uniform float uMarbleSheen; // the Glass group's Sheen lines setting
uniform float uSpeechLevel;
varying vec3 vCloudX;
varying vec3 vCloudY;
#ifndef KNOWLEDGE_PROVIDER
uniform sampler2D uBackdrop;
uniform float uMarbleRefraction;
uniform vec2 uViewportPx;
varying vec2 vCentre;
vec3 marbleLens(vec2 p, float r, float radiusPx) {
  // This pixel from the centre, in canvas pixels, and where its ray lands
  // behind the ball: mirrored through the centre, further out near the limb.
  // (The centre comes from the vertex: reading gl_FragCoord turns the point
  // sprite's own coordinates upside down under ANGLE's SwiftShader.)
  vec2 rel = vec2(p.x, -p.y) * radiusPx;
  float bend = 0.6 + 1.2 * r * r;
  vec2 size = vec2(textureSize(uBackdrop, 0));
  vec2 at = (vCentre * 0.5 + 0.5) * uViewportPx - rel * bend;
  vec2 spread = rel * 0.02 * r;
  return vec3(texture2D(uBackdrop, (at - spread) / size).r, texture2D(uBackdrop, at / size).g,
    texture2D(uBackdrop, (at + spread) / size).b);
}
#endif
// The shells' survey noise.
float marbleHash(vec3 p) {
  p = fract(p * 0.1031);
  p += dot(p, p.zyx + 31.32);
  return fract((p.x + p.y) * p.z);
}
float marbleNoise(vec3 p) {
  vec3 i = floor(p);
  vec3 f = fract(p);
  f = f * f * (3.0 - 2.0 * f);
  return mix(
    mix(mix(marbleHash(i), marbleHash(i + vec3(1.0, 0.0, 0.0)), f.x),
      mix(marbleHash(i + vec3(0.0, 1.0, 0.0)), marbleHash(i + vec3(1.0, 1.0, 0.0)), f.x), f.y),
    mix(mix(marbleHash(i + vec3(0.0, 0.0, 1.0)), marbleHash(i + vec3(1.0, 0.0, 1.0)), f.x),
      mix(marbleHash(i + vec3(0.0, 1.0, 1.0)), marbleHash(i + vec3(1.0, 1.0, 1.0)), f.x), f.y),
    f.z);
}
// One face's sheen: the level through this bearing (cloud frame) and its
// hairline, one canvas pixel wide; where levels crowd closer than a pixel they
// resolve to their mean coverage, so the limb glows instead of shimmering.
vec2 marbleSheen(vec3 bearing, vec3 pole, vec3 across, float levels, float wander, float minor) {
  float drift = 0.1 * (marbleNoise(across * 2.3) - 0.5) + 0.05 * (marbleNoise(across * 5.1) - 0.5)
    + 0.02 * (marbleNoise(across * 11.0) - 0.5);
  float level = (0.5 + 0.5 * dot(bearing, pole) + drift * wander) * levels;
  float spacing = fwidth(level);
  float line = 1.0 - smoothstep(0.25, 1.2, abs(fract(level - 0.5) - 0.5) / max(spacing, 1e-5));
  line = mix(line, min(spacing, 1.0), smoothstep(0.4, 0.95, spacing));
  return vec2(line, mod(floor(level + 0.5), 5.0) < 0.5 ? 0.5 : minor);
}
vec4 glassMarble(vec2 p, float r, float aa, float radiusPx, vec3 tint, vec3 dark, float seed, float boost) {
  float h = sqrt(max(0.0, 1.0 - r * r));
  vec3 normal = vec3(p.x, -p.y, h);
  // Front and back of the glass in the cloud's own frame.
  vec3 cloudZ = cross(vCloudX, vCloudY);
  vec3 front = vec3(dot(normal, vCloudX), dot(normal, vCloudY), dot(normal, cloudZ));
  vec3 rear = vec3(p.x, -p.y, -h);
  vec3 back = vec3(dot(rear, vCloudX), dot(rear, vCloudY), dot(rear, cloudZ));
  // Each marble's levels circle a pole leaning from the cloud's axis, as the
  // shells' circle theirs; more levels on a larger marble, so the lines fall
  // a few pixels apart at any size, and on a marble they wander further.
  float lean = 0.3 + 0.6 * fract(seed * 2.91), toward = seed * 17.0;
  vec3 pole = vec3(sin(lean) * cos(toward), cos(lean), sin(lean) * sin(toward));
  float levels = (3.0 + 0.1 * radiusPx) * uMarbleSheen;
  vec3 offset = vec3(seed * 7.3, seed * 3.1, seed * 5.9);
  // The shells' drift at a scale that bends each level across the marble
  // as it bends across a shell, a few line spacings to a wiggle.
  // On a small marble the minor levels fade, so its few lines never rule it.
  float minor = 0.2 * mix(0.35, 1.0, smoothstep(24.0, 56.0, radiusPx));
  vec2 frontSheen = marbleSheen(front, pole, front * 0.4 + offset, levels, 4.0, minor);
  vec2 backSheen = marbleSheen(back, pole, back * 0.4 + offset, levels, 4.0, minor);
  float line = frontSheen.x * frontSheen.y * 0.5 + backSheen.x * backSheen.y * 0.3;
  // Mostly pale aqua, a little of the branch, as the shells' sheen.
  vec3 shellTint = vec3(0.62 + 0.5 * (tint.r - tint.b) - 0.25 * (2.0 * tint.g - tint.r - tint.b),
    0.62 + 0.25 * (2.0 * tint.g - tint.r - tint.b),
    0.62 - 0.5 * (tint.r - tint.b) - 0.25 * (2.0 * tint.g - tint.r - tint.b));
  vec3 pale = mix(shellTint, vec3(0.78, 1.0, 0.94), 0.7);
  float limb = 1.0 - h;
  vec3 sun = normalize(vec3(-0.45, 0.55, 0.75));
  float spec = pow(max(dot(normal, normalize(sun + vec3(0.0, 0.0, 1.0))), 0.0), 220.0);
  // Light gathers on the far side of the marble from the sun, in its colour.
  float caustic = smoothstep(0.2, 0.95, dot(normalize(p * vec2(1.0, -1.0) + 1e-4), -sun.xy / length(sun.xy)))
    * smoothstep(0.45, 0.97, r);
  // Dust too fine to resolve: a faint glow through the marble's depth. Focus
  // and the Executive's voice lift it only a little: the dust itself carries
  // the brightening, and the glass stays clear.
  // The dust cloud's own glow, centred as the cloud is.
  vec3 haze = mix(tint, vec3(1.0), 0.2) * exp(-r * r / 0.4) * 0.06 * uMarbleDust
    * (1.0 + 0.25 * boost / max(uMarbleDust, 1.0)) * (1.0 + 0.3 * uSpeechLevel);
  float solid = uMarbleOpacity;
  vec3 light = (pale * (line * (1.0 + 0.6 * boost) + limb * limb * limb * 0.6)
    + mix(tint, vec3(1.0), 0.3) * caustic * 0.28
    + vec3(1.0) * (spec * 0.85 + pow(max(dot(normal, sun), 0.0), 6.0) * 0.04)) * solid;
  // 0.5 lets about a third of the scene through, 1 a tenth, 1.5 almost none;
  // thicker toward the limb, as glass is.
  float bodyA = 1.0 - exp(-2.5 * solid);
  float body = bodyA + (1.0 - bodyA) * limb * limb * 0.6 * min(solid, 1.0);
  // Light over the tinted body: alpha follows the glass's brightest channel
  // alone, so the glass sets how much of the scene it hides, never the dust,
  // whose glow is added on top.
  float shine = clamp(max(light.r, max(light.g, light.b)), 0.0, 1.0);
  float alpha = body + (1.0 - body) * shine;
  float edge = 1.0 - smoothstep(1.0 - aa, 1.0 + aa, r);
  vec3 seen = dark * 0.35;
#ifndef KNOWLEDGE_PROVIDER
  // Seen through the tinted body, coloured a little by the branch and lost
  // to reflection at the limb.
  vec3 stain = mix(vec3(1.0), tint / max(max(tint.r, max(tint.g, tint.b)), 1e-3), 0.35);
  float through = 1.0 - pow(limb, 4.0);
  seen += marbleLens(p, r, radiusPx) * stain * through * uMarbleRefraction;
#endif
  return vec4((seen * body + light + haze) / max(alpha, 0.02), alpha * edge);
}
`;

// Procedural replica of the 2D painter's node pass, composited source-over
// exactly like canvas: depth glow, then ring stroke, then the gradient disc.
export const POINT_FRAGMENT_SHADER = `
uniform float uActivityOpacity;
#ifdef KNOWLEDGE_PROVIDER
uniform float uProviderOpacity;
#endif
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
varying vec4 vActivity;
varying float vTwinkle;
varying float vSeed;
varying float vCurate;
varying float vSpeech;
uniform float uArticleStyle;
uniform float uCoreStyle;
uniform float uSubjectStyle;
uniform float uSubnodeStyle;
uniform float uRingStyle;
float roundedBoxDistance(vec2 point, float halfSize, float corner) {
  vec2 q = abs(point) - vec2(halfSize - corner);
  return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - corner;
}
${GLASS_MARBLE_GLSL}
void main() {
  vec2 p = (gl_PointCoord - 0.5) * 2.0 / max(vDiscFrac, 1e-4);
  float r = length(p);
  float aa = 1.6 / vRadiusPx;
  float nodeVariant = vStyle.x < 0.5
    ? uArticleStyle
    : (vStyle.x < 1.2
      ? uSubjectStyle
      : (vStyle.x < 1.5 ? uSubnodeStyle : uCoreStyle));
  // Squares: Articles 4-5, subjects 5-6 (subject 4 is the round marble).
  float squareFirst = vStyle.x < 0.5 ? 4.0 : 5.0;
  bool squareNode = vStyle.x < 1.5 && nodeVariant > squareFirst - 0.5;
  bool roundedSquare = nodeVariant < squareFirst + 0.5;
  bool marble = vStyle.x > 0.5 && vStyle.x < 1.5
    && nodeVariant > 3.5 && nodeVariant < 4.5;
  // Leaves shimmer ambiently via the twinkle floor; a real focus (the
  // thinking sweep, hover) always wins. Subjects never twinkle.
  float boost = vStyle.x > 0.5 ? vFocus : max(vFocus, vTwinkle);
  float effAlpha = mix(vStyle.w, 1.0, boost);
  vec3 acc = vec3(0.0);
  float accA = 0.0;
  // How much of the pixel is a marble's glass, which focus never frosts.
  float glassCover = 0.0;
  // One ring calculation for subjects and auto-curated Article leaves.
  // An unmarked Brain remains a bare floating ball of light.
  float ringA = 0.0;
  if (vCurate > 0.5 || (vStyle.x > 0.5 && vStyle.x < 1.5)) {
      float halfW = (vStyle.z * 0.5) / vRadiusPx;
      float ringDistance = squareNode
        ? abs(roundedBoxDistance(p, vStyle.y, roundedSquare ? 0.18 : 0.06))
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
              roundedSquare ? 0.14 : 0.045))
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
  if (vStyle.x > 0.5) {
    // Depth glow: gradient from 0.25r (palette glow) to glowScale*r (clear).
    float glowT = clamp((r - 0.25) / max(vGlowScale - 0.25, 1e-3), 0.0, 1.0);
    float glowA = vGlow.a * uGlowScale * (1.0 - glowT) * (1.0 + 0.45 * vSpeech);
    acc = vGlow.rgb * glowA;
    accA = glowA;
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
      brightness = min(1.0, brightness * (1.0 + 0.3 * vSpeech));
      disc = mix(vec3(0.45, 0.75, 1.0), vec3(1.0), brightness);
      discA = brightness * (1.0 - smoothstep(0.88, 1.02, r)) * effAlpha;
      }
    } else {
      // Subject disc variants per tier (owner 2026-08-03): branch nodes
      // ride uSubjectStyle, deeper sub-branch nodes uSubnodeStyle.
      // 0 Classic disc, 1 Plasma orb, 2 Gem, 3 Hollow, 4 Dust marble.
      // Obsidience adds 5 Rounded square and 6 Data tile for the Library.
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
      } else if (marble) {
        vec4 glass = glassMarble(p, r, aa, vRadiusPx, vCore, vDark, vSeed, boost);
        disc = glass.rgb;
        discA = glass.a * effAlpha;
        // The node's own glow stands behind the marble; seen through the
        // glass it should not fill it.
        float behind = 1.0 - 0.6 * edge;
        acc *= behind;
        accA *= behind;
        glassCover = edge;
      } else {
        // Library square nodes retain the same palette/depth language while
        // changing the actual sprite silhouette. Rounded square is a filled
        // glass tile; Data tile is a sharper hollow frame with scan rows.
        float corner = roundedSquare ? 0.16 : 0.045;
        float boxDistance = roundedBoxDistance(p, 0.82, corner);
        float boxInside = 1.0 - smoothstep(-aa, aa, boxDistance);
        float boxEdge = 1.0 - smoothstep(aa * 0.35, aa * 1.8, abs(boxDistance));
        if (roundedSquare) {
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
    if (vCurate > 0.5) {
      acc = vRing.rgb * ringA + acc * (1.0 - ringA);
      accA = ringA + accA * (1.0 - ringA);
    }
  }
  if (vActivity.w > 0.5) {
    // A local event halo leaves the authored branch colors and comet paths
    // intact. Reads breathe, Tools beat faster, commits radiate, failures flash.
    float mode = vActivity.w;
    float rate = mode > 4.5 ? 11.0 : (mode < 1.5 ? 3.0 : (mode < 2.5 ? 8.0 : 2.0));
    float beat = 0.5 + 0.5 * sin(uTime * rate);
    if (mode > 4.5) beat = pow(beat, 3.0);
    bool committed = mode > 3.5 && mode < 4.5;
    float wave = committed ? fract(uTime * 0.8) : 0.0;
    float radius = 1.12 + wave * 0.65;
    float halo = exp(-pow((r - radius) / max(0.10, aa), 2.0));
    // A newly reported Tool waits for the same arriving fill as its node.
    float alpha = halo * (committed ? (1.0 - wave) : (0.35 + beat * 0.6))
      * uActivityOpacity * clamp(vFocus, 0.0, 1.0);
    acc = vActivity.rgb * alpha + acc * (1.0 - alpha);
    accA = alpha + accA * (1.0 - alpha);
  }
  if (accA <= 0.004) discard;
  vec3 color = acc / max(accA, 1e-4);
  color = mix(color, vec3(1.0), boost * (marble ? 0.08 * (1.0 - glassCover) : 0.45));
  gl_FragColor = vec4(color, accA);
#ifdef KNOWLEDGE_PROVIDER
  gl_FragColor.a *= uProviderOpacity;
#endif
}
`;

// Links render as screen-space BEAM quads, not GL lines: each segment is
// extruded perpendicular to its screen direction in the vertex shader and
// shaded with a bright core plus a soft glow falloff (additive), so the
// connectors read as light beams. Widths/opacities ride live tuning
// uniforms.
export const BEAM_VERTEX_SHADER = `
#ifdef KNOWLEDGE_PROVIDER
// One instanced ribbon per native relationship. Endpoints follow the node
// texture, so layout updates upload O(nodes), not O(links * curve segments).
attribute vec4 aLink; // source index, target index, stable bow phase, opacity
uniform sampler2D uPositions;
uniform sampler2D uNodeColors;
uniform float uTextureSize;
uniform float uSelected;
uniform float uHovered;
uniform float uCurve;
uniform float uOverview;
varying float vLinkOpacity;
#ifdef KNOWLEDGE_MEMORY_LINKS
// A Memory link is a quiet thread at rest and a tendril while a memory
// operation holds both its records.
attribute vec3 aLive;   // lit from and until, in seconds on the scene's clock; operation colour + 8 * which end it starts from
uniform float uClock;
uniform float uReach;   // the stream's radius, for dimming its far side
uniform float uLivePx;  // a lit tendril's width
varying float vAlong;
varying vec2 vLive;     // how lit, and for how long
varying float vNear;
varying float vTint;
#endif
vec2 nodeUv(float index) {
  return (vec2(mod(index, uTextureSize), floor(index / uTextureSize)) + 0.5) / uTextureSize;
}
#ifdef KNOWLEDGE_CODE
${KNOWLEDGE_SHELL_ROUTE_GLSL}
#endif
vec3 threadPoint(vec3 a, vec3 b, float t, float phase) {
#ifdef KNOWLEDGE_CODE
  return knowledgeShellPoint(a, b, t);
#else
  // The early Knowledge tendrils: the thread's middle is pushed outward
  // from the stream's axis by a share of its length, so a link arches
  // around the stream instead of cutting through it. Its x coordinate stays
  // chronological; a thread that lies on the axis bows by its own phase.
  vec3 middle = 0.5 * (a + b);
  float away = length(middle.yz);
  vec3 outward = away > 1e-3 ? vec3(0.0, middle.yz / away) : vec3(0.0, cos(phase), sin(phase));
  return mix(a, b, t) + 2.0 * t * (1.0 - t) * clamp(distance(a, b) * 0.22, 14.0, 80.0) * uCurve * outward;
#endif
}
#else
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
#endif
#ifdef KNOWLEDGE_REVIEW_EFFECT
attribute vec2 aReview;
varying vec2 vReview;
#endif
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
#ifdef KNOWLEDGE_THREAD_LINKS
varying float vFront;
#endif
void main() {
#ifdef KNOWLEDGE_PROVIDER
  vec3 from = texture2D(uPositions, nodeUv(aLink.x)).xyz;
  vec3 to = texture2D(uPositions, nodeUv(aLink.y)).xyz;
  float t0 = position.x;
  #ifdef KNOWLEDGE_CODE
  float t1 = min(1.0, t0 + 1.0 / ${KNOWLEDGE_CROSS_SEGMENTS}.0);
  #else
  float t1 = min(1.0, t0 + 0.125);
  #endif
  vec3 aStart = threadPoint(from, to, t0, aLink.z);
  vec3 aEnd = threadPoint(from, to, t1, aLink.z);
  float aSide = position.y;
  float aEnd01 = position.z;
  float t = mix(t0, t1, aEnd01);
  vec3 aColor = mix(texture2D(uNodeColors, nodeUv(aLink.x)).rgb,
    texture2D(uNodeColors, nodeUv(aLink.y)).rgb, t);
  float aArc = t * distance(from, to);
  float aWidth = 0.0;
  float aP = -1.0; // adjacency never claims a Tool traversed this relationship
  float aDormant = 1.0;
  float aHover = (aLink.x == uSelected || aLink.y == uSelected ||
    aLink.x == uHovered || aLink.y == uHovered) ? 1.0 : 0.0;
  vLinkOpacity = mix(aLink.w * uOverview, 0.85, aHover);
  #ifdef KNOWLEDGE_MEMORY_LINKS
  vec3 here = mix(aStart, aEnd, aEnd01);
  vAlong = t;
  vLive = vec2(aLive.y > aLive.x && uClock >= aLive.x ? 1.0 - smoothstep(aLive.y, aLive.y + 0.9, uClock) : 0.0,
    uClock - aLive.x);
  vTint = aLive.z;
  // Threads on the stream's far side stand back.
  vNear = clamp(0.62 + 0.38 * ((modelViewMatrix * vec4(here, 1.0)).z
    - (modelViewMatrix * vec4(here.x, 0.0, 0.0, 1.0)).z) / max(uReach, 1.0), 0.3, 1.0);
  #endif
#endif
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
  float beamGlow = uGlow;
#ifdef KNOWLEDGE_REVIEW_EFFECT
  vReview = aReview;
  beamGlow = aReview.x > 0.5
    ? sin(clamp((aReview.y - 1.35) / 0.55, 0.0, 1.0) * 3.14159265)
    : (aReview.y >= 0.8 ? 0.2 + 0.08 * cos((aReview.y - 0.8) * 3.14159265) : 0.0);
#endif
  float swell = aP >= 0.0 ? 1.0 + beamGlow * 0.9 : 1.0;
#ifdef KNOWLEDGE_MEMORY_LINKS
  // A tendril grows to its width as it lights.
  swell = mix(1.0, uLivePx / uWidthPx, vLive.x * min(1.0, max(vLive.y, 0.0) / 0.25));
#endif
  vec2 normalPx = vec2(-direction.y, direction.x) *
    (mix(uWidthPx, uFloorPx, aWidth) * swell * 0.5 * aSide);
  vec4 clip = mix(clipA, clipB, aEnd01);
  clip.xy += (normalPx / (uViewportPx * 0.5)) * clip.w;
  vColor = aColor;
  vAcross = aSide;
  vArc = aArc;
#ifdef KNOWLEDGE_THREAD_LINKS
  // How squarely this part of the link faces the viewer: 1 on the ball's
  // near side, -1 behind it.
  vec3 fromCentre = (modelViewMatrix * vec4(mix(aStart, aEnd, aEnd01), 1.0)).xyz
    - (modelViewMatrix * vec4(0.0, 0.0, 0.0, 1.0)).xyz;
  vFront = fromCentre.z / max(length(fromCentre), 1e-4);
#endif
  gl_Position = clip;
}
`;

// Shared active-path timeline (owner 2026-08-02): every beam fragment
// carries its plan-progress coordinate vP (-1 off-path). The BEAM head
// (uBeamP) travels the path first as the thin blue pilot light; the SOLID
// beam (uSolidP), tube and centre line, launches once the head clears the
// first node and fills behind its own comet; when the fill completes the whole
// path pulses NEON (uGlow); then segmented dashes stream one direction
// (uFlowAge) — information flowing — in the beam's own gradient colors.
// On a cross-link whose endpoints were both reached another way vP is
// V-shaped, so both fronts read as two comets meeting at the middle.
const PATH_TIMELINE_GLSL = `
  float head = 1.0 - smoothstep(0.0, uHeadSpan, uBeamP - vP);
#if defined(KNOWLEDGE_REVIEW_EFFECT) || defined(KNOWLEDGE_SELECTION)
  float alpha = max(uOpacity, 0.55) * band;
  vec3 color = mix(vColor, vec3(1.0), head * 0.6);
#else
  // The Independence Day beam (owner 2026-10-15): a thin blue pilot light
  // runs the route first; the beam itself fires down it in the branch's
  // colour, white-hot at its front, once the pilot reaches the first node.
  float pilot = 1.0 - smoothstep(0.06, 0.2, t);
  float alpha = pilot * (0.7 + head * 0.3);
  vec3 color = mix(vec3(0.55, 0.8, 1.0), vec3(1.0), head * 0.7);
#endif
  float coreA = 0.0;
  if (uSolidP >= vP) {
    float solidHead = 1.0 - smoothstep(0.0, uHeadSpan, uSolidP - vP);
    coreA = core * (0.85 + solidHead * 0.15);
#if defined(KNOWLEDGE_REVIEW_EFFECT) || defined(KNOWLEDGE_SELECTION)
    color = mix(color, vec3(1.0), core * (0.25 + solidHead * 0.5));
#else
    alpha = max(uOpacity, 0.55) * band + solidHead * (1.0 - smoothstep(0.0, 1.0, t)) * 0.45;
    color = mix(vColor, vec3(1.0), min(1.0, core * (0.25 + solidHead * 0.5) + solidHead * 0.3));
#endif
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
  gl_FragColor = vec4(color, a * uPathOpacity);
`;

// Taxonomy beams (Brain spokes, structural arms, article spokes) —
// hollow-beam profile: a flat translucent TUBE with a crisply feathered
// silhouette. Dormant beams paint the tube ONLY (owner 2026-08-02: the
// bright center line is reserved for the thinking animation, so the
// chosen path is unmistakable); invisible-at-rest beams (aDormant 0)
// exist purely for the path timeline.
export const TAXONOMY_PATH_FRAGMENT_SHADER = `
uniform float uPathOpacity;
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
#ifdef KNOWLEDGE_SELECTION
    discard;
#endif
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
#ifndef KNOWLEDGE_SELECTION
  if (vDormant > 0.5) gl_FragColor.a += uOpacity * band * (1.0 - uPathOpacity);
#endif
}
`;

// Article cross-links: gently curved beams in the REVERSED gradient,
// checkered by arc length while dormant; the active path rides the same
// shared timeline as the taxonomy beams.
export const CROSS_PATH_FRAGMENT_SHADER = `
#ifdef KNOWLEDGE_PROVIDER
varying float vLinkOpacity;
#endif
#ifdef KNOWLEDGE_MEMORY_LINKS
varying float vAlong;
varying vec2 vLive;
varying float vNear;
varying float vTint;
#endif
uniform float uOpacity;
uniform float uDashFreq;
#ifndef KNOWLEDGE_REVIEW_EFFECT
uniform float uPathOpacity;
uniform float uBeamP;
uniform float uSolidP;
uniform float uGlow;
uniform float uFlowAge;
uniform float uHeadSpan;
#else
varying vec2 vReview;
#endif
varying vec3 vColor;
varying float vAcross;
varying float vArc;
varying float vP;
varying float vDormant;
#ifdef KNOWLEDGE_THREAD_LINKS
varying float vFront;
#endif
void main() {
  float t = abs(vAcross);
#ifdef KNOWLEDGE_MEMORY_LINKS
  {
    // At rest: a soft hairline in its records' colours, dimmer on the far side.
    float thread = 1.0 - smoothstep(0.15, 1.0, t);
    vec3 color = vColor;
    float alpha = uOpacity * vLinkOpacity * vNear * thread;
    if (vLive.x > 0.0) {
      // Lit. Between two records an operation holds, a front leaves each
      // and they meet in the middle. A recall's reach runs one way, from the
      // newest memory back to the one it returned. The tendril flashes when
      // the front arrives, then its dashes stream: along a held link, and
      // back toward the present along a recall's reach.
      float age = vLive.y;
      float start = floor(vTint / 8.0 + 0.01);
      float which = vTint - start * 8.0;
      float reached = start < 1.5 ? vAlong : 1.0 - vAlong;
      float behind = start < 0.5 ? min(1.0, age / 0.55) * 0.5 - min(vAlong, 1.0 - vAlong)
        : min(1.0, age / 0.55) - reached;
      float shown = smoothstep(0.0, 0.02, behind);
      float head = shown * (1.0 - smoothstep(0.0, 0.1, behind)) * (1.0 - smoothstep(0.55, 0.75, age));
      float flash = age > 0.55 ? exp(-(age - 0.55) * 3.2) : 0.0;
      float flow = start < 0.5 || start > 1.5 ? vArc * uDashFreq - age * 1.1 : vArc * uDashFreq + age * 1.1;
      float dash = age > 0.55 ? mix(0.3, 1.0, step(fract(flow), 0.55)) : 1.0;
      float sleeve = 1.0 - smoothstep(0.5, 1.0, t);
      float centre = 1.0 - smoothstep(0.12, 0.3, t);
      vec3 tint = which < 0.5 ? vec3(0.404, 0.91, 0.976) : which < 1.5 ? vec3(0.984, 0.749, 0.141)
        : which < 2.5 ? vec3(0.914, 0.659, 1.0) : which < 3.5 ? vec3(0.431, 0.906, 0.718) : vec3(0.984, 0.443, 0.522);
      vec3 lit = mix(mix(vColor, tint, 0.6), vec3(1.0), min(1.0, centre * 0.45 + head * 0.7 + flash * 0.5));
      float glow = shown * (sleeve * (0.22 + 0.5 * flash) + centre * dash * 0.85 + head);
      color = mix(color, lit, vLive.x);
      alpha = mix(alpha, uOpacity * glow, vLive.x);
    }
    gl_FragColor = vec4(color, alpha);
    return;
  }
#endif
  float band = (1.0 - smoothstep(0.88, 1.0, t)) * 0.24;
  float core = 1.0 - smoothstep(0.14, 0.24, t);
#ifdef KNOWLEDGE_REVIEW_EFFECT
  float uPathOpacity = 1.0;
  bool pending = vReview.x < 0.5;
  if (!pending && vReview.y >= ${(KNOWLEDGE_LINK_APPROVAL_DURATION_MS / 1000).toFixed(1)}) discard;
  float uBeamP = pending && vReview.y >= 0.8 ? 2.0 : vReview.y / (pending ? 0.6 : 0.9);
  float uSolidP = pending && vReview.y >= 0.8 ? 2.0
    : (vReview.y - (pending ? 0.2 : 0.45)) / (pending ? 0.6 : 0.9);
  float uGlow = pending
    ? (vReview.y >= 0.8 ? 0.2 + 0.08 * cos((vReview.y - 0.8) * 3.14159265) : 0.0)
    : sin(clamp((vReview.y - 1.35) / 0.55, 0.0, 1.0) * 3.14159265);
  float uFlowAge = -1.0;
  float uHeadSpan = 0.08;
  if (uBeamP < vP) discard;
#endif
  if (vP < 0.0 || uBeamP < vP) {
#ifdef KNOWLEDGE_THREAD_LINKS
    // At rest a link between Articles is one unbroken thread of light in
    // their two colours, a bright centre in a faint sleeve, so the eye can
    // follow it through the glass. Its dashes only shade it, and it stands
    // back on the ball's far side.
    float lit = fract(vArc * uDashFreq) > 0.55 ? 0.45 : 1.0;
    float sleeve = (1.0 - smoothstep(0.3, 1.0, t)) * 0.2;
    float centre = 1.0 - smoothstep(0.1, 0.3, t);
    gl_FragColor = vec4(mix(vColor, vec3(1.0), centre * 0.3),
      uOpacity * (sleeve + centre * 1.15 * lit) * mix(0.22, 1.0, smoothstep(-0.5, 0.3, vFront)));
    return;
#endif
    // Dormant: static checkered dashes at the tuned opacity.
    if (fract(vArc * uDashFreq) > 0.55) discard;
    float profile = min(1.0, band + core);
    gl_FragColor =
      vec4(mix(vColor, vec3(1.0), core * 0.2), uOpacity * profile);
#ifdef KNOWLEDGE_PROVIDER
    gl_FragColor.a *= vLinkOpacity;
#endif
    return;
  }
${PATH_TIMELINE_GLSL}
#ifndef KNOWLEDGE_REVIEW_EFFECT
  if (fract(vArc * uDashFreq) <= 0.55) gl_FragColor.a += uOpacity * min(1.0, band + core) * (1.0 - uPathOpacity);
#endif
#ifdef KNOWLEDGE_REVIEW_EFFECT
  if (!pending) gl_FragColor.a *= 1.0 - smoothstep(1.9,
    ${(KNOWLEDGE_LINK_APPROVAL_DURATION_MS / 1000).toFixed(1)}, vReview.y);
#endif
}
`;

// Elongated silver streaks streaming along the cross-link curves: each is
// clipped interval on the beam's exact polyline. Segmenting the tail prevents
// it from cutting through the layer while streaming still costs zero CPU
// once the ball settles.
export const PARTICLE_VERTEX_SHADER = `
attribute vec3 aStart;
attribute vec3 aEnd;
attribute vec2 aRange;
attribute float aPhase;
attribute float aSpeed;
attribute float aTip;
uniform float uTime;
uniform float uSpeedScale;
uniform float uStreakSpan;
varying float vTip;
varying float vVisible;
void main() {
  float head = fract(uTime * aSpeed * uSpeedScale + aPhase);
  float tail = max(0.0, head - uStreakSpan);
  float start = max(aRange.x, tail);
  float end = min(aRange.y, head);
  vVisible = end > start ? 1.0 : 0.0;
  float t = clamp(mix(start, end, aTip), aRange.x, aRange.y);
  vTip = clamp((t - tail) / max(0.00001, head - tail), 0.0, 1.0);
  float local = (t - aRange.x) / (aRange.y - aRange.x);
  gl_Position = projectionMatrix * modelViewMatrix * vec4(mix(aStart, aEnd, local), 1.0);
}
`;

export const PARTICLE_FRAGMENT_SHADER = `
varying float vTip;
varying float vVisible;
void main() {
  if (vVisible < 0.5) discard;
  gl_FragColor = vec4(0.86, 0.93, 1.0, 0.2 + 0.65 * vTip);
}
`;
