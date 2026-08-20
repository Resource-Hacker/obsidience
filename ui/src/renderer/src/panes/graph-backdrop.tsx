/** The Obsidience ball: the HEREBRUM 3D engine fed by the vault, using the
 *  ORIGINAL hierarchy layout + paint pipeline + the owner's recovered tuning.
 *  Structure: root "Obsidience" -> knowledge branches -> notes, plus literal
 *  agent satellites and the curated four-shelf Library satellite. Wikilinks
 *  render as cross-link tendrils, exactly like the old ball's
 *  taxonomy-vs-cross-link law. */

import { useEffect, useMemo, useRef, useState } from "react";
import {
  Knowledge3dScene,
  type Knowledge3dRenderEdge,
  type Knowledge3dRenderNode,
} from "@/components/themes/jarvis/knowledge-3d-scene";
import {
  DEFAULT_KNOWLEDGE_3D_TUNING,
  parseKnowledgeAgentNodeId,
  type Knowledge3dTuning,
} from "@/components/themes/jarvis/knowledge-3d";
import { layoutKnowledgeGraph } from "@/components/themes/jarvis/knowledge-layout";
import { DEFAULT_KNOWLEDGE_HUB_ANCHOR } from "@/components/themes/jarvis/knowledge-geometry";
import {
  knowledgeAmbientEdgeStroke,
  knowledgeNodeBaseAlpha,
  knowledgeNodeRadius,
  knowledgeSubjectGlowScale,
  knowledgeSubjectRingScale,
  knowledgeSubjectRingWidth,
  nodeCoreColor,
  paletteForAgent,
  paletteForBranch,
} from "@/components/themes/jarvis/knowledge-paint";
import { api, openReader, type GraphNode } from "@/lib/api";

const ROOT_ID = "@vault";

/** The owner's saved slider profile, recovered from the original app's
 *  storage (tuning3d.v3, 2026-08-20); missing newer fields fall back to the
 *  shipped defaults — the same normalize law the original used. */
const OWNER_TUNING: Knowledge3dTuning = {
  ...DEFAULT_KNOWLEDGE_3D_TUNING,
  sweepSeconds: 1.6, sweepMaxSeconds: 5, sweepSpeed: 2,
  ring2dPeers: 1, ring2dBranches: 1, ring2dArticles: 1,
  shellBase: 22, shellStep: 9,
  chargeStrength: 18, velocityDecay: 0.28,
  nodeGlow: 0.6, tendrilWidth: 13, branchWidth: 8, articleWidth: 3.5,
  crossWidth: 5, branchOpacity: 0.5, crossOpacity: 0.1,
  dashFrequency: 0.28, crossCurve: 0.5,
  streakSpeed: 0.5, streakSpan: 0.025, streakCount: 1,
  yawSpeed: 0.05, labelDistance: 1,
  lineArticles: 0, lineBranches: 1, linePeers: 0,
};

const TUNING_KEY = "obsidience.tuning3d.v1";

function loadTuning(): Knowledge3dTuning {
  try {
    const raw = localStorage.getItem(TUNING_KEY);
    if (!raw) return OWNER_TUNING;
    return { ...OWNER_TUNING, ...(JSON.parse(raw) as Partial<Knowledge3dTuning>) };
  } catch {
    return OWNER_TUNING;
  }
}

