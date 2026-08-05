"""The Wealth Core execution-risk profile.

Most of these test a REFUSAL TO LIMIT, which is unusual and deliberate. The
danger with this strategy is not an unbounded trade — sizes are 4% of equity and
admissions are one per session — it is a limit inherited from a different
strategy firing in a situation where firing is the wrong answer. So the tests
below mostly assert that a sell gets through.
"""
from __future__ import annotations

import pytest

from stock_strategy_shared.wealth_core.risk_profile import (
    DEFAULT_PROFILES,
    PROFILE_NAME,
    FractionalSharePolicy,
    PartialFillPolicy,
    RiskProfileUnavailable,
    TurnoverBehavior,
    WealthCoreRiskProfile,
    aggregate_exposures,
    evaluate_entry,
    evaluate_exit,
    require_profile,
)

P = WealthCoreRiskProfile()


def entry(**kw):
    base = dict(profile=P, equity=1_000_000.0, cash=500_000.0, notional=40_000.0,
                held_positions=10, pending_reservations=0,
                entries_this_session=0)
    base.update(kw)
    return evaluate_entry(**base)


class TestStartupGate:

    def test_wealth_core_without_its_profile_fails_to_start(self):
        """Inheriting ambiguous limits is worse than having none: every check
        would pass while enforcing the wrong ones, with nothing in any log."""
        with pytest.raises(RiskProfileUnavailable) as e:
            require_profile("stateful_ownership", {"legacy_target": object()})
        assert "MAX_POSITION_PCT" in str(e.value)
        assert "turnover" in str(e.value)

    def test_an_absent_profile_map_also_fails(self):
        with pytest.raises(RiskProfileUnavailable):
            require_profile("stateful_ownership", None)

    def test_the_default_profile_satisfies_the_gate(self):
        assert require_profile("stateful_ownership", DEFAULT_PROFILES).name == \
            PROFILE_NAME

    def test_the_gate_is_not_for_the_legacy_model(self):
        with pytest.raises(ValueError):
            require_profile("target_portfolio", DEFAULT_PROFILES)


class TestTheProfileRefusesIncoherentValues:

    def test_an_exit_notional_cap_cannot_be_configured(self):
        """It would bind hardest during a drawdown — the session on which the
        most capital needs to leave."""
        with pytest.raises(ValueError) as e:
            WealthCoreRiskProfile(maximum_exit_notional_per_session=1_000_000.0)
        assert "drawdown" in str(e.value)

    def test_a_concentration_cap_below_the_entry_weight_is_refused(self):
        """It would breach on the day of entry."""
        with pytest.raises(ValueError):
            WealthCoreRiskProfile(maximum_single_security_aggregate_exposure=0.01)

    def test_the_required_fields_are_all_present(self):
        d = P.to_dict()
        for k in ("maximum_positions", "nominal_entry_weight",
                  "maximum_new_entries_per_session",
                  "maximum_total_entry_notional_per_session",
                  "maximum_exit_notional_per_session",
                  "maximum_pending_entry_reservations",
                  "maximum_single_security_aggregate_exposure",
                  "maximum_same_issuer_exposure",
                  "maximum_daily_turnover_behavior", "minimum_cash_buffer",
                  "fractional_share_policy", "partial_fill_policy"):
            assert k in d
        assert d["maximum_positions"] == 25
        assert d["nominal_entry_weight"] == 0.04
        assert d["maximum_new_entries_per_session"] == 1
        assert d["fractional_share_policy"] == \
            FractionalSharePolicy.WHOLE_SHARES_ONLY.value
        assert d["partial_fill_policy"] == PartialFillPolicy.ACCEPT_GAP_REDUCED.value


