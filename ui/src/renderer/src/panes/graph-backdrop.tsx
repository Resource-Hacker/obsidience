/** Thin host for the copied HEREBRUM 3D scene: Obsidience graph -> render model.
 *  The scene component is pure props (no IPC) — we map /api/graph into
 *  Knowledge3dRenderNode/Edge, seed positions with the copied radial layout,
 *  and let the in-scene d3-force-3d physics take over. */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Knowledge3dScene,
  type Knowledge3dRenderEdge,
  type Knowledge3dRenderNode,
} from "@/components/themes/jarvis/knowledge-3d-scene";
import { DEFAULT_KNOWLEDGE_3D_TUNING } from "@/components/themes/jarvis/knowledge-3d";
import { layoutKnowledgeGraph } from "@/components/themes/jarvis/knowledge-layout";
import { DEFAULT_KNOWLEDGE_HUB_ANCHOR } from "@/components/themes/jarvis/knowledge-geometry";
import { api, openReader, type GraphNode } from "@/lib/api";

interface Palette { core: string; dark: string; ring: string; glow: string }

const KIND_PALETTE: Record<string, Palette> = {
  charter: { core: "#c4b5fd", dark: "#2e1065", ring: "rgba(167,139,250,0.85)", glow: "rgba(139,92,246,0.5)" },
  runbook: { core: "#fcd34d", dark: "#451a03", ring: "rgba(251,191,36,0.85)", glow: "rgba(245,158,11,0.45)" },
  task: { core: "#6ee7b7", dark: "#022c22", ring: "rgba(52,211,153,0.85)", glow: "rgba(16,185,129,0.45)" },
  receipt: { core: "#94a3b8", dark: "#0f172a", ring: "rgba(148,163,184,0.6)", glow: "rgba(100,116,139,0.3)" },
  note: { core: "#67e8f9", dark: "#083344", ring: "rgba(34,211,238,0.85)", glow: "rgba(6,182,212,0.45)" },
};

const TASK_STATUS_RING: Record<string, string> = {
  blocked: "rgba(251,113,133,0.95)",
  active: "rgba(103,232,249,0.95)",
  review: "rgba(251,191,36,0.95)",
  failed: "rgba(244,63,94,0.95)",
};

const LAYOUT_KIND: Record<string, string> = {
  charter: "concept", runbook: "procedure", task: "task", receipt: "event", note: "note",
};

export function GraphBackdrop() {
  const [graph, setGraph] = useState<{ nodes: GraphNode[]; links: { source: string; target: string }[] }>({ nodes: [], links: [] });
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [sceneKey, setSceneKey] = useState(0);
  const titles = useRef(new Map<string, string>());

  useEffect(() => {
    let live = true;
    const pull = () => api.graph().then((g) => { if (live) setGraph(g); }).catch(() => undefined);
    pull();
    const t = setInterval(pull, 15_000);
    return () => { live = false; clearInterval(t); };
  }, []);

  const model = useMemo(() => {
    const degree = new Map<string, number>();
    for (const l of graph.links) {
      degree.set(l.source, (degree.get(l.source) ?? 0) + 1);
      degree.set(l.target, (degree.get(l.target) ?? 0) + 1);
    }
    const layout = layoutKnowledgeGraph({
      nodes: graph.nodes.map((n) => ({
        id: n.id,
        degree: degree.get(n.id) ?? 0,
        kind: (LAYOUT_KIND[n.kind] ?? "note") as never,
        label: n.title,
      })),
      edges: graph.links.map((l, i) => ({
        id: String(i), source: l.source, target: l.target, type: "related_to" as never,
      })),
    });
    const pos = new Map(layout.nodes.map((n) => [n.id, n]));
    titles.current = new Map(graph.nodes.map((n) => [n.id, n.title]));
    const nodes: Knowledge3dRenderNode[] = graph.nodes.map((n) => {
      const p = pos.get(n.id);
      const pal = KIND_PALETTE[n.kind] ?? KIND_PALETTE.note;
      const deg = degree.get(n.id) ?? 0;
      const ring = (n.kind === "task" && n.status && TASK_STATUS_RING[n.status]) || pal.ring;
      return {
        id: n.id,
        x: p?.x ?? 0.5,
        y: p?.y ?? 0.5,
        radius: n.kind === "charter" ? 16 : 7 + Math.min(9, deg * 1.4),
        subject: n.kind === "charter",
        core: pal.core, dark: pal.dark, ring, glow: pal.glow,
        ringScale: 1, ringWidth: n.kind === "task" ? 1.6 : 1, glowScale: 1, alpha: 1,
      };
    });
    const edges: Knowledge3dRenderEdge[] = graph.links.map((l) => ({
      source: l.source, target: l.target,
      color: "rgba(45,212,191,0.32)", taxonomy: true,
    }));
    return { nodes, edges };
  }, [graph]);

  return (
    <div className="absolute inset-0">
      <Knowledge3dScene
        key={sceneKey}
        nodes={model.nodes}
        edges={model.edges}
        hub={DEFAULT_KNOWLEDGE_HUB_ANCHOR}
        focusNodeIds={useMemo(() => new Set<string>(), [])}
        pathSpec={null}
        focusActive={false}
        focusPhase={null}
        visible
        reducedMotion={false}
        adapterPreference="system"
        animationProfile="balanced"
        hoveredNodeId={hoveredId}
        tuning={DEFAULT_KNOWLEDGE_3D_TUNING}
        onHover={setHoveredId}
        onNodeAction={(kind, id) => { if (kind === "click") openReader(id); }}
        onProjected={() => undefined}
        onContextLost={() => setSceneKey((k) => k + 1)}
      />
      {hoveredId ? (
        <div className="pointer-events-none absolute bottom-6 left-1/2 -translate-x-1/2 rounded border border-cyan-300/25 bg-[#030a10]/90 px-3 py-1 font-mono text-[11px] tracking-[0.14em] text-cyan-100">
          {titles.current.get(hoveredId) ?? hoveredId}
        </div>
      ) : null}
    </div>
  );
}
