/** One shell-following route for links, Review paint and travelling streaks.
 *  Coordinates are in the cloud's local space, before orbit/scale. */
export const KNOWLEDGE_CROSS_SEGMENTS = 32;

/** GPU form of the same route for instanced provider ribbons. Stable endpoint
 * order, antipodal tangent, exact attachments and sag correction match below. */
export const KNOWLEDGE_SHELL_ROUTE_GLSL = `
vec3 knowledgeShellPoint(vec3 a, vec3 b, float t) {
  if (t <= 0.0) return a;
  if (t >= 1.0) return b;
  float ra = length(a), rb = length(b);
  vec3 u = ra > 1e-8 ? a / ra : rb > 1e-8 ? b / rb : vec3(1.0, 0.0, 0.0);
  vec3 end = rb > 1e-8 ? b / rb : u;
  float cosine = clamp(dot(u, end), -1.0, 1.0);
  vec3 tangent = end - cosine * u;
  float tangentLength = length(tangent);
  float angle = atan(tangentLength, cosine);
  if (tangentLength > 1e-8) tangent /= tangentLength;
  else {
    vec3 basis = abs(u.x) <= abs(u.y) && abs(u.x) <= abs(u.z) ? vec3(1.0, 0.0, 0.0)
      : abs(u.y) <= abs(u.z) ? vec3(0.0, 1.0, 0.0) : vec3(0.0, 0.0, 1.0);
    tangent = normalize(basis - dot(basis, u) * u);
  }
  float radius = mix(ra, rb, t) * (1.0 + 1e-6) / cos(angle / ${KNOWLEDGE_CROSS_SEGMENTS}.0);
  return (cos(angle * t) * u + sin(angle * t) * tangent) * radius;
}
`;

/** Call with endpoints in stable ID order; reverse the samples for a reversed
 *  rendered edge. This also gives antipodal links one stable side to go around.
 *  Equal endpoint radii follow their shell; different radii transition smoothly
 *  between shells. No article-size offset, raised leads or extra outward bow.
 *  Endpoints may be read in place from a shared position buffer by offset; the
 *  solver calls this for every link on every settling tick, so it allocates
 *  nothing. */
export function writeKnowledgeCrossRoute(
  output: Float32Array,
  a: ArrayLike<number>,
  b: ArrayLike<number>,
  aOffset = 0,
  bOffset = 0,
): void {
  const ax = a[aOffset], ay = a[aOffset + 1], az = a[aOffset + 2];
  const bx = b[bOffset], by = b[bOffset + 1], bz = b[bOffset + 2];
  const ra = Math.hypot(ax, ay, az);
  const rb = Math.hypot(bx, by, bz);
  let ux = 1, uy = 0, uz = 0;
  if (ra > 1e-8) { ux = ax / ra; uy = ay / ra; uz = az / ra; }
  else if (rb > 1e-8) { ux = bx / rb; uy = by / rb; uz = bz / rb; }
  let ex = ux, ey = uy, ez = uz;
  if (rb > 1e-8) { ex = bx / rb; ey = by / rb; ez = bz / rb; }
  const dot = Math.max(-1, Math.min(1, ux * ex + uy * ey + uz * ez));
  let tx = ex - dot * ux, ty = ey - dot * uy, tz = ez - dot * uz;
  const tangentLength = Math.hypot(tx, ty, tz);
  // atan2 retains small and nearly antipodal angles without acos cancellation.
  const angle = Math.atan2(tangentLength, dot);
  if (tangentLength > 1e-8) {
    tx /= tangentLength; ty /= tangentLength; tz /= tangentLength;
  } else {
    const axis = Math.abs(ux) <= Math.abs(uy) && Math.abs(ux) <= Math.abs(uz)
      ? 0 : Math.abs(uy) <= Math.abs(uz) ? 1 : 2;
    const along = axis === 0 ? ux : axis === 1 ? uy : uz;
    tx = (axis === 0 ? 1 : 0) - along * ux;
    ty = (axis === 1 ? 1 : 0) - along * uy;
    tz = (axis === 2 ? 1 : 0) - along * uz;
    const length = Math.hypot(tx, ty, tz);
    tx /= length; ty /= length; tz /= length;
  }
  // Compensate only for tessellation sag (under 0.5% even for antipodes).
  // Projecting a segment onto either endpoint ray then bounds its radius by
  // the interpolated shell. This also protects the exact attachment segments.
  const sagScale = (1 + 1e-6) / Math.cos(angle / KNOWLEDGE_CROSS_SEGMENTS);
  output[0] = ax; output[1] = ay; output[2] = az;
  for (let step = 1; step < KNOWLEDGE_CROSS_SEGMENTS; step++) {
    const s = step / KNOWLEDGE_CROSS_SEGMENTS;
    const cosine = Math.cos(angle * s), sine = Math.sin(angle * s);
    const radius = (ra + (rb - ra) * s) * sagScale;
    output[step * 3] = radius * (cosine * ux + sine * tx);
    output[step * 3 + 1] = radius * (cosine * uy + sine * ty);
    output[step * 3 + 2] = radius * (cosine * uz + sine * tz);
  }
  const last = KNOWLEDGE_CROSS_SEGMENTS * 3;
  output[last] = bx; output[last + 1] = by; output[last + 2] = bz;
}
