"""Config loader for the dataset production pipeline
(configs/dataset_production.yaml). Mirrors the pattern in rupsaa/config.py
but kept separate so this package never needs to import the main
pydantic-settings-based Settings (which is fine, but keeping the dataset
tooling self-contained makes it trivially runnable in isolation)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = PROJECT_ROOT / "configs" / "dataset_production.yaml"


@lru_cache
def load_dataset_config() -> dict:
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def default_base_dir() -> Path:
    return PROJECT_ROOT / load_dataset_config()["base_dir"]
