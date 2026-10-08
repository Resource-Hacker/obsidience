import { GraphPublisher, type GraphCatalog, type GraphViewState } from "./graph-stream";
import type { ProviderPresentationFactory } from "./provider-graph-scene";

type BankView = {
  canvas: HTMLCanvasElement; command: Parameters<ProviderPresentationFactory>[1];
  redraw: () => void; consumers: (count: number) => void;
  catalog: GraphCatalog; state: GraphViewState;
};

/** One Memory stream owner, selecting among the existing per-bank canvases.
 * No extra graph, layout, fetch or capture loop belongs to the viewer. */
export class MemoryStagePresentation {
  private views = new Map<string, BankView>();
  private canvas = document.createElement("canvas");
  private context = this.canvas.getContext("2d", {alpha: false})!;
  private publisher: GraphPublisher;
  private selected = "";
  private consumers = 0;
  constructor() {
    this.canvas.width = this.canvas.height = 1;
    this.publisher = new GraphPublisher("memory", this.canvas, command => {
      if (command.action === "bank" && typeof command.value === "string") this.select(command.value);
      else this.views.get(this.selected)?.command(command);
    }, () => this.views.get(this.selected)?.redraw(), count => {
      this.consumers = count; this.views.get(this.selected)?.consumers(count);
      if (!count) this.canvas.width = this.canvas.height = 1;
    });
  }
  isSelected(bank: string) { return this.selected === bank; }
  select(bank: string) {
    const view = this.views.get(bank);
    if (!view) return;
    if (this.selected !== bank) {
      const previous = this.views.get(this.selected);
      previous?.command({action: "leave"}); previous?.consumers(0);
    }
    this.selected = bank; view.consumers(this.consumers);
    this.publisher.publishCatalog(view.catalog); this.publisher.publishState(view.state);
    view.redraw();
  }
  register(bank: string): ProviderPresentationFactory {
    return (canvas, command, redraw, consumers) => {
      const view: BankView = {canvas, command, redraw, consumers,
        catalog: {nodes: [], count: 0, links: 0}, state: {bank, loading: true}};
      this.views.set(bank, view);
      if (!this.selected) this.select(bank);
      return {
        publishCatalog: value => { view.catalog = value; if (this.isSelected(bank)) this.publisher.publishCatalog(value); },
        publishState: value => { view.state = value; if (this.isSelected(bank)) this.publisher.publishState(value); },
        frame: () => {
          if (!this.isSelected(bank) || !this.publisher.hasViewers || !canvas.width || !canvas.height) return;
          if (this.canvas.width !== canvas.width || this.canvas.height !== canvas.height) {
            this.canvas.width = canvas.width; this.canvas.height = canvas.height;
          }
          // Replace transparent pixels too, as Knowledge's transfer path does.
          // Source-over would retain old nodes and the previously selected bank.
          this.context.globalCompositeOperation = "copy";
          this.context.drawImage(canvas, 0, 0); this.publisher.frame();
        },
        dispose: () => {
          if (this.views.get(bank) !== view) return;
          this.views.delete(bank);
          if (this.isSelected(bank)) {
            this.selected = "";
            const next = this.views.keys().next().value;
            if (next) this.select(next);
          }
        },
      };
    };
  }
  dispose() {
    this.publisher.dispose(); this.views.clear(); this.selected = "";
    this.canvas.width = this.canvas.height = 1;
  }
}
