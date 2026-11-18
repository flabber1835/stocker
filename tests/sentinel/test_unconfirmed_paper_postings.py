"""Replay the incident's two native events across plans in private PostgreSQL."""
import asyncio
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from fractions import Fraction
from types import SimpleNamespace

import pytest

from sentinel import binding, dual_plan_authority
from sentinel.execution import broker_cash, journal
from sentinel.execution.contract import BrokerAccountIdentity, BrokerAccountSnapshot, BrokerObservation
from sentinel.execution.states import CommandState, RuntimeState
from sentinel.execution.market_buy_policy import MarketBuyPolicy
from sentinel.execution.plan import ExecutionPlan
from sentinel.paper import cash
import sentinel.paper.cash_postings as cash_postings
from sentinel.paper.model import PaperActivationRefused, PaperRetryableRefused
from tests.sentinel.test_alpaca_boundary_overlay import account_payload, activity_event, sse
from tests.sentinel.test_paper_current_cash_acceptance import ACCOUNT_NUMBER, NOW, conn, pg, selected


@pytest.fixture
def incident(conn, monkeypatch):
    # The unit under test is monetary reconciliation. The callers separately
    # qualify the signed fractional policy, native account binding and plan.
    monkeypatch.setattr(MarketBuyPolicy, "from_env", lambda: MarketBuyPolicy(fractional=True))
    monkeypatch.setattr(dual_plan_authority, "require_current_buy_policy", lambda conn, plan: None)
    dto = binding.require(conn).identity
    ident = BrokerAccountIdentity("alpaca", ACCOUNT_NUMBER)
    obs = BrokerObservation(NOW, account_identity=ident)
    plan = ExecutionPlan("prior", date(2026,8,18), date(2026,8,19), Decimal(1),
        account_cash=Decimal("7064.26"), account_nav=Decimal("50000"), **dto.to_dict())
    journal.adopt_current_plan(conn, plan)
    empty, _ = selected(events="")
    def ingest(broker, clock, **opts):
        return asyncio.run(broker_cash.ingest_account_cash(conn, broker_adapter=broker, broker="alpaca",
            account_id=ACCOUNT_NUMBER, through=clock, **opts))
    start = ingest(empty, NOW)
    broker_cash.record_plan_baseline(conn, plan_id=plan.plan_id, decision_session=plan.decision_session,
                                     activity_state=start)
    div = activity_event(activity_type="DIV", activity_subtype="CDIV", net_amount="6.25")
    fee = activity_event(activity_type="FEE", activity_subtype="CAT", net_amount="-0.01",
                         event_id="01J5R000000000000000000002", ref_id="fee-1")
    broker, _ = selected(events=sse(div)+sse(fee))
    legacy = ingest(broker, NOW+timedelta(hours=1))
    assert legacy.posting_kinds is None
    state = ingest(broker, NOW+timedelta(hours=2), qualify_postings=True)
    assert set(dict(state.posting_kinds).values()) == {"CDIV","FEE"}
    def observe(plan, value, **changes):
        account = BrokerAccountSnapshot(ident, cash=Decimal(value), buying_power=Decimal(value),
            equity=Decimal("50000"), multiplier=Decimal(1), status="ACTIVE")
        return cash.fractional_posting_reserve(conn, plan=plan, deployment=dto, account=account,
            observation=obs, activity_state=state, **changes)
    return plan, state, observe


@pytest.mark.parametrize("later,reserve", [("7064.25","0"), ("7070.51","0.01")])
def test_carries_unconfirmed_refs_and_reserves_fee_until_reflected(conn, incident, later, reserve):
    plan, state, observe = incident
    assert observe(plan, "7064.26") == Decimal("0.01")
    pending = cash_postings.carry_forward(conn, plan_id=plan.plan_id, account_id=ACCOUNT_NUMBER)
    successor = replace(plan, plan_id="next", decision_session=plan.effective_session)
    journal.adopt_current_plan(conn, successor)
    with pytest.raises(PaperActivationRefused, match="superseded"):
        observe(plan, "7064.26")
    base = broker_cash.record_plan_baseline(conn, plan_id=successor.plan_id,
        decision_session=successor.decision_session, activity_state=state, **pending)
    assert len(base.pending_postings) == 2
    assert observe(successor, "7064.26") == Decimal("0.01")
    conn.commit()
    assert observe(successor, later) == Decimal(reserve)
    assert observe(successor, "7070.50") == 0
    assert cash_postings.carry_forward(conn, plan_id=successor.plan_id, account_id=ACCOUNT_NUMBER) == {}
    cash_postings.verify_restored_postings(conn, baseline=base, activity=state, plan=successor,
                                          has_observation=True)
    with pytest.raises(PaperActivationRefused, match="unexplained"):
        observe(successor, "7064.26")


