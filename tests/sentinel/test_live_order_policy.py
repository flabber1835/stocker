"""LIVE pre-submit limits and settlement consumer, exercised with generated keys."""
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal, localcontext
import inspect

import pytest

from sentinel.authority.model import AuthorityRefused
from sentinel.execution import live_order_policy as policy
from sentinel.execution.contract import BrokerAccountIdentity, BrokerPosition, OrderTerms, Side
from sentinel.execution.identity import CommandIdentity
from sentinel.execution.live_settlement import LiveFundingAdmission
from sentinel.execution.states import CommandState
from tests.sentinel.live_order_fixtures import (
    DAY, NOW, REFERENCE_SESSION, command, funding, order_fixture, resigned_authority,
)


def assess(fixture=None, *, receipt=True, **changes):
    fixture = fixture or order_fixture()
    arguments = dict(admission=fixture.admission, now=NOW, effective_session=DAY,
        request=fixture.request, account=fixture.account, account_observed_at=NOW,
        positions=fixture.positions, commitments=fixture.commitments,
        reference_close=Decimal(10), reference_session=REFERENCE_SESSION,
        funding=funding(fixture).admission if receipt is True else receipt)
    arguments.update(changes)
    return policy.require_live_order(**arguments)


def refused(code, fixture=None, **changes):
    with pytest.raises(policy.LiveOrderRefused, match=code):
        assess(fixture, **changes)


def test_separately_signed_synthetic_funding_consumes_original_promise():
    result = assess()
    assert result.allowed is True
    assert result.outstanding_buy_commitment == Decimal(101)
    assert result.daily_buy_commitment == Decimal(101)
    assert result.remaining_settled_cash == Decimal(899)
    assert result.remaining_capital == Decimal(9899)


def test_missing_native_acceptance_defers_and_dict_cannot_self_qualify():
    with pytest.raises(policy.LiveOrderDeferred, match="SETTLEMENT_NOT_QUALIFIED"):
        assess(receipt=None)
    refused("TYPED_FUNDING", receipt={"provenance": "NATIVE", "settled_cash": "1000000"})


def test_unknown_and_partial_orders_reserve_their_original_maximum():
    fixture = order_fixture()
    uncertain = command(fixture, security="OTHER", quantity=Decimal(20),
        state=CommandState.UNKNOWN, filled_quantity=Decimal(4), filled_average_price=Decimal(10),
        created_at=NOW - timedelta(days=3))
    fixture.commitments += (uncertain,)
    result = assess(fixture, receipt=funding(fixture, provider_reserved_cash="50").admission)
    assert result.outstanding_buy_commitment == Decimal(303)
    assert result.daily_buy_commitment == Decimal(303)
    assert result.remaining_settled_cash == Decimal(647)


def test_same_day_cancel_does_not_replenish_daily_commitment():
    fixture = order_fixture()
    cancelled = command(fixture, security="OTHER", quantity=Decimal(20), state=CommandState.CANCELLED)
    fixture.commitments += (cancelled,)
    result = assess(fixture)
    assert result.outstanding_buy_commitment == 101
    assert result.daily_buy_commitment == 303
    refused("DAILY_COMMITMENT", fixture,
            admission=resigned_authority(fixture, max_daily_buy_commitment="302"))


def test_old_filled_or_cancelled_buy_does_not_count_again_today():
    fixture = order_fixture()
    fixture.commitments += (command(fixture, security="OLD", state=CommandState.CANCELLED,
                                   created_at=NOW-timedelta(days=3)),)
    assert assess(fixture).daily_buy_commitment == 101


@pytest.mark.parametrize("limit,amount,code", [
    ("max_order_principal", "100", "ORDER_LIMIT"),
    ("max_daily_buy_commitment", "100", "DAILY_COMMITMENT"),
    ("max_capital", "100", "CAPITAL_LIMIT"),
])
def test_signed_limits_restrict_even_otherwise_valid_requests(limit, amount, code):
    fixture = order_fixture()
    refused(code, fixture, admission=resigned_authority(fixture, **{limit: amount}))


def test_signed_qualified_valuation_consumes_capital_without_caller_boolean():
    fixture = order_fixture()
    refused("CAPITAL_LIMIT", fixture, receipt=funding(fixture, long_market_value="9900").admission)
    with pytest.raises(TypeError):
        assess(fixture, current_long_value=Decimal(0), all_positions_valued=True)


