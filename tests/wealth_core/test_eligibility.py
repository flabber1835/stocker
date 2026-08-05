"""Entry-universe eligibility (spec §1), as amended by the recovered certified
source on 2026-08-03.

Two of these corrections REVERSE earlier instructions, and both matter:

  * issuer groups are NOT deduplicated before the leadership cutoff. The
    certified path ranked the whole eligible population by raw momentum, took
    the leadership set from it, and prevented an issuer conflict only at
    ADMISSION. Removing related securities earlier changes the population the
    cutoff is computed over, so the candidate stream cannot match.
  * the leadership floor is max(25, ceil(N x 0.10)), not a minimum of one.
    Identical for large universes; different for early history, which is exactly
    where a reproduction diverges first.

The other theme is REFUSING TO GUESS. Issuer identity comes from relatedtickers
or permaticker and from nothing else — a name- or ticker-root heuristic merges
unrelated companies and splits related ones, and neither shows up in any
aggregate number.
"""
from __future__ import annotations

import pytest

from stock_strategy_shared.wealth_core.eligibility import (
    ADV_WINDOW_SESSIONS,
    EligibilityConfig,
    EligibilityInput,
    EligibilityReason,
    TerminalState,
    adv20_dollars,
    build_issuer_group_key,
    eligible_ids,
    evaluate,
    is_common_equity,
    leadership_population,
    signal_day_dollar_volume,
)
from stock_strategy_shared.wealth_core.signals import (
    MINIMUM_LEADERSHIP_POPULATION,
    REQUIRED_CLOSES,
    leadership_count,
)

CFG = EligibilityConfig()


def closes(n=REQUIRED_CLOSES, start=100.0, step=1.0):
    return [start + step * i for i in range(n)]


def inp(sec="S1", **over):
    base = dict(security_id=sec, ticker=f"T{sec[1:]}",
                category="Domestic Common Stock",
                issuer_group_key=f"P:{sec}", issuer_key_source="PERMATICKER",
                listed_on_session=True, unadjusted_signal_price=25.0,
                adv20_dollars=50_000_000.0, signal_dollar_volume=10_000_000.0,
                signal_closes_split_adj_div_unadj=closes())
    base.update(over)
    return EligibilityInput(**base)


def reason(**over):
    return evaluate(inp(**over), CFG).reason


# ── 1. security class, from the raw Sharadar category string ────────────────

class TestSecurityCategory:
    @pytest.mark.parametrize("cat", ["Domestic Common Stock", "ADR Common Stock",
                                     "Canadian Common Stock"])
    def test_common_stock_categories_are_admissible(self, cat):
        assert is_common_equity(cat) is True
        assert reason(category=cat) is EligibilityReason.ELIGIBLE

    @pytest.mark.parametrize("cat", [
        "Domestic Common Stock Warrant", "ADR Common Stock Warrant",
        "Domestic Preferred Stock", "ADR Preferred Stock",
    ])
    def test_warrants_and_preferreds_are_excluded_even_containing_common_stock(self, cat):
        """The certified rule is a conjunction, not a substring test. 'Common
        Stock Warrant' contains 'Common Stock' — a naive `in` check admits every
        warrant in the universe."""
        assert is_common_equity(cat) is False
        assert reason(category=cat) is EligibilityReason.NOT_COMMON_EQUITY

    @pytest.mark.parametrize("cat", ["ETF", "ETN", "Domestic Stock Fund",
                                     "Institutional Investor", None, ""])
    def test_non_common_categories_are_excluded(self, cat):
        assert is_common_equity(cat) is False

    def test_the_raw_category_is_retained_in_the_audit_record(self):
        r = evaluate(inp(category="ADR Common Stock"), CFG)
        assert r.detail["category"] == "ADR Common Stock"


# ── 2. issuer identity — from Sharadar fields, never from names ─────────────

