/** The Knowledge stage's right-click menu for one node. */

import { useEffect, useRef } from "react";

export interface NodeMenuState { id: string; x: number; y: number }

export function NodeActionMenu({ menu, title, canEdit, onSelect, onRead, onClose, onClear }: {
  menu: NodeMenuState; title: string; canEdit: boolean;
  onSelect: () => void; onRead: () => void; onClose: () => void; onClear: () => void;
}) {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (event: PointerEvent) => {
      if (!root.current?.contains(event.target as Node)) onClose();
    };
    window.addEventListener("pointerdown", close);
    return () => window.removeEventListener("pointerdown", close);
  }, [onClose]);
  const left = Math.max(8, Math.min(menu.x + 12, window.innerWidth - 184));
  const top = Math.max(8, Math.min(menu.y + 12, window.innerHeight - 180));
  return (
    <div ref={root} className="pointer-events-auto fixed z-50 w-44 rounded-lg border border-cyan-300/25 bg-[#030a10]/95 p-1 shadow-[0_0_30px_rgba(34,211,238,0.12)] backdrop-blur"
      style={{ left, top }}>
      <p className="truncate border-b border-cyan-300/10 px-2 py-1 font-mono text-[8px] uppercase tracking-wider text-cyan-300/45">{title}</p>
      <button type="button" onClick={onSelect} className="block w-full rounded px-2 py-1.5 text-left font-mono text-[10px] uppercase tracking-wider text-cyan-100 hover:bg-cyan-300/10">Select node</button>
      <button type="button" onClick={onRead} className="block w-full rounded px-2 py-1.5 text-left font-mono text-[10px] uppercase tracking-wider text-cyan-100 hover:bg-cyan-300/10">Read</button>
      {canEdit ? <button type="button" onClick={onRead} className="block w-full rounded px-2 py-1.5 text-left font-mono text-[10px] uppercase tracking-wider text-cyan-100 hover:bg-cyan-300/10">Edit task</button> : null}
      <button type="button" onClick={onClear} className="block w-full rounded px-2 py-1.5 text-left font-mono text-[10px] uppercase tracking-wider text-cyan-300/60 hover:bg-cyan-300/10">Clear selection</button>
    </div>
  );
}