def test_unmatched_cent_unknown_order_and_modified_observation_refuse(conn, incident, monkeypatch):
    plan, state, observe = incident
    with pytest.raises(PaperActivationRefused, match="unexplained"):
        observe(plan, "7064.27")
    with monkeypatch.context() as p:
        p.setattr(journal, "in_flight_commands", lambda *_: [SimpleNamespace(client_key="other")])
        with pytest.raises(PaperActivationRefused, match="unresolved"):
            observe(plan, "7064.26")
    assert observe(plan,"7064.26") == Decimal("0.01")
    conn.execute("UPDATE sentinel_processed_sessions SET state=state || '{\"reserve\":\"0\"}'::jsonb"
                 " WHERE cursor_name=%s", (cash_postings.PREFIX + plan.plan_id,))
    with pytest.raises(PaperActivationRefused, match="contents"):
        observe(plan,"7064.26")


def test_stale_writer_cannot_reverse_a_confirmed_posting(conn, incident, monkeypatch):
    plan, _, observe = incident
    assert observe(plan, "7064.26") == Decimal("0.01")
    reader = cash_postings.read_posting_status
    subject = dict(plan_id=plan.plan_id, account_id=ACCOUNT_NUMBER)
    stale = reader(conn, **subject)
    assert observe(plan, "7070.51") == Decimal("0.01")
    confirmed = reader(conn, **subject)
    replies = iter((stale, confirmed))
    monkeypatch.setattr(cash_postings, "read_posting_status", lambda *a, **kw: next(replies))
    with pytest.raises(PaperActivationRefused, match="concurrently"):
        observe(plan, "7064.26")
    assert reader(conn, **subject) == confirmed


def test_retained_posting_cannot_fall_back_to_a_missing_activity_cursor(conn, incident):
    plan, _, observe = incident
    observe(plan, "7064.26")
    with pytest.raises(PaperActivationRefused, match="retained cash postings"):
        cash.fractional_posting_reserve(conn, plan=plan, deployment=binding.require(conn).identity,
            account=None, observation=None, activity_state=None)


def test_three_crl_fill_cash_rows_are_all_required_for_posting_admission(conn, incident):
    from sentinel.execution.commands import Command
    from sentinel.execution.contract import BrokerInstrument, Side
    from sentinel.execution.identity import CommandIdentity
    plan, _, observe = incident
    price = Decimal("335.82")
    command = Command(CommandIdentity(binding.require(conn).identity, plan.plan_id, "CRL"),
        BrokerInstrument("CRL", "CRL", "owned-crl"), Side.BUY, None,
        state=CommandState.FILLED, broker_order_id="owned-order", notional=Decimal("1337.66"),
        filled_quantity=Decimal("3.983235066"), filled_average_price=price)
    journal.save_command(conn, command)
    fills = tuple(SimpleNamespace(client_key=command.client_key, broker_order_id=command.broker_order_id,
        quantity=Decimal(qty), price=price, filled_at=NOW + timedelta(milliseconds=i),
        activity_id=f"native-{i}", cash_amount=Decimal(amount), side=Side.BUY)
        for i, (qty, amount) in enumerate([("1","-335.82"), ("1.983235066","-666.01"), ("1","-335.82")]))
    assert journal.record_fills(conn, fills) == 3
    assert observe(plan, "5726.61") == Decimal("0.01")
    baseline = broker_cash.load_plan_baseline(conn, plan_id=plan.plan_id)
    state = broker_cash.load_activity_state(conn, broker=plan.broker, account_id=ACCOUNT_NUMBER)
    cash_postings.verify_restored_postings(conn, baseline=baseline, activity=state, plan=plan, has_observation=True)
    # The omitted one-share leg is exactly representable by price times quantity.
    # A reconstructed principal still cannot confirm a native posting.
    conn.execute("DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s",
        (journal.FILL_CASH_PREFIX + journal.fill_fingerprint(fills[0]),))
    with pytest.raises(PaperRetryableRefused, match="explicit signed fill cash"):
        observe(plan, "5726.61")
    with pytest.raises(PaperActivationRefused, match="original signed fill"):
        cash_postings.verify_restored_postings(conn, baseline=baseline, activity=state, plan=plan, has_observation=True)


