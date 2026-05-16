from __future__ import annotations

import hashlib

import yaml

from stock_strategy_shared.schemas.strategy import StrategyConfig


def load_strategy(path: str) -> tuple[StrategyConfig, str]:
    """Load and validate a strategy config YAML. Returns (config, config_hash)."""
    with open(path) as f:
        raw = f.read()
    config_hash = hashlib.sha256(raw.encode()).hexdigest()[:16]
    try:
        return StrategyConfig(**yaml.safe_load(raw)), config_hash
    except Exception as exc:
        raise RuntimeError(f"Failed to load strategy config from {path}: {exc}") from exc
