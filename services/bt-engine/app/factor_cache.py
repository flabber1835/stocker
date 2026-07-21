"""Per-sweep factor memoization (external-audit performance item #12).

Within one sweep, prices/fundamentals are loaded ONCE and shared by every
config; per rebalance date D the factor frame depends only on
(D, factor_engine config, data). The standing 54-config grid varies mostly
NON-factor knobs (cluster caps, liquidity floor, falling-knife) — only
momentum_method changes the factor output — so caching by
(as_of_date, factor_cfg_key) collapses ~54 factor computations per date to
the number of DISTINCT factor_engine configs (2 in the standing grid).

Disk-backed (pickle) rather than in-memory: a decades-long sweep touches
thousands of dates × ~750KB frames — gigabytes that must not live in RAM on
the NAS. The cache directory is scoped by a DATA FINGERPRINT (row count +
date span + ticker count of the loaded frames): a top-up changes the
fingerprint and the stale cache is wiped on the next sweep. Every operation
is fail-soft — an IO error degrades to a recompute, never a failed sweep.
"""
from __future__ import annotations

import hashlib
import json
import os
import pickle
import shutil
from datetime import date
from pathlib import Path

import pandas as pd

CACHE_DIR_ENV = "BT_FACTOR_CACHE_DIR"
DEFAULT_CACHE_DIR = "/tmp/bt_factor_cache"
_MARKER = "fingerprint.txt"


def data_fingerprint(prices: pd.DataFrame, fundamentals: pd.DataFrame,
                     n_tickers: int) -> str:
    """Cheap identity of the loaded dataset — enough to invalidate on top-ups
    (row counts and date span change) without hashing gigabytes."""
    parts = [
        str(len(prices)), str(len(fundamentals)), str(n_tickers),
        str(prices["date"].min()) if len(prices) else "-",
        str(prices["date"].max()) if len(prices) else "-",
    ]
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:16]


def factor_cfg_key(factor_engine_cfg) -> str:
    """Identity of the factor-relevant config slice (pydantic model or dict)."""
    dump = (factor_engine_cfg.model_dump(mode="json")
            if hasattr(factor_engine_cfg, "model_dump") else dict(factor_engine_cfg))
    return hashlib.sha1(json.dumps(dump, sort_keys=True, default=str).encode()).hexdigest()[:12]


class FactorCache:
    def __init__(self, fingerprint: str, root: str | None = None):
        self.root = Path(root or os.getenv(CACHE_DIR_ENV, DEFAULT_CACHE_DIR))
        self.fingerprint = fingerprint
        self.hits = 0
        self.misses = 0
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            marker = self.root / _MARKER
            if not marker.exists() or marker.read_text().strip() != fingerprint:
                # data changed (top-up) → every cached frame is stale; start clean
                for p in self.root.iterdir():
                    (shutil.rmtree if p.is_dir() else os.unlink)(p)
                marker.write_text(fingerprint)
            self._ok = True
        except OSError:
            self._ok = False          # cache disabled, sweeps still correct

    def _path(self, as_of: date, cfg_key: str) -> Path:
        return self.root / f"{cfg_key}_{as_of.isoformat()}.pkl"

    def get(self, as_of: date, cfg_key: str) -> pd.DataFrame | None:
        if not self._ok:
            return None
        try:
            with open(self._path(as_of, cfg_key), "rb") as f:
                df = pickle.load(f)
            self.hits += 1
            return df
        except (OSError, pickle.PickleError, EOFError, AttributeError):
            self.misses += 1
            return None

    def put(self, as_of: date, cfg_key: str, df: pd.DataFrame) -> None:
        if not self._ok:
            return
        try:
            tmp = self._path(as_of, cfg_key).with_suffix(".tmp")
            with open(tmp, "wb") as f:
                pickle.dump(df, f, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, self._path(as_of, cfg_key))
        except OSError:
            pass                      # fail-soft: next config just recomputes
