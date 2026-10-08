import { useEffect, useRef, useState } from "react";
import { onShellStageVisibility, type StageRegion } from "@/lib/shell-client";
import "./provider-graph.css";

const VIEWS = ["memory", "library", "code"];

/** One background stage; provider frames keep their own graph and render lifetime. */
export function GraphStage() {
  const [active, setActive] = useState(!document.hidden);
  // Each view pauses while its own part of the stage is locked, asleep or covered.
  const [shown, setShown] = useState<Record<string, boolean>>({});
  const frames = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const region = (view: string): StageRegion | null => {
      const frame = frames.current?.querySelector(`iframe[data-graph="${view}"]`);
      if (!frame || !innerWidth || !innerHeight) return null;
      const rect = frame.getBoundingClientRect();
      return { x: rect.left / innerWidth, y: rect.top / innerHeight,
        width: rect.width / innerWidth, height: rect.height / innerHeight };
    };
    const stops = VIEWS.map(view => onShellStageVisibility("samsung", visible =>
      setShown(current => current[view] === visible ? current : { ...current, [view]: visible }),
    () => region(view)));
    return () => stops.forEach(stop => stop());
  }, []);
  useEffect(() => {
    const changed = () => setActive(!document.hidden);
    document.addEventListener("visibilitychange", changed);
    return () => document.removeEventListener("visibilitychange", changed);
  }, []);
  function publishVisibility() {
    frames.current?.querySelectorAll("iframe").forEach(frame => frame.contentWindow?.postMessage({
      type: "obsidience-stage-visibility", visible: active && shown[frame.dataset.graph] !== false,
    }, location.origin));
  }
  useEffect(publishVisibility, [active, shown]);
  return <main className="graph-stage" aria-label="Obsidience graph stage">
    <div className="stage-views" ref={frames}>
      {VIEWS.map(view => <section key={view} aria-label={`${view} graph`}>
        <iframe title={`${view} graph`} data-graph={view} onLoad={publishVisibility}
          src={`?surface=${view === "library" ? "knowledge&graph=library" : view}&surface_id=samsung&stage=1`} />
      </section>)}
    </div>
  </main>;
}
