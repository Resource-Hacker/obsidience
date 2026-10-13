import * as THREE from "three";

const MAX_LABELS = 18;
const LABEL_FILL = "rgba(2, 8, 14, 0.86)";
const LABEL_TEXT = "rgba(240, 249, 255, 0.98)";

export interface Knowledge3dLabelMeta {
  label: string;
  role: "root" | "section" | "claim";
  depth: number;
  branch: string;
  radius: number;
  accent: string;
  accentSoft: string;
}

interface LabelLayout {
  id: string;
  meta: Knowledge3dLabelMeta;
  lines: string[];
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
  material: THREE.LineDashedMaterial;
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
    focusActive: boolean,
    now: number,
  ) => void;
  render: (renderer: THREE.WebGLRenderer) => void;
  dispose: () => void;
}

function labelLines(label: string, maximumLineLength = 24): string[] {
  const normalized = label.trim().replace(/\s+/gu, " ");
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
    const lines = labelLines(meta.label, meta.role === "root" ? 28 : 24);
    const characterWidth =
      meta.role === "root" ? 10.7 : meta.role === "section" ? 7.35 : 7;
    const textWidth =
      Math.max(...lines.map((line) => line.length)) * characterWidth;
    const boxWidth = Math.max(48, textWidth + 24);
    const boxHeight = lines.length * 13 + 10;
    const outward = point.x >= width / 2 ? 1 : -1;
    const offset =
      meta.role === "root" ? 36 : meta.role === "section" ? 30 : 18;
    let centerX =
      meta.role === "root"
        ? point.x
        : point.x + outward * (offset + boxWidth / 2);
    let centerY =
      meta.role === "root" ? point.y - offset - boxHeight / 2 : point.y - 6;
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
    const endX = Math.max(bounds.left, Math.min(bounds.right, point.x));
    const endY = Math.max(bounds.top, Math.min(bounds.bottom, point.y));
    const deltaX = endX - point.x;
    const deltaY = endY - point.y;
    const distance = Math.max(1, Math.hypot(deltaX, deltaY));
    const startRadius =
      meta.role === "root" ? 22 : meta.role === "section" ? 16 : 9;
    return [
      {
        id,
        meta,
        lines,
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

function roundedRectangle(
  context: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
): void {
  const corner = Math.min(radius, width / 2, height / 2);
  context.beginPath();
  context.moveTo(x + corner, y);
  context.lineTo(x + width - corner, y);
  context.quadraticCurveTo(x + width, y, x + width, y + corner);
  context.lineTo(x + width, y + height - corner);
  context.quadraticCurveTo(
    x + width,
    y + height,
    x + width - corner,
    y + height,
  );
  context.lineTo(x + corner, y + height);
  context.quadraticCurveTo(x, y + height, x, y + height - corner);
  context.lineTo(x, y + corner);
  context.quadraticCurveTo(x, y, x + corner, y);
  context.closePath();
}

function drawCenteredSpacedText(
  context: CanvasRenderingContext2D,
  text: string,
  centerX: number,
  centerY: number,
  letterSpacing: number,
): void {
  const characters = [...text];
  const widths = characters.map(
    (character) => context.measureText(character).width,
  );
  const total =
    widths.reduce((sum, value) => sum + value, 0) +
    Math.max(0, characters.length - 1) * letterSpacing;
  let cursor = centerX - total / 2;
  context.textAlign = "left";
  for (let index = 0; index < characters.length; index += 1) {
    context.fillText(characters[index], cursor, centerY);
    cursor += widths[index] + letterSpacing;
  }
}

function createLabelTexture(
  layout: LabelLayout,
  pixelRatio: number,
  focusActive: boolean,
): THREE.CanvasTexture {
  const scale = Math.max(1, Math.min(2, pixelRatio));
  const canvas = document.createElement("canvas");
  canvas.width = Math.ceil(layout.width * scale);
  canvas.height = Math.ceil(layout.height * scale);
  const context = canvas.getContext("2d");
  if (!context) throw new Error("Unable to create label canvas");
  context.scale(scale, scale);

  const inset = layout.meta.depth === 1 ? 0.8 : 0.5;
  roundedRectangle(
    context,
    inset,
    inset,
    layout.width - inset * 2,
    layout.height - inset * 2,
    layout.meta.depth === 1 ? 3 : 2,
  );
  context.fillStyle = LABEL_FILL;
  context.fill();
  context.strokeStyle =
    layout.meta.depth === 1 ? layout.meta.accent : layout.meta.accentSoft;
  context.lineWidth = layout.meta.depth === 1 ? 1.1 : 0.75;
  context.setLineDash(focusActive ? [4, 7] : []);
  context.stroke();
  context.setLineDash([]);

  context.beginPath();
  context.moveTo(3, 4);
  context.lineTo(3, layout.height - 4);
  context.strokeStyle = layout.meta.accent;
  context.lineWidth = 2.2;
  context.stroke();

  let fontSize = 10.5;
  let fontWeight = 400;
  let letterSpacing = 0.26;
  if (layout.meta.role === "root") {
    fontSize = 14;
    fontWeight = 600;
    letterSpacing = 1.96;
  } else if (layout.meta.role === "section") {
    fontWeight = 600;
    fontSize = layout.meta.depth === 1 ? 12.5 : layout.meta.depth === 2 ? 11.5 : 10.5;
    letterSpacing = fontSize * (layout.meta.depth === 1 ? 0.115 : layout.meta.depth === 2 ? 0.09 : 0.075);
  }
  context.font = `${fontWeight} ${fontSize}px "JetBrains Mono", ui-monospace, monospace`;
  context.fillStyle =
    layout.meta.role === "root" ? "rgba(224, 242, 254, 0.9)" : LABEL_TEXT;
  context.textBaseline = "middle";
  const firstLineY =
    layout.height / 2 - ((layout.lines.length - 1) * 13) / 2;
  layout.lines.forEach((line, index) => {
    drawCenteredSpacedText(
      context,
      line,
      layout.width / 2,
      firstLineY + index * 13,
      letterSpacing,
    );
  });

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
  focusActive: boolean,
): string {
  return [
    layout.meta.label,
    layout.meta.role,
    layout.meta.depth,
    layout.meta.accent,
    layout.meta.accentSoft,
    pixelRatio,
    focusActive ? 1 : 0,
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

    update(projected, labelIds, activeNodeIds, metadata, focusActive, now) {
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
        const signature = labelSignature(layout, pixelRatio, focusActive);
        let label = labelSprites.get(layout.id);
        if (!label || label.signature !== signature) {
          if (label) disposeLabel(label);
          const material = new THREE.SpriteMaterial({
            map: createLabelTexture(layout, pixelRatio, focusActive),
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
          const material = new THREE.LineDashedMaterial({
            color: layout.meta.accent,
            dashSize: 3,
            gapSize: 6,
            opacity: 0.72,
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
        leader.line.computeLineDistances();
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
