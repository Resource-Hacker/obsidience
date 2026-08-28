import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Eye, EyeOff, LoaderCircle, Mic, MicOff, Pause, Play } from "lucide-react";
import { PaneFrame } from "@/components/themes/obsidience/workspace/pane-frame";
import {
  DEFAULT_SURFACE_ID,
  OBSIDIENCE_PANES,
  clampPaneRect,
  loadWorkspace,
  paneDefinition,
  saveWorkspace,
  type PaneId,
  type PaneRect,
  type WorkspaceState,
} from "@/components/themes/obsidience/workspace/workspace-state";
import { GraphBackdrop } from "@/panes/graph-backdrop";
import { CameraPaneBody } from "@/panes/camera-pane";
import { HardwarePaneBody } from "@/panes/hardware-pane";
import { ChatPaneBody } from "@/panes/chat-pane";
import { TasksPaneBody } from "@/panes/tasks-pane";
import { LibraryPaneBody } from "@/panes/library-pane";
import { ReviewsPaneBody } from "@/panes/reviews-pane";
import {
  ReaderKnowledgePaneBody,
  ReaderPaneBody,
  ReaderSourcePaneBody,
  type ReaderDockingProps,
} from "@/panes/reader-pane";
import { StatusPaneBody } from "@/panes/status-pane";
import { TerminalPaneBody } from "@/panes/terminal-pane";
import { TuningPaneBody } from "@/panes/tuning-pane";
import {
  WS_BASE,
  api,
  onOpenReader,
  onOpenSourceFile,
  onOpenTasks,
  type HardwareCameraState,
  type RealtimeState,
} from "@/lib/api";
import {
  loadReaderDockLayout,
  saveReaderDockLayout,
  type ReaderDockPosition,
  type ReaderModuleId,
} from "@/lib/reader-docking";

function staticPaneBody(id: PaneId) {
  switch (id) {
    case "chat": return <ChatPaneBody />;
    case "tasks": return <TasksPaneBody />;
    case "library": return <LibraryPaneBody />;
    case "reviews": return <ReviewsPaneBody />;
    case "status": return <StatusPaneBody />;
    case "hardware": return <HardwarePaneBody />;
    case "terminal": return <TerminalPaneBody />;
    case "tuning": return <TuningPaneBody />;
    case "reader": case "knowledge": case "source": case "camera": return null;
  }
}

const topZ = (workspace: WorkspaceState) => Math.max(...Object.values(workspace).map((pane) => pane.z));
const isReaderModule = (id: PaneId): id is ReaderModuleId => id === "knowledge" || id === "source";
const OFF_REALTIME: RealtimeState = {
  schema_version: 1,
  phase: "off",
  enabled: false,
  ready: false,
  transport_ready: false,
  proactive: false,
  requested_proactive: false,
  pid: null,
  started_monotonic_ns: null,
  last_error: null,
  vision_source: null,
  audio_source: "",
  audio_sink: "",
  input_level: 0,
  user_speaking: false,
  live_transcript: null,
  acoustic_echo_cancellation: false,
  speech: {
    transport: "Pipecat LocalAudioTransport 0.0.98",
    turn_taking: "NVIDIA NeMo Voice Agent",
    asr: "Nemotron Speech Streaming EN 0.6B",
    asr_device: "RTX 4080 SUPER",
    asr_chunk_ms: 160,
    tts: "Pocket TTS 3.0.2",
    tts_device: "CPU",
    voice: "starfleet",
  },
  model: null,
  task_ref: "Tasks/executive/realtime",
  task_run_id: null,
  task_status: "draft",
  scheduler_paused: false,
  recent_log: [],
};

