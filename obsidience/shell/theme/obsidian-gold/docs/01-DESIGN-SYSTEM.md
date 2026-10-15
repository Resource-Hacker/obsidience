# Obsidian Gold design system

## Material and hierarchy

Canvas is near-black `#090d0e`; reading surfaces are `#0d1113`; raised controls use `#161b1d`. Brand brass is `#c6a56b`, with `#efcf91` for focus and occasional emphasis. Main text is warm off-white `#eee9dc`; supporting text is `#b8b2a5`. Gold is the architectural frame, not the color of every number or status. Success, warning, failure and information retain distinct colors plus explicit labels or icons.

Texture belongs only on outer chrome and wallpaper, at approximately 2.5% effective opacity. Data tables, body text, code, graph evidence and charts have smooth opaque backgrounds. Do not use backdrop blur, translucency, chromatic aberration, pulsing neon, scanline flicker or a frame-time shader for grain. Bevels are restrained and internal to the illustrated chrome; production outer borders remain compositor-owned.

Gold arcs are sparse architectural seams. Never put an arc through a table, reading column, input field or auth prompt. The original SVG wallpaper is an optional presentation asset, not a command to replace the live graph stage.

## Typography and density

Body text: 14 logical px minimum by default, 1.5 line height. Reader text: 15–16 logical px, line length approximately 70–82 characters. Technical labels and metadata: 12 px, with short 10–11 px decorative labels only where not essential to operating a control. Pane titles: 14 px. Main section headings: 18–26 px. Technical type uses an installed JetBrains Mono or monospace fallback; no fonts are shipped.

Default controls are 36 px high; touch variants 44 px. Rows are approximately 40–48 px. Compact mode reduces whitespace, not text legibility or essential target area. At 200% text scale, narrow views reflow and scroll internally rather than clipping.

The native pane title strip remains 36 px in this preset. Native compositor gaps remain 5 logical px and the established pane grid remains 10 px. Design spacing uses 4/8/12/16/24/32 px inside content, not a competing window grid.

## Reusable components

| Component | Visual contract | Existing implementation seam |
|---|---|---|
| Pane frame | Opaque body, quiet inactive chrome, clear keyboard focus | `qml/workspace/PaneFrame.qml` and compositor border adapter |
| Module header | One title, context, bounded actions; no competing drag owner | `PaneModuleHeader` / existing header components |
| Button | Neutral default, brass primary, visible disabled/focus/pending state | Shared `components/visual` controls |
| Field/select | Smooth dark inset, readable label, error/help text | Shared Qt control palette or wrappers |
| Section/panel | 1-px structural edge, 8-px radius, no glass | Existing pane composition |
| Row/table | Clear primary identity, secondary provenance, explicit status | Existing model delegates |
| Status chip | Color plus text/icon; no health inference | Existing service/task state |
| Trace/receipt | Actor, target, dispatched/uncertain/verified outcome | Existing runtime receipts |
| Modal | Named target, consequence, cancel and affirmative action | Existing owning operation |
| Graph inspector | Stable selected identity and provider-specific fields | Existing Graph/Reader seam |
| Notification | Source, age, supported actions, private-lock redaction | Sole notification owner |

## Semantics

There are exactly six Article kinds: Knowledge, Agent, Task, Runbook, Skill, Tool. Historical memory and code records are provider views, not additional Article kinds. Tool and Skill pairing is preserved. Agent display names are identity data from the live model: Computer, Alexandria, Darwin and Heimdall in the inspected installation. The illustrative screenshots do not create new agents.

A successful command dispatch is not a verified operation. A completed animation is not a receipt. Missing telemetry is `Unavailable` or a gap, not zero. A disconnected service is not an empty collection. All stale observations display age/source; action confirmations bind to exact current targets and revisions.

## Motion and OLED

Reduced motion is the default design. No autonomous decorative animations. Use 100–120 ms for meaningful hover or navigation feedback only. Keep the existing compositor-owned OLED seam policy; do not add a second timer, random pixel drift, graph reheat or per-pane shader. Theme changes do not alter device refresh, HDR luminance or VRR behavior.

## Accessibility targets

Use at least 4.5:1 for normal reading text, at least 3:1 for meaningful non-text control boundaries and visible state indicators, and a 2-px visible focus outline. Structural separators that are not needed to identify a control may be quieter. These are design targets, not a claim of full WCAG/native accessibility conformance. Native semantic labels, keyboard order, magnification and AT-SPI/screen-reader integration must also be validated.

Sources: [WCAG 2.2](https://www.w3.org/TR/WCAG22/), [Contrast minimum](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html), [Target size minimum](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html). See the generated contrast report for evaluated token pairs.
