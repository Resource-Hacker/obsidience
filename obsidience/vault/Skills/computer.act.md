---
type: skill
title: Using computer.act
obsidience:
  tool: '[[Tools/computer.act]]'
  approved_at: '2026-09-06T01:04:58'
  provenance: proposed by Codex (task codex:knowledge-handoff)
---

Use computer.act for one bounded click inside the application bound by the current Task.

- Pass `{"application": str, "action": "click", "target": str, "point": {"x": int, "y": int}, "postcondition": str optional}`. Use the canonical application name or exact app_id from the Shell Scene. Describe the intended control in target.
- Select the center of that control from the immediately attached image. Express its position on a 1000 by 1000 grid covering the whole image: x is left-to-right and y is top-to-bottom. Both are integers 0-999. For example, the image center is {"x": 500, "y": 500}. Read text and icons directly with vision; never invent desktop coordinates, element indices or capture tokens.
- The image must come from the immediately preceding successful computer.observe of this application. Any intervening Tool or invalid response discards the private action lease. Do not act from memory or an older image. If the intended control is unclear, finish with that limitation without clicking.
- The Capability validates the same image/window, handles foreground activation if needed, maps the point, delivers one click and captures the result. Input scope permits one attempt. State scope permits at most three distinct steps only when fresh images establish each preceding result. Every later step requires a separate newer computer.observe immediately before action. Any failed precondition, rejected or uncertain delivery, or unavailable post-image ends the sequence; never retry it.
- A completed result with verified_scope: click establishes delivery at your selected point plus a fresh post-image. Inspect that image before describing the result. A mode-selection screen is not a started match; a target label or requested postcondition is not evidence by itself.
- Stop on missing or ambiguous application, expired image, changed identity or geometry, sleeping Surface, lock, cancellation, rejected or uncertain delivery, or unavailable post-image. Report the specific blocker without changing input paths or repeating the click.
