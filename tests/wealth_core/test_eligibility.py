"""Entry-universe eligibility (spec §1) — and its separation from tradeability.

The defect this engine replaces was using `can_execute` as eligibility, which
made the leadership population "everything tradeable" rather than the investable
universe. That admits ETFs, preferreds, sub-$1 stocks and illiquid names, and it
does so silently: the backtest completes, every number looks reasonable, and the
strategy under test is not the one specified.

The boundary tests are exact because "at least $20 million" and "more than $20
million" differ by real securities on real days, and nothing in an aggregate
result would reveal which rule ran.
"""
from __future__ import annotations

import pytest

from stock_strategy_shared.wealth_core.eligibility import (
    EligibilityConfig,
    EligibilityInput,
    EligibilityReason,
    SecurityClass,
    deduplicate_issuers,
    eligible_ids,
    eligible_universe,
    evaluate,
)
from stock_strategy_shared.wealth_core.signals import REQUIRED_CLOSES

CFG = EligibilityConfig()


def closes(n=REQUIRED_CLOSES, start=100.0, step=1.0):
    return [start + step * i for i in range(n)]


def inp(sec="S1", **over):
    base = dict(security_id=sec, ticker=f"T{sec[1:]}", issuer_id=f"I{sec[1:]}",
                security_class=SecurityClass.COMMON, listed_on_session=True,
                unadjusted_signal_price=25.0, adv20_dollars=50_000_000.0,
                signal_dollar_volume=10_000_000.0,
                signal_closes_split_adj_div_unadj=closes())
    base.update(over)
    return EligibilityInput(**base)


def reason(**over):
    return evaluate(inp(**over), CFG).reason


# ── security class ──────────────────────────────────────────────────────────

class TestSecurityClass:
    @pytest.mark.parametrize("cls", [SecurityClass.ETF, SecurityClass.PREFERRED,
                                     SecurityClass.FUND, SecurityClass.WARRANT,
                                     SecurityClass.UNIT, SecurityClass.OTHER])
    def test_non_common_equity_is_excluded_however_tradeable(self, cls):
        """MANDATORY for ETFs and preferreds. Both trade perfectly well and both
        would sail through a tradeability check — which is exactly why using
        `can_execute` as eligibility was wrong."""
        assert reason(security_class=cls) is EligibilityReason.NOT_COMMON_EQUITY

    @pytest.mark.parametrize("cls", [SecurityClass.COMMON, SecurityClass.ADR_COMMON])
    def test_common_and_common_adr_are_admissible(self, cls):
        assert reason(security_class=cls) is EligibilityReason.ELIGIBLE


# ── thresholds, at the boundary ─────────────────────────────────────────────

class TestThresholds:
    def test_a_common_stock_below_one_dollar_is_excluded(self):
        assert reason(unadjusted_signal_price=0.99) is \
            EligibilityReason.PRICE_BELOW_MINIMUM

    def test_exactly_one_dollar_qualifies(self):
        """'At least $1' is `>=`."""
        assert reason(unadjusted_signal_price=1.0) is EligibilityReason.ELIGIBLE

    def test_ADV20_exactly_at_the_minimum_QUALIFIES(self):
        """MANDATORY. `>` instead of `>=` would drop every security sitting
        exactly on the threshold — invisible in any aggregate."""
        assert reason(adv20_dollars=20_000_000.0) is EligibilityReason.ELIGIBLE

    def test_ADV20_immediately_below_FAILS(self):
        assert reason(adv20_dollars=19_999_999.99) is \
            EligibilityReason.ADV20_BELOW_MINIMUM

    def test_signal_dollar_volume_exactly_at_the_minimum_QUALIFIES(self):
        assert reason(signal_dollar_volume=5_000_000.0) is EligibilityReason.ELIGIBLE

    def test_signal_dollar_volume_immediately_below_FAILS(self):
        assert reason(signal_dollar_volume=4_999_999.99) is \
            EligibilityReason.SIGNAL_DOLLAR_VOLUME_BELOW_MINIMUM

    @pytest.mark.parametrize("field", ["unadjusted_signal_price", "adv20_dollars",
                                       "signal_dollar_volume"])
    def test_a_missing_measurement_fails_rather_than_passing(self, field):
        """None means 'not measured'. Treating it as satisfying a minimum would
        admit exactly the securities with the worst data."""
        assert evaluate(inp(**{field: None}), CFG).eligible is False


