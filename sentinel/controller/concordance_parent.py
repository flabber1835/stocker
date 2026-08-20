"""Versioned hardened native parent required by Simplified Concordance LD-RC.

This derives a NEW controller identity from frozen Sentinel 1.1.  The frozen
Sentinel 1.1 artefact is never edited or relabelled.
"""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json

from sentinel.controller.frozen_rule import ControllerConfig, load as load_sentinel_1p1

STRATEGY_ID = "sentinel_concordance_parent_30pp_v1"
STRATEGY_VERSION = 1
FAST_DAMAGED_BREADTH_DELTA5 = 0.30
EXPECTED_SENTINEL_1P1_DELTA5 = 0.40


def _digest(*, source: ControllerConfig, fast_entry: dict) -> str:
    payload = {
        "schema": "sentinel.concordance_parent/1",
        "strategy_id": STRATEGY_ID,
        "strategy_version": STRATEGY_VERSION,
        "source_strategy_id": source.strategy_id,
        "source_rule_sha256": source.digest,
        "fast_entry": fast_entry,
        "override": {
            "min_damaged_breadth_delta5": FAST_DAMAGED_BREADTH_DELTA5,
        },
    }
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        allow_nan=False).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def load() -> ControllerConfig:
    """Load frozen Sentinel 1.1, prove the expected parent, then derive 30pp.

    Refusing if the source no longer says 40pp prevents an accidental
    double-promotion or an unrelated future Sentinel rule from inheriting the
    Concordance research fingerprint.
    """
    source = load_sentinel_1p1()
    observed = source.fast_entry.get("min_damaged_breadth_delta5")
    if observed != EXPECTED_SENTINEL_1P1_DELTA5:
        raise RuntimeError(
            "Concordance parent source mismatch: frozen Sentinel 1.1 must have "
            f"min_damaged_breadth_delta5={EXPECTED_SENTINEL_1P1_DELTA5}, got "
            f"{observed!r}")
    fast_entry = dict(source.fast_entry)
    fast_entry["min_damaged_breadth_delta5"] = FAST_DAMAGED_BREADTH_DELTA5
    return replace(
        source,
        fast_entry=fast_entry,
        strategy_id=STRATEGY_ID,
        digest=_digest(source=source, fast_entry=fast_entry),
    )


__all__ = [
    "EXPECTED_SENTINEL_1P1_DELTA5", "FAST_DAMAGED_BREADTH_DELTA5",
    "STRATEGY_ID", "STRATEGY_VERSION", "load",
]