class TestIssuerIdentity:
    def test_related_tickers_give_ONE_key_regardless_of_input_order(self):
        """MANDATORY. Sorting is what makes the key stable; without it the same
        issuer produces different keys on different rows and the conflict check
        silently stops working."""
        a, sa = build_issuer_group_key("GOOG", ["GOOGL"], "1001")
        b, sb = build_issuer_group_key("GOOGL", ["GOOG"], "1002")
        assert a == b == "GOOG|GOOGL"
        assert sa == sb == "RELATEDTICKERS"

    def test_duplicate_and_unsorted_related_tickers_collapse_identically(self):
        k1, _ = build_issuer_group_key("C", ["B", "A", "C"], "9")
        k2, _ = build_issuer_group_key("A", ["C", "B"], "9")
        assert k1 == k2 == "A|B|C"

    def test_no_related_tickers_falls_back_to_permaticker(self):
        """MANDATORY."""
        assert build_issuer_group_key("AAPL", [], "199059") == \
            ("P:199059", "PERMATICKER")
        assert build_issuer_group_key("AAPL", None, "199059")[0] == "P:199059"

    def test_NAME_AND_TICKER_ROOT_SIMILARITY_NEVER_ESTABLISH_IDENTITY(self):
        """MANDATORY, and the reason strict mode exists. PBR/PBR-A share a root
        and ARE related; GOOG/GOOGL share none and are. A root heuristic gets
        both wrong, in opposite directions, silently."""
        pbr, _ = build_issuer_group_key("PBR", [], "111")
        pbra, _ = build_issuer_group_key("PBR-A", [], "222")
        assert pbr != pbra          # no root inference: different permatickers
        assert pbr == "P:111" and pbra == "P:222"

        import inspect

        from stock_strategy_shared.wealth_core import eligibility as mod
        src = inspect.getsource(mod)
        for banned in ("startswith(", "rstrip(", "company_name", "name_norm"):
            assert banned not in src, (
                f"{banned!r} suggests name/root-derived issuer identity")

    def test_missing_issuer_identity_FAILS_STRICT_MODE_deterministically(self):
        """MANDATORY. Strict mode refuses rather than inventing a group."""
        assert build_issuer_group_key("X", None, None) == (None, None)
        assert reason(issuer_group_key=None) is \
            EligibilityReason.MISSING_ISSUER_IDENTITY

    def test_non_strict_mode_tolerates_a_missing_key(self):
        loose = EligibilityConfig(strict_issuer_identity=False)
        assert evaluate(inp(issuer_group_key=None), loose).eligible is True

    def test_the_key_source_is_recorded(self):
        r = evaluate(inp(issuer_key_source="RELATEDTICKERS"), CFG)
        assert r.detail["issuer_key_source"] == "RELATEDTICKERS"


# ── 3. primary-listing metadata must not affect certified results ───────────

def test_PRIMARY_LISTING_METADATA_CANNOT_AFFECT_CERTIFIED_RESULTS():
    """MANDATORY. Sharadar does not carry it and the certified prototype did not
    use it, so it must be inert — proven by running both values, not promised."""
    a = evaluate(inp(is_primary_listing=True), CFG)
    b = evaluate(inp(is_primary_listing=False), CFG)
    c = evaluate(inp(is_primary_listing=None), CFG)
    assert a.eligible == b.eligible == c.eligible is True
    assert a.reason is b.reason is c.reason

    import inspect

    from stock_strategy_shared.wealth_core import eligibility as mod
    body = inspect.getsource(mod.evaluate)
    assert "is_primary_listing" not in body


# ── 4. NO pre-cutoff deduplication (certified correction) ───────────────────

class TestRelatedSecuritiesStayInThePopulation:
    def test_related_securities_REMAIN_in_the_pre_cutoff_population(self):
        """MANDATORY, and it reverses the earlier instruction. The certified
        path ranked the whole eligible population — related names included — and
        separated them only at admission."""
        a = inp("S1", issuer_group_key="S1|S2", issuer_key_source="RELATEDTICKERS")
        b = inp("S2", issuer_group_key="S1|S2", issuer_key_source="RELATEDTICKERS")
        res = leadership_population([a, b])
        assert eligible_ids(res) == ["S1", "S2"]
        assert all(r.reason is EligibilityReason.ELIGIBLE for r in res.values())

    def test_no_DUPLICATE_ISSUER_reason_is_emitted_at_eligibility_time(self):
        """The population is not where issuer conflicts are decided any more."""
        res = leadership_population([inp("S1", issuer_group_key="K"),
                                     inp("S2", issuer_group_key="K")])
        assert not any(r.reason is EligibilityReason.DUPLICATE_ISSUER
                       for r in res.values())

    def test_the_cutoff_is_computed_over_the_UNDEDUPLICATED_population(self):
        """The concrete consequence: 30 eligible securities of which 20 share one
        issuer still give a leadership count based on 30, not 11."""
        rows = [inp(f"D{i}", issuer_group_key="DUP") for i in range(20)] + \
               [inp(f"E{i}", issuer_group_key=f"P:E{i}") for i in range(10)]
        n = len(eligible_ids(leadership_population(rows)))
        assert n == 30
        assert leadership_count(n) == MINIMUM_LEADERSHIP_POPULATION


