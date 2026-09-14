"""Local model catalog, hardware defaults, and resource-aware model leases.

Tasks choose a model and reasoning effort. The Hardware pane chooses which
components stay warm on each physical device. A Task may temporarily replace
only the defaults whose devices it needs; unrelated resident models remain
loaded and every displaced default is restored after the Task.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import itertools
import json
import os
import statistics
import struct
import subprocess
import tempfile
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, replace
from pathlib import Path

import httpx

from .benchmark import (
    MODEL_COMPARISON_CONTRACT,
    MODEL_COMPARISON_MAX_TOKENS,
    MODEL_COMPARISON_PROMPT,
    MODEL_COMPARISON_SAMPLES,
    MODEL_COMPARISON_TEMPERATURE,
    MODEL_COMPARISON_WARMUPS,
    comparison_result,
)
from ..host.inventory import (
    CPU_DEVICE,
    DEVICE_LABELS,
    GPU_DEVICES,
    GPU_UUIDS,
    IGPU_DEVICE,
    RTX_4000_DEVICE,
    RTX_4080_DEVICE,
    gpu_snapshot,
    hardware_sensor_snapshot,
    storage_snapshot,
)


EXECUTIVE_MODEL = "obsidience-gemma"
SPECIALIST_MODEL = "obsidience-qwen38-9b-distill"
QWEN_W4_MODEL = "obsidience-qwen38-27b-w4a16"
QWEN_Q8_MODEL = "obsidience-qwen38-27b-q8"
HOMEUSER_MODEL = "obsidience-qwen38-27b-homeuser"
MUSE_MODEL = "obsidience-muse-glimmer-30b"
QWEN_MODELS = frozenset({SPECIALIST_MODEL, QWEN_W4_MODEL, QWEN_Q8_MODEL, HOMEUSER_MODEL})
AUTO_MODEL = "auto"
NONE_COMPONENT = "none"
PERCEPTION_COMPONENT = "omniparser"
DISPLAY_COMPONENT = "display-media"

GEMMA_SERVICE = "obsidience-gemma.service"
QWEN_DISTILL_SERVICE = "obsidience-qwen38-9b-distill.service"
QWEN_FAST_SERVICE = "obsidience-qwen38.service"
QWEN_Q8_SERVICE = "obsidience-qwen38-q8.service"
HOMEUSER_SERVICE = "obsidience-qwen38-homeuser.service"
MUSE_SERVICE = "obsidience-muse-glimmer.service"
PERCEPTION_UNITS = ("jarvis-perception.socket", "jarvis-perception.service")
PERCEPTION_RESIDENCY_MARKER = Path(
    os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
) / "obsidience-perception-enabled"

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PRODUCT_ROOT = PROJECT_ROOT / "obsidience"
MODEL_SETTINGS_PATH = PRODUCT_ROOT / "state" / "model-settings.json"
MODEL_LAUNCH_DIR = PRODUCT_ROOT / "state" / "model-launch"
MODEL_CATALOG_STATE_PATH = PRODUCT_ROOT / "state" / "model-catalog.json"
MODEL_SOURCE_ROOT = PRODUCT_ROOT / "evidence" / "models"
GEMMA_MODEL = PRODUCT_ROOT / "state" / "models" / "executive.gguf"
GEMMA_PROJECTOR = Path(
    "/var/lib/ai/models/jarvis-fixed/gemma-4-26b-a4b-it-qat-7b92b5b2/"
    "mmproj-F16.gguf"
)
GEMMA_PROJECTOR_SHA256 = "d00f211a7d4f7fb19bd9b75d8e9342eccffb5920b08fd9562167560fdfcc5dd1"
QWEN_DISTILL_MODEL = Path(
    "/var/lib/ai/models/obsidience-qwen38-9b-distill/"
    "Qwen3.8-9B-Distill-Heretic-Uncensored-Q8_0.gguf"
)
QWEN_DISTILL_VERIFIED = QWEN_DISTILL_MODEL.with_suffix(
    QWEN_DISTILL_MODEL.suffix + ".verified"
)
QWEN_DISTILL_EXPECTED_SIZE = 9_786_060_160
QWEN_FAST_MODEL = Path(
    "/var/lib/ai/models/obsidience-qwen38-vllm/"
    "Qwen3.8-27B-Uncensored-W4A16/model.safetensors.index.json"
)
QWEN_FAST_VERIFIED = QWEN_FAST_MODEL.parent / ".verified"
QWEN_FAST_EXPECTED_SIZE = 163_317
QWEN_Q8_MODEL_PATH = Path(
    "/var/lib/ai/models/obsidience-qwen38-27b-q8/"
    "Qwen3.8-27B-Uncensored-Q8_0.gguf"
)
QWEN_Q8_VERIFIED = QWEN_Q8_MODEL_PATH.with_suffix(QWEN_Q8_MODEL_PATH.suffix + ".verified")
QWEN_Q8_EXPECTED_SIZE = 29_047_084_416
HOMEUSER_MODEL_PATH = Path(
    "/var/lib/ai/models/obsidience-qwen38-homeuser/model.safetensors.index.json"
)
HOMEUSER_VERIFIED = HOMEUSER_MODEL_PATH.parent / ".verified"
HOMEUSER_EXPECTED_SIZE = 224_298
MUSE_MODEL_PATH = Path(
    "/var/lib/ai/models/obsidience-muse-glimmer-30b/"
    "Muse-Glimmer-30B-KQuant-17GB-Q4_K_M.gguf"
)
MUSE_VERIFIED = MUSE_MODEL_PATH.parent / ".verified"
MUSE_EXPECTED_SIZE = 16_756_683_904
@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    base_url: str
    purpose: str
    context_tokens: int
    max_output_tokens: int
    max_context_tokens: int
    quantization: str
    hardware: str
    runtime: str
    capabilities: tuple[str, ...]
    reasoning_budgets: dict[str, int]
    supported_devices: tuple[str, ...]
    default_allowed_devices: tuple[str, ...]
    min_gpu_count: int
    default_gpu_memory_utilization: float
    default_max_num_seqs: int
    device_sets: tuple[tuple[str, ...], ...] = ()
    task_capable: bool = True
    benchmark_kind: str = "tokens"
    hardware_assignable: bool = True
    service: str | None = None
    model_path: Path | None = None
    verified_path: Path | None = None
    expected_size: int | None = None
    runtime_path: Path | None = None
    projector_path: Path | None = None
    projector_sha256: str | None = None
    family: str = ""
    supports_json_schema: bool = False


class ModelResourceUnavailable(RuntimeError):
    """A valid model layout conflicts with a current component reservation."""

    def __init__(
        self, spec: ModelSpec, layouts: list[tuple[str, ...]],
        reservations: dict[str, tuple[str, ...]],
    ) -> None:
        self.model_id = spec.id
        self.candidate_layouts = tuple(layouts)
        needed = {device for layout in layouts for device in layout}
        self.reservations = {
            owner: tuple(device for device in devices if device in needed)
            for owner, devices in reservations.items() if needed.intersection(devices)
        }
        blockers = "; ".join(
            f"{owner}: {' + '.join(DEVICE_LABELS[device] for device in devices)}"
            for owner, devices in self.reservations.items()
        )
        super().__init__(f"{spec.label} needs reserved hardware ({blockers})")

    def as_dict(self) -> dict:
        return {
            "code": "model_resources_reserved",
            "model_id": self.model_id,
            "candidate_layouts": [list(layout) for layout in self.candidate_layouts],
            "reservations": {owner: list(devices) for owner, devices in self.reservations.items()},
        }


MODELS = {
    EXECUTIVE_MODEL: ModelSpec(
        id=EXECUTIVE_MODEL,
        label="Gemma 4 26B-A4B",
        family="gemma4",
        base_url="http://127.0.0.1:8089/v1",
        purpose="Responsive Executive conversation and Task dispatch",
        context_tokens=16_384,
        max_output_tokens=3_584,
        max_context_tokens=98_304,
        quantization="Q4_K_XL",
        hardware="One Ada GPU",
        runtime="llama.cpp b10078",
        capabilities=("text", "vision", "reasoning", "tools"),
        reasoning_budgets={"none": 0, "low": 256, "medium": 768, "high": 1_536, "xhigh": 2_560},
        supported_devices=(RTX_4000_DEVICE,),
        default_allowed_devices=(RTX_4000_DEVICE,),
        min_gpu_count=1,
        default_gpu_memory_utilization=0.90,
        default_max_num_seqs=1,
        service=GEMMA_SERVICE,
        model_path=GEMMA_MODEL,
        projector_path=GEMMA_PROJECTOR,
        projector_sha256=GEMMA_PROJECTOR_SHA256,
        supports_json_schema=True,
    ),
    SPECIALIST_MODEL: ModelSpec(
        id=SPECIALIST_MODEL,
        label="Qwen3.8 9B Distill Heretic Q8",
        base_url="http://127.0.0.1:8092/v1",
        purpose="Fully GPU-resident specialist reasoning, tools, and knowledge work",
        context_tokens=32_768,
        max_output_tokens=8_192,
        max_context_tokens=262_144,
        quantization="Q8_0 weights · Q8_0 KV",
        hardware="One Ada GPU with 12 GB+ free VRAM",
        runtime="llama.cpp b21e4de · MTP3",
        capabilities=("text", "reasoning", "tools", "knowledge"),
        reasoning_budgets={"none": 0, "low": 1_536, "medium": 3_072, "high": 4_608, "xhigh": 6_144},
        supported_devices=GPU_DEVICES,
        default_allowed_devices=(RTX_4080_DEVICE,),
        min_gpu_count=1,
        default_gpu_memory_utilization=0.95,
        default_max_num_seqs=1,
        service=QWEN_DISTILL_SERVICE,
        model_path=QWEN_DISTILL_MODEL,
        verified_path=QWEN_DISTILL_VERIFIED,
        expected_size=QWEN_DISTILL_EXPECTED_SIZE,
        supports_json_schema=True,
    ),
    QWEN_W4_MODEL: ModelSpec(
        id=QWEN_W4_MODEL,
        label="Qwen3.8 27B Uncensored Fast",
        base_url="http://127.0.0.1:8082/v1",
        purpose="Fast long-context specialist reasoning and knowledge work",
        context_tokens=65_536,
        max_output_tokens=10_240,
        max_context_tokens=262_144,
        quantization="W4A16 AutoRound",
        hardware="Both Ada GPUs",
        runtime="vLLM 0.27.1 · TP2 · MTP2 · FP8 KV",
        capabilities=("text", "reasoning", "tools", "knowledge"),
        reasoning_budgets={"none": 0, "low": 2_048, "medium": 4_096, "high": 6_144, "xhigh": 8_192},
        supported_devices=GPU_DEVICES,
        default_allowed_devices=GPU_DEVICES,
        min_gpu_count=2,
        default_gpu_memory_utilization=0.82,
        default_max_num_seqs=2,
        service=QWEN_FAST_SERVICE,
        model_path=QWEN_FAST_MODEL,
        verified_path=QWEN_FAST_VERIFIED,
        expected_size=QWEN_FAST_EXPECTED_SIZE,
        supports_json_schema=True,
    ),
    QWEN_Q8_MODEL: ModelSpec(
        id=QWEN_Q8_MODEL,
        label="Qwen3.8 27B OrcaRouter Q8",
        base_url="http://127.0.0.1:8090/v1",
        purpose="Highest-precision local Qwen option",
        context_tokens=65_536,
        max_output_tokens=10_240,
        max_context_tokens=262_144,
        quantization="Q8_0",
        hardware="Both Ada GPUs",
        runtime="llama.cpp b21e4de · MTP2",
        capabilities=("text", "reasoning", "tools", "knowledge"),
        reasoning_budgets={"none": 0, "low": 2_048, "medium": 4_096, "high": 6_144, "xhigh": 8_192},
        supported_devices=GPU_DEVICES,
        default_allowed_devices=GPU_DEVICES,
        min_gpu_count=2,
        default_gpu_memory_utilization=0.90,
        default_max_num_seqs=1,
        service=QWEN_Q8_SERVICE,
        model_path=QWEN_Q8_MODEL_PATH,
        verified_path=QWEN_Q8_VERIFIED,
        expected_size=QWEN_Q8_EXPECTED_SIZE,
        supports_json_schema=True,
    ),
    HOMEUSER_MODEL: ModelSpec(
        id=HOMEUSER_MODEL,
        label="Qwen3.8 27B Pristinely Uncensored",
        base_url="http://127.0.0.1:8091/v1",
        purpose="Single-GPU specialist reasoning while Gemma remains responsive",
        context_tokens=10_240,
        max_output_tokens=6_144,
        max_context_tokens=262_144,
        quantization="HOMEUSER mixed INT4",
        hardware="RTX 4000 Ada · fully GPU resident",
        runtime="vLLM 0.27.1 · Zynerji loader-compatible · FP8 KV",
        capabilities=("text", "reasoning", "tools", "knowledge"),
        reasoning_budgets={"none": 0, "low": 1_536, "medium": 3_072, "high": 4_608, "xhigh": 6_144},
        supported_devices=(RTX_4000_DEVICE,),
        default_allowed_devices=(RTX_4000_DEVICE,),
        min_gpu_count=1,
        default_gpu_memory_utilization=0.97,
        default_max_num_seqs=1,
        service=HOMEUSER_SERVICE,
        model_path=HOMEUSER_MODEL_PATH,
        verified_path=HOMEUSER_VERIFIED,
        expected_size=HOMEUSER_EXPECTED_SIZE,
        runtime_path=Path(
            "/var/lib/ai/src/obsidience-qwen38-vllm/venv/bin/vllm"
        ),
        supports_json_schema=True,
    ),
    MUSE_MODEL: ModelSpec(
        id=MUSE_MODEL,
        label="Muse Glimmer 30B",
        base_url="http://127.0.0.1:8095/v1",
        purpose="High-capability agentic reasoning, tools, coding, and graph curation",
        context_tokens=32_768,
        max_output_tokens=8_192,
        max_context_tokens=131_072,
        quantization="Official KQuant 17GB Q4_K_M",
        hardware="RTX 4000 text-only; both GPUs for vision + DFlash",
        runtime="llama.cpp b21e4de · optional DFlash + vision",
        capabilities=("text", "reasoning", "tools", "code", "vision"),
        reasoning_budgets={"none": 512, "low": 2_048, "medium": 4_096, "high": 6_144, "xhigh": 8_192},
        supported_devices=GPU_DEVICES,
        default_allowed_devices=GPU_DEVICES,
        min_gpu_count=1,
        default_gpu_memory_utilization=0.94,
        default_max_num_seqs=1,
        device_sets=(GPU_DEVICES, (RTX_4000_DEVICE,)),
        service=MUSE_SERVICE,
        model_path=MUSE_MODEL_PATH,
        verified_path=MUSE_VERIFIED,
        expected_size=MUSE_EXPECTED_SIZE,
        runtime_path=Path("/var/lib/ai/opt/llama.cpp-b21e4de/bin/llama-server"),
        supports_json_schema=True,
    ),
}


def _default_profile(spec: ModelSpec) -> dict:
    return {
        "allowed_devices": list(spec.default_allowed_devices),
        "context_tokens": spec.context_tokens,
        "max_output_tokens": spec.max_output_tokens,
        "gpu_memory_utilization": spec.default_gpu_memory_utilization,
        "max_num_seqs": spec.default_max_num_seqs,
    }


def _default_settings() -> dict:
    return {
        "schema_version": 2,
        "hardware": {
            CPU_DEVICE: NONE_COMPONENT,
            IGPU_DEVICE: DISPLAY_COMPONENT,
            RTX_4080_DEVICE: PERCEPTION_COMPONENT,
            RTX_4000_DEVICE: EXECUTIVE_MODEL,
        },
        "models": {model_id: _default_profile(spec) for model_id, spec in MODELS.items()},
        "benchmarks": {},
    }


def _normalize_devices(value: object, spec: ModelSpec) -> list[str]:
    raw = value if isinstance(value, list) else list(spec.default_allowed_devices)
    devices = [str(item) for item in raw if str(item) in spec.supported_devices]
    devices = list(dict.fromkeys(devices))
    if len(devices) < spec.min_gpu_count:
        return list(spec.default_allowed_devices)
    return devices


def _device_sets(spec: ModelSpec, allowed_devices: object) -> list[tuple[str, ...]]:
    allowed = tuple(
        device for device in GPU_DEVICES
        if device in allowed_devices and device in spec.supported_devices
    )
    if spec.device_sets:
        return [
            devices for devices in spec.device_sets
            if all(device in allowed for device in devices)
        ]
    return [
        devices
        for count in range(spec.min_gpu_count, len(allowed) + 1)
        for devices in itertools.combinations(allowed, count)
    ]


def _normalize_settings(raw: object) -> dict:
    defaults = _default_settings()
    if not isinstance(raw, dict):
        return defaults
    # One-time compatibility with the former global standby selector.
    if "hardware" not in raw and "standby_model" in raw:
        standby = str(raw.get("standby_model", EXECUTIVE_MODEL))
        if standby in MODELS and MODELS[standby].min_gpu_count == 2:
            defaults["hardware"][RTX_4080_DEVICE] = standby
            defaults["hardware"][RTX_4000_DEVICE] = standby
        elif standby == NONE_COMPONENT:
            defaults["hardware"][RTX_4000_DEVICE] = NONE_COMPONENT
    hardware = raw.get("hardware")
    if isinstance(hardware, dict):
        for device in (CPU_DEVICE, IGPU_DEVICE, *GPU_DEVICES):
            value = str(hardware.get(device, defaults["hardware"][device]))
            if value in {NONE_COMPONENT, PERCEPTION_COMPONENT, DISPLAY_COMPONENT, *MODELS}:
                defaults["hardware"][device] = value
    defaults["hardware"][CPU_DEVICE] = NONE_COMPONENT
    defaults["hardware"][IGPU_DEVICE] = DISPLAY_COMPONENT
    model_rows = raw.get("models")
    if isinstance(model_rows, dict):
        for model_id, spec in MODELS.items():
            row = model_rows.get(model_id)
            if not isinstance(row, dict):
                continue
            profile = defaults["models"][model_id]
            devices = _normalize_devices(row.get("allowed_devices"), spec)
            profile["allowed_devices"] = (
                devices if _device_sets(spec, devices) else list(spec.default_allowed_devices)
            )
            for field, low, high in (
                ("context_tokens", 2_048, spec.max_context_tokens),
                ("max_output_tokens", 256, 32_768),
                ("max_num_seqs", 1, 32),
            ):
                try:
                    profile[field] = max(low, min(high, int(row.get(field, profile[field]))))
                except (TypeError, ValueError):
                    pass
            try:
                profile["gpu_memory_utilization"] = max(
                    0.50, min(0.99, float(row.get("gpu_memory_utilization", profile["gpu_memory_utilization"])))
                )
            except (TypeError, ValueError):
                pass
    benchmarks = raw.get("benchmarks")
    if isinstance(benchmarks, dict):
        defaults["benchmarks"] = {
            model_id: row
            for model_id, row in benchmarks.items()
            if model_id in MODELS and isinstance(row, dict)
        }
    return defaults


def _read_settings() -> dict:
    try:
        raw = json.loads(MODEL_SETTINGS_PATH.read_text())
    except (OSError, ValueError, TypeError):
        raw = {}
    return _normalize_settings(raw)


def _write_settings(settings: dict) -> None:
    MODEL_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = MODEL_SETTINGS_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(settings, indent=2, sort_keys=True) + "\n")
    temporary.replace(MODEL_SETTINGS_PATH)


def _launch_path(model_id: str) -> Path:
    return MODEL_LAUNCH_DIR / f"{model_id}.json"


def _write_launch(spec: ModelSpec, devices: tuple[str, ...], profile: dict) -> None:
    MODEL_LAUNCH_DIR.mkdir(parents=True, exist_ok=True)
    path = _launch_path(spec.id)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({
        "model_id": spec.id,
        "devices": list(devices),
        "gpu_uuids": [GPU_UUIDS[device] for device in devices],
        "context_tokens": profile["context_tokens"],
        "max_output_tokens": profile["max_output_tokens"],
        "gpu_memory_utilization": profile["gpu_memory_utilization"],
        "max_num_seqs": profile["max_num_seqs"],
        "projector_path": str(spec.projector_path) if spec.projector_path else None,
    }, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def _read_launch(model_id: str) -> tuple[str, ...]:
    try:
        raw = json.loads(_launch_path(model_id).read_text())
        devices = tuple(str(item) for item in raw.get("devices", []))
    except (OSError, ValueError, TypeError, AttributeError):
        return ()
    return tuple(device for device in devices if device in GPU_DEVICES)


def configured_spec(model_id: str) -> ModelSpec:
    spec = MODELS[model_id]
    profile = _read_settings()["models"][model_id]
    return replace(
        spec,
        context_tokens=int(profile["context_tokens"]),
        max_output_tokens=int(profile["max_output_tokens"]),
    )


def normalize_model(value: object, *, allow_auto: bool = True) -> str:
    model = str(value or AUTO_MODEL).strip().lower()
    allowed = {model_id for model_id, spec in MODELS.items() if spec.task_capable}
    if allow_auto:
        allowed.add(AUTO_MODEL)
    if model not in allowed:
        raise ValueError(f"model must be one of: {', '.join(sorted(allowed))}")
    return model


def resolve_model(preference: object, agent_ref: str) -> ModelSpec:
    selected = normalize_model(preference)
    if selected == AUTO_MODEL:
        selected = EXECUTIVE_MODEL if agent_ref == "Agents/Executive/Executive" else SPECIALIST_MODEL
    return configured_spec(selected)


def _healthy(spec: ModelSpec, timeout: float = 0.35) -> bool:
    try:
        # The model owner retains transport connections, never health results.
        # Standalone inspection still owns and closes its temporary client.
        if RUNTIME.health_client is not None:
            response = RUNTIME.health_client.get(
                spec.base_url.removesuffix("/v1") + "/health", timeout=timeout,
            )
            return response.status_code == 200
        with httpx.Client(timeout=timeout) as client:
            response = client.get(spec.base_url.removesuffix("/v1") + "/health")
        return response.status_code == 200
    except (httpx.HTTPError, OSError):
        return False


def _service_state(service: str | None) -> str:
    if not service:
        return "external"
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", service],
            check=False,
            capture_output=True,
            text=True,
            timeout=1,
        )
        return result.stdout.strip() or "inactive"
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"


def _installed(spec: ModelSpec) -> tuple[bool, int | None]:
    size = None
    if spec.model_path:
        try:
            size = spec.model_path.stat().st_size
        except OSError:
            size = None
    installed = bool(
        size is not None
        and (spec.expected_size is None or size == spec.expected_size)
        and (spec.verified_path is None or spec.verified_path.exists())
        and (spec.runtime_path is None or spec.runtime_path.exists())
        and (spec.projector_path is None or spec.projector_path.is_file())
    )
    return installed, size


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    material = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    if path.exists() and path.read_bytes() == material:
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".model-source-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(material)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.close(descriptor)
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


def _verification_lines(spec: ModelSpec) -> list[str]:
    path = spec.verified_path
    if not path or not path.is_file():
        return []
    return [
        line.strip() for line in path.read_text(errors="replace").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _model_source_identity(spec: ModelSpec) -> dict:
    installed, size = _installed(spec)
    model_path = spec.model_path
    resolved_path = None
    if model_path and model_path.exists():
        with contextlib.suppress(OSError):
            resolved_path = str(model_path.resolve())
    verification = _verification_lines(spec)
    identity = {
        "schema": "obsidience.model-source.v1",
        "model_id": spec.id,
        "label": spec.label,
        "artifact": {
            "path": str(model_path) if model_path else None,
            "resolved_path": resolved_path,
            "size_bytes": size,
            "expected_size_bytes": spec.expected_size,
            "installed": installed,
        },
        "verification_path": str(spec.verified_path) if spec.verified_path else None,
        "verification": verification,
        "runtime_path": str(spec.runtime_path) if spec.runtime_path else None,
        "runtime": spec.runtime,
        "service": spec.service,
        "quantization": spec.quantization,
        "capabilities": list(spec.capabilities),
        "task_capable": spec.task_capable,
        "benchmark_kind": spec.benchmark_kind,
        "hardware_assignable": spec.hardware_assignable,
        "supported_device_sets": [
            list(devices) for devices in _device_sets(spec, spec.supported_devices)
        ],
    }
    if spec.projector_path:
        identity["projector"] = {
            "path": str(spec.projector_path),
            "size_bytes": (
                spec.projector_path.stat().st_size
                if spec.projector_path.is_file()
                else None
            ),
            "sha256": spec.projector_sha256,
            "installed": spec.projector_path.is_file(),
        }
    fingerprint_material = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return {
        **identity,
        "fingerprint": "sha256:" + hashlib.sha256(fingerprint_material).hexdigest(),
    }


def sync_model_source(model_id: str) -> dict:
    """Materialize one immutable model artifact manifest in Source."""
    if model_id not in MODELS:
        raise ValueError("unknown model")
    identity = _model_source_identity(configured_spec(model_id))
    fingerprint = str(identity["fingerprint"]).removeprefix("sha256:")
    relative = Path("models") / model_id / f"artifact--{fingerprint[:16]}.json"
    _atomic_json(PRODUCT_ROOT / "evidence" / relative, identity)
    return {
        "model_id": model_id,
        "fingerprint": identity["fingerprint"],
        "source_path": f"obsidience/evidence/{relative.as_posix()}",
        "manifest": identity,
    }


def record_model_source(model_id: str, record_kind: str, payload: dict) -> str:
    """Append one immutable local benchmark or configuration record to Source."""
    if model_id not in MODELS:
        raise ValueError("unknown model")
    if record_kind not in {"benchmark", "configuration"}:
        raise ValueError("unsupported model source record")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    nonce = f"{time.time_ns():x}"
    relative = (
        Path("models") / model_id / f"{record_kind}s"
        / f"{record_kind}--{stamp}-{nonce}.json"
    )
    record = {
        "schema": f"obsidience.model-{record_kind}.v1",
        "model_id": model_id,
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        **payload,
    }
    _atomic_json(PRODUCT_ROOT / "evidence" / relative, record)
    return f"obsidience/evidence/{relative.as_posix()}"


def sync_model_sources() -> list[dict]:
    """Refresh Source manifests and return only newly seen model revisions."""
    current = {model_id: sync_model_source(model_id) for model_id in sorted(MODELS)}
    previous: dict[str, str] = {}
    first_registration = not MODEL_CATALOG_STATE_PATH.exists()
    if not first_registration:
        with contextlib.suppress(OSError, ValueError, TypeError):
            raw = json.loads(MODEL_CATALOG_STATE_PATH.read_text())
            if isinstance(raw.get("fingerprints"), dict):
                previous = {
                    str(key): str(value) for key, value in raw["fingerprints"].items()
                }
    events = []
    if not first_registration:
        for model_id, row in current.items():
            if previous.get(model_id) == row["fingerprint"]:
                continue
            spec = configured_spec(model_id)
            events.append({
                "model_event_id": f"model-{time.time_ns():x}",
                "model_id": model_id,
                "model_label": spec.label,
                "model_fingerprint": row["fingerprint"],
                "source_path": row["source_path"],
                "benchmark_kind": spec.benchmark_kind,
                "hardware_assignable": spec.hardware_assignable,
                "task_capable": spec.task_capable,
                "valid_device_sets": [
                    list(devices) for devices in _device_sets(spec, spec.supported_devices)
                ],
                "change": "added" if model_id not in previous else "revision",
            })
    _atomic_json(MODEL_CATALOG_STATE_PATH, {
        "schema": "obsidience.model-catalog.v1",
        "fingerprints": {
            model_id: row["fingerprint"] for model_id, row in current.items()
        },
    })
    return events


def inspect_model(model_id: str) -> dict:
    if model_id not in MODELS:
        raise ValueError("unknown model")
    source_row = sync_model_source(model_id)
    return {
        "model": model_document(model_id),
        "source": {
            "path": source_row["source_path"],
            "fingerprint": source_row["fingerprint"],
        },
        "gpus": gpu_snapshot(),
    }


def _benchmark_doc(value: object) -> dict | None:
    if not isinstance(value, dict):
        return None
    result = json.loads(json.dumps(value))
    result.setdefault(
        "kind",
        "tokens" if result.get("tokens_per_second") is not None else "realtime_audio",
    )
    metrics = result.get("metrics")
    if (
        result.get("ttft_ms") is None
        and isinstance(metrics, dict)
        and metrics.get("first_text_ms") is not None
    ):
        result["ttft_ms"] = float(metrics["first_text_ms"])
    if not result.get("summary"):
        if result.get("tokens_per_second") is not None:
            result["summary"] = f"{float(result['tokens_per_second']):.2f} tok/s"
        else:
            result["summary"] = "benchmark recorded"
    return result


def catalog() -> list[dict]:
    settings = _read_settings()
    hardware = settings["hardware"]
    rows = []
    for base_spec in MODELS.values():
        spec = configured_spec(base_spec.id)
        installed, size = _installed(spec)
        external_devices = RUNTIME.external_models.get(spec.id, ())
        loaded = _healthy(spec) or bool(external_devices)
        profile = settings["models"][spec.id]
        assigned = [device for device in GPU_DEVICES if hardware.get(device) == spec.id]
        active_devices = (
            list(external_devices)
            if external_devices
            else list(_read_launch(spec.id)) if loaded else []
        )
        rows.append({
            "id": spec.id,
            "label": spec.label,
            "purpose": spec.purpose,
            "base_url": spec.base_url,
            "context_tokens": spec.context_tokens,
            "max_output_tokens": spec.max_output_tokens,
            "max_context_tokens": spec.max_context_tokens,
            "quantization": spec.quantization,
            "hardware": spec.hardware,
            "runtime": spec.runtime,
            "capabilities": list(spec.capabilities),
            "installed": installed,
            "loaded": loaded,
            "available": loaded or installed,
            "state": "loaded" if loaded else _service_state(spec.service),
            "size_bytes": size,
            "default_for": (
                "Executive Tasks" if spec.id == EXECUTIVE_MODEL
                else "Automatic specialist Tasks" if spec.id == SPECIALIST_MODEL
                else "Selectable specialist Tasks" if spec.task_capable
                else "Hardware interface component"
            ),
            "supported_devices": list(spec.supported_devices),
            "allowed_devices": profile["allowed_devices"],
            "min_gpu_count": spec.min_gpu_count,
            "device_sets": [list(devices) for devices in _device_sets(spec, spec.supported_devices)],
            "assigned_devices": assigned,
            "active_devices": active_devices,
            "gpu_memory_utilization": profile["gpu_memory_utilization"],
            "max_num_seqs": profile["max_num_seqs"],
            "last_benchmark": _benchmark_doc(settings["benchmarks"].get(spec.id)),
            "task_capable": spec.task_capable,
            "category": "task_reasoning" if spec.task_capable else "realtime_interface",
            "benchmark_kind": spec.benchmark_kind,
            "hardware_assignable": spec.hardware_assignable,
            "source_manifest": sync_model_source(spec.id)["source_path"],
        })
    return rows


def hardware_catalog() -> dict:
    settings = _read_settings()
    model_rows = {row["id"]: row for row in catalog()}
    sensors = hardware_sensor_snapshot()
    slots = []
    for device in (CPU_DEVICE, IGPU_DEVICE, *GPU_DEVICES):
        options = [{"id": NONE_COMPONENT, "label": "None", "available": True}]
        if device == IGPU_DEVICE:
            options = [{
                "id": DISPLAY_COMPONENT,
                "label": "USB-C display + VAAPI media",
                "available": True,
            }]
        if device == RTX_4080_DEVICE:
            options.append({
                "id": PERCEPTION_COMPONENT,
                "label": "OmniParser perception",
                "available": True,
            })
        for model_id, spec in MODELS.items():
            if not spec.hardware_assignable:
                continue
            if device not in spec.supported_devices:
                continue
            row = model_rows[model_id]
            options.append({
                "id": model_id,
                "label": row["label"],
                "available": bool(row["available"] and device in row["allowed_devices"]),
                "linked": spec.min_gpu_count > 1 or any(
                    len(devices) > 1 for devices in spec.device_sets
                ),
            })
        slots.append({
            "id": device,
            "label": DEVICE_LABELS[device],
            "kind": "cpu" if device == CPU_DEVICE else "igpu" if device == IGPU_DEVICE else "gpu",
            "selected": settings["hardware"][device],
            "sensors": sensors.get(device),
            "options": options,
            "note": (
                "No managed CPU inference component is installed. OmniParser uses 4080-specific TensorRT engines."
                if device == CPU_DEVICE else
                "Drives the isolated USB-C interface and accelerates media. No validated ROCm model backend is installed."
                if device == IGPU_DEVICE else
                "Display GPU; free VRAM determines the practical context ceiling."
                if device == RTX_4080_DEVICE else
                "Isolated-display GPU; Gemma is the responsive default."
            ),
        })
    return {
        "policy": "hardware_slots",
        "slots": slots,
        "storage": storage_snapshot(),
    }


async def _systemctl(action: str, *units: str, timeout: float = 45) -> None:
    process = await asyncio.create_subprocess_exec(
        "systemctl", "--user", action, *units,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except (TimeoutError, asyncio.CancelledError) as exc:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
        await process.communicate()
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise RuntimeError(f"systemctl {action} timed out for {', '.join(units)}") from None
    if process.returncode:
        detail = (stderr or stdout).decode(errors="replace").strip()
        raise RuntimeError(f"systemctl {action} failed for {', '.join(units)}: {detail}")


async def _active(unit: str) -> bool:
    process = await asyncio.create_subprocess_exec(
        "systemctl", "--user", "is-active", "--quiet", unit,
    )
    return await process.wait() == 0


async def _benchmark_text_sample(
    client: httpx.AsyncClient,
    active: ModelSpec,
) -> dict:
    payload = {
        "model": active.id,
        "messages": [{"role": "user", "content": MODEL_COMPARISON_PROMPT}],
        "max_tokens": min(MODEL_COMPARISON_MAX_TOKENS, active.max_output_tokens),
        "temperature": MODEL_COMPARISON_TEMPERATURE,
        "stream": True,
        "stream_options": {"include_usage": True},
        "chat_template_kwargs": {"enable_thinking": False},
    }
    started = time.perf_counter()
    first_text_at: float | None = None
    completion_tokens = 0
    output_parts: list[str] = []
    async with client.stream(
        "POST", f"{active.base_url}/chat/completions", json=payload
    ) as response:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if not line.startswith("data:"):
                continue
            material = line[5:].strip()
            if not material or material == "[DONE]":
                continue
            try:
                event = json.loads(material)
            except json.JSONDecodeError:
                continue
            usage = event.get("usage")
            if isinstance(usage, dict) and usage.get("completion_tokens") is not None:
                completion_tokens = int(usage["completion_tokens"])
            choices = event.get("choices")
            if not isinstance(choices, list) or not choices:
                continue
            delta = choices[0].get("delta")
            content = delta.get("content") if isinstance(delta, dict) else None
            if isinstance(content, str) and content:
                first_text_at = first_text_at or time.perf_counter()
                output_parts.append(content)
    finished = time.perf_counter()
    if first_text_at is None or not output_parts:
        raise RuntimeError(f"{active.label} benchmark returned no streamed public text")
    if completion_tokens <= 0:
        completion_tokens = max(1, len("".join(output_parts).split()))
    return {
        "ttft_ms": (first_text_at - started) * 1_000,
        "total_seconds": finished - started,
        "completion_tokens": completion_tokens,
    }


async def _benchmark_text_model(active: ModelSpec) -> dict:
    """Measure one OpenAI-compatible model under the common comparison contract."""

    rows: list[dict] = []
    async with httpx.AsyncClient(timeout=900) as client:
        for _ in range(MODEL_COMPARISON_WARMUPS + MODEL_COMPARISON_SAMPLES):
            rows.append(await _benchmark_text_sample(client, active))
    return comparison_result(
        model_id=active.id,
        devices=list(_read_launch(active.id)),
        samples=rows[MODEL_COMPARISON_WARMUPS:],
        tested_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        metrics={"temperature_zero_supported": True},
    )


class _HardwareModelRuntime:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.health_client: httpx.Client | None = None
        self.running_model: str | None = None
        self.prefill_task: asyncio.Task | None = None
        self.switching = False
        self.reconciliation_pending = False
        self.external_models: dict[str, tuple[str, ...]] = {}
        self.device_reservations: dict[str, tuple[str, ...]] = {}

    def _reserved_devices(self, *, excluding: str | None = None) -> set[str]:
        return {
            device
            for owner, devices in self.device_reservations.copy().items()
            if owner != excluding
            for device in devices
        }

    async def _wait_ready(self, spec: ModelSpec, devices: tuple[str, ...]) -> None:
        deadline = asyncio.get_running_loop().time() + 900
        async with httpx.AsyncClient(timeout=2) as client:
            while asyncio.get_running_loop().time() < deadline:
                # The legacy perception socket may be reactivated by an
                # external display/session edge while a 4080 Task model is
                # still loading. Reassert this lease before its CUDA context
                # can consume the Task model's remaining VRAM.
                if (
                    RTX_4080_DEVICE in devices
                    and (
                        await _active(PERCEPTION_UNITS[0])
                        or await _active(PERCEPTION_UNITS[1])
                    )
                ):
                    await self._perception(False)
                try:
                    response = await client.get(spec.base_url.removesuffix("/v1") + "/health")
                    if response.status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                if spec.service and not await _active(spec.service):
                    raise RuntimeError(f"{spec.service} stopped before the model became ready")
                await asyncio.sleep(1)
        raise RuntimeError(f"{spec.label} did not become ready within 15 minutes")

    @staticmethod
    def _verify_install(spec: ModelSpec) -> None:
        installed, _size = _installed(spec)
        if not installed or not spec.service:
            raise RuntimeError(f"{spec.id} is not installed")

    async def _stop(self, spec: ModelSpec) -> None:
        if spec.service and (await _active(spec.service) or _healthy(spec, timeout=0.75)):
            await _systemctl("stop", spec.service, timeout=120)
        if _healthy(spec, timeout=0.75):
            raise RuntimeError(f"unmanaged {spec.id} process remained after stopping {spec.service}")

    async def _start(self, spec: ModelSpec, devices: tuple[str, ...]) -> None:
        self._verify_install(spec)
        current = _read_launch(spec.id)
        if _healthy(spec, timeout=0.75) and current == devices:
            if spec.service and not await _active(spec.service):
                raise RuntimeError(f"{spec.id} is running outside {spec.service}")
            return
        if _healthy(spec, timeout=0.75) or (spec.service and await _active(spec.service)):
            await self._stop(spec)
        profile = _read_settings()["models"][spec.id]
        _write_launch(spec, devices, profile)
        await _systemctl("start", spec.service, timeout=60)
        await self._wait_ready(spec, devices)

    async def _perception(self, enabled: bool) -> None:
        if enabled:
            # Hardware residency is authoritative. Re-enable socket activation
            # only when OmniParser is the selected 4080 component.
            PERCEPTION_RESIDENCY_MARKER.write_text("enabled\n")
            await _systemctl("enable", PERCEPTION_UNITS[0])
            await _systemctl("start", PERCEPTION_UNITS[0])
            await _systemctl("start", PERCEPTION_UNITS[1], timeout=120)
        else:
            # Removing the sockets.target link prevents a legacy display or
            # observation edge from reclaiming VRAM after this stop completes.
            PERCEPTION_RESIDENCY_MARKER.unlink(missing_ok=True)
            await _systemctl("disable", PERCEPTION_UNITS[0])
            await _systemctl("stop", *PERCEPTION_UNITS, timeout=120)
            # SIGINT during CUDA startup can leave the intentionally displaced
            # legacy worker in failed state even though it is fully stopped.
            await _systemctl("reset-failed", *PERCEPTION_UNITS)

    @staticmethod
    def _desired_models(settings: dict) -> dict[str, tuple[str, ...]]:
        desired: dict[str, list[str]] = {}
        for device in GPU_DEVICES:
            component = settings["hardware"].get(device)
            if component in MODELS:
                desired.setdefault(component, []).append(device)
        clean: dict[str, tuple[str, ...]] = {}
        for model_id, devices in desired.items():
            spec = MODELS[model_id]
            allowed = settings["models"][model_id]["allowed_devices"]
            selected = tuple(device for device in GPU_DEVICES if device in devices and device in allowed)
            if selected in _device_sets(spec, allowed):
                clean[model_id] = selected
        return clean

    async def _reconcile_defaults(self, *, strict: bool = False) -> None:
        self.reconciliation_pending = True
        settings = _read_settings()
        reserved = self._reserved_devices()
        desired = {
            model_id: devices
            for model_id, devices in self._desired_models(settings).items()
            if not set(devices) & reserved
        }
        perception_wanted = (
            settings["hardware"].get(RTX_4080_DEVICE) == PERCEPTION_COMPONENT
            and RTX_4080_DEVICE not in reserved
        )
        for model_id, base_spec in MODELS.items():
            service_active = bool(base_spec.service and await _active(base_spec.service))
            if not service_active and not _healthy(base_spec, timeout=0.75):
                continue
            if model_id not in desired or _read_launch(model_id) != desired[model_id]:
                await self._stop(base_spec)
        if not perception_wanted and (
            await _active(PERCEPTION_UNITS[0])
            or await _active(PERCEPTION_UNITS[1])
        ):
            await self._perception(False)
        for model_id, devices in desired.items():
            spec = configured_spec(model_id)
            installed, _size = _installed(spec)
            if not installed:
                if strict:
                    raise RuntimeError(f"{spec.label} is not installed")
                continue
            if RTX_4080_DEVICE in devices and (
                await _active(PERCEPTION_UNITS[0])
                or await _active(PERCEPTION_UNITS[1])
            ):
                await self._perception(False)
            await self._start(spec, devices)
        if perception_wanted:
            conflicts = [
                model_id for model_id, devices in desired.items()
                if RTX_4080_DEVICE in devices and _healthy(MODELS[model_id], timeout=0.75)
            ]
            if not conflicts:
                await self._perception(True)
        self.reconciliation_pending = False

    def _unreserved_layouts(
        self, spec: ModelSpec, override: object = None,
    ) -> list[tuple[str, ...]]:
        """One reservation check for scheduler admission and locked activation."""
        profile = _read_settings()["models"][spec.id]
        allowed = tuple(device for device in profile["allowed_devices"] if device in spec.supported_devices)
        layouts = _device_sets(spec, allowed)
        if override is not None:
            if (not isinstance(override, list) or not override
                    or any(not isinstance(device, str) for device in override)
                    or len(override) != len(set(override))
                    or any(device not in allowed for device in override)):
                raise ValueError("model devices must name each allowed GPU exactly once")
            requested = tuple(device for device in GPU_DEVICES if device in override)
            if requested not in layouts:
                valid = [" + ".join(devices) for devices in layouts]
                raise ValueError(
                    f"{spec.label} supports a layout from: "
                    f"{', '.join(valid) or 'no current GPU layout'}"
                )
            layouts = [requested]
        if not layouts:
            raise ValueError(f"{spec.label} has no valid configured GPU layout")
        # task.create can ask from its Tool thread while Realtime changes the
        # reservation on the event loop. Use one snapshot for decision/evidence.
        reservations = self.device_reservations.copy()
        reserved = set(itertools.chain.from_iterable(reservations.values()))
        candidates = [devices for devices in layouts if not set(devices) & reserved]
        if not candidates:
            raise ModelResourceUnavailable(spec, layouts, reservations)
        return candidates

    def check_resources(self, spec: ModelSpec, devices: object = None) -> None:
        """Validate admission without probing or changing services or hardware."""
        self._unreserved_layouts(spec, devices)

    def _pick_devices(self, spec: ModelSpec, override: object = None) -> tuple[str, ...]:
        candidates = self._unreserved_layouts(spec, override)
        if override is not None:
            return candidates[0]
        current = _read_launch(spec.id)
        if current in candidates and _healthy(spec, timeout=0.75):
            return current
        if spec.device_sets:
            return candidates[0]
        loaded = {
            device
            for model_id, candidate in MODELS.items()
            if model_id != spec.id and (
                _healthy(candidate, timeout=0.75)
                or _service_state(candidate.service) in {"active", "activating", "reloading"}
            )
            for device in _read_launch(model_id)
        }
        return min(
            enumerate(candidates),
            key=lambda item: (sum(device in loaded for device in item[1]), item[0]),
        )[1]

    async def _activate_task_model(self, spec: ModelSpec, devices: tuple[str, ...]) -> None:
        self.check_resources(spec, list(devices))
        for model_id, candidate in MODELS.items():
            if model_id == spec.id:
                continue
            service_active = bool(candidate.service and await _active(candidate.service))
            healthy = _healthy(candidate, timeout=0.75)
            if not service_active and not healthy:
                continue
            candidate_devices = _read_launch(model_id)
            # An active managed model without an attributable launch layout is
            # unsafe to preserve: it may already own either GPU while loading.
            if not candidate_devices or set(candidate_devices) & set(devices):
                await self._stop(candidate)
        if RTX_4080_DEVICE in devices and (
            await _active(PERCEPTION_UNITS[0])
            or await _active(PERCEPTION_UNITS[1])
        ):
            await self._perception(False)
        await self._start(spec, devices)

    async def _prepare_external_model(
        self,
        spec: ModelSpec,
        devices: tuple[str, ...],
    ) -> None:
        """Clear only the hardware needed by one externally supervised model."""

        for candidate in MODELS.values():
            service_active = bool(candidate.service and await _active(candidate.service))
            healthy = _healthy(candidate, timeout=0.75)
            if not service_active and not healthy:
                continue
            candidate_devices = _read_launch(candidate.id)
            if (
                candidate.id == spec.id
                or not candidate_devices
                or set(candidate_devices) & set(devices)
            ):
                await self._stop(candidate)
        if RTX_4080_DEVICE in devices and (
            await _active(PERCEPTION_UNITS[0])
            or await _active(PERCEPTION_UNITS[1])
        ):
            await self._perception(False)

    @asynccontextmanager
    async def resident_prefill(self, spec: ModelSpec):
        """Borrow an idle resident model; never load, switch or queue speculative work."""
        if self.lock.locked():
            yield False
            return
        try:
            # Also skip an unlocked lock with a foreground waiter already
            # scheduled to acquire it. Speculation must never join that queue.
            async with asyncio.timeout(0):
                await self.lock.acquire()
        except TimeoutError:
            yield False
            return
        self.prefill_task = asyncio.current_task()
        try:
            try:
                resident = _read_launch(spec.id) in self._unreserved_layouts(spec)
            except (ValueError, ModelResourceUnavailable):
                resident = False
            yield resident and await asyncio.to_thread(_healthy, spec)
        finally:
            self.prefill_task = None
            self.lock.release()

    async def cancel_prefill(self) -> None:
        task = self.prefill_task
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    @asynccontextmanager
    async def lease(self, spec: ModelSpec, devices: object = None):
        await self.cancel_prefill()
        await self.lock.acquire()
        activation_attempted = False
        cancelled = False
        try:
            selected = self._pick_devices(spec, devices)
            self.switching = True
            activation_attempted = True
            self.reconciliation_pending = True
            await self._activate_task_model(spec, selected)
            self.running_model = spec.id
            self.switching = False
            yield configured_spec(spec.id)
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            self.running_model = None
            try:
                # STOP must not begin another long model load. The next ordinary
                # lease activates its own exact layout and restores defaults on
                # normal exit; initialize/settings operations also reconcile.
                if (activation_attempted and not cancelled
                        and not asyncio.current_task().cancelling()):
                    self.switching = True
                    with contextlib.suppress(Exception):
                        await self._reconcile_defaults()
                        self.reconciliation_pending = False
            finally:
                self.switching = False
                self.lock.release()

    async def initialize(self) -> list[dict]:
        if self.health_client is None:
            self.health_client = httpx.Client(timeout=0.75, trust_env=False)
        model_events = sync_model_sources()
        async with self.lock:
            self.switching = True
            try:
                settings = _read_settings()
                _write_settings(settings)
                await self._reconcile_defaults()
                self.reconciliation_pending = False
            finally:
                self.switching = False
        return model_events

    async def set_hardware(self, device: object, component: object) -> dict:
        device_id = str(device or "")
        component_id = str(component or NONE_COMPONENT)
        if device_id not in {CPU_DEVICE, IGPU_DEVICE, *GPU_DEVICES}:
            raise ValueError("unknown hardware slot")
        if device_id == CPU_DEVICE and component_id != NONE_COMPONENT:
            raise ValueError("no managed CPU inference component is installed")
        if device_id == IGPU_DEVICE:
            if component_id != DISPLAY_COMPONENT:
                raise ValueError("the AMD iGPU is reserved for the live USB-C display and VAAPI media")
            return self.settings()
        if component_id not in {NONE_COMPONENT, PERCEPTION_COMPONENT, DISPLAY_COMPONENT, *MODELS}:
            raise ValueError("unknown hardware component")
        if component_id == PERCEPTION_COMPONENT and device_id != RTX_4080_DEVICE:
            raise ValueError("OmniParser currently requires its RTX 4080 TensorRT engines")
        previous_settings = _read_settings()
        settings = json.loads(json.dumps(previous_settings))
        hardware = settings["hardware"]
        old = hardware.get(device_id)
        if old in MODELS and sum(hardware.get(gpu) == old for gpu in GPU_DEVICES) > 1:
            for gpu in GPU_DEVICES:
                if hardware.get(gpu) == old:
                    hardware[gpu] = NONE_COMPONENT
        if component_id in MODELS:
            spec = MODELS[component_id]
            allowed = settings["models"][component_id]["allowed_devices"]
            if device_id not in allowed:
                raise ValueError(f"{DEVICE_LABELS[device_id]} is not allowed for {spec.label}")
            layouts = [devices for devices in _device_sets(spec, allowed) if device_id in devices]
            if not layouts:
                raise ValueError(f"{DEVICE_LABELS[device_id]} has no valid layout for {spec.label}")
            selected = min(layouts, key=len)
            for gpu in GPU_DEVICES:
                if hardware.get(gpu) == component_id:
                    hardware[gpu] = NONE_COMPONENT
            for gpu in selected:
                hardware[gpu] = component_id
        else:
            hardware[device_id] = component_id
        async with self.lock:
            self.switching = True
            try:
                _write_settings(settings)
                try:
                    await self._reconcile_defaults(strict=True)
                except Exception:
                    _write_settings(previous_settings)
                    with contextlib.suppress(Exception):
                        await self._reconcile_defaults()
                    raise
            finally:
                self.switching = False
        return self.settings()

    async def update_model(self, model_id: str, payload: dict) -> dict:
        if model_id not in MODELS:
            raise ValueError("unknown model")
        spec = MODELS[model_id]
        cancelled_after_commit = False
        async with self.lock:
            # Read the profile only after admission: a waiting operation must
            # not overwrite another owner's intervening settings commit.
            settings = _read_settings()
            profile = settings["models"][model_id]
            previous_profile = json.loads(json.dumps(profile))
            if "allowed_devices" in payload:
                devices = _normalize_devices(payload["allowed_devices"], spec)
                if not _device_sets(spec, devices):
                    raise ValueError(f"{spec.label} has no valid layout on those GPUs")
                profile["allowed_devices"] = devices
            for field, low, high in (
                ("context_tokens", 2_048, spec.max_context_tokens),
                ("max_output_tokens", 256, 32_768),
                ("max_num_seqs", 1, 32),
            ):
                if field in payload:
                    value = int(payload[field])
                    if not low <= value <= high:
                        raise ValueError(f"{field} must be between {low} and {high}")
                    profile[field] = value
            if "gpu_memory_utilization" in payload:
                value = float(payload["gpu_memory_utilization"])
                if not 0.50 <= value <= 0.99:
                    raise ValueError("gpu_memory_utilization must be between 0.50 and 0.99")
                profile["gpu_memory_utilization"] = value
            if int(profile["max_output_tokens"]) >= int(profile["context_tokens"]):
                raise ValueError("max output must be smaller than context")
            for device in GPU_DEVICES:
                if settings["hardware"].get(device) == model_id and device not in profile["allowed_devices"]:
                    settings["hardware"][device] = NONE_COMPONENT
            self.switching = True
            try:
                self.reconciliation_pending = True
                if _healthy(spec, timeout=0.75):
                    await self._stop(spec)
                _write_settings(settings)
                configuration_source = record_model_source(model_id, "configuration", {
                    "before": previous_profile,
                    "after": json.loads(json.dumps(profile)),
                })
                # Settings and their Source receipt are now committed. A stop
                # during readiness must not erase that effect or claim ready.
                try:
                    await self._reconcile_defaults()
                    self.reconciliation_pending = False
                except asyncio.CancelledError:
                    cancelled_after_commit = True
            finally:
                self.switching = False
            result = model_document(model_id)
        result.update({
            "configuration_applied": True,
            "configuration_source": configuration_source,
            "runtime_reconciled": not cancelled_after_commit,
        })
        if cancelled_after_commit:
            result.update({
                "cancellation_requested": True,
                "reconciliation_warning": (
                    "Configuration was saved, but runtime reconciliation was interrupted. "
                    "The new runtime configuration is not verified ready."
                ),
            })
        return result

    async def benchmark(self, model_id: str, devices: object) -> dict:
        if model_id not in MODELS:
            raise ValueError("unknown model")
        spec = configured_spec(model_id)
        requested = list(devices) if isinstance(devices, list) else None
        committed_result = None
        try:
            async with self.lease(spec, requested) as active:
                result = await _benchmark_text_model(active)
                result["source_path"] = record_model_source(model_id, "benchmark", result)
                settings = _read_settings()
                settings["benchmarks"][model_id] = result
                _write_settings(settings)
                committed_result = result
        except asyncio.CancelledError:
            if committed_result is None:
                raise
            return {
                **committed_result,
                "cancellation_requested": True,
                "runtime_reconciled": False,
                "reconciliation_warning": (
                    "Benchmark measurements were saved, but default-model reconciliation "
                    "was interrupted. Default residency is not verified restored."
                ),
            }
        return committed_result

    def settings(self) -> dict:
        settings = _read_settings()
        active_models = [
            spec.id
            for spec in MODELS.values()
            if _healthy(spec) or spec.id in self.external_models
        ]
        return {
            "residency_policy": "hardware_slots",
            "hardware": settings["hardware"],
            "active_models": active_models,
            "task_model": self.running_model,
            "hardware_reservations": {
                owner: list(devices)
                for owner, devices in self.device_reservations.items()
            },
            "switching": self.switching,
            "reconciliation_pending": self.reconciliation_pending,
        }

    async def reserve_devices(self, owner: str, devices: tuple[str, ...]) -> None:
        """Reserve physical GPUs for a non-model component without blocking Tasks."""

        if not owner or "\x00" in owner or len(owner) > 96:
            raise ValueError("device reservation owner must be bounded text")
        selected = tuple(device for device in GPU_DEVICES if device in devices)
        if not selected or len(selected) != len(devices) or len(devices) != len(set(devices)):
            raise ValueError("device reservation must name known GPUs exactly once")
        async with self.lock:
            conflicts = self._reserved_devices(excluding=owner) & set(selected)
            if conflicts:
                raise RuntimeError("requested hardware is already reserved")
            self.switching = True
            try:
                for candidate in MODELS.values():
                    active = bool(candidate.service and await _active(candidate.service))
                    if not active and not _healthy(candidate, timeout=0.75):
                        continue
                    layout = _read_launch(candidate.id)
                    if not layout or set(layout) & set(selected):
                        await self._stop(candidate)
                if RTX_4080_DEVICE in selected and (
                    await _active(PERCEPTION_UNITS[0])
                    or await _active(PERCEPTION_UNITS[1])
                ):
                    await self._perception(False)
                self.device_reservations[owner] = selected
            finally:
                self.switching = False

    async def release_devices(self, owner: str) -> None:
        async with self.lock:
            self.switching = True
            try:
                self.device_reservations.pop(owner, None)
                await self._reconcile_defaults()
            finally:
                self.switching = False

    async def shutdown(self) -> None:
        await self.cancel_prefill()
        # Model services outlive the development harness. Defaults are already
        # reconciled after normal Tasks/settings changes and at next initialize.
        # Interrupted leases deliberately leave a visible pending reconciliation.
        client, self.health_client = self.health_client, None
        if client is not None:
            client.close()

    async def acquire_external_lease(
        self,
        owner: str,
        spec: ModelSpec,
    ) -> tuple[str, ...]:
        """Reserve exactly one selected model's configured hardware."""

        if not owner or "\x00" in owner or len(owner) > 96:
            raise ValueError("external lease owner must be bounded text")
        await self.cancel_prefill()
        await self.lock.acquire()
        self.switching = True
        try:
            selected = self._pick_devices(spec)
            await self._prepare_external_model(spec, selected)
            self.running_model = owner
            self.external_models.clear()
            return selected
        except BaseException:
            self.running_model = None
            self.switching = False
            self.lock.release()
            raise

    def mark_external_lease_ready(
        self,
        owner: str,
        models: dict[str, tuple[str, ...]],
    ) -> None:
        """Expose a settled external lease without releasing its hardware lock."""

        if self.running_model == owner and self.lock.locked():
            normalized: dict[str, tuple[str, ...]] = {}
            for model_id, devices in models.items():
                if model_id not in MODELS:
                    raise ValueError(f"unknown external model: {model_id}")
                clean = tuple(device for device in GPU_DEVICES if device in devices)
                if clean not in _device_sets(MODELS[model_id], MODELS[model_id].supported_devices):
                    raise ValueError(f"invalid external device layout for {model_id}")
                normalized[model_id] = clean
            self.external_models = normalized
            self.switching = False

    def mark_external_lease_stopping(self, owner: str) -> None:
        """Expose the external runtime's bounded teardown as a transition."""

        if self.running_model == owner and self.lock.locked():
            self.switching = True

    async def release_external_lease(self) -> None:
        """Restore persisted Hardware selections after the external runtime exits."""

        if not self.lock.locked():
            self.external_models.clear()
            return
        try:
            self.switching = True
            self.running_model = None
            self.external_models.clear()
            await self._reconcile_defaults()
        finally:
            self.switching = False
            self.lock.release()