def test_successor_rejects_changed_predecessor_or_sizing_cash(conn, incident):
    plan, state, observe = incident
    assert observe(plan, "7064.26") == Decimal("0.01")
    carry = cash_postings.carry_forward(conn, plan_id=plan.plan_id, account_id=ACCOUNT_NUMBER)
    successor = replace(plan, plan_id="new", account_cash=Decimal("7064.27"))
    broker_cash.record_plan_baseline(conn, plan_id=successor.plan_id,
        decision_session=successor.decision_session, activity_state=state, **carry)
    with pytest.raises(PaperActivationRefused, match="predecessor"):
        observe(successor, "7064.27")
    conn.execute("DELETE FROM sentinel_processed_sessions WHERE cursor_name=%s",
                 (cash_postings.PREFIX + plan.plan_id,))
    with pytest.raises(PaperActivationRefused, match="predecessor"):
        observe(replace(successor, account_cash=plan.account_cash), "7064.26")


@pytest.mark.parametrize("end_cash", ["7064.26", "7064.25"])
def test_plan_preparation_rechecks_cash_around_complete_book(conn, incident, monkeypatch, end_cash):
    import sentinel.paper.reconciliation_evidence as evidence
    plan, state, _ = incident
    owned = binding.require(conn)
    snapshot = dict(account_payload(), created_at="2026-02-12T00:00:00Z", equity="50000",
        buying_power="7064.25", multiplier="1", status="ACTIVE", trading_blocked=False,
        account_blocked=False, trade_suspended_by_user=False)
    sequence = iter(["7064.26", end_cash])
    broker, http = selected(routes={"/v2/account": lambda _: dict(snapshot, cash=next(sequence))})
    observation = BrokerObservation(NOW, account_identity=BrokerAccountIdentity("alpaca", ACCOUNT_NUMBER))
    rec = SimpleNamespace(clean=True, runtime_state=RuntimeState.RUNNING, observation=observation)
    async def confirm(**kwargs):
        assert kwargs["broker"] is broker and kwargs["informational_current_book"]
        return rec
    monkeypatch.setattr(evidence.reconciliation, "reconcile", confirm)
    def prepare():
        return asyncio.run(cash_postings.prepare(conn, broker=broker, binding=owned, plan=plan,
            rec=rec, account=None, activity=state, actions=None, clock=lambda: state.processed_through))
    if end_cash == "7064.25":
        with pytest.raises(PaperRetryableRefused, match="account endpoint changed"):
            prepare()
        assert cash_postings.read_posting_status(conn, plan_id=plan.plan_id, account_id=ACCOUNT_NUMBER) is None
    else:
        _, account, current, reserve = prepare()
        assert account.cash == Decimal(end_cash) and current == state and reserve == Decimal("0.01")
    assert [call[1] for call in http.calls] == ["/v2/account", "/v2/account"]


def test_ambiguous_attribution_is_fenced_and_removed_debit_reservation_is_caught(conn, incident, monkeypatch):
    with pytest.raises(PaperActivationRefused, match="ambiguous"):
        cash_postings._remaining({"A": Fraction(5), "B": Fraction(5)}, Fraction(5))
    fees = {str(i): Fraction("-0.01") for i in range(50)}
    assert set(cash_postings._remaining(fees, Fraction("-0.50"))) == fees.keys()
    import ast
    import inspect
    source = ast.parse(inspect.getsource(cash_postings._store))
    targets = [n for n in ast.walk(source) if isinstance(n, ast.Assign)
               and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "reserve"]
    assert len(targets) == 1
    targets[0].value = ast.parse('Decimal(0)', mode="eval").body
    namespace = {}
    exec(compile(ast.fix_missing_locations(source), "<removed-fee-reserve>", "exec"),
         vars(cash_postings), namespace)
    monkeypatch.setattr(cash_postings, "_store", namespace["_store"])
    with pytest.raises(AssertionError):
        test_carries_unconfirmed_refs_and_reserves_fee_until_reflected(conn, incident, "7070.51", "0.01")

