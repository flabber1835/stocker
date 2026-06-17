"""Tests for the thematic overlay on the portfolio-builder.

The overlay NEVER ranks by theme exposure — the quant score owns selection. The
theme only (a) TILTS member scores within the full pool, or (b) RESTRICTS the pool
to theme members. Default is OFF (covered by the schema test). These exercise the
pure helpers (apply_theme_tilt, restrict_to_theme) and their interaction with
greedy_select, plus graceful no-op behavior.
"""
import asyncio
import os

import numpy as np
import pandas as pd

from app.select import apply_theme_tilt, restrict_to_theme, greedy_select

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@x/x")
os.environ.setdefault("STRATEGY_CONFIG_PATH",
                      os.path.join(os.path.dirname(__file__), "..", "..",
                                   "strategies", "quality_core_v1.yaml"))


# ── unified theme source: AI theme == the hardcoded AI_BUILDOUT_UNIVERSE ───────
# (the SAME set the screener's Theme filter uses) so the screener and the built book
# are one universe — no theme_exposures / theme-classifier dependency for the AI book.

def test_ai_theme_uses_hardcoded_universe_not_db():
    from app.main import _load_theme_members
    from stock_strategy_shared.ai_universe import AI_BUILDOUT_UNIVERSE, AI_BUILDOUT_SET

    class _BoomConn:                       # must NOT be touched for the AI theme
        async def execute(self, *a, **k):
            raise AssertionError("AI theme must resolve from the hardcoded universe, not the DB")

    for theme in ("ai_infra", "ai_buildout"):
        res = asyncio.run(_load_theme_members(_BoomConn(), theme, 0.35))
        assert set(res.keys()) == AI_BUILDOUT_SET           # membership == hardcoded list
        assert len(res) == len(AI_BUILDOUT_UNIVERSE)
        assert all(v == 1.0 for v in res.values())          # uniform binary exposure


# ── graceful fallback: a NON-AI theme still reads the legacy theme_exposures and
# must never break a build when that table is absent/empty ──────────────────────

def test_load_theme_members_returns_empty_on_missing_table():
    from app.main import _load_theme_members

    class _BadConn:
        async def execute(self, *a, **k):
            raise Exception("relation \"theme_exposures\" does not exist")

    res = asyncio.run(_load_theme_members(_BadConn(), "some_other_theme", 0.35))
    assert res == {}        # empty -> overlay no-ops, the build proceeds (no crash)


# ── apply_theme_tilt ──────────────────────────────────────────────────────────

def test_tilt_boosts_members_only():
    scores = {"AAA": 0.80, "BBB": 0.70, "CCC": 0.60}
    members = {"AAA": 0.5, "CCC": 1.0}          # exposures
    out = apply_theme_tilt(scores, members, tilt_lambda=0.20)
    assert out["AAA"] == 0.80 * (1 + 0.20 * 0.5)   # boosted
    assert out["CCC"] == 0.60 * (1 + 0.20 * 1.0)   # boosted (stronger exposure)
    assert out["BBB"] == 0.70                        # non-member unchanged


def test_tilt_lambda_zero_is_identity():
    scores = {"AAA": 0.8, "BBB": 0.7}
    assert apply_theme_tilt(scores, {"AAA": 1.0}, tilt_lambda=0.0) == scores


def test_tilt_empty_members_is_identity():
    scores = {"AAA": 0.8, "BBB": 0.7}
    assert apply_theme_tilt(scores, {}, tilt_lambda=0.5) == scores


def test_tilt_does_not_mutate_input():
    scores = {"AAA": 0.8}
    out = apply_theme_tilt(scores, {"AAA": 1.0}, tilt_lambda=0.5)
    assert scores == {"AAA": 0.8}            # original untouched
    assert out["AAA"] == 0.8 * 1.5


def test_tilt_preserves_quant_order_within_members():
    # A higher-quant member stays above a lower-quant member after an equal tilt.
    scores = {"HI": 0.90, "LO": 0.50}
    out = apply_theme_tilt(scores, {"HI": 0.6, "LO": 0.6}, tilt_lambda=0.3)
    assert out["HI"] > out["LO"]


# ── restrict_to_theme ─────────────────────────────────────────────────────────

def test_restrict_keeps_only_members_in_order():
    tickers = ["AAA", "BBB", "CCC", "DDD"]
    scores = {"AAA": 1, "BBB": 2, "CCC": 3, "DDD": 4}
    rank = {"AAA": 1, "BBB": 2, "CCC": 3, "DDD": 4}
    members = {"BBB": 0.4, "DDD": 0.9}
    keep, s, r = restrict_to_theme(tickers, scores, rank, members)
    assert keep == ["BBB", "DDD"]            # order preserved, non-members dropped
    assert s == {"BBB": 2, "DDD": 4}
    assert r == {"BBB": 2, "DDD": 4}


def test_restrict_empty_members_yields_empty():
    keep, s, r = restrict_to_theme(["AAA"], {"AAA": 1}, {"AAA": 1}, {})
    assert keep == [] and s == {} and r == {}


# ── interaction with greedy_select (the point of the overlay) ──────────────────

def _diag_cov(tickers):
    # independent names, unit vol → vol term doesn't reorder; score drives picks.
    return pd.DataFrame(np.eye(len(tickers)), index=tickers, columns=tickers)


def test_tilt_can_lift_a_member_over_a_higher_nonmember():
    # MEMB (0.70 quant) trails NONM (0.75) on raw score, but a tilt closes the gap.
    tickers = ["NONM", "MEMB", "OTH"]
    base = {"NONM": 0.75, "MEMB": 0.70, "OTH": 0.40}
    cov = _diag_cov(tickers)

    raw = greedy_select(pd.Series(base), cov, target=1)
    assert raw[0]["ticker"] == "NONM"        # without tilt, NONM wins

    tilted = apply_theme_tilt(base, {"MEMB": 1.0}, tilt_lambda=0.20)  # 0.70*1.2=0.84
    picked = greedy_select(pd.Series(tilted), cov, target=1)
    assert picked[0]["ticker"] == "MEMB"     # tilt lifts the member above NONM


def test_small_tilt_does_not_override_a_strong_quant_lead():
    # A bounded tilt must NOT drag in a weak member over a far-better non-member.
    tickers = ["STRONG", "WEAKMEMB"]
    base = {"STRONG": 0.95, "WEAKMEMB": 0.40}
    cov = _diag_cov(tickers)
    tilted = apply_theme_tilt(base, {"WEAKMEMB": 1.0}, tilt_lambda=0.25)  # 0.40*1.25=0.50
    picked = greedy_select(pd.Series(tilted), cov, target=1)
    assert picked[0]["ticker"] == "STRONG"   # quant discipline preserved


def test_restrict_then_select_builds_only_from_members():
    tickers = ["A", "B", "C", "D", "E"]
    scores = {"A": 0.9, "B": 0.8, "C": 0.7, "D": 0.6, "E": 0.5}
    rank = {t: i + 1 for i, t in enumerate(tickers)}
    members = {"B": 0.5, "D": 0.5, "E": 0.5}        # A and C excluded
    keep, s, _ = restrict_to_theme(tickers, scores, rank, members)
    cov = _diag_cov(keep)
    selected = greedy_select(pd.Series(s), cov, target=10)
    picked = {x["ticker"] for x in selected}
    assert picked == {"B", "D", "E"}                # never A or C
