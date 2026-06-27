"""Config-version seam: reload-per-run + cross-step skew detection.

Root cause (seam audit): each chain service loaded the strategy config ONCE at
startup and cached it; a deployed config change + a staggered restart left
services running DIFFERENT versions, observed as divergent config_hash across one
chain's steps (pipeline=cd66…, builder/vetter=66b9…) — a portfolio built under
different assumptions than its ranking. Fixes:
  1. _reload_strategy() re-reads the config at each run start → all services
     converge on the current file every run (no restart needed).
  2. _detect_config_skew() compares the upstream runs' config_hash to ours and
     surfaces any mismatch (audit + warning) so a residual skew is never silent.
"""
import asyncio
from contextlib import asynccontextmanager
from unittest.mock import MagicMock, patch

from app import main as pmain


# ── reload-per-run ────────────────────────────────────────────────────────────

def test_reload_strategy_picks_up_a_changed_config():
    """_reload_strategy must re-read from disk, so a deployed change is reflected
    in the module globals without a process restart."""
    calls = {"n": 0}

    def _fake_load(path):
        calls["n"] += 1
        # simulate the file content (hence hash) changing between runs
        return (MagicMock(strategy_id="s"), f"hash-{calls['n']}")

    with patch.object(pmain, "load_strategy", _fake_load):
        pmain._reload_strategy()
        first = pmain.config_hash
        pmain._reload_strategy()
        second = pmain.config_hash

    assert first == "hash-1" and second == "hash-2", (first, second)
    assert calls["n"] == 2  # re-read on every run, not cached


# ── cross-step skew detection ─────────────────────────────────────────────────

def _engine_returning(portfolio_hash, vetter_hash):
    """A mock engine whose connect() yields portfolio then vetter config_hash rows
    in the order _detect_config_skew queries them."""
    seq = [(portfolio_hash,), (vetter_hash,)]
    idx = {"i": 0}

    class _Conn:
        async def execute(self, *a, **k):
            row = seq[idx["i"]] if idx["i"] < len(seq) else None
            idx["i"] += 1
            res = MagicMock()
            res.first = MagicMock(return_value=row)
            return res

    @asynccontextmanager
    async def _connect():
        yield _Conn()

    eng = MagicMock()
    eng.connect = _connect
    return eng


def test_detect_skew_flags_divergent_upstream_hashes():
    with patch.object(pmain, "config_hash", "CUR", create=True), \
         patch.object(pmain, "engine", _engine_returning("CUR", "OTHER"), create=True):
        skew = asyncio.run(pmain._detect_config_skew(ranking_config_hash="DIFF"))
    # ranking differs (DIFF≠CUR) and vetter differs (OTHER≠CUR); portfolio matches.
    assert skew == {"ranking": "DIFF", "vetter": "OTHER"}, skew


def test_detect_skew_empty_when_all_consistent():
    with patch.object(pmain, "config_hash", "CUR", create=True), \
         patch.object(pmain, "engine", _engine_returning("CUR", "CUR"), create=True):
        skew = asyncio.run(pmain._detect_config_skew(ranking_config_hash="CUR"))
    assert skew == {}


def test_detect_skew_never_raises_on_db_error():
    boom = MagicMock()
    def _bad_connect():
        raise RuntimeError("db down")
    boom.connect = _bad_connect
    with patch.object(pmain, "config_hash", "CUR", create=True), patch.object(pmain, "engine", boom, create=True):
        # ranking matches so the only failure path is the DB lookup → must swallow
        skew = asyncio.run(pmain._detect_config_skew(ranking_config_hash="CUR"))
    assert skew == {}
