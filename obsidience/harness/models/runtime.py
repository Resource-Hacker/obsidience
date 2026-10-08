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
import threading
from contextlib import asynccontextmanager
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from pathlib import Path

import httpx
import pynvml

from . import memory as model_memory
from ..config import CONFIG
from ..host.gpu_memory import GpuMemory, process_identity

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
SPECIALIST_MODEL = EXECUTIVE_MODEL  # Legacy profile ID; auto selection uses CONFIG.
AUTO_MODEL = "auto"
NONE_COMPONENT = "none"
DISPLAY_COMPONENT = "display-media"

GEMMA_SERVICE = "obsidience-gemma.service"

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PRODUCT_ROOT = PROJECT_ROOT / "obsidience"
MODEL_SETTINGS_PATH = PRODUCT_ROOT / "state" / "model-settings.json"
MODEL_LAUNCH_DIR = PRODUCT_ROOT / "state" / "model-launch"
MODEL_CATALOG_STATE_PATH = PRODUCT_ROOT / "state" / "model-catalog.json"
MODEL_SOURCE_ROOT = PRODUCT_ROOT / "evidence" / "models"
GEMMA_MODEL = PRODUCT_ROOT / "state" / "models" / "executive.gguf"
GEMMA_TEMPLATE = GEMMA_MODEL.with_name("executive-template.jinja")
GEMMA_MTP = Path(
    "/var/lib/ai/models/jarvis-fixed/gemma-4-26b-a4b-it-qat-7b92b5b2/"
    "mtp-gemma-4-26B-A4B-it.gguf"
)
GEMMA_MTP_SHA256 = "7272d97595f0d4c74bd7b623492b7dbdaafd8b7c72f329a8270ba4eca68f768a"
GEMMA_PROJECTOR = Path(
    "/var/lib/ai/models/jarvis-fixed/gemma-4-26b-a4b-it-qat-7b92b5b2/"
    "mmproj-F16.gguf"
)
GEMMA_PROJECTOR_SHA256 = "d00f211a7d4f7fb19bd9b75d8e9342eccffb5920b08fd9562167560fdfcc5dd1"
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
    chat_template_path: Path | None = None
    mtp_path: Path | None = None
    mtp_sha256: str | None = None
    mtp_tokens: int = 0
    family: str = ""
    supports_json_schema: bool = False
    supports_input_token_limit: bool = False


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


class ModelMemoryUnavailable(ModelResourceUnavailable):
    """An unchanged model profile must wait for measurable GPU capacity."""

    def __init__(self, spec: ModelSpec, layouts: list[tuple[str, ...]],
                 memory: dict | None = None, detail: str = "") -> None:
        super().__init__(spec, layouts, {})
        self.memory = memory or {}
        self.detail = detail
        devices = dict.fromkeys(device for layout in layouts for device in layout)
        self.args = (f"{spec.label} is waiting for GPU memory on "
                     + " + ".join(DEVICE_LABELS[d] for d in devices)
                     + (f" ({detail})" if detail else "; other applications still occupy the required VRAM"),)

    def as_dict(self) -> dict:
        return {**super().as_dict(), "code": "model_memory_unavailable",
                "memory": self.memory, "detail": self.detail}