def test_cash_buying_power_and_sale_proceeds_never_supply_settlement():
    fixture = order_fixture()
    fixture.account = replace(fixture.account, cash=Decimal(1000000), buying_power=Decimal(1000000))
    sale = command(fixture, security="SOLD", side=Side.SELL, state=CommandState.FILLED,
                   filled_quantity=Decimal(10), filled_average_price=Decimal(100))
    fixture.commitments += (sale,)
    with pytest.raises(policy.LiveOrderDeferred, match="SETTLED_UNRESERVED"):
        assess(fixture, receipt=funding(fixture, settled_cash="100").admission)


def test_provider_holds_and_journal_promises_are_not_assumed_to_overlap():
    fixture = order_fixture()
    with pytest.raises(policy.LiveOrderDeferred, match="SETTLED_UNRESERVED"):
        assess(fixture, receipt=funding(fixture, settled_cash="200", provider_reserved_cash="100").admission)


def test_premium_respects_both_hard_100bps_and_tighter_signed_limit():
    fixture = order_fixture()
    requested = replace(fixture.request, order_terms=OrderTerms("limit", "day", Decimal("10.11")))
    refused("PREMIUM", fixture, request=requested, commitments=(requested,))
    refused("PREMIUM", fixture, admission=resigned_authority(fixture, max_buy_premium_bps=0))


def test_split_adjusted_raw_price_comparison_stays_exact_for_nonterminating_ratio():
    fixture = order_fixture()
    good = replace(fixture.request, order_terms=OrderTerms("limit", "day", Decimal("6.73")))
    assert assess(fixture, request=good, commitments=(good,), reference_unit_factor="3/2").allowed
    bad = replace(good, order_terms=OrderTerms("limit", "day", Decimal("6.74")))
    refused("PREMIUM", fixture, request=bad, commitments=(bad,), reference_unit_factor="3/2")
    for factor in ("0", "-1", "2/2", "1.5", 2):
        refused("SHARE_FACTOR", fixture, reference_unit_factor=factor)


@pytest.mark.parametrize("reference", [DAY, DAY+timedelta(days=1), REFERENCE_SESSION-timedelta(days=1)])
def test_only_actual_preceding_exchange_close_can_anchor_price(reference):
    refused("PRECEDING_CLOSE", reference_session=reference)


def test_live_does_not_accept_market_buy_or_fractional_shares():
    fixture = order_fixture()
    market = replace(fixture.request, order_terms=OrderTerms())
    refused("PROTECTED_LIMIT_DAY", fixture, request=market, commitments=(market,))
    fractional = replace(fixture.request, quantity=Decimal("1.5"))
    refused("WHOLE_SHARES", fixture, request=fractional, commitments=(fractional,))


def test_request_must_equal_actual_original_pending_journal_record():
    fixture = order_fixture()
    refused("NOT_IN_JOURNAL", fixture, commitments=())
    changed = replace(fixture.request, quantity=Decimal(11))
    refused("CHANGED_ORIGINAL", fixture, request=changed)
    refused("CONFLICTING_COMMAND", fixture, commitments=(fixture.request, changed))
    terminal = replace(fixture.request, state=CommandState.CANCELLED)
    refused("DURABLE_PENDING", fixture, request=terminal, commitments=(terminal,))


def test_same_uuid_in_paper_cannot_supply_account_or_commands():
    fixture = order_fixture()
    account = replace(fixture.account, identity=BrokerAccountIdentity("alpaca", fixture.subject.account_id))
    refused("ACCOUNT_SUBJECT", fixture, account=account)
    paper = replace(fixture.request, identity=CommandIdentity(
        replace(fixture.request.identity.deployment, broker="alpaca"), "plan", "SEC"))
    refused("COMMAND_SUBJECT", fixture, request=paper, commitments=(paper,))


@pytest.mark.parametrize("observed", [NOW-timedelta(seconds=31), NOW+timedelta(microseconds=1), NOW.replace(tzinfo=None)])
def test_stale_or_future_or_unzoned_account_read_defers(observed):
    with pytest.raises(policy.LiveOrderDeferred, match="ACCOUNT_NOT_CURRENT"):
        assess(account_observed_at=observed)


