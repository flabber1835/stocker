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


# Cross-step skew detection is now LINEAGE-based (_detect_lineage_skew, SG1) — a pure
# ranking-vs-portfolio config comparison. See tests/pipeline/test_lineage_skew.py. The
# old async DB-based _detect_config_skew (which queried the nonexistent
# vetter_runs.config_hash) was removed.