export function GraphBackdrop() {
  const [graph, setGraph] = useState<{ nodes: GraphNode[]; links: { source: string; target: string }[] }>({ nodes: [], links: [] });
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [sceneKey, setSceneKey] = useState(0);
  const [viewport, setViewport] = useState({ width: window.innerWidth, height: window.innerHeight });
  const titles = useRef(new Map<string, string>());
  const tuning = useMemo(loadTuning, []);

  useEffect(() => {
    const onResize = () => setViewport({ width: window.innerWidth, height: window.innerHeight });
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => {
    let live = true;
    const pull = () => api.graph().then((g) => { if (live) setGraph(g); }).catch(() => undefined);
    pull();
    const t = setInterval(pull, 15_000);
    window.addEventListener("obsidience:graph-refresh", pull);
    return () => {
      live = false;
      clearInterval(t);
      window.removeEventListener("obsidience:graph-refresh", pull);
    };
  }, []);

  const model = useMemo(() => {
    const all = graph.nodes.filter((n) => !n.id.startsWith("Receipts/"));
    // Literal subagents (HEREBRUM model): each Agents/<Name>/ subtree plus the
    // tasks assigned to that agent render as their OWN satellite ball.
    const agentNames = [...new Set(all.filter((n) => n.id.startsWith("Agents/"))
      .map((n) => n.id.split("/")[1]))].sort();
    const assigneeOf = (n: GraphNode): string | null => {
      const m = /Agents\/([^\]|/]+)/.exec(n.assignee ?? "");
      return m ? m[1] : null;
    };
    const subRef = (raw: string, pool: Set<string>): string | null => {
      const clean = raw.trim().replace(/^\[\[/, "").replace(/\]\]$/, "").split("|")[0].split("#")[0];
      if (pool.has(clean)) return clean;
      const base = clean.split("/").pop()!.toLowerCase();
      for (const id of pool) if (id.split("/").pop()!.toLowerCase() === base) return id;
      return null;
    };
    const childRefsOf = (node: GraphNode): string[] => node.children ?? node.subtasks ?? [];
    const hierarchyParents = (members: GraphNode[]): Map<string, string> => {
      const pool = new Set(members.map((node) => node.id));
      const byId = new Map(members.map((node) => [node.id, node]));
      const parentOf = new Map<string, string>();
      for (const parent of members) {
        for (const raw of childRefsOf(parent)) {
          const child = subRef(raw, pool);
          if (!child || child === parent.id || parentOf.has(child) || byId.get(child)?.kind !== parent.kind) continue;
          let cursor = parent.id;
          let cyclic = false;
          while (parentOf.has(cursor)) {
            cursor = parentOf.get(cursor) as string;
            if (cursor === child) { cyclic = true; break; }
          }
          if (!cyclic) parentOf.set(child, parent.id);
        }
      }
      return parentOf;
    };
    const allIds = new Set(all.map((node) => node.id));
    const checkoutIdsOf = (identity?: GraphNode): Set<string> => new Set(
      Object.values(identity?.checkouts ?? {}).flatMap((values) => values ?? [])
        .map((raw) => subRef(raw, allIds)).filter((ref): ref is string => Boolean(ref)),
    );
    const libraryKinds = new Set(["tool", "skill", "runbook", "task"]);
    const libraryNotes = all.filter((n) => libraryKinds.has(n.kind));
    const hierarchyClosure = (roots: Set<string>): Set<string> => {
      const pool = new Set(libraryNotes.map((node) => node.id));
      const byId = new Map(libraryNotes.map((node) => [node.id, node]));
      const closure = new Set([...roots].filter((ref) => pool.has(ref)));
      const queue = [...closure];
      while (queue.length) {
        const parent = byId.get(queue.shift() as string);
        if (!parent) continue;
        for (const raw of childRefsOf(parent)) {
          const child = subRef(raw, pool);
          if (!child || closure.has(child) || byId.get(child)?.kind !== parent.kind) continue;
          closure.add(child);
          queue.push(child);
        }
      }
      return closure;
    };
    // The four authoring primitives belong to the curated Library satellite;
    // the executive ball carries only its checked-out projections.
    const executiveCheckouts = hierarchyClosure(
      checkoutIdsOf(all.find((node) => node.id === "Agent/Obsidience")),
    );
    const executivePrimitives = libraryNotes.filter((node) => executiveCheckouts.has(node.id));
    const executiveParents = hierarchyParents(executivePrimitives);
    const executiveContainers = new Set(executiveParents.values());
    const notes = [
      ...all.filter((n) => !n.id.startsWith("Agents/") && !libraryKinds.has(n.kind)),
      ...executivePrimitives,
    ];
    const branchOf = (id: string): string | null => (id.includes("/") ? id.split("/", 1)[0] : null);
    const primitiveFolders = ["Tools", "Skills", "Runbooks", "Tasks"]
      .filter((folder) => executivePrimitives.some((node) => branchOf(node.id) === folder));
    const folders = [...new Set(notes.map((n) => branchOf(n.id)).filter(Boolean))] as string[];
    const worldFolders = folders.filter((f) => f !== "Agent" && !primitiveFolders.includes(f)).sort();
    const branches = ["Agent", ...worldFolders];

    const degree = new Map<string, number>();
    const noteIds = new Set(notes.map((n) => n.id));
    const crossLinks = graph.links.filter((l) => noteIds.has(l.source) && noteIds.has(l.target));
    for (const l of crossLinks) {
      degree.set(l.source, (degree.get(l.source) ?? 0) + 1);
      degree.set(l.target, (degree.get(l.target) ?? 0) + 1);
    }

    // Hierarchy input: root -> branch sections -> leaf notes (role "claim").
    const layoutNodes = [
      { id: ROOT_ID, degree: branches.length, kind: "concept" as never, label: "Obsidience", role: "root" as never, parentId: null, order: 0 },
      ...branches.map((b, i) => ({
        id: `@branch/${b}`, degree: notes.filter((n) => branchOf(n.id) === b).length,
        kind: "concept" as never, label: b, role: "section" as never, parentId: ROOT_ID, order: i,
      })),
      ...primitiveFolders.map((folder, index) => ({
        id: `@branch/${folder}`, degree: executivePrimitives.filter((node) => branchOf(node.id) === folder).length,
        kind: "concept" as never, label: folder, role: "section" as never, parentId: "@branch/Agent", order: index,
      })),
      ...notes.map((n, i) => {
        const container = executiveParents.get(n.id);
        const isContainer = executiveContainers.has(n.id);
        return {
          id: n.id, degree: degree.get(n.id) ?? 0, kind: "note" as never, label: n.title,
          role: (isContainer ? "section" : "claim") as never,
          parentId: container ?? (n.id.includes("/") ? `@branch/${branchOf(n.id)}` : ROOT_ID),
          order: i,
        };
      }),
    ];
    const taxonomyEdges = layoutNodes
      .filter((n) => n.parentId)
      .map((n, i) => ({ id: `t${i}`, source: n.parentId as string, target: n.id, type: "related_to" as never }));
    const crossEdges = crossLinks.filter((link) => executiveParents.get(link.target) !== link.source).map((l, i) => ({
      id: `x${i}`, source: l.source, target: l.target, type: "related_to" as never,
    }));

    const layout = layoutKnowledgeGraph({
      anchor: DEFAULT_KNOWLEDGE_HUB_ANCHOR,
      viewport: {
        width: viewport.width,
        height: viewport.height,
        bounds: { left: 0, right: viewport.width, top: 0, bottom: viewport.height },
      },
      nodes: layoutNodes,
      edges: [...taxonomyEdges, ...crossEdges],
      ringScales: { peers: tuning.ring2dPeers, branches: tuning.ring2dBranches, articles: tuning.ring2dArticles },
      circularStage: true,
    });
    const pos = new Map(layout.nodes.map((n) => [n.id, n]));
    const meta = new Map(notes.map((n) => [n.id, n]));
    titles.current = new Map([
      [ROOT_ID, "Obsidience"],
      ...[...branches, ...primitiveFolders].map((b) => [`@branch/${b}`, b] as [string, string]),
      ...notes.map((n) => [n.id, n.title] as [string, string]),
    ]);

    // — the original buildKnowledge3dRenderModel law, tone = top folder —
    const renderNodes: Knowledge3dRenderNode[] = layout.nodes.map((p) => {
      const role = p.role as never as ("root" | "section" | "claim" | undefined);
      const branch = p.id === ROOT_ID ? null
        : p.id.startsWith("@branch/") ? p.id.slice(8)
        : branchOf(p.id);
      const palette = p.id === ROOT_ID ? paletteForBranch(null) : paletteForBranch(branch);
      const subject = role === "root" || role === "section";
      const noteMeta = meta.get(p.id);
      return {
        id: p.id, x: p.x, y: p.y, depth: p.depth, role, parentId: p.parentId,
        radius: knowledgeNodeRadius(role, degree.get(p.id) ?? 0, false, p.depth),
        subject,
        core: nodeCoreColor(palette, role, noteMeta?.status),
        dark: palette.dark,
        ring: subject ? palette.ring : "rgba(0,0,0,0)",
        glow: subject ? palette.glow : "rgba(0,0,0,0)",
        ringScale: knowledgeSubjectRingScale(p.depth),
        ringWidth: knowledgeSubjectRingWidth(role, p.depth),
        glowScale: subject ? knowledgeSubjectGlowScale(role, p.depth) : 1,
        alpha: knowledgeNodeBaseAlpha(role, p.depth, "hot"),
      };
    });
    const paletteOf = (id: string) =>
      id === ROOT_ID ? paletteForBranch(null) : paletteForBranch(id.startsWith("@branch/") ? id.slice(8) : branchOf(id));
    const renderEdges: Knowledge3dRenderEdge[] = [
      // Taxonomy beams carry the full-saturation branch hue (original law).
      ...taxonomyEdges.map((e) => ({
        source: e.source, target: e.target, taxonomy: true,
        color: paletteOf(e.target).core,
      })),
      // Cross-links keep the dim 2D stroke and the REVERSED far-end gradient.
      ...crossEdges.map((e) => ({
        source: e.source, target: e.target, taxonomy: false,
        color: knowledgeAmbientEdgeStroke(false, false, paletteOf(e.source)),
        colorEnd: paletteOf(e.target).core,
      })),
    ];
    // ---- satellites: one ball per agent, seeded by its own mini hierarchy ----
    const linkPairs = graph.links;
    const agentSatellites = agentNames.map((name) => {
      const identityRef = `Agents/${name}/${name}`;
      const assigned = new Set(all.filter((node) => node.kind === "task" && assigneeOf(node) === name)
        .map((node) => node.id));
      const checkedOut = hierarchyClosure(new Set([
        ...checkoutIdsOf(all.find((node) => node.id === identityRef)),
        ...assigned,
      ]));
      const members = all.filter((n) =>
        (n.id.startsWith(`Agents/${name}/`) && n.id !== identityRef) ||
        checkedOut.has(n.id));
      const primitiveMembers = members.filter((member) => libraryKinds.has(member.kind));
      const primitiveParents = hierarchyParents(primitiveMembers);
      const primitiveContainers = new Set(primitiveParents.values());
      const satelliteFolders = ["Tools", "Skills", "Runbooks", "Tasks"]
        .filter((folder) => primitiveMembers.some((member) => branchOf(member.id) === folder));
      const satLayoutNodes = [
        { id: identityRef, degree: members.length, kind: "concept" as never, label: name, role: "root" as never, parentId: null as string | null, order: 0 },
        ...satelliteFolders.map((folder, index) => ({
          id: `@sat/${name}/${folder.toLowerCase()}`, degree: primitiveMembers.filter((member) => branchOf(member.id) === folder).length,
          kind: "concept" as never, label: folder, role: "section" as never, parentId: identityRef, order: index,
        })),
        ...members.map((n, i) => ({
          id: n.id, degree: 0, kind: "note" as never, label: n.title,
          role: (primitiveContainers.has(n.id) ? "section" : "claim") as never,
          parentId: primitiveParents.get(n.id) ?? (libraryKinds.has(n.kind)
            ? `@sat/${name}/${String(branchOf(n.id)).toLowerCase()}` : identityRef),
          order: i,
        })),
      ];
      const satLayout = layoutKnowledgeGraph({
        nodes: satLayoutNodes,
        edges: satLayoutNodes.filter((n) => n.parentId)
          .map((n, i) => ({ id: `s${i}`, source: n.parentId as string, target: n.id, type: "related_to" as never })),
      });
      const satPos = new Map(satLayout.nodes.map((n) => [n.id, n]));
      const pal = paletteForAgent(name);
      const memberSet = new Set(satLayoutNodes.map((n) => n.id));
      const satNodes: Knowledge3dRenderNode[] = satLayoutNodes.map((ln) => {
        const pp = satPos.get(ln.id);
        const role = ln.role as never as ("root" | "section" | "claim");
        const subject = role === "root" || role === "section";
        const noteMeta = all.find((n) => n.id === ln.id);
        return {
          id: ln.id, x: pp?.x ?? 0.5, y: pp?.y ?? 0.5, depth: pp?.depth,
          role, parentId: pp?.parentId,
          radius: knowledgeNodeRadius(role, 1, false, pp?.depth),
          subject,
          core: nodeCoreColor(pal, subject ? role : undefined, noteMeta?.status),
          dark: pal.dark,
          ring: subject ? pal.ring : "rgba(0,0,0,0)",
          glow: subject ? pal.glow : "rgba(0,0,0,0)",
          ringScale: knowledgeSubjectRingScale(pp?.depth),
          ringWidth: knowledgeSubjectRingWidth(subject ? role : undefined, pp?.depth),
          glowScale: subject ? knowledgeSubjectGlowScale(role, pp?.depth) : 1,
          alpha: knowledgeNodeBaseAlpha(subject ? role : undefined, pp?.depth, "hot"),
        };
      });
      const satEdges: Knowledge3dRenderEdge[] = [
        ...satLayoutNodes.filter((n) => n.parentId)
          .map((n) => ({ source: n.parentId as string, target: n.id, taxonomy: true, color: pal.core })),
        ...linkPairs.filter((l) => memberSet.has(l.source) && memberSet.has(l.target) && l.source !== identityRef)
          .filter((l) => primitiveParents.get(l.target) !== l.source)
          .map((l) => ({ source: l.source, target: l.target, taxonomy: false,
                         color: knowledgeAmbientEdgeStroke(false, false, pal), colorEnd: pal.core })),
      ];
      for (const ref of memberSet) {
        const n = all.find((x) => x.id === ref);
        titles.current.set(`agent:${name}/${ref}`,
          n?.title ?? (ref === identityRef ? name : satelliteFolders.find((folder) => ref === `@sat/${name}/${folder.toLowerCase()}`) ?? ref));
      }
      return { agentId: name, nodes: satNodes, edges: satEdges, tuning };
    });
    // HEREBRUM's Library returns as a first-class green satellite. Its four
    // shelves hold the accepted primitive notes; every primitive keeps its
    // recursively authored hierarchy inside its own shelf.
    const libraryRoot = "@library";
    const shelfOrder = ["tool", "skill", "runbook", "task"] as const;
    const shelfLabels = { tool: "Tools", skill: "Skills", runbook: "Runbooks", task: "Tasks" };
    const libraryParents = hierarchyParents(libraryNotes);
    const libraryContainers = new Set(libraryParents.values());
    const libraryLayoutNodes = [
      { id: libraryRoot, degree: libraryNotes.length, kind: "concept" as never, label: "Library", role: "root" as never, parentId: null as string | null, order: 0 },
      ...shelfOrder.map((kind, index) => ({
        id: `@library/${shelfLabels[kind]}`,
        degree: libraryNotes.filter((node) => node.kind === kind).length,
        kind: "concept" as never,
        label: shelfLabels[kind],
        role: "section" as never,
        parentId: libraryRoot,
        order: index,
      })),
      ...libraryNotes.map((node, index) => ({
        id: node.id,
        degree: 0,
        kind: "note" as never,
        label: node.title,
        role: (libraryContainers.has(node.id) ? "section" : "claim") as never,
        parentId: libraryParents.get(node.id) ?? `@library/${shelfLabels[node.kind as keyof typeof shelfLabels]}`,
        order: index,
      })),
    ];
    const libraryLayout = layoutKnowledgeGraph({
      nodes: libraryLayoutNodes,
      edges: libraryLayoutNodes.filter((node) => node.parentId).map((node, index) => ({
        id: `l${index}`, source: node.parentId as string, target: node.id, type: "related_to" as never,
      })),
    });
    const libraryPositions = new Map(libraryLayout.nodes.map((node) => [node.id, node]));
    const libraryPalette = paletteForAgent("library");
    const librarySet = new Set(libraryLayoutNodes.map((node) => node.id));
    const libraryRenderNodes: Knowledge3dRenderNode[] = libraryLayoutNodes.map((node) => {
      const point = libraryPositions.get(node.id);
      const role = node.role as never as ("root" | "section" | "claim");
      const subject = role === "root" || role === "section";
      const noteMeta = libraryNotes.find((note) => note.id === node.id);
      return {
        id: node.id, x: point?.x ?? 0.5, y: point?.y ?? 0.5, depth: point?.depth,
        role, parentId: point?.parentId,
        radius: knowledgeNodeRadius(role, 1, false, point?.depth),
        subject,
        core: nodeCoreColor(libraryPalette, subject ? role : undefined, noteMeta?.status),
        dark: libraryPalette.dark,
        ring: subject ? libraryPalette.ring : "rgba(0,0,0,0)",
        glow: subject ? libraryPalette.glow : "rgba(0,0,0,0)",
        ringScale: knowledgeSubjectRingScale(point?.depth),
        ringWidth: knowledgeSubjectRingWidth(subject ? role : undefined, point?.depth),
        glowScale: subject ? knowledgeSubjectGlowScale(role, point?.depth) : 1,
        alpha: knowledgeNodeBaseAlpha(subject ? role : undefined, point?.depth, "hot"),
      };
    });
    const libraryRenderEdges: Knowledge3dRenderEdge[] = [
      ...libraryLayoutNodes.filter((node) => node.parentId).map((node) => ({
        source: node.parentId as string, target: node.id, taxonomy: true, color: libraryPalette.core,
      })),
      ...linkPairs.filter((link) => librarySet.has(link.source) && librarySet.has(link.target))
        .filter((link) => libraryParents.get(link.target) !== link.source).map((link) => ({
        source: link.source, target: link.target, taxonomy: false,
        color: knowledgeAmbientEdgeStroke(false, false, libraryPalette), colorEnd: libraryPalette.core,
      })),
    ];
    for (const ref of librarySet) {
      const note = libraryNotes.find((node) => node.id === ref);
      const shelf = Object.values(shelfLabels).find((label) => ref === `@library/${label}`);
      titles.current.set(`agent:library/${ref}`, note?.title ?? (ref === libraryRoot ? "Library" : shelf ?? ref));
    }
    const librarySatellite = {
      agentId: "library",
      nodes: libraryRenderNodes,
      edges: libraryRenderEdges,
      tuning,
    };
    const satellites = [...agentSatellites, librarySatellite];
    return { nodes: renderNodes, edges: renderEdges, satellites };
  }, [graph, viewport, tuning]);

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
        tuning={tuning}
        satellites={model.satellites}
        onHover={setHoveredId}
        onNodeAction={(kind, id) => {
          const parsed = parseKnowledgeAgentNodeId(id);
          const ref = parsed.nodeId;
          if (kind === "click") openReader(ref);
        }}
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