@pytest.mark.parametrize("changes", [
    {"multiplier": Decimal(2)}, {"trading_blocked": True},
    {"account_blocked": True}, {"trade_suspended_by_user": True}, {"status": "CLOSED"},
])
def test_unavailable_or_leveraged_accounts_refuse(changes):
    fixture = order_fixture()
    refused("UNAVAILABLE_OR_LEVERAGED", fixture, account=replace(fixture.account, **changes))


def sell_fixture():
    fixture = order_fixture()
    fixture.request = command(fixture, side=Side.SELL)
    fixture.commitments = (fixture.request,)
    fixture.positions = (BrokerPosition(fixture.request.instrument, Decimal(20)),)
    return fixture


def test_valid_reduction_needs_no_buy_funding_premium_or_capital_budget():
    fixture = sell_fixture()
    result = assess(fixture, receipt=None, reference_close=None, reference_session=None,
        admission=resigned_authority(fixture, max_capital="1", max_order_principal="1", max_daily_buy_commitment="1"))
    assert result.allowed and result.side is Side.SELL
    assert result.funding_receipt_sha256 is None


def test_unknown_other_sell_blocks_overselling_unreserved_holdings():
    fixture = sell_fixture()
    other = command(fixture, side=Side.SELL, revision=1, quantity=Decimal(11), state=CommandState.UNKNOWN)
    fixture.commitments += (other,)
    refused("SELL_EXCEEDS_UNRESERVED", fixture, receipt=None)


def test_partial_current_sell_uses_its_remaining_quantity_with_same_original_key():
    fixture = sell_fixture()
    fixture.request = replace(fixture.request, filled_quantity=Decimal(5),
        filled_average_price=Decimal(10), state=CommandState.PARTIALLY_FILLED)
    fixture.commitments = (fixture.request,)
    fixture.positions = (BrokerPosition(fixture.request.instrument, Decimal(5)),)
    assert assess(fixture, receipt=None).allowed


def test_changed_native_asset_and_short_positions_refuse():
    fixture = sell_fixture()
    changed = replace(fixture.positions[0], instrument=replace(fixture.request.instrument, broker_id="other-native"))
    refused("INSTRUMENT_NOT_HELD", fixture, positions=(changed,), receipt=None)
    short = BrokerPosition(fixture.request.instrument, Decimal(-1))
    refused("MONETARY", fixture, positions=(short,), receipt=None)


def test_fresh_authority_revocation_is_not_cached():
    fixture = order_fixture()
    revoked = set()
    admission = replace(fixture.admission, revoked_certificate_sha256=lambda: revoked)
    result = assess(fixture, admission=admission)
    revoked.add(result.certificate_sha256)
    with pytest.raises(AuthorityRefused, match="revoked"):
        assess(fixture, admission=admission)


def test_limit_arithmetic_does_not_depend_on_decimal_context():
    with localcontext() as context:
        context.prec = 2
        result = assess()
    assert result.outstanding_buy_commitment == 101
    assert result.remaining_settled_cash == 899


def test_unknown_original_reservation_guard_has_behavioral_falsifier(monkeypatch):
    source = inspect.getsource(policy.require_live_order)
    needle = "outstanding += original_principal"
    assert source.count(needle) == 1
    changed = source.replace(needle, "outstanding += Fraction(0)")
    namespace = {}
    exec(compile(changed, "live-reservation-falsifier", "exec"), policy.__dict__, namespace)
    monkeypatch.setattr(policy, "require_live_order", namespace["require_live_order"])
    with pytest.raises(AssertionError):
        test_unknown_and_partial_orders_reserve_their_original_maximum()


def test_sale_proceeds_cannot_replace_signed_settlement_guard_falsifier(monkeypatch):
    source = inspect.getsource(policy.require_live_order)
    needle = "Fraction(settled.settled_cash)"
    assert source.count(needle) == 1
    changed = source.replace(needle, "Fraction(account.cash)")
    namespace = {}
    exec(compile(changed, "live-settlement-falsifier", "exec"), policy.__dict__, namespace)
    monkeypatch.setattr(policy, "require_live_order", namespace["require_live_order"])
    with pytest.raises(pytest.fail.Exception):
        test_cash_buying_power_and_sale_proceeds_never_supply_settlement()
