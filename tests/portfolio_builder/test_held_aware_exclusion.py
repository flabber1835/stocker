"""Unit tests for held-aware vetter exclusion in the portfolio-builder.

Source-of-truth / falling-knife-sells redesign:
  - the builder builds a fresh, holdings-agnostic target each day;
  - an LLM-judgement exclusion of a HELD name stays buy-side only (the LLM has no
    sell authority) — it is NOT removed from the candidate pool, so it remains in
    the target and is not orphan-exited;
  - ONLY the deterministic falling-knife backstop (risk_type='drawdown') may drop
    a HELD name from the target, which the delta engine then orphan-exits;
  - a NON-held name is excluded on any reason (you simply don't buy a vetoed name).
"""
from app.select import compute_excluded_set


def test_non_held_excluded_on_any_reason():
    out = compute_excluded_set(
        vetter_excluded=["AAA", "BBB"],
        held_now=set(),
        excluded_risk_type={"AAA": "earnings", "BBB": "legal"},
    )
    assert out == {"AAA", "BBB"}


def test_held_non_drawdown_exclusion_is_buy_side_only():
    # Held + LLM-judgement reason → NOT excluded (kept in target, never sold).
    out = compute_excluded_set(
        vetter_excluded=["AAA"],
        held_now={"AAA"},
        excluded_risk_type={"AAA": "earnings"},
    )
    assert out == set()


def test_held_drawdown_exclusion_drops_from_target():
    # Held + falling-knife → excluded → dropped from target → delta orphan-exits it.
    out = compute_excluded_set(
        vetter_excluded=["AAA"],
        held_now={"AAA"},
        excluded_risk_type={"AAA": "drawdown"},
    )
    assert out == {"AAA"}


def test_mixed_held_and_non_held():
    # AAA held+drawdown → excluded; BBB held+legal → kept; CCC not held → excluded.
    out = compute_excluded_set(
        vetter_excluded=["AAA", "BBB", "CCC"],
        held_now={"AAA", "BBB"},
        excluded_risk_type={"AAA": "drawdown", "BBB": "legal", "CCC": "regulatory"},
    )
    assert out == {"AAA", "CCC"}


def test_missing_risk_type_for_held_is_buy_side_only():
    # A held name whose exclusion has no/empty risk_type is treated as non-drawdown
    # (buy-side only) — only an explicit 'drawdown' may sell a held name.
    out = compute_excluded_set(
        vetter_excluded=["AAA"],
        held_now={"AAA"},
        excluded_risk_type={},
    )
    assert out == set()


def test_empty_inputs():
    assert compute_excluded_set([], set(), {}) == set()
