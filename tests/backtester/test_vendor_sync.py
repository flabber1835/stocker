"""Guard: the backtester's math must BE production's math.

rank.py / select.py (audit finding #3): the former byte-synced copies are now
re-export shims onto stock_strategy_shared.strategy_engine — the guard is
MODULE IDENTITY (`is`), which is strictly stronger than byte equality: there
is one object, so drift is impossible rather than merely detected.

regime.py is still a real vendored copy (not yet moved) — byte-sync enforced.
"""
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def test_vendored_rank_and_select_ARE_the_canonical_modules():
    import app._vendor.rank as vendored_rank
    import app._vendor.select as vendored_select
    import stock_strategy_shared.strategy_engine.rank as canonical_rank
    import stock_strategy_shared.strategy_engine.select as canonical_select
    assert vendored_rank is canonical_rank
    assert vendored_select is canonical_select


def test_shims_still_point_at_strategy_engine():
    """A shim quietly reverted to a fork would break the single-source
    guarantee while identity above still passed in THIS process order —
    check the file text too."""
    for shim in ("services/backtester/app/_vendor/rank.py",
                 "services/backtester/app/_vendor/select.py",
                 "services/pipeline/app/rank.py",
                 "services/portfolio-builder/app/select.py"):
        text = (_ROOT / shim).read_text()
        assert "stock_strategy_shared.strategy_engine" in text, shim
        assert "sys.modules[__name__]" in text, shim


def test_vendored_regime_is_byte_identical_to_source():
    s = (_ROOT / "services/pipeline/app/regime.py").read_bytes()
    v = (_ROOT / "services/backtester/app/_vendor/regime.py").read_bytes()
    assert s == v, "_vendor/regime.py has drifted from pipeline regime.py — re-copy verbatim"
