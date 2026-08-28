"""Central config. Everything overridable via obsidience.toml at project root."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRODUCT_ROOT = PROJECT_ROOT / "obsidience"


@dataclass
class Config:
    vault_dir: Path = PRODUCT_ROOT / "vault"
    db_path: Path = PRODUCT_ROOT / "state" / "obsidience.sqlite3"
    host: str = "127.0.0.1"
    port: int = 8765

    # LLM (OpenAI-compatible llama.cpp server)
    llm_base_url: str = "http://127.0.0.1:8089/v1"
    llm_model: str = "obsidience-gemma"
    llm_temperature: float = 0.4
    llm_max_tokens: int = 3584
    max_steps: int = 24  # tool-loop cap per session

    # Embeddings (fastembed; project alias points at the installed offline cache)
    embed_model: str = "BAAI/bge-small-en-v1.5"
    embed_cache_dir: str = str(PRODUCT_ROOT / "state" / "models" / "retrieval-cache")

    # Retrieval / activation packet
    search_k: int = 24
    rrf_k: int = 60

    # Scheduler
    tick_seconds: int = 20
    concurrency: int = 1

    # Voice (STT)
    whisper_model: str = "small"
    voice_enabled: bool = True

    # Git audit trail
    git_commit: bool = True

    extras: dict = field(default_factory=dict)

    @property
    def project_root(self) -> Path:
        return PROJECT_ROOT

    @property
    def product_root(self) -> Path:
        return PROJECT_ROOT / "obsidience"

    @property
    def staging_dir(self) -> Path:
        return self.vault_dir / "_staging"

    @property
    def source_dir(self) -> Path:
        """Backing blob filesystem; deliberately outside graph indexing."""
        return self.product_root / "evidence"

    @property
    def raw_source_dir(self) -> Path:
        return self.source_dir / "raw"

    @property
    def system_dir(self) -> Path:
        return self.product_root / "state" / "system"

    @property
    def runtime_dir(self) -> Path:
        return self.product_root / "state"


def load_config() -> Config:
    cfg = Config()
    toml_path = PROJECT_ROOT / "obsidience" / "obsidience.toml"
    if toml_path.exists():
        data = tomllib.loads(toml_path.read_text())
        for key, val in data.items():
            if hasattr(cfg, key):
                cur = getattr(cfg, key)
                setattr(cfg, key, Path(val) if isinstance(cur, Path) else val)
            else:
                cfg.extras[key] = val
    env_port = os.environ.get("OBSIDIENCE_PORT")
    if env_port:
        cfg.port = int(env_port)
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    return cfg


CONFIG = load_config()
