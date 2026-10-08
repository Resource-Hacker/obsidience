"""Memory plans from the installed llama.cpp estimator and vLLM profiles."""

from __future__ import annotations

import math
import json
import os
from pathlib import Path
import subprocess

from ..host.gpu_memory import MIB
from ..host.inventory import GPU_UUIDS

FIT_ROOT = Path("/var/lib/ai/opt/llama.cpp-b21e4de")


def plan_key(spec, profile: dict, devices: tuple[str, ...], script: Path) -> tuple:
    paths = [spec.model_path, spec.projector_path, spec.mtp_path,
             script]
    if spec.id != "obsidience-flash-next":
        paths.append(FIT_ROOT / "bin/llama-fit-params")
    if spec.id == "obsidience-muse-glimmer-30b" and len(devices) > 1:
        paths.extend(spec.model_path.parent / name for name in (
            "mmproj-Muse-Glimmer-30B-Q4_K_M.gguf", "dflash-Muse-Glimmer-30B-Q4_K_M.gguf"))
    fingerprints = []
    for path in paths:
        if path:
            stat = path.stat()
            fingerprints.append((str(path.resolve()), stat.st_size, stat.st_mtime_ns))
    return (spec.id, devices, spec.context_tokens, profile["max_num_seqs"],
            profile["gpu_memory_utilization"], tuple(fingerprints))


def estimate(spec, profile: dict, devices: tuple[str, ...], totals: dict[str, int]) -> dict[str, int]:
    if spec.id == "obsidience-flash-next":
        manifest = json.loads(spec.model_path.read_text())
        memory = manifest.get("memory_profile", {})
        if not isinstance(memory, dict) or not isinstance(memory.get("memory_mib"), dict):
            raise ValueError("Strata memory profile must provide per-stage MiB ceilings")
        amounts = memory["memory_mib"]
        if (memory.get("context_tokens") != spec.context_tokens
                or memory.get("max_num_seqs") != profile["max_num_seqs"]
                or memory.get("gpu_memory_utilization") != profile["gpu_memory_utilization"]
                or set(amounts) != set(devices)
                or any(type(value) is not int or value <= 0 or value > totals[device]
                       for device, value in amounts.items())):
            raise ValueError("Strata needs a qualified per-stage memory plan for this exact profile")
        return amounts
    if "vLLM" in spec.runtime:
        # vLLM reserves this configured fraction, including its KV working set.
        return {device: math.ceil(totals[device] * profile["gpu_memory_utilization"])
                for device in devices}
    command = [str(FIT_ROOT / "bin/llama-fit-params"), "--fit-print", "on",
               "-m", str(spec.model_path), "-c", str(spec.context_tokens),
               "-ngl", "99", "--parallel", str(profile["max_num_seqs"])]
    if spec.id == "obsidience-gemma":
        # Match llm.sh defaults; Gemma retains F16 KV and its projector.
        command += ["-b", "4096", "-ub", "1024", "-fa", "on"]
    else:
        command += ["-b", "2048", "-ub", "512", "-fa", "on",
                    "--cache-type-k", "q8_0", "--cache-type-v", "q8_0"]
    split = len(devices) > 1 and spec.id != "obsidience-qwen38-9b-distill"
    command += ["--split-mode", "layer" if split else "none"]
    if split:
        # Use a stable layout for estimation; admission redistributes the total
        # against actual free space for the existing automatic layer split.
        command += ["--tensor-split", ",".join(str(totals[d]) for d in devices)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=20,
                            env={**os.environ, "CUDA_VISIBLE_DEVICES": ",".join(GPU_UUIDS[d] for d in devices),
                                 "CUDA_DEVICE_ORDER": "PCI_BUS_ID", "LD_LIBRARY_PATH": str(FIT_ROOT / "lib")})
    if result.returncode:
        raise ValueError("Installed model memory estimator could not read this profile")
    amounts = {device: 0 for device in devices} if not split else {}
    seen = set()
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[0].startswith("CUDA") and all(p.isdigit() for p in parts[1:]):
            index = int(parts[0][4:])
            if index < len(devices):
                # Driver allocations, the native MTP context, and growth during
                # inference sit outside fit-print's base model/context/compute.
                amounts[devices[index]] = sum(map(int, parts[1:])) + 1024
                seen.add(devices[index])
    if (set(amounts) != set(devices) or not seen
            or (not split and devices[0] not in seen)):
        raise ValueError("Installed model memory estimator returned an incomplete GPU layout")
    if spec.projector_path:
        amounts[devices[0]] += math.ceil(spec.projector_path.stat().st_size / MIB)
    if spec.mtp_path:
        amounts[devices[0]] += math.ceil(spec.mtp_path.stat().st_size / MIB)
    if spec.id == "obsidience-muse-glimmer-30b" and len(devices) > 1:
        for name in ("mmproj-Muse-Glimmer-30B-Q4_K_M.gguf", "dflash-Muse-Glimmer-30B-Q4_K_M.gguf"):
            amounts[devices[0]] += math.ceil((spec.model_path.parent / name).stat().st_size / MIB)
    return amounts