# ── history ─────────────────────────────────────────────────────────────────

class TestHistory:
    def test_exactly_126_prior_sessions_qualify(self):
        """MANDATORY. 126 sessions of history PRIOR to the signal session, plus
        the signal session itself, is 127 closes — precisely what the momentum
        signal needs to read close[t-126]. The two statements describe one rule."""
        assert len(closes()) == 127
        assert reason(signal_closes_split_adj_div_unadj=closes()) is \
            EligibilityReason.ELIGIBLE

    def test_125_prior_sessions_FAIL(self):
        """MANDATORY. One short, and the signal would silently return None."""
        assert reason(signal_closes_split_adj_div_unadj=closes(REQUIRED_CLOSES - 1)) \
            is EligibilityReason.INSUFFICIENT_126_SESSION_HISTORY

    def test_a_GAP_inside_the_window_fails(self):
        """MANDATORY, and the reason length alone is not enough: a window with a
        hole has 127 slots and fewer than 127 sessions of real history."""
        c = closes(); c[40] = None
        assert reason(signal_closes_split_adj_div_unadj=c) is \
            EligibilityReason.INSUFFICIENT_126_SESSION_HISTORY

    def test_a_nonpositive_price_inside_the_window_is_a_gap(self):
        c = closes(); c[40] = 0.0
        assert reason(signal_closes_split_adj_div_unadj=c) is \
            EligibilityReason.INSUFFICIENT_126_SESSION_HISTORY

    def test_a_frozen_series_fails_on_volatility_not_history(self):
        """Enough observations, but zero formation volatility — which would
        divide into infinity and top the ranking. The reason has to say which
        test failed or the diagnosis is guesswork."""
        assert reason(signal_closes_split_adj_div_unadj=[100.0] * REQUIRED_CLOSES) \
            is EligibilityReason.INVALID_FORMATION_VOLATILITY


# ── point-in-time existence ─────────────────────────────────────────────────

class TestPointInTime:
    def test_a_delisted_security_REMAINS_eligible_before_its_delisting(self):
        """MANDATORY, and the whole survivorship-bias defence. The security
        existed that day; that it later delisted is information from the
        future."""
        assert reason(listed_on_session=True) is EligibilityReason.ELIGIBLE

    def test_a_security_not_listed_on_the_session_is_excluded(self):
        assert reason(listed_on_session=False) is \
            EligibilityReason.NOT_LISTED_ON_SESSION

    def test_an_unresolved_terminal_action_FAILS_CLOSED_first(self):
        """MANDATORY. Checked before everything else: a security whose terminal
        outcome is unknown must not be admitted whatever else is true of it."""
        assert reason(unresolved_terminal_action=True,
                      unadjusted_signal_price=0.10) is \
            EligibilityReason.UNRESOLVED_TERMINAL_ACTION


# ── issuer deduplication ────────────────────────────────────────────────────

class TestIssuerDeduplication:
    def test_two_share_classes_of_one_issuer_yield_ONE_candidate(self):
        """MANDATORY. Spec §1 allows one position per economic issuer, so two
        classes must not occupy two leadership slots."""
        a = inp("S1", issuer_id="ACME", is_primary_listing=True)
        b = inp("S2", issuer_id="ACME", is_primary_listing=False)
        res = eligible_universe([a, b])
        assert eligible_ids(res) == ["S1"]
        assert res["S2"].reason is EligibilityReason.DUPLICATE_ISSUER
        assert res["S2"].detail["kept"] == "S1"

    def test_primary_common_beats_a_primary_ADR(self):
        common = inp("S9", issuer_id="ACME", security_class=SecurityClass.COMMON)
        adr = inp("S1", issuer_id="ACME", security_class=SecurityClass.ADR_COMMON)
        assert eligible_ids(eligible_universe([adr, common])) == ["S9"]

    def test_among_equals_higher_ADV20_wins(self):
        thin = inp("S1", issuer_id="ACME", adv20_dollars=25_000_000.0)
        thick = inp("S2", issuer_id="ACME", adv20_dollars=90_000_000.0)
        assert eligible_ids(eligible_universe([thin, thick])) == ["S2"]

    def test_a_full_tie_breaks_on_security_id_then_ticker(self):
        """Two identical listings must still resolve deterministically, or the
        chosen one depends on input order and the decile membership drifts."""
        a = inp("S2", issuer_id="ACME")
        b = inp("S1", issuer_id="ACME")
        assert eligible_ids(eligible_universe([a, b])) == ["S1"]

    def test_dedup_only_considers_securities_that_already_passed(self):
        """An ineligible listing must not win its issuer's seat and thereby
        eliminate an eligible sibling."""
        bad = inp("S1", issuer_id="ACME", security_class=SecurityClass.ETF)
        good = inp("S2", issuer_id="ACME")
        assert eligible_ids(eligible_universe([bad, good])) == ["S2"]

    def test_different_issuers_are_untouched(self):
        assert eligible_ids(eligible_universe(
            [inp("S1", issuer_id="A"), inp("S2", issuer_id="B")])) == ["S1", "S2"]


