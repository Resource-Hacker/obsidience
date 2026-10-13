import * as THREE from "three";

// Labels are survey callouts: a thin leader from the marked point to a caption
// in light monospace capitals, inside a thin box in the branch colour. The
// box's dark fill keeps the caption in front of whatever the graph draws
// behind it.
const MAX_LABELS = 18;
const LABEL_FILL = "rgba(3, 3, 4, 0.86)";
const LABEL_TEXT = "#ffffff";
const LABEL_DIM = "rgba(255, 255, 255, 0.62)";
const LINE_HEIGHT = 13;

export interface Knowledge3dLabelMeta {
  label: string;
  role: "root" | "section" | "claim";
  depth: number;
  branch: string;
  radius: number;
  accent: string;
}

interface LabelLayout {
  id: string;
  meta: Knowledge3dLabelMeta;
  lines: string[];
  /** Dim second caption: where the point sits in the hierarchy. */
  note: string;
  fontSize: number;
  letterSpacing: number;
  width: number;
  height: number;
  centerX: number;
  centerY: number;
  startX: number;
  startY: number;
  endX: number;
  endY: number;
}

interface LabelSprite {
  signature: string;
  sprite: THREE.Sprite;
}

interface LeaderLine {
  geometry: THREE.BufferGeometry;
  line: THREE.Line;
  material: THREE.LineBasicMaterial;
}

interface ActiveNodeSprites {
  focus: THREE.Sprite;
  focusMaterial: THREE.SpriteMaterial;
  wave: THREE.Sprite;
  waveMaterial: THREE.SpriteMaterial;
}

export interface Knowledge3dLabelLayer {
  resize: (width: number, height: number, pixelRatio: number) => void;
  update: (
    projected: ReadonlyMap<string, { x: number; y: number }>,
    labelIds: readonly string[],
    activeNodeIds: ReadonlySet<string>,
    metadata: ReadonlyMap<string, Knowledge3dLabelMeta>,
    now: number,
  ) => void;
  render: (renderer: THREE.WebGLRenderer) => void;
  dispose: () => void;
}

function labelLines(label: string, maximumLineLength = 24): string[] {
  const normalized = label.trim().replace(/\s+/gu, " ").toUpperCase();
  if (normalized.length <= maximumLineLength || !normalized.includes(" ")) {
    return [normalized];
  }
  const words = normalized.split(" ");
  let split = 1;
  let best = Number.POSITIVE_INFINITY;
  for (let index = 1; index < words.length; index += 1) {
    const longest = Math.max(
      words.slice(0, index).join(" ").length,
      words.slice(index).join(" ").length,
    );
    if (longest < best) {
      best = longest;
      split = index;
    }
  }
  return [words.slice(0, split).join(" "), words.slice(split).join(" ")];
}

