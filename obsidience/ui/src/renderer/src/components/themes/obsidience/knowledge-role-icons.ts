// Role icons (owner 2026-08-03): WeakAuras-style — see-through 2D neon
// glyphs, one per ROLE. Painted to canvases so they serve both DOM chrome
// and the 3D nameplate sprites (THREE.CanvasTexture).
//   executive  → robot head (cyan)
//   curator    → brain with a wrench over it, gear in the back layer (amber)
//   researcher → purple flask bubbling with liquid
//   guardian   → blue shield
//   library    → open book (emerald) — Library, the shared knowledge
//                library (owner 2026-08-04): a passive vault, not an actor

export type KnowledgeRole =
  | "executive"
  | "curator"
  | "researcher"
  | "guardian"
  | "library";

const ROLE_TINTS: Record<KnowledgeRole, string> = {
  executive: "#67e8f9",
  curator: "#fbbf24",
  researcher: "#c084fc",
  guardian: "#60a5fa",
  library: "#34d399",
};

export function knowledgeRoleTint(role: KnowledgeRole): string {
  return ROLE_TINTS[role];
}

function neonStroke(
  ctx: CanvasRenderingContext2D,
  tint: string,
  width: number,
): void {
  ctx.strokeStyle = tint;
  ctx.lineWidth = width;
  ctx.lineJoin = "round";
  ctx.lineCap = "round";
  ctx.shadowColor = tint;
  ctx.shadowBlur = width * 3;
}

function paintExecutive(ctx: CanvasRenderingContext2D, s: number): void {
  const tint = ROLE_TINTS.executive;
  neonStroke(ctx, tint, s * 0.035);
  // Robot head: rounded rect skull, eye band, antenna.
  const w = s * 0.5;
  const h = s * 0.44;
  const x = (s - w) / 2;
  const y = s * 0.3;
  ctx.beginPath();
  ctx.roundRect(x, y, w, h, s * 0.08);
  ctx.stroke();
  ctx.globalAlpha = 0.16;
  ctx.fillStyle = tint;
  ctx.fill();
  ctx.globalAlpha = 1;
  // Eyes.
  ctx.globalAlpha = 0.9;
  for (const ex of [x + w * 0.28, x + w * 0.72]) {
    ctx.beginPath();
    ctx.arc(ex, y + h * 0.42, s * 0.045, 0, Math.PI * 2);
    ctx.fillStyle = "#ffffff";
    ctx.fill();
  }
  ctx.globalAlpha = 1;
  // Mouth grille.
  ctx.beginPath();
  ctx.moveTo(x + w * 0.3, y + h * 0.74);
  ctx.lineTo(x + w * 0.7, y + h * 0.74);
  ctx.stroke();
  // Antenna.
  ctx.beginPath();
  ctx.moveTo(s / 2, y);
  ctx.lineTo(s / 2, y - s * 0.12);
  ctx.stroke();
  ctx.beginPath();
  ctx.arc(s / 2, y - s * 0.15, s * 0.03, 0, Math.PI * 2);
  ctx.stroke();
}

function paintGear(
  ctx: CanvasRenderingContext2D,
  cx: number,
  cy: number,
  radius: number,
  tint: string,
): void {
  ctx.save();
  ctx.globalAlpha = 0.45;
  neonStroke(ctx, tint, radius * 0.18);
  const teeth = 8;
  for (let i = 0; i < teeth; i += 1) {
    const angle = (i / teeth) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(cx + Math.cos(angle) * radius, cy + Math.sin(angle) * radius);
    ctx.lineTo(
      cx + Math.cos(angle) * radius * 1.3,
      cy + Math.sin(angle) * radius * 1.3,
    );
    ctx.stroke();
  }
  ctx.beginPath();
  ctx.arc(cx, cy, radius, 0, Math.PI * 2);
  ctx.stroke();
  ctx.restore();
}