export default function App() {
  const surfaceId = window.obsidience?.surfaceId ?? DEFAULT_SURFACE_ID;
  const [workspace, setWorkspace] = useState<WorkspaceState>(loadWorkspace);
  const [readerDock, setReaderDock] = useState(loadReaderDockLayout);
  const [draggingReaderModule, setDraggingReaderModule] = useState<ReaderModuleId | null>(null);
  const [viewport, setViewport] = useState({ width: window.innerWidth, height: window.innerHeight });
  const [realtime, setRealtime] = useState<RealtimeState>(OFF_REALTIME);
  const [realtimeAction, setRealtimeAction] = useState<"power" | "mode" | null>(null);
  const [realtimeError, setRealtimeError] = useState<string | null>(null);
  const [camera, setCamera] = useState<HardwareCameraState | null>(null);
  const [cameraAction, setCameraAction] = useState(false);
  const [cameraError, setCameraError] = useState<string | null>(null);
  const [realtimeNotice, setRealtimeNotice] = useState<string | null>(null);
  const realtimeReady = useRef(false);
  const cameraWasActive = useRef(false);
  const realtimeNoticeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const acceptRealtimeState = useCallback((next: RealtimeState, reason?: string) => {
    if (reason === "runtime_ready" && next.ready && !realtimeReady.current) {
      setRealtimeNotice("Realtime mode active");
      if (realtimeNoticeTimer.current) clearTimeout(realtimeNoticeTimer.current);
      realtimeNoticeTimer.current = setTimeout(() => setRealtimeNotice(null), 4_000);
    }
    realtimeReady.current = next.ready;
    setRealtime(next);
  }, []);

  useEffect(() => {
    const onResize = () => setViewport({ width: window.innerWidth, height: window.innerHeight });
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  useEffect(() => saveWorkspace(workspace), [workspace]);
  useEffect(() => saveReaderDockLayout(readerDock), [readerDock]);

  useEffect(() => {
    let closed = false;
    let socket: WebSocket | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    const connect = () => {
      if (closed) return;
      socket = new WebSocket(`${WS_BASE}/ws/realtime`);
      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data as string) as {
            state?: RealtimeState; reason?: string;
          };
          if (message.state) acceptRealtimeState(message.state, message.reason);
        } catch { /* bounded runtime status is optional */ }
      };
      socket.onclose = () => {
        if (!closed) retry = setTimeout(connect, 1000);
      };
    };
    void api.realtime().then((state) => {
      if (!closed) acceptRealtimeState(state);
    }).catch(() => undefined);
    connect();
    return () => {
      closed = true;
      if (retry) clearTimeout(retry);
      if (realtimeNoticeTimer.current) clearTimeout(realtimeNoticeTimer.current);
      socket?.close();
    };
  }, [acceptRealtimeState]);

  useEffect(() => {
    let closed = false;
    const desiredActive = workspace.camera.open || realtime.enabled;
    setCameraAction(true);
    setCameraError(null);
    void (async () => {
      try {
        let state = await api.hardwareCamera();
        if (state.active !== desiredActive) {
          state = await api.setHardwareCamera(desiredActive);
        }
        if (!closed) setCamera(state);
      } catch (error) {
        if (!closed) setCameraError(error instanceof Error ? error.message : String(error));
      } finally {
        if (!closed) setCameraAction(false);
      }
    })();
    return () => { closed = true; };
  }, [realtime.enabled, realtime.phase, workspace.camera.open]);

  useEffect(() => {
    const active = camera?.active === true;
    if (active && !cameraWasActive.current) {
      setWorkspace((w) => w.camera.open ? w : ({
        ...w,
        camera: { ...w.camera, open: true, z: topZ(w) + 1 },
      }));
    }
    cameraWasActive.current = active;
  }, [camera?.active]);

  const toggleRealtime = useCallback(async () => {
    setRealtimeAction("power");
    setRealtimeError(null);
    try {
      const state = realtime.enabled ? await api.stopRealtime() : await api.startRealtime();
      acceptRealtimeState(state);
    } catch (error) {
      setRealtimeError(error instanceof Error ? error.message : String(error));
    } finally {
      setRealtimeAction(null);
    }
  }, [acceptRealtimeState, realtime.enabled]);

  const toggleCameraPane = useCallback(() => {
    setCameraError(null);
    setWorkspace((w) => ({
      ...w,
      camera: { ...w.camera, open: !w.camera.open, z: topZ(w) + 1 },
    }));
  }, []);

  const closeCameraPane = useCallback(() => {
    setWorkspace((w) => ({ ...w, camera: { ...w.camera, open: false } }));
  }, []);

  const toggleProactive = useCallback(async () => {
    setRealtimeAction("mode");
    setRealtimeError(null);
    try {
      acceptRealtimeState(await api.setRealtimeProactive(!realtime.proactive));
    } catch (error) {
      setRealtimeError(error instanceof Error ? error.message : String(error));
    } finally {
      setRealtimeAction(null);
    }
  }, [acceptRealtimeState, realtime.proactive]);

  // Any "open in reader" request opens the reader pane too.
  useEffect(() => onOpenReader(() => {
    setWorkspace((w) => ({ ...w, reader: { ...w.reader, open: true, z: topZ(w) + 1 } }));
  }), []);

  useEffect(() => onOpenSourceFile(() => {
    setWorkspace((w) => ({ ...w, reader: { ...w.reader, open: true, z: topZ(w) + 1 } }));
  }), []);

  useEffect(() => onOpenTasks(() => {
    setWorkspace((w) => ({ ...w, tasks: { ...w.tasks, open: true, z: topZ(w) + 1 } }));
  }), []);

  const focusPane = useCallback((id: PaneId) => {
    setWorkspace((w) => ({ ...w, [id]: { ...w[id], z: topZ(w) + 1 } }));
  }, []);

  const togglePane = useCallback((id: PaneId) => {
    if (isReaderModule(id) && readerDock[id].placement !== "floating") {
      setReaderDock((layout) => ({ ...layout, [id]: {
        ...layout[id],
        collapsed: workspace.reader.open ? !layout[id].collapsed : false,
      } }));
      setWorkspace((w) => ({ ...w, reader: { ...w.reader, open: true, z: topZ(w) + 1 } }));
      return;
    }
    setWorkspace((w) => ({ ...w, [id]: { ...w[id], open: !w[id].open, z: topZ(w) + 1 } }));
  }, [readerDock, workspace.reader.open]);

  const commitRect = useCallback((id: PaneId, rect: PaneRect) => {
    setWorkspace((w) => ({ ...w, [id]: { ...w[id], rect } }));
  }, []);

  const collapseReaderModule = useCallback((id: ReaderModuleId) => {
    setReaderDock((layout) => ({ ...layout, [id]: { ...layout[id], collapsed: true } }));
  }, []);

  const expandReaderModule = useCallback((id: ReaderModuleId) => {
    setReaderDock((layout) => ({ ...layout, [id]: { ...layout[id], collapsed: false } }));
  }, []);

  const floatReaderModule = useCallback((id: ReaderModuleId) => {
    setReaderDock((layout) => ({
      ...layout,
      [id]: { ...layout[id], placement: "floating", collapsed: false },
    }));
    setWorkspace((w) => ({ ...w, [id]: { ...w[id], open: true, z: topZ(w) + 1 } }));
    setDraggingReaderModule(null);
  }, []);

  const dockReaderModule = useCallback((
    id: ReaderModuleId,
    side: "left" | "right",
    position: ReaderDockPosition,
  ) => {
    setReaderDock((layout) => {
      const neighbors = (["knowledge", "source"] as const)
        .filter((candidate) => candidate !== id && layout[candidate].placement === side)
        .map((candidate) => layout[candidate].order);
      const order = position === "top"
        ? (neighbors.length ? Math.min(...neighbors) - 1 : 0)
        : (neighbors.length ? Math.max(...neighbors) + 1 : 0);
      return { ...layout, [id]: { placement: side, order, collapsed: false } };
    });
    setWorkspace((w) => ({
      ...w,
      [id]: { ...w[id], open: false },
      reader: { ...w.reader, open: true, z: topZ(w) + 1 },
    }));
    setDraggingReaderModule(null);
  }, []);

  const docking = useMemo<ReaderDockingProps>(() => ({
    layout: readerDock,
    dragging: draggingReaderModule,
    onCollapse: collapseReaderModule,
    onExpand: expandReaderModule,
    onFloat: floatReaderModule,
    onDock: dockReaderModule,
    onDragStart: setDraggingReaderModule,
    onDragEnd: () => setDraggingReaderModule(null),
  }), [
    collapseReaderModule,
    dockReaderModule,
    draggingReaderModule,
    expandReaderModule,
    floatReaderModule,
    readerDock,
  ]);

  const openPanes = useMemo(
    () => OBSIDIENCE_PANES.filter((def) => workspace[def.id].surfaceId === surfaceId &&
      workspace[def.id].open &&
      (!isReaderModule(def.id) || readerDock[def.id].placement === "floating")),
    [readerDock, surfaceId, workspace],
  );

  const paneIsVisible = (id: PaneId) => workspace[id].surfaceId === surfaceId && (isReaderModule(id)
    ? readerDock[id].placement === "floating"
      ? workspace[id].open
      : workspace.reader.open && !readerDock[id].collapsed
    : workspace[id].open);

  const microphoneLevel = typeof realtime.input_level === "number" && Number.isFinite(realtime.input_level)
    ? Math.min(1, Math.max(0, realtime.input_level))
    : 0;
  const microphoneLevelPercent = Math.round(microphoneLevel * 100);
  const cameraViewOpen = workspace.camera.open;
  const cameraTitle = cameraError ?? (cameraAction
    ? "Applying camera state"
    : cameraViewOpen
      ? camera?.active ? "Close camera video" : "Waking camera for video"
      : camera?.active ? "Camera hardware active for Realtime; open video view" : "Open camera video");

  return (
    <div data-obsidience-theme="obsidience" className="fixed inset-0 overflow-hidden bg-[#02060c] text-cyan-50">
      <GraphBackdrop />

      {/* top bar */}
      <header className="pointer-events-none absolute inset-x-0 top-0 z-40 flex items-center justify-between px-5 py-3">
        <h1 className="font-mono text-[13px] uppercase tracking-[0.4em] text-cyan-200/90 drop-shadow-[0_0_12px_rgba(34,211,238,0.45)]">
          Obsidience
        </h1>
        <div className="pointer-events-auto flex items-center gap-3">
          <div
            className="flex w-[22rem] flex-col gap-1 rounded border border-cyan-300/15 bg-[#020b14]/80 p-1"
            title={realtimeError ?? realtime.last_error ?? undefined}
          >
            <div className="flex items-center gap-1">
              <button
                type="button"
                aria-label={realtime.enabled ? "Disable real-time mode" : "Enable real-time mode"}
                aria-pressed={realtime.enabled}
                disabled={realtimeAction !== null || realtime.phase === "starting" || realtime.phase === "stopping"}
                onClick={() => void toggleRealtime()}
                className={`grid h-7 w-8 place-items-center rounded border transition-colors ${
                  realtime.enabled
                    ? "border-cyan-300/55 bg-cyan-400/15 text-cyan-100 shadow-[0_0_12px_rgba(34,211,238,0.18)]"
                    : realtime.phase === "error"
                      ? "border-red-400/45 bg-red-400/10 text-red-200"
                      : "border-cyan-300/15 text-cyan-300/55 hover:border-cyan-300/40 hover:text-cyan-100"
                } disabled:cursor-wait disabled:opacity-60`}
                title={realtime.ready ? "Realtime mode active" : realtime.enabled ? `Realtime ${realtime.phase}` : "Enable realtime mode"}
              >
                {realtime.phase === "starting" || realtime.phase === "stopping" || realtimeAction === "power"
                  ? <LoaderCircle size={15} className="animate-spin" />
                  : realtime.enabled ? <Mic size={15} /> : <MicOff size={15} />}
              </button>
              <button
                type="button"
                aria-label={cameraViewOpen ? "Close camera video" : "Open camera video"}
                aria-pressed={cameraViewOpen}
                disabled={cameraAction}
                onClick={toggleCameraPane}
                className={`grid h-7 w-8 place-items-center rounded border transition-colors ${cameraViewOpen
                  ? "border-cyan-300/55 bg-cyan-400/15 text-cyan-100 shadow-[0_0_12px_rgba(34,211,238,0.18)]"
                  : cameraError
                    ? "border-red-400/45 bg-red-400/10 text-red-200"
                    : camera?.active
                      ? "border-amber-300/40 bg-amber-300/10 text-amber-100/80"
                    : "border-cyan-300/15 text-cyan-300/55 hover:border-cyan-300/40 hover:text-cyan-100"
                } disabled:cursor-not-allowed disabled:opacity-60`}
                title={cameraTitle}
              >
                {cameraAction ? <LoaderCircle size={15} className="animate-spin" />
                  : cameraViewOpen ? <Eye size={15} /> : <EyeOff size={15} />}
              </button>
              <button
                type="button"
                aria-label={realtime.proactive ? "Disable proactive mode" : "Enable proactive mode"}
                aria-pressed={realtime.proactive}
                disabled={!realtime.ready || realtimeAction !== null}
                onClick={() => void toggleProactive()}
                className={`grid h-7 w-8 place-items-center rounded border transition-colors ${
                  realtime.proactive
                    ? "border-amber-300/60 bg-amber-300/15 text-amber-100 shadow-[0_0_12px_rgba(252,211,77,0.18)]"
                    : "border-cyan-300/15 text-cyan-300/55 hover:border-cyan-300/40 hover:text-cyan-100"
                } disabled:cursor-not-allowed disabled:opacity-25`}
                title={realtime.ready
                  ? realtime.proactive ? "Return to command-only mode" : "Enable proactive observation"
                  : "Real-time mode must finish loading first"}
              >
                {realtimeAction === "mode"
                  ? <LoaderCircle size={14} className="animate-spin" />
                  : realtime.proactive ? <Pause size={14} /> : <Play size={14} />}
              </button>
              <span className={`px-1 font-mono text-[9px] uppercase tracking-[0.18em] ${
                realtime.proactive ? "text-amber-200/80" : realtime.ready ? "text-cyan-200/70" : "text-cyan-300/35"
              }`}>
                {realtime.proactive ? "proactive" : realtime.ready ? "realtime" : realtime.phase}
              </span>
            </div>
            {realtime.enabled ? (
              <div className="flex flex-col gap-1 px-0.5 pb-0.5">
                <div
                  role="meter"
                  aria-label="Live speech recognition microphone level"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={microphoneLevelPercent}
                  className="flex items-center gap-1"
                  title={`Speech recognition input: ${microphoneLevelPercent}%`}
                >
                  <span className="shrink-0 font-mono text-[7px] uppercase tracking-[0.16em] text-cyan-300/45">
                    input
                  </span>
                  <span className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full border border-cyan-300/15 bg-cyan-950/70">
                    <span
                      className="block h-full rounded-full bg-gradient-to-r from-cyan-500 via-cyan-300 to-emerald-300 shadow-[0_0_8px_rgba(103,232,249,0.65)] transition-[width] duration-75 ease-out"
                      style={{ width: `${microphoneLevelPercent}%` }}
                    />
                  </span>
                </div>
                <div aria-live="polite" className="flex items-start gap-1 font-mono text-[9px] leading-4">
                  <span className="shrink-0 uppercase tracking-[0.14em] text-cyan-300/45">
                    {realtime.user_speaking
                      ? "hearing"
                      : realtime.live_transcript?.final ? "heard" : "listening"}
                  </span>
                  <span className="min-w-0 whitespace-normal break-words text-cyan-100/85">
                    {realtime.live_transcript?.text || "Listening…"}
                  </span>
                </div>
              </div>
            ) : null}
          </div>
          <nav className="flex items-center gap-1.5">
            {OBSIDIENCE_PANES.map((def) => (
              <button
                key={def.id}
                onClick={() => def.id === "camera" ? toggleCameraPane() : togglePane(def.id)}
                className={`rounded border px-2.5 py-1 font-mono text-[10px] uppercase tracking-[0.18em] transition-colors ${
                  paneIsVisible(def.id)
                    ? "border-cyan-300/50 bg-cyan-400/10 text-cyan-100"
                    : "border-cyan-300/15 text-cyan-300/50 hover:border-cyan-300/40 hover:text-cyan-100"
                }`}
              >
                {def.title}
              </button>
            ))}
          </nav>
        </div>
      </header>

      {realtimeNotice ? (
        <div
          role="status"
          aria-live="polite"
          className="pointer-events-none absolute left-1/2 top-14 z-40 -translate-x-1/2 rounded border border-cyan-300/45 bg-[#03101b]/95 px-4 py-2 font-mono text-[10px] uppercase tracking-[0.24em] text-cyan-100 shadow-[0_0_24px_rgba(34,211,238,0.2)]"
        >
          {realtimeNotice}
        </div>
      ) : null}

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
              onClose={() => def.id === "camera" ? closeCameraPane() : togglePane(def.id)}
              onRectCommit={(r) => commitRect(def.id, r)}
            >
              {def.id === "reader" ? <ReaderPaneBody docking={docking} />
                : def.id === "knowledge" ? <ReaderKnowledgePaneBody docking={docking} />
                  : def.id === "source" ? <ReaderSourcePaneBody docking={docking} />
                    : def.id === "camera" ? <CameraPaneBody active={camera?.active === true} activationError={cameraError} />
                    : staticPaneBody(def.id)}
            </PaneFrame>
          );
        })}
      </div>
    </div>
  );
}
