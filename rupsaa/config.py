"""Central configuration for Rupsaa.

Single source of truth for paths, the base model ID, and environment-driven
settings. Nothing else in the codebase should hard-code a model ID, a config
path, or read `os.environ` directly for these values — import from here.

Precedence for the model ID: MODEL_ID env var > configs/model.yaml
"base_model_id". This lets deployment environments override the model
without editing YAML, while YAML remains the documented default.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIGS_DIR = PROJECT_ROOT / "configs"

load_dotenv(PROJECT_ROOT / ".env")


class Settings(BaseSettings):
    """Environment-driven settings (see .env.example for documented defaults)."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    huggingface_token: str | None = None
    model_id: str | None = None  # overrides configs/model.yaml if set
    # Which trained LoRA adapter to load on top of the base model. Override
    # via the RUPSAA_ADAPTER_PATH env var (e.g. "adapters/rupsaa-v0.1" once
    # that adapter exists). If the resolved path doesn't exist or is empty,
    # rupsaa/model/loader.py logs a warning and serves the base model only
    # — nothing breaks if this points at an adapter that hasn't been
    # trained yet.
    adapter_path: str = Field(
        default="adapters/rupsaa-v1",
        validation_alias=AliasChoices("RUPSAA_ADAPTER_PATH", "ADAPTER_PATH"),
    )

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5500,http://127.0.0.1:5500"

    web_api_url: str = "http://localhost:8000"

    embedding_model_id: str | None = None  # overrides configs/rag.yaml if set
    vector_store_dir: str = "knowledge/index"
    knowledge_docs_dir: str = "knowledge/documents"
    # Structured terminology entries (rupsaa/rag/terminology.py), one JSON
    # file per term, owner-editable via web/knowledge.html → Terminology.
    knowledge_terminology_dir: str = "knowledge/terminology"

    # Owner-only tools (Teach Rupsaa, Rupsaa Knowledge) — see api/owner_routes.py.
    # Unset (empty) by default for local development, which allows access
    # with a logged warning. Set this to a real secret before ever exposing
    # the API beyond localhost/a trusted tunnel — once set, every /owner/*
    # request must send a matching `X-Owner-Key` header or it's rejected.
    owner_api_key: str = ""

    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    def resolve_path(self, relative: str) -> Path:
        """Resolve a project-relative path (e.g. from a YAML config) to an
        absolute path anchored at the project root, so scripts work
        regardless of the caller's current working directory."""
        p = Path(relative)
        return p if p.is_absolute() else PROJECT_ROOT / p


@lru_cache
def get_settings() -> Settings:
    return Settings()


def _load_yaml(name: str) -> dict:
    path = CONFIGS_DIR / name
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache
def load_model_config() -> dict:
    cfg = _load_yaml("model.yaml")
    settings = get_settings()
    if settings.model_id:
        cfg["base_model_id"] = settings.model_id
    return cfg


@lru_cache
def load_training_config(config_path: str | None = None) -> dict:
    """Loads a training config YAML.

    `config_path` is an optional path to a specific training config (e.g.
    "configs/training/rupsaa_v0.1_qlora.yaml"), resolved relative to
    PROJECT_ROOT if not absolute. Defaults to configs/training.yaml,
    preserving existing CLI/behavior when no override is given.
    """
    if config_path is None:
        return _load_yaml("training.yaml")
    path = Path(config_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@lru_cache
def load_inference_config() -> dict:
    return _load_yaml("inference.yaml")


@lru_cache
def load_rag_config() -> dict:
    cfg = _load_yaml("rag.yaml")
    settings = get_settings()
    if settings.embedding_model_id:
        cfg["embedding_model_id"] = settings.embedding_model_id
    cfg["vector_store"]["index_dir"] = settings.vector_store_dir
    cfg["documents"]["source_dir"] = settings.knowledge_docs_dir
    return cfg


def get_base_model_id() -> str:
    return load_model_config()["base_model_id"]
