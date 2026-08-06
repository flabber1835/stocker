"""The volatility profile must CHANGE BEHAVIOUR, not just change a number.

WHY THIS FILE EXISTS, and why it is separate from everything else.

`test_signals.py` proves each formula is mathematically correct against
hand-computed closed forms. The golden fixture proves the certified end-to-end
behaviour is frozen. Neither proves the profile is actually WIRED to anything:
a `volatility_profile` that was accepted, hashed, and then quietly ignored by
`score_universe` would pass both, because the hand-computed tests call
`annualized_formation_volatility` directly and the golden scenario — measured at
the 2026-08-06 re-pin — produces the SAME 30 entries, the same 24 positions and
the same final cash to the cent under both profiles. Its securities all carry
the same +/-2% jitter, so log compression is near-uniform across the
cross-section and cancels out of the ranking.

So this is the missing rung: a deliberately small scenario in which the two
profiles are FORCED to disagree, asserted at four levels — the volatility, the
ordering, the security actually admitted, and the config hash that makes a
result attributable to the formula that produced it.

It does not touch `golden.py` and pins none of its hashes. The certified
artefact stays exactly where it is.

THE CONSTRUCTION, and why it produces a genuine flip rather than a tuned one.

Two securities whose formation segments have the IDENTICAL cumulative return
(+50%), so `log1p(momentum)` — the numerator of the durable score — is the same
number for both and volatility is the only thing that can order them.

    SPIKE   rises in 3 large up-gaps, drifting gently down in between
    SLIDE   falls in 4 large down-gaps, drifting gently up in between

Every gap is the same size IN LOG TERMS (0.35). That is the whole mechanism:
the same log move is worth more in simple terms on the way up than on the way
down, because a simple return is unbounded above and floored at -100%.

    up      e^0.35 - 1  = +41.9%
    down    1 - e^-0.35 = -29.5%

So SIMPLE returns see SPIKE's three gaps as much larger than SLIDE's four and
rank SPIKE the more volatile name; LOG returns see all seven gaps as identical
in size, count them, and rank SLIDE the more volatile name — because it has one
more. The two profiles therefore disagree about WHICH SECURITY IS RISKIER on
identical price paths, and since volatility is the denominator of the durable
score they disagree about which one to buy.

That asymmetry is a property of the two formulas, not of these numbers. The
magnitudes were chosen only to put both margins around 18%, comfortably clear of
any tie-break.
"""
from __future__ import annotations

import math

import pytest

from stock_strategy_shared.wealth_core.eligibility import (
    EligibilityConfig,
    EligibilityInput,
    EligibilityReason,
    evaluate,
)
from stock_strategy_shared.wealth_core.engine import (
    Operation,
    Reason,
    SecurityBar,
    WealthCoreConfig,
    decide,
    score_universe,
)
from stock_strategy_shared.wealth_core.marks import Mark, MarkStatus
from stock_strategy_shared.wealth_core.signals import (
    LOG_RETURNS_CERTIFIED_V1,
    LONG_LOOKBACK_SESSIONS,
    REQUIRED_CLOSES,
    SIMPLE_RETURNS_V1,
    SKIP_RECENT_SESSIONS,
    VOLATILITY_PROFILES,
    annualized_formation_volatility,
    medium_term_momentum,
    rank_candidates,
    recent_return,
)
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState

# ── the scenario ────────────────────────────────────────────────────────────

GAP_LOG = 0.35                      # every gap, in log terms, for both names
CUMULATIVE = math.log(1.5)          # both formation segments return exactly +50%
FORMATION_RETURNS = 105

SPIKE_GAPS = 3                      # large moves UP
SLIDE_GAPS = 4                      # large moves DOWN — one more, deliberately


def _series(n_gaps: int, sign: int) -> list[float]:
    """`REQUIRED_CLOSES` closes whose formation segment returns exactly +50%.

    `n_gaps` returns of `sign * GAP_LOG`, and the remaining formation returns
    all equal to whatever makes the log returns sum to `CUMULATIVE`. The tail
    after the formation segment is FLAT, so `recent_return` is exactly 0.0 —
    which qualifies (spec §4, zero passes) for both names identically, keeping
    the freshness gate out of the comparison.
    """
    gap = sign * GAP_LOG
    drift = (CUMULATIVE - n_gaps * gap) / (FORMATION_RETURNS - n_gaps)
    step = FORMATION_RETURNS // n_gaps
    at = {i * step + 3 for i in range(n_gaps)}
    closes = [100.0]
    for i in range(FORMATION_RETURNS):
        closes.append(round(closes[-1] * math.exp(gap if i in at else drift), 4))
    return closes + [closes[-1]] * SKIP_RECENT_SESSIONS


SPIKE = _series(SPIKE_GAPS, +1)
SLIDE = _series(SLIDE_GAPS, -1)

