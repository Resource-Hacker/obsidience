/** Thin Obsidience host for Obsidience's unchanged graph tuning records. */

import {
  DEFAULT_KNOWLEDGE_3D_TUNING,
  clampKnowledge3dTuning,
  type Knowledge3dTuning,
} from "@/components/themes/obsidience/knowledge-3d";

export const MAIN_GRAPH_ID = "main";
export const LIBRARY_GRAPH_ID = "library";

const PROFILE_KEY = "obsidience.graph-tuning-profiles.v2";
export const DEFAULT_GRAPH_TUNING_PROFILE = "Default";

export interface GraphTuningProfiles {
  active: string;
  profiles: Record<string, Knowledge3dTuning>;
}

export type GraphTuningProfileStore = Record<string, GraphTuningProfiles>;

export function loadGraphTuningProfileStore(): GraphTuningProfileStore {
  try {
    const parsed = JSON.parse(localStorage.getItem(PROFILE_KEY) ?? "{}") as GraphTuningProfileStore;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function persistGraphTuningProfileStore(store: GraphTuningProfileStore): void {
  try {
    localStorage.setItem(PROFILE_KEY, JSON.stringify(store));
  } catch {
    // Presentation persistence is best-effort.
  }
}

export function graphTuningProfilesFor(
  store: GraphTuningProfileStore,
  graphId: string,
): GraphTuningProfiles {
  const current = store[graphId];
  if (current?.profiles[current.active]) return current;
  return {
    active: DEFAULT_GRAPH_TUNING_PROFILE,
    profiles: { [DEFAULT_GRAPH_TUNING_PROFILE]: loadGraphTuning(graphId) },
  };
}

export function saveGraphTuningProfile(
  graphId: string,
  name: string,
  tuning: Knowledge3dTuning,
): GraphTuningProfileStore {
  const profile = name.trim().slice(0, 24);
  const store = loadGraphTuningProfileStore();
  if (!profile || profile === "__new__") return store;
  const current = graphTuningProfilesFor(store, graphId);
  if (!(profile in current.profiles) && Object.keys(current.profiles).length >= 32) {
    return store;
  }
  const record = clampKnowledge3dTuning(tuning);
  const next = {
    ...store,
    [graphId]: {
      active: profile,
      profiles: { ...current.profiles, [profile]: record },
    },
  };
  persistGraphTuningProfileStore(next);
  saveGraphTuning(graphId, record);
  announceGraphTuning({ graphId, tuning: record });
  return next;
}

export function selectGraphTuningProfile(
  graphId: string,
  name: string,
): GraphTuningProfileStore {
  const store = loadGraphTuningProfileStore();
  const current = graphTuningProfilesFor(store, graphId);
  const record = current.profiles[name];
  if (!record) return store;
  const next = {
    ...store,
    [graphId]: { ...current, active: name },
  };
  persistGraphTuningProfileStore(next);
  saveGraphTuning(graphId, record);
  announceGraphTuning({ graphId, tuning: record });
  return next;
}

/**
 * The exact active Obsidience records recovered from its Chromium Local Storage
 * on 2026-08-20.  Keep these role-keyed: Obsidience uses visible agent names
 * while Obsidience persisted the stable role ids.
 */
const EXECUTIVE_TUNING: Knowledge3dTuning = clampKnowledge3dTuning({
  ...DEFAULT_KNOWLEDGE_3D_TUNING,
  sweepSeconds: 1.6, sweepMaxSeconds: 5, sweepSpeed: 3,
  ring2dPeers: 1, ring2dBranches: 1, ring2dArticles: 1,
  shellBase: 22, shellStep: 9,
  chargeStrength: 30, velocityDecay: 0.35,
  nodeGlow: 1, tendrilWidth: 12, branchWidth: 8, articleWidth: 4,
  crossWidth: 10, branchOpacity: 0.75, crossOpacity: 0.2,
  dashFrequency: 0.32, crossCurve: 0.2, linkDistance: 1,
  sizeCore: 1.25, sizeBranch: 1, sizeSubnode: 1, sizeChild: 1, sizeArticle: 1.5,
  streakSpeed: 0.4, streakSpan: 0.05, streakCount: 1,
  yawSpeed: 0.05, labelDistance: 1,
  lineArticles: 0, lineBranches: 1, linePeers: 0,
  graphScale: 1, subjectStyle: 0, subnodeStyle: 0, articleStyle: 0,
  ringStyle: 0, coreStyle: 0, rolePlates: 1,
  orbitRadius: 78, orbitSpeed: 0.02, orbitTilt: 25, spinSpeed: 0.07,
  ballScale: 0.45, orbitLine: 0, orbitLineWidth: 2.5, orbitLineOpacity: 0.35,
});

const GUARDIAN_TUNING: Knowledge3dTuning = clampKnowledge3dTuning({
  ...DEFAULT_KNOWLEDGE_3D_TUNING,
  sweepSeconds: 1.6, sweepMaxSeconds: 5, sweepSpeed: 0.7,
  ring2dPeers: 1, ring2dBranches: 1, ring2dArticles: 1,
  shellBase: 22, shellStep: 9, chargeStrength: 30, velocityDecay: 0.35,
  nodeGlow: 0.6, tendrilWidth: 12, branchWidth: 8, articleWidth: 2,
  crossWidth: 6, branchOpacity: 0.75, crossOpacity: 0.75,
  dashFrequency: 0.28, crossCurve: 0.22, linkDistance: 1,
  sizeCore: 1, sizeBranch: 1, sizeSubnode: 1, sizeChild: 1, sizeArticle: 1,
  streakSpeed: 1, streakSpan: 0.06, streakCount: 2,
  yawSpeed: 0.1, labelDistance: 1,
  lineArticles: 0, lineBranches: 1, linePeers: 0,
  graphScale: 0.6, subjectStyle: 0, subnodeStyle: 0, articleStyle: 0,
  ringStyle: 0, coreStyle: 0, rolePlates: 1,
  orbitRadius: 85, orbitSpeed: 0.05, orbitTilt: 25, spinSpeed: 0.15,
  ballScale: 0.45, orbitLine: 1, orbitLineWidth: 8, orbitLineOpacity: 0.2,
});

const CURATOR_TUNING: Knowledge3dTuning = clampKnowledge3dTuning({
  ...DEFAULT_KNOWLEDGE_3D_TUNING,
  sweepSeconds: 1.6, sweepMaxSeconds: 5, sweepSpeed: 0.7,
  ring2dPeers: 1, ring2dBranches: 1, ring2dArticles: 1,
  shellBase: 22, shellStep: 9, chargeStrength: 30, velocityDecay: 0.35,
  nodeGlow: 0.6, tendrilWidth: 24, branchWidth: 20, articleWidth: 4,
  crossWidth: 16, branchOpacity: 0.75, crossOpacity: 0.25,
  dashFrequency: 0.28, crossCurve: 0.4, linkDistance: 1,
  sizeCore: 1, sizeBranch: 1, sizeSubnode: 1, sizeChild: 1, sizeArticle: 1,
  streakSpeed: 1, streakSpan: 0.06, streakCount: 2,
  yawSpeed: 0.2, labelDistance: 1,
  lineArticles: 0, lineBranches: 1, linePeers: 0,
  graphScale: 0.5, subjectStyle: 0, subnodeStyle: 0, articleStyle: 0,
  ringStyle: 0, coreStyle: 3, rolePlates: 1,
  orbitRadius: 100, orbitSpeed: 0.075, orbitTilt: 40, spinSpeed: -0.3,
  ballScale: 0.45, orbitLine: 1, orbitLineWidth: 5, orbitLineOpacity: 0.25,
});

const RESEARCHER_TUNING: Knowledge3dTuning = clampKnowledge3dTuning({
  ...DEFAULT_KNOWLEDGE_3D_TUNING,
  sweepSeconds: 1.6, sweepMaxSeconds: 5, sweepSpeed: 1,
  ring2dPeers: 1, ring2dBranches: 1, ring2dArticles: 1,
  shellBase: 15, shellStep: 10, chargeStrength: 30, velocityDecay: 0.35,
  nodeGlow: 0.6, tendrilWidth: 24, branchWidth: 20, articleWidth: 4,
  crossWidth: 6, branchOpacity: 0.75, crossOpacity: 0.5,
  dashFrequency: 0.28, crossCurve: 0.6,
  sizeCore: 2, sizeBranch: 1, sizeSubnode: 1, sizeChild: 1, sizeArticle: 1,
  streakSpeed: 1, streakSpan: 0.06, streakCount: 2,
  yawSpeed: 0.05, labelDistance: 1,
  lineArticles: 0, lineBranches: 1, linePeers: 0,
  graphScale: 0.4, subjectStyle: 0, subnodeStyle: 0, articleStyle: 0,
  ringStyle: 0, coreStyle: 2, rolePlates: 1,
  orbitRadius: 110, orbitSpeed: 0.2, orbitTilt: 67, spinSpeed: 0.3,
  ballScale: 0.45, orbitLine: 1, orbitLineWidth: 3, orbitLineOpacity: 0.3,
});

const LIBRARY_TUNING: Knowledge3dTuning = clampKnowledge3dTuning({
  ...DEFAULT_KNOWLEDGE_3D_TUNING,
  sweepSeconds: 1.6, sweepMaxSeconds: 5, sweepSpeed: 0.7,
  ring2dPeers: 1, ring2dBranches: 1, ring2dArticles: 1,
  shellBase: 22, shellStep: 9, chargeStrength: 30, velocityDecay: 0.35,
  nodeGlow: 0.6, tendrilWidth: 12, branchWidth: 8, articleWidth: 2,
  crossWidth: 6, branchOpacity: 0.75, crossOpacity: 0.1,
  dashFrequency: 0.5, crossCurve: 0.6, linkDistance: 1,
  sizeCore: 2, sizeBranch: 1, sizeSubnode: 1, sizeChild: 1, sizeArticle: 1,
  streakSpeed: 0.5, streakSpan: 0.01, streakCount: 0,
  yawSpeed: 0.05, labelDistance: 1,
  lineArticles: 0, lineBranches: 1, linePeers: 1,
  graphScale: 0.75, subjectStyle: 0, subnodeStyle: 0, articleStyle: 0,
  ringStyle: 0, coreStyle: 4, rolePlates: 1,
  orbitRadius: 100, orbitSpeed: 0, orbitTilt: 55, spinSpeed: 0.3,
  ballScale: 0.45, orbitLine: 0, orbitLineWidth: 2.5, orbitLineOpacity: 0.35,
});

/** Compatibility export for the main/Executive reset surface. */
export const OWNER_GRAPH_TUNING = EXECUTIVE_TUNING;

export function defaultGraphTuning(graphId: string): Knowledge3dTuning {
  const normalized = graphId.trim().toLowerCase();
  const record = normalized === "heimdall" || normalized === "guardian"
    ? GUARDIAN_TUNING
    : normalized === "alexandria" || normalized === "curator"
      ? CURATOR_TUNING
      : normalized === "darwin" || normalized === "researcher"
        ? RESEARCHER_TUNING
        : normalized === LIBRARY_GRAPH_ID || normalized === "library"
          ? LIBRARY_TUNING
          : EXECUTIVE_TUNING;
  return { ...record };
}

// v3 deliberately starts from the recovered records: the earlier Obsidience
// v1/v2 keys were generic placeholders, not the owner's Obsidience settings.
const tuningKey = (graphId: string) => `obsidience.tuning3d.${encodeURIComponent(graphId)}.v3`;

export function loadGraphTuning(graphId = MAIN_GRAPH_ID): Knowledge3dTuning {
  try {
    const raw = localStorage.getItem(tuningKey(graphId));
    return raw ? clampKnowledge3dTuning(JSON.parse(raw) as unknown) : defaultGraphTuning(graphId);
  } catch {
    return defaultGraphTuning(graphId);
  }
}

export function saveGraphTuning(graphId: string, tuning: Knowledge3dTuning): void {
  try {
    localStorage.setItem(tuningKey(graphId), JSON.stringify(clampKnowledge3dTuning(tuning)));
  } catch {
    // Presentation persistence is best-effort.
  }
}

export interface GraphTuningChange { graphId: string; tuning: Knowledge3dTuning }

export function announceGraphTuning(change: GraphTuningChange): void {
  window.dispatchEvent(new CustomEvent("obsidience:graph-tuning", { detail: change }));
}

export function onGraphTuning(handler: (change: GraphTuningChange) => void): () => void {
  const fn = (event: Event) => handler((event as CustomEvent<GraphTuningChange>).detail);
  window.addEventListener("obsidience:graph-tuning", fn);
  return () => window.removeEventListener("obsidience:graph-tuning", fn);
}

let selectedGraphId = MAIN_GRAPH_ID;

export function selectGraph(graphId: string): void {
  selectedGraphId = graphId || MAIN_GRAPH_ID;
  window.dispatchEvent(new CustomEvent("obsidience:graph-selected", {
    detail: { graphId: selectedGraphId },
  }));
}

export function onGraphSelected(handler: (graphId: string) => void): () => void {
  const fn = (event: Event) => handler(
    (event as CustomEvent<{ graphId: string }>).detail?.graphId ?? MAIN_GRAPH_ID,
  );
  window.addEventListener("obsidience:graph-selected", fn);
  handler(selectedGraphId);
  return () => window.removeEventListener("obsidience:graph-selected", fn);
}

export function requestGraphThinkingTest(graphId: string): void {
  window.dispatchEvent(new CustomEvent("obsidience:graph-thinking-test", {
    detail: { graphId },
  }));
}

export function onGraphThinkingTest(handler: (graphId: string) => void): () => void {
  const fn = (event: Event) => handler(
    (event as CustomEvent<{ graphId: string }>).detail?.graphId ?? MAIN_GRAPH_ID,
  );
  window.addEventListener("obsidience:graph-thinking-test", fn);
  return () => window.removeEventListener("obsidience:graph-thinking-test", fn);
}
