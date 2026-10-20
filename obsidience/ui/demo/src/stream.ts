/** The demo build's "@/graph/stream": the real module, with each stage
 *  publisher's selection and hover state also handed to the demo chrome
 *  (the desktop delivers that state to the native Graph pane instead). */
import { GraphPublisher as StagePublisher, type GraphControl, type GraphViewState } from "../../src/renderer/src/graph/stream";
import type { GraphSource } from "@/lib/shell-client";

export * from "../../src/renderer/src/graph/stream";

export type PublishedState = { view: GraphSource; state: GraphViewState; command: (command: GraphControl) => void };
const listeners = new Set<(published: PublishedState) => void>();

export function onPublishedState(listener: (published: PublishedState) => void): () => void {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export class GraphPublisher extends StagePublisher {
  private demoView: GraphSource;
  private demoCommand: (command: GraphControl) => void;
  constructor(view: GraphSource, canvas: HTMLCanvasElement, command: (command: GraphControl) => void,
    redraw: () => void, consumers: (count: number) => void) {
    super(view, canvas, command, redraw, consumers);
    this.demoView = view; this.demoCommand = command;
  }
  publishState(value: GraphViewState) {
    super.publishState(value);
    // The base constructor may publish before this subclass is initialized.
    if (!this.demoView) return;
    for (const listener of listeners) listener({view: this.demoView, state: value, command: this.demoCommand});
  }
}
