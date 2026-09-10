/** One shell-following route for links, Review paint and travelling streaks.
 *  Coordinates are in the cloud's local space, before orbit/scale. */
export const KNOWLEDGE_CROSS_SEGMENTS = 32;

/** Call with endpoints in stable ID order; reverse the samples for a reversed
 *  rendered edge. This also gives antipodal links one stable side to go around.
 *  Equal endpoint radii follow their shell; different radii transition smoothly
 *  between shells. No article-size offset, raised leads or extra outward bow. */
export function writeKnowledgeCrossRoute(
  output: Float32Array,
  a: readonly number[],
  b: readonly number[],
): void {
  const ra = Math.hypot(...a);
  const rb = Math.hypot(...b);
  const u = ra > 1e-8 ? a.map(value => value / ra)
    : rb > 1e-8 ? b.map(value => value / rb) : [1, 0, 0];
  const end = rb > 1e-8 ? b.map(value => value / rb) : u;
  const dot = Math.max(-1, Math.min(1, u.reduce((sum, value, i) => sum + value * end[i], 0)));
  const tangent = end.map((value, i) => value - dot * u[i]);
  const tangentLength = Math.hypot(...tangent);
  // atan2 retains small and nearly antipodal angles without acos cancellation.
  const angle = Math.atan2(tangentLength, dot);
  if (tangentLength > 1e-8) {
    for (let axis = 0; axis < 3; axis++) tangent[axis] /= tangentLength;
  } else {
    const axis = Math.abs(u[0]) <= Math.abs(u[1]) && Math.abs(u[0]) <= Math.abs(u[2])
      ? 0 : Math.abs(u[1]) <= Math.abs(u[2]) ? 1 : 2;
    for (let i = 0; i < 3; i++) tangent[i] = (i === axis ? 1 : 0) - u[axis] * u[i];
    const length = Math.hypot(...tangent);
    for (let i = 0; i < 3; i++) tangent[i] /= length;
  }
  // Compensate only for tessellation sag (under 0.5% even for antipodes).
  // Projecting a segment onto either endpoint ray then bounds its radius by
  // the interpolated shell. This also protects the exact attachment segments.
  const sagScale = (1 + 1e-6) / Math.cos(angle / KNOWLEDGE_CROSS_SEGMENTS);
  output.set(a, 0);
  for (let step = 1; step < KNOWLEDGE_CROSS_SEGMENTS; step++) {
    const s = step / KNOWLEDGE_CROSS_SEGMENTS;
    const phi = angle * s;
    const radius = (ra + (rb - ra) * s) * sagScale;
    for (let axis = 0; axis < 3; axis++) {
      const direction = Math.cos(phi) * u[axis] + Math.sin(phi) * tangent[axis];
      output[step * 3 + axis] = radius * direction;
    }
  }
  output.set(b, KNOWLEDGE_CROSS_SEGMENTS * 3);
}