MODELS = {
    EXECUTIVE_MODEL: ModelSpec(
        id=EXECUTIVE_MODEL,
        label="Gemma 4 26B-A4B Heretic XXL",
        family="gemma4",
        base_url="http://127.0.0.1:8089/v1",
        purpose="Executive conversation and specialist Tasks with Task-selected reasoning",
        context_tokens=16_384,
        max_output_tokens=3_584,
        max_context_tokens=98_304,
        quantization="UDmerge-Q4_K_XXL",
        hardware="One Ada GPU",
        runtime="llama.cpp b10078 · MTP3",
        capabilities=("text", "vision", "reasoning", "tools"),
        reasoning_budgets={"none": 0, "low": 256, "medium": 768, "high": 1_536, "xhigh": 2_560},
        supported_devices=(RTX_4000_DEVICE,),
        default_allowed_devices=(RTX_4000_DEVICE,),
        min_gpu_count=1,
        default_gpu_memory_utilization=0.90,
        default_max_num_seqs=1,
        service=GEMMA_SERVICE,
        model_path=GEMMA_MODEL,
        verified_path=GEMMA_MODEL.with_suffix(".gguf.verified"),
        expected_size=14_329_791_488,
        projector_path=GEMMA_PROJECTOR,
        projector_sha256=GEMMA_PROJECTOR_SHA256,
        chat_template_path=GEMMA_TEMPLATE,
        mtp_path=GEMMA_MTP,
        mtp_sha256=GEMMA_MTP_SHA256,
        mtp_tokens=3,
        supports_json_schema=True,
        # Enable only with the matching native admission-guard engine deployment.
        supports_input_token_limit=True,
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
            RTX_4080_DEVICE: NONE_COMPONENT,
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
    if "hardware" not in raw and raw.get("standby_model") == NONE_COMPONENT:
        defaults["hardware"][RTX_4000_DEVICE] = NONE_COMPONENT
    hardware = raw.get("hardware")
    if isinstance(hardware, dict):
        for device in (CPU_DEVICE, IGPU_DEVICE, *GPU_DEVICES):
            value = str(hardware.get(device, defaults["hardware"][device]))
            if value in {NONE_COMPONENT, DISPLAY_COMPONENT, *MODELS}:
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
        "chat_template_path": str(spec.chat_template_path) if spec.chat_template_path else None,
        "mtp_path": str(spec.mtp_path) if spec.mtp_path else None,
        "mtp_tokens": spec.mtp_tokens,
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
        selected = normalize_model(CONFIG.llm_model, allow_auto=False)
    return configured_spec(selected)


MODEL_API_KEY_CREDENTIAL = "obsidience-model-api-key"
_MODEL_AUTH_HEADERS: dict[str, str] | None = None


def model_auth_headers() -> dict[str, str]:
    """Bearer key for loopback model servers, from this service's credential.

    Browsers can reach loopback ports; the key keeps web pages from driving
    inference. Health and model listings stay public in llama-server.
    """
    global _MODEL_AUTH_HEADERS
    if _MODEL_AUTH_HEADERS is None:
        key = ""
        directory = os.environ.get("CREDENTIALS_DIRECTORY")
        if directory:
            with contextlib.suppress(OSError):
                key = (Path(directory) / MODEL_API_KEY_CREDENTIAL).read_text().strip()
        _MODEL_AUTH_HEADERS = {"Authorization": f"Bearer {key}"} if key else {}
    return dict(_MODEL_AUTH_HEADERS)


def _healthy(spec: ModelSpec, timeout: float = 0.35) -> bool:
    try:
        # The model owner retains transport connections, never health results.
        # Standalone inspection still owns and closes its temporary client.
        client_context = (
            contextlib.nullcontext(RUNTIME.health_client)
            if RUNTIME.health_client is not None else httpx.Client(timeout=timeout)
        )
        with client_context as client:
            response = client.get(
                spec.base_url.removesuffix("/v1") + "/health", timeout=timeout,
            )
            if response.status_code != 200:
                return False
            # A healthy reused port may belong to another model owner.
            response = client.get(spec.base_url + "/models", timeout=timeout,
                                  headers=model_auth_headers())
            response.raise_for_status()
            payload = response.json()
        models = payload.get("data") if isinstance(payload, dict) else None
        return isinstance(models, list) and any(
            isinstance(model, dict) and model.get("id") == spec.id for model in models
        )
    except (httpx.HTTPError, OSError, ValueError):
        return False


async def _probe(spec: ModelSpec, timeout: float = 0.75) -> bool:
    """Run the synchronous health probe off the event loop."""
    return await asyncio.to_thread(_healthy, spec, timeout)


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
        and (spec.chat_template_path is None or spec.chat_template_path.is_file())
        and (spec.mtp_path is None or spec.mtp_path.is_file())
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
    if spec.chat_template_path:
        installed_template = spec.chat_template_path.is_file()
        identity["chat_template"] = {
            "path": str(spec.chat_template_path),
            "sha256": (
                hashlib.sha256(spec.chat_template_path.read_bytes()).hexdigest()
                if installed_template else None
            ),
            "installed": installed_template,
        }
    if spec.mtp_path:
        identity["mtp"] = {
            "path": str(spec.mtp_path),
            "size_bytes": spec.mtp_path.stat().st_size if spec.mtp_path.is_file() else None,
            "sha256": spec.mtp_sha256,
            "draft_tokens": spec.mtp_tokens,
            "installed": spec.mtp_path.is_file(),
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


def _benchmark_doc(value: object, spec: ModelSpec) -> dict | None:
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
        loaded = _healthy(spec)
        profile = settings["models"][spec.id]
        assigned = [device for device in GPU_DEVICES if hardware.get(device) == spec.id]
        active_devices = list(_read_launch(spec.id)) if loaded else []
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
                "Automatic model selection" if spec.id == CONFIG.llm_model
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
            "last_benchmark": _benchmark_doc(settings["benchmarks"].get(spec.id), spec),
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
                "linked": spec.min_gpu_count > 1,
            })
        slots.append({
            "id": device,
            "label": DEVICE_LABELS[device],
            "kind": "cpu" if device == CPU_DEVICE else "igpu" if device == IGPU_DEVICE else "gpu",
            "selected": settings["hardware"][device],
            "sensors": sensors.get(device),
            "options": options,
            "note": (
                "No managed CPU inference component is installed."
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
    async with httpx.AsyncClient(timeout=900, headers=model_auth_headers()) as client:
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
        # Incremented by every residency action; with the default target it
        # identifies whether the last reconciliation still describes the state.
        self.residency_generation = 0
        self._reconciled_state: tuple | None = None
        self.device_reservations: dict[str, tuple[str, ...]] = {}
        self._reservation_yielders: dict[str, Callable[[], Awaitable[None]]] = {}
        self._work_requests = 0
        self._activity_listeners: set[Callable[[bool], None]] = set()
        self.gpu_memory = GpuMemory()
        self._memory_plans: dict[tuple, dict[str, int]] = {}
        self._memory_plan_lock = threading.RLock()
        self._memory_refresh_lock = asyncio.Lock()
        self._reservation_processes: dict[str, tuple[int, float]] = {}

    @property
    def work_requested(self) -> bool:
        return self._work_requests > 0

    def subscribe_activity(self, listener: Callable[[bool], None]) -> Callable[[], None]:
        """Notify optional standby clients at work boundaries, without polling."""
        self._activity_listeners.add(listener)
        return lambda: self._activity_listeners.discard(listener)

    def _notify_activity(self) -> None:
        for listener in tuple(self._activity_listeners):
            with contextlib.suppress(Exception):
                listener(self.work_requested)

    async def _admit_memory(self, spec: ModelSpec, devices: object = None) -> tuple[str, ...]:
        await self.refresh_memory_plans([spec])
        selected = await asyncio.to_thread(self._pick_devices, spec, devices)
        # Reclaim Edge and verify the projected capacity before interrupting
        # Wake. A rejected admission never drains the speech worker.
        await self._prepare_memory(spec, selected)
        return selected

    async def _yield_reservations(self, spec: ModelSpec, selected: tuple[str, ...]) -> None:
        await self.cancel_prefill()
        if self._reservation_yielders:
            selected = set(selected)
            for owner, release in tuple(self._reservation_yielders.items()):
                if selected.intersection(self.device_reservations.get(owner, ())):
                    # The speech owner drains its worker before releasing
                    # its GPU. Never invoke it under the model lock.
                    await release()

    async def _begin_work(self, spec: ModelSpec, devices: object = None, *,
                          resident: tuple[str, ...] | None = None) -> None:
        # The settled resident default already holds its memory; it needs no
        # admission estimate, fresh measurement or Edge reclamation.
        selected = resident if resident is not None else await self._admit_memory(spec, devices)
        self._work_requests += 1
        self._notify_activity()
        try:
            await self._yield_reservations(spec, selected)
        except BaseException:
            self._end_work()
            raise

    def _end_work(self) -> None:
        self._work_requests -= 1
        self._notify_activity()

    def _reserved_devices(self, *, excluding: str | None = None) -> set[str]:
        return {
            device
            for owner, devices in self.device_reservations.copy().items()
            if owner != excluding
            for device in devices
        }

    def set_reservation_yielder(self, owner: str,
                               release: Callable[[], Awaitable[None]] | None) -> None:
        """Change only an existing owner's standby policy on the event loop."""
        if owner not in self.device_reservations:
            return
        if release is None:
            self._reservation_yielders.pop(owner, None)
        else:
            self._reservation_yielders[owner] = release

    def set_reservation_process(self, owner: str, pid: int) -> None:
        """The component owner attests the exact process it can drain."""
        if owner not in self.device_reservations:
            raise ValueError("GPU process needs its owner's existing reservation")
        self._reservation_processes[owner] = process_identity(pid)

    @staticmethod
    def _memory_script(spec: ModelSpec) -> Path:
        return PRODUCT_ROOT / "scripts" / {EXECUTIVE_MODEL: "llm.sh"}[spec.id]

    def _memory_plan(self, spec: ModelSpec, devices: tuple[str, ...]) -> dict[str, int] | None:
        profile = _read_settings()["models"][spec.id]
        try:
            key = model_memory.plan_key(spec, profile, devices, self._memory_script(spec))
        except OSError:
            return None
        with self._memory_plan_lock:
            return self._memory_plans.get(key)

    @staticmethod
    async def _memory_operation(callback, *args):
        operation = asyncio.create_task(asyncio.to_thread(callback, *args))
        try:
            return await asyncio.shield(operation)
        except asyncio.CancelledError:
            # NVML/fit-print and a pidfd signal/wait have bounded native work.
            # Repeated cancellation must still join that work before teardown.
            while not operation.done():
                try:
                    await asyncio.shield(operation)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            with contextlib.suppress(Exception):
                operation.result()
            raise

    async def refresh_memory_plans(self, specs: list[ModelSpec] | None = None) -> None:
        """Estimate changed profiles off the event loop, on existing work edges."""
        async with self._memory_refresh_lock:
            settings = _read_settings()
            for spec in specs or [configured_spec(key) for key in MODELS]:
                if not _installed(spec)[0]:
                    continue
                profile = settings["models"][spec.id]
                for devices in _device_sets(spec, profile["allowed_devices"]):
                    try:
                        key = model_memory.plan_key(spec, profile, devices, self._memory_script(spec))
                        with self._memory_plan_lock:
                            if key in self._memory_plans:
                                continue
                        rows = await self._memory_operation(self.gpu_memory.snapshot)
                        if not set(devices).issubset(rows):
                            continue
                        # CUDA's estimator aborts when a selected GPU is nearly full.
                        if any(rows[device].free_mib < 1024 for device in devices):
                            continue
                        amounts = await self._memory_operation(model_memory.estimate, spec, profile, devices)
                        with self._memory_plan_lock:
                            # Keep only the current profile for this model/layout.
                            self._memory_plans = {k: v for k, v in self._memory_plans.items()
                                                  if k[:2] != key[:2]}
                            self._memory_plans[key] = amounts
                    except (OSError, ValueError, subprocess.SubprocessError, pynvml.NVMLError) as exc:
                        print(f"[models] {spec.id} memory plan unavailable: {exc}")

    def _memory_error(self, spec: ModelSpec, devices: tuple[str, ...], *,
                      managed: bool = True, edge: bool = True, fresh: bool = False):
        try:
            rows = self.gpu_memory.snapshot(fresh=fresh)
        except (OSError, pynvml.NVMLError):
            return ModelMemoryUnavailable(spec, [devices], detail="current VRAM measurement unavailable")
        if not set(devices).issubset(rows):
            return ModelMemoryUnavailable(spec, [devices], detail="selected GPU measurement unavailable")
        if (_read_launch(spec.id) == devices and any(
                p.unit == spec.service for d in devices for p in rows[d].processes)
                and _healthy(spec, timeout=0.75)):
            return None  # The selected resident model already owns its buffers.
        plan = self._memory_plan(spec, devices)
        if plan is None:
            return ModelMemoryUnavailable(spec, [devices], detail="measuring this model profile")
        units = {candidate.service for candidate in MODELS.values() if candidate.service}
        yieldable = {identity for owner, identity in self._reservation_processes.copy().items()
                     if owner in self._reservation_yielders}
        capacities = {}
        for device in devices:
            row = rows[device]
            owned = [p for p in row.processes if managed and (
                p.unit in units or (p.pid, p.started) in yieldable)]
            reclaimable = sum(p.mib for p in owned)
            edge_mib = sum(self.gpu_memory.edge_reclaimable(p) for p in row.processes) if edge else 0
            capacities[device] = {"required_mib": plan[device], "free_mib": row.free_mib,
                                  "managed_reclaimable_mib": reclaimable,
                                  "edge_reclaimable_mib": edge_mib,
                                  "available_mib": max(0, min(row.total_mib, row.free_mib + reclaimable + edge_mib))}
        if any(v["available_mib"] < v["required_mib"] for v in capacities.values()):
            return ModelMemoryUnavailable(spec, [devices], capacities)
        return None

    async def _prepare_memory(self, spec: ModelSpec, devices: tuple[str, ...], *,
                              managed: bool = True) -> None:
        def measure(edge: bool):
            # NVML and the health probe stay off the event loop.
            return asyncio.to_thread(self._memory_error, spec, devices,
                                     managed=managed, edge=edge, fresh=True)
        error = await measure(False)
        if error is None:
            return
        # Only attempt Edge reclamation if that bounded release can make this
        # exact profile fit. Other desktop applications are never terminated.
        if await measure(True) is not None:
            raise error
        pids = await self._memory_operation(self.gpu_memory.reclaim_edge, devices)
        if pids:
            from ..execution import trace as action_trace
            action_trace.emit("status", "Recycled Edge GPU helper for model admission",
                              [spec.label, f"GPU helper processes: {', '.join(map(str, pids))}"])
        error = await measure(False)
        if error is not None:
            raise error

    async def _wait_ready(self, spec: ModelSpec, devices: tuple[str, ...]) -> None:
        deadline = asyncio.get_running_loop().time() + 900
        async with httpx.AsyncClient(timeout=2) as client:
            while asyncio.get_running_loop().time() < deadline:
                try:
                    response = await client.get(spec.base_url.removesuffix("/v1") + "/health")
                    if response.status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                if spec.service and not await _active(spec.service):
                    error = await asyncio.to_thread(self._memory_error, spec, devices,
                                                    managed=False, edge=False, fresh=True)
                    if error is not None:
                        raise error
                    raise RuntimeError(f"{spec.service} stopped before the model became ready")
                await asyncio.sleep(1)
        raise RuntimeError(f"{spec.label} did not become ready within 15 minutes")

    @staticmethod
    def _verify_install(spec: ModelSpec) -> None:
        installed, _size = _installed(spec)
        if not installed or not spec.service:
            raise RuntimeError(f"{spec.id} is not installed")

    async def _stop(self, spec: ModelSpec) -> None:
        if spec.service and (await _active(spec.service) or await _probe(spec)):
            self.residency_generation += 1
            await _systemctl("stop", spec.service, timeout=120)
        if await _probe(spec):
            raise RuntimeError(f"unmanaged {spec.id} process remained after stopping {spec.service}")

    async def _start(self, spec: ModelSpec, devices: tuple[str, ...]) -> None:
        self._verify_install(spec)
        current = _read_launch(spec.id)
        if current == devices and await _probe(spec):
            if spec.service and not await _active(spec.service):
                raise RuntimeError(f"{spec.id} is running outside {spec.service}")
            return
        # Settings/default residency can start a model without a Task lease.
        # Refresh the exact profile before stopping or loading its service.
        self.residency_generation += 1
        await self.refresh_memory_plans([spec])
        if await _probe(spec) or (spec.service and await _active(spec.service)):
            await self._stop(spec)
        profile = _read_settings()["models"][spec.id]
        await self._prepare_memory(spec, devices, managed=False)
        _write_launch(spec, devices, profile)
        await _systemctl("start", spec.service, timeout=60)
        await self._wait_ready(spec, devices)

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

    def _default_target(self, settings: dict) -> dict[str, tuple[str, ...]]:
        return {
            model_id: devices
            for model_id, devices in self._desired_models(settings).items()
            if not set(devices) & self._reserved_devices()
        }

    async def _reconcile_defaults(self, *, strict: bool = False) -> None:
        self.reconciliation_pending = True
        settings = _read_settings()
        desired = self._default_target(settings)
        for model_id, base_spec in MODELS.items():
            service_active = bool(base_spec.service and await _active(base_spec.service))
            if not service_active and not await _probe(base_spec):
                continue
            if model_id not in desired or _read_launch(model_id) != desired[model_id]:
                await self._stop(base_spec)
        for model_id, devices in desired.items():
            spec = configured_spec(model_id)
            installed, _size = _installed(spec)
            if not installed:
                if strict:
                    raise RuntimeError(f"{spec.label} is not installed")
                continue
            await self._start(spec, devices)
        self._reconciled_state = (self.residency_generation, desired)
        self.reconciliation_pending = False

    def _settled_since_reconciliation(self) -> bool:
        """No residency action or default-target change since the last success."""
        try:
            return self._reconciled_state == (
                self.residency_generation, self._default_target(_read_settings()))
        except Exception:
            return False

    def _resident_layout(self, spec: ModelSpec, devices: object = None) -> tuple[str, ...] | None:
        """The settled default layout already serving this exact model, if any.

        Only an unchanged reconciliation qualifies.
        """
        if devices is not None or not self._settled_since_reconciliation():
            return None
        layout = self._reconciled_state[1].get(spec.id)
        try:
            if not layout or _read_launch(spec.id) != layout:
                return None
        except Exception:
            return None
        return layout

    def invalidate_residency(self) -> None:
        """A failed provider connection voids the settled resident fast path."""
        self._reconciled_state = None

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
        # Yieldable standby reservations permit admission; _begin_work drains
        # their owners before the selected model can touch the hardware.
        reservations = {owner: devices for owner, devices in self.device_reservations.copy().items()
                        if owner not in self._reservation_yielders}
        reserved = set(itertools.chain.from_iterable(reservations.values()))
        candidates = [devices for devices in layouts if not set(devices) & reserved]
        if not candidates:
            raise ModelResourceUnavailable(spec, layouts, reservations)
        return candidates

    def check_resources(self, spec: ModelSpec, devices: object = None) -> None:
        """Read current capacity without changing services or reclaiming Edge."""
        self._memory_layouts(spec, self._unreserved_layouts(spec, devices))

    def _memory_layouts(self, spec: ModelSpec, candidates: list[tuple[str, ...]]) -> list[tuple[str, ...]]:
        available, errors = [], []
        for layout in candidates:
            error = self._memory_error(spec, layout)
            if error is None:
                available.append(layout)
            else:
                errors.append(error)
        if not available:
            raise errors[0]
        return available

    def _pick_devices(self, spec: ModelSpec, override: object = None) -> tuple[str, ...]:
        # Each catalog model has one supported device layout.
        return self._memory_layouts(spec, self._unreserved_layouts(spec, override))[0]

    async def _activate_task_model(self, spec: ModelSpec, devices: tuple[str, ...]) -> None:
        await asyncio.to_thread(self.check_resources, spec, list(devices))
        if self._reserved_devices().intersection(devices):
            raise ModelResourceUnavailable(spec, [devices], self.device_reservations.copy())
        await self._start(spec, devices)

    @asynccontextmanager
    async def resident_prefill(self, spec: ModelSpec, *, load_if_idle: bool = False):
        """Borrow idle capacity; only explicit standby may restore its model."""
        if self.lock.locked() or self.work_requested:
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
                layout = _read_launch(spec.id)
                resident = (layout in self._unreserved_layouts(spec)
                            and not self._reserved_devices().intersection(layout))
            except (ValueError, ModelResourceUnavailable):
                resident = False
            healthy = resident and await asyncio.to_thread(_healthy, spec)
            if not healthy and load_if_idle:
                try:
                    selected = await asyncio.to_thread(self._pick_devices, spec)
                    self.switching = True
                    await self._activate_task_model(spec, selected)
                    healthy = True
                except ModelResourceUnavailable:
                    healthy = False
                finally:
                    self.switching = False
            yield healthy
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
        # Steady state: the reconciled default model already serves this lease.
        # One off-loop health probe replaces memory admission, device selection
        # and the per-model service scan; any change takes the complete path.
        resident = self._resident_layout(spec, devices)
        if resident is not None and not await _probe(spec):
            resident = None
        await self._begin_work(spec, devices, resident=resident)
        try:
            await self.lock.acquire()
            if resident is not None and self._resident_layout(spec, devices) != resident:
                # Residency changed while this lease waited. Complete ordinary
                # admission outside the model lock, keeping this work request.
                self.lock.release()
                resident = None
                await self._yield_reservations(spec, await self._admit_memory(spec, devices))
                await self.lock.acquire()
        except BaseException:
            self._end_work()
            raise
        activation_attempted = False
        cancelled = False
        try:
            if resident is None:
                selected = await asyncio.to_thread(self._pick_devices, spec, devices)
                self.switching = True
                activation_attempted = True
                self.reconciliation_pending = True
                await self._activate_task_model(spec, selected)
            else:
                activation_attempted = True
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
                    if self._settled_since_reconciliation():
                        # The resident default served this lease unchanged;
                        # reconciling again would only repeat its probes.
                        self.reconciliation_pending = False
                    else:
                        self.switching = True
                        with contextlib.suppress(Exception):
                            await self._reconcile_defaults()
                            self.reconciliation_pending = False
            finally:
                self.switching = False
                self.lock.release()
                self._end_work()

    async def initialize(self) -> list[dict]:
        if self.health_client is None:
            self.health_client = httpx.Client(timeout=0.75, trust_env=False)
        model_events = sync_model_sources()
        await self.refresh_memory_plans()
        async with self.lock:
            self.switching = True
            try:
                settings = _read_settings()
                _write_settings(settings)
                try:
                    await self._reconcile_defaults()
                except ModelMemoryUnavailable as exc:
                    # Non-model API routes remain useful while another application owns the GPU.
                    print(f"[models] default residency deferred: {exc}")
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
        if component_id not in {NONE_COMPONENT, DISPLAY_COMPONENT, *MODELS}:
            raise ValueError("unknown hardware component")
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
        reconciliation_error = None
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
                if await _probe(spec):
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
                except Exception as exc:
                    # Preserve the committed settings and Source even when
                    # restoring runtime residency fails. This is not a safe
                    # invitation to replay configuration.
                    reconciliation_error = str(exc)
            finally:
                self.switching = False
            result = model_document(model_id)
        result.update({
            "configuration_applied": True,
            "configuration_source": configuration_source,
            "runtime_reconciled": not cancelled_after_commit and reconciliation_error is None,
        })
        if reconciliation_error is not None:
            result["reconciliation_warning"] = (
                "Configuration was saved, but runtime reconciliation failed: "
                + reconciliation_error + ". Runtime readiness remains unverified."
            )
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
                result["model_fingerprint"] = _model_source_identity(active)["fingerprint"]
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
        active_models = [spec.id for spec in MODELS.values() if _healthy(spec)]
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

    async def reserve_devices(self, owner: str, devices: tuple[str, ...], *,
                              yield_when_needed: Callable[[], Awaitable[None]] | None = None) -> None:
        """Reserve physical GPUs for a non-model component without blocking Tasks."""

        if not owner or "\x00" in owner or len(owner) > 96:
            raise ValueError("device reservation owner must be bounded text")
        selected = tuple(device for device in GPU_DEVICES if device in devices)
        if not selected or len(selected) != len(devices) or len(devices) != len(set(devices)):
            raise ValueError("device reservation must name known GPUs exactly once")
        async with self.lock:
            if yield_when_needed is not None and self.work_requested:
                raise RuntimeError("standby hardware is needed by active work")
            conflicts = self._reserved_devices(excluding=owner) & set(selected)
            if conflicts:
                raise RuntimeError("requested hardware is already reserved")
            self.switching = True
            try:
                for candidate in MODELS.values():
                    active = bool(candidate.service and await _active(candidate.service))
                    if not active and not await _probe(candidate):
                        continue
                    layout = _read_launch(candidate.id)
                    if not layout or set(layout) & set(selected):
                        await self._stop(candidate)
                self.device_reservations[owner] = selected
                if yield_when_needed is not None:
                    self._reservation_yielders[owner] = yield_when_needed
                else:
                    self._reservation_yielders.pop(owner, None)
            finally:
                self.switching = False

    async def release_devices(self, owner: str) -> None:
        async with self.lock:
            self.switching = True
            try:
                self.device_reservations.pop(owner, None)
                self._reservation_processes.pop(owner, None)
                self._reservation_yielders.pop(owner, None)
                try:
                    await self._reconcile_defaults()
                except ModelMemoryUnavailable as exc:
                    print(f"[models] default residency deferred: {exc}")
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
        self.gpu_memory.close()


def model_document(model_id: str) -> dict:
    if model_id not in MODELS:
        raise ValueError("unknown model")
    return next(row for row in catalog() if row["id"] == model_id)


RUNTIME = _HardwareModelRuntime()


def check_resources(spec: ModelSpec, devices: object = None) -> None:
    RUNTIME.check_resources(spec, devices)


def invalidate_residency() -> None:
    RUNTIME.invalidate_residency()


@asynccontextmanager
async def resident_prefill(spec: ModelSpec, *, load_if_idle: bool = False):
    async with RUNTIME.resident_prefill(spec, load_if_idle=load_if_idle) as available:
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


async def reserve_devices(owner: str, devices: tuple[str, ...], *,
                          yield_when_needed: Callable[[], Awaitable[None]] | None = None) -> None:
    await RUNTIME.reserve_devices(owner, devices, yield_when_needed=yield_when_needed)


async def release_devices(owner: str) -> None:
    await RUNTIME.release_devices(owner)