function layoutLabels(
  ids: readonly string[],
  projected: ReadonlyMap<string, { x: number; y: number }>,
  metadata: ReadonlyMap<string, Knowledge3dLabelMeta>,
  width: number,
  height: number,
): LabelLayout[] {
  const occupied: Array<{
    left: number;
    right: number;
    top: number;
    bottom: number;
  }> = [];
  return ids.slice(0, MAX_LABELS).flatMap((id) => {
    const point01 = projected.get(id);
    const meta = metadata.get(id);
    if (
      !point01 ||
      !meta ||
      point01.x < -0.05 ||
      point01.x > 1.05 ||
      point01.y < -0.05 ||
      point01.y > 1.05
    ) {
      return [];
    }
    const point = { x: point01.x * width, y: point01.y * height };
    const root = meta.role === "root";
    const lines = labelLines(meta.label, root ? 28 : 24);
    const note = root ? "" : [meta.branch, meta.role === "claim" ? "article" : `level ${meta.depth}`]
      .filter(Boolean).join(" \u00b7 ").toUpperCase();
    const fontSize = root ? 13 : meta.role === "section" ? 10.5 : 10;
    const letterSpacing = fontSize * (root ? 0.32 : 0.08);
    // Monospace advance is 0.6 em.
    const textWidth = Math.max(
      ...lines.map((line) => line.length * (fontSize * 0.6 + letterSpacing)),
      note.length * (8 * 0.6 + 1.2),
    );
    const boxWidth = Math.max(40, textWidth + 14);
    const boxHeight = lines.length * LINE_HEIGHT + (note ? 17 : 0) + 8;
    const outward = point.x >= width / 2 ? 1 : -1;
    const reach = root ? 0 : meta.role === "section" ? 22 : 16;
    let centerX = root ? point.x : point.x + outward * (reach + boxWidth / 2);
    let centerY = point.y - (root ? 34 : 20) - boxHeight / 2;
    centerX = Math.max(
      boxWidth / 2 + 8,
      Math.min(width - boxWidth / 2 - 8, centerX),
    );
    centerY = Math.max(
      boxHeight / 2 + 8,
      Math.min(height - boxHeight / 2 - 8, centerY),
    );
    let bounds = {
      left: centerX - boxWidth / 2,
      right: centerX + boxWidth / 2,
      top: centerY - boxHeight / 2,
      bottom: centerY + boxHeight / 2,
    };
    for (
      let lane = 0;
      lane < 10 &&
      occupied.some(
        (other) =>
          !(
            bounds.right + 4 < other.left ||
            bounds.left - 4 > other.right ||
            bounds.bottom + 4 < other.top ||
            bounds.top - 4 > other.bottom
          ),
      );
      lane += 1
    ) {
      centerY = Math.max(
        boxHeight / 2 + 8,
        Math.min(
          height - boxHeight / 2 - 8,
          centerY +
            (lane % 2 === 0 ? 1 : -1) * (Math.floor(lane / 2) + 1) * 28,
        ),
      );
      bounds = {
        left: centerX - boxWidth / 2,
        right: centerX + boxWidth / 2,
        top: centerY - boxHeight / 2,
        bottom: centerY + boxHeight / 2,
      };
    }
    occupied.push(bounds);
    // The leader meets the box at its near lower corner.
    const endX = outward > 0 ? bounds.left : bounds.right;
    const endY = bounds.bottom - 0.5;
    const deltaX = endX - point.x;
    const deltaY = endY - point.y;
    const distance = Math.max(1, Math.hypot(deltaX, deltaY));
    const startRadius = meta.role === "section" ? 9 : 5;
    return [
      {
        id,
        meta,
        lines,
        note,
        fontSize,
        letterSpacing,
        width: boxWidth,
        height: boxHeight,
        centerX,
        centerY,
        endX,
        endY,
        startX:
          point.x +
          (deltaX / distance) * Math.min(distance, startRadius),
        startY:
          point.y +
          (deltaY / distance) * Math.min(distance, startRadius),
      },
    ];
  });
}

function createLabelTexture(
  layout: LabelLayout,
  pixelRatio: number,
): THREE.CanvasTexture {
  const scale = Math.max(1, Math.min(2, pixelRatio));
  const canvas = document.createElement("canvas");
  canvas.width = Math.ceil(layout.width * scale);
  canvas.height = Math.ceil(layout.height * scale);
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Unable to create label canvas");
  context.scale(scale, scale);
  const edge = 7;
  context.fillStyle = LABEL_FILL;
  context.fillRect(0, 0, layout.width, layout.height);
  context.strokeStyle = layout.meta.accent;
  context.lineWidth = 1;
  context.strokeRect(0.5, 0.5, layout.width - 1, layout.height - 1);
  context.textAlign = "left";
  context.textBaseline = "middle";
  context.font = `300 ${layout.fontSize}px "JetBrains Mono", ui-monospace, monospace`;
  context.letterSpacing = `${layout.letterSpacing}px`;
  context.fillStyle = LABEL_TEXT;
  layout.lines.forEach((line, index) => {
    context.fillText(line, edge, 4 + LINE_HEIGHT / 2 + index * LINE_HEIGHT);
  });
  if (layout.note) {
    // A hairline in the branch colour parts the title from where it lives.
    const rule = 4 + layout.lines.length * LINE_HEIGHT + 2;
    context.globalAlpha = 0.6;
    context.fillStyle = layout.meta.accent;
    context.fillRect(6, rule, layout.width - 12, 1);
    context.globalAlpha = 1;
    context.font = '300 8px "JetBrains Mono", ui-monospace, monospace';
    context.letterSpacing = "1.2px";
    context.fillStyle = LABEL_DIM;
    context.fillText(layout.note, edge, rule + 9);
  }

  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.generateMipmaps = false;
  texture.minFilter = THREE.LinearFilter;
  texture.magFilter = THREE.LinearFilter;
  return texture;
}

