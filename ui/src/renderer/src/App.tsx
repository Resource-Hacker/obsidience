import { useCallback, useEffect, useMemo, useState } from "react";
import { PaneFrame } from "@/components/themes/jarvis/workspace/pane-frame";
import {
  OBSIDIENCE_PANES,
  clampPaneRect,
  loadWorkspace,
  paneDefinition,
  saveWorkspace,
  type JarvisPaneId,
  type PaneRect,
  type WorkspaceState,
} from "@/components/themes/jarvis/workspace/workspace-state";
import { GraphBackdrop } from "@/panes/graph-backdrop";
import { ChatPaneBody } from "@/panes/chat-pane";
import { JobsPaneBody } from "@/panes/jobs-pane";
import { ReviewsPaneBody } from "@/panes/reviews-pane";
import { ReaderPaneBody } from "@/panes/reader-pane";
import { StatusPaneBody } from "@/panes/status-pane";
import { TerminalPaneBody } from "@/panes/terminal-pane";
import { onOpenReader } from "@/lib/api";

function paneBody(id: JarvisPaneId) {
  switch (id) {
    case "chat": return <ChatPaneBody />;
    case "jobs": return <JobsPaneBody />;
    case "reviews": return <ReviewsPaneBody />;
    case "reader": return <ReaderPaneBody />;
    case "status": return <StatusPaneBody />;
    case "terminal": return <TerminalPaneBody />;
  }
}

export default function App() {
  const [workspace, setWorkspace] = useState<WorkspaceState>(loadWorkspace);
  const [viewport, setViewport] = useState({ width: window.innerWidth, height: window.innerHeight });

  useEffect(() => {
    const onResize = () => setViewport({ width: window.innerWidth, height: window.innerHeight });
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => saveWorkspace(workspace), [workspace]);

  // Any "open in reader" request opens the reader pane too.
  useEffect(() => onOpenReader(() => {
    setWorkspace((w) => ({ ...w, reader: { ...w.reader, open: true, z: topZ(w) + 1 } }));
  }), []);

  const topZ = (w: WorkspaceState) => Math.max(...Object.values(w).map((p) => p.z));

  const focusPane = useCallback((id: JarvisPaneId) => {
    setWorkspace((w) => ({ ...w, [id]: { ...w[id], z: topZ(w) + 1 } }));
  }, []);

  const togglePane = useCallback((id: JarvisPaneId) => {
    setWorkspace((w) => ({ ...w, [id]: { ...w[id], open: !w[id].open, z: topZ(w) + 1 } }));
  }, []);

  const commitRect = useCallback((id: JarvisPaneId, rect: PaneRect) => {
    setWorkspace((w) => ({ ...w, [id]: { ...w[id], rect } }));
  }, []);

  const openPanes = useMemo(
    () => OBSIDIENCE_PANES.filter((def) => workspace[def.id].open),
    [workspace],
  );

  return (
    <div data-dex-theme="jarvis" className="fixed inset-0 overflow-hidden bg-[#02060c] text-cyan-50">
      <GraphBackdrop />

      {/* top bar */}
      <header className="pointer-events-none absolute inset-x-0 top-0 z-40 flex items-center justify-between px-5 py-3">
        <h1 className="font-mono text-[13px] uppercase tracking-[0.4em] text-cyan-200/90 drop-shadow-[0_0_12px_rgba(34,211,238,0.45)]">
          Obsidience
        </h1>
        <nav className="pointer-events-auto flex items-center gap-1.5">
          {OBSIDIENCE_PANES.map((def) => (
            <button
              key={def.id}
              onClick={() => togglePane(def.id)}
              className={`rounded border px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.18em] transition-colors ${
                workspace[def.id].open
                  ? "border-cyan-300/50 bg-cyan-400/10 text-cyan-100"
                  : "border-cyan-300/15 text-cyan-300/50 hover:border-cyan-300/40 hover:text-cyan-100"
              }`}
            >
              {def.title}
            </button>
          ))}
        </nav>
      </header>

      {/* floating panes */}
      <div className="pointer-events-none absolute inset-0 z-30">
        {openPanes.map((def) => {
          const state = workspace[def.id];
          const rect = clampPaneRect(def.id, state.rect ?? def.defaultRect(viewport), viewport);
          return (
            <PaneFrame
              key={def.id}
              id={def.id}
              title={def.title}
              rect={rect}
              z={state.z}
              locked={false}
              resizable={def.resizable}
              minWidth={def.minWidth}
              minHeight={def.minHeight}
              viewport={viewport}
              onFocus={() => focusPane(def.id)}
              onClose={() => togglePane(def.id)}
              onRectCommit={(r) => commitRect(def.id, r)}
            >
              {paneBody(def.id)}
            </PaneFrame>
          );
        })}
      </div>
    </div>
  );
}
