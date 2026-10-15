/** The Executive and Library Knowledge stage: the Obsidience 3D engine fed by
 *  the live vault (knowledge-model.ts) with the owner's tuning, the thinking
 *  route of live activity (thinking-state.ts), Reader selection, link Review
 *  previews and the pane publisher. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { GraphPublisher } from "@/graph/stream";
import { Knowledge3dScene } from "@/graph/knowledge/knowledge-3d-scene";
import {
  knowledgeAgentNodeId,
  parseKnowledgeAgentNodeId,
  type Knowledge3dTuning,
} from "@/graph/knowledge/knowledge-3d";
import {
  DEFAULT_KNOWLEDGE_HUB_ANCHOR,
  type KnowledgeLayoutAnchor,
} from "@/graph/knowledge/knowledge-geometry";
import { KNOWLEDGE_LINK_APPROVAL_DURATION_MS } from "@/graph/knowledge/knowledge-3d-cloud";
import { api, type GraphLinkProposals, type ProviderNode } from "@/lib/api";
import { claimShellKnowledgePresenter, onShellReaderSelection, presentShellReader, type GraphSource } from "@/lib/shell-client";
import {
  MAIN_GRAPH_ID,
  loadGraphTuning,
  onGraphThinkingTest,
  onGraphTuning,
  selectGraph,
} from "@/graph/tuning";
import { ActionTracePopup } from "@/graph/trace/action-trace-popup";
import { articleDisplayAliases, projectedArticleLinks, visibleArticleLinks } from "./graph-links";
import { operationAccent, operationStatus, type GraphActivityAccent } from "./graph-activity";
import { previewLinkReviewCloud, projectLinkReviewEffects, recordLinkApproval, type LinkApproval } from "./graph-link-review";
import { buildThinkingRoute, type GraphCloud, type ThinkingRoute } from "./thinking-route";
import { ROOT_ID, buildKnowledgeModel, graphSnapshotFingerprint, type VaultGraphSnapshot } from "./knowledge-model";
import { useThinkingActivity } from "./thinking-state";
import { NodeActionMenu, type NodeMenuState } from "./node-menu";

const READABLE_SWEEP_SECONDS = 1.6; // Initial branch travel; relationship tails keep this pace.

interface SatelliteThinkingTest {
  agentId: string;
  route: ThinkingRoute;
  key: number;
}

export function GraphBackdrop({
  visible = true,
  lockMode = false,
  sharePresentation = false,
  graphScope = MAIN_GRAPH_ID,
  presentationSource = "knowledge",
  onPresentationConsumers,
  hub = DEFAULT_KNOWLEDGE_HUB_ANCHOR,
}: {
  visible?: boolean;
  lockMode?: boolean;
  sharePresentation?: boolean;
  graphScope?: string;
  presentationSource?: GraphSource;
  onPresentationConsumers?: (count: number) => void;
  hub?: KnowledgeLayoutAnchor;
} = {}) {
  const [graph, setGraph] = useState<VaultGraphSnapshot>({
    nodes: [], links: [], auto_curated: [], auto_curate_resolved: false,
    navigation: { groups: [] },
  });
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const [publisher, setPublisher] = useState<GraphPublisher | null>(null);
  useEffect(() => lockMode ? undefined : claimShellKnowledgePresenter(presentationSource === "library" ? "library" : "knowledge"), [lockMode, presentationSource]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [readerSelection, setReaderSelection] = useState<{ ref: string; graphId: string } | null>(null);
  const [nodeMenu, setNodeMenu] = useState<NodeMenuState | null>(null);
  useEffect(() => {
    setHoveredId(null); setSelectedId(null); setReaderSelection(null); setNodeMenu(null);
  }, [graphScope]);
  const [traceInspectionSince, setTraceInspectionSince] = useState<number | null>(null);
  const [traceDismissedSince, setTraceDismissedSince] = useState<number | null>(null);
  const [sceneKey, setSceneKey] = useState(0);
  const [viewport, setViewport] = useState({ width: window.innerWidth, height: window.innerHeight });
  const graphFingerprint = useRef<string | null>(null);
  const testTimers = useRef<number[]>([]);
  const satelliteTestTimer = useRef<number | null>(null);
  const [satelliteTest, setSatelliteTest] = useState<SatelliteThinkingTest | null>(null);
  const [tuning, setTuning] = useState<Knowledge3dTuning>(() => loadGraphTuning(MAIN_GRAPH_ID));
  const [satelliteTunings, setSatelliteTunings] = useState<Record<string, Knowledge3dTuning>>({});
  const [linkProposals, setLinkProposals] = useState<GraphLinkProposals>({ entries: [], truncated: false });
  const [linkApprovals, setLinkApprovals] = useState<LinkApproval[]>([]);
  const proposalStarts = useRef(new Map<string, number>());
  const { activity, setActivity, operations, clearedRuns, finishedRuns, playback, speechEnvelope, activityKey } = useThinkingActivity({
    onReview: (review) => {
      const wallNow = Date.now();
      const frameNow = performance.now();
      setLinkApprovals((current) => recordLinkApproval(current, review, wallNow, frameNow));
      // Approval retains its preview spring until the fresh accepted snapshot
      // replaces it. Removing it here would briefly tear out and re-add the link.
      if (review.state === "rejected") {
        setLinkProposals((current) => ({ ...current,
          entries: current.entries.filter((link) => link.proposal_id !== review.proposal_id),
        }));
      }
    },
    onGraphChanged: () => window.dispatchEvent(new Event("obsidience:graph-refresh")),
    acceptGraph: (graphId) => graphScope === "library" ? graphId === "library"
      : graphId === MAIN_GRAPH_ID || graph.navigation.groups.some((group) => group.scene === "executive"
        && (graphId === group.id || graphId === group.root_ref.split("/")[1])),
  });

  function selectReader(ref: string, graphId: string): void {
    setReaderSelection((previous) =>
      previous?.ref === ref && previous.graphId === (graphId || MAIN_GRAPH_ID) ? previous
        : ref ? { ref, graphId: graphId || MAIN_GRAPH_ID } : null);
  }
  useEffect(() => onShellReaderSelection(selectReader), []);

  // One expiry deadline for finite approval paint; the scene owns every frame.
  useEffect(() => {
    if (!linkApprovals.length) return;
    const deadline = Math.min(...linkApprovals.map((item) => item.startedAt + KNOWLEDGE_LINK_APPROVAL_DURATION_MS));
    const timer = window.setTimeout(() => setLinkApprovals((current) => current.filter(
      (item) => performance.now() - item.startedAt < KNOWLEDGE_LINK_APPROVAL_DURATION_MS,
    )), Math.max(1, deadline - performance.now()));
    return () => window.clearTimeout(timer);
  }, [linkApprovals]);

  // Reading the trace can outlive the graph's activity linger. This retains only
  // the popup's bounded presentation, never the animation or Task execution.
  useEffect(() => {
    if (visible && !lockMode) return;
    setTraceInspectionSince(null);
    setTraceDismissedSince(null);
  }, [visible, lockMode]);

  useEffect(() => {
    if (!lockMode) return;
    setHoveredId(null);
    setSelectedId(null);
    setReaderSelection(null);
    setNodeMenu(null);
  }, [lockMode]);

  useEffect(() => {
    const onResize = () => setViewport({ width: window.innerWidth, height: window.innerHeight });
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => onGraphTuning(({ graphId, tuning: next }) => {
    if (graphId === MAIN_GRAPH_ID) setTuning(next);
    else setSatelliteTunings((current) => ({ ...current, [graphId]: next }));
  }), []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setSelectedId(null);
      setReaderSelection(null);
      setNodeMenu(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => () => {
    testTimers.current.forEach((timer) => window.clearTimeout(timer));
    if (satelliteTestTimer.current !== null) window.clearTimeout(satelliteTestTimer.current);
  }, []);

  useEffect(() => {
    let live = true;
    let requested = 0;
    let pulling = false;
    const pull = async () => {
      requested += 1;
      if (pulling) return;
      pulling = true;
      let request: number;
      do {
        request = requested;
        try {
          const next = await api.graph();
          // A review event invalidates any response started before that event.
          if (!live || request !== requested) continue;
          const proposals = next.link_proposals ?? { entries: [], truncated: false };
          const now = performance.now();
          proposalStarts.current = new Map(proposals.entries.map((link) => [
            link.proposal_id, proposalStarts.current.get(link.proposal_id) ?? now,
          ]));
          setLinkProposals((current) => JSON.stringify(current) === JSON.stringify(proposals) ? current : proposals);
          const snapshot: VaultGraphSnapshot = {
            nodes: next.nodes,
            links: next.links,
            auto_curated: next.auto_curated ?? [],
            auto_curate_resolved: next.auto_curate_resolved === true,
            navigation: next.navigation,
          };
          const fingerprint = graphSnapshotFingerprint(snapshot);
          // Accepted knowledge stays separate from the Scene-only spring preview.
          if (fingerprint === graphFingerprint.current) continue;
          graphFingerprint.current = fingerprint;
          setGraph(snapshot);
        } catch { /* retain the last accepted graph until a successful refresh */ }
      } while (live && request !== requested);
      pulling = false;
    };
    pull();
    const t = setInterval(pull, 15_000);
    window.addEventListener("obsidience:graph-refresh", pull);
    return () => {
      live = false;
      clearInterval(t);
      window.removeEventListener("obsidience:graph-refresh", pull);
    };
  }, []);

  const displayAliases = useMemo(() => articleDisplayAliases([
    ...graph.nodes,
    ...graph.navigation.groups.flatMap((group) => group.subjects),
  ]), [graph.nodes, graph.navigation]);
  // Tuning stays out of this model except for the three layout scales: a
  // slider step must not replace the node arrays every cloud is built from.
  const model = useMemo(() => buildKnowledgeModel(graph, displayAliases, hub, viewport,
    { peers: tuning.ring2dPeers, branches: tuning.ring2dBranches, articles: tuning.ring2dArticles }),
  [graph, displayAliases, hub, viewport, tuning.ring2dPeers, tuning.ring2dBranches, tuning.ring2dArticles]);
  const satelliteTuning = useCallback((agentId: string) =>
    satelliteTunings[agentId] ?? loadGraphTuning(agentId), [satelliteTunings]);

  // Only the Scene receives the visual spring preview. Thinking paths, Reader
  // selection and accepted graph state continue to use the accepted model.
  const presentation = useMemo(() => {
    const links = [...model.articleLinks, ...projectedArticleLinks(linkProposals.entries, displayAliases)];
    const project = <T extends GraphCloud>(cloud: T, graphId: string): T => {
      const scope = model.reviewScopes.get(graphId);
      if (!scope) return cloud;
      const union = visibleArticleLinks(links, scope.articleIds, scope.agentRef, scope.scopeRefs);
      return previewLinkReviewCloud(cloud, scope.links, union, graphId === MAIN_GRAPH_ID, scope.edgeColorEnd);
    };
    const main = project(model, MAIN_GRAPH_ID);
    const satellites = model.satellites.map((cloud) => project(cloud, cloud.agentId));
    const labelMetadata = new Map(model.labelMetadata);
    for (const node of main.nodes) {
      const label = labelMetadata.get(node.id);
      if (label) labelMetadata.set(node.id, { ...label, radius: node.radius });
    }
    return { nodes: main.nodes, edges: main.edges, satellites, labelMetadata };
  }, [model, linkProposals, displayAliases]);

  useEffect(() => onGraphThinkingTest((graphId) => {
    testTimers.current.forEach((timer) => window.clearTimeout(timer));
    testTimers.current = [];
    if (satelliteTestTimer.current !== null) {
      window.clearTimeout(satelliteTestTimer.current);
      satelliteTestTimer.current = null;
    }
    setActivity(null);
    setSatelliteTest(null);
    const cloud = graphId === MAIN_GRAPH_ID
      ? model
      : model.satellites.find((satellite) => satellite.agentId === graphId);
    if (!cloud) return;
    const leaves = cloud.nodes.filter((node) => node.role === "claim");
    const pool = leaves.length > 0 ? leaves : cloud.nodes.filter((node) => node.role !== "root");
    if (pool.length === 0) return;
    const target = pool[Math.floor(Math.random() * pool.length)];
    const route = buildThinkingRoute(cloud, [target.id], [[target.id]]);
    if (!route) return;
    activityKey.current += 1;
    const key = activityKey.current;
    if (graphId !== MAIN_GRAPH_ID) {
      // Satellite tests use the cloud's own non-held sweep timeline and do not
      // wake the Executive retrieval path.
      setSatelliteTest({ agentId: graphId, route, key });
      satelliteTestTimer.current = window.setTimeout(() => {
        setSatelliteTest((current) => current?.key === key ? null : current);
        satelliteTestTimer.current = null;
      }, 14_000);
      return;
    }
    // Obsidience starts the thinking state immediately, admits the real path at
    // 750 ms, flips to speaking at 3.2 s, and ends the synthetic turn at 5.8 s.
    setActivity({ refs: [], phase: "thinking", key, graphId, query: "Thinking test", startedAt: Date.now() });
    testTimers.current.push(window.setTimeout(() => {
      setActivity((current) => current?.key === key
        ? { ...current, refs: [target.id], phase: "thinking" }
        : current);
    }, 750));
    testTimers.current.push(window.setTimeout(() => {
      setActivity((current) => current?.key === key ? { ...current, phase: "speaking" } : current);
    }, 3_200));
    testTimers.current.push(window.setTimeout(() => {
      setActivity((current) => current?.key === key ? null : current);
      testTimers.current = [];
    }, 5_800));
  }), [model]);

  const renderedActivityRefs = useMemo(() => {
    const executiveRef = graph.navigation.groups.find((group) => group.id === "executive")?.root_ref;
    return (activity?.refs ?? []).map((ref) =>
      ref === executiveRef && (!activity?.graphId || activity.graphId === MAIN_GRAPH_ID)
        ? ROOT_ID : displayAliases.get(ref) ?? ref);
  }, [activity?.refs, activity?.graphId, displayAliases, graph.navigation]);
  const operationClouds = useMemo(() => {
    const executiveRef = graph.navigation.groups.find((group) => group.id === "executive")?.root_ref;
    const graphIds = new Map(graph.navigation.groups.flatMap((group) => {
      const id = group.id === "executive" ? MAIN_GRAPH_ID
        : group.id === "library" ? "library" : group.root_ref.split("/")[1];
      return [[group.id, id], [group.root_ref, id]] as [string, string][];
    }));
    const clouds = [{ agentId: MAIN_GRAPH_ID, ...model }, ...model.satellites];
    return clouds.map((cloud) => {
      const refsByRun = new Map<string, Set<string>>();
      const addRefs = (identity: string, refs: string[]) => {
        const group = refsByRun.get(identity) ?? new Set<string>();
        for (const ref of refs) group.add(ref);
        refsByRun.set(identity, group);
      };
      const accents = new Map<string, GraphActivityAccent>();
      let key: string | number = "";
      const hasPacket = activity && (activity.graphId ?? MAIN_GRAPH_ID) === cloud.agentId;
      if (hasPacket) {
        key = activity.runId ? `run:${activity.runId}` : `packet:${activity.startedAt}`;
        addRefs(String(key), renderedActivityRefs);
      }
      for (const entry of operations) {
        // Owner browsing follows the current selection immediately. A later
        // Reader response is evidence for its legend, not another path replay.
        if (entry.kind === "read" && !entry.run_id) continue;
        if (entry.graph_id !== "*" && (graphIds.get(entry.graph_id) ?? entry.graph_id) !== cloud.agentId) continue;
        if (entry.kind === "context" && hasPacket && entry.run_id === activity.runId) continue;
        const refs = entry.refs.map((ref) => ref === executiveRef && cloud.agentId === MAIN_GRAPH_ID
          ? ROOT_ID : displayAliases.get(ref) ?? ref);
        const identity = entry.run_id ? `run:${entry.run_id}` : `operation:${entry.id}`;
        addRefs(identity, refs);
        // A new Tool extends the running sweep instead of restarting all of
        // that agent's already illuminated Tools from the Brain.
        if (!key) key = identity;
        const accent = operationAccent(entry);
        if (accent) for (const ref of refs) accents.set(ref, accent);
      }
      const refGroups = [...refsByRun.values()].map(group => [...group]);
      const runIds = [...refsByRun.keys()].filter(identity => identity.startsWith("run:"));
      const phase = runIds.length
        ? (runIds.every(identity => finishedRuns.current.has(identity.slice(4))
          || (playback.current.status === "speaking" && playback.current.run_id === identity.slice(4))) ? "speaking" as const : "thinking" as const)
        : hasPacket ? activity.phase : "thinking" as const;
      return { agentId: cloud.agentId, key: `${cloud.agentId}:${key}`, phase, accents,
        route: buildThinkingRoute(cloud, refGroups.flat(), refGroups) };
    });
  }, [activity, operations, model, renderedActivityRefs, displayAliases, graph.navigation]);
  const scopedCloud = graphScope === MAIN_GRAPH_ID ? presentation
    : presentation.satellites.find(cloud => cloud.agentId === graphScope);
  // Each satellite's tuning joins its cloud here, at the Scene boundary.
  const agentSatellites = useMemo(() => graphScope === MAIN_GRAPH_ID
    ? presentation.satellites.filter(cloud => cloud.agentId !== "library")
      .map(cloud => ({ ...cloud, tuning: satelliteTuning(cloud.agentId) }))
    : [], [presentation.satellites, graphScope, satelliteTuning]);
  const scopedTuning = graphScope !== MAIN_GRAPH_ID && model.satellites.some(cloud => cloud.agentId === graphScope)
    ? satelliteTuning(graphScope) : tuning;
  const scopedId = (id: string) => graphScope === MAIN_GRAPH_ID ? id : knowledgeAgentNodeId(graphScope, id);
  const localId = (id: string | null) => {
    if (!id) return null;
    const parsed = parseKnowledgeAgentNodeId(id);
    return graphScope === MAIN_GRAPH_ID ? (parsed.agentId === "library" ? null : id)
      : parsed.agentId === graphScope ? parsed.nodeId : null;
  };
  const mainActivity = operationClouds.find(cloud => cloud.agentId === graphScope) ?? operationClouds[0];
  const mainRoute = mainActivity.route;
  const mainPhase = mainRoute ? mainActivity.phase : null;
  const effectiveSweepSpeed = useMemo(() => scopedTuning.automaticSweepSpeed >= 0.5 && mainRoute
    ? 1 / READABLE_SWEEP_SECONDS
    : scopedTuning.sweepSpeed,
  [mainRoute, scopedTuning.automaticSweepSpeed, scopedTuning.sweepSpeed]);
  const effectiveTuning = useMemo(
    () => effectiveSweepSpeed === scopedTuning.sweepSpeed
      ? scopedTuning
      : { ...scopedTuning, sweepSpeed: effectiveSweepSpeed },
    [effectiveSweepSpeed, scopedTuning],
  );
  const satelliteRoutes = useMemo(() => {
    if (satelliteTest) return [{
      agentId: satelliteTest.agentId,
      spec: satelliteTest.route.pathSpec,
      nodeIds: satelliteTest.route.nodeIds,
      passedIds: satelliteTest.route.passedIds,
      key: satelliteTest.key,
      hold: false,
    }];
    return operationClouds.slice(1).flatMap(({ agentId, route, key, phase, accents }) => {
      if (!route) return [];
      const speed = satelliteTuning(agentId).automaticSweepSpeed >= 0.5
        ? 1 / READABLE_SWEEP_SECONDS : undefined;
      return [{ agentId, spec: route.pathSpec, nodeIds: route.nodeIds, passedIds: route.passedIds,
        accents, key, phase, hold: true, speed }];
    });
  }, [activity, satelliteTuning, satelliteTest, operationClouds]);

  const selected = selectedId ? parseKnowledgeAgentNodeId(selectedId) : null;
  const selectionPath = useMemo(() => {
    if (!readerSelection || lockMode) return null;
    const group = graph.navigation.groups.find((entry) => entry.id === readerSelection.graphId
      || entry.root_ref === readerSelection.graphId);
    const agentId = group ? group.id === "executive" ? MAIN_GRAPH_ID
      : group.id === "library" ? "library" : group.root_ref.split("/")[1] : readerSelection.graphId;
    const cloud = agentId === MAIN_GRAPH_ID ? model : model.satellites.find((entry) => entry.agentId === agentId);
    const ref = agentId === MAIN_GRAPH_ID && readerSelection.ref === graph.navigation.groups.find((g) => g.id === "executive")?.root_ref
      ? ROOT_ID : displayAliases.get(readerSelection.ref) ?? readerSelection.ref;
    const route = cloud ? buildThinkingRoute(cloud, [ref]) : null;
    return route ? { agentId, id: ref, spec: route.pathSpec } : null;
  }, [readerSelection, lockMode, model, graph.navigation, displayAliases]);
  const cameraFocus = selected ? {
    agentId: selected.agentId,
    nodeId: selected.nodeId,
  } : null;
  const selectNode = (id: string, read: boolean) => {
    const parsed = parseKnowledgeAgentNodeId(id);
    setSelectedId(id);
    setNodeMenu(null);
    selectGraph(parsed.agentId ?? MAIN_GRAPH_ID);
    setReaderSelection({ ref: parsed.nodeId, graphId: parsed.agentId ?? MAIN_GRAPH_ID });
    if (read) {
      const ref = graph.nodes.find((node) => node.id === parsed.nodeId)?.article_ref ?? parsed.nodeId;
      selectReader(ref, parsed.agentId ?? MAIN_GRAPH_ID);
      presentShellReader(ref, parsed.agentId ?? MAIN_GRAPH_ID);
    }
  };
  const clearSelection = () => {
    setSelectedId(null);
    setReaderSelection(null);
    setNodeMenu(null);
    selectGraph(graphScope);
  };
  const highlightedId = lockMode ? null : hoveredId;
  const menuParsed = nodeMenu ? parseKnowledgeAgentNodeId(nodeMenu.id) : null;
  const menuNode = menuParsed
    ? graph.nodes.find((node) => node.id === menuParsed.nodeId) ?? null
    : null;
  const labelIds = useMemo(() => {
    const ordered: string[] = [];
    const add = (id: string | null | undefined) => {
      if (id && !ordered.includes(id)) ordered.push(id);
    };
    add(hoveredId);
    add(selectionPath ? selectionPath.agentId === MAIN_GRAPH_ID ? selectionPath.id
      : knowledgeAgentNodeId(selectionPath.agentId, selectionPath.id) : selectedId);
    return lockMode ? [] : ordered;
  }, [hoveredId, lockMode, selectedId, selectionPath]);

  const relationEffects = useMemo(() => projectLinkReviewEffects(
    linkProposals.entries, linkApprovals, graph.links, displayAliases,
    [{ agentId: "main", nodes: presentation.nodes, edges: presentation.edges }, ...presentation.satellites], performance.now(),
    proposalStarts.current,
  ), [linkProposals, linkApprovals, graph.links, displayAliases, presentation]);
  const scopedEffects = useMemo(() => graphScope === MAIN_GRAPH_ID
    ? relationEffects.filter(effect => effect.graphId !== "library")
    : relationEffects.filter(effect => effect.graphId === graphScope)
      .map(effect => ({ ...effect, graphId: MAIN_GRAPH_ID })), [relationEffects, graphScope]);
  const scopedLabels = useMemo(() => new Map([...presentation.labelMetadata].flatMap(([id, meta]) => {
    const parsed = parseKnowledgeAgentNodeId(id);
    return graphScope === MAIN_GRAPH_ID ? (parsed.agentId === "library" ? [] : [[id, meta] as const])
      : parsed.agentId === graphScope ? [[parsed.nodeId, meta] as const] : [];
  })), [presentation.labelMetadata, graphScope]);
  const pendingLinkCount = new Set(scopedEffects.filter((effect) => effect.phase === "pending").map((effect) => effect.id)).size;
  const approvedLinkCount = new Set(scopedEffects.filter((effect) => effect.phase === "approved").map((effect) => effect.id)).size;

  const viewCatalog = useMemo(() => {
    const nodes: ProviderNode[] = [];
    const clouds = scopedCloud ? [{ agentId: graphScope, nodes: scopedCloud.nodes, edges: scopedCloud.edges }, ...agentSatellites] : [];
    for (const cloud of clouds) for (const node of cloud.nodes) {
      const id = cloud.agentId === MAIN_GRAPH_ID ? node.id : knowledgeAgentNodeId(cloud.agentId, node.id);
      const article = graph.nodes.find(article => article.id === node.id);
      const meta = presentation.labelMetadata.get(id);
      nodes.push({id, name: meta?.label || model.titles.get(id) || node.id,
        kind: article?.kind || node.role, color: meta?.accent || "#67e8f9",
        ref: article?.article_ref || node.id, graph_id: cloud.agentId});
    }
    return {nodes, count: nodes.length, links: clouds.reduce((count, cloud) => count + cloud.edges.length, 0),
      graphs: clouds.map(cloud => ({id: cloud.agentId, name: cloud.agentId === MAIN_GRAPH_ID ? "Executive"
        : cloud.agentId === "library" ? "Library" : cloud.agentId, count: cloud.nodes.length, links: cloud.edges.length}))};
  }, [graph.nodes, presentation, scopedCloud, graphScope, model.satellites, model.titles, agentSatellites]);
  useEffect(() => publisher?.publishCatalog(viewCatalog), [publisher, viewCatalog]);
  useEffect(() => publisher?.publishState({connected: true, graphId: graphScope,
    selected: viewCatalog.nodes.find(node => node.id === selectedId) || null,
    hover: viewCatalog.nodes.find(node => node.id === hoveredId) || null,
    latest: operations.length ? {label: operations.at(-1)!.label, status: operations.at(-1)!.status} : undefined,
  }), [publisher, viewCatalog, selectedId, hoveredId, operations, graphScope]);

  return (
    <div className="absolute inset-0">
      <Knowledge3dScene
          sharePresentation={sharePresentation && !lockMode}
          presentationSource={presentationSource}
          primaryGraphId={graphScope}
          onPresentationReady={setPublisher}
          onPresentationConsumers={onPresentationConsumers}
          onPresentationCommand={command => {
            if (command.action === "select" && command.id) {
              const id = viewCatalog.nodes.some(node => node.id === command.id) ? command.id : scopedId(command.id);
              if (viewCatalog.nodes.some(node => node.id === id)) selectNode(id, false);
            }
            else if (command.action === "clear" || command.action === "fit") clearSelection();
            else if (command.action === "refresh") window.dispatchEvent(new Event("obsidience:graph-refresh"));
          }}
          key={`${sceneKey}:${graphScope}`}
          nodes={scopedCloud?.nodes ?? []}
          edges={scopedCloud?.edges ?? []}
          hub={hub}
          focusNodeIds={mainRoute?.nodeIds ?? new Set<string>()}
          passedNodeIds={mainRoute?.passedIds}
          pathSpec={mainRoute?.pathSpec ?? null}
          focusActive={Boolean(mainPhase)}
          focusKey={mainActivity.key}
          clearedActivityKeys={new Set([...clearedRuns].flatMap(runId => operationClouds.map(cloud => `${cloud.agentId}:run:${runId}`)))}
          focusPhase={mainPhase}
          activityAccents={mainActivity.accents}
          selectionPath={graphScope === MAIN_GRAPH_ID ? (selectionPath?.agentId === "library" ? null : selectionPath)
            : selectionPath?.agentId === graphScope ? {...selectionPath, agentId: MAIN_GRAPH_ID} : null}
          speechEnvelope={visible && !lockMode && graphScope === MAIN_GRAPH_ID ? speechEnvelope : undefined}
          visible={visible}
          reducedMotion={false}
          adapterPreference="system"
          animationProfile="maximum"
          hoveredNodeId={localId(highlightedId)}
          labelIds={labelIds.flatMap(id => { const local = localId(id); return local ? [local] : []; })}
          showActivityLabels={!lockMode}
          labelMetadata={scopedLabels}
          tuning={effectiveTuning}
          satellites={agentSatellites}
          satelliteSweeps={graphScope === MAIN_GRAPH_ID ? satelliteRoutes.filter(route => route.agentId !== "library") : []}
          relationEffects={scopedEffects}
          cameraFocus={lockMode ? null : graphScope === MAIN_GRAPH_ID ? (cameraFocus?.agentId === "library" ? null : cameraFocus)
            : cameraFocus?.agentId === graphScope ? {...cameraFocus, agentId: MAIN_GRAPH_ID} : null}
          onBackgroundClick={lockMode ? undefined : clearSelection}
          onHover={lockMode ? undefined : id => setHoveredId(id ? scopedId(id) : null)}
          onNodeAction={(kind, id, at) => {
            if (lockMode) return;
            if (kind === "click") selectNode(scopedId(id), true);
            else setNodeMenu({ id: scopedId(id), x: at.x, y: at.y });
          }}
          onContextLost={() => setSceneKey((k) => k + 1)}
      />
      {!lockMode && visible && operations.some((entry) => entry.kind !== "context") ? (
        <div role="status" aria-live="polite" aria-label="Knowledge activity"
          className="pointer-events-none absolute right-5 top-5 z-20 max-w-[24rem] rounded-md border border-cyan-300/15 bg-[#030a10]/85 px-3 py-2 font-mono text-[11px] shadow-lg">
          {operations.filter((entry) => entry.kind !== "context").slice(-4).reverse().map((entry) => (
            <div key={entry.id} className="flex items-baseline gap-2 py-0.5" style={{ color: operationAccent(entry)?.color }}>
              <span aria-hidden="true">{entry.status === "running" ? "◉" : "◇"}</span>
              <span className="truncate">{entry.label}</span>
              <span className="ml-auto shrink-0 opacity-70">{operationStatus(entry)}</span>
              {entry.omitted_refs > 0 ? <span className="shrink-0">+{entry.omitted_refs} omitted</span> : null}
            </div>
          ))}
        </div>
      ) : null}
      {!lockMode && visible && (pendingLinkCount > 0 || approvedLinkCount > 0 || linkProposals.truncated) ? (
        <div role="status" aria-live="polite" data-testid="link-review-status"
          className="pointer-events-none absolute bottom-5 left-5 z-20 rounded-md border border-slate-500/25 bg-[#030a10]/85 px-3 py-2 font-mono text-[11px] shadow-lg">
          {pendingLinkCount > 0 ? <p className="text-amber-300"><span aria-hidden="true">┄ </span>{pendingLinkCount} {pendingLinkCount === 1 ? "link" : "links"} awaiting review · glowing preview</p> : null}
          {approvedLinkCount > 0 ? <p className="text-cyan-200"><span aria-hidden="true">✦ </span>{approvedLinkCount} {approvedLinkCount === 1 ? "link approved" : "links approved"}</p> : null}
          {linkProposals.truncated ? <p className="mt-1 text-slate-400">Review links incomplete · see Reviews</p> : null}
        </div>
      ) : null}
      {!lockMode && visible && (traceInspectionSince !== null || (activity && activity.startedAt !== traceDismissedSince)) ? (
        <ActionTracePopup since={traceInspectionSince ?? activity!.startedAt}
          keptOpen={traceInspectionSince !== null}
          onKeepOpen={(keep) => setTraceInspectionSince(keep ? (traceInspectionSince ?? activity?.startedAt ?? null) : null)}
          onClose={() => {
            setTraceInspectionSince(null);
            setTraceDismissedSince(activity?.startedAt ?? null);
          }} />
      ) : null}
      {!lockMode && nodeMenu ? (
        <NodeActionMenu
          menu={nodeMenu}
          title={model.titles.get(nodeMenu.id) ?? menuParsed?.nodeId ?? nodeMenu.id}
          canEdit={menuNode?.kind === "task" && !menuNode.synthetic}
          onSelect={() => selectNode(nodeMenu.id, false)}
          onRead={() => selectNode(nodeMenu.id, true)}
          onClose={() => setNodeMenu(null)}
          onClear={clearSelection}
        />
      ) : null}
    </div>
  );
}
