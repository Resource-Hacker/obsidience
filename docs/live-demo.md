---
title: Live demo
hide:
  - toc
---

# Live demo

The real Obsidience graph UI, running in your browser: the same React/Three.js
bundle the desktop shell renders, with Obsidience describing itself.

<div class="demo-frame">
<iframe src="../demo/?embed=1" title="Live Obsidience graph demo" loading="lazy" allow="fullscreen"></iframe>
</div>

<p class="demo-links"><a href="../demo/">Open the demo full screen</a></p>

## What you can do

- **Watch the tour.** It loops through three moments. *Thinking*: the Executive
  answers "How does speech turn-taking decide I've finished speaking?"; a pilot
  light runs the route, the main beam follows it to each Article in the Thinking
  Packet, and the Action Trace shows the packet, the Hindsight recall (unfolded
  into memory cards), the Tool call and the outcome. *Recall*: Hindsight lights
  the memories it returned on the memory timeline. *Code*: a coding agent's
  code-graph lookup lights the matching symbols, with a card for each.
- **Orbit, zoom and inspect.** Drag to orbit, scroll to zoom (hold Ctrl while
  the demo is embedded in a page), and click a node to see its label and
  preview, with a link to the Article, source file or commit on GitHub.
- **Switch graphs.** Knowledge, Memory and Code are the three desktop stages.
  Choosing one pauses the tour; the play button resumes it.
- **Change the look.** The sliders button opens the Graph settings the desktop
  pane offers for the Knowledge and Code graphs. They start from the
  maintainer's own tuning and are not saved.

## Where the data comes from

Everything in the demo is public and comes from this repository:

- **Knowledge** is the starter Vault in `obsidience/defaults/vault`, projected
  by the Harness's own Knowledge projection: the Executive with Darwin,
  Alexandria and Heimdall as satellites.
- **Code** is this repository's codebase-memory-mcp index, laid out by the
  provider and projected by the Harness's Code adapter.
- **Memory** is a Hindsight-shaped bank generated from the repository history:
  commit subjects and dates as experiences, sentences from `DESIGN.md` and these
  docs as world facts, and monthly observations counted from those commits,
  linked by time, shared files and topic. It is not anyone's conversation memory.
- **The tour** replays activity and Action Trace frames recorded from the
  Harness's real emitters. Its Thinking Packet was compiled by the Harness from
  the starter Vault (without the embedding service, so retrieval used its
  lexical lane), and its code lookup is a real code-graph search.

No Harness, model or memory provider runs behind the demo, and the page loads
nothing but its own files. It needs WebGL2; without hardware acceleration it
runs slowly.

`obsidience/ui/demo/generate.py` rebuilds the data, `leak_check.py` checks it,
and `pnpm --dir obsidience/ui build:demo` builds the page.
