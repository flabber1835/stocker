"""Dollar execution, recovery, cancellation and share ownership boundaries."""
import asyncio
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal as D, localcontext

import pytest

from sentinel import schema
from sentinel.execution import fractional_progress as progress, fractional_sizing as sizing, journal
from sentinel.execution.contract import BrokerFill, BrokerObservation, BrokerPosition, Completeness, Side
from sentinel.execution.market_buy_policy import FRACTIONAL_MODE, MarketBuyPolicy
from sentinel.execution.states import CommandState as S
from sentinel.execution.target_reprojection import TargetProjection, TargetProjectionRefused
from tests.sentinel.test_order_terms_schema import pg, database
from tests.sentinel.test_journal_and_reconcile import AAA, DEPLOY, cmd
from tests.sentinel.test_limit_day_sizing import references
from tests.sentinel.test_market_buy_policy import MARKET_ENV
from tests.sentinel.test_limit_day_transport import broker_for
from tests.sentinel.test_issue_183_alpaca_hardening import INSTRUMENT, full_order, run
from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
from tests.v5.test_opening import case, base

NOW = datetime(2026, 8, 12, 14, 0, tzinfo=timezone.utc)


def projection(budget="1000", baseline="0"):
    return TargetProjection("plan-1", "a" * 64, date(2026, 8, 12), {}, (), {},
        {AAA.security_id: D(baseline)}, opening_sizing={"mode": FRACTIONAL_MODE,
            "purchases": {AAA.security_id: {"budget": budget, "origin": "ENTRY"}}})


def observation(held="0", orders=()):
    return BrokerObservation(observed_at=NOW, completeness=Completeness.COMPLETE,
        positions=(BrokerPosition(AAA, D(held)),) if D(held) else (), orders=orders)


def dollars(*, notional="999", filled="0", state=S.PLANNED, revision=0):
    return replace(cmd(state=state, filled=filled, revision=revision), quantity=None,
        notional=D(notional), broker_order_id="native-" + str(revision),
        filled_average_price=D(100) if D(filled) else None, created_at=NOW)


def native_fills(conn, command):
    journal.record_fills(conn, (BrokerFill(command.client_key, command.broker_order_id,
        command.filled_quantity, command.filled_average_price, NOW),))


def test_fractional_policy_has_distinct_authority_and_preserves_legacy_policy():
    selected = MarketBuyPolicy.from_env({**MARKET_ENV, "SENTINEL_PAPER_BUY_POLICY": FRACTIONAL_MODE})
    assert selected.fractional and selected.fingerprint() != MarketBuyPolicy().fingerprint()
    assert MarketBuyPolicy.from_dict(selected.to_dict()) == selected
    assert MarketBuyPolicy().to_dict()["schema"] == "sentinel.market-buy-policy/1"
    with pytest.raises(TargetProjectionRefused, match="PAPER endpoint"):
        MarketBuyPolicy.from_env({**MARKET_ENV, "SENTINEL_PAPER_BUY_POLICY": FRACTIONAL_MODE,
                                 "ALPACA_BASE_URL": "https://api.alpaca.markets"})


def test_native_notional_post_uses_dollars_and_accepts_null_qty():
    broker, http = broker_for(AssetIdAlpacaExecutionBroker,
        payload=full_order(qty=None, notional="123.45"))
    outcome = run(broker.submit(client_key="key-1", instrument=INSTRUMENT,
        side=Side.BUY, quantity=None, notional=D("123.45")))
    assert outcome.state is S.ACKNOWLEDGED
    body = http.calls[0][2]
    assert body["notional"] == "123.45" and "qty" not in body
    assert body["symbol"] == INSTRUMENT.broker_id and body["type"] == "market"
    assert body["time_in_force"] == "day" and body["extended_hours"] is False


@pytest.mark.parametrize("change", [{"notional": None}, {"notional": "124.45"}, {"qty": "1"}])
def test_contradictory_dollar_acknowledgement_never_acks(change):
    from sentinel.execution import recovery
    command = replace(dollars(notional="123.45", state=S.SEND_PENDING), instrument=INSTRUMENT)
    broker, http = broker_for(AssetIdAlpacaExecutionBroker,
        payload=full_order(**{**{"qty": None, "notional": "123.45", "client_order_id": command.client_key}, **change}))
    # This is already after transport; any malformed successful body must
    # retain UNKNOWN. No second order is permitted on absence or parse failure.
    result = run(recovery.dispatch(broker, command))
    assert result.state is S.UNKNOWN and len(http.calls) == 1


def test_entry_budget_is_independent_of_share_price_and_does_not_mutate_shadow():
    state, plan = case(entries=2)
    before = state.to_dict()
    raw = base(state, plan)
    fixed = {"through_event_seq": 0, "commands": [], "holdings": {}}
    cheap = sizing.resolve(state, plan, raw, references(plan, raw), MarketBuyPolicy(True),
        baseline=fixed, retained_targets={})
    expensive_refs = references(plan, raw, prices={"SEC-AAA": D(100000), "SEC-BBB": D(100000), "SENTINEL:BIL": D(100)})
    expensive = sizing.resolve(state, plan, raw, expensive_refs, MarketBuyPolicy(True),
        baseline=fixed, retained_targets={})
    assert cheap.opening_sizing["purchases"] == expensive.opening_sizing["purchases"]
    assert cheap.opening_sizing["purchases"]["SEC-AAA"]["budget"] == "5000"
    assert cheap.target_basket["SEC-AAA"] == 0
    assert state.to_dict() == before
    changed = dict(expensive.opening_sizing)
    changed["purchases"] = {**changed["purchases"], "SEC-AAA": {"budget": "5001", "origin": "ENTRY"}}
    with pytest.raises(TargetProjectionRefused, match="rederive"):
        sizing.validate_projection(replace(expensive, opening_sizing=changed), plan=plan)