# Pinned per profile. These are the numbers the whole file turns on, so they are
# stated rather than recomputed: a change to either is a change to the strategy.
EXPECTED_VOL = {
    SIMPLE_RETURNS_V1:        {"SPIKE": 1.1303498971918273, "SLIDE": 0.9567690028530034},
    LOG_RETURNS_CERTIFIED_V1: {"SPIKE": 0.9468659163540747, "SLIDE": 1.1232611073689500},
}
EXPECTED_SCORE = {
    SIMPLE_RETURNS_V1:        {"SPIKE": 0.35870760825075254, "SLIDE": 0.42378579040406000},
    LOG_RETURNS_CERTIFIED_V1: {"SPIKE": 0.42821808357979085, "SLIDE": 0.36097137651093264},
}
# The consequence, and the reason this file is not just arithmetic.
EXPECTED_WINNER = {SIMPLE_RETURNS_V1: "SLIDE", LOG_RETURNS_CERTIFIED_V1: "SPIKE"}

SERIES = {"SPIKE": SPIKE, "SLIDE": SLIDE}
SEC = {"SPIKE": "SEC_SPIKE", "SLIDE": "SEC_SLIDE"}


def bars() -> list[SecurityBar]:
    return [SecurityBar(SEC["SPIKE"], "SPIKE", "ISSUER_SPIKE", SPIKE),
            SecurityBar(SEC["SLIDE"], "SLIDE", "ISSUER_SLIDE", SLIDE)]


# ── 1. the comparison is fair: nothing but volatility can separate them ─────

class TestTheTwoSeriesAreAFairComparison:
    """If the names differed on history, freshness, momentum or eligibility, a
    difference in the chosen security would prove nothing about the profiles."""

    def test_both_have_exactly_the_required_history(self):
        assert len(SPIKE) == len(SLIDE) == REQUIRED_CLOSES

    def test_their_momentum_is_IDENTICAL(self):
        """The numerator of the durable score is log1p(momentum). Identical
        momentum means the numerator cancels and ONLY volatility can order
        them — which is what makes the flip attributable."""
        assert medium_term_momentum(SPIKE) == medium_term_momentum(SLIDE) == 0.5

    def test_their_freshness_is_IDENTICAL_and_qualifies(self):
        assert recent_return(SPIKE) == recent_return(SLIDE) == 0.0

    def test_both_stay_positive_and_plausibly_priced(self):
        assert min(SPIKE) > 1.0 and min(SLIDE) > 1.0

    @pytest.mark.parametrize("profile", VOLATILITY_PROFILES)
    @pytest.mark.parametrize("name", ["SPIKE", "SLIDE"])
    def test_both_are_ELIGIBLE_under_both_profiles(self, name, profile):
        """Liquidity and history are ample for both under both formulas, so the
        admission difference below cannot be an eligibility difference wearing
        a costume."""
        r = evaluate(EligibilityInput(
            security_id=SEC[name], ticker=name,
            category="Domestic Common Stock",
            issuer_group_key=f"P:{name}", issuer_key_source="PERMATICKER",
            listed_on_session=True, unadjusted_signal_price=SERIES[name][-1],
            adv20_dollars=80_000_000.0, signal_dollar_volume=25_000_000.0,
            signal_closes_split_adj_div_unadj=SERIES[name],
            history_contiguous=True),
            EligibilityConfig(volatility_profile=profile))
        assert r.reason is EligibilityReason.ELIGIBLE

    def test_the_ASYMMETRY_that_drives_the_whole_file(self):
        """Every gap is the same size in logs; it is not the same size in
        simple returns. That single fact is the mechanism."""
        up = math.exp(GAP_LOG) - 1.0
        down = 1.0 - math.exp(-GAP_LOG)
        assert up == pytest.approx(0.419068, abs=1e-6)
        assert down == pytest.approx(0.295312, abs=1e-6)
        assert up > down, (
            "a simple return is unbounded above and floored at -100%, so the "
            "same log move is larger on the upside — which is why SPIKE's 3 "
            "gaps outweigh SLIDE's 4 under simple returns and not under log")


# ── 2. the volatility itself, per profile ───────────────────────────────────

class TestTheVolatilityDiffersByProfile:

    @pytest.mark.parametrize("profile", VOLATILITY_PROFILES)
    @pytest.mark.parametrize("name", ["SPIKE", "SLIDE"])
    def test_the_pinned_value(self, name, profile):
        assert annualized_formation_volatility(SERIES[name], profile) == \
            pytest.approx(EXPECTED_VOL[profile][name])

    def test_the_profiles_DISAGREE_about_which_name_is_riskier(self):
        """Not merely 'the numbers differ'. They order the two securities in
        OPPOSITE directions on identical price paths, which is the only kind of
        difference that can change a portfolio."""
        s = EXPECTED_VOL[SIMPLE_RETURNS_V1]
        lg = EXPECTED_VOL[LOG_RETURNS_CERTIFIED_V1]
        assert s["SPIKE"] > s["SLIDE"], "simple returns call SPIKE riskier"
        assert lg["SPIKE"] < lg["SLIDE"], "log returns call SLIDE riskier"