def model_document(model_id: str) -> dict:
    if model_id not in MODELS:
        raise ValueError("unknown model")
    return next(row for row in catalog() if row["id"] == model_id)


RUNTIME = _HardwareModelRuntime()


def check_resources(spec: ModelSpec, devices: object = None) -> None:
    RUNTIME.check_resources(spec, devices)


@asynccontextmanager
async def resident_prefill(spec: ModelSpec):
    async with RUNTIME.resident_prefill(spec) as available:
        yield available


@asynccontextmanager
async def lease(spec: ModelSpec, devices: object = None):
    async with RUNTIME.lease(spec, devices) as active:
        yield active


async def initialize() -> list[dict]:
    return await RUNTIME.initialize()


async def set_hardware(device: object, component: object) -> dict:
    return await RUNTIME.set_hardware(device, component)


async def update_model(model_id: str, payload: dict) -> dict:
    return await RUNTIME.update_model(model_id, payload)


async def benchmark(model_id: str, devices: object) -> dict:
    return await RUNTIME.benchmark(model_id, devices)


def settings() -> dict:
    return RUNTIME.settings()


async def shutdown() -> None:
    await RUNTIME.shutdown()


async def acquire_external_lease(
    owner: str,
    spec: ModelSpec,
) -> tuple[str, ...]:
    return await RUNTIME.acquire_external_lease(owner, spec)


async def release_external_lease() -> None:
    await RUNTIME.release_external_lease()


async def reserve_devices(owner: str, devices: tuple[str, ...]) -> None:
    await RUNTIME.reserve_devices(owner, devices)


async def release_devices(owner: str) -> None:
    await RUNTIME.release_devices(owner)


def mark_external_lease_ready(
    owner: str,
    models: dict[str, tuple[str, ...]],
) -> None:
    RUNTIME.mark_external_lease_ready(owner, models)


def mark_external_lease_stopping(owner: str) -> None:
    RUNTIME.mark_external_lease_stopping(owner)