# ── 5. leadership population size (certified correction) ────────────────────

class TestLeadershipCount:
    @pytest.mark.parametrize("n,expected", [
        (9, 9), (10, 10), (25, 25),          # small universes: everyone leads
        (100, 25), (250, 25),                # the floor binds
        (251, 26), (260, 26), (261, 27),     # the ceiling takes over
    ])
    def test_it_is_max_25_ceil_ten_percent(self, n, expected):
        """MANDATORY. max(25, ceil(N x 0.10)), capped at N. The 250/251 step is
        where the floor hands over to the ceiling."""
        assert leadership_count(n) == expected

    def test_the_floor_is_a_named_parameter(self):
        assert MINIMUM_LEADERSHIP_POPULATION == 25
        assert leadership_count(100, minimum_leadership_population=10) == 10

    def test_the_ceiling_boundaries_are_retained_separately(self):
        """The ceil behaviour itself, isolated from the floor."""
        assert leadership_count(255, minimum_leadership_population=0) == 26
        assert leadership_count(250, minimum_leadership_population=0) == 25
        assert leadership_count(0) == 0


# ── 6. liquidity in the certified price domain ──────────────────────────────

class TestLiquidityDomain:
    def test_signal_dollar_volume_uses_the_RAW_UNADJUSTED_close(self):
        """MANDATORY. Using the split-adjusted signal close would rescale every
        liquidity figure by the cumulative split factor — a 4:1 split makes a
        stock look a quarter as liquid, and the error grows with age."""
        assert signal_day_dollar_volume(50.0, 200_000) == 10_000_000.0

    def test_ADV20_INCLUDES_the_signal_session(self):
        """MANDATORY. The window is the 20 sessions ENDING AT t inclusive, so
        the last observation is t's own."""
        c = [10.0] * 19 + [100.0]
        v = [1_000_000] * 20
        assert adv20_dollars(c, v) == pytest.approx((19 * 10e6 + 100e6) / 20)

    def test_the_window_is_exactly_20_sessions(self):
        assert ADV_WINDOW_SESSIONS == 20
        assert adv20_dollars([10.0] * 19, [1e6] * 19) is None       # too short
        long = adv20_dollars([1.0] * 50 + [10.0] * 20, [1e6] * 70)
        assert long == pytest.approx(10e6)                          # last 20 only

    def test_a_missing_session_FAILS_CONTINUITY_rather_than_being_replaced(self):
        """MANDATORY. Substituting a stale observation would let a security that
        stopped trading keep its liquidity qualification."""
        c = [10.0] * 20; c[5] = None
        assert adv20_dollars(c, [1e6] * 20) is None
        v = [1e6] * 20; v[7] = None
        assert adv20_dollars([10.0] * 20, v) is None

    def test_the_thresholds_stay_inclusive(self):
        assert reason(adv20_dollars=20_000_000.0) is EligibilityReason.ELIGIBLE
        assert reason(adv20_dollars=19_999_999.99) is \
            EligibilityReason.ADV20_BELOW_MINIMUM
        assert reason(signal_dollar_volume=5_000_000.0) is EligibilityReason.ELIGIBLE
        assert reason(signal_dollar_volume=4_999_999.99) is \
            EligibilityReason.SIGNAL_DOLLAR_VOLUME_BELOW_MINIMUM


# ── 7. terminal state from ACTIONS, never from isdelisted ───────────────────