function paintCurator(ctx: CanvasRenderingContext2D, s: number): void {
  // A set of interlocking gears (owner 2026-08-03: replaced the earlier
  // brain-and-wrench glyph).
  const tint = ROLE_TINTS.curator;
  const gear = (
    cx: number,
    cy: number,
    radius: number,
    teeth: number,
    phase: number,
    alpha: number,
  ): void => {
    ctx.save();
    ctx.globalAlpha = alpha;
    neonStroke(ctx, tint, radius * 0.16);
    for (let i = 0; i < teeth; i += 1) {
      const angle = phase + (i / teeth) * Math.PI * 2;
      ctx.beginPath();
      ctx.moveTo(
        cx + Math.cos(angle) * radius,
        cy + Math.sin(angle) * radius,
      );
      ctx.lineTo(
        cx + Math.cos(angle) * radius * 1.32,
        cy + Math.sin(angle) * radius * 1.32,
      );
      ctx.stroke();
    }
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.stroke();
    ctx.globalAlpha = alpha * 0.16;
    ctx.fillStyle = tint;
    ctx.fill();
    ctx.globalAlpha = alpha;
    // Hub hole.
    ctx.beginPath();
    ctx.arc(cx, cy, radius * 0.32, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  };
  // Large drive gear, small idler meshing at its lower right, and a faint
  // third in the back layer for depth.
  gear(s * 0.63, s * 0.3, s * 0.1, 8, 0.2, 0.4);
  gear(s * 0.42, s * 0.44, s * 0.17, 9, 0, 0.95);
  gear(s * 0.66, s * 0.66, s * 0.11, 7, 0.35, 0.85);
}

function paintResearcher(ctx: CanvasRenderingContext2D, s: number): void {
  const tint = ROLE_TINTS.researcher;
  neonStroke(ctx, tint, s * 0.035);
  // Erlenmeyer flask.
  const topY = s * 0.24;
  const neckHalf = s * 0.06;
  const baseY = s * 0.76;
  const baseHalf = s * 0.24;
  ctx.beginPath();
  ctx.moveTo(s / 2 - neckHalf, topY);
  ctx.lineTo(s / 2 - neckHalf, s * 0.42);
  ctx.lineTo(s / 2 - baseHalf, baseY);
  ctx.quadraticCurveTo(s / 2, baseY + s * 0.1, s / 2 + baseHalf, baseY);
  ctx.lineTo(s / 2 + neckHalf, s * 0.42);
  ctx.lineTo(s / 2 + neckHalf, topY);
  ctx.stroke();
  // Liquid fill.
  ctx.globalAlpha = 0.35;
  ctx.fillStyle = tint;
  ctx.beginPath();
  ctx.moveTo(s / 2 - baseHalf * 0.82, baseY - s * 0.045);
  ctx.lineTo(s / 2 + baseHalf * 0.82, baseY - s * 0.045);
  ctx.quadraticCurveTo(s / 2, baseY + s * 0.08, s / 2 - baseHalf * 0.82, baseY - s * 0.045);
  ctx.fill();
  ctx.globalAlpha = 1;
  // Bubbles rising out of the neck.
  ctx.globalAlpha = 0.85;
  for (const [bx, by, br] of [
    [0.46, 0.6, 0.02],
    [0.55, 0.52, 0.025],
    [0.5, 0.34, 0.02],
    [0.56, 0.2, 0.028],
    [0.44, 0.14, 0.02],
  ] as const) {
    ctx.beginPath();
    ctx.arc(s * bx, s * by, s * br, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

function paintGuardian(ctx: CanvasRenderingContext2D, s: number): void {
  const tint = ROLE_TINTS.guardian;
  neonStroke(ctx, tint, s * 0.04);
  // Shield: flat top, tapering point.
  const top = s * 0.2;
  const left = s * 0.26;
  const right = s * 0.74;
  ctx.beginPath();
  ctx.moveTo(left, top);
  ctx.lineTo(right, top);
  ctx.lineTo(right, s * 0.52);
  ctx.quadraticCurveTo(right, s * 0.72, s / 2, s * 0.84);
  ctx.quadraticCurveTo(left, s * 0.72, left, s * 0.52);
  ctx.closePath();
  ctx.stroke();
  ctx.globalAlpha = 0.18;
  ctx.fillStyle = tint;
  ctx.fill();
  ctx.globalAlpha = 1;
  // Center boss line.
  ctx.globalAlpha = 0.8;
  ctx.beginPath();
  ctx.moveTo(s / 2, top + s * 0.08);
  ctx.lineTo(s / 2, s * 0.72);
  ctx.stroke();
  ctx.globalAlpha = 1;
}

function paintLibrary(ctx: CanvasRenderingContext2D, s: number): void {
  const tint = ROLE_TINTS.library;
  neonStroke(ctx, tint, s * 0.035);
  // Open book: two page panels meeting at a center spine.
  const top = s * 0.3;
  const bottom = s * 0.72;
  const mid = s / 2;
  const edge = s * 0.2;
  ctx.beginPath();
  ctx.moveTo(mid, top + s * 0.05);
  ctx.quadraticCurveTo(mid - s * 0.16, top - s * 0.03, edge, top + s * 0.04);
  ctx.lineTo(edge, bottom);
  ctx.quadraticCurveTo(mid - s * 0.16, bottom - s * 0.07, mid, bottom + s * 0.02);
  ctx.quadraticCurveTo(mid + s * 0.16, bottom - s * 0.07, s - edge, bottom);
  ctx.lineTo(s - edge, top + s * 0.04);
  ctx.quadraticCurveTo(mid + s * 0.16, top - s * 0.03, mid, top + s * 0.05);
  ctx.stroke();
  ctx.globalAlpha = 0.16;
  ctx.fillStyle = tint;
  ctx.fill();
  ctx.globalAlpha = 1;
  // Spine.
  ctx.globalAlpha = 0.8;
  ctx.beginPath();
  ctx.moveTo(mid, top + s * 0.05);
  ctx.lineTo(mid, bottom + s * 0.02);
  ctx.stroke();
  // Text lines on each page.
  ctx.globalAlpha = 0.6;
  for (const [x0, x1] of [
    [edge + s * 0.045, mid - s * 0.075],
    [mid + s * 0.075, s - edge - s * 0.045],
  ] as const) {
    for (const ly of [0.42, 0.51, 0.6] as const) {
      ctx.beginPath();
      ctx.moveTo(x0, s * ly);
      ctx.lineTo(x1, s * ly);
      ctx.stroke();
    }
  }
  ctx.globalAlpha = 1;
}

const PAINTERS: Record<KnowledgeRole, (c: CanvasRenderingContext2D, s: number) => void> = {
  executive: paintExecutive,
  curator: paintCurator,
  researcher: paintResearcher,
  guardian: paintGuardian,
  library: paintLibrary,
};

export function knowledgeRoleForAgent(agentId: string): KnowledgeRole {
  // Obsidience uses stable role ids while Obsidience's graph satellites use
  // their visible agent names. Resolve both forms centrally so DOM controls
  // and the floating THREE.Sprite plates can never disagree.
  const identity = agentId.trim().split("/").filter(Boolean).pop()?.toLowerCase() ?? "";
  if (identity === "alexandria" || identity === "curator") return "curator";
  if (identity === "darwin" || identity === "researcher") return "researcher";
  if (identity === "heimdall" || identity === "guardian") return "guardian";
  if (identity === "library" || identity === "library") return "library";
  // The main agent and unknown future roles remain visibly executive rather
  // than losing their nameplate.
  return "executive";
}

/** Paint a role glyph onto a fresh square canvas (transparent background,
 *  neon translucent strokes) — DOM <img>/<canvas> and THREE.CanvasTexture
 *  both consume it. */
export function paintKnowledgeRoleIcon(
  role: KnowledgeRole,
  size: number,
): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (ctx) PAINTERS[role](ctx, size);
  return canvas;
}
