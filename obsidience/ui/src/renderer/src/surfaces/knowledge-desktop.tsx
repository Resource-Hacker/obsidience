import { useEffect, useState } from "react";
import { onOpenReader } from "@/lib/api";
import {
  onShellGraphDisplay,
  onShellKnowledgeVisibility,
  presentShellReader,
} from "@/lib/shell-client";
import { GraphBackdrop } from "@/panes/graph-backdrop";

const CENTERED_HUB = { x: 0.5, y: 0.5 } as const;

/** The exact Three.js knowledge desktop without the Electron application. */
export function KnowledgeDesktopSurface() {
  const query = new URLSearchParams(window.location.search);
  const lockMode = query.get("lock") === "1";
  const requestedSurfaceId = query.get("surface_id") ?? "samsung";
  const surfaceId = ["samsung", "usb-c", "dp-4"].includes(requestedSurfaceId)
    ? requestedSurfaceId
    : "samsung";
  const [visible, setVisible] = useState(true);
  const [selectedSurfaceId, setSelectedSurfaceId] = useState("samsung");

  useEffect(() => onOpenReader((ref, graphId) => {
    presentShellReader(ref, graphId);
  }), []);
  useEffect(() => onShellKnowledgeVisibility(surfaceId, setVisible), [surfaceId]);
  useEffect(() => onShellGraphDisplay(setSelectedSurfaceId), []);

  const showGraph = selectedSurfaceId === surfaceId && (lockMode || visible);

  return (
    <main
      aria-label="Obsidience knowledge desktop"
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
      {selectedSurfaceId === surfaceId ? (
        <GraphBackdrop visible={showGraph} lockMode={lockMode} hub={CENTERED_HUB} />
      ) : null}
    </main>
  );
}
