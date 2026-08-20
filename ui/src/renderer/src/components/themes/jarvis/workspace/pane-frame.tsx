import {
  Component,
  useRef,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import {
  clampPaneRect,
  type JarvisPaneId,
  type PaneRect,
  type PaneViewport,
} from "./workspace-state";

/** A crashing pane body must degrade to an in-pane message, never unmount
 *  the whole HUD (the voice session lives in this window). */
class PaneErrorBoundary extends Component<
  { title: string; children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return (
        <div className="flex h-full items-center justify-center p-6 text-center">
          <p className="font-mono text-[11px] leading-relaxed text-rose-200/80">
            The {this.props.title} pane hit an error. Close and reopen it from
            the Panes menu.
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}

/**
 * One floating workspace pane: a static JARVIS-styled frame with a
 * draggable title bar, a lock toggle, a close control, and an optional
 * resize grip. Drag and resize write directly to the element's style while
 * the pointer moves (no React re-render per frame — the knowledge canvas
 * keeps its frame budget) and commit a single clamped rect on release.
 * The chrome carries no animation classes: passive HUD pixels stay static.
 */
export function PaneFrame({
  id,
  title,
  rect,
  z,
  locked,
  resizable,
  minWidth,
  minHeight,
  viewport,
  onFocus,
  onClose,
  onRectCommit,
  children,
}: {
  id: JarvisPaneId;
  title: string;
  rect: PaneRect;
  z: number;
  locked: boolean;
  resizable: boolean;
  minWidth: number;
  minHeight: number;
  viewport: PaneViewport;
  onFocus: () => void;
  onClose: () => void;
  onRectCommit: (rect: PaneRect) => void;
  children: ReactNode;
}) {
  const rootRef = useRef<HTMLElement>(null);
  const liveRect = useRef<PaneRect>(rect);

  const beginPointerAdjust = (
    event: ReactPointerEvent,
    mode: "move" | "resize",
  ) => {
    if (locked || event.button !== 0) return;
    const root = rootRef.current;
    if (!root) return;
    event.preventDefault();
    const pointerId = event.pointerId;
    const start = { x: event.clientX, y: event.clientY, rect: { ...rect } };
    liveRect.current = { ...rect };
    let moved = false;
    const handle = event.currentTarget as HTMLElement;
    handle.setPointerCapture(pointerId);
    const onMove = (move: globalThis.PointerEvent) => {
      // Only the initiating pointer drives the drag: a second touch on the
      // title bar must not teleport the pane or end the gesture.
      if (move.pointerId !== pointerId) return;
      const dx = move.clientX - start.x;
      const dy = move.clientY - start.y;
      if (!moved && dx === 0 && dy === 0) return;
      moved = true;
      const next =
        mode === "move"
          ? { ...start.rect, x: start.rect.x + dx, y: start.rect.y + dy }
          : {
              ...start.rect,
              width: Math.max(start.rect.width + dx, minWidth),
              height: Math.max(start.rect.height + dy, minHeight),
            };
      liveRect.current = clampPaneRect(id, next, viewport);
      root.style.left = `${liveRect.current.x}px`;
      root.style.top = `${liveRect.current.y}px`;
      root.style.width = `${liveRect.current.width}px`;
      root.style.height = `${liveRect.current.height}px`;
    };
    const onUp = (up: globalThis.PointerEvent) => {
      if (up.pointerId !== pointerId) return;
      handle.removeEventListener("pointermove", onMove);
      handle.removeEventListener("pointerup", onUp);
      handle.removeEventListener("pointercancel", onUp);
      // A plain click must not persist a rect: an unmoved pane keeps its
      // responsive default so it can keep following the display size.
      if (moved) onRectCommit(liveRect.current);
    };
    handle.addEventListener("pointermove", onMove);
    handle.addEventListener("pointerup", onUp);
    handle.addEventListener("pointercancel", onUp);
  };

  return (
    <section
      ref={rootRef}
      data-jarvis-pane={id}
      data-pane-locked={locked}
      aria-label={`${title} pane`}
      className="pointer-events-auto absolute flex flex-col overflow-hidden rounded-xl border border-cyan-300/25 bg-[#030a10]/92 shadow-[0_0_45px_rgba(34,211,238,0.08)] backdrop-blur-md"
      style={{
        left: rect.x,
        top: rect.y,
        width: rect.width,
        height: rect.height,
        zIndex: z,
      }}
      onPointerDownCapture={onFocus}
    >
      <header
        data-pane-drag-handle
        onPointerDown={(event) => {
          // Buttons keep their own semantics; everything else drags.
          if ((event.target as HTMLElement).closest("button")) return;
          beginPointerAdjust(event, "move");
        }}
        className={`flex shrink-0 select-none items-center justify-between gap-3 border-b border-cyan-300/15 px-3 py-2 ${
          locked ? "cursor-default" : "cursor-grab"
        }`}
      >
        <h2 className="truncate font-mono text-[10px] uppercase tracking-[0.22em] text-cyan-100">
          {title}
        </h2>
        <div className="flex shrink-0 items-center gap-1.5">
          <button
            type="button"
            onClick={onClose}
            aria-label={`Close ${title} pane`}
            className="rounded border border-cyan-300/25 px-2 py-0.5 font-mono text-[10px] leading-none text-cyan-300/60 transition-colors hover:bg-cyan-300/10 hover:text-cyan-100 motion-reduce:transition-none"
          >
            ×
          </button>
        </div>
      </header>
      <div className="min-h-0 flex-1 overflow-hidden">
        <PaneErrorBoundary title={title}>{children}</PaneErrorBoundary>
      </div>
      {resizable && !locked && (
        <div
          data-pane-resize-handle
          onPointerDown={(event) => beginPointerAdjust(event, "resize")}
          className="absolute bottom-0 right-0 h-4 w-4 cursor-se-resize"
          title="Resize pane"
        >
          <div className="absolute bottom-1 right-1 h-2 w-2 border-b-2 border-r-2 border-cyan-300/40" />
        </div>
      )}
    </section>
  );
}