class TestTerminalState:
    def test_a_terminal_ACTIONS_event_creates_pending_state(self):
        """MANDATORY. Pending fails closed and is checked FIRST, so nothing else
        about the security can override an unknown outcome."""
        assert reason(terminal_state=TerminalState.TERMINAL_PENDING,
                      unadjusted_signal_price=0.10) is \
            EligibilityReason.UNRESOLVED_TERMINAL_ACTION

    def test_ISDELISTED_ALONE_CANNOT_MANUFACTURE_A_SETTLEMENT(self):
        """MANDATORY. `isdelisted` is a static flag: it says a security delisted,
        never that an outcome was verified. Nothing in this module reads it, so
        it cannot resolve or zero anything."""
        # Comment-stripped, for the third time in this project: the docstring
        # EXPLAINING that isdelisted is never read would otherwise fail the test
        # ENFORCING that it is never read.
        import ast
        import inspect

        from stock_strategy_shared.wealth_core import eligibility as mod
        tree = ast.parse(inspect.getsource(mod))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef, ast.Module)) and ast.get_docstring(node):
                node.body = node.body[1:]
        code = ast.unparse(tree)
        assert "isdelisted" not in code and "is_delisted" not in code

    def test_resolved_and_normal_states_are_admissible(self):
        assert reason(terminal_state=TerminalState.NORMAL) is \
            EligibilityReason.ELIGIBLE
        assert reason(terminal_state=TerminalState.TERMINAL_RESOLVED) is \
            EligibilityReason.ELIGIBLE


# ── unchanged §1 requirements ───────────────────────────────────────────────

class TestRemainingRequirements:
    def test_price_boundary_is_inclusive(self):
        assert reason(unadjusted_signal_price=1.0) is EligibilityReason.ELIGIBLE
        assert reason(unadjusted_signal_price=0.99) is \
            EligibilityReason.PRICE_BELOW_MINIMUM

    def test_exactly_126_prior_sessions_qualify_and_125_fail(self):
        assert len(closes()) == 127          # 126 prior + the signal session
        assert reason(signal_closes_split_adj_div_unadj=closes()) is \
            EligibilityReason.ELIGIBLE
        assert reason(signal_closes_split_adj_div_unadj=closes(REQUIRED_CLOSES - 1)) \
            is EligibilityReason.INSUFFICIENT_126_SESSION_HISTORY

    def test_a_gap_inside_the_window_fails(self):
        c = closes(); c[40] = None
        assert reason(signal_closes_split_adj_div_unadj=c) is \
            EligibilityReason.INSUFFICIENT_126_SESSION_HISTORY

    def test_a_frozen_series_fails_on_volatility(self):
        assert reason(signal_closes_split_adj_div_unadj=[100.0] * REQUIRED_CLOSES) \
            is EligibilityReason.INVALID_FORMATION_VOLATILITY

    def test_a_delisted_security_remains_eligible_before_its_delisting(self):
        assert reason(listed_on_session=True) is EligibilityReason.ELIGIBLE
        assert reason(listed_on_session=False) is \
            EligibilityReason.NOT_LISTED_ON_SESSION


# ── determinism, and the standing invariant ─────────────────────────────────

def test_eligibility_is_unchanged_by_input_row_order():
    rows = [inp(f"S{i}", adv20_dollars=20_000_000.0 + i) for i in range(30)]
    fwd = eligible_ids(leadership_population(rows))
    assert eligible_ids(leadership_population(list(reversed(rows)))) == fwd
    assert eligible_ids(leadership_population(rows[11:] + rows[:11])) == fwd


def test_TRADEABILITY_CANNOT_MAKE_AN_INELIGIBLE_SECURITY_ELIGIBLE():
    """PERMANENT INVARIANT. Checked over comment-stripped source so the prose
    explaining the separation cannot trip the check enforcing it."""
    import ast
    import inspect

    from stock_strategy_shared.wealth_core import eligibility as mod
    tree = ast.parse(inspect.getsource(mod))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                             ast.Module)) and ast.get_docstring(node):
            node.body = node.body[1:]
    code = ast.unparse(tree)
    for forbidden in ("can_execute", "tradeable", "raw_open"):
        assert forbidden not in code
    assert not any(f in EligibilityInput.__dataclass_fields__
                   for f in ("tradeable", "can_execute", "raw_open"))
