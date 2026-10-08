import { useEffect, useState } from "react";
import { GraphViewer } from "./graph-viewer";
import { onOpenReader } from "@/lib/api";
import {
  onShellGraphDisplay,
  onShellKnowledgeVisibility,
  presentShellReader,
} from "@/lib/shell-client";
import { GraphBackdrop } from "@/panes/graph-backdrop";
import "./provider-graph.css";

const CENTERED_HUB = { x: 0.5, y: 0.5 } as const;

/** The Three.js knowledge desktop surface. */
export function KnowledgeDesktopSurface() {
  return new URLSearchParams(location.search).get("viewer") === "1" ? <GraphViewer view="knowledge"/> : <KnowledgeStage />;
}
function KnowledgeStage() {
  const query = new URLSearchParams(window.location.search);
  const lockMode = query.get("lock") === "1";
  const library = query.get("graph") === "library";
  const [consumers, setConsumers] = useState(0);
  const requestedSurfaceId = query.get("surface_id") ?? "samsung";
  const surfaceId = ["samsung", "usb-c", "dp-4"].includes(requestedSurfaceId)
    ? requestedSurfaceId
    : "samsung";
  const [visible, setVisible] = useState(true);
  const [stageVisible, setStageVisible] = useState(true);
  const [selectedSurfaceId, setSelectedSurfaceId] = useState("usb-c");

  useEffect(() => onOpenReader((ref, graphId) => {
    presentShellReader(ref, graphId);
  }), []);
  useEffect(() => library ? undefined : onShellKnowledgeVisibility(surfaceId, setVisible), [surfaceId, library]);
  useEffect(() => onShellGraphDisplay(setSelectedSurfaceId), []);
  useEffect(() => {
    let paneVisible = true;
    const visibility = () => setStageVisible(paneVisible && !document.hidden);
    const pane = (event: Event) => {
      paneVisible = (event as CustomEvent<boolean>).detail === true; visibility();
    };
    const changed = (event: MessageEvent) => {
      if (event.origin === location.origin && event.data?.type === "obsidience-stage-visibility") {
        paneVisible = event.data.visible === true; visibility();
      }
    };
    window.addEventListener("message", changed);
    window.addEventListener("obsidience-pane-visibility", pane);
    document.addEventListener("visibilitychange", visibility);
    visibility();
    return () => {
      window.removeEventListener("message", changed);
      window.removeEventListener("obsidience-pane-visibility", pane);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, []);

  const ownsStage = library || selectedSurfaceId === surfaceId;
  const showGraph = ownsStage && ((stageVisible && (library || lockMode || visible)) || consumers > 0);

  return (
    <main
      aria-label={library ? "Knowledge Library stage" : "Agent knowledge stage"}
      data-obsidience-theme="obsidience"
      data-obsidience-shell-surface="knowledge"
      className="fixed inset-0 overflow-hidden bg-[#02060c] text-cyan-50"
    >
      {showGraph && (surfaceId !== "samsung" || lockMode) ? (
        <span
          aria-label="Obsidience"
          className="pointer-events-none absolute left-5 top-3 z-10 font-mono text-[13px] uppercase"
          style={{
            color: "rgba(165, 243, 252, 0.9)",
            letterSpacing: "5.2px",
            textShadow: "0 0 12px rgba(34, 211, 238, 0.45)",
          }}
        >
          OBSIDIENCE
        </span>
      ) : null}
      {ownsStage ? (
        <GraphBackdrop visible={showGraph} lockMode={lockMode} hub={CENTERED_HUB}
          graphScope={library ? "library" : "main"} presentationSource={library ? "library" : "knowledge"}
          sharePresentation={!lockMode} onPresentationConsumers={setConsumers} />
      ) : null}
    </main>
  );
}