# ── 3. the ordering flips ───────────────────────────────────────────────────

class TestTheCANDIDATE_ORDERING_Flips:

    @pytest.mark.parametrize("profile", VOLATILITY_PROFILES)
    def test_the_top_ranked_candidate_is_the_expected_one(self, profile):
        cfg = WealthCoreConfig(volatility_profile=profile)
        ranked = rank_candidates(score_universe(bars(), cfg))
        assert [r.ticker for r in ranked][0] == EXPECTED_WINNER[profile]

    @pytest.mark.parametrize("profile", VOLATILITY_PROFILES)
    def test_the_scores_are_the_pinned_ones(self, profile):
        cfg = WealthCoreConfig(volatility_profile=profile)
        by_ticker = {s.ticker: s for s in score_universe(bars(), cfg)}
        for name in ("SPIKE", "SLIDE"):
            assert by_ticker[name].score == \
                pytest.approx(EXPECTED_SCORE[profile][name])

    def test_the_ordering_is_a_strict_REVERSAL_not_a_near_tie(self):
        """A flip decided in the fifth decimal would be a tie-break in
        disguise. Both margins are ~18%, so the reversal survives any
        reasonable change to rounding."""
        for profile, winner in EXPECTED_WINNER.items():
            loser = "SLIDE" if winner == "SPIKE" else "SPIKE"
            ratio = EXPECTED_SCORE[profile][winner] / EXPECTED_SCORE[profile][loser]
            assert ratio > 1.15, f"{profile}: margin only {ratio:.4f}"

    def test_BOTH_names_are_in_the_leadership_set_under_both_profiles(self):
        """The flip has to be an ORDERING difference, not one name dropping out
        of contention. With two eligible securities the leadership floor of 25
        caps at the population, so both compete under both profiles."""
        for profile in VOLATILITY_PROFILES:
            cfg = WealthCoreConfig(volatility_profile=profile)
            scored = score_universe(bars(), cfg)
            assert all(s.in_top_decile for s in scored)
            assert all(s.qualified for s in scored)


# ── 4. the PORTFOLIO DECISION differs — the point of the file ───────────────

def _state_with_one_vacancy() -> PortfolioState:
    """A book already constructed, holding one unrelated name, with exactly one
    free slot.

    `initialized` must be True or `decide` is in its opening and fills EVERY
    free slot, admitting both securities and dissolving the choice. Seating a
    real holding is how that state is reached honestly, rather than by setting
    the flag on an empty book.
    """
    st = PortfolioState.fresh(1_000_000.0, n_slots=2)
    st.slots[1].occupied_by = "SEC_INCUMBENT"
    st.episodes[1] = HoldingEpisode(
        security_id="SEC_INCUMBENT", ticker="INCUM", issuer_id="ISSUER_INCUM",
        slot_id=1, signal_date="2026-01-01", entry_date="2026-01-02",
        entry_raw_open=50.0, entry_split_adjusted_price=50.0,
        initial_shares=100, current_shares=100,
        episode_peak_split_adjusted_close=50.0, market_sessions_held=10)
    st.initialized = True
    return st


def _marks() -> dict[str, Mark]:
    m = {sid: Mark(sid, MarkStatus.CURRENT, raw_mark_close=SERIES[n][-1])
         for n, sid in SEC.items()}
    m["SEC_INCUMBENT"] = Mark("SEC_INCUMBENT", MarkStatus.CURRENT,
                              raw_mark_close=50.0)
    return m


