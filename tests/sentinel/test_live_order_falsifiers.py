"""Behavioral guard-removal controls for real-money pre-transport boundaries."""
import inspect
from datetime import timedelta

import pytest

from sentinel.execution import live_order_policy as policy
from tests.sentinel import test_live_order_policy as regression
from tests.sentinel.live_order_fixtures import NOW, funding, order_fixture


def test_assessment_expires_at_the_earliest_original_observation_boundary():
    fixture = order_fixture()
    result = regression.assess(fixture, receipt=funding(fixture).admission)
    assert result.valid_until == NOW + timedelta(seconds=20)
    result = regression.assess(fixture, receipt=funding(fixture).admission,
        account_observed_at=NOW - timedelta(seconds=25))
    assert result.valid_until == NOW + timedelta(seconds=5)
    fixture = regression.sell_fixture()
    assert regression.assess(fixture, receipt=None).valid_until == NOW + timedelta(seconds=30)


@pytest.mark.parametrize("needle,check", [
    ("if principal > Fraction(limits.max_order_principal):", "order"),
    ("if daily > Fraction(limits.max_daily_buy_commitment):", "daily"),
    ("if capital < 0:", "capital"),
    ("if price > reference / factor * Fraction(10000 + limits.max_buy_premium_bps, 10000):", "premium"),
    ("if Fraction(request.remaining) + other_reservations > Fraction(position.quantity):", "sell"),
    ("if not _same_original(original, request) or original != request:", "original"),
])
def test_removed_financial_guards_are_detected_by_behavior(monkeypatch, needle, check):
    source = inspect.getsource(policy.require_live_order)
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, "if False:"), "live-order-guard-falsifier", "exec"),
         policy.__dict__, namespace)
    monkeypatch.setattr(policy, "require_live_order", namespace["require_live_order"])
    with pytest.raises((pytest.fail.Exception, AssertionError)):
        if check == "order":
            regression.test_signed_limits_restrict_even_otherwise_valid_requests(
                "max_order_principal", "100", "ORDER_LIMIT")
        elif check == "daily":
            regression.test_signed_limits_restrict_even_otherwise_valid_requests(
                "max_daily_buy_commitment", "100", "DAILY_COMMITMENT")
        elif check == "capital":
            regression.test_signed_limits_restrict_even_otherwise_valid_requests(
                "max_capital", "100", "CAPITAL_LIMIT")
        elif check == "premium":
            regression.test_premium_respects_both_hard_100bps_and_tighter_signed_limit()
        elif check == "sell":
            regression.test_unknown_other_sell_blocks_overselling_unreserved_holdings()
        else:
            regression.test_request_must_equal_actual_original_pending_journal_record()


def test_whole_share_guard_removal_is_detected(monkeypatch):
    source = inspect.getsource(policy._command)
    needle = "if result.quantity != result.quantity.to_integral_value():"
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, "if False:"), "live-whole-share-falsifier", "exec"),
         policy.__dict__, namespace)
    monkeypatch.setattr(policy, "_command", namespace["_command"])
    with pytest.raises(pytest.fail.Exception):
        regression.test_live_does_not_accept_market_buy_or_fractional_shares()
