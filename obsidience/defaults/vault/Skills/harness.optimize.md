---
type: skill
title: Using harness.optimize
description: Use AutoSaddler to validate Agent and Runbook instruction improvements
  against independent cases.
obsidience:
  tool: '[[Tools/harness.optimize]]'
---

## Runtime

For Audit with `optimization_case`, call [harness.optimize](/Tools/harness.optimize.md) once with that exact value as `case_id`. Report the real verdict, comparison and Source report. If the result includes `proposal`, finish `review` with its filename. Otherwise finish `completed` for a report or `failed` for an error without a report.

## Reference

AutoSaddler is Heimdall's single instruction-improvement mechanism. The controller captures incidents, supplies independent executable criteria and publishes eligible changes after the Audit receipt. Do not perform a parallel inspection/proposal loop, invent a case, change expectations, repeat the optimizer or claim deployment merely because a candidate was staged. The existing Repair Task separately owns recovery of interrupted work and failed services.
