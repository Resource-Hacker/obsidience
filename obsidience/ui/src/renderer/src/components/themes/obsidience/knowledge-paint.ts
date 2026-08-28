/** Node/edge paint pipeline — lifted VERBATIM from Obsidience's
 *  knowledge-graph-backdrop.tsx (2026-08-20) so the Obsidience ball renders
 *  exactly like the original. Only the tone table changed: Obsidience tones
 *  are vault top-folders instead of the workstation subject taxonomy, mapped
 *  onto the SAME branch hues.
 */

import type { KnowledgeHierarchyRole } from "./knowledge-ontology";

export interface KnowledgeBranchPalette {
  core: string;
  dark: string;
  glow: string;
  ring: string;
  edge: string;
  edgeInspect: string;
  edgeActive: string;
}

/* — verbatim: chromaticKnowledgePalette — */
function chromaticKnowledgePalette(
  hue: number,
  saturation: number,
  lightness: number,
): KnowledgeBranchPalette {
  return {
    core: `hsl(${hue}, ${saturation}%, ${lightness}%)`,
    dark: `hsla(${hue}, ${Math.max(38, saturation - 20)}%, 13%, 0.96)`,
    glow: `hsla(${hue}, ${saturation}%, ${lightness}%, 0.22)`,
    ring: `hsla(${hue}, ${saturation}%, ${Math.min(84, lightness + 9)}%, 0.42)`,
    edge: `hsla(${hue}, ${saturation}%, ${lightness}%, 0.17)`,
    edgeInspect: `hsla(${hue}, ${saturation}%, ${lightness}%, 0.32)`,
    edgeActive: `hsla(${hue}, ${saturation}%, ${Math.min(88, lightness + 10)}%, 0.96)`,
  };
}

/* — verbatim: the root ("brain") and neutral palettes — */
export const BRAIN_PALETTE: KnowledgeBranchPalette = {
  core: "#e0f2fe",
  dark: "rgba(12,42,60,0.96)",
  glow: "rgba(224,242,254,0.25)",
  ring: "rgba(224,242,254,0.42)",
  edge: "rgba(186,230,253,0.22)",
  edgeInspect: "rgba(224,242,254,0.34)",
  edgeActive: "rgba(240,249,255,0.96)",
};
export const NEUTRAL_PALETTE: KnowledgeBranchPalette = {
  core: "#67e8f9",
  dark: "rgba(8,47,73,0.96)",
  glow: "rgba(34,211,238,0.18)",
  ring: "rgba(103,232,249,0.3)",
  edge: "rgba(34,211,238,0.15)",
  edgeInspect: "rgba(34,211,238,0.24)",
  edgeActive: "rgba(165,243,252,0.92)",
};

/** Every direct child of the Executive Brain owns one unique, stable hue. The
 *  thirteen known first-level branches are spaced around the whole wheel so
 *  no Executive subject collapses into a shared Agent color. */
const FOLDER_PALETTES: Record<string, KnowledgeBranchPalette> = {
  Personal: chromaticKnowledgePalette(0, 86, 66),
  Tools: chromaticKnowledgePalette(28, 92, 60),
  Games: chromaticKnowledgePalette(55, 94, 58),
  Tasks: chromaticKnowledgePalette(83, 82, 60),
  Websites: chromaticKnowledgePalette(111, 78, 57),
  Observations: chromaticKnowledgePalette(138, 78, 56),
  Architecture: chromaticKnowledgePalette(166, 76, 55),
  "ADMECH Workstation": chromaticKnowledgePalette(194, 91, 60),
  Subagents: chromaticKnowledgePalette(222, 88, 67),
  "News and Research": chromaticKnowledgePalette(249, 84, 72),
  Skills: chromaticKnowledgePalette(277, 86, 70),
  Projects: chromaticKnowledgePalette(305, 84, 68),
  Runbooks: chromaticKnowledgePalette(332, 86, 64),
  Sources: chromaticKnowledgePalette(239, 84, 74),    // news indigo
};
const SPARE_HUES = [199, 271, 350, 130, 43, 239];

