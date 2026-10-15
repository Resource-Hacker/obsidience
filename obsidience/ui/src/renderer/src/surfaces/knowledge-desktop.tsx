import { useEffect, useState } from "react";
import {
  onShellGraphDisplay,
  onShellKnowledgeVisibility,
} from "@/lib/shell-client";
import { GraphBackdrop } from "@/panes/graph-backdrop";
import "./provider-graph.css";

const CENTERED_HUB = { x: 0.5, y: 0.5 } as const;

/** The Three.js knowledge desktop surface. */
export function KnowledgeDesktopSurface() {
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

  useEffect(() => library ? undefined : onShellKnowledgeVisibility(surfaceId, setVisible), [surfaceId, library]);
  useEffect(() => onShellGraphDisplay(setSelectedSurfaceId), []);
  useEffect(() => {
    let paneVisible = true;
    const visibility = () => setStageVisible(paneVisible && !document.hidden);
    const changed = (event: MessageEvent) => {
      if (event.origin === location.origin && event.data?.type === "obsidience-stage-visibility") {
        paneVisible = event.data.visible === true; visibility();
      }
    };
    window.addEventListener("message", changed);
    document.addEventListener("visibilitychange", visibility);
    visibility();
    return () => {
      window.removeEventListener("message", changed);
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
      className="fixed inset-0 overflow-hidden bg-[#030304] text-cyan-50"
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