def test_first_purchase_is_cents_with_fee_headroom_and_no_fictional_quantity(database):
    schema.ensure_schema(database)
    with localcontext() as context:
        context.prec = 3
        delta = progress.delta(database, projection=projection("123456.78"), deployment=DEPLOY,
            security_id=AAA.security_id, observation=observation())
    assert delta.quantity is None and delta.notional == D("123455.78")
    assert delta.is_increase


def test_cancelled_partial_requires_exact_fills_and_only_spends_remainder(database):
    schema.ensure_schema(database)
    command = dollars(filled="4", state=S.CANCELLED)
    journal.save_command(database, command)
    blocked = progress.derive(database, projection=projection(), deployment=DEPLOY)
    assert blocked.targets[AAA.security_id] == 4 and "FILL_PRINCIPAL_PENDING" in blocked.blocked[AAA.security_id]
    native_fills(database, command)
    delta = progress.delta(database, projection=projection(), deployment=DEPLOY,
        security_id=AAA.security_id, observation=observation("4"))
    assert delta.notional == 598  # 400 principal + two conservative $1 fee reserves.
    assert delta.quantity is None
    # Re-reading after restart does not restore the original $999 purchase.
    assert progress.delta(database, projection=projection(), deployment=DEPLOY,
        security_id=AAA.security_id, observation=observation("4")) == delta


def test_filled_purchase_retains_actual_shares_and_no_topup(database):
    schema.ensure_schema(database)
    command = dollars(filled="9.99", state=S.FILLED)
    journal.save_command(database, command)
    result = progress.derive(database, projection=projection(), deployment=DEPLOY, require_terminal=True)
    assert result.targets[AAA.security_id] == D("9.99") and not result.budgets
    delta = progress.delta(database, projection=projection(), deployment=DEPLOY,
        security_id=AAA.security_id, observation=observation("9.99"))
    from sentinel.execution.commands import DeltaClass
    assert delta.classification is DeltaClass.NONE


def test_unknown_has_no_reusable_dollars_or_guessed_share_remainder(database):
    schema.ensure_schema(database)
    journal.save_command(database, dollars(state=S.UNKNOWN))
    result = progress.derive(database, projection=projection(), deployment=DEPLOY)
    assert result.blocked == {AAA.security_id: "PURCHASE_COMMAND_UNRESOLVED"}
    with pytest.raises(TargetProjectionRefused, match="unresolved"):
        progress.derive(database, projection=projection(), deployment=DEPLOY, require_terminal=True)


def test_rejection_does_not_repeat_but_retains_budget_for_a_fresh_plan(database):
    schema.ensure_schema(database)
    journal.save_command(database, dollars(state=S.REJECTED))
    result = progress.derive(database, projection=projection(), deployment=DEPLOY, require_terminal=True)
    assert result.budgets[AAA.security_id] == 1000
    assert result.blocked[AAA.security_id] == "PURCHASE_REJECTED_REQUIRES_NEW_PLAN"
    assert not progress.delta(database, projection=projection(), deployment=DEPLOY,
        security_id=AAA.security_id, observation=observation()).is_increase


def test_completed_whole_fallback_keeps_shares_and_discards_unused_dollar_obligation(database):
    schema.ensure_schema(database)
    command = replace(cmd(qty="9", filled="9", state=S.FILLED), filled_average_price=D(100), created_at=NOW)
    journal.save_command(database, command)
    result = progress.derive(database, projection=projection(), deployment=DEPLOY)
    assert result.targets[AAA.security_id] == 9 and not result.budgets
    assert progress.delta(database, projection=projection(), deployment=DEPLOY,
        security_id=AAA.security_id, observation=observation("9")).notional is None


def test_owned_prefix_is_stable_across_later_commands_but_detects_changed_prior_fill(database):
    schema.ensure_schema(database)
    previous = replace(cmd(plan="previous", qty="1", filled="1", state=S.FILLED),
                       filled_average_price=D(100), created_at=NOW)
    journal.save_command(database, previous)
    from types import SimpleNamespace
    plan = SimpleNamespace(plan_id="plan-1")
    saved = progress.baseline(database, deployment=DEPLOY, plan=plan, actions=None)
    journal.save_command(database, dollars())
    assert progress.baseline(database, deployment=DEPLOY, plan=plan, actions=None, saved=saved) == saved
    database.execute("UPDATE sentinel_commands SET filled_quantity=0 WHERE client_key=%s", (previous.client_key,))
    with pytest.raises(TargetProjectionRefused, match="evidence changed"):
        progress.baseline(database, deployment=DEPLOY, plan=plan, actions=None, saved=saved)
