---
type: tool
title: computer.hardware
description: 'Read this computer''s hardware right now: CPU and memory, and each GPU''s
  load, free VRAM, temperature, power and video encoder/decoder use. Pass {}. You
  are this computer, so call it when asked what you can do or how fast right now,
  such as how fast you can render or encode video or how busy the GPUs are, and answer
  as the computer from these readings and your recorded hardware knowledge.'
obsidience:
  binding: capability:computer.hardware
  source: obsidience/harness/capabilities/computer/hardware.py
---

## Runtime

Read this computer's current hardware with `{}`: CPU load and temperature, memory, and for each GPU its utilization, video encoder and decoder use, free VRAM, temperature, power and performance state. It reads the same bounded measurements as the Hardware panes and changes nothing.

## Reference

Readings are a sample of the last few seconds; the CPU utilization percentage needs a previous sample and is null when none was taken recently, so use `load_1m` then. A GPU entry whose readings are missing reports only what was read; `problems` names components that could not be read. The Tool reports load, not capability: what the hardware can do comes from the installation's recorded hardware Knowledge.
