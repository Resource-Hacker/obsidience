/** Reader: renders any vault note; opened by graph clicks and task links. */

import { useEffect, useState } from "react";
import { JarvisMarkdown } from "@/components/themes/jarvis/workspace/jarvis-markdown";
import { api, onOpenReader, type NoteDoc } from "@/lib/api";

export function ReaderPaneBody() {
  const [note, setNote] = useState<NoteDoc | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => onOpenReader((ref) => {
    setError(null);
    api.note(ref).then(setNote).catch((e) => setError(String(e)));
  }), []);

  if (error) return <p className="p-4 font-mono text-[11px] text-rose-300">{error}</p>;
  if (!note) {
    return (
      <p className="p-4 font-mono text-[11px] text-cyan-200/40">
        Click a node on the graph (or a task title) to read it here.
      </p>
    );
  }
  return (
    <div className="h-full overflow-y-auto p-4">
      <p className="font-mono text-[9px] uppercase tracking-[0.25em] text-cyan-300/40">{note.kind} · {note.ref}</p>
      <h1 className="mb-3 mt-1 font-mono text-[15px] uppercase tracking-[0.12em] text-cyan-50">{note.title}</h1>
      {Object.keys(note.meta).length ? (
        <div className="mb-3 rounded border border-cyan-300/10 bg-[#020a12] p-2">
          {Object.entries(note.meta).slice(0, 10).map(([k, v]) => (
            <p key={k} className="font-mono text-[10px] text-cyan-200/60">
              <span className="text-cyan-300/40">{k}:</span> {v}
            </p>
          ))}
        </div>
      ) : null}
      <div className="text-[12.5px] leading-relaxed text-cyan-100/90">
        <JarvisMarkdown content={note.body} />
      </div>
    </div>
  );
}
