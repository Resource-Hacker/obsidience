import {
  layoutKnowledgeGraph,
  type KnowledgeLayout,
  type KnowledgeLayoutInput,
} from "./knowledge-layout";

interface LayoutRequest {
  requestId: number;
  input: KnowledgeLayoutInput;
}

interface LayoutResponse {
  requestId: number;
  layout: KnowledgeLayout;
}

const workerScope = self as unknown as {
  onmessage: ((event: MessageEvent<LayoutRequest>) => void) | null;
  postMessage(message: LayoutResponse): void;
};

workerScope.onmessage = (event) => {
  workerScope.postMessage({
    requestId: event.data.requestId,
    layout: layoutKnowledgeGraph(event.data.input),
  });
};

