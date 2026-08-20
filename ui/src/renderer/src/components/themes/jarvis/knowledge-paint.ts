/** Node/edge paint pipeline — lifted VERBATIM from HEREBRUM's
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

/** Obsidience branches on the original hue wheel (hues verbatim from
 *  KNOWLEDGE_MAIN_BRANCH_HUES; sat/light pairs from the original table). */
/** The Agent subtree wears HEREBRUM's agent branch verbatim: hue 173 with
 *  the original sub-tone sat/light pairs (agent/agentTasks/agentRunbooks/
 *  agentSkills/agentTools). World-knowledge folders get the other main hues. */
const FOLDER_PALETTES: Record<string, KnowledgeBranchPalette> = {
  Agent: chromaticKnowledgePalette(173, 66, 50),      // agent
  Tasks: chromaticKnowledgePalette(173, 58, 64),      // agentTasks
  Runbooks: chromaticKnowledgePalette(173, 84, 52),   // agentRunbooks
  Skills: chromaticKnowledgePalette(173, 88, 68),     // agentSkills
  Tools: chromaticKnowledgePalette(173, 74, 62),      // agentTools
  Sources: chromaticKnowledgePalette(239, 84, 74),    // news indigo
};
const SPARE_HUES = [199, 271, 350, 130, 43, 239];

/** Satellite agents wear their own branch hues (HEREBRUM main-hue wheel). */
const AGENT_PALETTES: Record<string, KnowledgeBranchPalette> = {
  Alexandria: chromaticKnowledgePalette(271, 91, 75),  // curator violet
  Darwin: chromaticKnowledgePalette(130, 88, 62),      // researcher green
  Heimdall: chromaticKnowledgePalette(43, 96, 56),     // guardian gold
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
