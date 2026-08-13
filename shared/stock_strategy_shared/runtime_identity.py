"""Small, deterministic runtime/dependency identity shared by built engines.

This module deliberately lives outside ``wealth_core``: changing the mechanism
that identifies a runtime must not move the certified strategy-source hash.
"""
from __future__ import annotations

import dataclasses
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
from typing import Any


def installed_distributions() -> list[list[str]]:
    """Return every installed distribution as sorted canonical name/version."""
    found: dict[str, list[str]] = {}
    for dist in metadata.distributions():
        raw_name = dist.metadata.get("Name")
        if not raw_name:
            continue
        name = str(raw_name).strip().lower().replace("_", "-")
        version = str(dist.version)
        found.setdefault(name, []).append(version)
    # Sorting duplicate versions makes the digest independent of metadata
    # directory enumeration while still exposing a broken double install.
    return [[name, "|".join(sorted(found[name]))] for name in sorted(found)]


def dependency_identity(lock_path: str | Path) -> dict[str, Any]:
    """Bind exact lock bytes and the complete installed distribution closure."""
    path = Path(lock_path)
    lock = path.read_bytes()
    distributions = installed_distributions()
    canonical = json.dumps(
        distributions, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False).encode("utf-8")
    return {
        "requirements_lock_sha256": hashlib.sha256(lock).hexdigest(),
        "distributions_sha256": hashlib.sha256(canonical).hexdigest(),
        "distributions_count": len(distributions),
    }


def wealth_core_baseline_identity(*, starting_cash: float = 1_000_000.0
                                  ) -> dict[str, Any]:
    """Name every effective default consumed by canonical baseline replay."""
    from stock_strategy_shared.wealth_core.eligibility import EligibilityConfig
    from stock_strategy_shared.wealth_core.engine import WealthCoreConfig

    config = WealthCoreConfig()
    eligibility = EligibilityConfig()
    config_value = dataclasses.asdict(config)
    eligibility_value = dataclasses.asdict(eligibility)
    return {
        "starting_cash": starting_cash,
        "wealth_core_config": config_value,
        "wealth_core_config_sha256": hashlib.sha256(json.dumps(
            config_value, sort_keys=True, separators=(",", ":"),
            allow_nan=False).encode("utf-8")).hexdigest(),
        "engine_config_hash": config.config_hash(),
        "eligibility_config": eligibility_value,
        "eligibility_config_sha256": hashlib.sha256(json.dumps(
            eligibility_value, sort_keys=True, separators=(",", ":"),
            allow_nan=False).encode("utf-8")).hexdigest(),
    }


__all__ = [
    "dependency_identity", "installed_distributions",
    "wealth_core_baseline_identity",
]
