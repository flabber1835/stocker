"""Fix C — transient factor-gate hold on held names (the PBR-A incident).

A held name dropped from the CURRENT ranking by the factor gate (NULL required
factor after a vendor blip) still carried stale obs from prior runs, so it
bypassed the documented data-gap hold and entered the orphan countdown — one
more build and it would have been force-sold over a fundamentals hiccup. The
engine now takes a factor_gate_gap set and HOLDS those names without advancing
the orphan action.
"""
from datetime import date

from app.engine import RankObservation, evaluate_target_vs_live, meets_floor_fresh


def _obs(run_date, rank):
    return RankObservation(run_date=run_date, rank=rank, composite_score=1.0)


def _base(**kw):
    args = dict(
        target_portfolio={"AAA": 0.5},
        live_positions={"AAA", "PBR-A"},
        universe={
            "AAA": [_obs(date(2026, 7, 6), 1)],
            # PBR-A: STALE obs only (ranked #2 on 07-02, absent from the current
            # 07-06 run) — exactly the shape that bypassed the data-gap hold.
            "PBR-A": [_obs(date(2026, 7, 2), 2)],
        },
        confirmation_days=3,
        max_positions=10,
        target_history=[{"AAA"}, {"AAA", "PBR-A"}],  # absent from newest target
        orphan_confirmation_days=2,
    )
    args.update(kw)
    return evaluate_target_vs_live(**args)


def test_gate_gap_holds_without_advancing_orphan():
    decisions = _base(factor_gate_gap={"PBR-A"})
    d = decisions["PBR-A"]
    assert d.action == "hold", d.reason
    assert "factor gate" in d.reason and "orphan" in d.reason
    assert d.confirmation_days_met == 0
    assert d.rank == 2  # stale obs rank reported, not 9999


def test_without_gate_gap_the_old_orphan_path_fires():
    # Regression contrast: same inputs minus the set → at_risk countdown (the bug).
    decisions = _base()
    assert decisions["PBR-A"].action == "at_risk"


def test_gate_gap_does_not_shield_in_target_names():
    # A name in the target is a plain hold via the normal path; the set is only
    # consulted for not-in-target holdings.
    decisions = _base(target_portfolio={"AAA": 0.4, "PBR-A": 0.2},
                      factor_gate_gap={"PBR-A"})
    assert decisions["PBR-A"].action in ("hold", "buy_add", "sell_trim")


def test_gate_gap_with_no_obs_still_holds():
    decisions = _base(
        universe={"AAA": [_obs(date(2026, 7, 6), 1)]},  # PBR-A: no obs at all
        factor_gate_gap={"PBR-A"},
    )
    assert decisions["PBR-A"].action == "hold"


def test_meets_floor_fresh_complement():
    ref = date(2026, 7, 6)
    rows = {
        "FRESH_OK":    (50.0, date(2026, 7, 6), 50_000_000.0),   # fresh + meets floor
        "FRESH_CHEAP": (2.0,  date(2026, 7, 6), 50_000_000.0),   # fresh, below price floor
        "STALE":       (50.0, date(2026, 6, 1), 50_000_000.0),   # stale price → data gap
        "NO_PX":       (None, None, None),
    }
    out = meets_floor_fresh(rows, min_price=5.0, min_avg_dollar_volume=20_000_000.0,
                            ref_date=ref, stale_days=7)
    assert out == {"FRESH_OK"}