/** Satellite balls use the exact hue of the role icon floating above them. */
const AGENT_PALETTES: Record<string, KnowledgeBranchPalette> = {
  Alexandria: chromaticKnowledgePalette(43, 96, 56),   // curator amber #fbbf24
  Darwin: chromaticKnowledgePalette(271, 91, 75),      // researcher violet #c084fc
  Heimdall: chromaticKnowledgePalette(213, 94, 68),    // guardian blue #60a5fa
  library: chromaticKnowledgePalette(157, 88, 59),     // curated library emerald
};

export function paletteForAgent(name: string): KnowledgeBranchPalette {
  const hit = AGENT_PALETTES[name];
  if (hit) return hit;
  let hash = 0;
  for (const ch of name) hash = (hash * 31 + ch.charCodeAt(0)) | 0;
  return chromaticKnowledgePalette([199, 271, 350, 130, 43][Math.abs(hash) % 5], 80, 62);
}

export function paletteForBranch(branch: string | null): KnowledgeBranchPalette {
  if (!branch) return BRAIN_PALETTE;
  const hit = FOLDER_PALETTES[branch];
  if (hit) return hit;
  let hash = 0;
  for (const ch of branch) hash = (hash * 31 + ch.charCodeAt(0)) | 0;
  return chromaticKnowledgePalette(SPARE_HUES[Math.abs(hash) % SPARE_HUES.length], 80, 62);
}

/* — verbatim: knowledgeNodeRadius — */
export function knowledgeNodeRadius(
  role: KnowledgeHierarchyRole | undefined,
  degree: number,
  inspect: boolean,
  depth = role === "root" ? 0 : role === "section" ? 2 : 4,
): number {
  if (role === "root") return 21;
  if (role === "section" && depth <= 1) return 15.5;
  if (role === "section" && depth === 2) return 11;
  if (role === "section") return 8.5;
  if (role === "entity") return 6;
  return (inspect ? 2.2 : 1.5) + Math.min(4.5, Math.sqrt(degree) * 0.55);
}

/* — verbatim: shared 2D/3D style policy — */
export function knowledgeSubjectRingScale(depth: number | undefined): number {
  return depth === 1 ? 1.55 : depth === 2 ? 1.48 : 1.4;
}

export function knowledgeSubjectRingWidth(
  role: KnowledgeHierarchyRole | undefined,
  depth: number | undefined,
): number {
  return role === "root" ? 1.2 : depth === 1 ? 1.15 : depth === 2 ? 0.85 : 0.65;
}

export function knowledgeSubjectGlowScale(
  role: KnowledgeHierarchyRole | undefined,
  depth: number | undefined,
): number {
  return role === "root" ? 3.4 : depth === 1 ? 2.85 : depth === 2 ? 2.35 : 1.9;
}

export function knowledgeNodeBaseAlpha(
  role: KnowledgeHierarchyRole | undefined,
  depth: number | undefined,
  tier: "hot" | "warm" | "cold" | undefined,
): number {
  if (role === "root") return 0.96;
  if (role === "section") {
    return depth === 1 ? 0.96 : depth === 2 ? 0.84 : 0.7;
  }
  if (role === "entity") return 0.58;
  return tier === "cold" ? 0.28 : tier === "warm" ? 0.5 : 0.7;
}

/* — verbatim: knowledgeAmbientEdgeStroke (contradicts tint + branch edge) — */
export function knowledgeAmbientEdgeStroke(
  contradicts: boolean,
  taxonomy: boolean,
  palette: KnowledgeBranchPalette,
): string {
  if (contradicts) return "rgba(251,113,133,0.16)";
  return taxonomy ? palette.edge : "rgba(34,211,238,0.055)";
}

/* — verbatim: lifecycle exceptions from nodeColor — */
export function nodeCoreColor(
  palette: KnowledgeBranchPalette,
  role: KnowledgeHierarchyRole | undefined,
  status: string | null | undefined,
): string {
  if (role === "root" || role === "section" || role === "entity") return palette.core;
  if (status === "failed" || status === "blocked") return "#fb7185";
  if (status === "archived") return "#475569";
  return palette.core;
}