function createRingTexture(fillAlpha: number, strokeAlpha: number): THREE.CanvasTexture {
  const canvas = document.createElement("canvas");
  canvas.width = 96;
  canvas.height = 96;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Unable to create active-node canvas");
  context.beginPath();
  context.arc(48, 48, 42, 0, Math.PI * 2);
  context.fillStyle = `rgba(255, 255, 255, ${fillAlpha})`;
  context.fill();
  context.strokeStyle = `rgba(255, 255, 255, ${strokeAlpha})`;
  context.lineWidth = 3;
  context.stroke();
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.generateMipmaps = false;
  texture.minFilter = THREE.LinearFilter;
  texture.magFilter = THREE.LinearFilter;
  return texture;
}

function labelSignature(
  layout: LabelLayout,
  pixelRatio: number,
): string {
  return [
    layout.meta.label,
    layout.meta.role,
    layout.meta.depth,
    layout.meta.branch,
    layout.meta.accent,
    pixelRatio,
  ].join("|");
}

function stablePhase(id: string): number {
  let hash = 0;
  for (const character of id) {
    hash = (hash * 31 + character.charCodeAt(0)) | 0;
  }
  return (Math.abs(hash) % 1000) / 1000;
}

export function createKnowledge3dLabelLayer(): Knowledge3dLabelLayer {
  const scene = new THREE.Scene();
  const camera = new THREE.OrthographicCamera(0, 1, 1, 0, -10, 10);
  camera.position.z = 1;
  const labelSprites = new Map<string, LabelSprite>();
  const leaderLines = new Map<string, LeaderLine>();
  const activeSprites = new Map<string, ActiveNodeSprites>();
  const focusTexture = createRingTexture(0.13, 0.9);
  const waveTexture = createRingTexture(0.035, 0.82);
  let width = 1;
  let height = 1;
  let pixelRatio = 1;
  let hasContent = false;

  const disposeLabel = (entry: LabelSprite): void => {
    scene.remove(entry.sprite);
    entry.sprite.material.map?.dispose();
    entry.sprite.material.dispose();
  };
  const disposeLeader = (entry: LeaderLine): void => {
    scene.remove(entry.line);
    entry.geometry.dispose();
    entry.material.dispose();
  };
  const disposeActive = (entry: ActiveNodeSprites): void => {
    scene.remove(entry.focus, entry.wave);
    entry.focusMaterial.dispose();
    entry.waveMaterial.dispose();
  };

  return {
    resize(nextWidth, nextHeight, nextPixelRatio) {
      width = Math.max(1, nextWidth);
      height = Math.max(1, nextHeight);
      pixelRatio = nextPixelRatio;
      camera.left = 0;
      camera.right = width;
      camera.top = height;
      camera.bottom = 0;
      camera.updateProjectionMatrix();
    },

    update(projected, labelIds, activeNodeIds, metadata, now) {
      const labels = layoutLabels(labelIds, projected, metadata, width, height);
      const wantedLabels = new Set(labels.map((entry) => entry.id));
      for (const [id, entry] of labelSprites) {
        if (!wantedLabels.has(id)) {
          disposeLabel(entry);
          labelSprites.delete(id);
        }
      }
      for (const [id, entry] of leaderLines) {
        if (!wantedLabels.has(id) || metadata.get(id)?.role === "root") {
          disposeLeader(entry);
          leaderLines.delete(id);
        }
      }

      labels.forEach((layout, index) => {
        const signature = labelSignature(layout, pixelRatio);
        let label = labelSprites.get(layout.id);
        if (!label || label.signature !== signature) {
          if (label) disposeLabel(label);
          const material = new THREE.SpriteMaterial({
            map: createLabelTexture(layout, pixelRatio),
            transparent: true,
            depthTest: false,
            depthWrite: false,
            toneMapped: false,
          });
          const sprite = new THREE.Sprite(material);
          sprite.renderOrder = 30 + index;
          scene.add(sprite);
          label = { signature, sprite };
          labelSprites.set(layout.id, label);
        }
        label.sprite.position.set(layout.centerX, height - layout.centerY, 0);
        label.sprite.scale.set(layout.width, layout.height, 1);
        label.sprite.renderOrder = 30 + index;

        if (layout.meta.role === "root") return;
        let leader = leaderLines.get(layout.id);
        if (!leader) {
          const geometry = new THREE.BufferGeometry();
          geometry.setAttribute(
            "position",
            new THREE.BufferAttribute(new Float32Array(6), 3).setUsage(
              THREE.DynamicDrawUsage,
            ),
          );
          const material = new THREE.LineBasicMaterial({
            opacity: 0.8,
            transparent: true,
            depthTest: false,
            depthWrite: false,
            toneMapped: false,
          });
          const line = new THREE.Line(geometry, material);
          line.renderOrder = 20;
          scene.add(line);
          leader = { geometry, line, material };
          leaderLines.set(layout.id, leader);
        }
        const positions = leader.geometry.getAttribute("position") as THREE.BufferAttribute;
        positions.setXYZ(0, layout.startX, height - layout.startY, 0);
        positions.setXYZ(1, layout.endX, height - layout.endY, 0);
        positions.needsUpdate = true;
        leader.material.color.set(layout.meta.accent);
      });

      const wantedActive = new Set<string>();
      for (const id of activeNodeIds) {
        const point = projected.get(id);
        const meta = metadata.get(id);
        if (!point || !meta || meta.role === "root") continue;
        wantedActive.add(id);
        let active = activeSprites.get(id);
        if (!active) {
          const focusMaterial = new THREE.SpriteMaterial({
            map: focusTexture,
            transparent: true,
            depthTest: false,
            depthWrite: false,
            toneMapped: false,
          });
          const waveMaterial = new THREE.SpriteMaterial({
            map: waveTexture,
            transparent: true,
            depthTest: false,
            depthWrite: false,
            toneMapped: false,
          });
          const focus = new THREE.Sprite(focusMaterial);
          const wave = new THREE.Sprite(waveMaterial);
          focus.renderOrder = 12;
          wave.renderOrder = 11;
          scene.add(wave, focus);
          active = { focus, focusMaterial, wave, waveMaterial };
          activeSprites.set(id, active);
        }
        const x = point.x * width;
        const y = height - point.y * height;
        const radius = meta.radius + (meta.role === "claim" ? 4 : 3);
        const phase = (now / 3800 + stablePhase(id)) % 1;
        const waveAmount = 0.5 - Math.cos(phase * Math.PI * 2) * 0.5;
        active.focus.position.set(x, y, 0);
        active.wave.position.set(x, y, 0);
        active.focus.scale.setScalar(radius * 2);
        active.wave.scale.setScalar((radius + 7) * 2 * (0.78 + waveAmount * 0.64));
        active.focusMaterial.color.set(meta.accent);
        active.waveMaterial.color.set(meta.accent);
        active.focusMaterial.opacity = 0.82;
        active.waveMaterial.opacity = 0.08 + waveAmount * 0.54;
      }
      for (const [id, entry] of activeSprites) {
        if (!wantedActive.has(id)) {
          disposeActive(entry);
          activeSprites.delete(id);
        }
      }
      hasContent = labelSprites.size > 0 || activeSprites.size > 0;
    },

    render(renderer) {
      if (hasContent) renderer.render(scene, camera);
    },

    dispose() {
      for (const entry of labelSprites.values()) disposeLabel(entry);
      labelSprites.clear();
      for (const entry of leaderLines.values()) disposeLeader(entry);
      leaderLines.clear();
      for (const entry of activeSprites.values()) disposeActive(entry);
      activeSprites.clear();
      focusTexture.dispose();
      waveTexture.dispose();
      scene.clear();
    },
  };
}
