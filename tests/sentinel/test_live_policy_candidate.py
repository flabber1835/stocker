"""Generated offline restrictions: no broker, configuration or order authority."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext

import pytest
from pydantic import ValidationError

from sentinel.execution import live_policy_candidate as candidate
from sentinel.execution.live_funding import FundingEvidence
from sentinel.execution.native_readonly import ExecutionSubject
from sentinel.trading_environment import TradingEnvironment

UTC = timezone.utc
NOW = datetime(2026, 10, 26, 13, 31, tzinfo=UTC)
DAY = NOW.date()
ACCOUNT = "11111111-1111-1111-1111-111111111111"
KEY = "sntl-0123456789abcdef0123"
SECOND = "sntl-0123456789abcdef0124"


def subject(**changes):
    data = dict(deployment_id="offline-only", account_id=ACCOUNT,
                takeover_epoch=1, environment=TradingEnvironment.LIVE,
                base_url="https://api.alpaca.markets")
    data.update(changes)
    return ExecutionSubject(**data)


def policy(**changes):
    data = dict(subject=subject(), issued_at=NOW - timedelta(minutes=1),
                expires_at=NOW + timedelta(hours=1), trading_day=DAY,
                max_capital="10000", max_order_principal="1000",
                max_daily_buy_commitment="3000", max_buy_premium_bps=100)
    data.update(changes)
    return candidate.PolicyCandidate(**data)


def terms(**changes):
    data = dict(subject=subject(), command_key=KEY, trading_day=DAY,
                quantity="10", limit_price="10.10", reference_close="10",
                reference_session=date(2026, 10, 23))
    data.update(changes)
    return candidate.BuyTermsCandidate(**data)


def fill(**changes):
    data = dict(subject=subject(), command_key=KEY, activity_id="activity-1",
                executed_at=NOW - timedelta(seconds=1), quantity="4", price="10")
    data.update(changes)
    return candidate.FillCandidate(**data)


def commitment(**changes):
    data = dict(terms=terms(), outcome="OPEN", fills=())
    data.update(changes)
    return candidate.CommitmentCandidate(**data)


def funding(**changes):
    data = dict(subject=subject(), observed_at=NOW, cash="10000", buying_power="10000",
                multiplier="1", status="ACTIVE", trading_blocked=False,
                account_blocked=False, trade_suspended_by_user=False,
                settled_cash="10000", reserved_cash="0",
                settlement_source="simulation/settled-v1",
                reservations_source="simulation/reservations-v1",
                provenance="SIMULATION_ONLY")
    data.update(changes)
    return FundingEvidence(**data)


def account(**changes):
    data = dict(funding=funding(), current_long_value="0", short_market_value="0",
                all_positions_valued=True, commitments=())
    data.update(changes)
    return candidate.AccountCandidate(**data)


def assess(p=None, a=None, requested=None, now=NOW):
    return candidate.assess_policy(p or policy(), a or account(), requested or terms(), now=now)


def assert_deferred(result, reason):
    assert result.status == "DEFERRED"
    assert reason in result.reasons


def test_simulated_fit_never_confers_live_or_money_authority():
    result = assess()
    assert result.status == "SIMULATION_WITHIN_LIMITS"
    assert result.candidate_additional_principal == Decimal("101")
    assert result.real_spendable_budget == 0
    assert result.order_authority == "NONE"
    assert result.live_transport_enabled is False
    assert result.native_settlement == "NOT_PROVEN"


@pytest.mark.parametrize("field,value", [
    ("real_spendable_budget", "1"), ("order_authority", "LIVE"),
    ("live_transport_enabled", True), ("native_settlement", "PROVEN"),
])
def test_assessment_cannot_be_constructed_with_authority(field, value):
    data = assess().model_dump()
    data[field] = value
    with pytest.raises(ValidationError):
        candidate.PolicyAssessment(**data)


def test_native_looking_funding_remains_deferred():
    assert_deferred(assess(a=account(funding=funding(provenance="NATIVE"))),
                    "NATIVE_SETTLEMENT_AND_RESERVATIONS_NOT_QUALIFIED")


@pytest.mark.parametrize("change", [
    {"account_id": "22222222-2222-2222-2222-222222222222"},
    {"deployment_id": "another-deployment"}, {"takeover_epoch": 2},
    {"environment": TradingEnvironment.PAPER, "base_url": "https://paper-api.alpaca.markets"},
])
def test_requested_subject_is_exact_even_if_native_uuid_is_identical(change):
    assert_deferred(assess(requested=terms(subject=subject(**change))), "SUBJECT_MISMATCH")


def test_policy_itself_cannot_be_paper():
    with pytest.raises(ValidationError):
        policy(subject=subject(environment=TradingEnvironment.PAPER,
                               base_url="https://paper-api.alpaca.markets"))


@pytest.mark.parametrize("origin", [
    "http://api.alpaca.markets", "https://api.alpaca.markets/",
    "https://api.alpaca.markets:443", "https://api.alpaca.markets/v2",
    "https://user:pass@api.alpaca.markets", "https://api.alpaca.markets.evil.test",
    "https://API.ALPACA.MARKETS", "https://api.alpaca.markets?paper=1",
])
def test_alternate_origins_refuse_canonical_subject(origin):
    with pytest.raises(ValidationError):
        subject(base_url=origin)


@pytest.mark.parametrize("change", [
    {"issued_at": NOW + timedelta(seconds=1)}, {"expires_at": NOW},
    {"trading_day": DAY - timedelta(days=1)},
])
def test_policy_clock_and_day_defer(change):
    code = "POLICY_DAY_MISMATCH" if "trading_day" in change else "POLICY_NOT_CURRENT"
    assert_deferred(assess(p=policy(**change)), code)


@pytest.mark.parametrize("change", [
    {"expires_at": NOW - timedelta(minutes=1)},
    {"expires_at": NOW + timedelta(days=2)},
    {"issued_at": NOW.replace(tzinfo=None)}, {"max_buy_premium_bps": 101},
    {"max_buy_premium_bps": True}, {"max_capital": "0"},
    {"max_order_principal": "-1"}, {"max_daily_buy_commitment": "NaN"},
])
def test_policy_construction_bounds(change):
    with pytest.raises(ValidationError):
        policy(**change)


@pytest.mark.parametrize("age", [-1, 31])
def test_fresh_account_evidence_required(age):
    assert_deferred(assess(a=account(funding=funding(observed_at=NOW - timedelta(seconds=age)))),
                    "STALE_OR_FUTURE_EVIDENCE")


@pytest.mark.parametrize("field,value,code", [
    ("multiplier", "2", "UNLEVERED_ACCOUNT_UNPROVEN"),
    ("status", "BLOCKED", "ACCOUNT_UNAVAILABLE"),
    ("trading_blocked", True, "ACCOUNT_UNAVAILABLE"),
    ("account_blocked", True, "ACCOUNT_UNAVAILABLE"),
    ("trade_suspended_by_user", True, "ACCOUNT_UNAVAILABLE"),
    ("settled_cash", None, "SETTLEMENT_OR_RESERVATIONS_MISSING"),
    ("reserved_cash", None, "SETTLEMENT_OR_RESERVATIONS_MISSING"),
    ("cash", "-1", "NEGATIVE_FUNDING_EVIDENCE"),
    ("settlement_source", "claimed-native", "SIMULATION_PROVENANCE_MISSING"),
])
def test_funding_guards_are_reused(field, value, code):
    assert_deferred(assess(a=account(funding=funding(**{field: value}))), code)


@pytest.mark.parametrize("change,code", [
    ({"short_market_value": "1"}, "SHORT_POSITION_REFUSED"),
    ({"all_positions_valued": False}, "POSITION_VALUATION_INCOMPLETE"),
])
def test_short_or_unpriced_received_security_cannot_fit_by_omission(change, code):
    assert_deferred(assess(a=account(**change)), code)


def test_order_cap_daily_cap_and_capital_are_independent():
    assert_deferred(assess(p=policy(max_order_principal="100")), "ORDER_LIMIT_EXCEEDED")
    assert_deferred(assess(p=policy(max_daily_buy_commitment="100")), "DAILY_LIMIT_EXCEEDED")
    assert_deferred(assess(p=policy(max_capital="100")), "CAPITAL_LIMIT_EXCEEDED")


def test_buy_premium_stays_at_most_owner_one_percent():
    assert assess().status == "SIMULATION_WITHIN_LIMITS"
    assert_deferred(assess(requested=terms(limit_price="10.1000000001")), "BUY_PREMIUM_EXCEEDED")
    assert_deferred(assess(p=policy(max_buy_premium_bps=0)), "BUY_PREMIUM_EXCEEDED")


def test_cash_and_settled_cash_are_not_interchangeable():
    assert_deferred(assess(a=account(funding=funding(settled_cash="100"))),
                    "SETTLED_UNRESERVED_FUNDS_INSUFFICIENT")


def test_partial_fill_reduces_reservation_without_double_daily_count():
    existing = commitment(fills=(fill(), fill()))
    result = assess(a=account(funding=funding(reserved_cash="60.60"),
                            current_long_value="40", commitments=(existing, existing)),
                    requested=terms(command_key=SECOND))
    assert result.status == "SIMULATION_WITHIN_LIMITS"
    assert result.existing_reservations == Decimal("60.60")
    assert result.daily_commitment == Decimal("201.60")  # 40 + 60.6 + 101
    assert result.candidate_additional_principal == Decimal("101")


def test_recovery_same_command_preserves_original_reservation_and_daily_total():
    existing = commitment(fills=(fill(),), outcome="UNKNOWN")
    a = account(funding=funding(reserved_cash="60.60"), current_long_value="40",
                commitments=(existing,))
    result = assess(a=a)
    recovered = candidate.AccountCandidate.model_validate_json(a.model_dump_json())
    assert assess(a=recovered) == result
    assert result.status == "SIMULATION_WITHIN_LIMITS"
    assert result.candidate_additional_principal == 0
    assert result.existing_reservations == Decimal("60.60")
    assert result.daily_commitment == Decimal("100.60")


def test_unknown_reservation_cannot_be_spent_by_second_command():
    existing = commitment(outcome="UNKNOWN")
    a = account(funding=funding(cash="201", buying_power="201", settled_cash="201",
                               reserved_cash="101"), commitments=(existing,))
    assert_deferred(assess(a=a, requested=terms(command_key=SECOND)),
                    "SETTLED_UNRESERVED_FUNDS_INSUFFICIENT")


def test_incomplete_reservation_inventory_defers():
    assert_deferred(assess(a=account(commitments=(commitment(outcome="UNKNOWN"),))),
                    "RESERVATION_EVIDENCE_INCOMPLETE")


def test_extra_unexplained_reserve_is_not_released_for_capital():
    a = account(funding=funding(reserved_cash="9900"))
    assert_deferred(assess(a=a), "CAPITAL_LIMIT_EXCEEDED")


def test_completed_fill_has_no_reservation_but_counts_actual_daily_spend():
    existing = commitment(outcome="FILLED", fills=(fill(quantity="10", price="9.99"),))
    result = assess(a=account(current_long_value="99.90", commitments=(existing,)))
    assert result.status == "SIMULATION_WITHIN_LIMITS"
    assert result.existing_reservations == 0
    assert result.daily_commitment == Decimal("99.90")


def test_fractional_partial_native_fills_do_not_change_whole_original_terms():
    existing = commitment(fills=(fill(quantity="0.125", price="10.01"),))
    result = assess(a=account(funding=funding(reserved_cash="99.7375"),
                            current_long_value="1.25125", commitments=(existing,)))
    assert result.status == "SIMULATION_WITHIN_LIMITS"
    assert result.daily_commitment == Decimal("100.98875")


@pytest.mark.parametrize("change", [
    {"quantity": "0.5"}, {"quantity": 10}, {"quantity": True},
    {"limit_price": 10.0}, {"limit_price": "Infinity"},
    {"reference_session": DAY}, {"side": "sell"}, {"time_in_force": "gtc"},
    {"command_key": "new-key"}, {"quantity": "1e1000"},
])
def test_original_terms_are_bounded_exact_whole_share_buy_day(change):
    with pytest.raises(ValidationError):
        terms(**change)


def test_changed_original_terms_do_not_acquire_a_second_reservation():
    result = assess(a=account(funding=funding(reserved_cash="101"),
                              commitments=(commitment(),)), requested=terms(quantity="11"))
    assert_deferred(result, "CHANGED_ORIGINAL_TERMS")
    assert result.candidate_additional_principal == 0


def test_conflicting_command_snapshots_refuse_instead_of_combining_progress():
    a = account(funding=funding(reserved_cash="101"),
                commitments=(commitment(), commitment(fills=(fill(),))))
    assert_deferred(assess(a=a), "CONFLICTING_COMMAND_SNAPSHOT")


def test_duplicate_activity_with_changed_economics_refuses():
    existing = commitment(fills=(fill(), fill(price="9.99")))
    a = account(funding=funding(reserved_cash="101"), commitments=(existing,))
    assert_deferred(assess(a=a), "CONFLICTING_FILL_IDENTITY")


def test_activity_identity_cannot_move_between_commands():
    a = account(funding=funding(reserved_cash="202"),
                commitments=(commitment(fills=(fill(),)),
                             commitment(terms=terms(command_key=SECOND), fills=(fill(),))))
    assert_deferred(assess(a=a), "REUSED_FILL_IDENTITY")


def test_fill_cannot_be_attached_to_another_original_command():
    a = account(funding=funding(reserved_cash="101"),
                commitments=(commitment(fills=(fill(command_key=SECOND),)),))
    assert_deferred(assess(a=a), "FILL_COMMAND_MISMATCH")


@pytest.mark.parametrize("changes,code", [
    ({"quantity": "11"}, "OVERFILLED_COMMAND"),
    ({"price": "10.11"}, "FILL_PRICE_EXCEEDS_LIMIT"),
    ({"executed_at": NOW + timedelta(seconds=1)}, "FILL_CLOCK_INVALID"),
    ({"executed_at": NOW - timedelta(days=1)}, "FILL_CLOCK_INVALID"),
    ({"subject": subject(takeover_epoch=2)}, "SUBJECT_MISMATCH"),
])
def test_fill_integrity_refusals(changes, code):
    a = account(funding=funding(reserved_cash="101"),
                commitments=(commitment(fills=(fill(**changes),)),))
    assert_deferred(assess(a=a), code)


def test_filled_label_does_not_release_unfilled_quantity():
    a = account(funding=funding(reserved_cash="101"),
                commitments=(commitment(outcome="FILLED", fills=(fill(),)),))
    result = assess(a=a)
    assert_deferred(result, "FILLED_WITH_REMAINING_QUANTITY")
    assert result.existing_reservations == Decimal("60.60")


@pytest.mark.parametrize("outcome", ["CANCELED", "EXPIRED", "FAILED"])
def test_unverified_terminal_labels_cannot_release_a_reservation(outcome):
    with pytest.raises(ValidationError):
        commitment(outcome=outcome)


def test_prior_day_fills_are_not_current_daily_spending_but_unresolved_reserve_is():
    prior_day = DAY - timedelta(days=3)
    existing = commitment(terms=terms(trading_day=prior_day, reference_session=prior_day - timedelta(days=1)),
                          fills=(fill(executed_at=NOW - timedelta(days=3)),), outcome="UNKNOWN")
    result = assess(a=account(funding=funding(reserved_cash="60.60"),
                            commitments=(existing,)), requested=terms(command_key=SECOND))
    assert result.status == "SIMULATION_WITHIN_LIMITS"
    assert result.daily_commitment == Decimal("161.60")


def test_decimal_context_cannot_change_restriction_arithmetic():
    a = account(funding=funding(reserved_cash="99.7375"), current_long_value="1.25125",
                commitments=(commitment(fills=(fill(quantity="0.125", price="10.01"),)),))
    normal = assess(a=a)
    with localcontext() as context:
        context.prec = 2
        assert assess(a=a) == normal


def test_model_copy_cannot_bypass_policy_or_terms_validation():
    with pytest.raises(ValidationError):
        assess(p=policy().model_copy(update={"max_capital": Decimal("-1")}))
    with pytest.raises(ValidationError):
        assess(requested=terms().model_copy(update={"quantity": Decimal("0.5")}))


def test_subject_guard_removal_is_observably_caught(monkeypatch):
    request = terms(subject=subject(takeover_epoch=2))
    assert_deferred(assess(requested=request), "SUBJECT_MISMATCH")
    monkeypatch.setattr(candidate, "_subject_matches", lambda *_: True)
    with pytest.raises(AssertionError):
        assert_deferred(assess(requested=request), "SUBJECT_MISMATCH")


def test_capital_guard_removal_is_observably_caught(monkeypatch):
    p = policy(max_capital="100")
    assert_deferred(assess(p=p), "CAPITAL_LIMIT_EXCEEDED")
    monkeypatch.setattr(candidate, "_capital_fits", lambda *_: True)
    with pytest.raises(AssertionError):
        assert_deferred(assess(p=p), "CAPITAL_LIMIT_EXCEEDED")