class TestTheSECURITY_ACTUALLY_ADMITTED_Differs:
    """The rung the other two levels cannot reach: a profile that is accepted,
    hashed and then ignored downstream passes every arithmetic test in
    test_signals.py and every hash in the golden fixture. It fails here."""

    @pytest.mark.parametrize("profile", VOLATILITY_PROFILES)
    def test_the_admitted_security_is_the_expected_one(self, profile):
        st = _state_with_one_vacancy()
        d = decide(session="2026-08-06", state=st, bars=bars(), marks=_marks(),
                   cfg=WealthCoreConfig(volatility_profile=profile),
                   strategy_id="stocker_wealth_core_v1", strategy_version=1)
        opened = [o for o in d.operations
                  if o.operation is Operation.OPEN_SLOT_POSITION]
        assert len(opened) == 1, "exactly one vacancy, so exactly one admission"
        assert opened[0].ticker == EXPECTED_WINNER[profile]
        assert opened[0].reason is Reason.ENTRY_DURABLE_RANK
        assert opened[0].slot_id == 0

    def test_THE_TWO_PROFILES_BUY_DIFFERENT_SECURITIES(self):
        """Stated as one assertion, because this is the invariant the file
        exists to hold: switching the profile must change a portfolio
        decision, not merely a recorded number."""
        bought = {}
        for profile in VOLATILITY_PROFILES:
            st = _state_with_one_vacancy()
            d = decide(session="2026-08-06", state=st, bars=bars(),
                       marks=_marks(),
                       cfg=WealthCoreConfig(volatility_profile=profile),
                       strategy_id="stocker_wealth_core_v1", strategy_version=1)
            bought[profile] = next(
                o.ticker for o in d.operations
                if o.operation is Operation.OPEN_SLOT_POSITION)
        assert bought[SIMPLE_RETURNS_V1] == "SLIDE"
        assert bought[LOG_RETURNS_CERTIFIED_V1] == "SPIKE"
        assert len(set(bought.values())) == 2, (
            "the two profiles bought the same security — either the profile is "
            "not reaching score_universe, or this scenario has stopped "
            "discriminating and is no longer testing anything")

    def test_the_loser_is_recorded_as_considered_rather_than_absent(self):
        """Both securities must appear in the candidate audit under both
        profiles. A name that vanished from the audit would make the admission
        difference look like an ordering flip when it was really a scoring
        failure."""
        for profile in VOLATILITY_PROFILES:
            st = _state_with_one_vacancy()
            d = decide(session="2026-08-06", state=st, bars=bars(),
                       marks=_marks(),
                       cfg=WealthCoreConfig(volatility_profile=profile),
                       strategy_id="stocker_wealth_core_v1", strategy_version=1)
            assert {c.ticker for c in d.candidates} == {"SPIKE", "SLIDE"}
            assert all(c.score is not None for c in d.candidates)


# ── 5. the result stays attributable to the formula that produced it ────────

class TestTheProfileIsInTheConfigHash:

    def test_the_two_profiles_hash_differently(self):
        """Without this a run scored under one formula is indistinguishable
        from a run scored under the other, and every historical result becomes
        unattributable — the reason the formula was never edited in place."""
        a = WealthCoreConfig(volatility_profile=SIMPLE_RETURNS_V1)
        b = WealthCoreConfig(volatility_profile=LOG_RETURNS_CERTIFIED_V1)
        assert a.config_hash() != b.config_hash()

    def test_the_decision_carries_that_hash(self):
        seen = set()
        for profile in VOLATILITY_PROFILES:
            st = _state_with_one_vacancy()
            d = decide(session="2026-08-06", state=st, bars=bars(),
                       marks=_marks(),
                       cfg=WealthCoreConfig(volatility_profile=profile),
                       strategy_id="stocker_wealth_core_v1", strategy_version=1)
            seen.add(d.config_hash)
        assert len(seen) == len(VOLATILITY_PROFILES)

    def test_an_unknown_profile_is_refused_by_the_config(self):
        with pytest.raises(ValueError, match="unknown volatility_profile"):
            WealthCoreConfig(volatility_profile="log_returns_v2")


# ── 6. the guard on this file's own relevance ───────────────────────────────

def test_this_fixture_is_INDEPENDENT_of_the_certified_artefact():
    """It must not import or perturb the certified scenario. That artefact is
    re-pinned deliberately and rarely; a discriminator that moved it would make
    every future re-pin ambiguous between 'the strategy changed' and 'the
    discriminator changed'.

    Checked over IMPORTS rather than over the text, for the reason this repo has
    now hit several times: the prose EXPLAINING that the artefact is untouched
    would otherwise fail the check ENFORCING that it is untouched.
    """
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path(__file__).read_text())
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
            imported += [a.name for a in node.names]
    offenders = [m for m in imported if "golden" in m or "repin" in m]
    assert not offenders, (
        f"this file must not reach the certified artefact: {offenders}")


def test_the_formation_segment_really_is_where_the_gaps_landed():
    """The gaps must sit INSIDE t-126 … t-21. A gap that drifted into the
    skipped month would stop affecting formation volatility, both profiles
    would agree, and every test above would quietly pass for one name."""
    for name, n_gaps in (("SPIKE", SPIKE_GAPS), ("SLIDE", SLIDE_GAPS)):
        c = SERIES[name]
        seg = c[-(LONG_LOOKBACK_SESSIONS + 1):len(c) - SKIP_RECENT_SESSIONS]
        assert len(seg) == FORMATION_RETURNS + 1
        big = [1 for a, b in zip(seg, seg[1:]) if abs(math.log(b / a)) > 0.2]
        assert len(big) == n_gaps
        tail = c[len(c) - SKIP_RECENT_SESSIONS - 1:]
        assert len(set(tail)) == 1, "the skipped month must stay flat"