class TestExitsAreNeverBlocked:
    """The failure mode being guarded against is a book that cannot get out."""

    def test_an_exit_is_approved_regardless_of_size(self):
        assert evaluate_exit(profile=P, notional=10_000_000.0).approved

    def test_an_exit_is_exempt_from_the_turnover_cap(self):
        v = evaluate_exit(profile=P, notional=500_000.0,
                          exit_notional_this_session=5_000_000.0,
                          reason="EXIT_TRAILING_STOP")
        assert v.approved and v.detail["exempt_from_turnover_cap"] is True

    def test_a_cascade_of_trailing_stops_is_not_throttled(self):
        """The session with the most selling is a drawdown, which is exactly
        when every stop fires at once."""
        total = 0.0
        for _ in range(25):
            v = evaluate_exit(profile=P, notional=40_000.0,
                              exit_notional_this_session=total,
                              reason="EXIT_TRAILING_STOP")
            assert v.approved
            total = v.detail["exit_notional_this_session"]
        assert total == pytest.approx(1_000_000.0)

    def test_the_one_entry_per_session_limit_does_not_touch_exits(self):
        """A strategy behaviour, not a safety rail."""
        assert evaluate_exit(profile=P, notional=40_000.0).approved
        assert not entry(entries_this_session=1).approved

    def test_the_turnover_behaviour_is_exits_exempt(self):
        assert P.maximum_daily_turnover_behavior is TurnoverBehavior.EXITS_EXEMPT


class TestEntryLimits:

    def test_a_normal_entry_is_approved(self):
        assert entry().approved

    def test_pending_reservations_count_toward_the_position_cap(self):
        """A queued-but-unfilled entry is committed capital. A check that
        ignored it would approve entries the planner already committed to, and
        the two views would disagree by exactly the number in flight."""
        assert not entry(held_positions=24, pending_reservations=1).approved
        assert "MAX_POSITIONS" in entry(held_positions=24,
                                        pending_reservations=1).reasons

    def test_reservations_have_their_own_ceiling(self):
        v = entry(held_positions=1, pending_reservations=5)
        assert "MAX_PENDING_RESERVATIONS" in v.reasons

    def test_unresolved_equity_blocks_an_admission(self):
        v = entry(equity=None)
        assert not v.approved and v.reasons == ("UNRESOLVED_EQUITY",)

    def test_the_cash_buffer_is_enforced(self):
        p = WealthCoreRiskProfile(minimum_cash_buffer=100_000.0)
        v = evaluate_entry(profile=p, equity=1_000_000.0, cash=120_000.0,
                           notional=40_000.0, held_positions=1,
                           pending_reservations=0, entries_this_session=0)
        assert "MIN_CASH_BUFFER" in v.reasons


class TestTheDistinctionsThatMatter:

    def test_a_gap_reduced_entry_below_4_percent_is_still_valid(self):
        """Rejecting it would make the strategy skip exactly the names that
        ran between the decision and the fill."""
        v = entry(notional=31_000.0, is_gap_reduced=True)
        assert v.approved
        assert v.detail["gap_reduced"] is True
        assert v.detail["weight"] < P.nominal_entry_weight

    def test_a_converted_position_above_4_percent_is_not_a_breach(self):
        """A takeover is not a purchase, and there is no trim to authorise."""
        by_sec, _ = aggregate_exposures({"ACQ": 800}, {"ACQ": "P:ACQ"},
                                        {"ACQ": 100.0}, 1_000_000.0)
        assert by_sec["ACQ"] == pytest.approx(0.08)
        assert by_sec["ACQ"] > P.nominal_entry_weight
        assert by_sec["ACQ"] <= P.maximum_single_security_aggregate_exposure

    def test_the_absurdity_bound_still_exists(self):
        v = entry(aggregate_exposure_after=0.40)
        assert "MAX_SINGLE_SECURITY_EXPOSURE" in v.reasons

    def test_issuer_exposure_aggregates_across_securities(self):
        _, by_issuer = aggregate_exposures(
            {"A": 100, "B": 200}, {"A": "P:X", "B": "P:X"},
            {"A": 100.0, "B": 100.0}, 1_000_000.0)
        assert by_issuer["P:X"] == pytest.approx(0.03)

    def test_exposure_is_computed_from_AGGREGATED_share_counts(self):
        """Two predecessor lots converted into one acquirer are ONE exposure.
        Reading them per-episode reports two 4% positions where the book holds
        one 8% position — the number a concentration limit exists to catch."""
        by_sec, _ = aggregate_exposures({"ACQ": 400 + 400}, {"ACQ": "P:ACQ"},
                                        {"ACQ": 100.0}, 1_000_000.0)
        assert by_sec["ACQ"] == pytest.approx(0.08)

    def test_an_unpriced_security_is_omitted_rather_than_valued_at_zero(self):
        by_sec, _ = aggregate_exposures({"A": 100}, {"A": "P:A"}, {}, 1_000.0)
        assert by_sec == {}
