export interface KnowledgeLayoutAnchor {
  x: number;
  y: number;
}

export interface KnowledgeLayoutBounds {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

export interface KnowledgeLayoutViewport {
  width: number;
  height: number;
  bounds: KnowledgeLayoutBounds;
}

export const DEFAULT_KNOWLEDGE_HUB_ANCHOR: KnowledgeLayoutAnchor = {
  x: 0.5,
  y: 0.395,
};

