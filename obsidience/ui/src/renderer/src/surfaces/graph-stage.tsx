import { useEffect, useRef, useState } from "react";
import { onShellStageVisibility } from "@/lib/shell-client";
import "./provider-graph.css";

/** One background stage; provider frames keep their own graph and render lifetime. */
export function GraphStage() {
  const [active, setActive] = useState(!document.hidden);
  const [shellVisible, setShellVisible] = useState(true);
  const frames = useRef<HTMLDivElement>(null);
  useEffect(() => onShellStageVisibility("samsung", setShellVisible), []);
  useEffect(() => {
    const changed = () => setActive(!document.hidden);
    document.addEventListener("visibilitychange", changed);
    return () => document.removeEventListener("visibilitychange", changed);
  }, []);
  const visible = active && shellVisible;
  function publishVisibility() {
    frames.current?.querySelectorAll("iframe").forEach(frame => frame.contentWindow?.postMessage({
      type: "obsidience-stage-visibility", visible,
    }, location.origin));
  }
  useEffect(publishVisibility, [visible]);
  const views = ["memory", "library", "code"];
  return <main className="graph-stage" aria-label="Obsidience graph stage">
    <div className="stage-views" ref={frames}>
      {views.map(view => <section key={view} aria-label={`${view} graph`}>
        <iframe title={`${view} graph`} data-graph={view} onLoad={publishVisibility}
          src={`?surface=${view === "library" ? "knowledge&graph=library" : view}&surface_id=samsung&stage=1`} />
      </section>)}
    </div>
  </main>;
}