# ── determinism and ordering ────────────────────────────────────────────────

class TestDeterminism:
    def test_eligibility_is_unchanged_by_input_row_order(self):
        """MANDATORY."""
        rows = [inp(f"S{i}", issuer_id=f"I{i % 7}",
                    adv20_dollars=20_000_000.0 + i) for i in range(30)]
        forward = eligible_ids(eligible_universe(rows))
        assert eligible_ids(eligible_universe(list(reversed(rows)))) == forward
        assert eligible_ids(eligible_universe(rows[11:] + rows[:11])) == forward

    def test_eligible_ids_are_canonically_ordered(self):
        """The audit hash is built from this, never from arrival order."""
        rows = [inp("S3"), inp("S1"), inp("S2")]
        assert eligible_ids(eligible_universe(rows)) == ["S1", "S2", "S3"]


# ── the decile is computed AFTER filtering and dedup ────────────────────────

def test_top_decile_is_computed_after_eligibility_and_dedup():
    """MANDATORY. The cutoff is a fraction of the ELIGIBLE population. Counting
    before filtering makes it a fraction of the raw feed; counting before dedup
    makes it a fraction that includes duplicates. Both widen the retained set."""
    from stock_strategy_shared.wealth_core.signals import top_decile_cutoff

    rows = ([inp(f"E{i}", issuer_id=f"IE{i}") for i in range(10)]      # eligible
            + [inp(f"D{i}", issuer_id="DUP") for i in range(10)]       # 1 survives
            + [inp(f"X{i}", issuer_id=f"IX{i}",
                   security_class=SecurityClass.ETF) for i in range(80)])
    res = eligible_universe(rows)
    n_eligible = len(eligible_ids(res))
    assert n_eligible == 11                      # 10 + one issuer survivor
    assert top_decile_cutoff(n_eligible) == 2    # not ceil(0.1*100) == 10


# ── the invariant that motivated the whole module ───────────────────────────

def test_TRADEABILITY_CANNOT_MAKE_AN_INELIGIBLE_SECURITY_ELIGIBLE():
    """PERMANENT INVARIANT. Nothing in this module reads tradeability, execution
    availability, or next-session volume — the signature makes it impossible.
    This was the actual defect: `SecurityBar.eligible = can_execute`."""
    import inspect

    from stock_strategy_shared.wealth_core import eligibility as mod
    src = inspect.getsource(mod)
    for forbidden in ("can_execute", "tradeable", "raw_open", "next_session"):
        assert forbidden not in src.split('"""')[0] + _code_only(src), (
            f"{forbidden!r} appears in eligibility logic — tradeability and "
            f"eligibility must stay separate concepts")
    assert not any(f in EligibilityInput.__dataclass_fields__
                   for f in ("tradeable", "can_execute", "raw_open"))


def _code_only(src: str) -> str:
    """Strip docstrings and comments so the prose EXPLAINING the separation does
    not trip the check that enforces it — the mistake made once already in
    tests/scripts/test_bulk_download_sharadar.py."""
    import ast
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                             ast.Module)) and ast.get_docstring(node):
            node.body = node.body[1:]
    return ast.unparse(tree)


def test_signal_eligibility_does_not_require_next_session_tradeability():
    """MANDATORY. A security may be signal-eligible on t and untradeable at
    t+1's open — the order simply waits. Requiring execution availability at
    signal time would silently shrink the universe using information that does
    not exist yet."""
    assert evaluate(inp(), CFG).eligible is True
