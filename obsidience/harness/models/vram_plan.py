"""Memory plans from the installed llama.cpp estimator."""

from __future__ import annotations

import math
import os
from pathlib import Path
import subprocess

from ..host.gpu_memory import MIB
from ..host.inventory import GPU_UUIDS

FIT_ROOT = Path("/var/lib/ai/opt/llama.cpp-b21e4de")


def plan_key(spec, profile: dict, devices: tuple[str, ...], script: Path) -> tuple:
    paths = [spec.model_path, spec.projector_path, spec.mtp_path,
             script, FIT_ROOT / "bin/llama-fit-params"]
    fingerprints = []
    for path in paths:
        if path:
            stat = path.stat()
            fingerprints.append((str(path.resolve()), stat.st_size, stat.st_mtime_ns))
    return (spec.id, devices, spec.context_tokens, profile["max_num_seqs"],
            profile["gpu_memory_utilization"], tuple(fingerprints))


def estimate(spec, profile: dict, devices: tuple[str, ...]) -> dict[str, int]:
    command = [str(FIT_ROOT / "bin/llama-fit-params"), "--fit-print", "on",
               "-m", str(spec.model_path), "-c", str(spec.context_tokens),
               "-ngl", "99", "--parallel", str(profile["max_num_seqs"]),
               # Match llm.sh defaults; Gemma retains F16 KV and its projector.
               "-b", "4096", "-ub", "1024", "-fa", "on", "--split-mode", "none"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=20,
                            env={**os.environ, "CUDA_VISIBLE_DEVICES": ",".join(GPU_UUIDS[d] for d in devices),
                                 "CUDA_DEVICE_ORDER": "PCI_BUS_ID", "LD_LIBRARY_PATH": str(FIT_ROOT / "lib")})
    if result.returncode:
        raise ValueError("Installed model memory estimator could not read this profile")
    amounts = {device: 0 for device in devices}
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
    if set(amounts) != set(devices) or devices[0] not in seen:
        raise ValueError("Installed model memory estimator returned an incomplete GPU layout")
    if spec.projector_path:
        amounts[devices[0]] += math.ceil(spec.projector_path.stat().st_size / MIB)
    if spec.mtp_path:
        amounts[devices[0]] += math.ceil(spec.mtp_path.stat().st_size / MIB)
    return amounts
