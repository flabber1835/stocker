"""Guard: preview_ranking must rank with production's math.

The former byte-synced copy is now a re-export shim onto
stock_strategy_shared.strategy_engine.rank — the guard is MODULE IDENTITY,
plus a file-text check that the shim wasn't quietly reverted to a fork."""
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def test_vendored_rank_IS_the_canonical_module():
    import app._vendor.rank as vendored
    import stock_strategy_shared.strategy_engine.rank as canonical
    assert vendored is canonical


def test_shim_still_points_at_strategy_engine():
    text = (_ROOT / "services/evaluator/app/_vendor/rank.py").read_text()
    assert "stock_strategy_shared.strategy_engine" in text
    assert "sys.modules[__name__]" in text
