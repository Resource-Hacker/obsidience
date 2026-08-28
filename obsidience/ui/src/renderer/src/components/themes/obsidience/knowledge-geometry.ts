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

export interface AmbientKnowledgeGeometry {
  anchor: KnowledgeLayoutAnchor;
  viewport: KnowledgeLayoutViewport;
}

export interface KnowledgeRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

export const DEFAULT_KNOWLEDGE_HUB_ANCHOR: KnowledgeLayoutAnchor = {
  x: 0.5,
  y: 0.395,
};

export const INSPECT_KNOWLEDGE_HUB_ANCHOR: KnowledgeLayoutAnchor = {
  x: 0.5,
  y: 0.5,
};

function clampUnit(value: number): number {
  return Math.max(0, Math.min(1, value));
}

/**
 * Convert the rendered arc-reactor center into the graph canvas coordinate
 * space. Quantization prevents sub-pixel ResizeObserver noise from starting
 * a redundant one-shot layout worker.
 */
export function normalizedKnowledgeHubAnchor(
  container: KnowledgeRect,
  reactor: KnowledgeRect,
): KnowledgeLayoutAnchor | null {
  if (
    !Number.isFinite(container.left) ||
    !Number.isFinite(container.top) ||
    !Number.isFinite(container.width) ||
    !Number.isFinite(container.height) ||
    !Number.isFinite(reactor.left) ||
    !Number.isFinite(reactor.top) ||
    !Number.isFinite(reactor.width) ||
    !Number.isFinite(reactor.height) ||
    container.width <= 0 ||
    container.height <= 0 ||
    reactor.width <= 0 ||
    reactor.height <= 0
  ) {
    return null;
  }
  const quantize = (value: number) => Math.round(clampUnit(value) * 10_000) / 10_000;
  return {
    x: quantize(
      (reactor.left + reactor.width / 2 - container.left) / container.width,
    ),
    y: quantize(
      (reactor.top + reactor.height / 2 - container.top) / container.height,
    ),
  };
}

export function sameKnowledgeHubAnchor(
  left: KnowledgeLayoutAnchor | null,
  right: KnowledgeLayoutAnchor | null,
): boolean {
  if (left === right) return true;
  if (!left || !right) return false;
  return left.x === right.x && left.y === right.y;
}

function quantize(value: number, places = 10_000): number {
  return Math.round(value * places) / places;
}

export function measuredAmbientKnowledgeGeometry(
  container: KnowledgeRect,
  reactor: KnowledgeRect,
  transcriptDeck?: KnowledgeRect | null,
): AmbientKnowledgeGeometry | null {
  const anchor = normalizedKnowledgeHubAnchor(container, reactor);
  if (!anchor) return null;

  const deckIsVisible = Boolean(
    transcriptDeck &&
      transcriptDeck.width > 0 &&
      transcriptDeck.height > 0 &&
      transcriptDeck.top > container.top &&
      transcriptDeck.top < container.top + container.height,
  );
  const deckTop = deckIsVisible
    ? (transcriptDeck!.top - container.top) / container.height
    : 0.965;
  // The transcript is a movable pane: the bottom carve only applies while
  // it actually sits in the lower band (its classic docked home). A pane
  // parked above the reactor band must not squeeze the whole graph into
  // the strip behind itself — the operator chose overlap; keep the full
  // stage instead (adversarial review 2026-08-02).
  const paneCarvesBottom = deckTop > anchor.y + 0.165;
  const bottom = paneCarvesBottom
    ? Math.max(anchor.y + 0.14, Math.min(0.955, deckTop - 0.025))
    : 0.955;
  return {
    anchor,
    viewport: {
      width: Math.max(1, Math.round(container.width)),
      height: Math.max(1, Math.round(container.height)),
      bounds: {
        left: 0.055,
        right: 0.945,
        top: 0.075,
        bottom: quantize(bottom),
      },
    },
  };
}

export function inspectKnowledgeViewport(
  ambient: KnowledgeLayoutViewport,
): KnowledgeLayoutViewport {
  const reviewPanelWidth = Math.min(42 * 16, ambient.width * 0.48);
  return {
    width: Math.max(1, Math.round(ambient.width - reviewPanelWidth - 24)),
    height: ambient.height,
    bounds: {
      left: 0.06,
      right: 0.94,
      top: 0.085,
      bottom: 0.915,
    },
  };
}

export function sameAmbientKnowledgeGeometry(
  left: AmbientKnowledgeGeometry | null,
  right: AmbientKnowledgeGeometry | null,
): boolean {
  if (left === right) return true;
  if (!left || !right) return false;
  return (
    sameKnowledgeHubAnchor(left.anchor, right.anchor) &&
    left.viewport.width === right.viewport.width &&
    left.viewport.height === right.viewport.height &&
    left.viewport.bounds.left === right.viewport.bounds.left &&
    left.viewport.bounds.right === right.viewport.bounds.right &&
    left.viewport.bounds.top === right.viewport.bounds.top &&
    left.viewport.bounds.bottom === right.viewport.bounds.bottom
  );
}
